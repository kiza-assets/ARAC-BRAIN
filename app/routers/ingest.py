"""Router ingest — Bloc Cerveau Vivant v0.5.

Endpoint d ingestion des bundles de conversations Claude Code locales
expédiés par le cron Mac.

Endpoints :
  - POST /v1/ingest/conversations  → ingestion bundle NDJSON gzippé

Sécurité (couches superposées) :
  1. Middleware Bearer Phase 3 (app/auth.py:bearer_middleware) — le jeton
     porteur est exigé de TOUTE requête, `127.0.0.1` compris ; seul
     `/healthz` est public. Il attache `request.state.auth_node_id` au token
     valide. Le desserrage de la boucle locale exige DEUX variables écrites
     (`ARAC_API_TRUST_LOOPBACK` + `_RAISON`) ; cf app/auth.py.
  2. Whitelist node_id via env ARAC_INGEST_ALLOWED_NODES (comma-separated).
  3. Cohérence header X-ARAC-Node-Id vs request.state.auth_node_id — empêche
     un token valide d ingest pour un autre node.

Doctrine ARAC (anti-fabulation + defense-in-depth) :
  - Validation Pydantic v2 stricte (extra="forbid").
  - Idempotence par hash SHA-256 du body décompressé (re-POST = même raw_id).
  - Sanitize secrets côté serveur (redondance vs sanitize Mac, A3 v0.5).
  - Rate-limit RL-2 : count DB sur (node_id, received_at > now() - 1h).
  - Bus-2 (A1) : NOTIFY conversation_ingested émis automatiquement par le
    trigger PG arac.notify_conversation_ingested (migration 0008 par I2).
"""

from __future__ import annotations

import gzip
import logging
import os

from fastapi import APIRouter, HTTPException, Request


router = APIRouter()
_logger = logging.getLogger("arac.api.ingest")


# ============================================================================
# Constantes
# ============================================================================

# Defaults : 10 MB body, 10 req/h/node. Overridables via env.
_DEFAULT_MAX_INGEST_SIZE = 10 * 1024 * 1024
_DEFAULT_RATE_LIMIT_PER_HOUR = 10

_ENV_MAX_SIZE = "MAX_INGEST_SIZE_BYTES"
_ENV_RATE_LIMIT = "ARAC_INGEST_RATE_LIMIT_PER_HOUR"
_ENV_ALLOWED_NODES = "ARAC_INGEST_ALLOWED_NODES"

_HEADER_NODE_ID = "X-ARAC-Node-Id"
_HEADER_SOURCE_PATH = "X-ARAC-Source-Path"


# ============================================================================
# Helpers config
# ============================================================================


def _get_max_size() -> int:
    """Lit MAX_INGEST_SIZE_BYTES (defaults 10 MB)."""
    raw = os.environ.get(_ENV_MAX_SIZE)
    if not raw:
        return _DEFAULT_MAX_INGEST_SIZE
    try:
        v = int(raw)
        return v if v > 0 else _DEFAULT_MAX_INGEST_SIZE
    except ValueError:
        return _DEFAULT_MAX_INGEST_SIZE



def _get_allowed_nodes() -> frozenset[str]:
    """Parse env ARAC_INGEST_ALLOWED_NODES (comma-separated)."""
    raw = os.environ.get(_ENV_ALLOWED_NODES, "")
    return frozenset(s.strip() for s in raw.split(",") if s.strip())


# ============================================================================
# Helpers auth / whitelist
# ============================================================================


