"""Router atoms — endpoints CRUD + retrieval pour `arac.memory_atoms`.

CRUD (Phase 2.3) — 6 endpoints :
  - POST   /v1/atoms                     create
  - GET    /v1/atoms/{id}                read single (bypass status)
  - GET    /v1/atoms                     list (filtres scope/kind/status/tag/limit/offset)
  - PATCH  /v1/atoms/{id}                partial update (scope/kind/key immutables)
  - DELETE /v1/atoms/{id}                soft delete (status='archived')
  - POST   /v1/atoms/{id}/supersede      versioning par supersession + garde tag pierre-angulaire (Option A)

Retrieval (Phase 4) — 4 endpoints :
  - POST   /v1/atoms/recall              kNN dense pur
  - POST   /v1/atoms/context_for         kNN dense + foundations + merge Python
  - GET    /v1/atoms/foundations         filtre tag pur pierre-angulaire
  - GET    /v1/atoms/{id}/lineage        chaîne supersession WITH RECURSIVE

⚠️ Ordre d'enregistrement FastAPI : les routes statiques (/recall, /context_for,
/foundations) DOIVENT être déclarées AVANT les routes paramétriques (/{atom_id}).
Sinon FastAPI tente de parser "recall" / "foundations" comme UUID → 422.

Mécanique supersede (auto-audit Phase 2.3) :
  1. SELECT old SANS FOR UPDATE → récupère scope/kind/key (seulement pour embed)
  2. embed(new_value) HORS transaction (~200-300ms, pool DB libre)
  3. async with db.transaction():
       SELECT old FOR UPDATE → re-check status='active'
       UPDATE old → status='superseded' (libère le slot UNIQUE WHERE active,
         sinon INSERT new collisionnerait avec ux_memory_atoms_active_scope_key)
       INSERT new (status='active', version=old.version+1) RETURNING id
       UPDATE old → superseded_by = new.id
  Rationale : éviter de tenir une connexion DB ouverte pendant l'API call OpenAI
  (anti-pattern saturation pool si Phase 7 fait 100 supersedes en boucle). L'ordre
  UPDATE-INSERT-UPDATE est imposé par l'index partial UNIQUE WHERE status='active'
  (1 seul atome actif possible par scope+key — découverte par test Phase 2.3).

Mapping erreurs PG → HTTP :
  - UniqueViolation (ux_memory_atoms_active_scope_key) → 409 + hint /supersede
  - ForeignKeyViolation (node_id, session_id, superseded_by) → 422
  - CheckViolation (kind/scope/status/audit_source/confidence_score) → 422
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from hashlib import sha256
import os
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg import AsyncConnection
from psycopg.errors import CheckViolation, ForeignKeyViolation, UniqueViolation
from psycopg.rows import dict_row

from app import journal
from app.db import get_db
from app.schemas.atom import (
    AtomCreate,
    AtomRead,
    AtomReadWithDistance,
    AtomSupersede,
    AtomUpdate,
    ContextBundle,
    ContextForRequest,
    LineageBranch,
    LineageNode,
    LineageRead,
    RecallFreshRequest,
    RecallRequest,
    ResumeRequest,
    ResumeResponse,
    Status,
    Warning,
)
from app.schemas.kind import KIND_ORDER, Kind
from app.schemas.scope import LEAVES, ROOTS, Scope
from app.services import context_shadow
from app.services.embeddings import embed
from app.services import project_registry

# Tag canonique des atomes pierre-angulaire. Filtré tel quel par
# foundations() et utilisé par la garde supersede Phase 4.
_PIERRE_ANGULAIRE_TAG = "pierre-angulaire"

# ----------------------------------------------------------------------------
# Phase 4.5 anti-drift constants
# ----------------------------------------------------------------------------
# Cf la doctrine anti-dérive §3.2.

# W-001 : cible 8-12 pierres-angulaires actives (atome #5). Seuil de
# déclenchement = strict supérieur à 12.
_PA_BUDGET_TARGET_MAX = 12

# W-002 : tags canoniques Phase 2.7. Tous tags hors de ce set émettent W-002.
_CANONICAL_TAGS: frozenset[str] = frozenset(
    {"pierre-angulaire", "founding-atom", "recalibration-candidate"}
)

# W-003 : longueur minimale "raisonnable" du rationale pour kind=decision.
# Sous ce seuil, on émet un info — Pydantic continue d'imposer rationale
# non-vide pour les RATIONALE_REQUIRED_KINDS (validator `_rationale_required`).
_DECISION_RATIONALE_MIN_CHARS = 200

# W-005 : les « mondes » ne sont pas une liste écrite ici — ce sont VOS racines.
#
# Un atome qui mélange deux mondes est un atome qui sera mal rappelé : il
# répondra à moitié à deux questions au lieu de répondre entièrement à une. La
# détection est volontairement NAÏVE (recherche de mots, insensible à la casse)
# et sa sévérité est `info` : elle attire l'œil, elle ne bloque rien.
#
# Le vocabulaire de chaque monde est dérivé de la taxonomie engendrée : la
# racine et le dernier segment de chacune de ses feuilles. `travail` +
# `travail/finance` donnent {"travail", "finance"}. Aucune liste à maintenir,
# et l'heuristique suit votre taxonomie quand elle évolue.


def _world_keywords() -> dict[str, frozenset[str]]:
    worlds: dict[str, set[str]] = {r: {r} for r in ROOTS}
    for leaf in LEAVES:
        root, _, tail = leaf.partition("/")
        if root in worlds and tail:
            worlds[root].add(tail.replace("-", " "))
            worlds[root].add(tail)
    return {w: frozenset(k) for w, k in worlds.items()}


_WORLD_KEYWORDS: dict[str, frozenset[str]] = _world_keywords()

# Certains scopes accueillent DÉLIBÉRÉMENT de la pensée transverse — un scope
# « idées » ou « liens » a vocation à relier des mondes, et l'avertissement y
# serait du bruit permanent. Déclarez-les ici, séparés par des virgules :
#
#     ARAC_TRANSVERSE_SCOPES="savoir/idees,savoir/liens"
#
# Vide par défaut : le dépôt ne connaît pas votre taxonomie, et exempter au
# hasard reviendrait à taire un avertissement utile.
_TRANSVERSE_SCOPES: frozenset[str] = frozenset(
    s.strip() for s in os.environ.get("ARAC_TRANSVERSE_SCOPES", "").split(",")
    if s.strip()
)

# Multiplicateur d'overshoot SQL pour la requête A (thématique) de context_for.
# k * 8 — tranché Phase 4 V-init (Option α 15 buckets, compensation ratio 15/6
# vs prototype antérieur). Monter à k*15 si saturation observée Phase 7+.
# §1.2 + PLAN_V2 Phase 4.
_CONTEXT_FOR_OVERSHOOT = 8


router = APIRouter()
_logger = logging.getLogger("arac.api.atoms")


# ============================================================================
# Helpers privés
# ============================================================================


def _compute_desc_hash(scope: str, kind: str, key: str, value: str) -> str:
    """sha256 hex de `scope|kind|key|value` pour dédup côté client."""
    return sha256(f"{scope}|{kind}|{key}|{value}".encode("utf-8")).hexdigest()


def _row_to_atom_read(row: dict[str, Any]) -> AtomRead:
    """psycopg dict_row → AtomRead. `embedding` exclu (24 KiB lourd payload).

    `tags` est natif `list[str]` via psycopg TEXT[]. `source_ref` est dict ou
    None (JSONB → dict natif psycopg3). Les Enum sont coerced depuis str par
    Pydantic v2.
    """
    return AtomRead(
        id=row["id"],
        kind=row["kind"],
        scope=row["scope"],
        key=row["key"],
        value=row["value"],
        desc_hash=row["desc_hash"],
        tags=list(row["tags"] or []),
        status=row["status"],
        superseded_by=row["superseded_by"],
        confidence=row["confidence"],
        audit_source=row["audit_source"],
        confidence_score=row["confidence_score"],
        source_ref=row["source_ref"],
        rationale=row["rationale"],
        node_id=row["node_id"],
        session_id=row["session_id"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_atom_read_with_distance(row: dict[str, Any]) -> AtomReadWithDistance:
    """Comme _row_to_atom_read mais propage le champ `distance` (cosine).

    Utilisé par `recall` (toujours une distance car kNN dense pur) et
    `context_for` pour les atomes thématiques (les foundations injectées
    ont distance=None — sélectionnées par filtre tag, pas par distance).
    """
    raw_distance = row.get("distance")
    return AtomReadWithDistance(
        id=row["id"],
        kind=row["kind"],
        scope=row["scope"],
        key=row["key"],
        value=row["value"],
        desc_hash=row["desc_hash"],
        tags=list(row["tags"] or []),
        status=row["status"],
        superseded_by=row["superseded_by"],
        confidence=row["confidence"],
        audit_source=row["audit_source"],
        confidence_score=row["confidence_score"],
        source_ref=row["source_ref"],
        rationale=row["rationale"],
        node_id=row["node_id"],
        session_id=row["session_id"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        distance=float(raw_distance) if raw_distance is not None else None,
    )


# Fragment SQL `CASE WHEN kind = ... THEN N ELSE ...` pour tri ordinal des
# foundations et du fallback context_for. Construit une seule fois au
# chargement du module depuis KIND_ORDER pour cohérence avec l'ordre des buckets.
_KIND_ORDER_CASE_SQL: str = (
    "CASE kind "
    + " ".join(f"WHEN '{k.value}' THEN {i}" for i, k in enumerate(KIND_ORDER))
    + " ELSE 999 END"
)


@contextmanager
def _handle_pg_errors():
    """Context manager : map psycopg errors → HTTPException."""
    try:
        yield
    except UniqueViolation:
        raise HTTPException(
            status_code=409,
            detail=(
                "scope+key déjà actif. "
                "Utilise POST /v1/atoms/{id}/supersede pour mettre à jour."
            ),
        )
    except ForeignKeyViolation as e:
        msg = str(e)
        if "node_id" in msg:
            raise HTTPException(status_code=422, detail="node_id inconnu (FK arac.nodes)")
        if "session_id" in msg:
            raise HTTPException(status_code=422, detail="session_id inconnu (FK arac.sessions)")
        raise HTTPException(
            status_code=422,
            detail={"erreur": "FK violation", **journal.diagnostic_exception(e)},
        )
    except CheckViolation as e:
        # Filet de sécurité — Pydantic devrait avoir filtré en amont.
        #
        # `detail=f"DB CHECK violation: {e}"` rendait la ligne ENTIÈRE au
        # client. MESURÉ : un POST sur un kind banni par la migration 0018 —
        # chemin que cette même migration déclare atteignable depuis l'API —
        # rendait en 422 « DETAIL:  Failing row contains (…, perso/sante,
        # temoin-…, <LE SOUVENIR>, [le vecteur], <desc_hash>, …) ». Le module
        # qui fabrique les 500 promet, dans la même version, que « le détail
        # n'est pas exposé ici : il peut contenir un secret ou un fragment de
        # souvenir » : une 422 n'a pas le droit de faire l'inverse.
        #
        # Ce qui reste dit tout ce qui sert : le NOM de la contrainte violée et
        # la colonne fautive. Ils viennent du schéma (`db/alembic/versions/`),
        # pas de la mémoire.
        raise HTTPException(
            status_code=422,
            detail={"erreur": "DB CHECK violation", **journal.diagnostic_exception(e)},
        )


# ============================================================================
# Helpers warnings anti-drift Phase 4.5
# ============================================================================
#
# Chaque helper retourne `Warning | None`. Le router agrège en list[Warning]
# et l'attache à l'AtomRead retourné (POST/supersede). Le log structuré JSON
# est émis par l'helper d'agrégation `_emit_warnings_log`, pas par chaque
# helper individuel — ça permet un seul event log par requête. Phase 4.6
# ajoutera la persistance audit_log.


def _build_w004_warning(
    atom_id: UUID,
    old_key: str,
    old_version: int,
    new_tags: list[str] | None,
    new_rationale: str | None,
) -> Warning:
    """W-004 : drop_pierre_angulaire_without_acknowledge (critical).

    Construit le warning bloquant inclus dans le HTTPException 409 detail.
    """
    return Warning(
        code="W-004",
        severity="critical",
        message=(
            "Tentative de démotion d'un atome pierre-angulaire sans "
            "acknowledge_drop_pierre_angulaire=true."
        ),
        context={
            "atom_id": str(atom_id),
            "old_key": old_key,
            "old_version": old_version,
            "new_tags": new_tags,
            "new_rationale_preview": (
                (new_rationale[:120] + "...")
                if new_rationale and len(new_rationale) > 120
                else new_rationale
            ),
        },
        remediation_hint=(
            "Set acknowledge_drop_pierre_angulaire=true to proceed and "
            "motivate the demotion explicitly in new_rationale (cf atome "
            "promotion-pierre-angulaire-critere #5)."
        ),
    )


async def _check_w001_pa_budget(
    db: AsyncConnection, tags: list[str]
) -> Warning | None:
    """W-001 : budget_pierres_angulaires_exceeded (warning).

    Compte les atomes actifs portant le tag pierre-angulaire APRÈS commit.
    Émis seulement si le nouvel atome porte lui-même le tag (sinon le compte
    n'a pas changé par ce write).
    """
    if _PIERRE_ANGULAIRE_TAG not in (tags or []):
        return None
    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT COUNT(*) AS c
            FROM arac.memory_atoms
            WHERE status = 'active'
              AND tags @> ARRAY[%s]::text[]
            """,
            (_PIERRE_ANGULAIRE_TAG,),
        )
        row = await cur.fetchone()
    count = int(row["c"]) if row else 0
    if count <= _PA_BUDGET_TARGET_MAX:
        return None
    return Warning(
        code="W-001",
        severity="warning",
        message=(
            f"Budget pierres-angulaires dépassé : {count} actives "
            f"(cible 8-12, plafond souple {_PA_BUDGET_TARGET_MAX})."
        ),
        context={"count_active_pa": count, "target_max": _PA_BUDGET_TARGET_MAX},
        remediation_hint=(
            "Liste des pierres-angulaires dépasse la cible (8-12). Envisager "
            "soit condensation par supersedes, soit démotion d'une "
            "pierre-angulaire devenue moins critique lors de la prochaine "
            "revue annuelle."
        ),
    )


