"""Router sessions — endpoints CRUD pour `arac.sessions` + `arac.session_buffer`.

5 endpoints :
  - POST   /v1/sessions/open                     ouvre nouvelle session
  - POST   /v1/sessions/{id}/append              append event au buffer
  - POST   /v1/sessions/{id}/close               close + embed(summary) + UPDATE
  - GET    /v1/sessions/{id}?include_buffer=     read (avec ou sans buffer)
  - GET    /v1/sessions                          list filtré (node_id/scope/status)

Mécanique close (similaire pattern supersede atoms.py 2.3) :
  1. SELECT session sans FOR UPDATE → check ended_at IS NULL
  2. embed(summary) HORS transaction (~200-300ms, pool DB libre)
  3. async with db.transaction():
       SELECT FOR UPDATE re-check (anti-race close concurrent)
       UPDATE session SET ended_at, summary, summary_embedding, accomplishments,
              blockers, next_steps, closed_by

`atoms_created` design (Q.B Phase 2.4 — calculé live, pas stocké) :
  Le champ DDL `arac.sessions.atoms_created` (UUID[]) reste NULL Phase 2-3.
  La liste est calculée à la demande via `SELECT id FROM arac.memory_atoms
  WHERE session_id = %s ORDER BY created_at ASC`. Pas de désync, pas d'INSERT
  supplémentaire à chaque atom. Un futur Claude/dev qui s'étonnerait que le
  champ DDL existe mais reste NULL doit consulter le mini-plan
  Phase 2.4. Si Phase 9+ on a besoin de "frozen at close time" (audit
  immuable), un cron ou trigger PG peut populer le champ à la close.

Mapping erreurs PG (`_handle_pg_errors`) — duplicaté depuis atoms.py Phase 2.4.
Refactor en `app/routers/_errors.py` reporté Phase 2.5/2.6 (YAGNI : 2 utilisateurs
n'imposent pas encore l'extraction).
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg import AsyncConnection
from psycopg.errors import CheckViolation, ForeignKeyViolation, UniqueViolation
from psycopg.rows import dict_row

from app import journal
from app.db import get_db
from app.schemas.scope import Scope
from app.schemas.session import (
    SessionAppendEvent,
    SessionBufferEntry,
    SessionClose,
    SessionOpen,
    SessionRead,
    SessionReadWithBuffer,
    SessionState,
)
from app.services.embeddings import embed


router = APIRouter()
_logger = logging.getLogger("arac.api.sessions")


# ============================================================================
# Helpers privés
# ============================================================================


@contextmanager
def _handle_pg_errors():
    """Map psycopg errors → HTTPException. Dupliqué depuis atoms.py Phase 2.4
    (refactor en _errors.py reporté Phase 2.5/2.6 — YAGNI minimaliste).
    """
    try:
        yield
    except UniqueViolation as e:
        # Sessions n'a pas d'UNIQUE explicite (PK auto). Si jamais ça arrive,
        # c'est une corruption — message générique. Le diagnostic PostgreSQL
        # (contrainte, table, colonne, sqlstate) vient du schéma ; le message,
        # lui, porte `Key (…)=(…)` avec les VALEURS, et ne sort donc plus.
        raise HTTPException(
            status_code=409,
            detail={
                "erreur": "unique constraint violation",
                **journal.diagnostic_exception(e),
            },
        )
    except ForeignKeyViolation as e:
        msg = str(e)
        if "node_id" in msg:
            raise HTTPException(status_code=422, detail="node_id inconnu (FK arac.nodes)")
        raise HTTPException(
            status_code=422,
            detail={"erreur": "FK violation", **journal.diagnostic_exception(e)},
        )
    except CheckViolation as e:
        # Même règle qu'`atoms._handle_pg_errors` : le nom de la contrainte,
        # jamais la ligne. Le message de PostgreSQL porte
        # `DETAIL:  Failing row contains (…)`, c'est-à-dire le souvenir.
        raise HTTPException(
            status_code=422,
            detail={"erreur": "DB CHECK violation", **journal.diagnostic_exception(e)},
        )


async def _fetch_atoms_for_session(
    db: AsyncConnection, session_id: UUID
) -> list[UUID]:
    """SELECT id FROM memory_atoms WHERE session_id = %s ORDER BY created_at ASC.

    Calcul live de `atoms_created` (Q.B Phase 2.4 — pas le champ DDL stocké).
    """
    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT id FROM arac.memory_atoms
            WHERE session_id = %s
            ORDER BY created_at ASC
            """,
            (str(session_id),),
        )
        rows = await cur.fetchall()
    return [row["id"] for row in rows]


