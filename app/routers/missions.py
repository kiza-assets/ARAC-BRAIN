"""Router missions — Bloc 9b v0.4 (observabilité triade ARAC).

Expose en lecture seule les transcripts JSONL produits par l'agent
Developer (triade Developer/Reviewer/Auditor
sections 6-8). Les fichiers sont écrits par I6 dans :

    $ARAC_HOME/logs/agents/{mission_id}.jsonl

Endpoints :
  - GET /v1/missions?limit=N        → liste des N missions récentes (mtime DESC)
  - GET /v1/missions/{mid}/transcript
        → text/plain (raw JSONL) par défaut
        → application/json si Accept: application/json
  - GET /v1/missions/{mid}/transcript?summary=true
        → JSON {mission_id, event_count, event_types_distribution,
                duration_ms, sha_before, sha_after, verdict}

Sécurité :
  - Path traversal bloqué (mission_id contenant '..' ou '/' ou '\\' → 403).
  - Lecture seule stricte (aucun POST/PATCH/DELETE).
  - Auth : géré globalement par le middleware Bearer (app/auth.py) — le jeton
    porteur est exigé de TOUTE requête, `127.0.0.1` compris ; seul `/healthz`
    est public. Le desserrage de la boucle locale exige DEUX variables écrites
    (`ARAC_API_TRUST_LOOPBACK` + `_RAISON`).

Doctrine ARAC :
  - Anti-fabulation : tout résultat vient d'une lecture FS réelle.
  - Prospective marking : si une mission est en cours (fichier ouvert
    par I6), les champs sha_after / verdict / duration_ms peuvent être
    None — c'est documenté dans le schema réponse summary.
"""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

import arac_runtime
from app.journal import raison  # noqa: E402


router = APIRouter()
_logger = logging.getLogger("arac.api.missions")


# Racine canonique des transcripts triade ARAC (cf I6 Bloc 9a — agent
# Developer wrap_run écrit ici). Override possible via env pour les tests.
_TRANSCRIPTS_DIR = Path(arac_runtime.agent_logs_dir())


# ============================================================================
# Helpers
# ============================================================================


def _validate_mission_id(mission_id: str) -> None:
    """Refuse tout mission_id avec séparateur path ou parent ref.

    On ne tente PAS de valider qu'il s'agit d'un UUID strict — I6 peut écrire
    des noms de fichier non-UUID (ex : 'manual-test-xxx.jsonl'). On bloque
    uniquement les patterns dangereux pour path traversal.

    Raises:
        HTTPException 403 si le mission_id contient '..', '/' ou '\\'.
    """
    if not mission_id:
        raise HTTPException(status_code=403, detail="Empty mission_id")
    if ".." in mission_id or "/" in mission_id or "\\" in mission_id:
        _logger.warning(
            "missions.path_traversal_blocked",
            extra={"event": "denied", "mission_id_raw": mission_id[:64]},
        )
        raise HTTPException(status_code=403, detail="Invalid mission_id")
    # Caractère NUL : protection défensive (FS Linux rejette mais on bloque
    # tôt pour ne pas dépendre du comportement OS).
    if "\x00" in mission_id:
        raise HTTPException(status_code=403, detail="Invalid mission_id")


def _mission_path(mission_id: str) -> Path:
    """Retourne le chemin .jsonl pour un mission_id validé.

    L'appelant DOIT avoir appelé _validate_mission_id() au préalable.
    """
    return _TRANSCRIPTS_DIR / f"{mission_id}.jsonl"


def _parse_jsonl(content: str) -> list[dict[str, Any]]:
    """Parse un transcript JSONL en list[dict]. Skip silencieusement les
    lignes vides ; lève sur ligne malformée (signal anomalie I6).

    Note doctrine : on NE silencie PAS les erreurs JSON sur ligne non-vide
    — un transcript corrompu doit être visible (anti-fabulation).
    """
    events: list[dict[str, Any]] = []
    for i, line in enumerate(content.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Transcript line {i} invalid JSON: {exc.msg}",
            )
        if not isinstance(ev, dict):
            raise HTTPException(
                status_code=500,
                detail=f"Transcript line {i} not a JSON object",
            )
        events.append(ev)
    return events