def _check_w002_tag_drift(tags: list[str]) -> Warning | None:
    """W-002 : tag_drift_non_conventional (info).

    Tags hors {pierre-angulaire, founding-atom, recalibration-candidate}.
    Pas d'enrichissement BDD (fréquence d'usage) Phase 4.5 — coûteux à peu
    de valeur ajoutée. Phase 6+ pourra l'ajouter.
    """
    non_canonical = [t for t in (tags or []) if t not in _CANONICAL_TAGS]
    if not non_canonical:
        return None
    return Warning(
        code="W-002",
        severity="info",
        message=(
            f"Tag(s) hors convention Phase 2.7 détecté(s) : "
            f"{sorted(non_canonical)}."
        ),
        context={
            "non_canonical_tags": sorted(non_canonical),
            "canonical_tags": sorted(_CANONICAL_TAGS),
        },
        remediation_hint=(
            "Si ce tag se répète au-delà de 3 occurrences sur 30 jours, "
            "envisager promotion en tag conventionné via atome decision "
            "dédié dans scope claude-config."
        ),
    )


def _check_w003_rationale_short(
    kind: Kind | str, rationale: str | None
) -> Warning | None:
    """W-003 : rationale_too_short_for_decision (info).

    kind=decision ET len(rationale) < 200. Pydantic impose rationale non-vide
    en amont via `_rationale_required` ; ce warning ajoute la dimension
    qualitative "trop court pour expliquer le pourquoi".
    """
    kind_value = kind.value if hasattr(kind, "value") else kind
    if kind_value != Kind.DECISION.value:
        return None
    length = len(rationale or "")
    if length >= _DECISION_RATIONALE_MIN_CHARS:
        return None
    return Warning(
        code="W-003",
        severity="info",
        message=(
            f"Rationale court pour kind=decision : {length} chars "
            f"(cible {_DECISION_RATIONALE_MIN_CHARS}+ chars)."
        ),
        context={
            "length": length,
            "target_min": _DECISION_RATIONALE_MIN_CHARS,
            "preview": (rationale or "")[:200],
        },
        remediation_hint=(
            "Rationale court pour une decision. Vérifier qu'il explique le "
            "POURQUOI (causes, contraintes, alternatives écartées) et pas "
            "seulement le QUOI. Si la decision est triviale, envisager "
            "kind=note à la place."
        ),
    )


def _check_w005_world_mix(scope: Scope | str, value: str) -> Warning | None:
    """W-005 : world_mix_suspected (info).

    Détection naïve : ≥2 mondes détectés via keyword match (insensible casse)
    ET scope hors catégorie "pensée transverse". Phase 4.5 = regex sur la
    vocabulaire dérivé de VOS racines et de VOS feuilles (`_world_keywords`).
    """
    scope_value = scope.value if hasattr(scope, "value") else scope
    if scope_value in _TRANSVERSE_SCOPES:
        return None
    value_lower = (value or "").lower()
    detected: dict[str, list[str]] = {}
    for world, keywords in _WORLD_KEYWORDS.items():
        matched = [kw for kw in keywords if kw in value_lower]
        if matched:
            detected[world] = matched
    if len(detected) < 2:
        return None
    return Warning(
        code="W-005",
        severity="info",
        message=(
            f"Atome potentiellement multi-monde : {len(detected)} mondes "
            f"détectés ({', '.join(sorted(detected.keys()))})."
        ),
        context={
            "detected_worlds": {w: kws for w, kws in detected.items()},
            "scope": scope_value,
        },
        remediation_hint=(
            "Cet atome semble parler de deux mondes à la fois. Rangez-le par "
            "ANGLE D'ANALYSE, pas par sujet : la question à laquelle il "
            "répondra un jour appartient à un seul monde. S'il en traverse "
            "réellement plusieurs, écrivez-en deux, reliés par leur "
            "source_ref — un atome à cheval répond à moitié à deux questions "
            "au lieu de répondre entièrement à une. Si un de vos scopes "
            "accueille délibérément de la pensée transverse, déclarez-le dans "
            "ARAC_TRANSVERSE_SCOPES pour taire cet avertissement là où il est "
            "du bruit."
        ),
    )


