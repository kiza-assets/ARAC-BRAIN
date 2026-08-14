"""Validateur strict des candidats `state:current` — v0.17 (PUR, lecture seule).

Valide un candidat `state:current` (tel que produit par
`current_state_reconciler.py`, ou une proposition d'atome `kind=state`) contre la
vérité terrain des enums réels (via `memory_policy`) et la doctrine v0.16
(plan v0.16 et suite). **Aucune DB, aucune API,
aucune écriture, aucun POST atom.** Le validateur ne décide jamais d'écrire ; il
retourne une liste de problèmes (vide = candidat conforme).

Garde-fous appliqués :
  - kind == "state" (le kind existe déjà ; aucun nouveau kind) ;
  - key == convention `current` ET conforme à la regex DB `_KEY_PATTERN`
    (slug ; un préfixe scope avec ':' ou '/' est refusé) ;
  - scope = feuille canonique déployée (jamais une racine nue) ;
  - source_atom_ids présents, OU un `no_source_reason` explicite si absents
    (un snapshot ne dit que ce que ses sources soutiennent) ;
  - anti-auto-citation : aucune source `kind=state` (G-RT5 v0.16) ;
  - summary non vide ;
  - confidence bornée (score 0..100 ; level ∈ enum Confidence réel) ;
  - garde sensible PAR SCOPE (G-RT1 v0.16) : feuille `perso/*` (et les 4 feuilles
    sensibles nommées) ⇒ human_review_required obligatoire, indépendamment du
    contenu textuel ; détection par contenu (`detect_sensitive`) en filet
    secondaire ;
  - no-secret : aucun secret évident dans summary / champs texte ;
  - invariants dry-run v0.17 : write_allowed == False, would_force == False,
    proposed_status != "active".

Usage :
    python -m app.brain.current_state_validator [chemin.json] [--json]
    -> exit 0 si tout conforme, 1 sinon. Le JSON peut être un candidat unique
       ou une liste de candidats (sortie de current_state_reconciler --json).
"""
from __future__ import annotations

import json
import os
import re
import sys

import arac_runtime

from app.brain import memory_policy as mp  # noqa: E402 — module pur, aucune DB
from app.services.sanitize import mask_secrets  # noqa: E402 — 13 patterns canoniques

# Convention de key v0.16 (DOMAIN-MODEL §2) : un `state:current` est un atome
# kind=state porté par la key stable `current` sur une feuille de scope. Le
# DB key pattern (`app/schemas/atom.py:_KEY_PATTERN`) interdit ':' et '/', donc
# la notation conceptuelle "<scope>:state:current" N'EST PAS une key DB valide :
# la key canonique est le slug `current`, le scope porte le domaine.
KEY_CONVENTION = "current"
PROPOSED_KIND = "state"

# Miroir applicatif de _KEY_PATTERN (app/schemas/atom.py) — slug strict.
_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
_KEY_MAX_LENGTH = 128

# Niveaux de confidence réels (app/schemas/atom.py:Confidence).
VALID_CONFIDENCE_LEVELS = frozenset(
    {"producer", "auditor_validated", "agent_suggest"})

# Garde sensible PAR SCOPE — indépendant du contenu.
#
# Le monde `perso` est sensible EN ENTIER, par fail-safe : décider feuille par
# feuille ce qui relève de la vie privée, c'est se tromper une fois de trop.
# Un état de domaine perso mérite une relecture humaine intégrale.
#
# Vous pouvez déclarer des scopes sensibles supplémentaires (hors `perso`) :
#
#     ARAC_SENSITIVE_SCOPES="travail/operations,travail/sante-collaborateurs"
#
# La sensibilité PAR SCOPE est une garde grossière et volontairement bête. La
# graduation fine (low/medium/high) vit dans `sensitivity_policy.py`.
_SENSITIVE_ROOT_PREFIX = "perso/"

HARD_SENSITIVE_SCOPES = frozenset(
    s.strip() for s in os.environ.get("ARAC_SENSITIVE_SCOPES", "").split(",")
    if s.strip()
)

# Garde-fou anti contenu-privé-long dans un rapport doc-only.
_MAX_SUMMARY_LEN = 2000


