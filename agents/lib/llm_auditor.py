"""Auditeur LLM cross-provider — Phase E.

Architecture (cf decision phase-e-auditor-llm-architecture-2026-05-22) :

  1. **Étape 1 — audit statique** (`agents.lib.commit_audit`) :
     déterministe, fail-fast. Si reject → reject final, LLM PAS appelé
     (économie API + protection contre injection de payload coûteux).

  2. **Étape 2 — audit LLM** (ce module) : appelle OpenAI GPT-5.5 (modèle par
     défaut `gpt-5.5-turbo`, fallback `gpt-4o-mini` si 404). Diversité
     cross-provider : le developer tourne sur Claude (Anthropic), l'auditeur
     LLM tourne sur OpenAI → réduit le risque de collusion d'erreurs de
     modèle (deux familles de modèles ont peu de chance d'avoir les mêmes
     angles morts).

Prompt :
  - system : constitution ARAC (variable ARAC_CONSTITUTION) + concaténation
    des 8 founding-atoms (récupérés via GET /v1/atoms/foundations) +
    consigne JSON strict.
  - user : diff + branch + files + node_id + mission_id.

Réponse attendue (response_format=json_object) :
  {"verdict": "approve"|"reject", "reasons": [string], "confidence": 0-1}

Exceptions custom pour différencier les modes d'échec :
  - RateLimitException (429) → caller queue + alert Telegram
  - LLMDownException (5xx, timeout, network) → caller décide fail-open/closed
  - LLMMalformedException (JSON invalide, schéma faux) → reject + gotcha

Env vars :
  - OPENAI_API_KEY                     obligatoire
  - ARAC_AUDITOR_LLM_ENABLED           default "true"
  - ARAC_AUDITOR_LLM_MODEL             default "gpt-5.5-turbo"
  - ARAC_AUDITOR_LLM_TIMEOUT_SEC       default 30
  - ARAC_AUDITOR_LLM_FAIL_MODE         default "open" (alt: "closed")

Retry strategy : 2 tentatives exponential backoff 2s, 4s sur 5xx / timeout /
network. Pas de retry sur 429 (raise immédiate → caller queue) ni sur 4xx
non-429 (raise immédiate → caller decide).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx

from app.api_token import entetes_api
from app.journal import raison

logger = logging.getLogger("arac.auditor.llm")

# ----------------------------------------------------------------------------
# La constitution — une seule source, partagee par l'API et par les agents
# ----------------------------------------------------------------------------
#
# Elle vit dans `app/constitution.py`, surchargeable par `config/constitution.md`.
# Deux copies du texte finiraient par diverger, et l'auditeur jugerait alors
# selon des regles que l'API n'applique plus.


def _load_constitution() -> str:
    """Le texte en vigueur. Lu a l'appel, pas a l'import : le modifier ne
    demande pas de redemarrer l'auditeur."""
    from app import constitution

    return constitution.text()


# ----------------------------------------------------------------------------
# Exceptions custom — discrimination des modes d'échec côté caller
# ----------------------------------------------------------------------------


class RateLimitException(Exception):
    """OpenAI a renvoyé 429. Le caller doit queue le retry + alert Telegram."""


class LLMDownException(Exception):
    """5xx, timeout, network error. Le caller applique ARAC_AUDITOR_LLM_FAIL_MODE."""


class LLMMalformedException(Exception):
    """Réponse non parsable en JSON ou ne respectant pas le schéma attendu.

    Le caller doit reject + POST atome `kind=gotcha` pour traçabilité."""


# ----------------------------------------------------------------------------
# Helpers internes
# ----------------------------------------------------------------------------


def _api_url() -> str:
    return os.environ.get("ARAC_API_URL", "").rstrip("/")


def _openai_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise LLMDownException("OPENAI_API_KEY non défini")
    return key


def _model_name() -> str:
    return os.environ.get("ARAC_AUDITOR_LLM_MODEL", "gpt-5.5-turbo").strip()


def _fallback_model() -> str:
    return os.environ.get("ARAC_AUDITOR_LLM_FALLBACK_MODEL", "gpt-4o-mini").strip()


def _timeout_sec() -> float:
    try:
        return float(os.environ.get("ARAC_AUDITOR_LLM_TIMEOUT_SEC", "30"))
    except ValueError:
        return 30.0


