"""Agent DÉVELOPPEUR — Phase D.2 : exécute missions + gate auditor avant commit.

Phase A : pur heartbeat (sync).
Phase D.0 plumbing : async + bus.subscribe (handler stub).
Phase D.1 MVP : execute claude CLI subprocess, POST delivery atome, relais.
Phase D.2 — RIEN NE PART SANS RELECTURE : ce que cet agent écrit passe par
l'auditeur avant d'être committé.
  - Post-subprocess, si `git status --porcelain` non vide :
      * POST `agent_message` to=`codex-auditor` (source_ref.type=commit_proposal
        + diff dans value après marqueur `--- DIFF ---`)
      * Attend verdict via map `_pending_verdicts[mission_id] -> Future`,
        timeout 60s.
      * Si verdict approved → `git add -A && git commit && git push origin`.
      * Si verdict rejected ou timeout → `git stash push -u`.
  - POST delivery atome (kind=delivery) + send agent_message summary à orchestrator
    (relais Telegram).
  - Le subscribe handler route maintenant par `source_ref.type` :
      * `commit_verdict` → set future result pour le mission_id (pas exécution)
      * sinon avec `mission_id` présent → flux mission normal D.1

NOTE Phase D.5 vague 2 (2026-05-22) : le kind=delivery est désormais disponible
(migration 0004 a élargi la whitelist à 19 kinds + ajouté Kind.DELIVERY dans
app/schemas/kind.py). Le POST utilise donc kind="delivery" + key=delivery-mission-*
(la key reste préfixée pour conserver la sémantique de regroupement mission).
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

from app.api_token import entetes_api
from agents.developer import push_guard
from agents.lib import bus, git_ops
from agents.lib.claude_cli import run_claude_subprocess, DEFAULT_TIMEOUT_SEC
from agents.lib.heartbeat import run_heartbeat_loop_async
from agents.lib.log_capture import MissionLogger

logger = logging.getLogger("arac.developer")

_NODE_ID = "claude-developer"
_ORCHESTRATOR_NODE_ID = "claude-orchestrator"
_AUDITOR_NODE_ID = "codex-auditor"

_VERDICT_TIMEOUT_SEC = 60.0

# Map mission_id -> Future qui sera réglée à l'arrivée du commit_verdict.
# Gardée module-level pour permettre au handler subscribe de la résoudre depuis
# n'importe quelle invocation (un seul event loop, pas besoin de Lock).
_pending_verdicts: dict[str, asyncio.Future[dict[str, Any]]] = {}


def _setup_logging() -> None:
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def _api_url() -> str:
    return os.environ.get("ARAC_API_URL", "").rstrip("/")


# ---------------------------------------------------------------------------
# Delivery state + summary
# ---------------------------------------------------------------------------


async def _post_delivery(
    *,
    mission_id: str,
    prompt: str,
    result: dict[str, Any],
    sha_before: str | None,
    sha_after: str | None,
    branch: str | None,
    verdict: str | None,
    verdict_atom_id: str | None,
    proposal_atom_id: str | None,
    transcript_path: str | None = None,
) -> dict[str, Any]:
    """Bloc 9a (D.4) : capture intégrale dans transcript JSONL → l'atome
    delivery garde des résumés courts (préservation table atoms) mais le full
    vit dans `transcript_path` référencé en source_ref.
    """
    key = f"delivery-mission-{mission_id[:8]}-{secrets.token_hex(4)}"
    stdout_summary = result.get("stdout_summary") or result.get("stdout", "")[:500]
    stderr_summary = result.get("stderr_summary") or result.get("stderr", "")[:500]
    body = (
        f"Mission delivery for {mission_id}.\n"
        f"Prompt: {prompt[:2000]}\n"
        f"ok={result['ok']} exit_code={result['exit_code']} "
        f"duration_sec={result['duration_sec']} timed_out={result['timed_out']}\n"
        f"branch={branch} sha_before={sha_before} sha_after={sha_after}\n"
        f"verdict={verdict} proposal={proposal_atom_id} verdict_atom={verdict_atom_id}\n"
        f"transcript={transcript_path or 'n/a'} "
        f"stdout_bytes={result.get('stdout_bytes', len(result.get('stdout','')))} "
        f"stderr_bytes={result.get('stderr_bytes', len(result.get('stderr','')))}\n"
        f"--- STDOUT (summary 500c, full in transcript) ---\n{stdout_summary}\n"
        f"--- STDERR (summary 500c, full in transcript) ---\n{stderr_summary}"
    )
    payload = {
        "kind": "delivery",
        "scope": "arac-strategie",
        "key": key,
        "value": body,
        "node_id": _NODE_ID,
        "source_ref": {
            "mission_id": mission_id,
            "type": "delivery",
            "phase": "D.4",
            "branch": branch,
            "sha_before": sha_before,
            "sha_after": sha_after,
            "verdict": verdict,
            "verdict_atom_id": verdict_atom_id,
            "proposal_atom_id": proposal_atom_id,
            "transcript_path": transcript_path,
            "stdout_bytes": result.get("stdout_bytes"),
            "stderr_bytes": result.get("stderr_bytes"),
        },
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            f"{_api_url()}/v1/atoms", json=payload, headers=entetes_api()
        )
        r.raise_for_status()
        return r.json()


async def _post_gotcha_atom(
    *,
    mission_id: str,
    transcript_path: str | None,
    trigger: str,
    reason: str,
) -> dict[str, Any]:
    """Bloc 9a §9 : post-mortem auto. POST kind=gotcha sur échec mission.

    Trigger : `rejected` (auditor refuse), `timeout` (audit timeout ou subprocess
    timeout), `subprocess_fail` (exit_code != 0).
    """
    short_mid = mission_id[:8] if mission_id else "nomid"
    key = f"gotcha-mission-{short_mid}-2026-05-22-{secrets.token_hex(3)}"
    value = (
        f"Échec mission {mission_id}: {reason}. "
        f"Transcript: {transcript_path or 'n/a'}"
    )
    payload = {
        "kind": "gotcha",
        "scope": "automations",
        "key": key,
        "value": value,
        "node_id": _NODE_ID,
        "rationale": (
            "Post-mortem auto v0.4 Bloc 9 — extrait automatique sur "
            f"trigger={trigger}. Transcript intégral disponible 90j."
        ),
        "confidence": "producer",
        "tags": ["post-mortem", "v0.4", "auto", trigger],
        "source_ref": {
            "mission_id": mission_id,
            "transcript_path": transcript_path,
            "trigger": trigger,
            "phase": "D.4",
        },
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            f"{_api_url()}/v1/atoms", json=payload, headers=entetes_api()
        )
        r.raise_for_status()
        return r.json()


def _build_summary(
    *,
    mission_id: str,
    result: dict[str, Any],
    sha_before: str | None,
    sha_after: str | None,
    branch: str | None,
    delivery_id: str,
    verdict: str | None,
    verdict_reasons: list[str] | None,
) -> str:
    short_mid = mission_id[:8]
    duration = result["duration_sec"]
    short_did = delivery_id[:8]

    if result["timed_out"]:
        return (
            f"⏱️ Mission {short_mid} TIMEOUT ({DEFAULT_TIMEOUT_SEC}s). "
            f"Delivery {short_did}."
        )
    if not result["ok"]:
        return (
            f"❌ Mission {short_mid} échec (exit={result['exit_code']}, {duration}s). "
            f"Delivery {short_did}."
        )

    if verdict == "approved" and sha_after and sha_after != sha_before:
        return (
            f"✅ Mission {short_mid} done ({duration}s). "
            f"Commit {sha_after} sur {branch} (auditor approved). "
            f"Delivery {short_did}."
        )
    if verdict == "rejected":
        why = "; ".join((verdict_reasons or [])[:3])
        return (
            f"🛑 Mission {short_mid} done ({duration}s) mais commit REFUSÉ par auditor. "
            f"Changements stash. Reasons: {why or 'see verdict atom'}. "
            f"Delivery {short_did}."
        )
    if verdict == "timeout":
        return (
            f"⏱️ Mission {short_mid} done ({duration}s), audit TIMEOUT — changements stash. "
            f"Delivery {short_did}."
        )
    # Cas no_changes (fast-path) ou autre
    if sha_after:
        return (
            f"✅ Mission {short_mid} done ({duration}s). HEAD inchangé ({sha_after}, "
            f"pas de changement détecté). Delivery {short_did}."
        )
    return f"✅ Mission {short_mid} done ({duration}s). Delivery {short_did}."


# ---------------------------------------------------------------------------
# Gate auditor : propose, attend verdict, commit ou stash
# ---------------------------------------------------------------------------


def _build_commit_message(mission_id: str, prompt: str) -> str:
    """Bloc 9a (D.4) : prompt intégral dans commit message (ex tronc 300c).
    Plafond commit lui-même cap à 8 KB (au-delà git refuse pas mais lisibilité
    nulle ; le full vit dans le transcript JSONL).
    """
    head = f"auto: mission {mission_id[:8]} via developer agent"
    body = (
        f"\n\nMission {mission_id}\n"
        f"Prompt: {prompt[:8000]}\n\n"
        "Verdict auditor (codex-auditor) static-audit: approved.\n\n"
        "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
    )
    return head + body


async def _post_commit_proposal(
    *,
    mission_id: str,
    branch: str | None,
    files: list[str],
    diff_text: str,
    diff_stat: str,
    reply_chat_id: int | None,
) -> dict[str, Any]:
    """POST agent_message vers codex-auditor avec diff dans value."""
    short_mid = mission_id[:8]
    key = f"msg-{_NODE_ID}-to-{_AUDITOR_NODE_ID}-{secrets.token_hex(4)}"
    body = (
        f"COMMIT_PROPOSAL mission={mission_id} branch={branch}\n"
        f"files ({len(files)}):\n  " + "\n  ".join(files) + "\n\n"
        f"--- STAT ---\n{diff_stat}\n"
        f"--- DIFF ---\n{diff_text}"
    )
    payload = {
        "kind": "agent_message",
        "scope": "automations",
        "key": key,
        "value": body,
        "node_id": _NODE_ID,
        "source_ref": {
            "to": _AUDITOR_NODE_ID,
            "from": _NODE_ID,
            "type": "commit_proposal",
            "mission_id": mission_id,
            "branch": branch,
            "files_changed": files,
            "reply_chat_id": reply_chat_id,
            "phase": "D.2",
        },
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            f"{_api_url()}/v1/atoms", json=payload, headers=entetes_api()
        )
        r.raise_for_status()
        return r.json()


async def _gate_and_commit(
    *,
    mission_id: str,
    prompt: str,
    branch: str | None,
    reply_chat_id: int | None,
    mission_logger: MissionLogger | None = None,
) -> dict[str, Any]:
    """Flux gate : propose, attend, commit ou stash.

    Retourne un dict avec :
      verdict: 'approved'|'rejected'|'timeout'|'no_changes'|'error'
      verdict_atom_id: str|None
      proposal_atom_id: str|None
      reasons: list[str]
      sha_after: str|None  (HEAD final, après commit ou stash)
    """
    files = await git_ops.status_porcelain()
    if not files:
        return {
            "verdict": "no_changes",
            "verdict_atom_id": None,
            "proposal_atom_id": None,
            "reasons": [],
            "sha_after": await git_ops.head_sha(),
        }

    # CRITIQUE : intent-to-add les untracked AVANT diff. Sinon les fichiers
    # nouveaux (cas typique des missions claude qui font Write tool) sont
    # absents du diff → audit gate approuve un diff vide à tort.
    # Bug découvert mission bab22208 (faux AKIA approuvé).
    intent_added = await git_ops.intent_to_add_untracked()
    if intent_added:
        logger.info(json.dumps({
            "event": "developer.intent_to_add",
            "mission_id": mission_id,
            "files_count": len(intent_added),
        }))

    diff_text = await git_ops.diff_text()
    diff_stat = await git_ops.diff_stat()

    # Future enregistré AVANT POST pour éviter une race avec un verdict très rapide.
    loop = asyncio.get_running_loop()
    fut: asyncio.Future[dict[str, Any]] = loop.create_future()
    _pending_verdicts[mission_id] = fut

    proposal_atom_id: str | None = None
    try:
        proposal = await _post_commit_proposal(
            mission_id=mission_id,
            branch=branch,
            files=files,
            diff_text=diff_text,
            diff_stat=diff_stat,
            reply_chat_id=reply_chat_id,
        )
        proposal_atom_id = proposal["id"]
        logger.info(json.dumps({
            "event": "developer.proposal_sent",
            "mission_id": mission_id,
            "proposal_atom_id": proposal_atom_id,
            "files_count": len(files),
            "diff_bytes": len(diff_text),
        }))
        if mission_logger is not None:
            mission_logger.write_event(
                "audit.proposal_posted",
                proposal_atom_id=proposal_atom_id,
                files=files,
                diff_bytes=len(diff_text),
                diff_stat=diff_stat,
            )
    except Exception as e:  # noqa: BLE001
        _pending_verdicts.pop(mission_id, None)
        logger.error(json.dumps({
            "event": "developer.proposal_post_fail",
            "mission_id": mission_id,
            "error": type(e).__name__,
            "detail": str(e)[:200],
        }))
        await _rollback_via_stash(
            mission_id, reason="proposal_post_fail", mission_logger=mission_logger
        )
        return {
            "verdict": "error",
            "verdict_atom_id": None,
            "proposal_atom_id": None,
            "reasons": [f"proposal post failed: {type(e).__name__}"],
            "sha_after": await git_ops.head_sha(),
        }

    # Wait verdict
    try:
        verdict_msg = await asyncio.wait_for(fut, timeout=_VERDICT_TIMEOUT_SEC)
    except asyncio.TimeoutError:
        _pending_verdicts.pop(mission_id, None)
        logger.error(json.dumps({
            "event": "developer.verdict_timeout",
            "mission_id": mission_id,
            "proposal_atom_id": proposal_atom_id,
            "timeout_sec": _VERDICT_TIMEOUT_SEC,
        }))
        await _rollback_via_stash(
            mission_id, reason="verdict_timeout", mission_logger=mission_logger
        )
        return {
            "verdict": "timeout",
            "verdict_atom_id": None,
            "proposal_atom_id": proposal_atom_id,
            "reasons": [f"no verdict within {_VERDICT_TIMEOUT_SEC}s"],
            "sha_after": await git_ops.head_sha(),
        }

    verdict_label = verdict_msg.get("verdict")
    verdict_atom_id = verdict_msg.get("verdict_atom_id")
    reasons = list(verdict_msg.get("reasons") or [])

    if mission_logger is not None:
        mission_logger.write_event(
            "audit.verdict_received",
            verdict_atom_id=verdict_atom_id,
            verdict=verdict_label,
            reasons=reasons,
        )

    if verdict_label == "approved":
        sha_after = await _commit_and_push(
            mission_id, prompt, branch,
            files=files, diff_text=diff_text, verdict=verdict_label,
            mission_logger=mission_logger,
        )
        return {
            "verdict": "approved",
            "verdict_atom_id": verdict_atom_id,
            "proposal_atom_id": proposal_atom_id,
            "reasons": [],
            "sha_after": sha_after,
        }

    # rejected (ou inconnu)
    await _rollback_via_stash(
        mission_id,
        reason=f"verdict_{verdict_label or 'unknown'}",
        mission_logger=mission_logger,
    )
    return {
        "verdict": verdict_label or "rejected",
        "verdict_atom_id": verdict_atom_id,
        "proposal_atom_id": proposal_atom_id,
        "reasons": reasons,
        "sha_after": await git_ops.head_sha(),
    }


async def _commit_and_push(
    mission_id: str,
    prompt: str,
    branch: str | None,
    *,
    files: list[str],
    diff_text: str,
    verdict: str = "approved",
    mission_logger: MissionLogger | None = None,
) -> str | None:
    # --- GARDE-FOU E.2 (fail-closed) ---------------------------------------
    # Audit statique local indépendant + scope + push off par défaut. Si le
    # garde-fou refuse, on NE COMMITE PAS : rollback via stash (non destructif).
    #
    # IMPORTANT : on audite le diff COMPLET (non tronqué), pas le `diff_text`
    # reçu (qui peut être tronqué à 50 KB pour le transport vers l'auditeur
    # distant). Le fichier COMPLET sera committé -> un secret au-delà de 50 KB
    # doit quand même être détecté (sinon faille fail-OPEN par troncature).
    full_diff = await git_ops.diff_text(max_bytes=5_000_000)
    audit_result = push_guard.run_local_audit(full_diff or diff_text, files, branch)
    decision = push_guard.evaluate_commit_guard(
        verdict=verdict,
        audit_result=audit_result,
        changed_files=files,
        allowed_paths=push_guard.configured_allowed_paths(),
        push_flag=push_guard.push_enabled(),
    )
    if not decision.allow_commit:
        logger.error(json.dumps({
            "event": "developer.commit_refused",
            "mission_id": mission_id,
            "refusals": decision.refusals[:20],
        }))
        if mission_logger is not None:
            mission_logger.write_event("commit_refused", refusals=decision.refusals[:20])
        await _rollback_via_stash(
            mission_id, reason="guard_refused", mission_logger=mission_logger
        )
        return await git_ops.head_sha()

    sha_before = await git_ops.head_sha()
    # Stage UNIQUEMENT les fichiers du diff audité (JAMAIS `git add -A`).
    add_r = await git_ops.add_paths(files)
    if not add_r["ok"]:
        logger.error(json.dumps({
            "event": "developer.git_add_fail",
            "mission_id": mission_id,
            "stderr": add_r["stderr"][:300],
        }))
        return await git_ops.head_sha()

    commit_msg = _build_commit_message(mission_id, prompt)
    commit_r = await git_ops.commit(commit_msg)
    if not commit_r["ok"]:
        logger.error(json.dumps({
            "event": "developer.git_commit_fail",
            "mission_id": mission_id,
            "stderr": commit_r["stderr"][:300],
            "stdout": commit_r["stdout"][:300],
        }))
        return await git_ops.head_sha()

    sha_after = await git_ops.head_sha()
    logger.info(json.dumps({
        "event": "developer.git_commit_ok",
        "mission_id": mission_id,
        "sha_after": sha_after,
        "branch": branch,
    }))
    if mission_logger is not None:
        mission_logger.write_event(
            "commit",
            sha_before=sha_before,
            sha_after=sha_after,
            branch=branch,
            commit_msg=commit_msg[:1024],
        )

    if branch and decision.allow_push:
        push_r = await git_ops.push(branch)
        logger.info(json.dumps({
            "event": "developer.git_push",
            "mission_id": mission_id,
            "branch": branch,
            "ok": push_r["ok"],
            "stderr_preview": push_r["stderr"][:200],
        }))
        if mission_logger is not None:
            mission_logger.write_event(
                "push",
                branch=branch,
                sha=sha_after,
                ok=push_r["ok"],
                stderr=push_r.get("stderr", ""),
            )
    elif branch:
        # Commit fait, mais push DÉSACTIVÉ (ARAC_DEVELOPER_PUSH_ENABLED!=true).
        # Comportement par défaut sûr : le commit local reste, l'opérateur pousse.
        logger.info(json.dumps({
            "event": "developer.push_skipped",
            "mission_id": mission_id,
            "branch": branch,
            "reason": "push_disabled_default",
            "sha": sha_after,
        }))
        if mission_logger is not None:
            mission_logger.write_event(
                "push_skipped", branch=branch, sha=sha_after,
                reason="push_disabled_default",
            )
    return sha_after


async def _rollback_via_stash(
    mission_id: str,
    reason: str,
    *,
    mission_logger: MissionLogger | None = None,
) -> None:
    msg = f"d2-rollback-{mission_id[:8]}-{reason}"
    r = await git_ops.stash_push(msg)
    logger.info(json.dumps({
        "event": "developer.stash_rollback",
        "mission_id": mission_id,
        "reason": reason,
        "stash_ok": r["ok"],
        "stash_stderr": r["stderr"][:200],
    }))
    if mission_logger is not None:
        mission_logger.write_event(
            "stash_rollback",
            reason=reason,
            stash_ref=msg,
            stash_ok=r["ok"],
        )


# ---------------------------------------------------------------------------
# Bus handler — route par source_ref.type
# ---------------------------------------------------------------------------


async def _handle_incoming(atom: dict[str, Any]) -> None:
    """Router rapide depuis bus.subscribe.

    IMPORTANT : ce handler doit revenir vite. Le subscribe loop appelle
    `await handler(atom)` séquentiellement — si on bloque ici sur
    `_gate_and_commit` (qui attend un verdict via Future), le subscribe ne
    peut PAS recevoir le verdict suivant → dead-lock.
    Solution : on délègue le traitement long de la mission à
    `asyncio.create_task(...)` et le handler revient immédiatement après.
    Pour les commit_verdict (courts, juste set_result sur future), pas
    besoin de create_task.
    """
    source_ref = atom.get("source_ref") or {}
    msg_type = source_ref.get("type")
    mission_id = source_ref.get("mission_id")
    sender = source_ref.get("from", "?")

    # Route 1 : verdict du auditor — set future (synchrone, court)
    if msg_type == "commit_verdict":
        fut = _pending_verdicts.pop(mission_id or "", None)
        if fut and not fut.done():
            fut.set_result({
                "verdict": source_ref.get("verdict"),
                "verdict_atom_id": source_ref.get("verdict_atom_id"),
                "proposal_atom_id": source_ref.get("proposal_atom_id"),
                "reasons": source_ref.get("reasons") or [],
            })
            logger.info(json.dumps({
                "event": "developer.verdict_received",
                "mission_id": mission_id,
                "verdict": source_ref.get("verdict"),
                "verdict_atom_id": source_ref.get("verdict_atom_id"),
            }))
        else:
            logger.info(json.dumps({
                "event": "developer.verdict_orphan",
                "mission_id": mission_id,
                "atom_id": atom.get("id"),
                "note": "no pending future (timeout or unknown mission)",
            }))
        return

    # Route 2 : mission depuis orchestrator — délégation à une task
    if not mission_id:
        logger.info(json.dumps({
            "event": "developer.ignored_no_mission_id",
            "atom_id": atom.get("id"),
            "from": sender,
        }))
        return

    asyncio.create_task(_process_mission(atom))


async def _process_mission(atom: dict[str, Any]) -> None:
    """Exécution longue d'une mission (subprocess + gate + delivery).

    Lancée en task détachée par `_handle_incoming` pour ne pas bloquer le
    subscribe loop qui doit pouvoir recevoir le commit_verdict suivant.

    Phase D.4 Bloc 9a : ouvre un `MissionLogger` qui capture intégralement
    prompt + completion + stderr dans `$ARAC_HOME/logs/agents/{id}.jsonl`.
    Sur échec (verdict=rejected, timeout, subprocess_fail), POST atome
    kind=gotcha post-mortem auto.
    """
    source_ref = atom.get("source_ref") or {}
    mission_id = source_ref.get("mission_id") or ""
    reply_chat_id = source_ref.get("reply_chat_id")
    prompt = (atom.get("value") or "").strip()

    logger.info(json.dumps({
        "event": "developer.mission_received",
        "mission_id": mission_id,
        "prompt_preview": prompt[:80],
        "reply_chat_id": reply_chat_id,
    }))

    sha_before = await git_ops.head_sha()
    branch_before = await git_ops.current_branch()

    # Bloc 9a : ouvre le transcript JSONL pour cette mission. Capture
    # tolérante aux erreurs FS (warn + continue, ne plante pas la mission).
    mission_logger: MissionLogger | None
    try:
        mission_logger = MissionLogger(mission_id)
        mission_logger.write_event(
            "mission.start",
            agent=_NODE_ID,
            prompt=prompt,
            reply_chat_id=reply_chat_id,
            branch=branch_before,
            sha_before=sha_before,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(json.dumps({
            "event": "developer.mission_logger_init_fail",
            "mission_id": mission_id,
            "err": str(e)[:200],
        }))
        mission_logger = None

    result = await run_claude_subprocess(prompt, mission_logger=mission_logger)

    branch_after = await git_ops.current_branch()
    # Note: sha_after final est connu après gate (commit ou non).

    logger.info(json.dumps({
        "event": "developer.subprocess_done",
        "mission_id": mission_id,
        "ok": result["ok"],
        "exit_code": result["exit_code"],
        "duration_sec": result["duration_sec"],
        "timed_out": result["timed_out"],
        "sha_before": sha_before,
        "branch_before": branch_before,
        "branch_after": branch_after,
    }))

    # Gate auditor (uniquement si subprocess succès)
    gate: dict[str, Any]
    if result["ok"] and not result["timed_out"]:
        gate = await _gate_and_commit(
            mission_id=mission_id,
            prompt=prompt,
            branch=branch_after or branch_before,
            reply_chat_id=reply_chat_id,
            mission_logger=mission_logger,
        )
    else:
        gate = {
            "verdict": "skipped_subprocess_fail",
            "verdict_atom_id": None,
            "proposal_atom_id": None,
            "reasons": [],
            "sha_after": sha_before,
        }

    sha_after = gate.get("sha_after") or await git_ops.head_sha()

    transcript_path = str(mission_logger.path) if mission_logger else None

    # POST delivery atom (kind=delivery depuis 0004 + patch D.5 vague 2)
    try:
        delivery = await _post_delivery(
            mission_id=mission_id,
            prompt=prompt,
            result=result,
            sha_before=sha_before,
            sha_after=sha_after,
            branch=branch_after or branch_before,
            verdict=gate.get("verdict"),
            verdict_atom_id=gate.get("verdict_atom_id"),
            proposal_atom_id=gate.get("proposal_atom_id"),
            transcript_path=transcript_path,
        )
        delivery_id = delivery["id"]
    except Exception as e:  # noqa: BLE001
        logger.error(json.dumps({
            "event": "developer.delivery_post_fail",
            "mission_id": mission_id,
            "error": type(e).__name__,
            "detail": str(e)[:200],
        }))
        delivery_id = "post-failed"

    # Bloc 9a §9 : hook post-mortem auto sur échec
    verdict_final = gate.get("verdict")
    should_post_gotcha = (
        result.get("timed_out")
        or not result.get("ok")
        or verdict_final == "rejected"
        or verdict_final == "timeout"
    )
    gotcha_atom_id: str | None = None
    if should_post_gotcha and mission_id:
        if result.get("timed_out"):
            trigger = "timeout"
            reason = f"subprocess timeout after {result.get('duration_sec')}s"
        elif not result.get("ok"):
            trigger = "subprocess_fail"
            reason = f"subprocess exit_code={result.get('exit_code')}"
        elif verdict_final == "rejected":
            trigger = "rejected"
            reasons_list = gate.get("reasons") or []
            reason = "auditor rejected: " + "; ".join(reasons_list[:3]) if reasons_list else "auditor rejected"
        elif verdict_final == "timeout":
            trigger = "timeout"
            reason = "audit verdict timeout"
        else:
            trigger = "unknown"
            reason = "unknown"
        try:
            gotcha_atom = await _post_gotcha_atom(
                mission_id=mission_id,
                transcript_path=transcript_path,
                trigger=trigger,
                reason=reason,
            )
            gotcha_atom_id = gotcha_atom.get("id")
            logger.info(json.dumps({
                "event": "developer.gotcha_posted",
                "mission_id": mission_id,
                "gotcha_atom_id": gotcha_atom_id,
                "trigger": trigger,
            }))
            if mission_logger is not None:
                mission_logger.write_event(
                    "gotcha.emitted",
                    gotcha_atom_id=gotcha_atom_id,
                    trigger=trigger,
                    summary=reason[:200],
                )
        except Exception as e:  # noqa: BLE001
            logger.error(json.dumps({
                "event": "developer.gotcha_post_fail",
                "mission_id": mission_id,
                "error": type(e).__name__,
                "detail": str(e)[:200],
            }))

    summary = _build_summary(
        mission_id=mission_id,
        result=result,
        sha_before=sha_before,
        sha_after=sha_after,
        branch=branch_after or branch_before,
        delivery_id=delivery_id,
        verdict=gate.get("verdict"),
        verdict_reasons=gate.get("reasons"),
    )

    try:
        await bus.send(
            from_node=_NODE_ID,
            to_node=_ORCHESTRATOR_NODE_ID,
            value=summary,
            metadata={
                "mission_id": mission_id,
                "reply_chat_id": reply_chat_id,
                "delivery_id": delivery_id,
                "verdict": gate.get("verdict"),
                "sha_after": sha_after,
            },
        )
        logger.info(json.dumps({
            "event": "developer.summary_sent",
            "mission_id": mission_id,
            "verdict": gate.get("verdict"),
            "summary_preview": summary[:80],
        }))
    except Exception as e:  # noqa: BLE001
        logger.error(json.dumps({
            "event": "developer.summary_send_fail",
            "mission_id": mission_id,
            "error": type(e).__name__,
            "detail": str(e)[:200],
        }))

    if mission_logger is not None:
        try:
            mission_logger.write_event(
                "mission.end",
                verdict_final=verdict_final,
                delivery_atom_id=delivery_id,
                gotcha_atom_id=gotcha_atom_id,
                total_duration_sec=result.get("duration_sec"),
                sha_after=sha_after,
            )
            mission_logger.close()
        except Exception as e:  # noqa: BLE001
            logger.warning(json.dumps({
                "event": "developer.transcript_close_fail",
                "mission_id": mission_id,
                "err": str(e)[:200],
            }))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def amain() -> int:
    _setup_logging()
    logger.info(json.dumps({
        "event": "boot.ok",
        "node_id": _NODE_ID,
        "phase": "D.2",
        "mode": "async + bus subscribe + claude CLI subprocess + auditor gate",
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
