"""Audit statique d'un diff git proposé par le developer — Phase D.2 MVP.

Aucun appel LLM. Vérifs déterministes :
- Diff non vide
- ≤ MAX_DIFF_LINES lignes
- ≤ MAX_FILES fichiers
- Aucun fichier dans FORBIDDEN_PATHS (data/founding-atoms/, data/aracagent-home/, .env)
- Pas de regex secret dans le diff (clés API, JWT, BEGIN PRIVATE KEY, ...)
- Branche ∈ ALLOWED_BRANCH_PATTERNS (feature/* uniquement, pas main/master)

Retourne un AuditResult avec ok=bool et reasons=list[str].
Cible Phase E : remplacer par auditor LLM cross-provider (Codex/GPT-5.5).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_DIFF_LINES = 200
MAX_FILES = 50

FORBIDDEN_PATHS = (
    "data/founding-atoms/",
    "data/aracagent-home/",
    ".env",
)

ALLOWED_BRANCH_PREFIX = "feature/"
DISALLOWED_BRANCHES = frozenset({"main", "master"})

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("anthropic_api_key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("github_token", re.compile(r"ghp_[A-Za-z0-9]{30,}")),
    ("private_key_header", re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}")),
    ("password_assignment", re.compile(r"""(?i)(?:password|passwd|secret)\s*[=:]\s*["'][^"'\s]{4,}["']""")),
)


@dataclass
class AuditResult:
    ok: bool
    reasons: list[str] = field(default_factory=list)

    def add(self, reason: str) -> None:
        self.reasons.append(reason)
        self.ok = False


def audit(
    *,
    diff_text: str,
    files: list[str],
    branch: str | None,
) -> AuditResult:
    """Audit statique d'un commit_proposal. Renvoie AuditResult(ok, reasons)."""
    result = AuditResult(ok=True)

    # 1. Diff non vide
    if not diff_text.strip() and not files:
        result.add("empty diff")
        return result

    # 2. Branche autorisée
    if not branch:
        result.add("unknown branch")
    elif branch in DISALLOWED_BRANCHES:
        result.add(f"forbidden branch {branch!r}")
    elif not branch.startswith(ALLOWED_BRANCH_PREFIX):
        result.add(f"branch {branch!r} does not start with {ALLOWED_BRANCH_PREFIX!r}")

    # 3. Nombre de fichiers
    if len(files) > MAX_FILES:
        result.add(f"too many files: {len(files)} > {MAX_FILES}")

    # 4. Volume du diff
    diff_lines = diff_text.count("\n")
    if diff_lines > MAX_DIFF_LINES:
        result.add(f"diff too large: {diff_lines} lines > {MAX_DIFF_LINES}")

    # 5. Paths interdits
    for path in files:
        for forbidden in FORBIDDEN_PATHS:
            if path == forbidden.rstrip("/") or path.startswith(forbidden):
                result.add(f"forbidden path: {path}")
                break

    # 6. Secrets dans le diff (regex)
    for label, pattern in _SECRET_PATTERNS:
        m = pattern.search(diff_text)
        if m:
            # On masque la match pour ne pas la propager dans les logs/atomes
            preview = m.group(0)[:6] + "***"
            result.add(f"possible secret leak ({label}): {preview}")

    return result
