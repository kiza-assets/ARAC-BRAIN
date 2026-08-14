"""Memory Governance Policy Engine — v0.10 (fonctions PURES, fondation).

Transforme la politique d'écriture mémoire + les gardes du classifier hardening en
logique testable et réutilisable. **Aucune DB, aucune API, aucune écriture,
aucun POST atom.** Source de vérité : les enums réels `app/schemas/kind.py` et
`app/schemas/scope.py` (imports purs, sans effet de bord DB).

Ce module ne décide JAMAIS d'écrire. Il classe une *proposition* d'atome et
retourne un verdict de policy (rejected / human_review_required / proposed).
L'écriture réelle reste hors périmètre (GO auditeur, Phase 5 lock-token).

Usage :
    from memory_policy import classify_candidate_policy
    verdict = classify_candidate_policy({"kind": "lecture", "scope": "outillage",
                                         "key": "x", "text": "..."})
"""
from __future__ import annotations

import os
import re
import tomllib
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import arac_runtime

from app.schemas.kind import Kind  # noqa: E402 — enum pur, aucun import DB
from app.schemas.scope import Scope  # noqa: E402 — enum pur, aucun import DB

# Vérité terrain dérivée des enums (single source of truth).
VALID_KINDS: frozenset[str] = frozenset(k.value for k in Kind)
VALID_SCOPES: frozenset[str] = frozenset(s.value for s in Scope)
BARE_ROOTS: frozenset[str] = frozenset(s.value for s in Scope if "/" not in s.value)
LEAF_SCOPES: frozenset[str] = frozenset(s.value for s in Scope if "/" in s.value)

# ---------------------------------------------------------------------------
# Remap des kinds doctrinaux Constitution V (inexistants) -> kinds réels.
# ---------------------------------------------------------------------------
KIND_REMAP: dict[str, str] = {
    "lecture": "reference",
    "doctrine": "decision",   # règle validée -> decision (rationale obligatoire)
    "record": "state",
    "foundation": "reference",
}

# Kinds exigeant un rationale non vide (miroir RATIONALE_REQUIRED_KINDS).
RATIONALE_REQUIRED: frozenset[str] = frozenset({Kind.DECISION.value})

# Kinds pour lesquels une source/provenance est attendue (savoir externe ou
# décision traçable). Absente -> human_review (jamais un rejet sec : soft guard).
SOURCE_RECOMMENDED_KINDS: frozenset[str] = frozenset(
    {Kind.REFERENCE.value, Kind.DECISION.value})
_SOURCE_FIELDS: tuple[str, ...] = ("source", "source_md", "source_ref",
                                   "source_diamond", "source_atom_ids")

# ---------------------------------------------------------------------------
# Détection de contenu sensible (légal / santé / famille / dette perso).
# Un contenu sensible n'est JAMAIS auto-routé vers une racine business.
# ---------------------------------------------------------------------------
# Marqueurs sensibles — stockés SANS accent (W001 : `_norm` retire les accents,
# donc 'légal'/'medécin'/'MÉDECIN'/forme décomposée matchent tous le marqueur
# accent-free). Couvre légal/judiciaire, santé/médical, finances perso/dettes,
# famille, et catégories spéciales RGPD (origine ethnique/religion — W002).
SENSITIVE_MARKERS: tuple[str, ...] = (
    # légal / judiciaire
    "legal", "avocat", "avocate", "avocats", "judiciaire", "tribunal", "proces",
    "contentieux", "huissier", "plainte", "controle judiciaire", "juridique",
    "juridiction",
    # santé / médical
    "sante", "medical", "medicale", "medecin", "medecine", "medicament",
    "grossesse", "enceinte", "accouchement", "maladie", "hopital", "therapie",
    "therapeute", "therapeutique", "psychologue", "psychiatre",
    # finances perso / dettes
    "dette", "dettes", "decouvert", "saisie", "endettement", "surendettement",
    # famille / personnes
    "famille", "familial", "familiale", "conjoint", "conjointe", "epouse",
    "epoux", "enfant", "enfants",
    # catégories spéciales RGPD : origine ethnique, religion, orientation (W002).
    # NB : 'race' seul n'est PAS ici (collision 'race condition') — cf _RACE_RE.
    "ethnie", "ethnique", "racial", "raciale", "racisme", "raciste",
    "origine ethnique", "appartenance ethnique", "religion", "religieux",
    "religieuse", "orientation sexuelle",
)

