"""Proposal Lifecycle — machine à états du cycle de vie des propositions (v1, PUR).

Modélise le cycle de vie complet d'une proposition `state:current` demandé par la
mission V0.60 :

    draft → generated → ready_for_review → approved → applied
                              ↘ rejected        ↘ superseded
            (à tout moment) → expired / failed / superseded

**Aucune DB, aucune API, aucune écriture mémoire, aucun POST atome.** Ce module ne
fait QUE manipuler des dicts de proposition en mémoire (transitions, expiration,
journal d'audit). La persistance reste au `current_state_proposal_store`. L'état
`applied` est MODÉLISÉ (préparation Phase 10) mais n'est JAMAIS atteignable
automatiquement : la transition vers `applied` exige `human_approved=True` ET ne
confère AUCUNE capacité d'écriture (l'écriture réelle d'un atome reste un chemin
humain L5 prospectif, hors de ce moteur).

INVARIANTS (verrouillés par tests) :
  - une transition illégale lève `LifecycleError` (jamais de saut d'état silencieux) ;
  - `apply_transition` retourne une COPIE (jamais de mutation en place) ;
  - chaque transition ajoute une entrée horodatée au `lifecycle_log` (audit) ;
  - `approved`/`rejected`/`applied` exigent un `actor` ; `applied` exige `human_approved=True` ;
  - `auto_apply_allowed`/`write_allowed` sont re-forcés à False si présents
    (le cycle de vie ne grante jamais une écriture) ;
  - expiration : un état non terminal dont `expires_at` est dépassé devient `expired`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

ENGINE_VERSION = "proposal_lifecycle@v1"

# --- États canoniques -------------------------------------------------------
S_DRAFT = "draft"
S_GENERATED = "generated"
S_READY = "ready_for_review"
S_APPROVED = "approved"
S_REJECTED = "rejected"
S_APPLIED = "applied"
S_SUPERSEDED = "superseded"
S_EXPIRED = "expired"
S_FAILED = "failed"

STATES: tuple[str, ...] = (
    S_DRAFT, S_GENERATED, S_READY, S_APPROVED, S_REJECTED,
    S_APPLIED, S_SUPERSEDED, S_EXPIRED, S_FAILED,
)

# États terminaux : aucune transition sortante « normale ».
TERMINAL_STATES: frozenset[str] = frozenset({S_REJECTED, S_APPLIED, S_SUPERSEDED})

# Transitions légales (graphe explicite). Tout ce qui n'y figure pas est refusé.
# `expired`/`failed` peuvent être régénérés (re-run du reconciler).
LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    S_DRAFT:    frozenset({S_GENERATED, S_FAILED, S_EXPIRED}),
    S_GENERATED: frozenset({S_READY, S_SUPERSEDED, S_EXPIRED, S_FAILED}),
    S_READY:    frozenset({S_APPROVED, S_REJECTED, S_SUPERSEDED, S_EXPIRED, S_FAILED}),
    S_APPROVED: frozenset({S_APPLIED, S_SUPERSEDED, S_EXPIRED, S_FAILED}),
    S_REJECTED: frozenset(),                       # terminal
    S_APPLIED:  frozenset({S_SUPERSEDED}),         # un état appliqué peut être remplacé
    S_SUPERSEDED: frozenset(),                     # terminal
    S_EXPIRED:  frozenset({S_GENERATED}),          # régénérable
    S_FAILED:   frozenset({S_GENERATED}),          # ré-essayable
}

# Transitions exigeant un acteur explicite non-'system' (traçabilité).
# Note : la garantie d'humanité réelle ne porte que sur 'applied' (via human_approved).
_ACTOR_REQUIRED: frozenset[str] = frozenset({S_APPROVED, S_REJECTED, S_APPLIED})

DEFAULT_TTL_DAYS = 14


class LifecycleError(Exception):
    """Transition illégale ou pré-condition de cycle de vie non satisfaite."""


# ---------------------------------------------------------------------------
# Helpers temps (robustes : naïf -> UTC)
# ---------------------------------------------------------------------------
def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _now(now: datetime | None) -> datetime:
    return _aware(now) or datetime.now(timezone.utc)


def _parse_iso(v) -> datetime | None:
    if not v or not isinstance(v, str):
        return None
    try:
        return _aware(datetime.fromisoformat(v.replace("Z", "+00:00")))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def can_transition(from_state: str, to_state: str) -> bool:
    """True si la transition from→to est légale."""
    return to_state in LEGAL_TRANSITIONS.get(from_state, frozenset())


def validate_transition(from_state: str, to_state: str) -> list[str]:
    """Retourne la liste des problèmes (vide = transition légale)."""
    issues: list[str] = []
    if from_state not in STATES:
        issues.append(f"état source inconnu : {from_state!r}")
    if to_state not in STATES:
        issues.append(f"état cible inconnu : {to_state!r}")
    if not issues and not can_transition(from_state, to_state):
        allowed = sorted(LEGAL_TRANSITIONS.get(from_state, frozenset()))
        issues.append(
            f"transition illégale {from_state} → {to_state} "
            f"(autorisées : {allowed or 'aucune (terminal)'})")
    return issues


def default_expires_at(now: datetime | None = None,
                       ttl_days: int = DEFAULT_TTL_DAYS) -> str:
    """Date d'expiration ISO par défaut (now + ttl_days)."""
    return (_now(now) + timedelta(days=ttl_days)).isoformat()


