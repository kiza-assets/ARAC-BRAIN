"""Router dashboard read-only ARAC (Phase D.5 + D.6 I7/I8).

Endpoints exposés (tous GET, aucune écriture) :
  - GET /v1/dashboard/scopes_summary    → list[ScopeSummary]
  - GET /v1/dashboard/atoms_by_scope    → list[AtomSummary]  (filtres scope/limit/offset
                                          + I7 D.6 : tag/status/kind optionnels)
  - GET /v1/dashboard/search            → list[AtomSummary]  (I8 D.6 : full-text ILIKE
                                          simple sur value ; PROSPECTIF Phase D.7+
                                          pour pg_trgm / pgvector recall sémantique)
  - GET /v1/dashboard/timeline          → TimelineData      (param days, clamp 1..365)
  - GET /v1/dashboard/foundations_state → FoundationsState
  - GET /v1/dashboard/ingest_stats      → IngestStats        (v0.5 Bloc I6 :
                                          métriques curator/raw_conversations
                                          sur 7j journaliers + agrégats 30j)
  - GET /v1/dashboard/                  → HTMLResponse (static/dashboard.html)

Doctrine read-only stricte : aucune route POST/PATCH/DELETE. Le dashboard est
un consommateur passif de la BDD ARAC — toute mutation passe par les routers
atoms / sessions / heartbeat existants.

Pas d'embedding exposé (24 KiB/atome — lourd, inutile pour un dashboard).
Les SELECT évitent volontairement la colonne `embedding` ; seuls les champs
nécessaires aux schemas dashboard sont projetés.

Style cohérent avec app/routers/atoms.py :
  - psycopg3 async via `async with db.cursor(row_factory=dict_row)`
  - Dependency injection FastAPI : `db: Annotated[AsyncConnection, Depends(get_db)]`
  - Logger structuré `arac.api.dashboard` (event + métadonnées)
  - Filtres GET via `Query(..., ge=..., le=...)`

Index PG exploités :
  - btree (scope) — implicit via égalité dans WHERE
  - btree (created_at) — pour les agrégats timeline
  - GIN ix_memory_atoms_tags — pour le filtre tag 'pierre-angulaire'
  - ix_memory_atoms_status — partial index status='active'
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app import journal
from app.db import get_db
from app.schemas.atom import Status
from app.schemas.dashboard import (
    AtomSummary,
    DailyStat,
    FoundationAtom,
    FoundationsState,
    IngestDailyPoint,
    IngestStats,
    RecentAudit,
    ScopeSummary,
    TimelineData,
)
from app.schemas.kind import Kind
from app.schemas.scope import Scope

# Tag canonique des atomes pierre-angulaire — miroir routers/atoms.py.
_PIERRE_ANGULAIRE_TAG = "pierre-angulaire"

# Path absolu vers static/dashboard.html. Résolu une seule fois au chargement
# du module pour éviter un Path() à chaque requête (cheap mais utile).
_STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"
_DASHBOARD_HTML_PATH = _STATIC_DIR / "dashboard.html"

# Placeholder servi quand static/dashboard.html n'existe pas encore (B2 ne
# l'a pas écrit). Pas de styling — le frontend B2 viendra le remplacer.
_PLACEHOLDER_HTML = (
    "<!doctype html>\n"
    "<html lang=\"fr\"><head><meta charset=\"utf-8\">"
    "<title>Dashboard ARAC</title></head>"
    "<body><h1>Dashboard ARAC</h1>"
    "<p>Frontend en cours de mise en place (B2). "
    "Les endpoints API sont disponibles sous <code>/v1/dashboard/*</code>.</p>"
    "</body></html>"
)


router = APIRouter()
_logger = logging.getLogger("arac.api.dashboard")


# ============================================================================
# Endpoint 1 — GET /scopes_summary
# ============================================================================


@router.get("/scopes_summary", response_model=list[ScopeSummary])
async def scopes_summary(
    db: Annotated[AsyncConnection, Depends(get_db)],
) -> list[ScopeSummary]:
    """GET /v1/dashboard/scopes_summary — agrégat global par scope.

    Une seule requête SQL avec jsonb_object_agg() pour reconstituer
    by_kind / by_status côté PG (un round-trip, agrégation déléguée à
    PostgreSQL). Tri par total_atoms DESC, puis scope ASC pour stabilité.

    Tous statuts inclus (active, draft, superseded, archived,
    low_confidence_archive) — le dashboard expose l'état complet, le
    filtrage doit se faire côté frontend si désiré.
    """
    sql = """
        WITH per_kind AS (
            SELECT scope, kind, COUNT(*) AS n
            FROM arac.memory_atoms
            GROUP BY scope, kind
        ),
        per_status AS (
            SELECT scope, status, COUNT(*) AS n
            FROM arac.memory_atoms
            GROUP BY scope, status
        ),
        per_scope AS (
            SELECT scope,
                   COUNT(*)                       AS total_atoms,
                   MIN(created_at)                AS first_atom_date,
                   MAX(created_at)                AS last_atom_date
            FROM arac.memory_atoms
            GROUP BY scope
        )
        SELECT s.scope,
               s.total_atoms,
               s.first_atom_date,
               s.last_atom_date,
               COALESCE(
                   (SELECT jsonb_object_agg(kind, n)
                    FROM per_kind k WHERE k.scope = s.scope),
                   '{}'::jsonb
               ) AS by_kind,
               COALESCE(
                   (SELECT jsonb_object_agg(status, n)
                    FROM per_status st WHERE st.scope = s.scope),
                   '{}'::jsonb
               ) AS by_status
        FROM per_scope s
        ORDER BY s.total_atoms DESC, s.scope ASC
    """
    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql)
        rows = await cur.fetchall()

    results: list[ScopeSummary] = []
    for row in rows:
        # row["by_kind"] / by_status arrivent en dict natif (psycopg3 JSONB → dict).
        # Les valeurs sont des int natifs PG.
        results.append(
            ScopeSummary(
                scope=row["scope"],
                total_atoms=int(row["total_atoms"]),
                by_kind={k: int(v) for k, v in (row["by_kind"] or {}).items()},
                by_status={k: int(v) for k, v in (row["by_status"] or {}).items()},
                first_atom_date=row["first_atom_date"],
                last_atom_date=row["last_atom_date"],
            )
        )

    _logger.info(
        "dashboard.scopes_summary",
        extra={"event": "ready", "scope_count": len(results)},
    )
    return results


# ============================================================================
# Endpoint 2 — GET /atoms_by_scope
# ============================================================================


@router.get("/atoms_by_scope", response_model=list[AtomSummary])
async def atoms_by_scope(
    db: Annotated[AsyncConnection, Depends(get_db)],
    scope: Scope,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    tag: str | None = Query(None, max_length=64),
    status: Status | None = Query(None),
    kind: Kind | None = Query(None),
) -> list[AtomSummary]:
    """GET /v1/dashboard/atoms_by_scope — atomes d'un scope (pagination + filtres).

    Projection légère : pas d'embedding, pas de desc_hash, pas de source_ref.
    Tri par created_at DESC (les plus récents en premier) — la valeur par
    défaut la plus utile pour un dashboard.

    `scope` est obligatoire (validation Pydantic via Enum) — un GET sans
    scope retournerait 422.

    Filtres optionnels (Phase D.6 I7) :
      - `tag` : appartenance via `tag = ANY(tags)` (index GIN ix_memory_atoms_tags).
      - `status` : égalité (enum Status, validation Pydantic — 422 si hors enum).
      - `kind`   : égalité (enum Kind, idem).

    Pattern SQL : guard `(%s::text IS NULL OR <pred>)` répété par filtre,
    param-bound psycopg3 (pas de concat). Si un filtre est NULL, le guard
    court-circuite et le prédicat n'est pas évalué.
    """
    sql = """
        SELECT id, kind, scope, key, value, tags, status, confidence,
               created_at, updated_at, version
        FROM arac.memory_atoms
        WHERE scope = %s
          AND (%s::text IS NULL OR %s = ANY(tags))
          AND (%s::text IS NULL OR status = %s)
          AND (%s::text IS NULL OR kind = %s)
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """
    scope_val = scope.value
    status_val = status.value if status else None
    kind_val = kind.value if kind else None

    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            sql,
            (
                scope_val,
                tag, tag,
                status_val, status_val,
                kind_val, kind_val,
                limit, offset,
            ),
        )
        rows = await cur.fetchall()

    results = [
        AtomSummary(
            id=row["id"],
            kind=row["kind"],
            scope=row["scope"],
            key=row["key"],
            value=row["value"],
            tags=list(row["tags"] or []),
            status=row["status"],
            confidence=row["confidence"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            version=row["version"],
        )
        for row in rows
    ]

    _logger.info(
        "dashboard.atoms_by_scope",
        extra={
            "event": "ready",
            # Le domaine en empreinte : `dashboard.atoms_by_scope` nommait en
            # clair, à chaque consultation, le pan de vie qu'on regardait.
            "scope_sha8": journal.sha8(scope.value),
            "limit": limit,
            "offset": offset,
            "tag": tag,
            "status": status_val,
            "kind": kind_val,
            "result_count": len(results),
        },
    )
    return results


# ============================================================================
# Endpoint 2bis — GET /search (I8 D.6) — full-text ILIKE simple
# ============================================================================


@router.get("/search", response_model=list[AtomSummary])
async def search(
    db: Annotated[AsyncConnection, Depends(get_db)],
    q: str = Query(..., min_length=1, max_length=200),
    scope: Scope | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
) -> list[AtomSummary]:
    """GET /v1/dashboard/search — recherche full-text simple ILIKE sur `value`.

    Phase D.6 (I8) : ILIKE substring case-insensitive, param-bound psycopg3
    (sécurisé contre injection, le % englobant est appliqué sur la valeur
    de paramètre — pas concaténé dans le SQL).

    Filtre optionnel `scope` (enum) → 422 si hors-enum.

    Tri par created_at DESC, LIMIT clamp 1..100.

    PROSPECTIF Phase D.7+ :
      - pg_trgm pour fuzzy match (similarity / GIN trigram index).
      - pgvector recall sémantique via colonne embedding (déjà indexée).
      Cet endpoint reste volontairement minimaliste pour D.6 — il sert
      de base UX, l'évolution sémantique se branchera plus tard sans
      casser le contrat (signature stable).
    """
    sql = """
        SELECT id, kind, scope, key, value, tags, status, confidence,
               created_at, updated_at, version
        FROM arac.memory_atoms
        WHERE value ILIKE %s
          AND (%s::text IS NULL OR scope = %s)
        ORDER BY created_at DESC
        LIMIT %s
    """
    pattern = "%" + q + "%"
    scope_val = scope.value if scope else None

    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, (pattern, scope_val, scope_val, limit))
        rows = await cur.fetchall()

    results = [
        AtomSummary(
            id=row["id"],
            kind=row["kind"],
            scope=row["scope"],
            key=row["key"],
            value=row["value"],
            tags=list(row["tags"] or []),
            status=row["status"],
            confidence=row["confidence"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            version=row["version"],
        )
        for row in rows
    ]

    _logger.info(
        "dashboard.search",
        extra={
            "event": "ready",
            "q_len": len(q),
            "scope_sha8": journal.sha8(scope_val),
            "limit": limit,
            "result_count": len(results),
        },
    )
    return results


# ============================================================================
# Endpoint 3 — GET /timeline
# ============================================================================


@router.get("/timeline", response_model=TimelineData)
async def timeline(
    db: Annotated[AsyncConnection, Depends(get_db)],
    days: int = Query(30, ge=1, le=365),
) -> TimelineData:
    """GET /v1/dashboard/timeline — stats journalières sur `days` derniers jours.

    Construction :
      1. generate_series : une ligne par jour civil [start_date, end_date]
         (pas de gap si aucun atome créé ce jour-là).
      2. LEFT JOIN sur arac.memory_atoms grouped by created_at::date.
      3. COUNT FILTER WHERE pour created / superseded / archived.
      4. jsonb_object_agg(kind, count) pour by_kind ce jour.

    Bornes [start_date, end_date] inclusives. `days=30` couvre par exemple
    aujourd'hui + 29 jours en arrière.

    Tous statuts confondus dans by_kind (vue de production : ce qui a été
    créé, pas ce qui est actuellement actif).
    """
    end_dt = datetime.now(timezone.utc).date()
    start_dt = end_dt - timedelta(days=days - 1)

    sql = """
        WITH dates AS (
            SELECT generate_series(
                       %s::date, %s::date, INTERVAL '1 day'
                   )::date AS d
        ),
        atoms_day AS (
            SELECT created_at::date AS d, kind, status
            FROM arac.memory_atoms
            WHERE created_at::date BETWEEN %s::date AND %s::date
        ),
        per_kind_day AS (
            SELECT d, jsonb_object_agg(kind, n) AS by_kind
            FROM (
                SELECT d, kind, COUNT(*) AS n
                FROM atoms_day
                GROUP BY d, kind
            ) k
            GROUP BY d
        )
        SELECT dates.d AS d,
               COUNT(a.d) FILTER (WHERE a.status = 'active')     AS created,
               COUNT(a.d) FILTER (WHERE a.status = 'superseded') AS superseded,
               COUNT(a.d) FILTER (
                   WHERE a.status IN ('archived', 'low_confidence_archive')
               )                                                 AS archived,
               COALESCE(pk.by_kind, '{}'::jsonb)                 AS by_kind
        FROM dates
        LEFT JOIN atoms_day a    ON a.d = dates.d
        LEFT JOIN per_kind_day pk ON pk.d = dates.d
        GROUP BY dates.d, pk.by_kind
        ORDER BY dates.d ASC
    """
    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, (start_dt, end_dt, start_dt, end_dt))
        rows = await cur.fetchall()

    daily_stats = [
        DailyStat(
            date=row["d"].isoformat(),
            created=int(row["created"]),
            superseded=int(row["superseded"]),
            archived=int(row["archived"]),
            by_kind={k: int(v) for k, v in (row["by_kind"] or {}).items()},
        )
        for row in rows
    ]

    _logger.info(
        "dashboard.timeline",
        extra={
            "event": "ready",
            "period_days": days,
            "start_date": start_dt.isoformat(),
            "end_date": end_dt.isoformat(),
            "row_count": len(daily_stats),
        },
    )

    return TimelineData(
        period_days=days,
        start_date=start_dt.isoformat(),
        end_date=end_dt.isoformat(),
        daily_stats=daily_stats,
    )


# ============================================================================
# Endpoint 4 — GET /foundations_state
# ============================================================================


@router.get("/foundations_state", response_model=FoundationsState)
async def foundations_state(
    db: Annotated[AsyncConnection, Depends(get_db)],
) -> FoundationsState:
    """GET /v1/dashboard/foundations_state — vue d'ensemble des atomes pierre-angulaire.

    Trois requêtes :
      A. Agrégats by_kind / by_scope sur les foundations active (1 SQL,
         jsonb_object_agg par axe).
      B. Liste complète des foundations (FoundationAtom light view), tri
         kind value ASC puis key ASC (cohérent avec ordre déterministe,
         pas le KIND_ORDER applicatif — le frontend pourra re-trier).
      C. 20 derniers audit_links (toutes priorités) ORDER BY created_at DESC.

    Note : on n'utilise pas l'ordre KIND_ORDER ici pour rester découplé de
    la doctrine retrieval — le dashboard est consommateur, pas producteur
    de doctrine. Tri lexicographique kind ASC + key ASC reste stable et
    interprétable côté frontend.
    """
    sql_agg = """
        WITH f AS (
            SELECT kind, scope
            FROM arac.memory_atoms
            WHERE status = 'active'
              AND tags @> ARRAY[%s]::text[]
        )
        SELECT
            (SELECT COUNT(*) FROM f)                                AS total_foundations,
            COALESCE(
                (SELECT jsonb_object_agg(kind, n)
                 FROM (SELECT kind, COUNT(*) AS n FROM f GROUP BY kind) x),
                '{}'::jsonb
            )                                                       AS by_kind,
            COALESCE(
                (SELECT jsonb_object_agg(scope, n)
                 FROM (SELECT scope, COUNT(*) AS n FROM f GROUP BY scope) x),
                '{}'::jsonb
            )                                                       AS by_scope
    """
    sql_list = """
        SELECT id, kind, scope, key, value, created_at
        FROM arac.memory_atoms
        WHERE status = 'active'
          AND tags @> ARRAY[%s]::text[]
        ORDER BY kind ASC, key ASC
    """
    sql_audits = """
        SELECT al.id, al.kind, al.target_atom_id, al.audit_source, al.created_at
        FROM arac.audit_links al
        ORDER BY al.created_at DESC
        LIMIT 20
    """

    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql_agg, (_PIERRE_ANGULAIRE_TAG,))
        agg = await cur.fetchone()
        await cur.execute(sql_list, (_PIERRE_ANGULAIRE_TAG,))
        list_rows = await cur.fetchall()
        await cur.execute(sql_audits)
        audit_rows = await cur.fetchall()

    # agg garanti non-None : la requête WITH retourne toujours une ligne
    # (même si f est vide → total_foundations=0, by_kind={}, by_scope={}).
    assert agg is not None

    foundations = [
        FoundationAtom(
            id=row["id"],
            kind=row["kind"],
            scope=row["scope"],
            key=row["key"],
            value=row["value"],
            created_at=row["created_at"],
        )
        for row in list_rows
    ]
    recent_audits = [
        RecentAudit(
            id=row["id"],
            kind=row["kind"],
            target_atom_id=row["target_atom_id"],
            audit_source=row["audit_source"],
            created_at=row["created_at"],
        )
        for row in audit_rows
    ]

    state = FoundationsState(
        total_foundations=int(agg["total_foundations"]),
        by_kind={k: int(v) for k, v in (agg["by_kind"] or {}).items()},
        by_scope={k: int(v) for k, v in (agg["by_scope"] or {}).items()},
        foundations=foundations,
        recent_audits=recent_audits,
    )

    _logger.info(
        "dashboard.foundations_state",
        extra={
            "event": "ready",
            "total_foundations": state.total_foundations,
            "recent_audits_count": len(recent_audits),
        },
    )
    return state


# ============================================================================
# Endpoint 5 — GET /ingest_stats (v0.5 Bloc I6 — Ingest Health)
# ============================================================================
# Convention tag : 'curator-extracted' (A5, cf D4 §7.1) — atomes posés par
# l'agent curator portent ce tag. Le filtre exploite l'index GIN existant
# ix_memory_atoms_tags (zéro DDL ajouté côté v0.5 I6).
# Approximation M7 (D4 §7.2) : `archived_reason` n'existe pas, on assimile
# « post-mortem 30j » à status IN ('archived','low_confidence_archive') +
# updated_at > now()-30d (acceptée comme dette doctrinale).

# Tag canonique des atomes générés par l'agent curator (A5 v0.5).
_CURATOR_EXTRACTED_TAG = "curator-extracted"


@router.get("/ingest_stats", response_model=IngestStats)
async def ingest_stats(
    db: Annotated[AsyncConnection, Depends(get_db)],
) -> IngestStats:
    """GET /v1/dashboard/ingest_stats — métriques curator + raw_conversations.

    Deux requêtes SQL (cf D4 §3.4) :

    A. Série journalière 7j via `generate_series` + LEFT JOIN — garantit la
       continuité (jours zéros présents, pas de gap). M1 (bundles received),
       M2 (messages total), M3 (atoms_generated par jour de curation).

    B. Agrégats globaux : M5 (last_successful_ingest), M6 (failed_bundles_7d),
       M7 numerator + denominator (atoms curator-extracted archivés vs créés
       sur 30j).

    Ratios M4 (atoms/messages 7j) et M7 (archived_ratio 30j) calculés en
    Python — None quand le dénominateur est zéro (anti-fabulation, le front
    affichera « n/a »).

    Period_days fixé à 7 (la série journalière). M7 utilise une fenêtre 30j
    distincte (post-mortem long terme).
    """
    period_days = 7

    sql_daily = """
        WITH dates AS (
            SELECT generate_series(
                (now() - interval '6 days')::date,
                now()::date,
                interval '1 day'
            )::date AS d
        )
        SELECT
            dates.d AS day,
            COALESCE((
                SELECT COUNT(*)
                FROM arac.raw_conversations rc
                WHERE rc.received_at::date = dates.d
            ), 0) AS bundles_received,
            COALESCE((
                SELECT SUM(rc.message_count)
                FROM arac.raw_conversations rc
                WHERE rc.received_at::date = dates.d
            ), 0) AS messages_total,
            COALESCE((
                SELECT SUM(rc.atoms_generated)
                FROM arac.raw_conversations rc
                WHERE rc.curated_at::date = dates.d
            ), 0) AS atoms_generated
        FROM dates
        ORDER BY dates.d ASC
    """

    sql_aggregate = """
        SELECT
            (SELECT MAX(curated_at)
               FROM arac.raw_conversations
              WHERE status = 'curated')                      AS last_successful_ingest,
            (SELECT COUNT(*)
               FROM arac.raw_conversations
              WHERE status = 'failed'
                AND received_at > now() - interval '7 days') AS failed_bundles_7d,
            (SELECT COUNT(*)
               FROM arac.memory_atoms
              WHERE status IN ('archived', 'low_confidence_archive')
                AND tags @> ARRAY[%s]::text[]
                AND updated_at > now() - interval '30 days') AS archived_by_curator_30d,
            (SELECT COUNT(*)
               FROM arac.memory_atoms
              WHERE tags @> ARRAY[%s]::text[]
                AND created_at > now() - interval '30 days') AS created_by_curator_30d
    """

    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql_daily)
        daily_rows = await cur.fetchall()
        await cur.execute(
            sql_aggregate,
            (_CURATOR_EXTRACTED_TAG, _CURATOR_EXTRACTED_TAG),
        )
        agg = await cur.fetchone()

    # agg toujours non-None : requête à 4 sous-SELECT retourne 1 ligne même
    # si tables vides (NULL ou 0 selon COUNT/MAX).
    assert agg is not None

    daily = [
        IngestDailyPoint(
            date=row["day"].isoformat(),
            bundles_received=int(row["bundles_received"]),
            messages_total=int(row["messages_total"]),
            atoms_generated=int(row["atoms_generated"]),
        )
        for row in daily_rows
    ]

    total_messages_7d = sum(p.messages_total for p in daily)
    total_atoms_7d = sum(p.atoms_generated for p in daily)
    ratio_atoms_per_message: float | None
    if total_messages_7d > 0:
        ratio_atoms_per_message = total_atoms_7d / total_messages_7d
    else:
        ratio_atoms_per_message = None

    archived = int(agg["archived_by_curator_30d"] or 0)
    created = int(agg["created_by_curator_30d"] or 0)
    archived_ratio: float | None = (archived / created) if created > 0 else None

    stats = IngestStats(
        period_days=period_days,
        daily=daily,
        ratio_atoms_per_message=ratio_atoms_per_message,
        last_successful_ingest=agg["last_successful_ingest"],
        failed_bundles_7d=int(agg["failed_bundles_7d"] or 0),
        archived_by_curator_30d=archived,
        created_by_curator_30d=created,
        archived_ratio=archived_ratio,
    )

    _logger.info(
        "dashboard.ingest_stats",
        extra={
            "event": "ready",
            "period_days": period_days,
            "daily_points": len(daily),
            "failed_bundles_7d": stats.failed_bundles_7d,
            "archived_by_curator_30d": archived,
            "created_by_curator_30d": created,
        },
    )
    return stats


# ============================================================================
# Endpoint 6 — GET /  (HTML dashboard frontend, sert static/dashboard.html)
# ============================================================================


@router.get("/", response_class=HTMLResponse)
async def dashboard_root() -> HTMLResponse:
    """GET /v1/dashboard/ — sert le frontend HTML (B2).

    Lit static/dashboard.html depuis le repo (mounté aussi via app.mount
    /static dans main.py). Si le fichier n'existe pas encore (B2 pas
    encore livré), retourne un placeholder minimal — pas de 404, pour
    permettre aux endpoints API d'être démontrables sans dépendre de B2.
    """
    try:
        content = _DASHBOARD_HTML_PATH.read_text(encoding="utf-8")
        _logger.info(
            "dashboard.html.served",
            extra={"event": "ready", "source": "static/dashboard.html"},
        )
        return HTMLResponse(content=content, status_code=200)
    except FileNotFoundError:
        _logger.info(
            "dashboard.html.placeholder",
            extra={
                "event": "ready",
                "source": "placeholder",
                "reason": "static/dashboard.html absent (B2 non livré)",
            },
        )
        return HTMLResponse(content=_PLACEHOLDER_HTML, status_code=200)
