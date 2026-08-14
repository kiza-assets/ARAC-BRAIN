"""Modèles Pydantic v2 pour `arac.memory_atoms` — création, lecture, mise à
jour, supersedure.

DDL de référence : `db/migrations/01_init.sql`, table `arac.memory_atoms`.
Validation alignée sur les CHECK constraints
PostgreSQL (vérifiées via `pg_constraint` 2026-05-10).

Modèles publics :
- `AtomCreate`     — POST /v1/atoms
- `AtomRead`       — GET /v1/atoms/{id} et listes
- `AtomUpdate`     — PATCH /v1/atoms/{id} (partial, scope/kind/key immutables)
- `AtomSupersede`  — POST /v1/atoms/{id}/supersede (versionnage strict, stack v2 §5)

Convention héritage / remplacement (AtomSupersede uniquement) :
- `None`     → hérite du champ de l'atome remplacé
- `[]`/`{}` → remplace par valeur vide explicite

Le scope est validé contre une énumération FERMÉE : un scope inventé part
en 422 avant d'atteindre la base.
"""

from datetime import datetime
from enum import Enum
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.kind import (
    AUDITOR_KINDS,
    Kind,
    PRODUCER_KINDS,
    RATIONALE_REQUIRED_KINDS,
)
from app.schemas.scope import Scope


# ============================================================================
# Enums secondaires (3) — miroir BDD CHECK constraints
# ============================================================================
# Définis ici (atom.py) tant qu'ils ne servent qu'à atom.py. YAGNI : refactor
# en `app/schemas/enums.py` si sessions.py (Phase 2.4) ou audit.py les
# réutilisent.


class Status(str, Enum):
    """Status d'un atome (`memory_atoms_status_check` BDD)."""

    ACTIVE = "active"                                  # atome courant utilisable
    DRAFT = "draft"                                    # brouillon non validé
    SUPERSEDED = "superseded"                          # remplacé par un autre atome
    ARCHIVED = "archived"                              # archivé manuellement
    LOW_CONFIDENCE_ARCHIVE = "low_confidence_archive"  # archivé par garbage_collector cron


class Confidence(str, Enum):
    """Niveau de confiance d'un atome (`memory_atoms_confidence_check` BDD)."""

    PRODUCER = "producer"                       # écrit par humain ou agent producer
    AUDITOR_VALIDATED = "auditor_validated"     # validé par auditeur (interactif)
    AGENT_SUGGEST = "agent_suggest"             # suggestion agent autonome non validée


class AuditSource(str, Enum):
    """Source d'un atome auditeur (`memory_atoms_audit_source_check` BDD).

    NULL en DB pour les atomes producteurs ; obligatoire (NOT NULL applicatif)
    pour les atomes auditeurs — cf validator `_audit_source_consistency`.
    """

    INTERACTIVE_HUMAN_VALIDATED = "interactive_human_validated"
    AUTONOMOUS_AGENT_SUGGEST = "autonomous_agent_suggest"


# ============================================================================
# Constantes
# ============================================================================

# Regex `key` — miroir BDD CHECK `arac.memory_atoms.key ~ '^[a-z0-9][a-z0-9-]*[a-z0-9]$'`
# Implique min_length=2 (start + end requis). Max imposé applicativement (128).
_KEY_PATTERN = r"^[a-z0-9][a-z0-9-]*[a-z0-9]$"
_KEY_MAX_LENGTH = 128

KeyField = Annotated[
    str,
    Field(pattern=_KEY_PATTERN, min_length=2, max_length=_KEY_MAX_LENGTH),
]


# ============================================================================
# Configuration Pydantic commune
# ============================================================================

_COMMON_CONFIG = ConfigDict(
    str_strip_whitespace=True,    # trim auto sur strings
    validate_assignment=True,     # re-valide à chaque assignement post-init
    extra="forbid",               # rejette champs inconnus (anti-fabulation API)
    use_enum_values=False,        # garde Kind/Scope/Status comme objets, pas strings
)


# ============================================================================
# Modèle de base (interne, mixin)
# ============================================================================


class AtomBase(BaseModel):
    """Base interne — champs communs à AtomCreate et AtomRead.

    Pas instanciable directement par l'API : utiliser AtomCreate (input) ou
    AtomRead (output) selon le sens du trafic.
    """

    model_config = _COMMON_CONFIG

    kind: Kind
    scope: Scope
    key: KeyField
    value: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    confidence_score: int | None = Field(default=None, ge=0, le=100)
    source_ref: dict[str, Any] | None = None
    rationale: str | None = None