# Radicaux sensibles — match par PRÉFIXE de mot (W004 : dérivés morphologiques,
# ex. legal->legalisation/legalite, medec->medecin, therap->therapeute,
# endett->endettement). Choisis pour éviter les collisions courantes (pas de
# 'famil' qui attraperait 'familier'). Erreur tolérée = vers human_review (sûr).
SENSITIVE_STEMS: tuple[str, ...] = (
    "legal", "legalis", "illegal", "juridi", "judiciair",
    "medec", "medic", "therap", "psychi", "psycholog",
    "endett", "surendett", "ethni", "racis", "racial",
)

# W002 : 'race' en sens HUMAIN est sensible (origine ethnique), MAIS jamais le
# 'race' technique ('race condition', 'data race', 'race to default'). On
# n'attrape donc 'race' QUE suivi d'un adjectif humain — les termes techniques
# n'ont jamais cet indice. L'ethnicité explicite (ethnie/racial/racisme/origine
# ethnique) est déjà couverte par SENSITIVE_MARKERS/STEMS.
_RACE_HUMAN_RE: re.Pattern[str] = re.compile(
    r"(?<!\w)races?\s+(?:humaine?s?|blanche?s?|noire?s?|metisse?s?|aryenne?s?)\b")

# Où un contenu sensible a le droit d'atterrir, et où il n'a PAS le droit.
#
# La règle protège contre une faute discrète : un fait de santé ou de famille
# rangé dans un scope professionnel. Il n'est pas perdu — il est pire, il est
# retrouvable par la mauvaise question, dans le mauvais contexte.
#
# Déclarez vos racines si votre taxonomie diffère :
#     ARAC_SENSITIVE_SAFE_ROOTS="perso,famille"
#     ARAC_BUSINESS_ROOTS="travail,societe"
#
# Défaut : `perso` est sûr ; aucune racine n'est déclarée « business », donc la
# garde ne se déclenche pas tant que vous ne l'avez pas armée. On préfère une
# garde silencieuse à une garde qui bloque au hasard sur une taxonomie qu'elle
# ne connaît pas.
def _roots_from_env(var: str, default: frozenset[str]) -> frozenset[str]:
    raw = os.environ.get(var, "")
    declared = frozenset(s.strip() for s in raw.split(",") if s.strip())
    return declared or default


SENSITIVE_SAFE_ROOTS: frozenset[str] = _roots_from_env(
    "ARAC_SENSITIVE_SAFE_ROOTS", frozenset({"perso"}))
BUSINESS_ROOTS: frozenset[str] = _roots_from_env(
    "ARAC_BUSINESS_ROOTS", frozenset())

# ---------------------------------------------------------------------------
# Secrets — jamais dans un atome. Patterns alignés sur le sanitizer Mac/serveur.
# ---------------------------------------------------------------------------
SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-ant-[a-zA-Z0-9_\-]{10,}"),
    re.compile(r"sk-[a-zA-Z0-9]{40,}"),
    re.compile(r"ghp_[a-zA-Z0-9]{20,}"),
    re.compile(r"(AKIA|ASIA)[A-Z0-9]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)bearer\s+[a-zA-Z0-9\-._~+/]{20,}"),
    re.compile(r"(?i)password\s*[=:]\s*\S+"),
    re.compile(r"postgres(?:ql)?://[^@\s]+:[^@\s]+@"),
    re.compile(r"(?i)\btoken\s*[=:]\s*[A-Za-z0-9_\-]{20,}"),
)

