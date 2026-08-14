"""Politique de seuils du curateur — le seuil exigé dépend du kind.

Ce module porte la POLITIQUE Python testable (seuils par kind, blocklist
anti-bruit, ajustement de confidence). Il N'EST PAS le curateur — c'est
le LLM Sonnet 4.5 dans le subprocess qui EXÉCUTE la politique via le
prompt système (cf agents/curator/prompt.py).

Rôle de ce fichier :
  1. Source-of-truth Python des seuils (le prompt les reflète textuellement).
  2. Helpers pour tests unitaires (`test_curator_policy.py` issue I9).
  3. Validation post-hoc côté gate auditor LLM (I9 va l'importer).

Aucune dépendance externe à la BDD ni à l'API ARAC : module pur fonction-
nel, sans I/O, pour rester testable hors-stack.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final


# ---------------------------------------------------------------------------
# Seuils confidence par kind (politique de seuils)
# ---------------------------------------------------------------------------
#
# Trois niveaux + 2 kinds calibrés spécifiquement :
#   STRICT  (0.85) : decision, gotcha, killed
#       → atomes "engageants", erreur = dette doctrinale longue
#   ALERT   (0.80) : alert
#       → bruit acceptable mais false-positive coûteux pour superviseur
#   STANDARD (0.75): pattern, state, todo
#       → atomes structurants pour la mémoire active
#   MOOD    (0.60) : mood
#       → signal subjectif, faux-positif moins grave
#   LARGE   (0.50) : idea, insight, question, reference, note
#       → captation large, rejets ultérieurs par audit_feedback côté usage
#
# Ces seuils sont un point de départ mesuré, pas une loi : ajustez-les
# après deux semaines d'usage réel, à la lumière de ce que le cerveau a
# retenu et de ce qu'il a laissé passer.

THRESHOLDS_BY_KIND: Final[dict[str, float]] = {
    # STRICT
    "decision": 0.85,
    "gotcha": 0.85,
    "killed": 0.85,
    # ALERT (proche STRICT)
    "alert": 0.80,
    # STANDARD
    "pattern": 0.75,
    "state": 0.75,
    "todo": 0.75,
    # MOOD
    "mood": 0.60,
    # LARGE
    "idea": 0.50,
    "insight": 0.50,
    "question": 0.50,
    "reference": 0.50,
    "note": 0.50,
}

# Kinds INTERDITS au curator (réservés agents triade developer/auditor)
FORBIDDEN_KINDS: Final[frozenset[str]] = frozenset(
    {"delivery", "validation", "contradiction", "suggestion", "agent_message"}
)


# ---------------------------------------------------------------------------
# Heuristiques confidence — modificateurs (politique, §« Calcul confidence »)
# ---------------------------------------------------------------------------
#
# Ces deltas SOMMENT (avec clipping [0.0, 1.0]) sur un score de base 0.5.
# Le LLM curator est instruit dans le prompt système d'appliquer ces deltas
# explicitement ; ce module les rend testables.

CONFIDENCE_DELTAS: Final[dict[str, float]] = {
    "explicit_phrasing": +0.30,    # "je décide", "on va faire", "attention", "note ça"
    "repeated_2_turns": +0.15,     # mention répétée par l'utilisateur sur 2 tours
    "context_identifiable": +0.10, # projet/scope identifiable sans ambiguïté
    "coherent_existing": +0.05,    # cohérent avec atomes scope existants (recall)
    "conditional": -0.20,          # "peut-être", "on verra", "si..."
    "question_unanswered": -0.30,  # question sans réponse (sauf kind=question)
    "generated_code": -0.40,       # snippet code (vit dans git, pas ARAC)
    "small_talk": -0.80,           # "ok merci", "parfait", "salut"
}


# ---------------------------------------------------------------------------
# Anti-bruit positif — rejets systématiques (peu importe confidence)
# ---------------------------------------------------------------------------
#
# Patterns à matcher AVANT calcul confidence. Si match → reject + reason.
# Les secrets méritent un kind=alert avec value MASQUÉE (cf prompt §"Anti-bruit").

_SMALL_TALK_WORDS = (
    r"ok|oui|non|merci|parfait|salut|bonjour|hello|hi|bye|"
    r"super|ah|hm|mh|ouais|ouep|nope|yep|cool|génial|wow|d'accord|"
    r"thanks|thx|cheers|nickel|impec|impeccable|top"
)
_RE_SMALL_TALK = re.compile(
    rf"^\s*(?:{_SMALL_TALK_WORDS})"
    rf"(?:[\s,.!?]+(?:{_SMALL_TALK_WORDS}))*"
    r"[\s.!?]*$",
    re.IGNORECASE,
)

_RE_STACK_TRACE = re.compile(
    r"(Traceback \(most recent call last\)|ERROR\s+\d|^\s*at\s+\S+\(.*:\d+:\d+\)$|"
    r"^\s*File \"[^\"]+\", line \d+,)",
    re.MULTILINE,
)

# Patterns secrets connus (alignés sur log_capture.py — 13 patterns)
_SECRET_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"sk-ant-[a-zA-Z0-9_\-]+"),                          # anthropic key
    re.compile(r"sk-[a-zA-Z0-9]{40,}"),                             # openai key
    re.compile(r"ghp_[a-zA-Z0-9]{30,}"),                            # github pat
    re.compile(r"gho_[a-zA-Z0-9]{30,}"),                            # github oauth
    re.compile(r"glpat-[a-zA-Z0-9_\-]+"),                           # gitlab pat
    re.compile(r"xoxb-[a-zA-Z0-9-]+"),                              # slack bot
    re.compile(r"(AKIA|ASIA)[A-Z0-9]{16}"),                         # aws key
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),              # private key
    re.compile(r"eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\."     # jwt
               r"[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(?i)password\s*[=:]\s*\S+"),                       # password=
    re.compile(r"(?i)bearer\s+[a-zA-Z0-9\-._~+/]{20,}"),            # bearer
    re.compile(r"postgres://[^@]+@"),                                # pg dsn
    re.compile(r"\b(?:FR|GB|DE|ES|IT|BE|NL|LU)\d{2}\s?(?:\d{4}\s?){2,7}\d{1,4}\b"),  # IBAN
)

# Code généré (heuristique simple : présence triple-backtick + langage explicite)
_RE_GENERATED_CODE = re.compile(
    r"```(python|sql|js|javascript|typescript|ts|bash|sh|go|rust|java|cpp|c|"
    r"yaml|yml|json|html|css|jsx|tsx|toml|ini|dockerfile)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicyVerdict:
    """Résultat d'évaluation politique sur un atome candidat."""

    accepted: bool
    reason: str  # "ok", "below_threshold", "small_talk", "forbidden_kind",
                 # "stack_trace", "generated_code", "secret_detected",
                 # "unknown_kind"
    threshold: float | None = None  # seuil applicable (None si rejet anti-bruit)