# ============================================================================
# AtomCreate — POST /v1/atoms
# ============================================================================


class AtomCreate(AtomBase):
    """Input de création d'un atome.

    Champs auto-générés côté service / DB (NON exposés ici) :
    - `id` (UUID PK auto)
    - `embedding` (généré par app.services.embeddings.embed(value))
    - `desc_hash` (sha256(scope|kind|key|value), généré par le router)
    - `status` (DB default 'active')
    - `superseded_by` (None à la création)
    - `version` (default 1)
    - `created_at`, `updated_at` (DB DEFAULT NOW + trigger)

    Validators custom :
    - `_rationale_required`     — rationale non vide pour kind=decision
    - `_audit_source_consistency` — audit_source obligatoire pour AUDITOR,
                                     interdit pour PRODUCER
    - `_confidence_consistency`  — cohérence kind/audit_source/confidence
    """

    model_config = _COMMON_CONFIG

    confidence: Confidence = Confidence.PRODUCER
    audit_source: AuditSource | None = None
    node_id: str = Field(min_length=1)
    session_id: UUID | None = None

    # ------------------------------------------------------------------
    # Validators applicatifs (non DDL)
    # ------------------------------------------------------------------

    @model_validator(mode="after")
    def _rationale_required(self) -> "AtomCreate":
        """`rationale` obligatoire pour kinds dans RATIONALE_REQUIRED_KINDS (DECISION)."""
        if self.kind in RATIONALE_REQUIRED_KINDS and not (self.rationale or "").strip():
            raise ValueError(
                f"`rationale` est obligatoire pour kind={self.kind.value} "
                f"(stack v2 §2.4 : 'rationale obligatoire pour decision via app logic')"
            )
        return self

    @model_validator(mode="after")
    def _audit_source_consistency(self) -> "AtomCreate":
        """`audit_source` obligatoire pour AUDITOR, interdit pour PRODUCER."""
        if self.kind in AUDITOR_KINDS and self.audit_source is None:
            raise ValueError(
                f"`audit_source` obligatoire pour kind auditeur ({self.kind.value})"
            )
        if self.kind in PRODUCER_KINDS and self.audit_source is not None:
            raise ValueError(
                f"`audit_source` interdit pour kind producteur ({self.kind.value})"
            )
        return self

    @model_validator(mode="after")
    def _confidence_consistency(self) -> "AtomCreate":
        """Cohérence kind / audit_source / confidence pour auditeurs.

        Mappings imposés (côté Pydantic, redondance applicative avec stack v2 §2.4) :
        - `audit_source=interactive_human_validated` ⇒ `confidence=auditor_validated`
        - `audit_source=autonomous_agent_suggest`    ⇒ `confidence=agent_suggest`

        Pour les producers : `confidence=producer` est le default sensé. Si
        l'appelant force `confidence=auditor_validated`/`agent_suggest` sur un
        producer, on ne bloque pas (cas marginal de réimport historique).
        """
        if self.kind in AUDITOR_KINDS:
            if (
                self.audit_source == AuditSource.INTERACTIVE_HUMAN_VALIDATED
                and self.confidence != Confidence.AUDITOR_VALIDATED
            ):
                raise ValueError(
                    "audit_source=interactive_human_validated impose "
                    "confidence=auditor_validated"
                )
            if (
                self.audit_source == AuditSource.AUTONOMOUS_AGENT_SUGGEST
                and self.confidence != Confidence.AGENT_SUGGEST
            ):
                raise ValueError(
                    "audit_source=autonomous_agent_suggest impose "
                    "confidence=agent_suggest"
                )
        return self