def _row_to_session_read(
    row: dict[str, Any], atoms_created: list[UUID]
) -> SessionRead:
    """psycopg dict_row → SessionRead. `summary_embedding` exclu (lourd)."""
    return SessionRead(
        id=row["id"],
        node_id=row["node_id"],
        scope=row["scope"],
        topic=row["topic"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        summary=row["summary"],
        accomplishments=list(row["accomplishments"] or []),
        blockers=list(row["blockers"] or []),
        next_steps=list(row["next_steps"] or []),
        closed_by=row["closed_by"],
        atoms_created=atoms_created,
    )


def _row_to_session_read_with_buffer(
    row: dict[str, Any],
    atoms_created: list[UUID],
    buffer_rows: list[dict[str, Any]],
) -> SessionReadWithBuffer:
    """SessionRead + buffer events ordonnés chronologiquement."""
    base_data = _row_to_session_read(row, atoms_created).model_dump()
    return SessionReadWithBuffer(
        **base_data,
        buffer=[
            SessionBufferEntry(
                session_id=br["session_id"],
                event_type=br["event_type"],
                payload=br["payload"],
                created_at=br["created_at"],
            )
            for br in buffer_rows
        ],
    )


# ============================================================================
# POST /v1/sessions/open
# ============================================================================


@router.post("/open", response_model=SessionRead, status_code=201)
async def open_session(
    payload: SessionOpen,
    db: Annotated[AsyncConnection, Depends(get_db)],
) -> SessionRead:
    """POST /v1/sessions/open — crée nouvelle session ouverte (ended_at IS NULL)."""
    sql = """
        INSERT INTO arac.sessions (node_id, scope, topic)
        VALUES (%s, %s, %s)
        RETURNING *
    """
    params = (payload.node_id, payload.scope.value, payload.topic)

    with _handle_pg_errors():
        async with db.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            row = await cur.fetchone()
    assert row is not None
    return _row_to_session_read(row, atoms_created=[])  # nouvelle session, pas d'atomes


# ============================================================================
# POST /v1/sessions/{id}/append
# ============================================================================


@router.post("/{session_id}/append", status_code=201)
async def append_event(
    session_id: UUID,
    payload: SessionAppendEvent,
    db: Annotated[AsyncConnection, Depends(get_db)],
) -> dict[str, Any]:
    """POST /v1/sessions/{id}/append — append event au session_buffer.

    409 si session déjà closed (ended_at IS NOT NULL). 404 si inexistante.

    Returns: `{ok, session_id, event_type, created_at}`. Pas de buffer_entry_id
    car `arac.session_buffer` n'a pas de PK (append-only log).
    """
    # 1. Check session ouverte
    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT id, ended_at FROM arac.sessions WHERE id = %s",
            (str(session_id),),
        )
        s = await cur.fetchone()
    if s is None:
        raise HTTPException(status_code=404, detail="session not found")
    if s["ended_at"] is not None:
        raise HTTPException(
            status_code=409,
            detail="session already closed, cannot append events",
        )

    # 2. INSERT event
    with _handle_pg_errors():
        async with db.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                INSERT INTO arac.session_buffer (session_id, event_type, payload)
                VALUES (%s, %s, %s::jsonb)
                RETURNING session_id, event_type, payload, created_at
                """,
                (
                    str(session_id),
                    payload.event_type,
                    json.dumps(payload.payload) if payload.payload is not None else None,
                ),
            )
            row = await cur.fetchone()
    assert row is not None
    return {
        "ok": True,
        "session_id": str(row["session_id"]),
        "event_type": row["event_type"],
        "created_at": row["created_at"].isoformat(),
    }


# ============================================================================
# POST /v1/sessions/{id}/close
# ============================================================================


@router.post("/{session_id}/close", response_model=SessionRead)
async def close_session(
    session_id: UUID,
    payload: SessionClose,
    db: Annotated[AsyncConnection, Depends(get_db)],
) -> SessionRead:
    """POST /v1/sessions/{id}/close — close + embed(summary) + UPDATE.

    Mécanique transactionnelle (cf docstring module). embed HORS transaction.
    """
    # 1. SELECT sans FOR UPDATE
    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT id, ended_at FROM arac.sessions WHERE id = %s",
            (str(session_id),),
        )
        s = await cur.fetchone()
    if s is None:
        raise HTTPException(status_code=404, detail="session not found")
    if s["ended_at"] is not None:
        raise HTTPException(
            status_code=409,
            detail=f"session already closed at {s['ended_at']}",
        )

    # 2. embed HORS transaction (~200-300ms, pool DB libre)
    summary_embedding = await embed(payload.summary)

    # 3. Transaction courte : SELECT FOR UPDATE re-check + UPDATE
    with _handle_pg_errors():
        async with db.transaction():
            async with db.cursor(row_factory=dict_row) as cur:
                # Re-check FOR UPDATE — bloque close concurrents
                await cur.execute(
                    "SELECT ended_at FROM arac.sessions WHERE id = %s FOR UPDATE",
                    (str(session_id),),
                )
                check = await cur.fetchone()
                if check is None:
                    raise HTTPException(status_code=404, detail="session disappeared during close")
                if check["ended_at"] is not None:
                    raise HTTPException(
                        status_code=409,
                        detail="session was closed concurrently",
                    )

                # UPDATE close
                await cur.execute(
                    """
                    UPDATE arac.sessions
                    SET ended_at = NOW(),
                        summary = %s,
                        summary_embedding = %s::halfvec(3072),
                        accomplishments = %s,
                        blockers = %s,
                        next_steps = %s,
                        closed_by = %s
                    WHERE id = %s
                    RETURNING *
                    """,
                    (
                        payload.summary,
                        summary_embedding,
                        payload.accomplishments,
                        payload.blockers,
                        payload.next_steps,
                        payload.closed_by.value,
                        str(session_id),
                    ),
                )
                row = await cur.fetchone()
                assert row is not None

    # 4. Calcul atoms_created live (post-commit)
    atoms_created = await _fetch_atoms_for_session(db, session_id)
    return _row_to_session_read(row, atoms_created=atoms_created)


# ============================================================================
# GET /v1/sessions/{id}
# ============================================================================


@router.get("/{session_id}", response_model=SessionReadWithBuffer | SessionRead)
async def get_session(
    session_id: UUID,
    db: Annotated[AsyncConnection, Depends(get_db)],
    include_buffer: bool = Query(default=False),
) -> SessionRead | SessionReadWithBuffer:
    """GET /v1/sessions/{id} — lecture session.

    `include_buffer=true` ajoute la liste des events ordonnés chronologiquement.
    """
    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT * FROM arac.sessions WHERE id = %s",
            (str(session_id),),
        )
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")

    atoms_created = await _fetch_atoms_for_session(db, session_id)

    if not include_buffer:
        return _row_to_session_read(row, atoms_created)

    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT session_id, event_type, payload, created_at
            FROM arac.session_buffer
            WHERE session_id = %s
            ORDER BY created_at ASC
            """,
            (str(session_id),),
        )
        buffer_rows = await cur.fetchall()
    return _row_to_session_read_with_buffer(row, atoms_created, buffer_rows)