# ---------------------------------------------------------------------------
# « Ce contenu mériterait une feuille que vous n'avez pas encore. »
#
# Quand un sujet revient sans avoir de rangement propre, le moteur ne l'invente
# PAS (un scope inventé part en 422 et l'atome est perdu) : il le SIGNALE, et
# vous décidez d'ajouter la feuille ou non.
#
# Le dépôt ne propose aucune correspondance : il ne connaît ni votre métier ni
# vos sujets. Déclarez les vôtres en TOML, une ligne par feuille manquante :
#
#     # config/scope_suggestions.toml
#     [suggestions]
#     "travail/operations" = ["avocat", "judiciaire", "huissier", "contentieux"]
#     "travail/finance"  = ["wallet", "stripe", "sepa"]
# ---------------------------------------------------------------------------


def _load_scope_suggestions() -> tuple[tuple[tuple[str, ...], str], ...]:
    """Lit `config/scope_suggestions.toml`. Absent -> aucune suggestion.

    Zéro suggestion n'est pas une panne : c'est le silence d'un moteur qui ne
    connaît pas encore vos sujets.
    """
    path = Path(
        os.environ.get("ARAC_SCOPE_SUGGESTIONS_CONFIG")
        or arac_runtime.config_dir() / "scope_suggestions.toml"
    )
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ()
    out = []
    for leaf, markers in (raw.get("suggestions") or {}).items():
        if isinstance(markers, (list, tuple)) and markers:
            out.append((tuple(str(m) for m in markers), str(leaf)))
    return tuple(out)


MISSING_SCOPE_SUGGESTIONS: tuple[tuple[tuple[str, ...], str], ...] = (
    _load_scope_suggestions()
)