# ============================================================================
# Warning — Phase 4.5 anti-drift
# ============================================================================
#
# Modèle pour les warnings émis par le pipeline d'écriture (POST/supersede)
# selon le catalogue Phase 4.5 (règle héritée de la doctrine anti-dérive).
# W-001 à W-008 : codes stables exposés au client. Severity calibrée :
#   - info     : signal faible à observer dans la durée
#   - warning  : dérive à corriger rapidement
#   - critical : action bloquante (W-004 → 409 + warning structuré dans le detail)
#
# W-008 est le dernier venu, et il n'observe pas une dérive : il rend visible
# un effet de la BASE que le router ne pouvait pas prévoir. Le trigger
# `arac.tg_auto_archive_low_confidence` est BEFORE INSERT — il change le
# `status` demandé. Un atome pouvait donc naître hors du rappel sur un 201 sans
# un mot, et une supersédure pouvait laisser un domaine/clé SANS aucun atome
# actif. Mesuré sur cerveau réel le 9 août 2026 ; cf `_check_w008_ne_nait_pas_
# actif` dans app/routers/atoms.py.
#
# Backward-compat : `AtomRead.warnings` default `[]`, les clients existants ne
# voient qu'un champ vide jusqu'à activation explicite des règles côté serveur.


class Warning(BaseModel):
    """Warning anti-drift Phase 4.5.

    Code stable (W-NNN), severity calibrée, message lisible humain + contexte
    structuré + remediation hint optionnel. Émis par les endpoints d'écriture
    et inclus dans `AtomRead.warnings` ou dans `HTTPException.detail.warnings`
    pour les warnings bloquants (W-004 critical).
    """

    model_config = ConfigDict(extra="forbid")

    code: str  # "W-001" ... "W-008"
    severity: str  # "info" | "warning" | "critical"
    message: str
    context: dict[str, Any] = Field(default_factory=dict)
    remediation_hint: str | None = None


# ============================================================================
# AtomRead — GET /v1/atoms/{id} et listes
# ============================================================================


class AtomRead(AtomBase):
    """Output de lecture d'un atome.

    `embedding` (3072 floats, ~24 KiB) est **exclu par défaut** — un endpoint
    dédié `GET /v1/atoms/{id}/embedding` sera ajouté Phase 4+ si besoin
    debug/admin. `desc_hash` est exposé (utile pour dédup côté client).

    `warnings` (Phase 4.5) : liste éventuellement vide de warnings anti-drift
    émis lors de la création / supersedure de cet atome. Vide sur les
    lectures GET (les warnings sont calculés au write, pas re-calculés au
    read — Phase 4.6 ajoutera la persistance audit_log).
    """

    model_config = _COMMON_CONFIG

    id: UUID
    desc_hash: str
    status: Status
    superseded_by: UUID | None
    confidence: Confidence
    audit_source: AuditSource | None
    node_id: str
    session_id: UUID | None
    version: int
    created_at: datetime
    updated_at: datetime
    warnings: list[Warning] = Field(
        default_factory=list,
        description=(
            "Warnings anti-drift Phase 4.5 émis lors de la création/supersedure. "
            "Vide sur GET (read-only) — non re-calculés. Cf "
            "la doctrine anti-dérive."
        ),
    )


# ============================================================================
# AtomUpdate — PATCH /v1/atoms/{id} (partial)
# ============================================================================


class AtomUpdate(BaseModel):
    """Partial update d'un atome existant.

    **Champs IMMUTABLES** (non présents ici) : `kind`, `scope`, `key`,
    `node_id`, `session_id`, `confidence`, `audit_source`.

    LIRE CETTE LIGNE EN ENTIER, ET PAS SEULEMENT SON PREMIER MOT. Ce qui est
    immuable, c'est le NIVEAU déclaré `confidence` — l'énumération
    `producer` / `agent_suggest` / `auditor_validated` — et la trace d'audit
    `audit_source`. Le CHIFFRE, `confidence_score`, est modifiable et figure
    plus bas dans cette même classe. La confusion des deux a fait imprimer à
    l'installateur, pendant sept manches, « la confiance d'un atome est
    IMMUABLE … ne cherchez pas le réglage qui le ferait monter » — alors que
    le réglage existe, qu'il est servi, et qu'il déplace le rappel.

    L'identité
    (scope, key) WHERE status='active' est garantie unique par index partial
    DB (`ux_memory_atoms_active_scope_key`). Pour "renommer" un atome :
    créer un nouvel atome (scope, new_key) qui supersède l'ancien via
    AtomSupersede.

    Si `value` est modifié, le **router** devra :
    1. Recalculer `desc_hash` = sha256(scope|kind|key|new_value)
    2. Régénérer `embedding` via app.services.embeddings.embed(new_value)
    3. UPDATE en transaction unique avec `value`

    Champs modifiables : `value`, `tags`, `status`, `source_ref`, `rationale`,
    `confidence_score`. Tous Optional — `None` = pas de modif côté UPDATE SQL.
    """

    model_config = _COMMON_CONFIG

    value: str | None = Field(default=None, min_length=1)
    tags: list[str] | None = None
    status: Status | None = None
    source_ref: dict[str, Any] | None = None
    rationale: str | None = None
    confidence_score: int | None = Field(default=None, ge=0, le=100)