def new_lifecycle(now: datetime | None = None, *, ttl_days: int = DEFAULT_TTL_DAYS,
                  initial_state: str = S_GENERATED) -> dict:
    """Bloc lifecycle initial pour une nouvelle proposition (à fusionner)."""
    if initial_state not in STATES:
        raise LifecycleError(f"état initial invalide : {initial_state!r}")
    n = _now(now)
    return {
        "lifecycle_state": initial_state,
        "lifecycle_created_at": n.isoformat(),
        "expires_at": (n + timedelta(days=ttl_days)).isoformat(),
        "state_reason": "création initiale",
        "lifecycle_log": [{
            "at": n.isoformat(), "from": None, "to": initial_state,
            "actor": "reconciler", "note": "génération initiale",
        }],
    }


def current_state(proposal: dict) -> str:
    """État courant d'une proposition (champ `lifecycle_state`, sinon `status`,
    sinon `generated`)."""
    return (proposal.get("lifecycle_state")
            or proposal.get("status") or S_GENERATED)


def is_expired(proposal: dict, now: datetime | None = None) -> bool:
    """True si `expires_at` est dépassé (et l'état n'est pas déjà terminal)."""
    exp = _parse_iso(proposal.get("expires_at"))
    if exp is None:
        return False
    if current_state(proposal) in TERMINAL_STATES or current_state(proposal) == S_EXPIRED:
        return False
    return _now(now) >= exp


def apply_transition(proposal: dict, to_state: str, *, actor: str = "system",
                     note: str = "", now: datetime | None = None,
                     human_approved: bool = False) -> dict:
    """Applique une transition. PUR : retourne une COPIE, ne mute jamais l'entrée.

    Lève `LifecycleError` si la transition est illégale ou si une pré-condition
    (acteur requis, human_approved pour `applied`) n'est pas satisfaite. N'accorde
    JAMAIS une capacité d'écriture (re-force write_allowed/auto_apply à False)."""
    import copy
    p = copy.deepcopy(proposal)
    frm = current_state(p)

    issues = validate_transition(frm, to_state)
    if issues:
        raise LifecycleError("; ".join(issues))

    if to_state in _ACTOR_REQUIRED and (not actor or actor == "system"):
        raise LifecycleError(
            f"transition vers {to_state} exige un acteur explicite (≠ 'system')")
    if to_state == S_APPLIED and not human_approved:
        raise LifecycleError(
            "transition vers 'applied' exige human_approved=True — l'apply réel "
            "d'un atome est un chemin humain L5 (jamais automatique)")

    n = _now(now)
    p["lifecycle_state"] = to_state
    # Compat : on reflète aussi dans `status` quand c'est un statut connu du store.
    p["status"] = to_state
    p["state_reason"] = note or f"transition {frm} → {to_state}"
    log = list(p.get("lifecycle_log") or [])
    log.append({"at": n.isoformat(), "from": frm, "to": to_state,
                "actor": actor, "note": note})
    p["lifecycle_log"] = log

    # INVARIANT : le cycle de vie ne grante jamais une écriture (même 'applied').
    if "write_allowed" in p:
        p["write_allowed"] = False
    if "would_force" in p:
        p["would_force"] = False
    sens = p.get("sensitivity")
    if isinstance(sens, dict):
        sens["auto_apply_allowed"] = False
    return p


def expire_if_due(proposal: dict, now: datetime | None = None,
                  *, actor: str = "lifecycle-expiry") -> dict:
    """Transitionne vers `expired` si l'expiration est dépassée (sinon inchangé)."""
    if not is_expired(proposal, now):
        return proposal
    frm = current_state(proposal)
    if not can_transition(frm, S_EXPIRED):
        return proposal  # état non-expirable (déjà terminal) : on laisse tel quel
    return apply_transition(proposal, S_EXPIRED, actor=actor,
                            note="expiration automatique (TTL dépassé)", now=now)


def summarize_lifecycle(proposals: list[dict], now: datetime | None = None) -> dict:
    """Agrège l'état du cycle de vie d'un lot de propositions (PUR, lecture seule)."""
    by_state: dict[str, int] = {}
    expired_now: list[str] = []
    actionable: list[str] = []  # ready_for_review = en attente d'action humaine
    for p in (proposals or []):
        st = current_state(p)
        by_state[st] = by_state.get(st, 0) + 1
        if is_expired(p, now):
            expired_now.append(p.get("proposal_id") or p.get("scope") or "?")
        if st == S_READY:
            actionable.append(p.get("proposal_id") or p.get("scope") or "?")
    return {
        "engine_version": ENGINE_VERSION,
        "total": len(proposals or []),
        "by_state": dict(sorted(by_state.items())),
        "expired_due": sorted(expired_now),
        "awaiting_human_review": sorted(actionable),
    }
