"""Router heartbeat — endpoint POST /v1/heartbeat (Phase A triade Agents).

Permet aux agents systemd (claude-orchestrator, claude-developer, codex-auditor)
de signaler leur vivacité au serveur ARAC sans nécessiter de credentials PG
directs (le user Unix `aracagent` n'a pas de rôle PG ; l'API porte les écritures).

Mécanique :
  1. INSERT dans `arac.nodes_heartbeat_history` (ligne par ping, conservée pour
     audit + alimentation cron `heartbeat_monitor` futur).
  2. UPDATE `arac.nodes.last_heartbeat` (atomique avec INSERT via transaction).

L'IP observée est capturée depuis `request.client.host` quand disponible
(un reverse proxy transmettrait l'origine via `X-Forwarded-For` — non géré ici car l'usage
est loopback localhost en Phase A).

Errors :
  - node_id inconnu → 422 (FK violation sur nodes_heartbeat_history.node_id_fkey)
  - Body vide ou node_id manquant → 422 (Pydantic)
"""

from __future__ import annotations

import json
import logging
from ipaddress import ip_address
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg import AsyncConnection
from psycopg.errors import ForeignKeyViolation
from pydantic import BaseModel, ConfigDict, Field

from app.db import get_db

logger = logging.getLogger("arac.heartbeat")
router = APIRouter()


class HeartbeatRequest(BaseModel):
    """Payload POST /v1/heartbeat — minimal."""

    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, max_length=128)
    metadata: dict[str, Any] | None = None


class HeartbeatResponse(BaseModel):
    """Sortie de heartbeat — confirme node_id et timestamp serveur appliqué."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    node_id: str
    heartbeat_at: str


@router.post("/heartbeat", response_model=HeartbeatResponse, status_code=201)
async def post_heartbeat(
    body: HeartbeatRequest,
    request: Request,
    db: Annotated[AsyncConnection, Depends(get_db)],
) -> HeartbeatResponse:
    """Enregistre un battement de cœur pour `node_id`.

    Transaction PG : INSERT history + UPDATE nodes.last_heartbeat en atomique.
    """
    # IP observée — utile pour audit, optionnelle. None si client inconnu (tests).
    ip_observed: str | None = None
    if request.client is not None:
        try:
            ip_observed = str(ip_address(request.client.host))
        except (ValueError, TypeError):
            ip_observed = None

    metadata_json = json.dumps(body.metadata) if body.metadata is not None else None

    try:
        async with db.transaction():
            row = await (
                await db.execute(
                    "INSERT INTO arac.nodes_heartbeat_history "
                    "(node_id, ip_observed, metadata) "
                    "VALUES (%s, %s::inet, %s::jsonb) "
                    "RETURNING heartbeat_at",
                    (body.node_id, ip_observed, metadata_json),
                )
            ).fetchone()
            await db.execute(
                "UPDATE arac.nodes SET last_heartbeat = NOW() WHERE node_id = %s",
                (body.node_id,),
            )
    except ForeignKeyViolation as e:
        raise HTTPException(
            status_code=422,
            detail=f"node_id inconnu (FK arac.nodes_heartbeat_history.node_id_fkey)",
        ) from e

    heartbeat_at = row[0].isoformat() if row else ""
    logger.info(
        "heartbeat.recorded",
        extra={"node_id": body.node_id, "ip": ip_observed},
    )
    return HeartbeatResponse(ok=True, node_id=body.node_id, heartbeat_at=heartbeat_at)