# ============================================================================
# AtomSupersede — POST /v1/atoms/{id}/supersede
# ============================================================================


class AtomSupersede(BaseModel):
    """Supersedure d'un atome existant — crée un nouvel atome qui remplace
    l'ancien (mécanique `supersedes` héritée du prototype antérieur, stack v2 §5).

    **Convention héritage / remplacement** (uniforme sur les 4 champs concernés) :
    - `None`           → **hérite** du champ de l'atome remplacé
    - `[]` / `{}` / "" → **remplace** par valeur vide explicite

    Le quatrième champ, `new_confidence_score`, a longtemps figuré dans cette
    convention SANS que le router l'applique : il passait la valeur brute, donc
    une supersédure muette sur le chiffre écrivait `NULL`. Le compte est
    désormais exact — trois champs de forme (`tags`, `rationale`,
    `source_ref`) plus le chiffre — et
    `tests/test_cockpit_dit_vrai.py::test_le_chiffre_de_confiance_est_bel_et_bien_servi`
    exige les quatre à la fois.

    Champs IMMUTABLES (hérités automatiquement de l'ancien atome) : `kind`,
    `scope`, `key`, `confidence`, `audit_source`. Si tu veux changer kind ou
    scope ou key, c'est un nouvel atome séparé, pas un supersede.

    **Effet transactionnel côté service** (orchestré par le router, pas Pydantic) :
    1. SELECT old atom by `id` (URL param)
    2. Si `old.status != 'active'` → 409 Conflict ("ne peut superseder qu'un atome actif")
    3. INSERT new atom :
       - `kind`, `scope`, `key`, `confidence`, `audit_source` hérités
       - `value` = `new_value`
       - `tags` = `new_tags` si fourni sinon `old.tags`
       - `rationale` = `new_rationale` si fourni sinon `old.rationale`
       - `source_ref` = `new_source_ref` si fourni sinon `old.source_ref`
       - `confidence_score` = `new_confidence_score` si fourni sinon `old.confidence_score`
       - `node_id` = `new_node_id`, `session_id` = `new_session_id`
       - `version` = `old.version + 1`
       - `status` = 'active'
       - `embedding` = embed(new_value)
       - `desc_hash` = sha256(scope|kind|key|new_value)
    4. UPDATE old atom : `status = 'superseded'`, `superseded_by = <new_id>`
    5. Le tout dans une transaction PG unique.
    """

    model_config = _COMMON_CONFIG

    new_value: str = Field(min_length=1)
    new_rationale: str | None = None         # None = hérite ; "" = remplace par vide
    new_tags: list[str] | None = None        # None = hérite ; [] = remplace par vide
    new_source_ref: dict[str, Any] | None = None  # None = hérite ; {} = remplace par vide
    new_confidence_score: int | None = Field(default=None, ge=0, le=100)
    new_node_id: str = Field(min_length=1)
    new_session_id: UUID | None = None

    # Phase 4 — garde tag pierre-angulaire (Option A).
    # Si l'atome remplacé porte le tag 'pierre-angulaire' ET que `new_tags`
    # est fourni explicitement (pas None) ET que `new_tags` ne contient pas
    # 'pierre-angulaire' ET que ce flag est False → 409. Le flag rend le
    # drop explicite, le tag n'est pas perdu par inadvertance.
    # Phase 4.5 transformera ce 409 en warning structuré W-004 + acceptation
    # via le même flag (règle héritée de la doctrine anti-dérive).
    acknowledge_drop_pierre_angulaire: bool = Field(
        default=False,
        description=(
            "Acquittement explicite du drop du tag 'pierre-angulaire'. "
            "Requis si l'ancien atome est pierre-angulaire et que `new_tags` "
            "ne le contient pas — sinon 409. Phase 4 garde Option A."
        ),
    )


# ============================================================================
# Phase 4 — retrieval REST (recall / context_for / foundations / lineage)
# ============================================================================


