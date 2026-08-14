"""Current State Proposal Store — v0.30 (PUR côté ARAC, lecture seule mémoire).

Magasin LOCAL de propositions `state:current`. Le sas entre « le reconciler
propose » et « un humain valide ». **N'écrit JAMAIS en mémoire ARAC** : aucune
base de données, aucune API d'écriture, aucun atome posté. La SEULE écriture est
celle d'un fichier JSON local sous un répertoire confiné (par défaut
``var/current_state_proposals/``, gitignoré).

INVARIANTS v0.30 :
  - ``write_allowed`` est **toujours False**, re-forcé à la persistance ; aucun
    flag ne le passe à True ;
  - ``would_force`` toujours False (``force=True`` PROSPECTIF, non implémenté) ;
  - une proposition est validée (`current_state_validator`) ET auditée
    (`current_state_proposal_auditor`) avant d'être stockée ; un verdict
    ``STOP_SECURITY`` ou ``REJECT`` **refuse** la persistance ;
  - confinement strict : ``proposal_id`` est un slug ``csp_<hex>`` ; tout
    ``..`` / séparateur est refusé ; le fichier reste sous ``proposal_dir`` ;
  - aucune suppression : les statuts marquent sans détruire.

Sous-commandes CLI : ``list``, ``read``, ``mark``, ``compare``, ``export``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile

import arac_runtime

from app.brain import current_state_validator as csv_  # noqa: E402 — pur, gardes structurelles
from app.brain import current_state_proposal_auditor as auditor  # noqa: E402 — pur, verdicts
from app.brain import proposal_lifecycle as lifecycle  # noqa: E402 — pur, machine à états
from app.services.sanitize import mask_secrets  # noqa: E402 — 13 patterns

# Confinement (Red-Team #1) : un proposal_dir ne peut écrire QUE sous une racine
# autorisée — `<repo>/var` (défaut prod) ou un répertoire temporaire (tests/démo).
# Tout `..` et tout chemin absolu sortant (configuration systeme, clefs SSH,
# taches planifiees) est refuse.
def _allowed_roots() -> tuple[str, ...]:
    cand = [str(arac_runtime.var_dir()), tempfile.gettempdir()]
    roots = []
    for p in cand:
        try:
            roots.append(os.path.realpath(p))
        except OSError:
            continue
    return tuple(dict.fromkeys(roots))  # dédup, ordre conservé

SCHEMA_VERSION = "v0.30"
GENERATED_BY = "current_state_proposal_store@v0.30"
DEFAULT_PROPOSAL_DIR = "var/current_state_proposals"
KEY_CONVENTION = "current"
PROPOSED_KIND = "state"

# Statuts de cycle de vie d'une proposition. `accepted_candidate` est un
# MARQUAGE humain — ce n'est JAMAIS une écriture mémoire. Les statuts v0.31
# (`write_plan_generated`, `human_rejected`, `write_dry_run_completed`) tracent le
# parcours vers une écriture HUMAINE future — ils restent du MARQUAGE LOCAL :
# aucune base de données, aucun atome posté, aucune table d'atomes écrite.
VALID_STATUSES = (
    "proposed", "needs_review", "rejected",
    "superseded_candidate", "accepted_candidate",
    # v0.31 — sas write plan / gate humain (marquage local uniquement)
    "write_plan_generated", "human_rejected", "write_dry_run_completed",
    # v0.60 — états canoniques du cycle de vie (proposal_lifecycle). Marquage
    # local uniquement : `applied` ne confère JAMAIS une écriture (chemin L5 humain).
    *lifecycle.STATES,
)

WRITE_BLOCKED_REASON = (
    "v0.30 proposal store : aucune écriture mémoire réelle. L'écriture d'un atome "
    "state est de niveau L5 = humain (v0.31 PROSPECTIF). force=True non implémenté.")

# Slug d'id : 'csp_' + hex. Aucun séparateur, aucun '..' possible.
_PROPOSAL_ID_RE = re.compile(r"^csp_[a-f0-9]{8,}$")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class ProposalError(Exception):
    """Erreur générique du proposal store."""


class ProposalSecurityError(ProposalError):
    """Violation de sécurité (write_allowed, force, traversal, secret)."""


class ProposalValidationError(ProposalError):
    """Proposition structurellement invalide (kind/key/scope)."""


# ---------------------------------------------------------------------------
# Helpers purs
# ---------------------------------------------------------------------------
def _as_text(value) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False)


def _parse_now(now_iso):
    """Parse un now ISO (str) en datetime aware, ou None (lifecycle gère None)."""
    if not now_iso or not isinstance(now_iso, str):
        return None
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def make_proposal_id(scope, generated_at, source_atom_ids, summary="") -> str:
    """Id déterministe & unique : sha1(scope|generated_at|sources|summary).
    Idempotent : mêmes entrées ⇒ même id ⇒ même fichier (anti-doublon, R9). Le
    summary est inclus (Red-Team #11) pour qu'un cas SANS source mais au contenu
    DIFFÉRENT ne collisionne pas (sinon écrasement de propositions distinctes)."""
    ids = ",".join(sorted(str(s) for s in (source_atom_ids or []) if s))
    payload = "|".join([scope or "", generated_at or "", ids, summary or ""])
    return "csp_" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _resolve_dir(proposal_dir) -> str:
    """Canonicalise et CONFINE proposal_dir à une racine autorisée (Red-Team #1).

    `os.path.realpath` résout `..` ET les symlinks du chemin lui-même (couvre un
    proposal_dir symlinké). Refuse tout chemin hors `<repo>/var` ou tmp."""
    if not proposal_dir or not isinstance(proposal_dir, str) or "\x00" in proposal_dir:
        raise ProposalSecurityError(f"proposal_dir invalide : {proposal_dir!r}")
    resolved = os.path.realpath(proposal_dir)
    for root in _allowed_roots():
        try:
            if os.path.commonpath([root, resolved]) == root:
                return resolved
        except ValueError:
            continue  # lecteurs différents (Windows) — non pertinent ici
    raise ProposalSecurityError(
        f"proposal_dir hors des racines autorisées (<repo>/var ou tmp) : "
        f"{proposal_dir!r} -> {resolved!r}")


def _safe_proposal_path(proposal_dir, proposal_id) -> str:
    """Chemin confiné d'une proposition. Refuse tout id non-slug ou traversal."""
    if not isinstance(proposal_id, str) or not _PROPOSAL_ID_RE.match(proposal_id):
        raise ProposalSecurityError(
            f"proposal_id invalide (slug 'csp_<hex>' requis) : {proposal_id!r}")
    base = _resolve_dir(proposal_dir)
    path = os.path.abspath(os.path.join(base, proposal_id + ".json"))
    if os.path.commonpath([base, path]) != base:
        raise ProposalSecurityError(f"path traversal refusé : {proposal_id!r}")
    return path


# ---------------------------------------------------------------------------
# Construction d'une proposition à partir d'un candidat reconciler
# ---------------------------------------------------------------------------
def _lineage_from_candidate(candidate: dict) -> str:
    diff = candidate.get("diff") or {}
    if diff.get("has_existing"):
        return ("supersede candidate" if diff.get("supersede_candidate")
                else "snapshot inchangé vs existant")
    return "création (aucun state:current actif)"


def _derive_sensitivity(scope: str | None) -> dict | None:
    """Sensibilité dérivée de la policy centralisée si le candidat ne la porte pas
    (fallback v0.60 — VAGUE 4). Lazy import : ne casse PAS le module si
    sensitivity_policy est absent du checkout (robustesse pré-convergence)."""
    if not scope:
        return None
    try:
        import sensitivity_policy as _sp
        return _sp.classify_scope(scope)
    except Exception:  # noqa: BLE001 — dégradation propre, jamais None forcé en haut
        return None


def build_proposal(candidate: dict, *, now_iso: str | None = None,
                   lineage_notes: str = "") -> dict:
    """Transforme un candidat reconciler en proposition. PUR. `write_allowed`
    est forcé à False — JAMAIS lu depuis l'entrée (R1)."""
    scope = candidate.get("scope")
    generated_at = candidate.get("generated_at") or now_iso or ""
    source_ids = [s for s in (candidate.get("source_atom_ids") or [])
                  if isinstance(s, str) and s.strip()]
    pid = make_proposal_id(scope, generated_at, source_ids,
                           _as_text(candidate.get("summary")))
    # VAGUE 4 — sensibilité TOUJOURS portée (comble le risk=None vu en VAGUE 2) :
    # candidat d'abord, sinon dérivée de la policy. Jamais d'écriture, lecture seule.
    sensitivity = candidate.get("sensitivity") or _derive_sensitivity(scope)
    risk = candidate.get("risk") or (sensitivity or {}).get("risk")
    review_level = candidate.get("review_level") or (sensitivity or {}).get("review_level")
    return {
        "schema_version": SCHEMA_VERSION,
        "proposal_id": pid,
        "scope": scope,
        # On NE normalise PAS silencieusement key/kind : on les reporte tels
        # quels (défaut canonique seulement si absents). Une key/kind invalide
        # doit être DÉTECTÉE et REJETÉE par validate+audit, jamais réécrite (ce
        # qui masquerait une erreur — ex. transformer un 'note' en 'state').
        "proposed_key": candidate.get("proposed_key", KEY_CONVENTION),
        "conceptual_ref": f"{scope}:state:current" if scope else None,
        "proposed_kind": candidate.get("proposed_kind", PROPOSED_KIND),
        "proposed_status": candidate.get("proposed_status", "dry_run"),
        "status": "proposed",
        "summary": candidate.get("summary"),
        "active_decisions": candidate.get("active_decisions", []),
        "blockers": candidate.get("blockers", []),
        "next_actions": candidate.get("next_actions", []),
        "risks": candidate.get("risks", []),
        "stale_items": candidate.get("stale_items", []),
        "source_atom_ids": source_ids,
        "source_count": len(source_ids),
        "source_state_ids": candidate.get("source_state_ids", []),
        "anti_auto_citation_ok": candidate.get("anti_auto_citation_ok", True),
        "no_source_reason": candidate.get("no_source_reason", ""),
        "confidence_level": candidate.get("confidence_level"),
        "confidence_score": candidate.get("confidence_score"),
        "human_review_required": bool(candidate.get("human_review_required")),
        "sensitive_flags": candidate.get("sensitive_flags", []),
        # VAGUE 4 — sensibilité persistée (lisible API/cockpit ; jamais de contenu).
        "risk": risk,
        "review_level": review_level,
        "sensitivity": sensitivity,
        "generated_by": GENERATED_BY,
        "generated_at": generated_at,
        "write_allowed": False,          # INVARIANT — jamais depuis l'entrée
        "would_force": False,            # force=True PROSPECTIF
        "write_blocked_reason": WRITE_BLOCKED_REASON,
        "lineage_notes": lineage_notes or _lineage_from_candidate(candidate),
    }


# ---------------------------------------------------------------------------
# Persistance (fichier local confiné — JAMAIS la mémoire ARAC)
# ---------------------------------------------------------------------------
def _neutralize(proposal: dict, *, mark_tamper: bool = False) -> dict:
    """Force les DEUX invariants d'écriture à False (Red-Team #3/#4). Symétrie :
    write_allowed ET would_force, jamais l'un sans l'autre. Si `mark_tamper`, on
    SIGNALE qu'une valeur disque truthy a été neutralisée (honnêteté > masquage)."""
    if mark_tamper and (proposal.get("write_allowed") not in (False, None)
                        or proposal.get("would_force") not in (False, None)):
        proposal["tamper_detected"] = True
    proposal["write_allowed"] = False
    proposal["would_force"] = False
    return proposal


def _persist(proposal: dict, proposal_dir: str) -> str:
    base = _resolve_dir(proposal_dir)
    os.makedirs(base, exist_ok=True)
    _neutralize(proposal)                    # re-force write_allowed ET would_force
    path = _safe_proposal_path(proposal_dir, proposal["proposal_id"])
    # Anti-symlink (Red-Team #2/#5) : O_NOFOLLOW refuse d'écrire à travers un lien
    # (l'id est déterministe donc prévisible — un lien pré-positionné détournerait
    # l'écriture). islink() ferme aussi le cas avant l'open.
    if os.path.islink(path):
        raise ProposalSecurityError(f"refus d'écrire à travers un symlink : {path}")
    data = json.dumps(proposal, ensure_ascii=False, indent=2)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:                    # ELOOP si lien, etc.
        raise ProposalSecurityError(f"écriture refusée (symlink/erreur) : {path} ({exc})")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(data)
    return path


def create_proposal(candidate: dict, proposal_dir: str = DEFAULT_PROPOSAL_DIR, *,
                    now_iso: str | None = None, lineage_notes: str = "",
                    validate: bool = True) -> tuple[dict, str]:
    """Valide, audite puis stocke une proposition. Retourne (proposition, chemin).

    Refuse la persistance si le candidat porte un signal d'écriture, ou si
    l'audit rend ``STOP_SECURITY`` / ``REJECT``."""
    # Pré-gardes sécurité : un candidat ne doit JAMAIS revendiquer une écriture.
    if candidate.get("write_allowed") not in (False, None):
        raise ProposalSecurityError("candidat avec write_allowed vrai — refus (proposal-only)")
    if candidate.get("would_force"):
        raise ProposalSecurityError("candidat avec would_force vrai — refus (force PROSPECTIF)")

    proposal = build_proposal(candidate, now_iso=now_iso, lineage_notes=lineage_notes)

    issues = csv_.validate_candidate(proposal)
    proposal["validator_result"] = {"safe": not issues, "issues": issues}

    audit = auditor.audit_proposal(proposal)
    proposal["auditor_result"] = {"verdict": audit["verdict"], "reasons": audit["reasons"]}

    if validate:
        if audit["verdict"] == auditor.STOP_SECURITY:
            raise ProposalSecurityError(f"audit STOP_SECURITY : {audit['reasons']}")
        if audit["verdict"] == auditor.REJECT:
            raise ProposalValidationError(f"audit REJECT : {audit['reasons']}")
        proposal["status"] = ("needs_review"
                              if audit["verdict"] == auditor.NEEDS_FIX else "proposed")

    # v0.60 — cycle de vie : toute proposition naît avec un état canonique, une
    # expiration (TTL) et un journal d'audit. `ready_for_review` si l'audit la juge
    # saine ; `generated` sinon (corrections à faire avant revue). Marquage LOCAL :
    # `applied` reste inatteignable sans validation humaine explicite (L5).
    init_state = (lifecycle.S_READY
                  if audit["verdict"] == auditor.GO_FOR_HUMAN_REVIEW
                  else lifecycle.S_GENERATED)
    proposal.update(lifecycle.new_lifecycle(_parse_now(now_iso),
                                            initial_state=init_state))

    return proposal, _persist(proposal, proposal_dir)


def transition_proposal(proposal_dir: str, proposal_id: str, to_state: str, *,
                        actor: str = "system", note: str = "",
                        now=None, human_approved: bool = False) -> dict:
    """Applique une transition de cycle de vie et persiste (marquage LOCAL).

    N'autorise JAMAIS une écriture mémoire : `write_allowed` reste False même pour
    l'état `applied` (l'écriture réelle d'un atome est un chemin humain L5)."""
    proposal = read_proposal(proposal_dir, proposal_id)
    updated = lifecycle.apply_transition(
        proposal, to_state, actor=actor, note=note, now=now,
        human_approved=human_approved)
    updated["write_allowed"] = False        # invariant réaffirmé (marquage ≠ écriture)
    _persist(updated, proposal_dir)
    return updated


# ---------------------------------------------------------------------------
# Lecture / listing / marquage / comparaison
# ---------------------------------------------------------------------------
def read_proposal(proposal_dir: str, proposal_id: str) -> dict:
    path = _safe_proposal_path(proposal_dir, proposal_id)
    if os.path.islink(path):                 # Red-Team #2/#5 : pas de lecture via lien
        raise ProposalSecurityError(f"refus de lire à travers un symlink : {proposal_id}")
    if not os.path.isfile(path):
        raise ProposalError(f"proposition introuvable : {proposal_id}")
    data = json.loads(open(path, encoding="utf-8").read())
    if not isinstance(data, dict):           # Red-Team delta V4 : JSON non-objet
        raise ProposalError(f"proposition corrompue (JSON non-objet) : {proposal_id}")
    # Neutralisation À LA LECTURE (Red-Team #4) : un fichier altéré (write_allowed/
    # would_force truthy) ne peut JAMAIS propager une valeur truthy en aval
    # (summarize/export) ; on signale la falsification au lieu de la masquer.
    return _neutralize(data, mark_tamper=True)


def list_proposals(proposal_dir: str) -> list[dict]:
    base = _resolve_dir(proposal_dir)
    if not os.path.isdir(base):
        return []
    out: list[dict] = []
    for name in sorted(os.listdir(base)):
        if not name.endswith(".json"):
            continue
        full = os.path.join(base, name)
        if os.path.islink(full):             # ignore les entrées symlink
            continue
        try:
            data = json.loads(open(full, encoding="utf-8").read())
        except (ValueError, OSError):
            continue
        if not isinstance(data, dict):       # Red-Team delta V4 : un fichier non-objet
            continue                         # ne doit pas planter l'énumération entière
        out.append(_neutralize(data, mark_tamper=True))
    return out


def summarize(proposal: dict) -> dict:
    """Vue courte d'une proposition (aucun contenu privé)."""
    return {
        "proposal_id": proposal.get("proposal_id"),
        "scope": proposal.get("scope"),
        "status": proposal.get("status"),
        "source_count": proposal.get("source_count"),
        "confidence_score": proposal.get("confidence_score"),
        "human_review_required": proposal.get("human_review_required"),
        "write_allowed": proposal.get("write_allowed", False),
        "verdict": (proposal.get("auditor_result") or {}).get("verdict"),
    }


def filter_proposals(proposals: list[dict], *, scope: str | None = None,
                     status: str | None = None, risk: str | None = None,
                     lifecycle_state: str | None = None,
                     needs_review: bool | None = None) -> list[dict]:
    """Filtre une liste de propositions (PUR, VAGUE 4). `status` matche status OU
    lifecycle_state ; `risk` = sensibilité low|medium|high ; `needs_review` = bool."""
    out: list[dict] = []
    for p in (proposals or []):
        if scope is not None and p.get("scope") != scope:
            continue
        if status is not None and status not in (p.get("status"), p.get("lifecycle_state")):
            continue
        if lifecycle_state is not None and p.get("lifecycle_state") != lifecycle_state:
            continue
        if risk is not None and (p.get("risk") or (p.get("sensitivity") or {}).get("risk")) != risk:
            continue
        if needs_review is not None and bool(p.get("human_review_required")) != bool(needs_review):
            continue
        out.append(p)
    return out


def source_drift(proposal: dict, current_source_ids, *,
                 current_max_updated_at: str | None = None) -> dict:
    """Détecte si les sources d'une proposition ont changé depuis sa génération
    (PUR, lecture seule, VAGUE 4). `current_source_ids` = ids des atomes-sources
    ACTUELS du scope (mêmes critères que la génération) ; `current_max_updated_at`
    = updated_at max des sources actuelles (ISO) pour repérer une édition postérieure
    à `generated_at`. Ne modifie JAMAIS la proposition ni la mémoire."""
    stored = {s for s in (proposal.get("source_atom_ids") or []) if s}
    cur = {s for s in (current_source_ids or []) if s}
    added = sorted(cur - stored)
    removed = sorted(stored - cur)
    gen_at = proposal.get("generated_at") or ""
    newer = bool(current_max_updated_at and gen_at
                 and str(current_max_updated_at) > str(gen_at))
    return {
        "drifted": bool(added or removed or newer),
        "added": added,
        "removed": removed,
        "newer_sources": newer,
        "stored_source_count": len(stored),
        "current_source_count": len(cur),
        "generated_at": gen_at,
    }


def mark_status(proposal_dir: str, proposal_id: str, status: str) -> dict:
    """Marque le statut d'une proposition (local). N'autorise JAMAIS une écriture
    mémoire — `write_allowed` reste False même pour `accepted_candidate`."""
    if status not in VALID_STATUSES:
        raise ProposalValidationError(
            f"statut invalide {status!r} — attendus : {VALID_STATUSES}")
    proposal = read_proposal(proposal_dir, proposal_id)
    # #11 : refuser le marquage si lifecycle_state TERMINAL existe et diverge du status.
    # Évite la désynchronisation status/lifecycle_state après état terminal (applied,
    # rejected, superseded). Les états non-terminaux restent librement marquables.
    ls = proposal.get("lifecycle_state")
    if ls in lifecycle.TERMINAL_STATES and status != ls:
        raise ProposalValidationError(
            f"proposition en état terminal {ls!r} — "
            f"marquage status={status!r} refusé (utiliser transition pour 'superseded')")
    proposal["status"] = status
    proposal["write_allowed"] = False        # marquage ≠ écriture (R10/R14)
    _persist(proposal, proposal_dir)
    return proposal


def expire_due_proposals(proposal_dir: str, now=None) -> list[str]:
    """Transitionne vers `expired` les propositions dont le TTL est dépassé et les
    persiste (MARQUAGE LOCAL — aucune écriture mémoire/DB). Retourne les ids expirés.
    Idempotent : une proposition déjà expirée/terminale est laissée intacte (VAGUE 4)."""
    expired: list[str] = []
    for p in list_proposals(proposal_dir):
        updated = lifecycle.expire_if_due(p, now)
        if updated is not p:                 # une copie transitionnée a été produite
            _persist(updated, proposal_dir)
            expired.append(updated.get("proposal_id"))
    return sorted(x for x in expired if x)


def compare_proposals(a: dict, b: dict) -> dict:
    """Diff structurel entre deux propositions. Aucune écriture."""
    a_ids = set(a.get("source_atom_ids") or [])
    b_ids = set(b.get("source_atom_ids") or [])
    changed: list[str] = []
    if a_ids != b_ids:
        changed.append("source_atom_ids")
    if _as_text(a.get("summary")).strip() != _as_text(b.get("summary")).strip():
        changed.append("summary")
    for f in ("confidence_score", "human_review_required", "status"):
        if a.get(f) != b.get(f):
            changed.append(f)
    a_at, b_at = a.get("generated_at") or "", b.get("generated_at") or ""
    newer, older = (b, a) if b_at >= a_at else (a, b)
    same_scope = a.get("scope") == b.get("scope")
    return {
        "scope_match": same_scope,
        "changed_fields": changed,
        "added_source_ids": sorted(b_ids - a_ids),
        "removed_source_ids": sorted(a_ids - b_ids),
        "newer_proposal_id": newer.get("proposal_id"),
        "older_proposal_id": older.get("proposal_id"),
        "supersede_candidate": bool(changed) and same_scope,
        "write_allowed": False,
    }


def compare_by_id(proposal_dir: str, a_id: str, b_id: str) -> dict:
    return compare_proposals(read_proposal(proposal_dir, a_id),
                             read_proposal(proposal_dir, b_id))


# ---------------------------------------------------------------------------
# Export safe (rédacté — secrets masqués, scope sensible non exposé)
# ---------------------------------------------------------------------------
_REDACTED_SENSITIVE = "[REDACTED:sensitive-scope]"
_CONTENT_TEXT_FIELDS = ("summary", "no_source_reason", "lineage_notes")
_CONTENT_LIST_FIELDS = ("active_decisions", "blockers", "next_actions", "risks",
                        "stale_items")

# Métadonnées structurelles dont la VALEUR est sûre à exposer, même pour un scope sensible
# (ids, slugs, comptes, statuts, drapeaux, timestamps, versions). Tout AUTRE champ texte (ou
# liste de texte) de premier niveau d'un scope sensible est occulté — deny-by-default. Ferme
# le delta Red-Team F-MEDIUM-1 : une proposition forgée/altérée portant une clé non-canonique
# (`value`, `atom_value`, texte libre) ne doit jamais sortir en clair pour un scope sensible.
_SENSITIVE_SAFE_KEYS = frozenset({
    "proposal_id", "scope", "status", "proposed_status", "proposed_kind", "proposed_key",
    "schema_version", "engine_version", "generated_at", "generated_by", "expires_at",
    "lifecycle_state", "confidence_level", "confidence_score",
    "source_count", "source_atom_ids", "source_state_ids",
    "human_review_required", "sensitive_flags", "anti_auto_citation_ok",
    "would_force", "write_allowed", "write_blocked_reason", "risk", "review_level",
})


def _mask_text(s) -> str:
    """Masque secrets connus (13 patterns) + variantes MAJUSCULE (Red-Team #8)."""
    return auditor.mask_loose(mask_secrets(_as_text(s)))


# Racines de monde traitées comme sensibles À L'EXPORT, même en racine nue
# (Red-Team delta V6) : `is_sensitive_scope('perso')` est False (la garde vise
# `perso/<feuille>`), or une proposition forgée/altérée à scope='perso' exporterait
# du contenu privé. Fail-safe : tout ce qui relève du monde `perso` est occulté.
_SENSITIVE_EXPORT_ROOTS = ("perso",)


def _is_sensitive_for_export(scope) -> bool:
    if csv_.is_sensitive_scope(scope):
        return True
    if isinstance(scope, str):
        return scope.strip().lower().split("/")[0] in _SENSITIVE_EXPORT_ROOTS
    return False


def _mask_all(obj):
    """Masquage RÉCURSIF de TOUTE chaîne d'une structure (Red-Team #6) : aucun
    champ texte ne peut échapper (no_source_reason, lineage_notes, stale_items,
    sous-clés d'item arbitraires note/title/detail/text/description…). Les CLÉS de
    dict sont masquées aussi (Red-Team delta V5 : un secret en clé survivait)."""
    if isinstance(obj, str):
        return _mask_text(obj)
    if isinstance(obj, list):
        return [_mask_all(x) for x in obj]
    if isinstance(obj, dict):
        return {(_mask_text(k) if isinstance(k, str) else k): _mask_all(v)
                for k, v in obj.items()}
    return obj


def _redact_proposal(proposal: dict) -> dict:
    """Source UNIQUE de rédaction, partagée par export_json ET export_markdown
    (Red-Team #6/#7/#9). Pour un scope sensible : AUCUN contenu exposé (ni JSON ni
    MD). Sinon : masquage récursif des secrets sur tous les champs."""
    p = json.loads(json.dumps(proposal))      # copie profonde
    if _is_sensitive_for_export(p.get("scope")):
        for f in _CONTENT_TEXT_FIELDS:
            if f in p:
                p[f] = _REDACTED_SENSITIVE
        for f in _CONTENT_LIST_FIELDS:
            if isinstance(p.get(f), list):
                p[f] = [_REDACTED_SENSITIVE for _ in p[f]]  # garde le compte
        # Deny-by-default (F-MEDIUM-1) : occulte tout autre champ texte de 1er niveau non whitelisté.
        for k in list(p.keys()):
            if k in _SENSITIVE_SAFE_KEYS or k in _CONTENT_TEXT_FIELDS or k in _CONTENT_LIST_FIELDS:
                continue
            v = p[k]
            if isinstance(v, str) and v:
                p[k] = _REDACTED_SENSITIVE
            elif isinstance(v, list) and v and all(isinstance(x, str) for x in v):
                p[k] = [_REDACTED_SENSITIVE for _ in v]  # garde le compte
    # Masquage récursif des secrets sur l'ensemble (y compris champs méta).
    p = _mask_all(p)
    # L'export n'autorise jamais une valeur d'écriture truthy.
    p["write_allowed"] = False
    p["would_force"] = False
    return p


def export_json(proposal: dict) -> str:
    return json.dumps(_redact_proposal(proposal), ensure_ascii=False, indent=2)


def export_markdown(proposal: dict) -> str:
    p = _redact_proposal(proposal)
    sensitive = _is_sensitive_for_export(p.get("scope"))
    lines = [
        f"# Proposition state:current — {p.get('scope')}", "",
        f"- proposal_id : `{p.get('proposal_id')}`",
        f"- status : **{p.get('status')}** · verdict : "
        f"{(p.get('auditor_result') or {}).get('verdict')}",
        f"- proposed_key : `{p.get('proposed_key')}` · kind : `{p.get('proposed_kind')}`",
        f"- source_count : {p.get('source_count')} · confidence : "
        f"{p.get('confidence_score')} ({p.get('confidence_level')})",
        f"- human_review_required : **{p.get('human_review_required')}** · "
        f"sensitive_flags : {p.get('sensitive_flags') or '—'}",
        f"- write_allowed : **{p.get('write_allowed')}** — {p.get('write_blocked_reason')}",
        "",
    ]
    if sensitive:
        lines.append("> scope sensible — contenu non exposé (revue humaine requise).")
    else:
        lines.append(f"**Résumé** : {p.get('summary')}")
        lines.append(
            f"- décisions : {len(p.get('active_decisions') or [])} · "
            f"blocages : {len(p.get('blockers') or [])} · "
            f"actions : {len(p.get('next_actions') or [])} · "
            f"risques : {len(p.get('risks') or [])} · "
            f"stale : {len(p.get('stale_items') or [])}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _add_dir(sp):
    sp.add_argument("--proposal-dir", default=DEFAULT_PROPOSAL_DIR,
                    help="Répertoire confiné des propositions (gitignoré).")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Current State Proposal Store — v0.30 (proposal-only, aucune "
                    "écriture mémoire).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="Lister les propositions.")
    _add_dir(p_list)
    p_list.add_argument("--json", action="store_true")

    p_read = sub.add_parser("read", help="Lire une proposition.")
    _add_dir(p_read)
    p_read.add_argument("--id", required=True)
    p_read.add_argument("--json", action="store_true")

    p_mark = sub.add_parser("mark", help="Marquer le statut (local, jamais write).")
    _add_dir(p_mark)
    p_mark.add_argument("--id", required=True)
    p_mark.add_argument("--status", required=True, choices=VALID_STATUSES)

    p_tr = sub.add_parser("transition", help="Transition de cycle de vie (local).")
    _add_dir(p_tr)
    p_tr.add_argument("--id", required=True)
    p_tr.add_argument("--to", required=True, choices=lifecycle.STATES)
    p_tr.add_argument("--actor", default="system")
    p_tr.add_argument("--note", default="")
    p_tr.add_argument("--human-approved", action="store_true",
                      help="Requis pour 'applied' (validation humaine explicite).")

    p_cmp = sub.add_parser("compare", help="Comparer deux propositions.")
    _add_dir(p_cmp)
    p_cmp.add_argument("--a", required=True)
    p_cmp.add_argument("--b", required=True)
    p_cmp.add_argument("--json", action="store_true")

    p_exp = sub.add_parser("export", help="Exporter (safe, rédacté).")
    _add_dir(p_exp)
    p_exp.add_argument("--id", required=True)
    p_exp.add_argument("--format", choices=("markdown", "json"), default="markdown")

    args = parser.parse_args(argv)

    if args.cmd == "list":
        items = [summarize(p) for p in list_proposals(args.proposal_dir)]
        if args.json:
            print(json.dumps({"count": len(items), "proposals": items},
                             ensure_ascii=False, indent=2))
        else:
            print(f"=== Proposals ({len(items)}) — {args.proposal_dir} ===")
            for it in items:
                print(f"  {it['proposal_id']}  {it['scope']:<20} {it['status']:<22} "
                      f"src={it['source_count']} write_allowed={it['write_allowed']}")
        return 0

    if args.cmd == "read":
        proposal = read_proposal(args.proposal_dir, args.id)
        print(json.dumps(proposal, ensure_ascii=False, indent=2) if args.json
              else export_markdown(proposal))
        return 0

    if args.cmd == "mark":
        proposal = mark_status(args.proposal_dir, args.id, args.status)
        print(f"marqué {proposal['proposal_id']} -> status={proposal['status']} "
              f"(write_allowed={proposal['write_allowed']})")
        return 0

    if args.cmd == "transition":
        try:
            p = transition_proposal(args.proposal_dir, args.id, args.to,
                                    actor=args.actor, note=args.note,
                                    human_approved=args.human_approved)
        except lifecycle.LifecycleError as exc:
            print(f"transition refusée : {exc}", file=sys.stderr)
            return 1
        print(f"{p['proposal_id']} -> lifecycle_state={p['lifecycle_state']} "
              f"(write_allowed={p['write_allowed']})")
        return 0

    if args.cmd == "compare":
        print(json.dumps(compare_by_id(args.proposal_dir, args.a, args.b),
                         ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "export":
        proposal = read_proposal(args.proposal_dir, args.id)
        print(export_json(proposal) if args.format == "json"
              else export_markdown(proposal))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