def detect_secret(text: str) -> bool:
    """Retourne True si `text` contient au moins un pattern secret connu."""
    if not isinstance(text, str) or not text:
        return False
    return any(pat.search(text) for pat in _SECRET_PATTERNS)


def is_small_talk(text: str) -> bool:
    """True si `text` est manifestement du small talk court (< 40 chars)."""
    if not isinstance(text, str):
        return False
    stripped = text.strip()
    if len(stripped) > 40:
        return False
    return bool(_RE_SMALL_TALK.match(stripped))


def is_stack_trace(text: str) -> bool:
    """True si `text` contient une stack trace Python/JS."""
    if not isinstance(text, str):
        return False
    return bool(_RE_STACK_TRACE.search(text))


def is_generated_code(text: str) -> bool:
    """True si `text` contient un bloc de code généré (```lang ...)."""
    if not isinstance(text, str):
        return False
    return bool(_RE_GENERATED_CODE.search(text))


def threshold_for(kind: str) -> float | None:
    """Retourne le seuil confidence min pour `kind`. None si kind inconnu/interdit."""
    if kind in FORBIDDEN_KINDS:
        return None
    return THRESHOLDS_BY_KIND.get(kind)


def check_policy(candidate: dict) -> tuple[bool, str]:
    """Évalue un atome candidat selon la politique HYBRID.

    Args:
      candidate : dict avec au moins {kind, value, confidence} (str|float).
                  Confidence peut être un float [0,1] ou un libellé
                  ('curator_strict', 'curator_standard', 'curator_large').

    Returns:
      (accepted, reason).

    Reasons possibles :
      - "ok"
      - "forbidden_kind" (delivery/validation/...)
      - "unknown_kind"
      - "below_threshold"
      - "small_talk"
      - "stack_trace"
      - "generated_code"
      - "secret_in_clear" (secret détecté ET kind != alert ET value non masquée)
    """
    verdict = _check_policy_verdict(candidate)
    return verdict.accepted, verdict.reason