async def fetch_foundations(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """GET /v1/atoms/foundations — renvoie la liste des 8 pierres-angulaires.

    Tolérant : si l'endpoint échoue, on log + renvoie liste vide (l'audit LLM
    continue, juste avec une fenêtre de contexte plus pauvre).
    """
    try:
        r = await client.get(f"{_api_url()}/v1/atoms/foundations", timeout=5.0,
                             headers=entetes_api())
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return data
        logger.warning(json.dumps({
            "event": "llm_auditor.foundations_unexpected_shape",
            "type": type(data).__name__,
        }))
        return []
    except (httpx.HTTPError, ValueError) as e:
        logger.warning(json.dumps({
            "event": "llm_auditor.foundations_fetch_fail",
            "error": type(e).__name__,
            "raison": raison(e),
        }))
        return []


def _build_system_prompt(foundations: list[dict[str, Any]]) -> str:
    """system message : constitution + 8 founding-atoms + consigne JSON strict."""
    constitution = _load_constitution()

    foundations_text_parts = []
    for f in foundations:
        key = f.get("key", "?")
        kind = f.get("kind", "?")
        scope = f.get("scope", "?")
        value = (f.get("value") or "").strip()
        # On garde la pierre-angulaire complète (la constitution est déjà à
        # ~2984 tokens, et 8 founding-atoms compactes restent gérables côté
        # context window GPT).
        foundations_text_parts.append(
            f"### Founding atom — {kind}/{scope}/{key}\n{value}"
        )
    foundations_block = "\n\n".join(foundations_text_parts) if foundations_text_parts else "(aucune pierre-angulaire chargée)"

    return (
        f"{constitution}\n\n"
        f"# Pierres angulaires actives (foundings)\n\n"
        f"{foundations_block}\n\n"
        f"# Mission de l'auditeur LLM\n\n"
        f"Tu es auditeur ARAC cross-provider. Le developer ARAC tourne sur "
        f"Claude (Anthropic), tu tournes sur OpenAI : ta diversité de modèle "
        f"est précisément ce qui apporte de la valeur (réduction du risque "
        f"de collusion d'angles morts).\n\n"
        f"Décide si ce commit_proposal peut être validé. Critères :\n"
        f"  - aucune violation de la constitution ARAC (anti-fabulation, "
        f"source-of-truth, séparation des quatre mondes, soft-delete, etc.)\n"
        f"  - aucun secret encodé (base64, hex, JWT déformé) que la regex "
        f"statique aurait raté\n"
        f"  - aucune logique de soft-bypass des règles statiques\n"
        f"  - le diff fait ce que la mission demande (cohérence sémantique)\n\n"
        f"Réponds STRICTEMENT en JSON :\n"
        f'{{"verdict": "approve" | "reject", "reasons": [string], "confidence": 0-1}}\n\n'
        f"En cas de doute légitime, préfère 'reject' avec confidence basse "
        f"plutôt qu'un approve hâtif (principe ARAC : la prudence prime)."
    )


def _build_user_prompt(
    *,
    diff: str,
    branch: str | None,
    files: list[str],
    mission_id: str,
    node_id: str,
) -> str:
    return (
        f"Mission: {mission_id}\n"
        f"Node: {node_id}\n"
        f"Branch: {branch or '?'}\n"
        f"Files ({len(files)}): {', '.join(files) if files else '(aucun)'}\n\n"
        f"Diff:\n{diff}"
    )


def _parse_llm_response(content: str) -> dict[str, Any]:
    """Parse + valide le JSON renvoyé. Raise LLMMalformedException si KO."""
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, ValueError) as e:
        raise LLMMalformedException(f"JSON decode failed: {e}") from e

    if not isinstance(parsed, dict):
        raise LLMMalformedException(f"response is not a dict: {type(parsed).__name__}")

    verdict = parsed.get("verdict")
    if verdict not in ("approve", "reject"):
        raise LLMMalformedException(
            f"verdict invalide: {verdict!r} (attendu 'approve' ou 'reject')"
        )

    reasons = parsed.get("reasons", [])
    if not isinstance(reasons, list):
        raise LLMMalformedException(f"reasons doit être une liste: {type(reasons).__name__}")
    reasons = [str(r) for r in reasons]

    confidence = parsed.get("confidence", 0.0)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    return {"verdict": verdict, "reasons": reasons, "confidence": confidence}