async def _check_w006_desc_hash_collision(
    db: AsyncConnection, desc_hash: str, exclude_id: UUID | None = None
) -> Warning | None:
    """W-006 : desc_hash_collision_recent (warning).

    Cherche un atome existant avec même desc_hash créé < 7j, quel que soit
    son status. `exclude_id` permet d'ignorer l'atome qu'on vient de créer
    (pas applicable en pratique car l'INSERT a eu lieu juste avant l'appel
    de ce helper, mais on garde l'API symétrique).
    """
    sql = """
        SELECT id, scope, kind, key, status, created_at
        FROM arac.memory_atoms
        WHERE desc_hash = %s
          AND created_at >= NOW() - INTERVAL '7 days'
          AND (%s::uuid IS NULL OR id <> %s::uuid)
        ORDER BY created_at DESC
        LIMIT 1
    """
    excl = str(exclude_id) if exclude_id else None
    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, (desc_hash, excl, excl))
        row = await cur.fetchone()
    if row is None:
        return None
    return Warning(
        code="W-006",
        severity="warning",
        message=(
            f"desc_hash identique à un atome créé < 7j "
            f"(scope={row['scope']}, kind={row['kind']}, key={row['key']})."
        ),
        context={
            "collision_atom_id": str(row["id"]),
            "scope": row["scope"],
            "kind": row["kind"],
            "key": row["key"],
            "status": row["status"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        },
        remediation_hint=(
            "Contenu sémantique identique à un atome récent détecté. "
            "Vérifier si vous voulez vraiment créer un nouvel atome ou si "
            "vous voulez supersede l'existant."
        ),
    )


async def _check_w007_scope_kind_unprecedented(
    db: AsyncConnection,
    node_id: str,
    scope: Scope | str,
    kind: Kind | str,
    exclude_id: UUID | None = None,
) -> Warning | None:
    """W-007 : scope_kind_combination_unprecedented (info).

    (scope, kind) jamais vu pour ce node_id. exclude_id ignore l'atome qu'on
    vient de créer.
    """
    scope_value = scope.value if hasattr(scope, "value") else scope
    kind_value = kind.value if hasattr(kind, "value") else kind
    sql = """
        SELECT COUNT(*) AS c
        FROM arac.memory_atoms
        WHERE node_id = %s
          AND scope = %s
          AND kind = %s
          AND (%s::uuid IS NULL OR id <> %s::uuid)
    """
    excl = str(exclude_id) if exclude_id else None
    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, (node_id, scope_value, kind_value, excl, excl))
        row = await cur.fetchone()
    count = int(row["c"]) if row else 0
    if count > 0:
        return None
    # Liste des combos déjà utilisés pour info
    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT scope, kind, COUNT(*) AS c
            FROM arac.memory_atoms
            WHERE node_id = %s
            GROUP BY scope, kind
            ORDER BY c DESC
            LIMIT 20
            """,
            (node_id,),
        )
        combos = await cur.fetchall()
    return Warning(
        code="W-007",
        severity="info",
        message=(
            f"Combinaison (scope={scope_value}, kind={kind_value}) "
            f"inédite pour node_id={node_id}."
        ),
        context={
            "node_id": node_id,
            "scope": scope_value,
            "kind": kind_value,
            "existing_combos": [
                {"scope": c["scope"], "kind": c["kind"], "count": int(c["c"])}
                for c in combos
            ],
        },
        remediation_hint=(
            "Combinaison (scope, kind) inédite pour ce node. Vérifier que "
            "le kind choisi est le plus précis (heuristiques de l'atome "
            "format-atome-canonique : decision vs idea, note vs insight, "
            "pattern vs gotcha, etc.)."
        ),
    )


def _check_w008_ne_nait_pas_actif(row: dict) -> Warning | None:
    """W-008 : l'atome vient d'être écrit, et il est DÉJÀ hors du rappel.

    LE SILENCE QUE CE WARNING BRISE — mesuré, pas déduit, sur un cerveau
    réel (banc « vide1brain », grappe 5496, API 8320, 9 août 2026).

    `arac.tg_auto_archive_low_confidence` est un trigger **BEFORE INSERT** :
    il bascule `status` en `low_confidence_archive` dès qu'une écriture porte
    `audit_source = 'autonomous_agent_suggest'` et un `confidence_score` non
    nul strictement inférieur à 70 (mesuré : 69 archivé, 70 actif). Le router
    demandait `status='active'` ; la base rendait autre chose, et personne ne
    le disait.

    Le cas qui coûte réellement un souvenir est la SUPERSÉDURE, parce que
    `confidence_score` y est HÉRITÉ quand l'appelant n'en parle pas :

        atome « suggestion d'agent », score 30, actif
        POST /v1/atoms/<id>/supersede {"new_value": "…"}   → 201
        ancien : status='superseded'   nouveau : status='low_confidence_archive'
        SELECT count(*) … WHERE scope=… AND key=… AND status='active'  → 0

    Réponse 201, aucune erreur, et plus aucun atome actif sur ce domaine et
    cette clé : `/recall` ne lit que `status='active'` — mesuré, il rend `[]`.
    L'écran de fin du bootstrap ne pouvait avertir que celui qui LISAIT ; ce
    warning avertit celui qui APPELLE, et `_persist_warning` le garde dans
    `arac.audit_log`.

    Sévérité `warning` et non `critical` : l'archivage est le comportement
    VOULU du seuil, pas une panne. Ce qui manquait, c'est de le nommer.
    """
    statut = row.get("status")
    if statut == "active":
        return None
    return Warning(
        code="W-008",
        severity="warning",
        message=(
            f"L'atome écrit n'est pas actif : la base l'a rangé en "
            f"« {statut} » à l'insertion. Il ne ressortira d'aucun rappel."
        ),
        context={
            "atom_id": str(row.get("id")),
            "status": statut,
            "scope": row.get("scope"),
            "key": row.get("key"),
            "confidence": row.get("confidence"),
            "audit_source": row.get("audit_source"),
            "confidence_score": row.get("confidence_score"),
            "seuil_archivage_basse_confiance": 70,
        },
        remediation_hint=(
            "Le déclencheur arac.tg_auto_archive_low_confidence archive à "
            "l'INSERT tout atome dont audit_source vaut "
            "'autonomous_agent_suggest' avec un confidence_score < 70. Il ne "
            "regarde PAS les UPDATE : PATCH /v1/atoms/<id> "
            "{\"confidence_score\": …} laisse un atome actif. Sur une "
            "supersédure, le score est HÉRITÉ quand new_confidence_score est "
            "absent — remontez d'abord le score de l'atome d'origine par "
            "PATCH, ou passez new_confidence_score >= 70."
        ),
    )


async def _persist_warning(
    db: AsyncConnection,
    target_atom_id: UUID | str | None,
    warning: Warning,
    node_id: str,
) -> None:
    """Insère un warning émis dans arac.audit_log (best-effort).

    Phase 4.6 : persistance long terme + analytics dashboard. Chaque warning
    devient une ligne audit_log avec action='warning', warning_code rempli, et
    warning_context JSONB contenant severity/message/context/remediation_hint.

    Jamais bloquant : toute exception (FK, contention, DB down) est loggée
    structuré JSON puis avalée — la persistance ne doit JAMAIS casser le
    POST/supersede de l'atome lui-même (les warnings sont déjà émis dans
    la réponse HTTP via atom_read.warnings).
    """
    try:
        async with db.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO arac.audit_log
                  (node_id, action, target_atom_id, warning_code,
                   warning_context, success, created_at)
                VALUES
                  (%s, %s, %s::uuid, %s, %s::jsonb, TRUE, NOW())
                """,
                (
                    node_id,
                    "warning",
                    str(target_atom_id) if target_atom_id else None,
                    warning.code,
                    json.dumps(
                        {
                            "severity": warning.severity,
                            "message": warning.message,
                            "context": warning.context,
                            "remediation_hint": warning.remediation_hint,
                        }
                    ),
                ),
            )
    except Exception as exc:  # noqa: BLE001 — best-effort persistence
        _logger.warning(
            "persist_warning_failed",
            extra={
                "event": "persist_warning_failed",
                "atom_id": str(target_atom_id) if target_atom_id else None,
                "warning_code": warning.code,
                "node_id": node_id,
                "error": type(exc).__name__,
                # `str(exc)[:200]` gardait les deux cents premiers caractères du
                # message. C'est exactement là que PostgreSQL range la ligne
                # fautive : « DETAIL:  Failing row contains (…, perso/sante,
                # <LE SOUVENIR>, …) » — mesuré. `raison()` rend la classe, le
                # SQLSTATE, la contrainte et la colonne, qui viennent du schéma.
                "raison": journal.raison(exc),
            },
        )