def is_sensitive_scope(scope: str | None) -> bool:
    """True si le scope cible relève du sensible PAR SCOPE (pas par contenu).

    Couvre les 4 feuilles sensibles nommées + tout `perso/*` (fail-safe : le
    monde perso est privé). Indépendant du texte (corrige le trou v0.16 :
    `detect_sensitive` est scope-blind)."""
    if not scope:
        return False
    # fail-closed sur la casse : 'PERSO/sante' ne doit pas contourner la garde
    # (les paths DB sont lowercase, mais une fixture non canonique pourrait ruser).
    s = scope.strip().lower()
    return s in HARD_SENSITIVE_SCOPES or s.startswith(_SENSITIVE_ROOT_PREFIX)


def _as_text(value) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False)


def validate_candidate(cand: dict) -> list[str]:
    """Retourne la liste des problèmes d'un candidat `state:current` (vide = OK)."""
    issues: list[str] = []
    scope = cand.get("scope")
    ref = scope or "?"

    # 1) kind == state (pas un nouveau kind).
    kind = cand.get("proposed_kind", cand.get("kind"))
    if kind != PROPOSED_KIND:
        issues.append(f"[{ref}] proposed_kind doit être 'state', trouvé {kind!r}")

    # 2) key == convention `current` + slug DB valide (jamais ':' / '/').
    key = cand.get("proposed_key", cand.get("key"))
    if not isinstance(key, str) or (":" in (key or "")) or ("/" in (key or "")):
        issues.append(
            f"[{ref}] key doit être un slug sans préfixe scope (':' / '/'), "
            f"trouvé {key!r}")
    elif not _KEY_RE.match(key) or len(key) > _KEY_MAX_LENGTH:
        issues.append(f"[{ref}] key viole le pattern DB `_KEY_PATTERN` : {key!r}")
    elif key != KEY_CONVENTION:
        issues.append(
            f"[{ref}] key doit suivre la convention '{KEY_CONVENTION}', "
            f"trouvé {key!r}")

    # 3) scope = feuille canonique déployée (jamais racine nue).
    ok, why = mp.validate_target_scope(scope)
    if not ok:
        issues.append(f"[{ref}] scope cible invalide : {why}")

    # 4) summary non vide.
    summary = cand.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        issues.append(f"[{ref}] summary vide ou absent")
    elif len(summary) > _MAX_SUMMARY_LEN:
        issues.append(
            f"[{ref}] summary trop long ({len(summary)} > {_MAX_SUMMARY_LEN}) "
            f"— risque de contenu privé long")

    # 5) source_atom_ids RÉELS présents OU no_source_reason explicite.
    # On compte les ids réels (str non vide) : un placeholder falsy ([None], [''],
    # [0]) ne « fait » pas une source (red-team v0.17 — bypass anti-fabulation).
    raw_sources = cand.get("source_atom_ids")
    raw_sources = raw_sources if isinstance(raw_sources, list) else []
    real_sources = [s for s in raw_sources if isinstance(s, str) and s.strip()]
    no_source_reason = (cand.get("no_source_reason") or "").strip()
    if not real_sources and not no_source_reason:
        issues.append(
            f"[{ref}] source_atom_ids vide/placeholder sans `no_source_reason` — un "
            f"snapshot ne dit que ce que ses sources soutiennent (anti-fabulation)")
    if not real_sources and not bool(cand.get("human_review_required")):
        issues.append(
            f"[{ref}] snapshot sans source réelle ⇒ human_review_required obligatoire")

    # 6) anti-auto-citation (G-RT5) : aucune source kind=state.
    state_sources = cand.get("source_state_ids")
    if isinstance(state_sources, list) and state_sources:
        issues.append(
            f"[{ref}] auto-citation interdite : source_atom_ids ne doit JAMAIS "
            f"contenir un id kind=state (G-RT5) — {len(state_sources)} détecté(s)")
    if cand.get("anti_auto_citation_ok") is False:
        issues.append(f"[{ref}] anti_auto_citation_ok=False — auto-citation détectée")

    # 7) confidence bornée.
    level = cand.get("confidence_level", cand.get("confidence"))
    if level is not None and level not in VALID_CONFIDENCE_LEVELS:
        issues.append(
            f"[{ref}] confidence_level hors enum réel {sorted(VALID_CONFIDENCE_LEVELS)} : "
            f"{level!r}")
    score = cand.get("confidence_score")
    if score is not None and (not isinstance(score, int) or not (0 <= score <= 100)):
        issues.append(f"[{ref}] confidence_score doit être un int 0..100, trouvé {score!r}")

    # 8) garde sensible PAR SCOPE (G-RT1) + par contenu (filet secondaire).
    hrr = bool(cand.get("human_review_required"))
    content_sensitive = mp.detect_sensitive(summary)
    if is_sensitive_scope(scope) and not hrr:
        issues.append(
            f"[{ref}] scope sensible (PAR SCOPE, G-RT1) ⇒ human_review_required "
            f"obligatoire, indépendamment du contenu")
    if content_sensitive and not hrr:
        issues.append(
            f"[{ref}] contenu sensible détecté ('{content_sensitive}') ⇒ "
            f"human_review_required attendu")

    # 9) no-secret (summary + tous les champs texte agrégés).
    blob = " ".join(
        _as_text(cand.get(f)) for f in
        ("summary", "active_decisions", "blockers", "next_actions", "risks",
         "stale_items", "write_blocked_reason", "no_source_reason"))
    # `mask_secrets` (13 patterns canoniques) est un SUR-ensemble de
    # mp.contains_secret (9) : si le masquage change le blob, un secret est présent
    # (couvre glpat-/xoxb-/gho_/jwt/token génériques que mp seul raterait).
    if mp.contains_secret(blob) or mask_secrets(blob) != blob:
        issues.append(f"[{ref}] secret détecté dans le candidat — rejet (no-secret)")

    # 10) invariants dry-run v0.17 (jamais d'écriture/force/active).
    if cand.get("write_allowed") is not False:
        issues.append(
            f"[{ref}] write_allowed doit être False (v0.17 dry-run ; POST = L5 humain), "
            f"trouvé {cand.get('write_allowed')!r}")
    if cand.get("would_force") not in (False, None):
        issues.append(
            f"[{ref}] would_force doit être False (force=True PROSPECTIF, non implémenté), "
            f"trouvé {cand.get('would_force')!r}")
    if cand.get("proposed_status") == "active":
        issues.append(
            f"[{ref}] proposed_status ne doit jamais être 'active' en dry-run "
            f"(un snapshot actif réel exige un POST humain L5)")

    return issues


