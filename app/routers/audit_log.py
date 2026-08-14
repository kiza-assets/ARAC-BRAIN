"""Router audit_log — Phase 4.6 (GET read-only /v1/audit_log).

Expose les entrées de `arac.audit_log` où `warning_code IS NOT NULL` — i.e.
les warnings anti-drift W-001..W-007 persistés Phase 4.6 par le router atoms
(I2). Le dashboard analytics Phase 6+ consomme ces données.

Endpoint :
  - GET /v1/audit_log     → AuditLogResponse {entries, total, limit, offset}

Filtres GET combinables (tous optionnels) :
  - warning_code : str   (ex: 'W-001' .. 'W-007')
  - since        : datetime ISO 8601 (created_at >= since)
  - node_id      : str   (filtre par node émetteur)
  - target_atom_id : UUID (filtre par atome cible du warning)
  - limit        : int 1..200 (défaut 50)
  - offset       : int >=0   (défaut 0)

Doctrine :
  - READ-ONLY strict : zéro POST/PATCH/DELETE.
  - Param binding psycopg3 `%s` (pas de f-string SQL — anti-injection).
  - Index partial `ix_audit_log_warning_code WHERE warning_code IS NOT NULL`
    exploite le WHERE de base.
  - Style cohérent avec app/routers/dashboard.py (async with db.cursor,
    dict_row, logger structuré 'arac.api.audit_log').
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app.db import get_db
from app.schemas.audit_log import AuditLogEntry, AuditLogResponse


router = APIRouter()
_logger = logging.getLogger("arac.api.audit_log")


# ============================================================================
# GET /v1/audit_log
# ============================================================================


@router.get("", response_model=AuditLogResponse)
async def list_audit_log(
    db: Annotated[AsyncConnection, Depends(get_db)],
    warning_code: str | None = Query(
        None, description="Code warning (W-001..W-007)"
    ),
    since: datetime | None = Query(
        None, description="ISO 8601 datetime — created_at >= since"
    ),
    node_id: str | None = Query(None, description="Filtre node_id"),
    target_atom_id: UUID | None = Query(
        None, description="Filtre target_atom_id (UUID atome cible)"
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> AuditLogResponse:
    """GET /v1/audit_log — entrées warning (Phase 4.6), filtrables/paginées.

    Stratégie SQL :
      - WHERE de base : `warning_code IS NOT NULL` (exploite l'index partial
        ix_audit_log_warning_code de la migration 0005).
      - Filtres optionnels via clauses None-safe :
            (%s::<type> IS NULL OR colonne = %s)
        → un seul SQL paramétré, pas de string concat dynamique.
      - Tri created_at DESC, LIMIT/OFFSET pour pagination.
      - COUNT(*) séparé (même WHERE) pour `total`.

    `severity` et `message` sont extraits de `warning_context` côté Python
    (commodité frontend), `warning_context` exposé garde uniquement le
    sous-objet `context` brut si présent (cf schema AuditLogEntry).
    """
    sql = """
        SELECT id, node_id, target_atom_id, warning_code,
               warning_context, action, created_at
        FROM arac.audit_log
        WHERE warning_code IS NOT NULL
          AND (%s::text         IS NULL OR warning_code   = %s)
          AND (%s::timestamptz  IS NULL OR created_at    >= %s)
          AND (%s::text         IS NULL OR node_id        = %s)
          AND (%s::uuid         IS NULL OR target_atom_id = %s)
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """
    count_sql = """
        SELECT COUNT(*) AS total
        FROM arac.audit_log
        WHERE warning_code IS NOT NULL
          AND (%s::text         IS NULL OR warning_code   = %s)
          AND (%s::timestamptz  IS NULL OR created_at    >= %s)
          AND (%s::text         IS NULL OR node_id        = %s)
          AND (%s::uuid         IS NULL OR target_atom_id = %s)
    """

    # psycopg3 accepte UUID natif comme param ::uuid, mais on stringify pour
    # rester homogène avec le None-safe pattern (un seul type col-param).
    target_param = str(target_atom_id) if target_atom_id is not None else None

    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            sql,
            (
                warning_code, warning_code,
                since, since,
                node_id, node_id,
                target_param, target_param,
                limit, offset,
            ),
        )
        rows = await cur.fetchall()

        await cur.execute(
            count_sql,
            (
                warning_code, warning_code,
                since, since,
                node_id, node_id,
                target_param, target_param,
            ),
        )
        total_row = await cur.fetchone()
        total = int(total_row["total"]) if total_row else 0

    entries: list[AuditLogEntry] = []
    for r in rows:
        # warning_context arrive en dict natif (JSONB → dict via psycopg3).
        # Tolérance : si str (legacy), parse JSON ; si rien, dict vide.
        raw_ctx = r.get("warning_context")
        if raw_ctx is None:
            ctx: dict = {}
        elif isinstance(raw_ctx, str):
            try:
                ctx = json.loads(raw_ctx)
            except json.JSONDecodeError:
                ctx = {}
        elif isinstance(raw_ctx, dict):
            ctx = raw_ctx
        else:
            ctx = {}

        # Le sous-objet `context` du warning_context est exposé brut côté
        # API ; les clés `severity` / `message` sont hissées à la racine.
        sub_context = ctx.get("context")
        if not isinstance(sub_context, dict):
            sub_context = {}

        entries.append(
            AuditLogEntry(
                id=int(r["id"]),
                node_id=r["node_id"],
                target_atom_id=r["target_atom_id"],
                warning_code=r["warning_code"],
                severity=ctx.get("severity"),
                message=ctx.get("message"),
                warning_context=sub_context,
                action=r["action"],
                created_at=r["created_at"],
            )
        )

    _logger.info(
        "audit_log.list",
        extra={
            "event": "ready",
            "result_count": len(entries),
            "total": total,
            "limit": limit,
            "offset": offset,
            "filter_warning_code": warning_code,
            "filter_node_id": node_id,
        },
    )

    return AuditLogResponse(
        entries=entries,
        total=total,
        limit=limit,
        offset=offset,
    )
