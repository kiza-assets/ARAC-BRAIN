"""Agent AUDITEUR — Phase E : gate commit autonome à deux étages.

Phase A : pur heartbeat (sync).
Phase D.0 : stub no-op pour validation du plumbing async + bus.subscribe.
Phase D.2 — la règle : aucun commit ne part sans un verdict explicite.
  - Subscribe `agent_inbox_codex_auditor`
  - Sur réception `agent_message` avec `source_ref.type=commit_proposal` :
      * Audit statique via `agents.lib.commit_audit.audit(...)` (regex secrets,
        paths interdits, sanity files/lignes, branche feature/*).

Deuxième étage LLM cross-fournisseur : un modèle relit ce qu'un autre modèle
a écrit. L'intérêt n'est pas la redondance, c'est l'indépendance des erreurs —
deux instances du même modèle se trompent souvent ensemble.

  Étape 1 inchangée — audit statique fail-fast. Si reject → reject final,
  PAS d'appel LLM (économie API + protection contre payload coûteux).

  Étape 2 NOUVELLE — audit LLM via OpenAI GPT-5.5 (diversité cross-provider :
  developer tourne sur Claude, auditeur sur OpenAI). Charge constitution +
  8 foundings dans le system prompt, JSON output strict (verdict, reasons,
  confidence). En cas d'échec LLM (5xx, timeout, network) : fail-mode
  contrôlé par `ARAC_AUDITOR_LLM_FAIL_MODE` (default `open` → approve).
  Sur 429 : alert Telegram + fail-mode. Sur JSON malformé : reject + atome
  kind=gotcha pour traçabilité.

POST `kind=validation` (approve final) ou `kind=alert` (reject) avec
`audit_source=autonomous_agent_suggest` + `confidence=agent_suggest` +
`source_ref.target_atom_id=<proposal_id>`.

`bus.send` un `agent_message` au developer avec
`source_ref.type=commit_verdict` + verdict_atom_id + verdict.

node_id : `codex-auditor` (cf systemd unit ARAC_NODE_ID).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import signal
import sys
from typing import Any

import httpx

import time

from app.api_token import entetes_api
from agents.lib import bus, commit_audit
from agents.lib.heartbeat import run_heartbeat_loop_async
from agents.lib.llm_auditor import (
    LLMDownException,
    LLMMalformedException,
    RateLimitException,
    audit_curator_atom,
    audit_with_llm,
    should_gate_atom_curator,
)
from agents.lib.log_capture import MissionLogger

logger = logging.getLogger("arac.auditor")

_NODE_ID = "codex-auditor"
_DEVELOPER_NODE_ID = "claude-developer"
_TELEGRAM_NODE_ID = "arac-telegram-bridge"

_DIFF_DELIM = "--- DIFF ---"


def _llm_enabled() -> bool:
    return os.environ.get("ARAC_AUDITOR_LLM_ENABLED", "true").strip().lower() == "true"


def _llm_fail_mode() -> str:
    """`open` (default, approve si LLM down) ou `closed` (reject)."""
    return os.environ.get("ARAC_AUDITOR_LLM_FAIL_MODE", "open").strip().lower()


async def _alert_telegram(message: str) -> None:
    """Envoie un agent_message d'alerte vers arac-telegram-bridge (best-effort).

    Pas de propagation d'erreur : l'audit doit continuer même si Telegram down.
    """
    try:
        await bus.send(
            from_node=_NODE_ID,
            to_node=_TELEGRAM_NODE_ID,
            value=message,
            metadata={"type": "auditor_alert", "severity": "warning"},
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(json.dumps({
            "event": "auditor.alert_telegram_fail",
            "error": type(e).__name__,
            "detail": str(e)[:200],
        }))


async def _post_gotcha_atom(*, mission_id: str, summary: str) -> None:
    """POST kind=gotcha auto (LLM JSON malformé). Best-effort."""
    short_mid = mission_id[:8] if mission_id else "nomid"
    key = f"gotcha-llm-auditor-malformed-{short_mid}-{secrets.token_hex(3)}"
    payload: dict[str, Any] = {
        "kind": "gotcha",
        "scope": "arac-strategie",
        "key": key,
        "value": (
            f"Auditeur LLM a renvoyé un JSON malformé sur mission {mission_id}. "
            f"Détail: {summary}. Action : commit rejeté par sécurité, "
            "investiguer modèle / prompt (cf phase-e-auditor-llm-architecture)."
        ),
        "node_id": _NODE_ID,
        "audit_source": "autonomous_agent_suggest",
        "confidence": "agent_suggest",
        "source_ref": {
            "phase": "E",
            "type": "llm_malformed_gotcha",
            "mission_id": mission_id,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{_api_url()}/v1/atoms", json=payload, headers=entetes_api()
            )
            r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        logger.warning(json.dumps({
            "event": "auditor.gotcha_post_fail",
            "mission_id": mission_id,
            "error": type(e).__name__,
            "detail": str(e)[:200],
        }))


def _setup_logging() -> None:
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def _api_url() -> str:
    return os.environ.get("ARAC_API_URL", "").rstrip("/")


def _parse_proposal_value(value: str) -> str:
    """Extrait le diff du body du commit_proposal (après `--- DIFF ---`)."""
    if _DIFF_DELIM not in value:
        return ""
    return value.split(_DIFF_DELIM, 1)[1].lstrip("\n")


async def _post_verdict_atom(
    *,
    ok: bool,
    proposal_atom_id: str,
    mission_id: str,
    reasons: list[str],
    branch: str | None,
    files: list[str],
) -> dict[str, Any]:
    """POST kind=validation (ok) ou kind=alert (ko). Renvoie le dict atome."""
    kind = "validation" if ok else "alert"
    short_mid = mission_id[:8] if mission_id else "nomid"
    key = f"verdict-{kind}-{short_mid}-{secrets.token_hex(4)}"
    if ok:
        value = (
            f"Verdict APPROVED on commit_proposal {proposal_atom_id} "
            f"(mission {mission_id}). Branch={branch}. Files={len(files)}. "
            f"Static checks passed: branch, paths, files-count, diff-size, secrets-regex. "
            f"LLM stage (Phase E): cf source_ref."
        )
    else:
        value = (
            f"Verdict REJECTED on commit_proposal {proposal_atom_id} "
            f"(mission {mission_id}). Branch={branch}. Files={len(files)}.\n"
            f"Reasons:\n- " + "\n- ".join(reasons)
        )

    payload: dict[str, Any] = {
        "kind": kind,
        "scope": "arac-strategie",
        "key": key,
        "value": value,
        "node_id": _NODE_ID,
        "audit_source": "autonomous_agent_suggest",
        "confidence": "agent_suggest",
        "source_ref": {
            "phase": "D.2",
            "type": "commit_verdict",
            "target_atom_id": proposal_atom_id,
            "mission_id": mission_id,
            "branch": branch,
            "files_changed": files,
            "reasons": reasons if not ok else [],
        },
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            f"{_api_url()}/v1/atoms", json=payload, headers=entetes_api()
        )
        r.raise_for_status()
        return r.json()


async def _post_curator_verdict_rejected_atom(
    *,
    curator_atom: dict[str, Any],
    raw_id: str,
    reasons: list[str],
) -> dict[str, Any]:
    """POST kind=verdict_rejected — extension v0.5 Vague 2 I9 (Q6 ciblé).

    Tracé pour atomes curator STRICT (decision/gotcha/killed) rejetés par
    gate LLM cross-fournisseur. Permet à l'opérateur de voir dans `arac.atoms`
    ce que le curator a tenté de poser et pourquoi l'auditeur a refusé.

    NB schéma : v0.4 ne définit pas formellement le kind `verdict_rejected`
    — il est introduit ici sous le scope `travail/strategie`. À documenter en
    Vague 2 I9 (sera capté par les seeds Vague 3 si stabilisé).
    """
    proposed_kind = curator_atom.get("kind", "?")
    proposed_scope = curator_atom.get("scope", "?")
    proposed_key = curator_atom.get("key", "?")
    short_raw = str(raw_id)[:8] if raw_id else "noraw"
    key = f"verdict-rejected-curator-{proposed_kind}-{short_raw}-{secrets.token_hex(3)}"
    value = (
        f"Auditeur LLM cross-provider (Q6 ciblé v0.5) a rejeté un atome "
        f"curator STRICT (kind={proposed_kind}, scope={proposed_scope}, "
        f"key={proposed_key}, raw_id={raw_id}).\n"
        f"Reasons:\n- " + "\n- ".join(reasons)
    )
    payload: dict[str, Any] = {
        "kind": "verdict_rejected",
        "scope": "arac-strategie",
        "key": key,
        "value": value,
        "node_id": _NODE_ID,
        "audit_source": "autonomous_agent_suggest",
        "confidence": "agent_suggest",
        "source_ref": {
            "phase": "v0.5_vague2_i9",
            "type": "curator_atom_verdict",
            "verdict": "rejected",
            "curator_raw_id": raw_id,
            "proposed_atom": {
                "kind": proposed_kind,
                "scope": proposed_scope,
                "key": proposed_key,
            },
            "reasons": reasons,
        },
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            f"{_api_url()}/v1/atoms", json=payload, headers=entetes_api()
        )
        r.raise_for_status()
        return r.json()


async def _handle_curator_atom_audit_request(atom: dict[str, Any]) -> None:
    """Hook v0.5 Vague 2 I9 (Q6 ciblé) — gate LLM cross-provider ciblé sur
    atomes extraits par curator avec kind STRICT (decision/gotcha/killed).

    Schéma `atom` (bus agent_message) :
        source_ref.type == "curator_atom_audit_request"
        source_ref.curator_raw_id == <raw_id>
        source_ref.proposed_atom == {kind, scope, key, value, tags, ...}

    Flow :
      1. Pré-filtre via `should_gate_atom_curator(proposed)` — skip si non STRICT
         (cohérent Q6 ciblé : pas de gate sur STANDARD/LARGE).
      2. Appelle `audit_curator_atom` → verdict cross-provider OpenAI GPT-5.5.
      3. Si reject → POST atome kind=verdict_rejected + alert Telegram bridge.
      4. Si approve → renvoie agent_message vers curator pour qu'il continue
         son flow (POST atome). Si LLM down → applique fail-mode (open par
         défaut, cohérent v0.4).
    """
    source_ref = atom.get("source_ref") or {}
    proposed = source_ref.get("proposed_atom") or {}
    raw_id = source_ref.get("curator_raw_id") or ""
    reply_to = source_ref.get("reply_to") or "arac-curator"

    # Pré-filtre Q6 ciblé : si pas STRICT, skip (laisser passer).
    if not should_gate_atom_curator(proposed):
        logger.info(json.dumps({
            "event": "auditor.curator_atom_skip_not_strict",
            "raw_id": raw_id,
            "proposed_kind": proposed.get("kind"),
            "proposed_node_id": proposed.get("node_id"),
        }))
        # Renvoie approve direct (pas de gate).
        try:
            await bus.send(
                from_node=_NODE_ID,
                to_node=reply_to,
                value=f"curator_atom_audit approved (skip non-strict): raw={raw_id[:8] if raw_id else '?'}",
                metadata={
                    "type": "curator_atom_verdict",
                    "verdict": "approved",
                    "skip_reason": "not_strict_kind",
                    "curator_raw_id": raw_id,
                },
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(json.dumps({
                "event": "auditor.curator_verdict_send_fail",
                "raw_id": raw_id,
                "error": type(e).__name__,
                "detail": str(e)[:200],
            }))
        return

    fail_mode = _llm_fail_mode()
    verdict = "approved"
    reasons: list[str] = []

    if not _llm_enabled():
        logger.info(json.dumps({
            "event": "auditor.curator_atom_llm_disabled",
            "raw_id": raw_id,
            "kind": proposed.get("kind"),
        }))
    else:
        try:
            llm_result = await audit_curator_atom(atom=proposed)
            if llm_result["verdict"] == "reject":
                verdict = "rejected"
                reasons = [f"llm: {r}" for r in llm_result["reasons"]]
                if not reasons:
                    reasons = ["llm: reject sans raison fournie"]
            logger.info(json.dumps({
                "event": "auditor.curator_atom_llm_done",
                "raw_id": raw_id,
                "kind": proposed.get("kind"),
                "verdict": llm_result["verdict"],
                "confidence": llm_result["confidence"],
            }))
        except RateLimitException as e:
            logger.warning(json.dumps({
                "event": "auditor.curator_atom_llm_rate_limit",
                "raw_id": raw_id,
                "fail_mode": fail_mode,
                "detail": str(e)[:200],
            }))
            await _alert_telegram(
                f"Audit LLM curator rate-limited raw={raw_id[:8] if raw_id else '?'} "
                f"(fail_mode={fail_mode})"
            )
            if fail_mode == "closed":
                verdict = "rejected"
                reasons = ["llm_rate_limit_fail_closed"]
        except LLMDownException as e:
            logger.warning(json.dumps({
                "event": "auditor.curator_atom_llm_down",
                "raw_id": raw_id,
                "fail_mode": fail_mode,
                "error": type(e).__name__,
                "detail": str(e)[:200],
            }))
            if fail_mode == "closed":
                verdict = "rejected"
                reasons = [f"llm_down: {str(e)[:160]}"]
        except LLMMalformedException as e:
            logger.error(json.dumps({
                "event": "auditor.curator_atom_llm_malformed",
                "raw_id": raw_id,
                "detail": str(e)[:200],
            }))
            verdict = "rejected"
            reasons = ["llm_malformed_json"]
        except Exception as e:  # noqa: BLE001
            logger.error(json.dumps({
                "event": "auditor.curator_atom_llm_unexpected",
                "raw_id": raw_id,
                "fail_mode": fail_mode,
                "error": type(e).__name__,
                "detail": str(e)[:200],
            }))
            if fail_mode == "closed":
                verdict = "rejected"
                reasons = [f"llm_unexpected: {type(e).__name__}"]

    if verdict == "rejected":
        # POST atome verdict_rejected (traçabilité opérateur) + alerte.
        try:
            await _post_curator_verdict_rejected_atom(
                curator_atom=proposed,
                raw_id=raw_id,
                reasons=reasons,
            )
        except Exception as e:  # noqa: BLE001
            logger.error(json.dumps({
                "event": "auditor.curator_verdict_post_fail",
                "raw_id": raw_id,
                "error": type(e).__name__,
                "detail": str(e)[:200],
            }))
        await _alert_telegram(
            f"Auditeur LLM a REJETÉ atome curator STRICT raw={raw_id[:8] if raw_id else '?'} "
            f"kind={proposed.get('kind', '?')}. Reasons: {'; '.join(reasons[:3])}"
        )

    # Notifie le curator du verdict.
    try:
        await bus.send(
            from_node=_NODE_ID,
            to_node=reply_to,
            value=(
                f"curator_atom_audit {verdict}: raw={raw_id[:8] if raw_id else '?'} "
                f"kind={proposed.get('kind', '?')}"
            ),
            metadata={
                "type": "curator_atom_verdict",
                "verdict": verdict,
                "curator_raw_id": raw_id,
                "reasons": reasons,
                "proposed_kind": proposed.get("kind"),
                "proposed_scope": proposed.get("scope"),
            },
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(json.dumps({
            "event": "auditor.curator_verdict_send_fail",
            "raw_id": raw_id,
            "error": type(e).__name__,
            "detail": str(e)[:200],
        }))


async def _handle_incoming(atom: dict[str, Any]) -> None:
    """Handler bus auditor — Phase D.2 + v0.5 Vague 2 I9 (Q6 ciblé).

    - Si l'atome a `source_ref.type == 'commit_proposal'` → audit + verdict.
    - Si l'atome a `source_ref.type == 'curator_atom_audit_request'` →
      gate LLM ciblé curator (Q6, extension v0.5 Vague 2 I9).
    - Sinon → log et no-op.
    """
    source_ref = atom.get("source_ref") or {}
    msg_type = source_ref.get("type")

    if msg_type == "curator_atom_audit_request":
        await _handle_curator_atom_audit_request(atom)
        return

    if msg_type != "commit_proposal":
        logger.info(json.dumps({
            "event": "auditor.incoming_ignored",
            "atom_id": atom.get("id"),
            "type": msg_type,
            "from": source_ref.get("from"),
        }))
        return

    proposal_atom_id = atom.get("id") or "?"
    mission_id = source_ref.get("mission_id") or ""
    branch = source_ref.get("branch")
    files = list(source_ref.get("files_changed") or [])
    reply_chat_id = source_ref.get("reply_chat_id")
    diff_text = _parse_proposal_value(atom.get("value") or "")

    logger.info(json.dumps({
        "event": "auditor.proposal_received",
        "proposal_atom_id": proposal_atom_id,
        "mission_id": mission_id,
        "branch": branch,
        "files_count": len(files),
        "diff_bytes": len(diff_text),
    }))

    # Bloc 9a (D.4) : ouvre transcript en mode append pour cette mission.
    # Chemin déterministe : $ARAC_HOME/logs/agents/{mission_id}.jsonl
    mission_transcript: MissionLogger | None = None
    audit_start = time.monotonic()
    if mission_id:
        try:
            mission_transcript = MissionLogger(mission_id)
            mission_transcript.write_event(
                "auditor.verdict_started",
                agent=_NODE_ID,
                proposal_atom_id=proposal_atom_id,
                diff_bytes=len(diff_text),
                files_count=len(files),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(json.dumps({
                "event": "auditor.transcript_open_fail",
                "mission_id": mission_id,
                "err": str(e)[:200],
            }))
            mission_transcript = None

    # ------------------------------------------------------------------
    # Étape 1 — audit statique (fail-fast, déterministe, pas d'API)
    # ------------------------------------------------------------------
    result = commit_audit.audit(diff_text=diff_text, files=files, branch=branch)

    static_duration_sec = time.monotonic() - audit_start
    logger.info(json.dumps({
        "event": "auditor.static_done",
        "proposal_atom_id": proposal_atom_id,
        "mission_id": mission_id,
        "ok": result.ok,
        "reasons_count": len(result.reasons),
        "reasons": result.reasons[:5],
        "duration_sec": round(static_duration_sec, 3),
    }))

    # ------------------------------------------------------------------
    # Étape 2 — audit LLM cross-provider (uniquement si étape 1 a passé,
    # et seulement si activé). Phase E — cf decision phase-e-auditor-
    # llm-architecture-2026-05-22.
    # ------------------------------------------------------------------
    llm_called = False
    llm_verdict: str | None = None
    llm_confidence: float | None = None
    if result.ok and _llm_enabled():
        llm_called = True
        llm_start = time.monotonic()
        fail_mode = _llm_fail_mode()
        try:
            llm_result = await audit_with_llm(
                diff=diff_text,
                branch=branch,
                files=files,
                mission_id=mission_id,
                node_id=_NODE_ID,
            )
            llm_verdict = llm_result["verdict"]
            llm_confidence = llm_result["confidence"]
            logger.info(json.dumps({
                "event": "auditor.llm_done",
                "mission_id": mission_id,
                "verdict": llm_verdict,
                "confidence": llm_confidence,
                "duration_sec": round(time.monotonic() - llm_start, 3),
            }))
            if llm_verdict == "reject":
                result.ok = False
                for reason in llm_result["reasons"]:
                    result.reasons.append(f"llm: {reason}")
                if not llm_result["reasons"]:
                    result.reasons.append("llm: reject sans raison fournie")
        except RateLimitException as e:
            logger.warning(json.dumps({
                "event": "auditor.llm_rate_limit",
                "mission_id": mission_id,
                "fail_mode": fail_mode,
                "detail": str(e)[:200],
            }))
            await _alert_telegram(
                f"Audit LLM rate-limited mission {mission_id[:8]} "
                f"(fail_mode={fail_mode})"
            )
            if fail_mode == "closed":
                result.ok = False
                result.reasons.append("llm_rate_limit_fail_closed")
            # sinon fail-open : on garde result.ok tel quel (approve)
        except LLMDownException as e:
            logger.warning(json.dumps({
                "event": "auditor.llm_down",
                "mission_id": mission_id,
                "fail_mode": fail_mode,
                "error": type(e).__name__,
                "detail": str(e)[:200],
            }))
            if fail_mode == "closed":
                result.ok = False
                result.reasons.append(f"llm_down: {str(e)[:160]}")
            # sinon fail-open : continue vers approve
        except LLMMalformedException as e:
            logger.error(json.dumps({
                "event": "auditor.llm_malformed",
                "mission_id": mission_id,
                "detail": str(e)[:200],
            }))
            result.ok = False
            result.reasons.append("llm_malformed_json")
            await _post_gotcha_atom(
                mission_id=mission_id,
                summary=str(e)[:200],
            )
        except Exception as e:  # noqa: BLE001
            # Filet de sécurité : toute exception inattendue applique fail-mode.
            logger.error(json.dumps({
                "event": "auditor.llm_unexpected_exception",
                "mission_id": mission_id,
                "fail_mode": fail_mode,
                "error": type(e).__name__,
                "detail": str(e)[:200],
            }))
            if fail_mode == "closed":
                result.ok = False
                result.reasons.append(f"llm_unexpected: {type(e).__name__}")

    audit_duration_sec = time.monotonic() - audit_start
    logger.info(json.dumps({
        "event": "auditor.audit_done",
        "proposal_atom_id": proposal_atom_id,
        "mission_id": mission_id,
        "ok": result.ok,
        "reasons_count": len(result.reasons),
        "reasons": result.reasons[:5],
        "llm_called": llm_called,
        "llm_verdict": llm_verdict,
        "llm_confidence": llm_confidence,
        "duration_sec": round(audit_duration_sec, 3),
    }))

    try:
        verdict_atom = await _post_verdict_atom(
            ok=result.ok,
            proposal_atom_id=proposal_atom_id,
            mission_id=mission_id,
            reasons=result.reasons,
            branch=branch,
            files=files,
        )
        verdict_atom_id = verdict_atom["id"]
    except Exception as e:  # noqa: BLE001
        logger.error(json.dumps({
            "event": "auditor.verdict_post_fail",
            "proposal_atom_id": proposal_atom_id,
            "error": type(e).__name__,
            "detail": str(e)[:200],
        }))
        verdict_atom_id = "post-failed"

    if mission_transcript is not None:
        try:
            mission_transcript.write_event(
                "auditor.verdict_done",
                verdict_atom_id=verdict_atom_id,
                verdict=("approved" if result.ok else "rejected"),
                reasons=result.reasons,
                audit_duration_sec=audit_duration_sec,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(json.dumps({
                "event": "auditor.transcript_write_fail",
                "mission_id": mission_id,
                "err": str(e)[:200],
            }))
        # NB: pas de close() ici — le developer fermera le transcript dans
        # mission.end.

    verdict_label = "approved" if result.ok else "rejected"
    short_reasons = "; ".join(result.reasons[:3]) if result.reasons else ""
    summary = (
        f"verdict={verdict_label} mission={mission_id[:8] or '?'} "
        f"proposal={proposal_atom_id[:8]}"
        + (f" reasons: {short_reasons}" if short_reasons else "")
    )

    try:
        await bus.send(
            from_node=_NODE_ID,
            to_node=_DEVELOPER_NODE_ID,
            value=summary,
            metadata={
                "type": "commit_verdict",
                "verdict": verdict_label,
                "mission_id": mission_id,
                "proposal_atom_id": proposal_atom_id,
                "verdict_atom_id": verdict_atom_id,
                "reasons": result.reasons,
                "reply_chat_id": reply_chat_id,
                "branch": branch,
            },
        )
        logger.info(json.dumps({
            "event": "auditor.verdict_sent",
            "mission_id": mission_id,
            "verdict": verdict_label,
            "verdict_atom_id": verdict_atom_id,
        }))
    except Exception as e:  # noqa: BLE001
        logger.error(json.dumps({
            "event": "auditor.verdict_send_fail",
            "mission_id": mission_id,
            "error": type(e).__name__,
            "detail": str(e)[:200],
        }))


async def amain() -> int:
    _setup_logging()
    logger.info(json.dumps({
        "event": "boot.ok",
        "node_id": _NODE_ID,
        "phase": "E",
        "mode": "async + bus subscribe + commit_audit gate (static + LLM)",
        "llm_enabled": _llm_enabled(),
        "llm_fail_mode": _llm_fail_mode(),
    }))

    stop_event = asyncio.Event()

    tasks = [
        asyncio.create_task(run_heartbeat_loop_async(stop_event=stop_event), name="heartbeat"),
        asyncio.create_task(
            bus.subscribe(_NODE_ID, _handle_incoming, stop_event=stop_event),
            name="bus_subscribe",
        ),
    ]

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info(json.dumps({"event": "shutdown.clean", "node_id": _NODE_ID}))
    return 0


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    sys.exit(main())
