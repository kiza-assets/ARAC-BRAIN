"""Current State Proposal Auditor — v0.30 (PUR, lecture seule).

Audite une proposition `state:current` (telle que produite/stockée par
`current_state_proposal_store.py`). **Aucune base de données, aucune API, aucune
écriture, aucun POST atome.** L'auditeur ne décide JAMAIS d'écrire : il rend un
verdict parmi :

  - ``GO_FOR_HUMAN_REVIEW`` — proposition saine, prête pour une revue humaine ;
  - ``NEEDS_FIX``          — incohérence corrigeable (source manquante,
                             sensible non flaggé, confidence hors bornes…) ;
  - ``REJECT``             — kind/key/scope invalides (root-level, scope fantôme) ;
  - ``STOP_SECURITY``      — secret, ``write_allowed=true``, marqueur d'écriture
                             base de données / API, ou ``force`` réel.

INVARIANT v0.30 : l'auditeur **ne retourne JAMAIS** ``GO_FOR_WRITE``. Aucune
proposition de v0.30 ne peut être écrite en mémoire — la validation humaine
(v0.31, PROSPECTIF) reste obligatoire avant toute écriture.

Usage :
    python -m app.brain.current_state_proposal_auditor \
        --proposal var/current_state_proposals/<id>.json [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

import arac_runtime

from app.brain import memory_policy as mp  # noqa: E402 — module pur, aucune base de données
from app.brain import current_state_validator as csv_  # noqa: E402 — pur, gardes structurelles
from app.services.sanitize import mask_secrets  # noqa: E402 — 13 patterns

# --- Verdicts (jamais GO_FOR_WRITE) ----------------------------------------
GO_FOR_HUMAN_REVIEW = "GO_FOR_HUMAN_REVIEW"
NEEDS_FIX = "NEEDS_FIX"
REJECT = "REJECT"
STOP_SECURITY = "STOP_SECURITY"
VALID_VERDICTS = frozenset({GO_FOR_HUMAN_REVIEW, NEEDS_FIX, REJECT, STOP_SECURITY})

KEY_CONVENTION = "current"
PROPOSED_KIND = "state"

# Champs de CONTENU à scanner pour secrets / marqueurs d'écriture. On EXCLUT
# volontairement les champs méta (`write_blocked_reason`, `write_allowed`,
# `auditor_result`…) qui contiennent légitimement les mots « POST atome / L5 »
# — les y scanner produirait un faux STOP_SECURITY.
_CONTENT_FIELDS = ("summary", "active_decisions", "blockers", "next_actions",
                   "risks", "stale_items", "lineage_notes", "no_source_reason")

# Marqueurs d'écriture base de données / API / code (haut signal — n'apparaissent
# pas dans une prose d'infra bénigne). Comparaison en minuscules.
_WRITE_CALL_MARKERS = (
    "requests.post", "httpx.post", "conn.commit", "cursor.execute(",
    "insert into", "delete from", "update set", "drop table", "truncate table",
    "post /atoms", "/api/v1/atoms", "session.add(", "db.execute(",
)

# Clés structurelles interdites : si présentes ET vraies, signal de falsification
# (une proposition ne doit JAMAIS porter une capacité d'écriture).
_FORBIDDEN_WRITE_KEYS = (
    "db_write", "api_write", "post_atom", "do_write", "execute_write",
    "commit_write", "memory_write", "force_real",
)


def _as_text(value) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False)


def _content_blob(proposal: dict) -> str:
    return " ".join(_as_text(proposal.get(f)) for f in _CONTENT_FIELDS)


# Durcissement LOCAL v0.30 (Red-Team #8) : les regex partagées de `sanitize` /
# `memory_policy` sont CASE-SENSITIVE sur les préfixes (sk-ant-/ghp_/…), donc une
# variante MAJUSCULE échappe. On ne modifie PAS les modules partagés (frontière +
# test de synchro byte-for-byte) : on ajoute une couche insensible à la casse
# PAR-DESSUS, ciblée sur les préfixes connus (pas de sur-rédaction).
_LOOSE_SECRET_RE = re.compile(
    r"(?i)("
    r"sk-ant-[a-z0-9_\-]{6,}|sk-[a-z0-9]{20,}|"
    r"ghp_[a-z0-9]{20,}|gho_[a-z0-9]{20,}|github_pat_[a-z0-9_]{20,}|"
    r"glpat-[a-z0-9_\-]{6,}|xoxb-[a-z0-9\-]{10,}|"
    r"(?:akia|asia)[a-z0-9]{16}|"
    r"-----begin [a-z ]*private key-----"
    r")")


def has_loose_secret(text) -> bool:
    """Détection insensible à la casse des préfixes de secret connus (couche locale)."""
    return bool(_LOOSE_SECRET_RE.search(text if isinstance(text, str) else ""))


def mask_loose(text) -> str:
    """Masque insensible à la casse des préfixes de secret connus (couche locale)."""
    return _LOOSE_SECRET_RE.sub("[REDACTED:secret]", text if isinstance(text, str) else "")


def _has_secret(blob: str) -> bool:
    # `mask_secrets` (13 patterns) est un sur-ensemble de `contains_secret` (9) :
    # si le masquage change le blob, un secret est présent. + couche CASE-INSENSITIVE
    # locale (Red-Team #8) pour les variantes MAJUSCULE des préfixes.
    return (mp.contains_secret(blob) or mask_secrets(blob) != blob
            or has_loose_secret(blob))


def _real_sources(proposal: dict) -> list[str]:
    raw = proposal.get("source_atom_ids")
    raw = raw if isinstance(raw, list) else []
    return [s for s in raw if isinstance(s, str) and s.strip()]


def audit_proposal(proposal: dict) -> dict:
    """Rend un verdict d'audit pour une proposition (aucune écriture).

    L'ordre est sécurité d'abord (STOP_SECURITY), puis structure (REJECT), puis
    cohérence corrigeable (NEEDS_FIX), enfin GO_FOR_HUMAN_REVIEW."""
    reasons: list[str] = []
    ref = proposal.get("scope") or proposal.get("proposal_id") or "?"

    # =================== 1) SÉCURITÉ — STOP_SECURITY ===================
    if proposal.get("write_allowed") is not False:
        reasons.append(
            f"[{ref}] write_allowed doit être False (proposal-only) — STOP_SECURITY")
        return _verdict(STOP_SECURITY, reasons, proposal)

    if proposal.get("would_force") not in (False, None):
        reasons.append(
            f"[{ref}] would_force vrai — force=True PROSPECTIF, jamais réel — STOP_SECURITY")
        return _verdict(STOP_SECURITY, reasons, proposal)

    bad_keys = [k for k in _FORBIDDEN_WRITE_KEYS if proposal.get(k)]
    if bad_keys:
        reasons.append(
            f"[{ref}] clé(s) d'écriture interdite(s) et vraie(s) : {bad_keys} — STOP_SECURITY")
        return _verdict(STOP_SECURITY, reasons, proposal)

    blob = _content_blob(proposal)
    if _has_secret(blob):
        reasons.append(f"[{ref}] secret détecté dans le contenu — STOP_SECURITY")
        return _verdict(STOP_SECURITY, reasons, proposal)

    low = blob.lower()
    hit = next((m for m in _WRITE_CALL_MARKERS if m in low), None)
    if hit:
        reasons.append(
            f"[{ref}] marqueur d'écriture base de données / API détecté "
            f"({hit!r}) — STOP_SECURITY")
        return _verdict(STOP_SECURITY, reasons, proposal)

    # =================== 2) STRUCTURE — REJECT ===================
    kind = proposal.get("proposed_kind", proposal.get("kind"))
    if kind != PROPOSED_KIND:
        reasons.append(f"[{ref}] proposed_kind doit être 'state', trouvé {kind!r} — REJECT")
        return _verdict(REJECT, reasons, proposal)

    key = proposal.get("proposed_key", proposal.get("key"))
    if (not isinstance(key, str) or ":" in (key or "") or "/" in (key or "")
            or key != KEY_CONVENTION):
        reasons.append(
            f"[{ref}] key invalide (slug '{KEY_CONVENTION}' attendu, sans ':' / '/'), "
            f"trouvé {key!r} — REJECT")
        return _verdict(REJECT, reasons, proposal)

    # Scope CANONIQUE strict (Red-Team #11) : `validate_target_scope` fait un
    # `.strip()` avant le test enum, donc ' outillage/infrastructure' / 'outillage/infrastructure\n' passent
    # alors qu'ils seraient persistés verbatim (scope fantôme aval). On REJETTE
    # tout scope à espaces/contrôle de bordure — le path DB est un slug strict.
    raw_scope = proposal.get("scope")
    if isinstance(raw_scope, str) and raw_scope != raw_scope.strip():
        reasons.append(
            f"[{ref}] scope non-canonique (espace/contrôle en bordure) : "
            f"{raw_scope!r} — REJECT")
        return _verdict(REJECT, reasons, proposal)

    scope_ok, scope_reason = mp.validate_target_scope(raw_scope)
    if not scope_ok:
        reasons.append(f"[{ref}] scope invalide / root-level : {scope_reason} — REJECT")
        return _verdict(REJECT, reasons, proposal)

    # =================== 3) COHÉRENCE — NEEDS_FIX ===================
    needs: list[str] = []

    # 3a) source_count cohérent avec les sources RÉELLES.
    real = _real_sources(proposal)
    declared = proposal.get("source_count")
    if declared is not None and declared != len(real):
        needs.append(
            f"[{ref}] source_count={declared} ≠ {len(real)} sources réelles — NEEDS_FIX")

    # 3b) sensible PAR SCOPE ⇒ human_review_required obligatoire.
    if csv_.is_sensitive_scope(proposal.get("scope")) and not proposal.get(
            "human_review_required"):
        needs.append(
            f"[{ref}] scope sensible (G-RT1) sans human_review_required — NEEDS_FIX")

    # 3c) gardes structurelles du validateur (réutilise la source unique).
    issues = csv_.validate_candidate(proposal)
    # Les violations sécurité/structure ont déjà été traitées en STOP/REJECT ;
    # ce qui reste relève du corrigeable.
    needs.extend(f"{i} — NEEDS_FIX" for i in issues)

    if needs:
        reasons.extend(needs)
        return _verdict(NEEDS_FIX, reasons, proposal, validator_issues=issues)

    # =================== 4) GO_FOR_HUMAN_REVIEW ===================
    reasons.append(
        f"[{ref}] proposition saine — prête pour revue humaine "
        f"(AUCUNE écriture : validation humaine obligatoire, v0.31 PROSPECTIF)")
    return _verdict(GO_FOR_HUMAN_REVIEW, reasons, proposal, validator_issues=[])


def _verdict(verdict: str, reasons: list[str], proposal: dict,
             validator_issues: list[str] | None = None) -> dict:
    assert verdict in VALID_VERDICTS  # garde : jamais GO_FOR_WRITE
    return {
        "verdict": verdict,
        "reasons": reasons,
        "proposal_id": proposal.get("proposal_id"),
        "scope": proposal.get("scope"),
        "human_review_required": bool(proposal.get("human_review_required")),
        "write_allowed": False,            # INVARIANT — l'auditeur n'autorise rien
        "is_human_review_ok": verdict == GO_FOR_HUMAN_REVIEW,
        "validator_issues": validator_issues if validator_issues is not None else None,
    }


def _exit_code(verdict: str) -> int:
    if verdict == GO_FOR_HUMAN_REVIEW:
        return 0
    if verdict == STOP_SECURITY:
        return 2
    return 1  # NEEDS_FIX / REJECT


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Current State Proposal Auditor — v0.30 (proposal-only).")
    parser.add_argument("--proposal", required=True,
                        help="Chemin d'un fichier JSON de proposition.")
    parser.add_argument("--json", action="store_true", help="Sortie JSON.")
    args = parser.parse_args(argv)

    if not os.path.isfile(args.proposal):
        print(f"[proposal-auditor] fichier introuvable : {args.proposal}",
              file=sys.stderr)
        return 2
    proposal = json.loads(open(args.proposal, encoding="utf-8").read())
    if isinstance(proposal, list):
        proposal = proposal[0] if proposal else {}

    result = audit_proposal(proposal)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"=== Proposal Auditor (LECTURE SEULE) — {os.path.basename(args.proposal)} ===")
        print(f"verdict={result['verdict']}  scope={result['scope']}  "
              f"write_allowed={result['write_allowed']}")
        for r in result["reasons"]:
            print("  -", r)
    return _exit_code(result["verdict"])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