class RecallRequest(BaseModel):
    """Body de POST /v1/atoms/recall — kNN dense pur.

    Embed le `query`, SELECT par cosine distance sur arac.memory_atoms
    `status='active' AND embedding IS NOT NULL`. Pas de foundations injectées
    — recherche sémantique pure. Filtres optionnels scope/kind/since.

    La signature et le SQL paramétré vivent dans `app/routers/atoms.py`.
    """

    model_config = _COMMON_CONFIG

    query: str = Field(min_length=1)
    k: int = Field(default=10, ge=1, le=100)
    scope: Scope | None = None
    kind: Kind | None = None
    since: datetime | None = None
    # (gap G1 — attribution d'appelant) : identité DÉCLARÉE du
    # consommateur pour le Context Engine shadow/serve (profils
    # cortex_dedup / canari, cf app/services/context_shadow.py). Slug machine
    # strict (jamais une PII — le champ finit dans context_receipts). Défaut
    # `unknown` : aucun changement de comportement pour les appelants
    # existants, le chemin servi reste bit-identique tant que les flags CE
    # (défaut OFF) ne sont pas armés.
    consumer: str = Field(
        default="unknown",
        pattern=r"^[a-z0-9][a-z0-9_.-]{0,63}$",
        description=(
            "Identité machine du consommateur (ex. 'cortex_dedup', 'canari') "
            "pour le Context Engine — slug lowercase, jamais une PII."
        ),
    )


# ============================================================================
# RecallFreshRequest — POST /v1/atoms/recall_fresh (Phase D.6 Tier 2)
# ============================================================================
#
# PROSPECTIF — Phase D.6 Tier 2. Le seuil `days=14` est hérité du prototype antérieur
# (cadence anti-oubli), non recalibré sur la distribution ARAC réelle. La
# colonne `confirmed_until` (3e exemption du prototype antérieur) n'est PAS présente
# en BDD ARAC au 2026-05-20 — la décision de l'introduire est reportée Phase E
# (cf docstring du endpoint dans app/routers/atoms.py:recall_fresh).


class RecallFreshRequest(BaseModel):
    """POST /v1/atoms/recall_fresh — recall avec filtre stale.

    Phase D.6 Tier 2 : recall classique + filtre âge `days`. 2 exemptions
    effectives côté ARAC (3 prévues à terme) :
      - updated_at >= now() - days   (atomes récents)
      - 'pierre-angulaire' ∈ tags    (doctrine exemptée du staleness)
      - [PROSPECTIF Phase E] confirmed_until > now() — colonne pas en BDD
        ARAC au 2026-05-20, à introduire si Phase E motive le besoin.

    GOTCHA : c'est un FILTRE DE LECTURE, pas un changement d'état.
    Atomes stales restent status=active, juste invisibles ici.
    """

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=10000)
    days: int = Field(default=14, ge=1, le=365)
    k: int = Field(default=10, ge=1, le=100)
    scope: Scope | None = None
    kind: Kind | None = None


class AtomReadWithDistance(AtomRead):
    """AtomRead enrichi de la distance cosine — exposé par `recall` et `context_for`.

    `distance` = cosine distance entre l'embedding du query/topic et l'embedding
    de cet atome. Plus la distance est faible, plus l'atome est sémantiquement
    proche. None pour les foundations injectées dans context_for (elles ne sont
    pas sélectionnées par distance filtre tag pur).

    Logger `top_1_distance` Phase 4+ alimente la décision Phase 8+ hybrid scoring.
    """

    model_config = _COMMON_CONFIG

    distance: float | None = None


class ContextForRequest(BaseModel):
    """Body de POST /v1/atoms/context_for — bundle thématique.

    2 SQL distincts (thématique + foundations) + merge Python. Foundations
    injectées en premier, anti-double via foundation_ids, cap par bucket
    APRÈS injection. Mapping kinds → buckets : Option α (15 buckets, un par
    kind) tranchée Phase 4 V-init.

    La mécanique exacte est décrite sur l'endpoint, dans `app/routers/atoms.py`.
    """

    model_config = _COMMON_CONFIG

    topic: str = Field(min_length=1)
    k: int = Field(default=10, ge=1, le=100)