# ============================================================================
# GET /v1/missions
# ============================================================================


@router.get("")
async def list_missions(
    limit: int = Query(20, ge=1, le=200, description="Max missions retournées"),
) -> list[dict[str, Any]]:
    """Liste les N transcripts les plus récents (par mtime DESC).

    Retourne `[{mission_id, mtime, size_bytes}]`. Liste vide si le dossier
    n'existe pas encore (cas startup avant première mission triade).
    """
    if not _TRANSCRIPTS_DIR.exists():
        _logger.info(
            "missions.list_no_dir",
            extra={
                "event": "ready",
                "dir": str(_TRANSCRIPTS_DIR),
                "result_count": 0,
            },
        )
        return []

    entries: list[tuple[Path, os.stat_result]] = []
    try:
        children = list(_TRANSCRIPTS_DIR.iterdir())
    except OSError as exc:
        # Dossier présent mais illisible (permissions) — dégradation propre plutôt
        # qu'un 500 non géré. Le volet permissions FS est hors-code (GO).
        _logger.error(
            "missions.list_unreadable",
            extra={
                "event": "degraded",
                "dir": str(_TRANSCRIPTS_DIR),
                "error": raison(exc),
                "result_count": 0,
            },
        )
        return []
    for child in children:
        if not child.is_file() or child.suffix != ".jsonl":
            continue
        try:
            st = child.stat()
        except OSError:
            # Fichier supprimé entre iterdir et stat — skip silencieusement.
            continue
        entries.append((child, st))

    entries.sort(key=lambda pair: pair[1].st_mtime, reverse=True)
    entries = entries[:limit]

    result = [
        {
            "mission_id": p.stem,
            "mtime": st.st_mtime,
            "size_bytes": st.st_size,
        }
        for p, st in entries
    ]
    _logger.info(
        "missions.list",
        extra={"event": "ready", "result_count": len(result), "limit": limit},
    )
    return result


# ============================================================================
# GET /v1/missions/{mission_id}/transcript
# ============================================================================


@router.get("/{mission_id}/transcript")
async def get_transcript(
    request: Request,
    mission_id: str,
    summary: bool = Query(False, description="Retourne uniquement métadonnées"),
):
    """Récupère le transcript JSONL d'une mission triade.

    Modes :
      - summary=true  → JSON métadonnées (counts, durée, verdict, sha).
      - Accept: application/json → liste d'événements parsée.
      - Sinon         → text/plain brut (JSONL line-delimited).
    """
    _validate_mission_id(mission_id)
    path = _mission_path(mission_id)

    try:
        path_exists = path.exists()
    except PermissionError as exc:
        # Path.exists() relève EACCES (parent illisible) en 3.12 → dégrade en 503
        # plutôt qu'un 500 + traceback bruyant. Volet perms FS = GO.
        _logger.error(
            "missions.transcript_unreadable",
            extra={"event": "degraded", "mission_id": mission_id,
                   "error": raison(exc)},
        )
        raise HTTPException(
            status_code=503,
            detail="Transcript temporarily unreadable (storage permissions)",
        )
    if not path_exists:
        _logger.info(
            "missions.transcript_not_found",
            extra={"event": "denied", "mission_id": mission_id},
        )
        raise HTTPException(status_code=404, detail="Transcript not found")

    try:
        content = path.read_text(encoding="utf-8")
    except PermissionError as exc:
        _logger.error(
            "missions.transcript_unreadable",
            extra={"event": "degraded", "mission_id": mission_id,
                   "error": raison(exc)},
        )
        raise HTTPException(
            status_code=503,
            detail="Transcript temporarily unreadable (storage permissions)",
        )
    except OSError as exc:
        _logger.exception(
            "missions.read_failed",
            extra={"event": "failed", "mission_id": mission_id},
        )
        raise HTTPException(
            status_code=500, detail=f"Cannot read transcript: {exc}"
        )

    if summary:
        events = _parse_jsonl(content)
        return _build_summary(mission_id, events)

    # Négociation contenu : si client demande JSON explicitement, on parse.
    accept = request.headers.get("Accept", "")
    if "application/json" in accept and "text/plain" not in accept:
        events = _parse_jsonl(content)
        _logger.info(
            "missions.transcript_json",
            extra={
                "event": "ready",
                "mission_id": mission_id,
                "event_count": len(events),
            },
        )
        return JSONResponse(content=events)

    _logger.info(
        "missions.transcript_raw",
        extra={
            "event": "ready",
            "mission_id": mission_id,
            "size_bytes": len(content),
        },
    )
    return PlainTextResponse(content=content, media_type="text/plain")


