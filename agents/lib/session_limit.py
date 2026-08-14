"""Détection + parsing du message « limite de session » du CLI Claude.

v0.7 — Auto-pacing du curator. Quand un subprocess `claude -p` épuise
le plafond de l'abonnement Claude (5h glissantes), le CLI n'appelle PAS le LLM :
il émet sur STDOUT un message court et sort en exit_code 1, p.ex. (observé le
2026-05-23 21:09, conv 5643f49a chunk 8/8) :

    You've hit your session limit · resets 12:30am (UTC)

Conséquence avant ce module : le chunk était compté en échec et la conversation
marquée 'failed' (statut honnête), perdant les atomes du dernier segment.
Or l'échec est TRANSITOIRE — il suffit d'attendre le reset (toujours < ~5h).

Ce module est PUR (aucune I/O, aucune dépendance ARAC) pour rester testable :
  - `detect_session_limit(text)`  -> bool   : le stdout est-il un message limite ?
  - `parse_reset_time(text, now)` -> datetime | None : l'instant UTC du reset.

L'orchestration de l'attente (sleep interruptible + retry du chunk) vit dans
agents/curator/main.py (qui tient le sémaphore + le stop_event).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

# Marqueur de la limite de session. Volontairement large (le wording exact du
# CLI peut bouger : « session limit », « usage limit »), mais ancré sur « limit »
# + « reset » pour éviter les faux positifs sur du contenu de conversation.
_LIMIT_MARKER_RE = re.compile(
    r"(?:session|usage)\s+limit",
    re.IGNORECASE,
)

# Heure du reset. Formats couverts :
#   « resets 12:30am (UTC) », « resets 3pm (UTC) », « reset 9 UTC », « resets 00:30 ».
# Groupes : 1=heure, 2=minutes (opt), 3=am|pm (opt), UTC mention (opt).
_RESET_RE = re.compile(
    r"reset[s]?\s+(\d{1,2})(?::(\d{2}))?\s*([ap]m)?\s*(?:\(?\s*UTC\s*\)?)?",
    re.IGNORECASE,
)


def detect_session_limit(text: str | None) -> bool:
    """True si `text` ressemble au message de plafond de session du CLI Claude.

    Requiert le marqueur de limite ET une mention de reset (les deux présents
    dans le message réel), pour ne pas confondre avec un atome/contenu parlant
    de « rate limit » au fil d'une conversation.
    """
    if not text:
        return False
    return bool(_LIMIT_MARKER_RE.search(text)) and bool(_RESET_RE.search(text))


def parse_reset_time(text: str | None, now: datetime) -> datetime | None:
    """Renvoie l'instant UTC du prochain reset annoncé dans `text`, sinon None.

    L'heure annoncée est une horloge murale UTC sans date ; on retourne la
    PROCHAINE occurrence future de cette heure (si déjà passée aujourd'hui,
    c'est demain). `now` est normalisé en UTC.
    """
    if not text:
        return None
    m = _RESET_RE.search(text)
    if not m:
        return None

    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    meridiem = (m.group(3) or "").lower()

    if meridiem == "am":
        hour = 0 if hour == 12 else hour
    elif meridiem == "pm":
        hour = 12 if hour == 12 else hour + 12

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None

    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)

    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


# Signature ROBUSTE d'un fast-fail « limite atteinte » du CLI `claude -p`.
# Plus large que `_LIMIT_MARKER_RE` (qui exige EN PLUS un « resets <heure> ») :
# couvre les wordings SANS le mot « reset » (« try again later/at », « limit
# reached », « too many requests ») qui ont fait ÉCHOUER la détection lors
# d'une cascade observée : exit_code 1, stdout ~100 caractères, la condition
# « marqueur ET heure de reset » n'a pas matché, l'attente jusqu'à la remise à
# zéro du quota ne s'est donc pas engagée, et le curateur a martelé 63 segments
# sur 64 à ~1,5 s d'intervalle -> conversation 'failed', 98 % du contenu perdu.
# On la BORNE par exit_code != 0 ET sortie COURTE pour ne JAMAIS confondre avec
# du contenu de conversation parlant de « rate limit » (qui sort en exit 0 et
# est long).
_USAGE_LIMIT_SIGNATURE_RE = re.compile(
    r"(?:session|usage|rate)\s+limit"
    r"|limit\s+reached"
    r"|reached\s+your\s+(?:usage|session|weekly|daily)?\s*limit"
    r"|too\s+many\s+requests"
    r"|try\s+again\s+(?:later|in|at|after|tomorrow)"
    r"|available\s+again"
    r"|reset[s]?\s+\d",
    re.IGNORECASE,
)

# Au-delà de cette taille, une sortie n'est PAS un bandeau de limite (= contenu
# réel / vraie erreur). Le bandeau CLI réel fait ~100 chars.
_USAGE_LIMIT_MAX_LEN = int(__import__("os").environ.get("ARAC_USAGE_LIMIT_MAX_LEN", "600"))


def is_usage_limit_output(
    exit_code: int,
    stdout: str | None,
    stderr: str | None = None,
    *,
    max_len: int = _USAGE_LIMIT_MAX_LEN,
) -> bool:
    """True si la sortie subprocess ressemble à un fast-fail « limite atteinte ».

    Détection ROBUSTE (cf cascade 2026-06-21) : exit_code != 0 ET sortie COURTE
    (<= max_len) ET présence d'un marqueur de limite élargi. Conçue pour rattraper
    les cas que `detect_session_limit` (qui exige un « resets <heure> » parsable)
    laisse passer. PURE (testable). Combinée à `detect_session_limit` dans le
    pacing du curator : l'un OU l'autre déclenche l'attente.
    """
    if exit_code == 0:
        return False
    text = ((stdout or "") + "\n" + (stderr or "")).strip()
    if not text or len(text) > max_len:
        return False
    return bool(_USAGE_LIMIT_SIGNATURE_RE.search(text))