def _emit_warnings_log(
    event: str,
    atom_id: UUID,
    warnings: list[Warning],
) -> None:
    """Log structuré JSON unique pour la liste de warnings d'un write.

    Émis par les routers POST/supersede après agrégation. La substance est
    persistée par `_persist_warning` dans `arac.audit_log` — en base, sous les
    rôles du cerveau, et elle part avec lui à la désinstallation.

    CE QUE CETTE LIGNE PORTAIT, ET POURQUOI ELLE NE LE PORTE PLUS. Elle versait
    dans journald le `message` ET le `context` COMPLETS de chaque
    avertissement. MESURÉ sur un cerveau vivant, un seul `POST /v1/atoms` y
    déposait :

        "message": "Rationale court pour kind=decision : 85 chars…",
        "context": {"preview": "POURQUOIJRN1 parce que Jrn a fait un choc
                    anaphylactique en 2019 a l hopital de Lille"},
        "message": "Combinaison (scope=perso/sante, kind=decision) inédite…",
        "context": {"scope": "perso/sante",
                    "existing_combos": [{"scope": "perso/sante", …}, …]}

    — soit les deux cents premiers caractères du POURQUOI d'une décision
    (W-003), le domaine de l'atome écrit (W-007, W-008), la clé et le domaine
    d'un atome VOISIN (W-006), et jusqu'à vingt domaines de la taxonomie en
    usage. Ce n'est pas un chemin de laboratoire : `agents/cortex/atoms_client`
    écrit CHAQUE atome de la digestion par ces deux routes, trois fois par
    jour, sans qu'un humain touche à quoi que ce soit.

    CE QUI RESTE. Le `code` et la `severity` sont des littéraux de ce fichier —
    ils ne viennent d'aucune donnée, et le code DIT le message (c'est à ça que
    sert un code). Le `context` garde sa FORME : ses clés, ses nombres, ses
    identifiants engendrés par la machine ; ses textes deviennent
    `sha8:<empreinte>/<n caractères>` (`app.journal.reduire`, fermé par
    défaut). Un exploitant garde donc « W-003, preview de 85 caractères,
    cible 200 » — exactement ce que l'avertissement voulait dire — et le
    lecteur qui a le droit de lire le texte le lit là où c'est légitime :
    `SELECT warning_context FROM arac.audit_log WHERE target_atom_id = …`.

    L'`atom_id` reste en clair, et c'est délibéré : c'est un UUID tiré par la
    base, il ne porte aucun mot, et c'est LUI qui relie la ligne du journal à
    la ligne complète en base.
    """
    if not warnings:
        return
    _logger.info(
        event,
        extra={
            "event": "warnings",
            "atom_id": str(atom_id),
            "warning_count": len(warnings),
            "detail_en_base": "arac.audit_log (action='warning')",
            "warnings": [
                {
                    "code": w.code,
                    "severity": w.severity,
                    "context": journal.reduire(w.context),
                }
                for w in warnings
            ],
        },
    )


# ============================================================================
# Endpoints retrieval (Phase 4) — DOIVENT être déclarés AVANT les routes
# paramétriques /{atom_id} pour que /foundations ne soit pas intercepté par
# /{atom_id} et parsé comme UUID. /recall et /context_for sont POST donc pas
# de collision GET/{atom_id} possible, mais on les groupe ici pour cohérence.
# Doctrine Phase 2.7 — le SQL est paramétré, jamais interpolé, et la
# mécanique exacte de chaque endpoint.
# ============================================================================


@router.post("/recall", response_model=list[AtomReadWithDistance])
async def recall(
    payload: RecallRequest,
    db: Annotated[AsyncConnection, Depends(get_db)],
) -> list[AtomReadWithDistance]:
    """POST /v1/atoms/recall — kNN dense pur.

    Embed le `query` via OpenAI text-embedding-3-large (3072 dim), puis SELECT
    par cosine distance sur arac.memory_atoms WHERE status='active' AND
    embedding IS NOT NULL. Filtres optionnels scope/kind/since.

    Pas de foundations injectées — c'est la stratégie "exploration libre" du
    triptyque retrieval. Pour le bundle thématique doctrine + recherche,
    voir /v1/atoms/context_for.

    Monitoring Phase 4+ : event `recall.query` loggé avec `top_1_distance`
    pour alimenter la décision Phase 8+ hybrid scoring.

    Index utilisé : `ix_memory_atoms_embedding` (HNSW halfvec_cosine_ops,
    m=16, ef_construction=64).

    SANS CLÉ D'EMBEDDINGS (mode dégradé, que le bootstrap propose pour
    découvrir le système sans dépenser) : `embed()` lève
    `EmbeddingsIndisponibles` dès la première ligne, avant toute requête SQL.
    Ce n'est PAS attrapé ici volontairement — le handler global d'app/errors.py
    rend un 503 qui nomme ce qui manque et le geste qui le pose. Le faire route
    par route aurait laissé les six autres appels à `embed()` rendre la 500 nue
    qu'un nouvel utilisateur recevait sur son tout premier rappel.
    """
    query_embedding = await embed(payload.query)
    scope_value = payload.scope.value if payload.scope else None
    kind_value = payload.kind.value if payload.kind else None
    since_value = payload.since

    sql = """
        SELECT id, kind, scope, key, value, desc_hash, tags, status,
               superseded_by, confidence, audit_source, confidence_score,
               source_ref, rationale, node_id, session_id, version,
               created_at, updated_at,
               embedding <=> %s::halfvec(3072) AS distance
        FROM arac.memory_atoms
        WHERE status = 'active'
          AND embedding IS NOT NULL
          AND (%s::text IS NULL OR scope = %s)
          AND (%s::text IS NULL OR kind = %s)
          AND (%s::timestamptz IS NULL OR created_at >= %s)
        ORDER BY embedding <=> %s::halfvec(3072)
        LIMIT %s
    """
    params = (
        query_embedding,
        scope_value, scope_value,
        kind_value, kind_value,
        since_value, since_value,
        query_embedding,
        payload.k,
    )

    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()

    results = [_row_to_atom_read_with_distance(r) for r in rows]

    # ------------------------------------------------------------------
    # Context Engine — SERVE GO-gaté puis SHADOW.
    # La réponse servie est FIGÉE ci-dessus (bit-identique par construction
    # tant que les flags, défaut OFF, ne sont pas armés). Une erreur du
    # moteur ne fait JAMAIS échouer le recall : serve_r3 retourne None
    # (fallback dense) et run_shadow n'élève jamais — les deux sont bruyants
    # (log ERROR + context_shadow.COUNTERS). `query_embedding` est RÉUTILISÉ
    # (zéro 2e appel OpenAI) ; le `await` inline garde la connexion poolée
    # valide (jamais de task détachée avec `db`).
    # ------------------------------------------------------------------
    ce_consumer = context_shadow.resolve_consumer(payload.consumer)
    ce_served = False
    # Gating serve sur le consommateur DÉCLARÉ (payload brut, jamais le
    # résolu) : ARAC_SHADOW_CE_CONSUMER_DEFAULT ne peut PAS élargir le
    # périmètre du GO au trafic anonyme (cf context_shadow, INTERACTION
    # serve × défaut env).
    if context_shadow.serve_enabled_for(payload.consumer):
        shadow_rows = await context_shadow.serve_r3(
            db,
            query_embedding=query_embedding,
            query_text=payload.query,
            scope=scope_value,
            kind=kind_value,
            since=since_value,
            k=payload.k,
            consumer=ce_consumer,
        )
        if shadow_rows is not None:
            results = [_row_to_atom_read_with_distance(r) for r in shadow_rows]
            ce_served = True
    elif context_shadow.shadow_enabled():
        await context_shadow.run_shadow(
            db,
            query_embedding=query_embedding,
            query_text=payload.query,
            scope=scope_value,
            kind=kind_value,
            since=since_value,
            k=payload.k,
            consumer=ce_consumer,
            served_ids=[str(r.id) for r in results],
        )

    # ------------------------------------------------------------------
    # FOLD V2 — shadow-v2 (observation pure), flag INDÉPENDANT du v1,
    # exécuté APRÈS le shadow v1 : quand les deux sont armés, deux reçus au
    # même query_sha256 = comparaison vivante v1/v2 par requête. Jamais de
    # serve v2 dans ce chantier. `query_embedding` RÉUTILISÉ (embed v1 brut
    # — le fold ne touche que les atomes, jamais la requête) ; run_shadow_v2
    # n'élève jamais (table repr vide/absente = no-op WARNING throttlé,
    # erreur = compteur shadow_v2_error séparé). `served_ids` = la vérité du
    # chemin servi FINAL (y compris serve R3 si GO-gaté actif).
    # ------------------------------------------------------------------
    if context_shadow.shadow_v2_enabled():
        await context_shadow.run_shadow_v2(
            db,
            query_embedding=query_embedding,
            query_text=payload.query,
            scope=scope_value,
            kind=kind_value,
            since=since_value,
            k=payload.k,
            consumer=ce_consumer,
            served_ids=[str(r.id) for r in results],
        )

    # Monitoring déficit recall Phase 8+ — top_1_distance loggé
    # à chaque appel. Phase 9 stabilisation utilisera ce signal pour décider
    # de l'activation de l'hybrid scoring conditionnel.
    # `ce_served`/`ce_consumer` : en mode SERVE, result_count
    # reflète la coupe budget/abstention de la décision R3 (0 sur abstention)
    # et top_1_distance reste la distance cosine BRUTE (contrat
    # abstention-valeur : distances servies = brutes, ordre dense, comme
    # prod) — le marqueur permet de séparer les deux populations dans la
    # série de mesures (jamais mélangées sans signal). Flags OFF :
    # ce_served=False, event autrement inchangé.
    top_1_distance = results[0].distance if results else None
    _logger.info(
        "recall.query",
        extra={
            "event": "ready",
            "query_chars": len(payload.query),
            "k": payload.k,
            # Le domaine ne sort qu'en empreinte : filtrer un rappel par domaine
            # est un fait de LA VIE de quelqu'un, pas un fait de la machine
            # (cf. app/journal.py). L'empreinte reste stable, donc « ces
            # quarante rappels portaient tous d0d5c4a2 » se lit encore.
            "scope_sha8": journal.sha8(scope_value),
            "kind": kind_value,
            "since": since_value.isoformat() if since_value else None,
            "result_count": len(results),
            "top_1_distance": top_1_distance,
            "ce_served": ce_served,
            "ce_consumer": ce_consumer,
        },
    )
    return results