def validate_many(candidates: list[dict]) -> dict:
    """Valide une liste de candidats. Retourne un rapport (aucune écriture)."""
    per_item: dict[str, list[str]] = {}
    for idx, c in enumerate(candidates):
        ref = c.get("scope", f"idx{idx}")
        per_item[ref] = validate_candidate(c)
    all_issues = [m for issues in per_item.values() for m in issues]
    return {
        "total": len(candidates),
        "ok": sum(1 for v in per_item.values() if not v),
        "with_issues": sum(1 for v in per_item.values() if v),
        "issues": all_issues,
        "per_item": per_item,
        "safe": not all_issues,
    }


def _load_candidates(path: str) -> list[dict]:
    """Charge un candidat unique ou une liste depuis un fichier JSON.

    Accepte : un objet candidat, une liste de candidats, ou un objet
    {"candidates": [...]} (sortie de current_state_reconciler --json)."""
    data = json.loads(open(path, encoding="utf-8").read())
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("candidates"), list):
        return data["candidates"]
    return [data]


def main(argv: list[str]) -> int:
    json_mode = "--json" in argv
    path = next((a for a in argv if a.endswith(".json")), None)
    if not path or not os.path.isfile(path):
        print(f"[current-state-validator] fichier JSON introuvable : {path}",
              file=sys.stderr)
        return 2
    candidates = _load_candidates(path)
    report = validate_many(candidates)
    if json_mode:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"=== Current State Validator (LECTURE SEULE) — {os.path.basename(path)} ===")
        print(f"candidats={report['total']} ok={report['ok']} "
              f"with_issues={report['with_issues']}")
        for msg in report["issues"]:
            print("  ISSUE:", msg)
        print("SAFE" if report["safe"] else "NOT SAFE")
    return 0 if report["safe"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