async def _call_openai_chat(
    *,
    client: httpx.AsyncClient,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    """Un POST chat completions vers OpenAI. Renvoie response.json() brut.

    Discrimine les statuts :
      - 200 → renvoie payload
      - 404 / model_not_found → LLMDownException (signale au caller fallback)
      - 429 → RateLimitException
      - 5xx → LLMDownException
      - autre 4xx → LLMDownException (config / auth — caller decide)
    """
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
    }
    headers = {
        "Authorization": f"Bearer {_openai_api_key()}",
        "Content-Type": "application/json",
    }
    r = await client.post(
        "https://api.openai.com/v1/chat/completions",
        json=payload,
        headers=headers,
    )

    if r.status_code == 200:
        return r.json()

    body_preview = ""
    try:
        body_preview = r.text[:300]
    except Exception:  # noqa: BLE001
        body_preview = "<unreadable>"

    if r.status_code == 429:
        raise RateLimitException(f"openai 429: {body_preview}")

    # Cas 404 / model_not_found / invalid_model → signal pour fallback.
    if r.status_code == 404 or "model_not_found" in body_preview or "does not exist" in body_preview:
        raise LLMDownException(f"model_not_found ({r.status_code}): {body_preview}")

    if 500 <= r.status_code < 600:
        raise LLMDownException(f"openai 5xx {r.status_code}: {body_preview}")

    # autres 4xx (auth, payload, etc.)
    raise LLMDownException(f"openai {r.status_code}: {body_preview}")