# ============================================================================
# GET /v1/sessions (list)
# ============================================================================


@router.get("", response_model=list[SessionRead])
async def list_sessions(
    db: Annotated[AsyncConnection, Depends(get_db)],
    node_id: str | None = None,
    scope: Scope | None = None,
    status: SessionState | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[SessionRead]:
    """GET /v1/sessions — list filtré. ORDER BY started_at DESC.

    `status=open` → `WHERE ended_at IS NULL`.
    `status=closed` → `WHERE ended_at IS NOT NULL`.

    Note dette mineure Phase 2.4 : `atoms_created` calculé en N+1 query
    (1 SELECT par session). Acceptable pour limit=200 max. À optimiser
    Phase 9+ si performance liste devient critique (LEFT JOIN ou subquery
    aggregée).
    """
    sql = "SELECT * FROM arac.sessions WHERE TRUE"
    params: list[Any] = []
    if node_id is not None:
        sql += " AND node_id = %s"
        params.append(node_id)
    if scope is not None:
        sql += " AND scope = %s"
        params.append(scope.value)
    if status is not None:
        if status == SessionState.OPEN:
            sql += " AND ended_at IS NULL"
        else:
            sql += " AND ended_at IS NOT NULL"
    sql += " ORDER BY started_at DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, tuple(params))
        rows = await cur.fetchall()

    results: list[SessionRead] = []
    for row in rows:
        atoms = await _fetch_atoms_for_session(db, row["id"])
        results.append(_row_to_session_read(row, atoms))
    return results