@router.post("/resume", response_model=ResumeResponse)
async def resume(
    payload: ResumeRequest,
    db: Annotated[AsyncConnection, Depends(get_db)],
) -> ResumeResponse:
    """POST /v1/atoms/resume — routeur de reprise de projet (P-V6-017).

    embed(query) -> plus proche centroïde de scope (`arac.project_registry`) -> recall
    dense RESTREINT à ce scope, avec expansion top-2 sur quasi-égalité. REJET OPEN-SET
    (distance > 0.70) -> fail-open = recall nu (jamais casser une reprise). Additif ;
    recall / context_router / curateur GELÉS. Zéro LLM read-path (embedding ≠ LLM).
    """
    query_embedding = await embed(payload.query)
    enabled = os.environ.get("ARAC_PROJECT_ROUTER_ENABLED", "false").strip().lower() == "true"
    r = await project_registry.route(db, query_embedding, k=payload.k, enabled=enabled)
    return ResumeResponse(
        routed_scope=r["routed_scope"], rejected=r["rejected"], reason=r.get("reason"),
        candidates=r["candidates"], atoms=r["atoms"],
    )


@router.post("/recall_fresh", response_model=list[AtomReadWithDistance])
async def recall_fresh(
    payload: RecallFreshRequest,
    db: Annotated[AsyncConnection, Depends(get_db)],
) -> list[AtomReadWithDistance]:
    """POST /v1/atoms/recall_fresh — kNN dense + filtre stale (Phase D.6 Tier 2).

    Reprend la mécanique de /recall (embed + cosine kNN sur halfvec(3072)) en
    ajoutant un filtre côté SQL pour ne retourner que les atomes "frais" au
    sens du prototype antérieur :
      - updated_at >= NOW() - days (récents)
      OU
      - 'pierre-angulaire' ∈ tags (doctrine exemptée du staleness)

    GOTCHA (cf atome pierre-angulaire `recall-fresh-filtre-lecture` à venir) :
    c'est un FILTRE DE LECTURE, pas une mutation. Les atomes stales restent
    `status='active'` en BDD et restent accessibles via /recall, /context_for,
    GET /v1/atoms/{id} et list_atoms. Seul ce endpoint les masque.

    PROSPECTIF — Phase D.6 Tier 2 :
      - Seuil 14 jours hérité du prototype antérieur, jamais recalibré pour ARAC.
      - Le prototype antérieur exposait aussi une 3e exemption via colonne `confirmed_until`
        (UPDATE SQL direct par superuser pour prolonger la fraîcheur d'un
        atome sans le supersede). Cette colonne n'est PAS présente en BDD ARAC
        au 2026-05-20 (vérifié via information_schema.columns) — la décision
        de l'ajouter ou non est explicitement reportée : une colonne de
        péremption sans doctrine d'usage est un champ mort de plus. Elle
        attend un incident qui la motive. Le SQL ci-dessous ne référence donc PAS
        la colonne pour éviter UndefinedColumn ; si Phase E décide de
        l'introduire, ajouter le OR ici + colonne migration séparée.

    Index utilisé : `ix_memory_atoms_embedding` (HNSW halfvec_cosine_ops,
    paramètres HNSW épinglés). Le filtre stale est appliqué post-tri kNN — la sélectivité du
    filtre étant typiquement haute (atomes récents), l'overhead est minimal.
    """
    query_embedding = await embed(payload.query)
    scope_value = payload.scope.value if payload.scope else None
    kind_value = payload.kind.value if payload.kind else None

    sql = """
        SELECT id, kind, scope, key, value, desc_hash, tags, status,
               superseded_by, confidence, audit_source, confidence_score,
               source_ref, rationale, node_id, session_id, version,
               created_at, updated_at,
               embedding <=> %s::halfvec(3072) AS distance
        FROM arac.memory_atoms
        WHERE status = 'active'
          AND embedding IS NOT NULL
          AND (
              updated_at >= NOW() - (%s::int * INTERVAL '1 day')
              OR 'pierre-angulaire' = ANY(tags)
          )
          AND (%s::text IS NULL OR scope = %s)
          AND (%s::text IS NULL OR kind = %s)
        ORDER BY embedding <=> %s::halfvec(3072)
        LIMIT %s
    """
    params = (
        query_embedding,
        payload.days,
        scope_value, scope_value,
        kind_value, kind_value,
        query_embedding,
        payload.k,
    )

    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()

    results = [_row_to_atom_read_with_distance(r) for r in rows]

    top_1_distance = results[0].distance if results else None
    _logger.info(
        "recall_fresh.query",
        extra={
            "event": "ready",
            "query_chars": len(payload.query),
            "days": payload.days,
            "k": payload.k,
            "scope_sha8": journal.sha8(scope_value),
            "kind": kind_value,
            "result_count": len(results),
            "top_1_distance": top_1_distance,
        },
    )
    return results


@router.post("/context_for", response_model=ContextBundle)
async def context_for(
    payload: ContextForRequest,
    db: Annotated[AsyncConnection, Depends(get_db)],
) -> ContextBundle:
    """POST /v1/atoms/context_for — bundle thématique kNN + foundations.

    Mécanique exacte :
      1. embed(topic) — 1 appel OpenAI.
      2. Requête A — SELECT thématique LIMIT k * 8 (overshoot Option α, tranché
         Phase 4 V-init pour compenser le ratio 15 buckets ARAC vs 6 du prototype antérieur).
      3. Requête B — SELECT foundations (tag pierre-angulaire) sans top-k,
         tri ordinal KIND_ORDER puis key ASC.
      4. Merge Python :
         a. Injection foundations en premier dans les buckets (par kind).
         b. Atomes thématiques : skip si déjà dans foundation_ids (anti-double
            — un atome thématique aussi pierre-angulaire compte 1×, sous le
            canal foundation). Sinon append jusqu'au cap k par bucket. Si le
            bucket est déjà saturé par les foundations → saturation_warning
            (la doctrine ne passe jamais à la trappe, l'écart est
            exposé, pas masqué).

    Buckets keyed par kind value (Option α, 15 entrées). Foundations ont
    distance=None ; thématiques portent leur cosine distance.

    Index utilisés : `ix_memory_atoms_embedding` (HNSW) pour A,
    `ix_memory_atoms_tags` (GIN) pour B.
    """
    topic_embedding = await embed(payload.topic)

    # Requête A — thématique avec overshoot k * _CONTEXT_FOR_OVERSHOOT
    sql_thematic = """
        SELECT id, kind, scope, key, value, desc_hash, tags, status,
               superseded_by, confidence, audit_source, confidence_score,
               source_ref, rationale, node_id, session_id, version,
               created_at, updated_at,
               embedding <=> %s::halfvec(3072) AS distance
        FROM arac.memory_atoms
        WHERE status = 'active'
          AND embedding IS NOT NULL
        ORDER BY embedding <=> %s::halfvec(3072)
        LIMIT %s
    """
    thematic_limit = payload.k * _CONTEXT_FOR_OVERSHOOT

    # Requête B — foundations (tag pur, pas d'embedding, pas de top-k)
    sql_foundations = f"""
        SELECT id, kind, scope, key, value, desc_hash, tags, status,
               superseded_by, confidence, audit_source, confidence_score,
               source_ref, rationale, node_id, session_id, version,
               created_at, updated_at
        FROM arac.memory_atoms
        WHERE status = 'active'
          AND tags @> ARRAY[%s]::text[]
        ORDER BY {_KIND_ORDER_CASE_SQL}, key ASC
    """

    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            sql_thematic, (topic_embedding, topic_embedding, thematic_limit)
        )
        thematic_rows = await cur.fetchall()
        await cur.execute(sql_foundations, (_PIERRE_ANGULAIRE_TAG,))
        foundation_rows = await cur.fetchall()

    # Initialiser un bucket vide par kind (Option α — 15 buckets stables même
    # si certains restent vides ; permet au LLM consommateur de raisonner
    # uniformément sur la structure de réponse).
    buckets: dict[str, list[AtomReadWithDistance]] = {k.value: [] for k in KIND_ORDER}
    foundation_ids: list[UUID] = []
    foundation_id_set: set[str] = set()
    saturation_warning: list[str] = []

    # Step 1 — injection foundations en premier (distance=None côté merge)
    for f_row in foundation_rows:
        f_atom = _row_to_atom_read_with_distance({**f_row, "distance": None})
        bucket_key = f_atom.kind.value if hasattr(f_atom.kind, "value") else f_atom.kind
        buckets[bucket_key].append(f_atom)
        foundation_ids.append(f_atom.id)
        foundation_id_set.add(str(f_atom.id))

    # Step 2 — atomes thématiques avec anti-double + cap par bucket
    for t_row in thematic_rows:
        t_id_str = str(t_row["id"])
        if t_id_str in foundation_id_set:
            # Anti-double : déjà compté sous le canal foundation
            continue
        t_atom = _row_to_atom_read_with_distance(t_row)
        bucket_key = t_atom.kind.value if hasattr(t_atom.kind, "value") else t_atom.kind
        bucket = buckets[bucket_key]
        if len(bucket) < payload.k:
            bucket.append(t_atom)
        else:
            saturation_warning.append(
                f"{bucket_key} bucket saturated by {len(bucket)} foundations, "
                f"thematic atom {t_atom.key} (distance={t_atom.distance:.4f}) not added"
            )

    # Log structuré pour validation du critère "2 SQL + 1 merge" (Phase 4)
    _logger.info(
        "context_for.bundle",
        extra={
            "event": "ready",
            "topic_chars": len(payload.topic),
            "k": payload.k,
            "thematic_overshoot": _CONTEXT_FOR_OVERSHOOT,
            "thematic_rows_fetched": len(thematic_rows),
            "foundation_count": len(foundation_ids),
            "bucket_sizes": {k: len(v) for k, v in buckets.items() if v},
            "saturation_warning_count": len(saturation_warning),
        },
    )

    return ContextBundle(
        topic=payload.topic,
        k=payload.k,
        buckets=buckets,
        foundation_ids=foundation_ids,
        saturation_warning=saturation_warning,
    )