async def audit_with_llm(
    *,
    diff: str,
    branch: str | None,
    files: list[str],
    mission_id: str,
    node_id: str,
    foundations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Audite un commit_proposal via OpenAI. Renvoie {verdict, reasons, confidence}.

    Si `foundations` est None, fait un GET /v1/atoms/foundations dans la
    même session httpx que l'appel OpenAI (optimise pool).

    Retry : 2 tentatives exponential backoff 2s, 4s sur LLMDownException
    (5xx / timeout / network). Pas de retry sur RateLimitException ni sur
    LLMMalformedException.

    Fallback modèle : si le modèle principal renvoie model_not_found, on
    retry une seule fois avec ARAC_AUDITOR_LLM_FALLBACK_MODEL (default
    gpt-4o-mini), sans backoff.
    """
    timeout = httpx.Timeout(connect=5.0, read=_timeout_sec(), write=5.0, pool=5.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        if foundations is None:
            foundations = await fetch_foundations(client)

        system_prompt = _build_system_prompt(foundations)
        user_prompt = _build_user_prompt(
            diff=diff, branch=branch, files=files,
            mission_id=mission_id, node_id=node_id,
        )

        primary_model = _model_name()
        fallback_model = _fallback_model()
        models_to_try = [primary_model]
        if fallback_model and fallback_model != primary_model:
            models_to_try.append(fallback_model)

        backoffs = (2.0, 4.0)
        last_exc: Exception | None = None

        for model in models_to_try:
            for attempt, backoff in enumerate([0.0] + list(backoffs)):
                if backoff > 0:
                    await asyncio.sleep(backoff)
                try:
                    raw = await _call_openai_chat(
                        client=client,
                        model=model,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                    )
                except RateLimitException:
                    # Pas de retry interne sur 429 — le caller queue.
                    raise
                except LLMDownException as e:
                    last_exc = e
                    err_str = str(e)
                    # Si model_not_found : sort de la boucle attempts pour
                    # passer au modèle fallback (pas d'utilité à retry x3).
                    if "model_not_found" in err_str:
                        logger.warning(json.dumps({
                            "event": "llm_auditor.model_not_found_fallback",
                            "model": model,
                            "detail": err_str[:200],
                        }))
                        break
                    logger.warning(json.dumps({
                        "event": "llm_auditor.attempt_failed",
                        "model": model,
                        "attempt": attempt,
                        "error": err_str[:200],
                    }))
                    continue
                except (httpx.TimeoutException, httpx.HTTPError, OSError) as e:
                    last_exc = LLMDownException(f"network/timeout: {type(e).__name__}: {e}")
                    logger.warning(json.dumps({
                        "event": "llm_auditor.attempt_network_fail",
                        "model": model,
                        "attempt": attempt,
                        "error": type(e).__name__,
                    }))
                    continue

                # 200 OK — parse
                try:
                    choices = raw.get("choices") or []
                    if not choices:
                        raise LLMMalformedException("response.choices vide")
                    content = (choices[0].get("message") or {}).get("content") or ""
                    parsed = _parse_llm_response(content)
                except LLMMalformedException:
                    raise
                except Exception as e:  # noqa: BLE001
                    raise LLMMalformedException(
                        f"parse error: {type(e).__name__}: {e}"
                    ) from e

                logger.info(json.dumps({
                    "event": "llm_auditor.verdict",
                    "mission_id": mission_id,
                    "model": model,
                    "verdict": parsed["verdict"],
                    "confidence": parsed["confidence"],
                    "reasons_count": len(parsed["reasons"]),
                }))
                return parsed

        # Toutes les tentatives ont échoué côté réseau / 5xx / model_not_found
        if last_exc is None:
            last_exc = LLMDownException("all attempts failed (no exception captured)")
        if isinstance(last_exc, LLMDownException):
            raise last_exc
        raise LLMDownException(str(last_exc))
# ============================================================================
# Extension v0.5 Vague 2 I9 — Gate ciblé curator (Q6)
# ============================================================================
# Ajouté par I9 pour Q6 : auditer via LLM cross-provider UNIQUEMENT les atomes
# extraits par le curator avec kind STRICT (decision, gotcha, killed). Les
# atomes STANDARD (pattern/state/todo/alert) et LARGE (idea/insight/...) ne
# sont PAS audités à ce niveau — le gate prompt-level dans le subprocess
# curator suffit (politique de seuils par kind).
#
# Q6 ciblé : node_id=arac-curator + kind in {decision, gotcha, killed}.
# Pas d'extension aux autres nodes (le developer reste gated via commit_audit
# v0.4, pas via cette extension).


_CURATOR_NODE_ID = "arac-curator"
_STRICT_KINDS_GATED = frozenset({"decision", "gotcha", "killed"})


def should_gate_atom_curator(atom_dict: dict) -> bool:
    """Q6 ciblé — retourne True ssi l'atome a été extrait par curator et son
    kind appartient à la liste STRICT.

    Critères stricts :
        - `atom_dict.get("node_id") == "arac-curator"`
        - `atom_dict.get("kind") in {"decision", "gotcha", "killed"}`

    Retourne False sinon. En particulier :
        - node_id != "arac-curator" → False (pas de gate sur developer/auditor)
        - kind in {"idea", "note", ...} (LARGE) → False
        - kind in {"pattern", "state", ...} (STANDARD) → False
        - atom_dict mal formé / clés manquantes → False (fail-safe)
    """
    if not isinstance(atom_dict, dict):
        return False
    if atom_dict.get("node_id") != _CURATOR_NODE_ID:
        return False
    if atom_dict.get("kind") not in _STRICT_KINDS_GATED:
        return False
    return True


async def audit_curator_atom(
    *,
    atom: dict,
    foundations: list[dict] | None = None,
) -> dict:
    """Audite un atome curator via OpenAI GPT-5.5. Wrapper sur
    `audit_with_llm` qui sérialise l'atome en pseudo-diff pour réutiliser
    la mécanique cross-provider existante (constitution + foundings +
    JSON strict {verdict, reasons, confidence}).

    Pré-condition : `should_gate_atom_curator(atom) is True`. Si l'appelant
    ne pré-filtre pas, le gate s'applique quand même mais c'est un gaspillage
    d'appel OpenAI.

    Retourne le même schéma que `audit_with_llm` :
        {"verdict": "approve"|"reject", "reasons": [str], "confidence": 0-1}

    Lève les mêmes exceptions : RateLimitException, LLMDownException,
    LLMMalformedException. Le caller (auditor.main) applique sa fail-mode.
    """
    # Sérialisation atome → "pseudo-diff" qui passe les heuristiques du
    # prompt audit existant. Pas besoin de prompt dédié curator pour v0.5 —
    # la constitution ARAC charge déjà les règles anti-fabulation / scope
    # / soft-delete qui s'appliquent à n'importe quel atome.
    kind = atom.get("kind", "?")
    scope = atom.get("scope", "?")
    key = atom.get("key", "?")
    value = atom.get("value") or ""
    tags = atom.get("tags") or []
    source_ref = atom.get("source_ref") or {}
    raw_id = source_ref.get("curator_raw_id") or source_ref.get("raw_id") or "?"

    pseudo_diff = (
        f"# Curator-extracted atom (raw_id={raw_id})\n"
        f"kind: {kind}\n"
        f"scope: {scope}\n"
        f"key: {key}\n"
        f"tags: {', '.join(tags) if tags else '(none)'}\n"
        f"value:\n{value}\n"
    )

    # mission_id synthétique : préfixe curator + raw_id court pour traçabilité.
    short_raw = str(raw_id)[:8] if raw_id and raw_id != "?" else "noraw"
    synthetic_mission_id = f"curator-{kind}-{short_raw}"

    return await audit_with_llm(
        diff=pseudo_diff,
        branch=None,
        files=[],
        mission_id=synthetic_mission_id,
        node_id=_CURATOR_NODE_ID,
        foundations=foundations,
    )