# ---------------------------------------------------------------------------
# Fonctions pures
# ---------------------------------------------------------------------------
def _strip_accents(text: str) -> str:
    """Décompose (NFKD) et retire les diacritiques combinants. 'médecin',
    'MÉDECIN' et la forme décomposée 'médecin' -> 'medecin'. Neutralise le
    bypass par accents/normalisation Unicode (W001)."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _norm(text: str | None) -> str:
    """Minuscule + sans accents (défense anti-bypass W001)."""
    return _strip_accents((text or "").lower())


def contains_secret(text: str | None) -> bool:
    """True si un secret (clé/token/credential) est détecté dans le texte."""
    t = text or ""
    return any(p.search(t) for p in SECRET_PATTERNS)


# Patterns de RÉDACTION (substitution) — volontairement PLUS LARGES que SECRET_PATTERNS
# (détection calibrée). La détection peut rater une forme (ex. `sk-proj-…` casse sur le
# tiret dans `sk-[A-Za-z0-9]{40,}`) ; la rédaction, elle, doit neutraliser TOUTE forme
# plausible en sortie d'artefact (défense en profondeur — finding Red-Team v0.96 HIGH).
REDACTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),                  # OpenAI/Anthropic (sk-, sk-ant-, sk-proj-)
    re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}"),             # GitHub tokens
    re.compile(r"glpat-[A-Za-z0-9_\-]{6,}"),               # GitLab PAT (cf. modules v0.33+)
    re.compile(r"(?i)xox[baprs]-[A-Za-z0-9\-]{10,}"),      # Slack (xoxb/xoxp/xoxa/xoxr/xoxs)
    re.compile(r"AIza[A-Za-z0-9_\-]{20,}"),                # Google API key
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{4,}"),  # JWT
    re.compile(r"(AKIA|ASIA)[A-Z0-9]{12,}"),               # AWS
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]{16,}"),
    re.compile(r"(?i)\b(?:password|passwd|secret|token|api[_-]?key)\s*[=:]\s*\S+"),
    re.compile(r"postgres(?:ql)?://[^@\s]+:[^@\s]+@"),     # DSN avec credential
    re.compile(r"[A-Za-z0-9+/]{40,}={0,2}"),               # base64 standard long
)
# Limitation connue (Red-Team v0.96 LOW, acceptée) : base64URL (-/_ au lieu de +//) en
# {40,} n'est pas masqué par le dernier pattern — non ajouté pour éviter de sur-redacter
# des identifiants longs légitimes kebab/snake. Les préfixes ci-dessus couvrent le modèle
# de menace réel (clés à préfixe connu) ; le DSN/bearer/token= couvrent les credentials.
_REDACTION_MASK = "[REDACTED]"


def redact_secrets(text):
    """Substitue toute forme de secret/token/DSN par ``[REDACTED]`` (récursif dict/list).

    PUR, additif. À appliquer sur les champs string copiés vers un artefact (findings,
    cartes, dossiers) — la détection `contains_secret` peut rater une forme ; la rédaction
    ne doit RIEN laisser fuir (défense en profondeur)."""
    if isinstance(text, str):
        out = text
        for pat in REDACTION_PATTERNS:
            out = pat.sub(_REDACTION_MASK, out)
        return out
    if isinstance(text, dict):
        return {k: redact_secrets(v) for k, v in text.items()}
    if isinstance(text, (list, tuple)):
        return [redact_secrets(v) for v in text]
    return text


def detect_sensitive(text: str | None) -> str | None:
    """Retourne le premier marqueur sensible présent, ou None.

    Trois couches (toutes sur texte normalisé sans accents — W001) :
      1. marqueurs exacts par frontière de mot (`(?<!\\w)marqueur(?!\\w)`) — évite
         les faux positifs `sante`⊂"composante", `proces`⊂"processus" ;
      2. radicaux par préfixe de mot (W004 : dérivés morphologiques) ;
      3. 'race' en sens humain, hors 'race condition' technique (W002).
    Erre TOUJOURS vers la détection (jamais permissif)."""
    t = _norm(text)
    # 1) marqueurs exacts. Red-Team V0.109 (HIGH) : frontière [a-z] (pas \w) — sinon
    # un suffixe chiffre/underscore contourne un marqueur nom-propre ('prenom123'
    # passait car \w inclut [0-9_]). [a-z] catche les suffixes chiffre/underscore
    # tout en préservant l'anti-substring lettre (sante⊂composante, proces⊂processus).
    for m in SENSITIVE_MARKERS:
        if re.search(r"(?<![a-z])" + re.escape(m) + r"(?![a-z])", t):
            return m
    # 2) radicaux / dérivés morphologiques (W004)
    for stem in SENSITIVE_STEMS:
        if re.search(r"(?<!\w)" + re.escape(stem) + r"\w*", t):
            return stem
    # 3) 'race' en sens humain (race humaine/blanche/...), jamais le 'race'
    #    technique (race condition, data race) — W002.
    if _RACE_HUMAN_RE.search(t):
        return "race humaine"
    return None


def map_kind(old_kind: str | None) -> str | None:
    """Mappe un kind doctrinal (ex. lecture/doctrine) vers un kind réel valide.

    Retourne la valeur de kind valide (∈ enum réel) ou None si non mappable."""
    if not old_kind:
        return None
    k = old_kind.strip().lower()
    k = KIND_REMAP.get(k, k)
    return k if k in VALID_KINDS else None


def validate_kind(kind: str | None) -> bool:
    """True si `kind` (après remap éventuel) est un kind réel valide."""
    return map_kind(kind) is not None


def validate_target_scope(scope: str | None) -> tuple[bool, str]:
    """Valide un scope CIBLE : doit être une feuille déployée (jamais racine nue).

    Retourne (ok, reason)."""
    if not scope:
        return False, "scope vide"
    s = scope.strip()
    # Toute racine nue (déclarée ou non) -> root-level : un atome posé là
    # est écrit, actif, et invisible au rappel.
    if "/" not in s:
        return False, f"racine nue interdite (no root-level) : {s}"
    if s not in VALID_SCOPES:
        return False, f"scope inexistant dans l'enum déployé : {s}"
    return True, "ok"


def suggest_missing_scope(text: str | None) -> str | None:
    """Suggère une feuille dédiée (inexistante) selon le contenu, ou None.

    Comparaison accent-free des deux côtés (W001) : 'légal'/'fidélité' matchent
    même après normalisation du texte."""
    t = _norm(text)
    for markers, leaf in MISSING_SCOPE_SUGGESTIONS:
        if any(_strip_accents(m.lower()) in t for m in markers):
            return leaf
    return None


def validate_source(candidate: dict) -> bool:
    """True si une source/provenance non vide est présente dans le candidat."""
    for f in _SOURCE_FIELDS:
        v = candidate.get(f)
        if isinstance(v, str) and v.strip():
            return True
        if isinstance(v, (list, tuple)) and len(v) > 0:
            return True
    return False


def requires_human_review(candidate: dict) -> bool:
    """True si la proposition exige une revue humaine.

    Déclencheurs : contenu sensible, scope cible invalide/manquant, kind non
    mappable, ou flag explicite `human_review_required` dans le candidat."""
    if candidate.get("human_review_required") is True:
        return True
    text = candidate.get("text") or candidate.get("value") or candidate.get("summary")
    if detect_sensitive(text):
        return True
    if not validate_kind(candidate.get("kind")):
        return True
    ok, _ = validate_target_scope(candidate.get("scope"))
    if not ok:
        return True
    return False


@dataclass
class PolicyVerdict:
    """Verdict de policy pour une proposition d'atome (aucune écriture)."""
    status: str                       # rejected | human_review_required | proposed
    mapped_kind: str | None
    scope: str | None
    human_review_required: bool
    sensitive_marker: str | None = None
    secret_detected: bool = False
    suggested_missing_scope: str | None = None
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "mapped_kind": self.mapped_kind,
            "scope": self.scope,
            "human_review_required": self.human_review_required,
            "sensitive_marker": self.sensitive_marker,
            "secret_detected": self.secret_detected,
            "suggested_missing_scope": self.suggested_missing_scope,
            "reasons": self.reasons,
        }