class ContextBundle(BaseModel):
    """Réponse de POST /v1/atoms/context_for — bundle de contexte thématique.

    Champs :
    - `topic` / `k` : echo des paramètres de la requête (debug / traçabilité)
    - `buckets` : dict keyed par kind value (15 entrées Option α). Chaque valeur
      est une liste d'AtomReadWithDistance. Foundations en premier (distance=None,
      tri ordinal par KIND_ORDER puis key ASC), puis atomes thématiques par
      cosine croissante. Cap = `k` atomes par bucket APRÈS injection foundations.
    - `foundation_ids` : UUIDs des atomes pierre-angulaire injectés (transparence
      pour le LLM consommateur — distingue doctrine vs thématique).
    - `saturation_warning` : messages d'alerte si un bucket a été saturé par les
      foundations et a écarté un atome thématique (la doctrine ne passe
      jamais à la trappe ; l'écart est exposé, pas masqué).
    """

    model_config = _COMMON_CONFIG

    topic: str
    k: int
    buckets: dict[str, list[AtomReadWithDistance]]
    foundation_ids: list[UUID]
    saturation_warning: list[str] = Field(default_factory=list)


class LineageBranch(str, Enum):
    """Branche d'un node dans une chaîne de lineage (Phase 4)."""

    ANCESTOR = "ancestor"
    SELF = "self"
    DESCENDANT = "descendant"


class LineageNode(AtomRead):
    """Node d'une chaîne de lineage — AtomRead enrichi de la position dans la chaîne.

    `depth` :
    - < 0 : ancêtre (version plus ancienne, antérieure dans la chaîne supersede).
            -1 = parent direct, -2 = grand-parent, etc.
    -   0 : atome cible (le paramètre URL de GET /v1/atoms/{id}/lineage)
    - > 0 : descendant (version plus récente, postérieure). +1 = enfant direct.

    `branch` dérivé de `depth` pour faciliter la consommation côté LLM/UI.
    """

    model_config = _COMMON_CONFIG

    depth: int
    branch: LineageBranch


class LineageRead(BaseModel):
    """Réponse de GET /v1/atoms/{id}/lineage — chaîne complète de supersession.

    `atom_id` : UUID de l'atome cible (paramètre URL).
    `chain` : ordonnée par depth ASC (ancêtres → self → descendants). Contient
              toujours au minimum l'atome cible (chain de longueur 1 si aucune
              supersession). Implémentation : WITH RECURSIVE bidirectionnel
              sur la colonne `superseded_by`.

    Note : un atome peut avoir plusieurs ancêtres au même depth si des
    "merges" de chaînes existent (deux atomes pointant le même superseded_by).
    Cas marginal mais autorisé par le schéma.
    """

    model_config = _COMMON_CONFIG

    atom_id: UUID
    chain: list[LineageNode]


# ============================================================================
# Sentinelles assert au chargement — garde-fous régression silencieuse
# ============================================================================

assert len(Status) == 5, f"Status enum doit avoir 5 membres, trouvé {len(Status)}"
assert len(Confidence) == 3, f"Confidence enum doit avoir 3 membres, trouvé {len(Confidence)}"
assert len(AuditSource) == 2, f"AuditSource enum doit avoir 2 membres, trouvé {len(AuditSource)}"


# --- Reprise de projet (routeur par centroïdes, P-V6-017) -------------------
class ResumeRequest(BaseModel):
    """Body de POST /v1/atoms/resume — routeur de reprise de projet.

    Embed le `query`, route vers le plus proche centroïde de scope
    (`arac.project_registry`), puis recall dense restreint à ce scope.
    Rejet open-set (trop loin) -> fail-open = recall nu. Zéro LLM read-path.
    """

    model_config = _COMMON_CONFIG

    query: str = Field(min_length=1)
    k: int = Field(default=8, ge=1, le=50)


class ResumeCandidate(BaseModel):
    model_config = _COMMON_CONFIG
    scope: str
    member_count: int
    distance: float


class ResumeAtom(BaseModel):
    model_config = _COMMON_CONFIG
    id: UUID
    kind: str
    scope: str
    key: str
    value: str
    distance: float


class ResumeResponse(BaseModel):
    """Réponse de /v1/atoms/resume : scope routé (ou None si rejeté), candidats, atomes."""

    model_config = _COMMON_CONFIG
    routed_scope: str | None
    rejected: bool
    reason: str | None = None
    candidates: list[ResumeCandidate]
    atoms: list[ResumeAtom]
