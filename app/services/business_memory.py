"""Cerveau métier — logique PURE (Phase F).

Règles métier de la mémoire ARAC, exprimées en fonctions PURES (aucune DB, aucun
réseau) pour être unit-testables ici (Docker absent) ET réutilisables côté API /
crons. Le schéma physique vit dans la migration additive 0013 ; ce module porte
les INVARIANTS :

  - aucune DÉCISION active sans source ;
  - une ancienne décision n'est JAMAIS supprimée -> elle devient `superseded`
    (liens `superseded_by`/`supersedes` posés) ;
  - les contradictions critiques sont VISIBLES (statut `disputed`) ;
  - les recherches courantes EXCLUENT le `superseded` (sauf demande historique) ;
  - une source FRAGILE/TRONQUÉE ne devient pas une vérité active ;
  - une incertitude RESTE une incertitude (pas de promotion silencieuse).

Mapping schéma (cf 01_init.sql + migration 0013) :
  source = `source_ref` (JSONB) ; ingested_at = `created_at` ; observed_at,
  last_verified_at, confirmed_until, supersedes, dedupe_key, semantic_hash =
  colonnes ajoutées en 0013 ; superseded_by déjà présent.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping


class BrainStatus(str, Enum):
    ACTIVE = "active"
    DRAFT = "draft"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"
    LOW_CONFIDENCE_ARCHIVE = "low_confidence_archive"
    DISPUTED = "disputed"
    PENDING_REVIEW = "pending_review"
    BLOCKED = "blocked"


# Statuts rendus par une recherche COURANTE par défaut (le reste est exclu).
DEFAULT_SEARCH_STATUSES = frozenset({BrainStatus.ACTIVE.value})
# Kinds porteurs d'une VÉRITÉ DURABLE : exigent une source pour être actifs.
DURABLE_KINDS = frozenset({"decision", "constraint", "gotcha", "killed", "state"})
# Kinds intrinsèquement INCERTAINS : ne se promeuvent pas en vérité active.
UNCERTAIN_KINDS = frozenset({"question", "idea", "suggestion"})
# Sous le seuil, une confidence est trop faible pour une vérité active.
ACTIVE_MIN_CONFIDENCE = 50


@dataclass
class BrainAtom:
    id: str
    kind: str
    scope: str
    key: str
    value: str = ""
    status: str = BrainStatus.ACTIVE.value
    source_ref: dict[str, Any] | None = None
    node_id: str | None = None
    confidence_score: int | None = None
    project: str | None = None
    observed_at: datetime | None = None
    created_at: datetime | None = None          # = ingested_at
    last_verified_at: datetime | None = None
    confirmed_until: datetime | None = None
    supersedes: str | None = None
    superseded_by: str | None = None
    dedupe_key: str | None = None
    semantic_hash: str | None = None
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "BrainAtom":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})

    def project_of(self) -> str:
        """Projet de l'atome : champ explicite, sinon dérivé du scope (1er segment)."""
        if self.project:
            return self.project
        return (self.scope or "").split(".", 1)[0].split("/", 1)[0]


# --- Dédup ------------------------------------------------------------------
def _esc(s: str) -> str:
    """Échappe le séparateur '/' (et '%') dans un composant de clé, pour éviter
    une collision d'identité quand un scope contient '/' (ex. 'a/b'+'c' vs
    'a'+'b/c'). Réversibilité non requise, seule l'UNICITÉ compte."""
    return (s or "").strip().lower().replace("%", "%25").replace("/", "%2F")


def compute_dedupe_key(scope: str, kind: str, key: str) -> str:
    """Clé d'IDENTITÉ EXACTE (même fait logique). Normalisée, déterministe, et
    SANS collision par injection de séparateur (composants échappés)."""
    return f"{_esc(scope)}/{_esc(kind)}/{_esc(key)}"


def compute_semantic_hash(value: str) -> str:
    """sha256 du `value` normalisé (espaces compactés, casse repliée)."""
    norm = " ".join((value or "").split()).lower()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def _norm_value_text(value: str) -> str:
    return " ".join((value or "").split()).lower()