@router.get("/foundations", response_model=list[AtomRead])
async def foundations(
    db: Annotated[AsyncConnection, Depends(get_db)],
) -> list[AtomRead]:
    """GET /v1/atoms/foundations — filtre tag pur pierre-angulaire.

    Retourne tous les atomes `status='active' AND tags @> ARRAY['pierre-angulaire']`.
    Pas d'embedding, pas de top-k — toute la doctrine. Tri ordinal par
    KIND_ORDER puis key ASC pour stabilité de réponse.

    Index utilisé : `ix_memory_atoms_tags` (GIN).

    Usage typique : onboarding session LLM sans
    sujet précis, read discipline en début de conversation MCP.
    """
    sql = f"""
        SELECT id, kind, scope, key, value, desc_hash, tags, status,
               superseded_by, confidence, audit_source, confidence_score,
               source_ref, rationale, node_id, session_id, version,
               created_at, updated_at
        FROM arac.memory_atoms
        WHERE status = 'active'
          AND tags @> ARRAY[%s]::text[]
        ORDER BY {_KIND_ORDER_CASE_SQL}, key ASC
    """

    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, (_PIERRE_ANGULAIRE_TAG,))
        rows = await cur.fetchall()
    return [_row_to_atom_read(r) for r in rows]


@router.get("/by-key", response_model=AtomRead)
async def get_atom_by_key(
    scope: str,
    key: str,
    db: Annotated[AsyncConnection, Depends(get_db)],
) -> AtomRead:
    """GET /v1/atoms/by-key?scope=&key= — l'atome ACTIF du slot (scope,key), ou 404.

    Ajout marginal du disposant : la résolution OBLIGATOIRE des 409 par le disposant
    cortex a besoin d'un fetch déterministe de l'incumbent (le 409 de POST ne
    porte pas son id ; `list_atoms` est paginé/ordonné autrement). Lecture de
    l'index partiel `ux_memory_atoms_active_scope_key` — une row au plus par
    construction (contrainte UNIQUE active).

    NB routage : déclaré AVANT `/{atom_id}` (l'ordre de déclaration FastAPI
    fait foi — sinon « by-key » serait avalé comme un atom_id).
    """
    sql = """
        SELECT id, kind, scope, key, value, desc_hash, tags, status,
               superseded_by, confidence, audit_source, confidence_score,
               source_ref, rationale, node_id, session_id, version,
               created_at, updated_at
        FROM arac.memory_atoms
        WHERE status = 'active' AND scope = %s AND key = %s
        LIMIT 1
    """
    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, (scope, key))
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404,
                            detail=f"Aucun atome actif pour (scope={scope}, key={key})")
    return _row_to_atom_read(row)


@router.get("/{atom_id}/lineage", response_model=LineageRead)
async def lineage(
    atom_id: UUID,
    db: Annotated[AsyncConnection, Depends(get_db)],
) -> LineageRead:
    """GET /v1/atoms/{id}/lineage — chaîne complète de supersession.

    Construit la lineage bidirectionnelle via deux CTE récursives sur la
    colonne `superseded_by` (chaque atome `superseded` pointe vers
    sa version `active` qui le remplace).

    - Ancestors (depth < 0) : chaînes de versions antérieures qui ont été
      remplacées en arrivant à l'atome cible. Cas marginal : plusieurs
      ancêtres au même depth si des "merges" de chaînes existent (deux
      atomes pointant le même superseded_by — autorisé par le schéma).
    - Self (depth = 0) : l'atome cible lui-même. Toujours présent.
    - Descendants (depth > 0) : chaîne de versions postérieures dont
      l'atome cible est lui-même l'ancêtre, jusqu'à la version finale
      (celle qui a status='active' ou qui n'a pas de superseded_by).

    Tri final par depth ASC, puis created_at ASC pour stabilité au sein
    d'un même depth.

    Index utilisé : `ix_memory_atoms_superseded` (btree partial WHERE
    superseded_by IS NOT NULL).

    404 si l'atome cible n'existe pas.
    """
    sql = """
        WITH RECURSIVE
        ancestors AS (
            -- Base : parents directs (atomes dont superseded_by = atom_id)
            SELECT id, kind, scope, key, value, desc_hash, tags, status,
                   superseded_by, confidence, audit_source, confidence_score,
                   source_ref, rationale, node_id, session_id, version,
                   created_at, updated_at,
                   -1 AS depth
            FROM arac.memory_atoms
            WHERE superseded_by = %s
            UNION ALL
            -- Step : ancêtre d'ancêtre
            SELECT a.id, a.kind, a.scope, a.key, a.value, a.desc_hash, a.tags,
                   a.status, a.superseded_by, a.confidence, a.audit_source,
                   a.confidence_score, a.source_ref, a.rationale, a.node_id,
                   a.session_id, a.version, a.created_at, a.updated_at,
                   ancestors.depth - 1
            FROM arac.memory_atoms a
            INNER JOIN ancestors ON a.superseded_by = ancestors.id
        ),
        descendants AS (
            -- Base : self (depth=0)
            SELECT id, kind, scope, key, value, desc_hash, tags, status,
                   superseded_by, confidence, audit_source, confidence_score,
                   source_ref, rationale, node_id, session_id, version,
                   created_at, updated_at,
                   0 AS depth
            FROM arac.memory_atoms
            WHERE id = %s
            UNION ALL
            -- Step : descendant via superseded_by
            SELECT a.id, a.kind, a.scope, a.key, a.value, a.desc_hash, a.tags,
                   a.status, a.superseded_by, a.confidence, a.audit_source,
                   a.confidence_score, a.source_ref, a.rationale, a.node_id,
                   a.session_id, a.version, a.created_at, a.updated_at,
                   descendants.depth + 1
            FROM arac.memory_atoms a
            INNER JOIN descendants ON descendants.superseded_by = a.id
        )
        SELECT * FROM ancestors
        UNION ALL
        SELECT * FROM descendants
        ORDER BY depth ASC, created_at ASC
    """
    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, (str(atom_id), str(atom_id)))
        rows = await cur.fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="atom not found")

    chain: list[LineageNode] = []
    for row in rows:
        depth = int(row["depth"])
        if depth < 0:
            branch = LineageBranch.ANCESTOR
        elif depth == 0:
            branch = LineageBranch.SELF
        else:
            branch = LineageBranch.DESCENDANT
        node = LineageNode(
            id=row["id"],
            kind=row["kind"],
            scope=row["scope"],
            key=row["key"],
            value=row["value"],
            desc_hash=row["desc_hash"],
            tags=list(row["tags"] or []),
            status=row["status"],
            superseded_by=row["superseded_by"],
            confidence=row["confidence"],
            audit_source=row["audit_source"],
            confidence_score=row["confidence_score"],
            source_ref=row["source_ref"],
            rationale=row["rationale"],
            node_id=row["node_id"],
            session_id=row["session_id"],
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            depth=depth,
            branch=branch,
        )
        chain.append(node)

    return LineageRead(atom_id=atom_id, chain=chain)


# ============================================================================
# Endpoints CRUD (Phase 2.3)
# ============================================================================