def _resolve_node_id(request: Request) -> str:
    """Résout le node_id ingest (Bearer attached ou header explicite).

    Ordre (cf D2 §1.1 + §2.2) :
      1. Si le middleware a authentifié un jeton (request.state.auth_node_id
         défini) → on l utilise.
         Si X-ARAC-Node-Id est aussi présent ET différent → 403 (mismatch).
      2. Sinon — cas qui ne survient plus qu'en régime DESSERRÉ, la boucle
         locale n'étant plus exemptée par défaut (app/auth.py) → header
         X-ARAC-Node-Id requis.
      3. Vérif whitelist ARAC_INGEST_ALLOWED_NODES (fail-closed si env absent).
    """
    header_node = request.headers.get(_HEADER_NODE_ID, "").strip() or None
    bearer_node = getattr(request.state, "auth_node_id", None)

    if bearer_node is not None:
        if header_node is not None and header_node != bearer_node:
            _logger.info(
                "ingest.bearer_node_mismatch",
                extra={
                    "event": "denied",
                    "header_node_id": header_node,
                    "bearer_node_id": bearer_node,
                },
            )
            raise HTTPException(
                status_code=403,
                detail="X-ARAC-Node-Id does not match Bearer token node",
            )
        node_id = bearer_node
    else:
        if not header_node:
            raise HTTPException(
                status_code=400,
                detail=f"Missing header {_HEADER_NODE_ID}",
            )
        node_id = header_node

    allowed = _get_allowed_nodes()
    if not allowed:
        # Fail-closed : env absent = aucun node autorisé.
        _logger.warning(
            "ingest.no_allowed_nodes_env",
            extra={"event": "config_missing"},
        )
        raise HTTPException(status_code=403, detail="Ingest not configured")
    if node_id not in allowed:
        _logger.info(
            "ingest.node_not_whitelisted",
            extra={"event": "denied", "node_id": node_id},
        )
        raise HTTPException(status_code=403, detail="Node not allowed for ingest")

    return node_id


# ============================================================================
# Helpers body
# ============================================================================


def _detect_gzip(raw: bytes) -> bool:
    """Magic bytes gzip : 0x1f 0x8b."""
    return len(raw) >= 2 and raw[0] == 0x1F and raw[1] == 0x8B


# Plafond dur du body DÉCOMPRESSÉ (revue adversariale 2026-07-03, C3) : le cap
# 10 MB s'appliquait au corps COMPRESSÉ — un gzip très répétitif de quelques MB
# peut se décompresser en ~1 GB et coucher la box (3,7 GiB RAM). Décompression
# STREAMING avec arrêt dur : jamais plus de _MAX_DECOMPRESSED_BYTES en mémoire.
_MAX_DECOMPRESSED_BYTES = 32 * 1024 * 1024  # 32 MB — largement > tout batch légitime
_DECOMPRESS_CHUNK = 1024 * 1024


def _decompress_if_gzip(
    raw_body: bytes, *, max_decompressed: int = _MAX_DECOMPRESSED_BYTES
) -> bytes:
    """Décompresse si gzip (magic bytes), sinon retourne tel quel.

    Tolérance : accepte body brut NDJSON (sans gzip) — utile en tests + clients
    légers. Le contrat spec recommande gzip mais ne l impose pas strictement.

    Anti-« gzip bomb » : décompression par blocs avec plafond dur → 413 dès
    que `max_decompressed` est dépassé, sans jamais matérialiser le reste.
    """
    if _detect_gzip(raw_body):
        import io

        out = bytearray()
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(raw_body)) as gz:
                while True:
                    chunk = gz.read(_DECOMPRESS_CHUNK)
                    if not chunk:
                        break
                    out.extend(chunk)
                    if len(out) > max_decompressed:
                        raise HTTPException(
                            status_code=413,
                            detail=(
                                "Decompressed body too large: "
                                f"> {max_decompressed} bytes"
                            ),
                        )
        except (OSError, EOFError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid gzip: {e}")
        return bytes(out)
    return raw_body




# ============================================================================
# POST /v1/ingest/conversations
# ============================================================================


@router.post("/conversations")
async def ingest_conversations(request: Request) -> None:
    """[GELÉ — remplacée par l'ingestion V2] Ingestion v1 par-snapshot → 410 Gone.

    La file vivante est V2 : POST /v1/ingest/messages (par-message, idempotent
    par dedup_key — app/routers/ingest_v2.py). `raw_conversations` est GELÉE
    lecture-seule (migration 0017) : table de LIGNÉE des atomes déjà curés,
    jamais backfillée, jamais droppée. Triggers NOTIFY supprimés (0016).

    Rollback : revert de ce commit + alembic downgrade 0017 + redéployer
    l'exporteur v1 sur le Mac (plist .v1.bak conservé sur place).
    """
    raise HTTPException(
        status_code=410,
        detail=(
            "Ingestion v1 gelée : utiliser POST "
            "/v1/ingest/messages (par-message). raw_conversations est en "
            "lecture seule (table de lignée)."
        ),
    )