def classify_candidate_policy(candidate: dict) -> dict:
    """Classe une proposition d'atome et retourne un verdict de policy.

    `candidate` : dict avec au moins `kind`, `scope`, et un texte
    (`text`/`value`/`summary`). NE POSTE RIEN, n'écrit RIEN.

    Statuts :
      - 'rejected'                : secret détecté, kind non mappable, ou scope
                                    racine nue / invalide sans suggestion.
      - 'human_review_required'   : sensible, scope manquant (feuille à créer),
                                    ou flag explicite.
      - 'proposed'                : valide, non sensible — proposable (mais
                                    JAMAIS auto-écrit : validation humaine ensuite).
    """
    text = candidate.get("text") or candidate.get("value") or candidate.get("summary")
    reasons: list[str] = []

    # Secret : scanné sur TOUS les champs texte (pas seulement le contenu) —
    # un secret collé dans rationale/source/key ne doit pas passer (défense profonde).
    secret_blob = " ".join(
        str(candidate.get(f) or "")
        for f in ("text", "value", "summary", "rationale", "source", "key"))
    secret = contains_secret(secret_blob)
    sensitive = detect_sensitive(text)
    mapped = map_kind(candidate.get("kind"))
    scope = candidate.get("scope")
    scope_ok, scope_reason = validate_target_scope(scope)
    missing = suggest_missing_scope(text)

    # 1) Secret -> rejet sec (jamais de secret en mémoire).
    if secret:
        reasons.append("secret détecté — rejet (no-secret)")
        return PolicyVerdict("rejected", mapped, scope, True, sensitive, True,
                             missing, reasons).to_dict()

    # 2) Kind non mappable -> rejet (kind invalide).
    if mapped is None:
        reasons.append(f"kind invalide / non mappable : {candidate.get('kind')!r}")
        return PolicyVerdict("rejected", None, scope, True, sensitive, False,
                             missing, reasons).to_dict()

    # 3) Scope racine nue (déployée ou non) -> rejet (no root-level).
    if scope and "/" not in scope:
        reasons.append(scope_reason)
        return PolicyVerdict("rejected", mapped, scope, True, sensitive, False,
                             missing, reasons).to_dict()

    # 4) Sensible routé vers une racine business -> jamais auto -> human review.
    target_root = (scope or "").split("/")[0]
    if sensitive and target_root in BUSINESS_ROOTS:
        reasons.append(
            f"sensitive_guard : contenu sensible ('{sensitive}') interdit en scope "
            f"business '{target_root}' — human_review_required")
        return PolicyVerdict("human_review_required", mapped, None, True, sensitive,
                             False, missing, reasons).to_dict()

    # 4bis) W003 — reroutage CROSS-WORLD interdit en AUTO. Si le scope cible est
    # valide MAIS le contenu évoque une feuille d'un AUTRE monde (racine
    # différente), on ne reroute JAMAIS automatiquement : on propose la feuille
    # et on exige une revue humaine. Empêche qu'un contenu perso atterrisse en
    # une racine business (ou l'inverse) sans validation.
    if scope_ok and missing and missing.split("/")[0] != target_root:
        reasons.append(
            f"cross-world (W003) : contenu évoque '{missing}' (monde "
            f"'{missing.split('/')[0]}') alors que scope cible '{scope}' (monde "
            f"'{target_root}') — pas de reroute auto, human_review_required")
        return PolicyVerdict("human_review_required", mapped, scope, True,
                             sensitive, False, missing, reasons).to_dict()

    # 5) Scope invalide / inexistant -> si feuille suggérée : review ; sinon review.
    if not scope_ok:
        reasons.append(scope_reason)
        if missing:
            reasons.append(f"feuille dédiée suggérée (à créer) : {missing}")
        return PolicyVerdict("human_review_required", mapped, None, True, sensitive,
                             False, missing, reasons).to_dict()

    # 6) Rationale obligatoire manquant pour decision -> human review.
    if mapped in RATIONALE_REQUIRED and not (candidate.get("rationale") or "").strip():
        reasons.append("kind=decision exige un rationale non vide — human_review")
        return PolicyVerdict("human_review_required", mapped, scope, True, sensitive,
                             False, missing, reasons).to_dict()

    # 6bis) Source/provenance attendue manquante (reference/decision) -> review.
    if mapped in SOURCE_RECOMMENDED_KINDS and not validate_source(candidate):
        reasons.append(
            f"source/provenance manquante pour kind={mapped} — human_review")
        return PolicyVerdict("human_review_required", mapped, scope, True, sensitive,
                             False, missing, reasons).to_dict()

    # 7) Sensible (vers scope sûr) -> proposable mais review obligatoire.
    if sensitive:
        reasons.append(f"contenu sensible ('{sensitive}') — human_review_required")
        return PolicyVerdict("human_review_required", mapped, scope, True, sensitive,
                             False, missing, reasons).to_dict()

    # 8) Flag explicite human_review_required.
    if candidate.get("human_review_required") is True:
        reasons.append("human_review_required demandé explicitement")
        return PolicyVerdict("human_review_required", mapped, scope, True, sensitive,
                             False, missing, reasons).to_dict()

    # 9) Valide, non sensible -> proposable (jamais auto-écrit).
    reasons.append("valide — proposable (validation humaine ensuite, aucun auto-write)")
    return PolicyVerdict("proposed", mapped, scope, False, sensitive, False,
                         missing, reasons).to_dict()
