"""Garde-fou commit/push de l'agent developer (Phase E.2 — fail-closed).

Avant ce module, `agents/developer/main.py::_commit_and_push` faisait
`git add -A && git commit && git push origin` dès qu'un verdict 'approved'
arrivait — push INCONDITIONNEL, et `git add -A` pouvait stager des fichiers
NON audités (créés après le diff envoyé à l'auditeur). Failles ciblées par la
mission (« push désactivé par défaut ; aucun git add -A ; périmètre invalide
= refus ; audit indisponible = refus »).

Ce module est PUR (aucune I/O hors lecture d'env) pour être unit-testable. Il
encode trois garde-fous, tous FAIL-CLOSED (le doute refuse) :

  1. PUSH OFF par défaut    — ARAC_DEVELOPER_PUSH_ENABLED=false. Le push n'a lieu
                              que si la variable vaut explicitement 'true'.
  2. AUDIT obligatoire      — un audit statique local (commit_audit.audit) doit
                              tourner ET être propre. S'il ne peut pas tourner
                              (exception) -> `audit_unavailable` -> refus.
  3. PÉRIMÈTRE              — chemins TOUJOURS interdits (.env, secrets/, clés) +
                              scope optionnel ARAC_DEVELOPER_ALLOWED_PATHS (si posé,
                              tout fichier hors scope refuse ; liste vide = refus).

Le commit lui-même n'agit JAMAIS via `git add -A` : le caller stage uniquement
les fichiers du diff audité (cf git_ops.add_paths).
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from typing import Mapping

from agents.lib import commit_audit

PUSH_ENABLED_ENV = "ARAC_DEVELOPER_PUSH_ENABLED"
ALLOWED_PATHS_ENV = "ARAC_DEVELOPER_ALLOWED_PATHS"

# Chemins TOUJOURS refusés au developer, même si l'auditeur distant a approuvé.
# Backstop indépendant de commit_audit (défense en profondeur : si l'audit
# distant est down/menteur, on bloque quand même les secrets/données de fondation).
_HARD_FORBIDDEN_PREFIXES = (
    "secrets/",
    "data/founding-atoms/",
    "data/aracagent-home/",
)
_HARD_FORBIDDEN_NAME_GLOBS = ("*.pem", "*.key", "*.p12", "id_rsa", "id_rsa.*", "*.keystore")


def push_enabled(env: Mapping[str, str] = os.environ) -> bool:
    """True UNIQUEMENT si ARAC_DEVELOPER_PUSH_ENABLED == 'true' (insensible casse)."""
    return str(env.get(PUSH_ENABLED_ENV, "false")).strip().lower() == "true"


def configured_allowed_paths(env: Mapping[str, str] = os.environ) -> list[str] | None:
    """Liste de préfixes/globs autorisés depuis ARAC_DEVELOPER_ALLOWED_PATHS (CSV).

    None  = variable absente -> pas de restriction de scope SUPPLÉMENTAIRE (les
            chemins durs interdits restent appliqués).
    []    = variable posée mais vide -> aucun scope accordé -> tout refuse
            (fail-closed explicite).
    """
    if ALLOWED_PATHS_ENV not in env:
        return None
    raw = str(env.get(ALLOWED_PATHS_ENV, "")).strip()
    return [p.strip() for p in raw.split(",") if p.strip()]


def _norm(path: str) -> str:
    # Retire UNIQUEMENT un préfixe './' (pas les caractères '.'/'/' un par un :
    # `.lstrip("./")` transformerait `.env` en `env` — faille critique).
    p = path.strip()
    while p.startswith("./"):
        p = p[2:]
    return p.strip()


def is_forbidden(path: str) -> bool:
    """True si `path` touche un emplacement TOUJOURS interdit (secrets, fondation)."""
    p = _norm(path)
    if not p:
        return False
    name = p.rsplit("/", 1)[-1]
    # .env et .env.* (à n'importe quel niveau)
    if name == ".env" or name.startswith(".env."):
        return True
    for prefix in _HARD_FORBIDDEN_PREFIXES:
        base = prefix.rstrip("/")
        if p == base or p.startswith(base + "/"):
            return True
    for glob in _HARD_FORBIDDEN_NAME_GLOBS:
        if fnmatch.fnmatch(name, glob):
            return True
    return False


def within_scope(path: str, allowed: list[str]) -> bool:
    """True si `path` est sous l'un des préfixes/globs `allowed`."""
    p = _norm(path)
    for a in allowed:
        a = _norm(a)
        if a in ("", "."):
            return True  # racine du repo = tout
        base = a.rstrip("/")
        if p == base or p.startswith(base + "/"):
            return True
        if fnmatch.fnmatch(p, a):
            return True
    return False


@dataclass
class GuardDecision:
    allow_commit: bool
    allow_push: bool
    refusals: list[str] = field(default_factory=list)


def evaluate_commit_guard(
    *,
    verdict: str | None,
    audit_result: "commit_audit.AuditResult | None",
    changed_files: list[str],
    allowed_paths: list[str] | None,
    push_flag: bool,
) -> GuardDecision:
    """Décision fail-closed. allow_commit=True UNIQUEMENT si zéro refus.
    allow_push=True UNIQUEMENT si allow_commit ET push_flag.
    """
    refusals: list[str] = []

    if verdict != "approved":
        refusals.append(f"verdict_not_approved:{verdict}")

    # Audit obligatoire (indisponible OU non-propre -> refus).
    if audit_result is None:
        refusals.append("audit_unavailable")
    elif not audit_result.ok:
        for r in audit_result.reasons:
            refusals.append(f"audit_failed:{r}")

    # Chemins durs interdits (toujours).
    for f in changed_files:
        if is_forbidden(f):
            refusals.append(f"forbidden_path:{f}")

    # Scope optionnel.
    if allowed_paths is not None:
        if len(allowed_paths) == 0:
            refusals.append("scope_empty_fail_closed")
        else:
            for f in changed_files:
                if not within_scope(f, allowed_paths):
                    refusals.append(f"scope_violation:{f}")

    allow_commit = len(refusals) == 0
    allow_push = allow_commit and push_flag
    return GuardDecision(allow_commit=allow_commit, allow_push=allow_push, refusals=refusals)


def run_local_audit(diff_text: str, files: list[str], branch: str | None):
    """Lance l'audit statique local. Retourne None si l'audit ne peut PAS tourner
    (-> le guard traite None comme `audit_unavailable` = refus, fail-closed)."""
    try:
        return commit_audit.audit(diff_text=diff_text, files=files, branch=branch)
    except Exception:  # noqa: BLE001 — audit indisponible = refus, jamais un commit aveugle
        return None
