"""Sanitize secrets pour l ingest API.

# Copie verbatim de agents/lib/log_capture.py:_SECRET_PATTERNS (frontière
# app↔agents — cf A3 v0.5)
#
# La frontière app/ ↔ agents/ ne tolère pas d import cross-package (D2 §1.8).
# On duplique donc les 13 regex en synchro stricte ici, et un test
# `tests/test_sanitize_sync.py` garantit byte-for-byte l égalité entre les
# deux sources canoniques (drift = CI rouge).

Doctrine ARAC (defense-in-depth zéro-leak) :
- 13 patterns canoniques (anthropic, openai, github PAT/oauth, gitlab, slack,
  aws, private key, JWT, password, bearer, postgres URL, token).
- Idempotent : `mask_secrets(mask_secrets(x)) == mask_secrets(x)`.
- mask_recursive applique sur tous les str d une structure JSON.
"""

from __future__ import annotations

import re
from typing import Any


# Les 13 regex de masquage (cf spec Bloc 9a). Ordre IMPORTANT : les patterns
# les plus spécifiques d abord (sk-ant- avant sk-, AKIA avant generic).
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"sk-ant-[a-zA-Z0-9_\-]+"), "[REDACTED:anthropic-key]"),
    (re.compile(r"sk-[a-zA-Z0-9]{40,}"), "[REDACTED:openai-key]"),
    (re.compile(r"ghp_[a-zA-Z0-9]{30,}"), "[REDACTED:github-pat]"),
    (re.compile(r"gho_[a-zA-Z0-9]{30,}"), "[REDACTED:github-oauth]"),
    (re.compile(r"glpat-[a-zA-Z0-9_\-]+"), "[REDACTED:gitlab-pat]"),
    (re.compile(r"xoxb-[a-zA-Z0-9-]+"), "[REDACTED:slack-bot]"),
    (re.compile(r"(AKIA|ASIA)[A-Z0-9]{16}"), "[REDACTED:aws-key]"),
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
        ),
        "[REDACTED:private-key]",
    ),
    (
        re.compile(
            r"eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}"
        ),
        "[REDACTED:jwt]",
    ),
    (re.compile(r"(?i)password\s*[=:]\s*\S+"), "password=[REDACTED]"),
    (re.compile(r"(?i)bearer\s+[a-zA-Z0-9\-._~+/]{20,}"), "bearer [REDACTED]"),
    (re.compile(r"postgres://[^@]+@"), "postgres://[REDACTED]@"),
    (
        re.compile(r"(?i)token\s*[=:]\s*[A-Za-z0-9_\-]{20,}"),
        "token=[REDACTED]",
    ),
)


def mask_secrets(text: str) -> str:
    """Applique les 13 regex de masquage. Retourne le texte masqué.

    Idempotent : `mask_secrets(mask_secrets(x)) == mask_secrets(x)` car les
    patterns `[REDACTED:*]` ne matchent aucune des regex.
    """
    if not isinstance(text, str) or not text:
        return text
    out = text
    for pat, repl in _SECRET_PATTERNS:
        out = pat.sub(repl, out)
    return out


def mask_recursive(value: Any) -> Any:
    """Applique mask_secrets récursivement sur tous les str d une structure JSON.

    Préserve les clés (les noms de champs ne sont jamais des secrets en
    pratique ; un nom comme `password` reste tel quel, c est sa valeur qu on
    masque).
    """
    if isinstance(value, str):
        return mask_secrets(value)
    if isinstance(value, dict):
        return {k: mask_recursive(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask_recursive(v) for v in value]
    return value


# Noms de catégorie alignés index-à-index sur `_SECRET_PATTERNS` — utilisés
# par `mask_secrets_with_hits` (colonne `ingest_receipts.
# scrub_hits`) : compte PAR CATÉGORIE de ce qui a été masqué, jamais la
# valeur masquée elle-même (cf docstring migration 0021_d063_ingest_receipts
# — cette table ne doit jamais recevoir de contenu brut non scrubé).
_SECRET_CATEGORY_NAMES: tuple[str, ...] = (
    "anthropic-key", "openai-key", "github-pat", "github-oauth", "gitlab-pat",
    "slack-bot", "aws-key", "private-key", "jwt", "password", "bearer",
    "postgres-url", "token",
)


def mask_secrets_with_hits(text: str) -> tuple[str, dict[str, int]]:
    """Comme `mask_secrets`, mais retourne aussi le compte de hits par catégorie.

    N'ajoute ni ne modifie `_SECRET_PATTERNS` ni `mask_secrets` : la synchro
    byte-for-byte avec agents/lib/log_capture.py (tests/test_sanitize_sync.py)
    reste intacte. Utilisé par app/routers/ingest_v2.py pour peupler
    `ingest_receipts.scrub_hits`.
    """
    if not isinstance(text, str) or not text:
        return text, {}
    out = text
    hits: dict[str, int] = {}
    for (pat, repl), category in zip(_SECRET_PATTERNS, _SECRET_CATEGORY_NAMES):
        out, n = pat.subn(repl, out)
        if n:
            hits[category] = hits.get(category, 0) + n
    return out, hits