def _check_policy_verdict(candidate: dict) -> PolicyVerdict:
    kind = candidate.get("kind")
    value = candidate.get("value") or ""

    # 1. Kinds interdits — fail-fast
    if kind in FORBIDDEN_KINDS:
        return PolicyVerdict(False, "forbidden_kind", None)

    threshold = threshold_for(kind)
    if threshold is None:
        return PolicyVerdict(False, "unknown_kind", None)

    # 2. Anti-bruit positif (peu importe confidence)
    if is_small_talk(value):
        return PolicyVerdict(False, "small_talk", threshold)
    if is_stack_trace(value):
        return PolicyVerdict(False, "stack_trace", threshold)
    if is_generated_code(value):
        return PolicyVerdict(False, "generated_code", threshold)

    # 3. Secret détecté
    #    Acceptable UNIQUEMENT si kind=alert ET value contient un marqueur
    #    masqué explicite ([REDACTED], "masqué", "***").
    if detect_secret(value):
        if kind != "alert":
            return PolicyVerdict(False, "secret_in_clear", threshold)
        lower = value.lower()
        if "[redacted]" not in lower and "masqué" not in lower and "***" not in value:
            return PolicyVerdict(False, "secret_in_clear", threshold)

    # 4. Seuil confidence
    confidence = candidate.get("confidence")
    score = _confidence_to_float(confidence, kind)
    if score is None or score < threshold:
        return PolicyVerdict(False, "below_threshold", threshold)

    return PolicyVerdict(True, "ok", threshold)


def _confidence_to_float(confidence, kind: str) -> float | None:
    """Convertit une confidence (float ou label) en score [0.0, 1.0].

    Labels reconnus :
      - 'curator_strict' → 0.85
      - 'curator_alert' → 0.80
      - 'curator_standard' → 0.75
      - 'curator_mood' → 0.60
      - 'curator_large' → 0.50
      - 'agent_suggest' → 0.50 (fallback v0.4)
    """
    if confidence is None:
        return None
    if isinstance(confidence, (int, float)):
        v = float(confidence)
        if 0.0 <= v <= 1.0:
            return v
        return None
    if isinstance(confidence, str):
        label_map = {
            "curator_strict": 0.85,
            "curator_alert": 0.80,
            "curator_standard": 0.75,
            "curator_mood": 0.60,
            "curator_large": 0.50,
            "agent_suggest": 0.50,
        }
        return label_map.get(confidence.strip().lower())
    return None


def compute_adjusted_confidence(
    base: float, *, flags: dict[str, bool]
) -> float:
    """Applique les deltas CONFIDENCE_DELTAS sur `base` selon `flags`.

    Args:
      base    : confidence de départ (typiquement 0.5).
      flags   : {nom_du_delta: bool}. Seuls les True sont appliqués.

    Returns:
      Confidence finale clippée dans [0.0, 1.0].
    """
    score = float(base)
    for flag_name, applied in flags.items():
        if not applied:
            continue
        delta = CONFIDENCE_DELTAS.get(flag_name, 0.0)
        score += delta
    return max(0.0, min(1.0, score))