@router.post("", response_model=AtomRead, status_code=201)
async def create_atom(
    payload: AtomCreate,
    db: Annotated[AsyncConnection, Depends(get_db)],
) -> AtomRead:
    """POST /v1/atoms — crée un atome.

    Pipeline : Pydantic validate → embed(value) → INSERT halfvec(3072).
    """
    embedding = await embed(payload.value)
    desc_hash = _compute_desc_hash(
        payload.scope.value, payload.kind.value, payload.key, payload.value
    )

    # Phase 1 anti-bruit (doctrine) : kind='agent_message' = TRANSPORT bus,
    # JAMAIS de la mémoire active. Forcé 'archived', NON-OVERRIDEABLE : calculé
    # depuis le seul `kind` (AtomCreate est extra="forbid" -> un client envoyant
    # status reçoit 422). Transport intact (GET /{id} ignore le status ; trigger
    # NOTIFY = AFTER INSERT). Exclu de recall/recall_fresh/context_for/intent_check
    # (tous WHERE status='active'). Promotion explicite = create_atom normal.
    _status = "archived" if payload.kind.value == "agent_message" else "active"

    sql = """
        INSERT INTO arac.memory_atoms (
            kind, scope, key, value, embedding, desc_hash, tags,
            confidence, audit_source, confidence_score, source_ref,
            rationale, node_id, session_id, status
        ) VALUES (
            %s, %s, %s, %s, %s::halfvec(3072), %s, %s,
            %s, %s, %s, %s::jsonb,
            %s, %s, %s, %s
        )
        RETURNING *
    """
    params = (
        payload.kind.value,
        payload.scope.value,
        payload.key,
        payload.value,
        embedding,
        desc_hash,
        payload.tags,
        payload.confidence.value,
        payload.audit_source.value if payload.audit_source else None,
        payload.confidence_score,
        json.dumps(payload.source_ref) if payload.source_ref is not None else None,
        payload.rationale,
        payload.node_id,
        str(payload.session_id) if payload.session_id else None,
        _status,
    )

    with _handle_pg_errors():
        async with db.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            row = await cur.fetchone()
    assert row is not None  # RETURNING * garantit une ligne

    # Phase 4.5 anti-drift — warnings POST.
    # Best-effort, non-bloquants. Calculés après l'INSERT (W-001 doit
    # compter APRÈS commit). Tout échec helper est swallow + logué pour
    # éviter qu'une erreur côté warning casse la création de l'atome.
    atom_read = _row_to_atom_read(row)
    warnings: list[Warning] = []
    try:
        w001 = await _check_w001_pa_budget(db, payload.tags)
        if w001:
            warnings.append(w001)
        w002 = _check_w002_tag_drift(payload.tags)
        if w002:
            warnings.append(w002)
        w003 = _check_w003_rationale_short(payload.kind, payload.rationale)
        if w003:
            warnings.append(w003)
        w005 = _check_w005_world_mix(payload.scope, payload.value)
        if w005:
            warnings.append(w005)
        w006 = await _check_w006_desc_hash_collision(
            db, desc_hash, exclude_id=atom_read.id
        )
        if w006:
            warnings.append(w006)
        w007 = await _check_w007_scope_kind_unprecedented(
            db, payload.node_id, payload.scope, payload.kind,
            exclude_id=atom_read.id,
        )
        if w007:
            warnings.append(w007)
        # W-008 lit la LIGNE RENDUE par la base, jamais le `status` demandé :
        # c'est tout l'intérêt — le trigger BEFORE INSERT a pu le changer.
        w008 = _check_w008_ne_nait_pas_actif(row)
        if w008:
            warnings.append(w008)
    except Exception as exc:  # noqa: BLE001 — best-effort warnings
        _logger.warning(
            "create_atom.warnings_helper_failed",
            extra={"event": "error", "atom_id": str(atom_read.id),
                   "error": journal.raison(exc)},
        )

    _emit_warnings_log("create_atom.warnings", atom_read.id, warnings)

    # Phase 4.6 — persistence audit_log (best-effort, jamais bloquant).
    for warning in warnings:
        await _persist_warning(db, atom_read.id, warning, payload.node_id)

    atom_read.warnings = warnings
    return atom_read


@router.get("/{atom_id}", response_model=AtomRead)
async def get_atom(
    atom_id: UUID,
    db: Annotated[AsyncConnection, Depends(get_db)],
) -> AtomRead:
    """GET /v1/atoms/{id} — lit un atome par ID."""
    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT * FROM arac.memory_atoms WHERE id = %s",
            (str(atom_id),),
        )
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="atom not found")
    return _row_to_atom_read(row)


@router.get("", response_model=list[AtomRead])
async def list_atoms(
    db: Annotated[AsyncConnection, Depends(get_db)],
    scope: Scope | None = None,
    kind: Kind | None = None,
    status: Status | None = None,
    tag: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[AtomRead]:
    """GET /v1/atoms — liste filtrée. ORDER BY created_at DESC."""
    sql = "SELECT * FROM arac.memory_atoms WHERE TRUE"
    params: list[Any] = []
    if scope is not None:
        sql += " AND scope = %s"
        params.append(scope.value)
    if kind is not None:
        sql += " AND kind = %s"
        params.append(kind.value)
    if status is not None:
        sql += " AND status = %s"
        params.append(status.value)
    if tag is not None:
        sql += " AND %s = ANY(tags)"
        params.append(tag)
    sql += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, tuple(params))
        rows = await cur.fetchall()
    return [_row_to_atom_read(r) for r in rows]


@router.patch("/{atom_id}", response_model=AtomRead)
async def update_atom(
    atom_id: UUID,
    payload: AtomUpdate,
    db: Annotated[AsyncConnection, Depends(get_db)],
) -> AtomRead:
    """PATCH /v1/atoms/{id} — partial update.

    Champs IMMUTABLES (rejetés par Pydantic AtomUpdate) : kind, scope, key,
    confidence, audit_source, node_id, session_id. Pour "renommer" un atome,
    utiliser supersede ou créer un nouvel atome.

    `confidence_score`, LUI, EST MODIFIABLE — et il faut le dire, parce que le
    contraire a été imprimé. Le NIVEAU déclaré (`confidence` : producer /
    agent_suggest / auditor_validated) et la trace d'audit (`audit_source`)
    sont refusés ici en `422 extra_forbidden` ; le NOMBRE 0-100 passe. Mesuré
    sur un cerveau réel : `PATCH {"confidence_score": 95}` sur un atome à 40
    rend `200` et la base porte 95.

    ASYMÉTRIE À CONNAÎTRE — elle n'est ni un bug ni un hasard, mais elle
    surprend : le trigger `arac.tg_auto_archive_low_confidence` est **BEFORE
    INSERT**, pas BEFORE UPDATE. Descendre le score sous 70 par ce PATCH-ci
    laisse donc l'atome ACTIF ; le même score atteint par supersédure (qui
    INSÈRE) archive le nouvel atome en `low_confidence_archive`, c'est-à-dire
    hors de `/recall`, qui ne lit que `status='active'`.

    Si `value` change : recalcul auto de `embedding` + `desc_hash` — c'est le
    SEUL champ qui appelle les embeddings. Un cerveau sans clé (mode dégradé)
    sert donc tout le reste de ce PATCH, `confidence_score` compris ; seul
    `value` y rend 503.
    """
    # Récupère scope/kind/key/value pour recalcul si value change
    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT scope, kind, key, value FROM arac.memory_atoms WHERE id = %s",
            (str(atom_id),),
        )
        old = await cur.fetchone()
    if old is None:
        raise HTTPException(status_code=404, detail="atom not found")

    # F2A (doctrine) : un kind='agent_message' est du transport/observabilité,
    # JAMAIS de la mémoire active. Interdire hermétiquement sa réactivation via
    # PATCH (le seul autre chemin status->active possible hors create_atom).
    if (
        old["kind"] == "agent_message"
        and payload.status is not None
        and payload.status.value == "active"
    ):
        raise HTTPException(
            status_code=422,
            detail="agent_message cannot be reactivated",
        )

    set_clauses: list[str] = []
    params: list[Any] = []

    if payload.value is not None and payload.value != old["value"]:
        new_embedding = await embed(payload.value)
        new_hash = _compute_desc_hash(
            old["scope"], old["kind"], old["key"], payload.value
        )
        set_clauses.append("value = %s")
        params.append(payload.value)
        set_clauses.append("embedding = %s::halfvec(3072)")
        params.append(new_embedding)
        set_clauses.append("desc_hash = %s")
        params.append(new_hash)

    if payload.tags is not None:
        set_clauses.append("tags = %s")
        params.append(payload.tags)
    if payload.status is not None:
        set_clauses.append("status = %s")
        params.append(payload.status.value)
    if payload.source_ref is not None:
        set_clauses.append("source_ref = %s::jsonb")
        params.append(json.dumps(payload.source_ref))
    if payload.rationale is not None:
        set_clauses.append("rationale = %s")
        params.append(payload.rationale)
    if payload.confidence_score is not None:
        set_clauses.append("confidence_score = %s")
        params.append(payload.confidence_score)

    if not set_clauses:
        # No-op — retourner l'atome inchangé
        async with db.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT * FROM arac.memory_atoms WHERE id = %s", (str(atom_id),)
            )
            row = await cur.fetchone()
        assert row is not None
        return _row_to_atom_read(row)

    sql = (
        f"UPDATE arac.memory_atoms SET {', '.join(set_clauses)} "
        f"WHERE id = %s RETURNING *"
    )
    params.append(str(atom_id))

    with _handle_pg_errors():
        async with db.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, tuple(params))
            row = await cur.fetchone()
    assert row is not None
    return _row_to_atom_read(row)


