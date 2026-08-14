"""Pydantic models pour le dashboard read-only ARAC (Phase D.5).

Tous les modèles ci-dessous sont des **outputs** (response_model) — le
dashboard n'expose que des GET, aucun POST/PATCH/DELETE. Les structures sont
calquées sur les agrégations SQL côté `app/routers/dashboard.py` : un schéma
par endpoint, plus quelques sous-structures partagées (DailyStat, etc.).

Convention Pydantic v2 : `ConfigDict(extra="forbid", str_strip_whitespace=True)`
pour cohérence avec `app/schemas/atom.py`. `use_enum_values=False` pour garder
les Kind/Scope/Status comme objets côté lecture.

Pas d'embedding exposé (24 KiB/atome — lourd, inutile pour un dashboard).

Sources de vérité :
- `arac.memory_atoms` (kind, scope, key, value, tags, status, confidence,
  created_at, updated_at, version)
- `arac.audit_links` (recent_audits : kind, target_atom_id, audit_source,
  created_at)
- Tag canonique des foundations : 'pierre-angulaire'.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.atom import AuditSource, Confidence, Status
from app.schemas.kind import Kind
from app.schemas.scope import Scope


# ============================================================================
# Configuration Pydantic commune (miroir atom.py)
# ============================================================================

_COMMON_CONFIG = ConfigDict(
    str_strip_whitespace=True,
    validate_assignment=True,
    extra="forbid",
    use_enum_values=False,
)


# ============================================================================
# Endpoint 1 — GET /v1/dashboard/scopes_summary
# ============================================================================


class ScopeSummary(BaseModel):
    """Agrégat par scope : total atomes + ventilation par kind / status.

    `by_kind` et `by_status` sont des dicts `<value>: count` — clés des
    enums (Kind.value, Status.value) pour faciliter la sérialisation
    JSON côté frontend (pas d'objet Enum dans la response).

    `first_atom_date` / `last_atom_date` : None si le scope n'a aucun
    atome (cas marginal — le SELECT côté router filtre déjà sur les
    scopes ayant au moins un atome, mais on garde la nullabilité par
    robustesse défensive).
    """

    model_config = _COMMON_CONFIG

    scope: Scope
    total_atoms: int = Field(ge=0)
    by_kind: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)
    first_atom_date: datetime | None = None
    last_atom_date: datetime | None = None


# ============================================================================
# Endpoint 2 — GET /v1/dashboard/atoms_by_scope
# ============================================================================


class AtomSummary(BaseModel):
    """Variante allégée de AtomRead pour le dashboard.

    Champs exposés (read-only, sans embedding ni desc_hash ni source_ref) :
    id, kind, scope, key, value, tags, status, confidence, created_at,
    updated_at, version.

    `value` retourné intégral — le frontend pourra tronquer côté UI selon
    le besoin (preview vs détail). Garde la sémantique d'un payload léger
    sans pour autant tronquer arbitrairement côté backend.
    """

    model_config = _COMMON_CONFIG

    id: UUID
    kind: Kind
    scope: Scope
    key: str
    value: str
    tags: list[str] = Field(default_factory=list)
    status: Status
    confidence: Confidence
    created_at: datetime
    updated_at: datetime
    version: int


# ============================================================================
# Endpoint 3 — GET /v1/dashboard/timeline
# ============================================================================


class DailyStat(BaseModel):
    """Une journée de stats agrégée.

    `date` au format ISO 'YYYY-MM-DD' (string, pas datetime — c'est une
    date civile sans timezone, agrégat sur created_at::date côté SQL).

    `created` / `superseded` / `archived` : compteurs basés sur status
    courant des atomes créés ce jour-là. Un atome créé puis superseded
    le même jour comptera dans `superseded`, pas dans `created` (le SQL
    fait un `COUNT FILTER WHERE status = ...`).

    `by_kind` : dict `<kind.value>: count` pour ce jour (tous statuts
    confondus). Permet au frontend de tracer une stacked area chart.
    """

    model_config = _COMMON_CONFIG

    date: str
    created: int = Field(ge=0)
    superseded: int = Field(ge=0)
    archived: int = Field(ge=0)
    by_kind: dict[str, int] = Field(default_factory=dict)


class TimelineData(BaseModel):
    """Réponse complète de l'endpoint timeline.

    `period_days` echo du paramètre `days` (default 30, clamp côté router).
    `start_date` / `end_date` : bornes ISO 'YYYY-MM-DD' de la fenêtre.
    `daily_stats` : liste ordonnée par date ASC, une entrée par jour
    civil dans [start_date, end_date]. Les jours sans atome créé sont
    présents avec des compteurs à 0 (continuité de la série pour le
    frontend — pas de gaps).
    """

    model_config = _COMMON_CONFIG

    period_days: int = Field(ge=1)
    start_date: str
    end_date: str
    daily_stats: list[DailyStat] = Field(default_factory=list)


# ============================================================================
# Endpoint 4 — GET /v1/dashboard/foundations_state
# ============================================================================


class FoundationAtom(BaseModel):
    """Atome pierre-angulaire (light view) — pour la liste foundations[].

    Pas de tags ni de confidence ici : on a déjà filtré sur le tag
    'pierre-angulaire', pas de plus-value à le ré-exposer.
    `value` exposé entier — un frontend pourra tronquer.
    """

    model_config = _COMMON_CONFIG

    id: UUID
    kind: Kind
    scope: Scope
    key: str
    value: str
    created_at: datetime


class RecentAudit(BaseModel):
    """Entrée légère de audit_links pour la liste recent_audits[].

    `id` = audit_links.id (UUID). `kind` ∈ {alert, validation, contradiction,
    suggestion} (sous-ensemble auditeur). `target_atom_id` : UUID nullable
    (pas de FK côté DDL — forensic, tolère orphelins après hard-delete).
    `audit_source` ∈ {interactive_human_validated, autonomous_agent_suggest}.
    """

    model_config = _COMMON_CONFIG

    id: UUID
    kind: Kind
    target_atom_id: UUID | None
    audit_source: AuditSource
    created_at: datetime


class FoundationsState(BaseModel):
    """État des atomes pierre-angulaire — les savoirs que vous avez désignés
    comme irremplaçables.

    `total_foundations` : count global (status='active' AND tags @>
    ARRAY['pierre-angulaire']).
    `by_kind` / `by_scope` : dict `<value>: count` pour la ventilation.
    `foundations` : liste des FoundationAtom (tri KIND_ORDER puis key ASC,
    miroir de l'endpoint /v1/atoms/foundations existant).
    `recent_audits` : 20 derniers audit_links toutes priorités confondues
    (ORDER BY created_at DESC LIMIT 20 côté router).
    """

    model_config = _COMMON_CONFIG

    total_foundations: int = Field(ge=0)
    by_kind: dict[str, int] = Field(default_factory=dict)
    by_scope: dict[str, int] = Field(default_factory=dict)
    foundations: list[FoundationAtom] = Field(default_factory=list)
    recent_audits: list[RecentAudit] = Field(default_factory=list)


# ============================================================================
# Endpoint 5 — GET /v1/dashboard/ingest_stats (v0.5 Bloc I6)
# ============================================================================
# PROSPECTIF — endpoint « Ingest Health » spécifié, pas encore implémenté.
# Source data : arac.raw_conversations (migration 0008) + arac.memory_atoms
# filtrés par convention tag 'curator-extracted' (A5 — atomes posés par le
# curator portent ce tag pour distinguer leur origine, cf D4 blocage §7.1).
#
# Décision D4 §7.2 : `archived_reason` n'existe pas. M7 (archivés post-mortem)
# est approximé par status IN ('archived','low_confidence_archive') + tag
# curator-extracted + updated_at récent (acceptée comme dette doctrinale).


class IngestDailyPoint(BaseModel):
    """Une journée de stats ingest curator.

    `date` au format ISO 'YYYY-MM-DD' (date civile UTC).
    `bundles_received` : M1 — COUNT raw_conversations.received_at::date = day.
    `messages_total` : M2 — SUM(message_count) sur les bundles reçus ce jour.
    `atoms_generated` : M3 — SUM(atoms_generated) sur les bundles curés ce
    jour (group by curated_at::date — donc un bundle reçu hier mais curé
    aujourd'hui compte aujourd'hui).
    """

    model_config = _COMMON_CONFIG

    date: str
    bundles_received: int = Field(ge=0)
    messages_total: int = Field(ge=0)
    atoms_generated: int = Field(ge=0)


class IngestStats(BaseModel):
    """Réponse complète de l'endpoint ingest_stats — métriques curator.

    Métriques exposées (cf doc 04 §"Métriques exposées dashboard" + D4 §2.3) :

    - `daily` : série 7j (M1+M2+M3) avec continuité (jours zéros si aucune
      activité — pas de gap).
    - `ratio_atoms_per_message` (M4) : sum(atoms_generated)/sum(messages_total)
      sur les 7j. None si messages_total cumulé = 0 (division par zéro).
    - `last_successful_ingest` (M5) : MAX(curated_at) WHERE status='curated'.
      None si aucune ingest jamais curée.
    - `failed_bundles_7d` (M6) : COUNT WHERE status='failed' AND received_at
      > now()-7d.
    - `archived_by_curator_30d` (M7 numerator) : COUNT memory_atoms
      curator-extracted, status archived/low_confidence_archive, updated_at
      > now()-30d. APPROXIMATION (D4 §7.2 — archived_reason absent).
    - `created_by_curator_30d` (M7 denominator) : COUNT memory_atoms
      curator-extracted, created_at > now()-30d.
    - `archived_ratio` (M7) : archived/created sur 30j. None si created=0.

    Anti-fabulation : tous les ratios sont None quand le dénominateur est
    nul — le frontend affiche « n/a » sans inventer de valeur.
    """

    model_config = _COMMON_CONFIG

    period_days: int = Field(ge=1)
    daily: list[IngestDailyPoint] = Field(default_factory=list)
    ratio_atoms_per_message: float | None = None
    last_successful_ingest: datetime | None = None
    failed_bundles_7d: int = Field(ge=0)
    archived_by_curator_30d: int = Field(ge=0)
    created_by_curator_30d: int = Field(ge=0)
    archived_ratio: float | None = None


# ============================================================================
# Sentinelles assert au chargement — garde-fous de cohérence
# ============================================================================
# Pas de dépendance enum-count ici (déjà couvert par schemas/kind.py et
# schemas/scope.py au chargement). Le simple fait d'importer ces schémas
# déclenche les sentinelles upstream.

_ = (Kind, Scope, Status, Confidence, AuditSource)  # keep imports referenced

# Type hint helper pour annotation côté router (évite import circulaire)
_DashboardAny = Any  # noqa: F841 — réservé extension future