def find_duplicate(
    candidate: BrainAtom, existing: Iterable[BrainAtom]
) -> BrainAtom | None:
    """Retourne le 1er atome existant (non-superseded) qui DOUBLONNE le candidat,
    par clé d'identité exacte OU hash sémantique. None sinon.

    Garde-fou : le hash sémantique n'est comparé que si les DEUX `value` sont
    non vides — sinon deux atomes SANS value (value='' -> même sha256 du vide)
    seraient faussement déclarés doublons."""
    cand_key = candidate.dedupe_key or compute_dedupe_key(candidate.scope, candidate.kind, candidate.key)
    cand_norm = _norm_value_text(candidate.value)
    cand_hash = candidate.semantic_hash or compute_semantic_hash(candidate.value)
    for a in existing:
        if a.id == candidate.id or a.status == BrainStatus.SUPERSEDED.value:
            continue
        a_key = a.dedupe_key or compute_dedupe_key(a.scope, a.kind, a.key)
        if a_key == cand_key:
            return a
        a_norm = _norm_value_text(a.value)
        if cand_norm and a_norm and (a.semantic_hash or compute_semantic_hash(a.value)) == cand_hash:
            return a
    return None


# --- Validation pour promotion en ACTIF -------------------------------------
# Marqueurs de SOURCE reconnus : schéma générique + schéma réel prod ARAC
# (source_ref = curator_raw_id/message_indices/extracted_by/ingest_node), calibré
# sur données prod (shadow Phase 2).
_SOURCE_KEYS = ("source_path", "path", "type", "uri", "id", "ref",
                "curator_raw_id", "extracted_by", "ingest_node", "conversation_id")


def _source_present(atom: BrainAtom) -> bool:
    s = atom.source_ref
    if not isinstance(s, Mapping) or not s:
        return False
    return any(str(s.get(k) or "").strip() for k in _SOURCE_KEYS)


def _source_fragile(atom: BrainAtom) -> bool:
    s = atom.source_ref or {}
    if not isinstance(s, Mapping):
        return False
    if s.get("fragile") is True:
        return True
    return str(s.get("reliability", "")).strip().lower() in {"low", "fragile", "weak"}


def validate_for_active(atom: BrainAtom, *, source_truncated: bool = False) -> list[str]:
    """Retourne la liste des RAISONS empêchant la promotion en `active` (vide = OK).

    Encode : pas d'actif durable sans source ; source tronquée bloque ; source
    fragile ne devient pas vérité ; incertitude reste incertitude ; confidence
    trop faible ne devient pas active.
    """
    reasons: list[str] = []
    if source_truncated:
        reasons.append("source_truncated")
    if atom.kind in DURABLE_KINDS and not _source_present(atom):
        reasons.append("missing_source")
    if _source_fragile(atom):
        reasons.append("fragile_source")
    if atom.kind in UNCERTAIN_KINDS:
        reasons.append("uncertain_kind")
    if atom.confidence_score is not None and atom.confidence_score < ACTIVE_MIN_CONFIDENCE:
        reasons.append("confidence_too_low")
    return reasons


def can_be_active(atom: BrainAtom, *, source_truncated: bool = False) -> bool:
    return not validate_for_active(atom, source_truncated=source_truncated)


# --- Supersession (jamais de suppression) -----------------------------------
@dataclass
class SupersessionPlan:
    new_id: str
    old_id: str
    old_new_status: str          # 'superseded'
    old_superseded_by: str       # = new_id
    new_supersedes: str          # = old_id
    new_status: str              # 'active'


def supersession_plan(new_atom: BrainAtom, old_atom: BrainAtom) -> SupersessionPlan:
    """Décrit les transitions pour que `new` remplace `old` SANS supprimer `old`.
    PUR : ne mute rien, renvoie le plan (le caller/DB applique)."""
    return SupersessionPlan(
        new_id=new_atom.id,
        old_id=old_atom.id,
        old_new_status=BrainStatus.SUPERSEDED.value,
        old_superseded_by=new_atom.id,
        new_supersedes=old_atom.id,
        new_status=BrainStatus.ACTIVE.value,
    )


# --- Contradiction ----------------------------------------------------------
def _norm_value(v: str) -> str:
    return " ".join((v or "").split()).lower()


def detect_contradiction(a: BrainAtom, b: BrainAtom) -> bool:
    """True si `a` et `b` se contredisent : MÊME (scope, key), tous deux ACTIFS,
    valeurs DIFFÉRENTES, et aucun ne supersede l'autre."""
    if a.id == b.id:
        return False
    if (a.scope, a.key) != (b.scope, b.key):
        return False
    if a.status != BrainStatus.ACTIVE.value or b.status != BrainStatus.ACTIVE.value:
        return False
    if a.superseded_by == b.id or b.superseded_by == a.id:
        return False
    if a.supersedes == b.id or b.supersedes == a.id:
        return False
    return _norm_value(a.value) != _norm_value(b.value)