# ============================================================================
# Summary builder
# ============================================================================


def _extract_field(events: list[dict[str, Any]], *keys: str) -> Any:
    """Cherche la première valeur non-None pour une des clés données.

    Scanne les events dans l'ordre ; retourne la première occurrence trouvée.
    Inspecte aussi le sous-dict `payload` / `data` si présent (convention
    courante des loggers structurés).
    """
    for ev in events:
        for k in keys:
            if k in ev and ev[k] is not None:
                return ev[k]
            for sub in ("payload", "data", "context", "meta"):
                sub_obj = ev.get(sub)
                if isinstance(sub_obj, dict) and sub_obj.get(k) is not None:
                    return sub_obj[k]
    return None


def _extract_timestamp(ev: dict[str, Any]) -> float | None:
    """Tente d'extraire un timestamp epoch (float) d'un event.

    Convention non-figée — I6 peut émettre soit `ts` (epoch float), soit
    `timestamp` (ISO 8601). On supporte les deux ; renvoie None sinon.
    """
    for key in ("ts", "epoch", "time_epoch"):
        val = ev.get(key)
        if isinstance(val, (int, float)):
            return float(val)
    iso = ev.get("timestamp") or ev.get("time")
    if isinstance(iso, str):
        try:
            from datetime import datetime

            # fromisoformat tolère 'Z' suffix depuis Python 3.11
            return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _build_summary(
    mission_id: str, events: list[dict[str, Any]]
) -> dict[str, Any]:
    """Construit le dict métadonnées à partir d'une liste d'events parsée.

    Tolérant aux schemas — I6 peut faire évoluer la structure des events
    sans casser ce router (les champs absents apparaissent None).
    """
    # Distribution des event types — on cherche `event`, `type`, ou `kind`
    # (convention non figée à ce stade).
    type_counter: Counter[str] = Counter()
    for ev in events:
        ev_type = ev.get("event") or ev.get("type") or ev.get("kind")
        if isinstance(ev_type, str):
            type_counter[ev_type] += 1
        else:
            type_counter["<unknown>"] += 1

    # Durée : min/max des timestamps si extractibles.
    timestamps = [t for t in (_extract_timestamp(ev) for ev in events) if t]
    if len(timestamps) >= 2:
        duration_ms: float | None = round(
            (max(timestamps) - min(timestamps)) * 1000, 2
        )
    else:
        duration_ms = None

    # SHA git avant/après — cherche dans payloads (convention I6 prévue par
    # Convention : l'agent Developer logue `sha_before` au start
    # et `sha_after` au commit).
    sha_before = _extract_field(events, "sha_before", "git_sha_before")
    sha_after = _extract_field(events, "sha_after", "git_sha_after")

    # Verdict : dernier verdict émis par Auditor (priorité au dernier).
    verdict = None
    for ev in reversed(events):
        v = ev.get("verdict")
        if v is None:
            for sub in ("payload", "data", "context"):
                sub_obj = ev.get(sub)
                if isinstance(sub_obj, dict) and sub_obj.get("verdict"):
                    v = sub_obj["verdict"]
                    break
        if v:
            verdict = v
            break

    return {
        "mission_id": mission_id,
        "event_count": len(events),
        "event_types_distribution": dict(type_counter),
        "duration_ms": duration_ms,
        "sha_before": sha_before,
        "sha_after": sha_after,
        "verdict": verdict,
    }
