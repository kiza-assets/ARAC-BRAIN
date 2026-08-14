"""Quota / Token Guard — v0.24 (PUR, lecture seule). Claude Code CLI only.

Détecte l'épuisement de quota / limite de session et calcule un BACKOFF respectueux.
**Ne contourne JAMAIS les limites, ne spamme JAMAIS Claude.** Aucun réseau, aucun
subprocess. Le marathon utilise ce module pour s'arrêter proprement (checkpoint +
closeout partiel) plutôt que de marteler l'API.

Politique : backoff MINIMUM 15 minutes, croissant, plafonné ; nombre de retries
borné ; jamais de boucle toutes les 5 minutes.
"""
from __future__ import annotations

import re

# Détection d'épuisement de quota / limite (transitoire mais à respecter).
_QUOTA_PATTERNS = (
    re.compile(r"quota\s+(exhausted|exceeded|reached)", re.I),
    re.compile(r"usage\s+limit", re.I),
    re.compile(r"session\s+limit", re.I),
    re.compile(r"rate\s*limit", re.I),
    re.compile(r"too\s+many\s+requests", re.I),
    re.compile(r"\b429\b"),
    re.compile(r"\boverloaded\b", re.I),
    re.compile(r"limit\s+(reached|exceeded)", re.I),
    re.compile(r"resets?\s+(at|in)\b", re.I),
)
# Erreurs transitoires réseau (réessayables avec backoff plus court côté futur).
_TRANSIENT_PATTERNS = (
    re.compile(r"\b50[234]\b"),
    re.compile(r"timed?\s*out|timeout", re.I),
    re.compile(r"temporarily\s+unavailable", re.I),
    re.compile(r"connection\s+reset|ECONNRESET", re.I),
)

MIN_BACKOFF_SEC = 15 * 60          # plancher dur : 15 minutes (jamais moins)
MAX_BACKOFF_SEC = 30 * 60          # plafond : 30 minutes
MAX_RETRIES_DEFAULT = 3            # nombre de tentatives borné


def detect_quota_exhausted(text: str | None) -> bool:
    """True si `text` indique un épuisement de quota / limite de session/rate."""
    t = text or ""
    return any(rx.search(t) for rx in _QUOTA_PATTERNS)


def classify_error(text: str | None) -> str:
    """Classe une erreur : 'quota' | 'transient' | 'hard' | 'none'."""
    t = (text or "").strip()
    if not t:
        return "none"
    if detect_quota_exhausted(t):
        return "quota"
    if any(rx.search(t) for rx in _TRANSIENT_PATTERNS):
        return "transient"
    return "hard"


def compute_backoff(attempt: int, *, min_sec: int = MIN_BACKOFF_SEC,
                    max_sec: int = MAX_BACKOFF_SEC) -> int:
    """Backoff croissant pour la tentative `attempt` (1-based), en secondes.

    Toujours >= `min_sec` (15 min), croissant (×2 par tentative), plafonné à
    `max_sec`. Déterministe (aucun jitter aléatoire — env sans random)."""
    a = max(1, int(attempt))
    backoff = min_sec * (2 ** (a - 1))
    return min(max(backoff, min_sec), max_sec)


def should_retry(attempt: int, *, max_retries: int = MAX_RETRIES_DEFAULT) -> bool:
    """True s'il reste des tentatives (attempt 1-based <= max_retries)."""
    return int(attempt) <= int(max_retries)


def quota_decision(text: str | None, attempt: int, *,
                   max_retries: int = MAX_RETRIES_DEFAULT,
                   wait_for_quota: bool = False) -> dict:
    """Décision structurée face à une sortie d'erreur.

    Sans `wait_for_quota` (défaut) : on s'ARRÊTE proprement (checkpoint) même sur
    quota — pas d'attente automatique. Avec `wait_for_quota` : on indique un backoff
    borné, et on stoppe après `max_retries`."""
    kind = classify_error(text)
    if kind == "none":
        return {"kind": "none", "action": "continue", "backoff_sec": 0,
                "should_retry": False}
    if kind == "hard":
        return {"kind": "hard", "action": "stop", "backoff_sec": 0,
                "should_retry": False,
                "reason": "erreur dure non transitoire — arrêt, pas de retry"}
    # quota / transient
    retry = wait_for_quota and should_retry(attempt, max_retries=max_retries)
    return {
        "kind": kind,
        "action": "backoff_wait" if retry else "checkpoint_stop",
        "backoff_sec": compute_backoff(attempt) if retry else 0,
        "should_retry": retry,
        "reason": ("quota/limite atteinte ; checkpoint + arrêt propre "
                   "(reprise via --resume)") if not retry else
                  (f"quota/limite ; backoff borné, tentative {attempt}/{max_retries}"),
    }