def find_contradictions(atoms: Iterable[BrainAtom]) -> list[tuple[str, str]]:
    """Paires (id_a, id_b) d'atomes actifs en contradiction (déterministe, sans doublon)."""
    items = list(atoms)
    pairs: list[tuple[str, str]] = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if detect_contradiction(items[i], items[j]):
                pairs.append(tuple(sorted((items[i].id, items[j].id))))  # type: ignore[arg-type]
    return pairs


# --- Fraîcheur --------------------------------------------------------------
def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def is_stale(atom: BrainAtom, now: datetime) -> bool:
    """True si la validité affirmée est dépassée (`confirmed_until` < now)."""
    cu = _aware(atom.confirmed_until)
    if cu is None:
        return False
    return _aware(now) > cu  # type: ignore[operator]


def freshness_report(atoms: Iterable[BrainAtom], now: datetime) -> dict[str, list[str]]:
    """{'fresh': [...], 'stale': [...]} sur les ids des atomes actifs."""
    fresh, stale = [], []
    for a in atoms:
        if a.status != BrainStatus.ACTIVE.value:
            continue
        (stale if is_stale(a, now) else fresh).append(a.id)
    return {"fresh": fresh, "stale": stale}


# --- Recherche --------------------------------------------------------------
def search(
    atoms: Iterable[BrainAtom],
    *,
    scope: str | None = None,
    key: str | None = None,
    project: str | None = None,
    historical: bool = False,
    include_disputed: bool = False,
) -> list[BrainAtom]:
    """Recherche COURANTE par défaut : ne renvoie que les `active` (exclut
    superseded/archived/blocked/draft/pending). `historical=True` renvoie TOUT
    (y compris superseded, pour reconstituer une chronologie avec relations)."""
    out: list[BrainAtom] = []
    allowed = None if historical else set(DEFAULT_SEARCH_STATUSES)
    if allowed is not None and include_disputed:
        allowed.add(BrainStatus.DISPUTED.value)
    for a in atoms:
        if allowed is not None and a.status not in allowed:
            continue
        if scope is not None and a.scope != scope:
            continue
        if key is not None and a.key != key:
            continue
        if project is not None and a.project_of() != project:
            continue
        out.append(a)
    return out


# --- Incertitude ------------------------------------------------------------
def assess_certainty(
    *,
    supporting: int,
    has_source: bool,
    contradicted: bool,
) -> str:
    """'certain' | 'uncertain'. Faute de preuve suffisante OU en contradiction
    -> 'uncertain' (une incertitude reste une incertitude)."""
    if contradicted or not has_source or supporting < 1:
        return "uncertain"
    return "certain"


# --- Reconstruction d'état d'un projet --------------------------------------
def reconstruct_project_state(
    atoms: Iterable[BrainAtom], project: str, now: datetime | None = None
) -> dict[str, Any]:
    """Reconstitue l'état ACTIF d'un projet depuis ses atomes (sources réelles).

    Renvoie : décisions/contraintes/tâches actives (superseded exclus), les
    contradictions visibles, et les incertitudes (atomes actifs SANS source).
    Aucune donnée inventée : si une décision n'a pas de source -> signalée comme
    incertaine plutôt que présentée comme vérité.
    """
    items = [a for a in atoms if a.project_of() == project]
    active = search(items, project=project)  # active only
    decisions = [a for a in active if a.kind == "decision"]
    constraints = [a for a in active if a.kind in {"constraint", "gotcha"}]
    tasks = [a for a in active if a.kind in {"todo", "state"}]
    contradictions = find_contradictions(active)
    uncertainties = [a.id for a in active if a.kind in DURABLE_KINDS and not _source_present(a)]
    report = {
        "project": project,
        "decisions": [a.id for a in decisions],
        "constraints": [a.id for a in constraints],
        "tasks": [a.id for a in tasks],
        "contradictions": contradictions,
        "uncertainties": uncertainties,
        "verdict": "uncertain" if (contradictions or uncertainties) else "reconstructed",
    }
    if now is not None:
        report["stale"] = freshness_report(active, now)["stale"]
    return report