@router.delete("/{atom_id}", response_model=AtomRead)
async def soft_delete_atom(
    atom_id: UUID,
    db: Annotated[AsyncConnection, Depends(get_db)],
) -> AtomRead:
    """DELETE /v1/atoms/{id} — soft delete : status='archived'.

    Pas de DELETE SQL réel — on garde la trace historique. Si l'atome n'est
    pas en status='active' (déjà archived ou superseded), on retourne 409.
    """
    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            UPDATE arac.memory_atoms
            SET status = 'archived'
            WHERE id = %s AND status = 'active'
            RETURNING *
            """,
            (str(atom_id),),
        )
        row = await cur.fetchone()
    if row is not None:
        return _row_to_atom_read(row)

    # Pas de match : soit atome inexistant, soit status != active
    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT status FROM arac.memory_atoms WHERE id = %s",
            (str(atom_id),),
        )
        existing = await cur.fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="atom not found")
    raise HTTPException(
        status_code=409,
        detail=f"atom already in status '{existing['status']}', cannot soft-delete",
    )


@router.post("/{atom_id}/supersede", response_model=AtomRead, status_code=201)
async def supersede_atom(
    atom_id: UUID,
    payload: AtomSupersede,
    db: Annotated[AsyncConnection, Depends(get_db)],
) -> AtomRead:
    """POST /v1/atoms/{id}/supersede — version un nouvel atome remplaçant l'ancien.

    Mécanique en 3 étapes (cf docstring module) :
    1. SELECT old (sans FOR UPDATE) — récupère scope/kind/key/...
    2. embed(new_value) HORS transaction — pool DB libre pendant ~200-300ms
    3. Transaction courte : SELECT FOR UPDATE re-check + INSERT new + UPDATE old
    """
    # Étape 1 : SELECT old sans lock
    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
            SELECT id, kind, scope, key, value, tags, rationale, source_ref,
                   confidence, audit_source, confidence_score, version, status
            FROM arac.memory_atoms WHERE id = %s
            """,
            (str(atom_id),),
        )
        old = await cur.fetchone()
    if old is None:
        raise HTTPException(status_code=404, detail="atom not found")
    if old["status"] != "active":
        raise HTTPException(
            status_code=409,
            detail=f"only active atoms can be superseded (got status='{old['status']}')",
        )

    # Garde tag pierre-angulaire — Option A + W-004.
    # Si l'ancien atome porte le tag 'pierre-angulaire' et que new_tags est
    # explicitement fourni (pas None = pas d'héritage) sans contenir le tag,
    # et que le flag d'acquittement est False → 409 bloquant. Placée AVANT
    # l'embed pour économiser l'appel OpenAI sur rejet.
    #
    # Phase 4.5 : le 409 retourne un body structuré avec un Warning W-004
    # critical (règle héritée de la doctrine anti-dérive)
    # §3.2 W-004). Le flag `acknowledge_drop_pierre_angulaire=true` reste la
    # voie consciente de démotion.
    old_tags = list(old["tags"] or [])
    if _PIERRE_ANGULAIRE_TAG in old_tags:
        new_tags_explicit = payload.new_tags is not None
        new_tags_drops_pa = (
            new_tags_explicit and _PIERRE_ANGULAIRE_TAG not in payload.new_tags
        )
        if new_tags_drops_pa and not payload.acknowledge_drop_pierre_angulaire:
            w004 = _build_w004_warning(
                atom_id=atom_id,
                old_key=old["key"],
                old_version=old["version"],
                new_tags=payload.new_tags,
                new_rationale=payload.new_rationale,
            )
            _emit_warnings_log("supersede_atom.w004_blocking", atom_id, [w004])
            raise HTTPException(
                status_code=409,
                detail={
                    "message": (
                        f"atom {atom_id} carries tag '{_PIERRE_ANGULAIRE_TAG}' "
                        f"and new_tags={payload.new_tags} would drop it. "
                        f"Set acknowledge_drop_pierre_angulaire=true to confirm "
                        f"the drop explicitly (Option A)."
                    ),
                    "warnings": [w004.model_dump()],
                },
            )

    # Étape 2 : embed HORS transaction
    new_embedding = await embed(payload.new_value)
    new_hash = _compute_desc_hash(
        old["scope"], old["kind"], old["key"], payload.new_value
    )

    # Convention héritage : None → hérite, [] / {} → remplace par vide
    new_tags = (
        payload.new_tags if payload.new_tags is not None else list(old["tags"] or [])
    )
    new_rationale = (
        payload.new_rationale if payload.new_rationale is not None else old["rationale"]
    )
    new_source_ref = (
        payload.new_source_ref
        if payload.new_source_ref is not None
        else old["source_ref"]
    )
    # LE QUATRIÈME CHAMP HÉRITAIT DANS LA DOCSTRING ET NULLE PART AILLEURS.
    #
    # `AtomSupersede` promet, noir sur blanc — « `confidence_score` =
    # `new_confidence_score` si fourni sinon `old.confidence_score` ». Le
    # `INSERT` ci-dessous passait `payload.new_confidence_score` BRUT. Une
    # supersédure qui ne parlait pas du chiffre — c'est-à-dire le cas normal,
    # « je corrige le fond, pas la confiance » — écrivait donc `NULL`.
    #
    # Mesuré sur un cerveau réel (banc 5471/8271, 9 août 2026) : atome à `40`,
    # `POST /v1/atoms/<id>/supersede {"new_value": …, "new_node_id": …}` → 201,
    # nouvel atome `confidence_score = NULL`. Les trois autres champs de la
    # même convention — `tags`, `rationale`, `source_ref` — héritaient
    # correctement dans la MÊME requête : la perte ne se voyait donc pas comme
    # une panne, mais comme un trou d'un seul champ.
    #
    # Ce que coûtait ce `NULL` : `ConfidenceModifier.adjust` traite `None`
    # comme « inconnue, neutre » (app/context/calibration.py) et
    # `context_router._relevance` lui substitue `50`. Un souvenir corrigé
    # perdait donc, en silence, la confiance qu'il avait gagnée — et le
    # cockpit affichait « — » là où il affichait un chiffre la veille.
    new_confidence_score = (
        payload.new_confidence_score
        if payload.new_confidence_score is not None
        else old["confidence_score"]
    )

    # Étape 3 : transaction courte
    with _handle_pg_errors():
        async with db.transaction():
            async with db.cursor(row_factory=dict_row) as cur:
                # Re-check FOR UPDATE — bloque tout supersede concurrent
                await cur.execute(
                    "SELECT status FROM arac.memory_atoms WHERE id = %s FOR UPDATE",
                    (str(atom_id),),
                )
                check = await cur.fetchone()
                if check is None:
                    raise HTTPException(status_code=404, detail="atom disappeared during supersede")
                if check["status"] != "active":
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"atom status changed during supersede "
                            f"(was active, now '{check['status']}')"
                        ),
                    )

                # 1. UPDATE old → status='superseded' (libère le slot UNIQUE WHERE
                #    status='active' avant l'INSERT new, sinon collision sur
                #    ux_memory_atoms_active_scope_key)
                await cur.execute(
                    """
                    UPDATE arac.memory_atoms
                    SET status = 'superseded'
                    WHERE id = %s
                    """,
                    (str(atom_id),),
                )

                # 2. INSERT new atom (peut maintenant prendre status='active')
                await cur.execute(
                    """
                    INSERT INTO arac.memory_atoms (
                        kind, scope, key, value, embedding, desc_hash, tags,
                        confidence, audit_source, confidence_score, source_ref,
                        rationale, node_id, session_id, version, status
                    ) VALUES (
                        %s, %s, %s, %s, %s::halfvec(3072), %s, %s,
                        %s, %s, %s, %s::jsonb,
                        %s, %s, %s, %s, 'active'
                    )
                    RETURNING *
                    """,
                    (
                        old["kind"],
                        old["scope"],
                        old["key"],
                        payload.new_value,
                        new_embedding,
                        new_hash,
                        new_tags,
                        old["confidence"],
                        old["audit_source"],
                        new_confidence_score,
                        json.dumps(new_source_ref) if new_source_ref is not None else None,
                        new_rationale,
                        payload.new_node_id,
                        str(payload.new_session_id) if payload.new_session_id else None,
                        old["version"] + 1,
                    ),
                )
                new_row = await cur.fetchone()
                assert new_row is not None

                # 3. UPDATE old → superseded_by = new.id (lien explicite vers la version active)
                await cur.execute(
                    """
                    UPDATE arac.memory_atoms
                    SET superseded_by = %s
                    WHERE id = %s
                    """,
                    (str(new_row["id"]), str(atom_id)),
                )

    # Phase 4.5 anti-drift — warnings supersede (W-001, W-002, W-003, W-005, W-006).
    # W-004 traité en amont (409 bloquant). W-007 pas applicable au supersede
    # (kind/scope hérités donc déjà précédentés pour ce node_id, sauf cas
    # marginal d'un node sans aucun atome préalable — improbable post-create).
    atom_read = _row_to_atom_read(new_row)
    warnings: list[Warning] = []
    try:
        w001 = await _check_w001_pa_budget(db, new_tags)
        if w001:
            warnings.append(w001)
        w002 = _check_w002_tag_drift(new_tags)
        if w002:
            warnings.append(w002)
        w003 = _check_w003_rationale_short(old["kind"], new_rationale)
        if w003:
            warnings.append(w003)
        w005 = _check_w005_world_mix(old["scope"], payload.new_value)
        if w005:
            warnings.append(w005)
        w006 = await _check_w006_desc_hash_collision(
            db, new_hash, exclude_id=atom_read.id
        )
        if w006:
            warnings.append(w006)
        # W-008 — LE cas qui coûte un souvenir : l'ancien vient d'être marqué
        # `superseded` et le remplaçant naît archivé. Le domaine et la clé
        # n'ont alors PLUS AUCUN atome actif, et la réponse reste un 201.
        w008 = _check_w008_ne_nait_pas_actif(new_row)
        if w008:
            warnings.append(w008)
    except Exception as exc:  # noqa: BLE001 — best-effort warnings
        _logger.warning(
            "supersede_atom.warnings_helper_failed",
            extra={"event": "error", "atom_id": str(atom_read.id),
                   "error": journal.raison(exc)},
        )

    _emit_warnings_log("supersede_atom.warnings", atom_read.id, warnings)

    # Phase 4.6 — persistence audit_log (best-effort, jamais bloquant).
    # node_id : prend celui du nouvel atome (RETURNING * de l'INSERT supersede)
    # — déjà résolu côté DB (payload.new_node_id si fourni, sinon hérité).
    for warning in warnings:
        await _persist_warning(db, atom_read.id, warning, atom_read.node_id)

    atom_read.warnings = warnings
    return atom_read
