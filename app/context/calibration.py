"""calibration.py — organes PURS du shadow R3-pur simplifié +
calibration GELÉE embarquée.

Organes issus d'un banc de calibration mené hors dépôt (rung R3, « sortant
élagué »), portés dans la bibliothèque applicative :
aucune E/S en dehors du chargement UNIQUE du fichier de calibration gelé
(`r3_calibration.json`, copie VERBATIM de la calibration du banc, version
`r3-calib-v1-20260708` — sha256 425dafd4549752b8f34587d7371cbfcb7f1030af18f
bc0873d1cbff70cc784d4, jamais recalculée à l'exécution).

Composition EXACTE de R3-pur simplifié (la source de vérité exécutable est
`r3_calibration.json`, embarqué à côté de ce fichier) :
  - PORTÉS ACTIFS : DistanceBands {high<=0.15, medium<=0.23, abstain_min<=
    0.53}, FreshnessModifier {stale_pen=0.02, unknown!=fresh},
    ConfidenceModifier {low50/high85/pen0.03/boost0.03}, BoundedModifiers
    (cap total ±0.20, ordre fixe fraîcheur -> confiance -> kind),
    ConsumerProfile/CONSUMER_PROFILES (cortex_dedup k=3 / session_interactive
    k=10 / canari_strict k=3+require_high).
  - PORTÉ MAIS DÉSACTIVÉ : KindModifier — présent dans la chaîne (no-op
    honnête quand `enabled=False`, exactement comme au banc), le loader
    FORCE `enabled=False` même si le JSON disait autre chose.
  - RETIRÉ (non porté) : GapFloor / stop_by_floor_and_budget — l'arrêt est
    budget-seul (cf `policy.decide`) ; le champ `gap_floor_by_stage` du JSON
    gelé est IGNORÉ par le loader (conservé dans le fichier pour la
    traçabilité de provenance, jamais lu).
  - DÉSACTIVÉ (non porté, non exécuté) : ScopeBoost — tracé
    `scope_boost_applied=False` dans les composants de décision ; le champ
    `scope_boost` du JSON est IGNORÉ par le loader.
  - EXCLUS : RRF/lexical, épisode.

Mêmes garanties que le banc : dataclasses immuables en usage — `.apply()` /
`.adjust()` ne mutent jamais leur entrée ; les bornes DURES de conception
(FRESHNESS_MAX_PENALTY etc.) sont des plafonds jamais dépassés même par une
calibration aberrante.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# --------------------------------------------------------------------- garde-fous de conception (bornes DURES, jamais dépassées même par un calibrage aberrant)
FRESHNESS_MAX_PENALTY = 0.15
FRESHNESS_MAX_BOOST = 0.15
CONFIDENCE_MAX_ADJUST = 0.10
KIND_MAX_ADJUST = 0.05
TOTAL_MODIFIER_CAP_DESIGN = 0.20  # plafond DESIGN de l'ajustement COMBINÉ des 3 organes

#: Version attendue de la calibration gelée — le loader REFUSE tout autre
#: fichier (anti-dérive : on ne « met pas à jour » une calibration en douce,
#: on en grave une nouvelle avec une nouvelle version).
CALIBRATION_VERSION = "r3-calib-v1-20260708"

_CALIBRATION_PATH = Path(__file__).resolve().parent / "r3_calibration.json"


# --------------------------------------------------------------------- bandes de confiance (port verbatim de bench calibration.DistanceBands)
@dataclass
class DistanceBands:
    """4 bandes déclarées {high,medium,low,none} — calibrées sur CALIB par
    quantiles de la distribution RÉELLE des distances (jamais une constante
    à priori). `abstain_min` est le seuil AU-DELÀ duquel la déclaration
    devient "none" ET la décision abstient franchement — au-delà de
    `medium_max` mais en-deçà de `abstain_min`, la bande "low" répond encore
    (comme prod), elle ne fait qu'avertir d'une confiance faible."""

    high_max: float
    medium_max: float
    abstain_min: float

    def classify(self, d0: float | None) -> str:
        if d0 is None:
            return "none"
        if d0 <= self.high_max:
            return "high"
        if d0 <= self.medium_max:
            return "medium"
        if d0 <= self.abstain_min:
            return "low"
        return "none"


# --------------------------------------------------------------------- fraîcheur (unknown != fresh) — port verbatim de bench calibration_r3
def freshness_state(confirmed_until: datetime | None, now: datetime) -> str:
    """"stale" si `confirmed_until` est dans le passé ; "unknown" si absent
    (JAMAIS "fresh" — l'absence de date factuelle n'est pas une preuve de
    fraîcheur) ; "fresh" seulement si une date de confirmation FUTURE existe
    réellement en base. Note prod : quasi tout le corpus a `confirmed_until
    IS NULL` -> "unknown" -> neutre par construction."""
    if confirmed_until is None:
        return "unknown"
    if confirmed_until < now:
        return "stale"
    return "fresh"


@dataclass
class FreshnessModifier:
    enabled: bool
    stale_penalty: float
    fresh_boost: float

    def adjust(self, distance: float, confirmed_until: datetime | None, now: datetime) -> float:
        if not self.enabled:
            return distance
        state = freshness_state(confirmed_until, now)
        if state == "stale":
            return distance + min(max(self.stale_penalty, 0.0), FRESHNESS_MAX_PENALTY)
        if state == "fresh":
            return max(0.0, distance - min(max(self.fresh_boost, 0.0), FRESHNESS_MAX_BOOST))
        return distance  # "unknown" -> neutre, ni boost ni pénalité (invariant unknown != fresh)


# --------------------------------------------------------------------- confiance (confidence_score 0-100) — port verbatim
@dataclass
class ConfidenceModifier:
    enabled: bool
    low_threshold: int
    high_threshold: int
    low_penalty: float
    high_boost: float

    def adjust(self, distance: float, confidence_score: int | None) -> float:
        if not self.enabled or confidence_score is None:
            return distance  # confiance NULL = inconnue, neutre (même honnêteté que la fraîcheur)
        if confidence_score >= self.high_threshold:
            return max(0.0, distance - min(max(self.high_boost, 0.0), CONFIDENCE_MAX_ADJUST))
        if confidence_score <= self.low_threshold:
            return distance + min(max(self.low_penalty, 0.0), CONFIDENCE_MAX_ADJUST)
        return distance


# --------------------------------------------------------------------- kind — porté mais DÉSACTIVÉ (no-op honnête dans la chaîne, comme au banc)
@dataclass
class KindModifier:
    """BOOST-ONLY par construction (`adjust` ne renvoie jamais une distance
    > l'entrée). DÉSACTIVÉ en R3-pur simplifié (décision round 3 : gain net
    non confirmé au calibrage) — porté pour rester bit-fidèle à la chaîne du
    banc, où il s'exécute en no-op quand `enabled=False`. Le loader force
    `enabled=False` quoi qu'en dise le JSON."""

    enabled: bool
    boosts: dict[str, float] = field(default_factory=dict)
    magnitude_cap: float = KIND_MAX_ADJUST

    def adjust(self, distance: float, kind: str | None) -> float:
        if not self.enabled or kind is None:
            return distance
        boost = max(0.0, min(self.boosts.get(kind, 0.0), self.magnitude_cap))
        return max(0.0, distance - boost)


# --------------------------------------------------------------------- bundle composé (ordre FIXE : fraîcheur -> confiance -> kind) — port verbatim
@dataclass
class BoundedModifiers:
    """Tous les modificateurs sont des AJUSTEMENTS DE DISTANCE bornés —
    PONDÉRATIONS DOUCES, jamais des filtres durs : aucun candidat n'est
    jamais EXCLU par un modificateur, seul son rang peut bouger (l'exclusion
    reste le monopole de la bande de confiance + l'arrêt budget, en aval)."""

    freshness: FreshnessModifier
    confidence: ConfidenceModifier
    kind: KindModifier
    total_cap: float = TOTAL_MODIFIER_CAP_DESIGN

    def apply(self, rows: list[dict], now: datetime) -> list[dict]:
        """`rows` : pool kNN trié par distance croissante — chaque item porte
        au moins {"id","distance"} + les colonnes R3 ("confirmed_until",
        "confidence_score","kind", éventuellement absentes -> traitées comme
        None/inconnues). Retourne une NOUVELLE liste (jamais de mutation),
        re-triée par distance finale (tri STABLE : à distance égale l'ordre
        kNN d'entrée est préservé), chaque row annotée de ses composants
        (raw_distance + 3 ajustements + état de fraîcheur) pour le reçu."""
        if not rows:
            return []
        out = []
        for r in rows:
            raw_d = r["distance"]
            d1 = self.freshness.adjust(raw_d, r.get("confirmed_until"), now)
            fresh_adj = d1 - raw_d
            d2 = self.confidence.adjust(d1, r.get("confidence_score"))
            conf_adj = d2 - d1
            d3 = self.kind.adjust(d2, r.get("kind"))
            kind_adj = d3 - d2
            total_adj = d3 - raw_d
            # plafond DESIGN de l'ajustement COMBINÉ (garde-fou "pondération
            # douce" même si les organes poussent simultanément dans le même
            # sens) — préserve le SIGNE, tronque seulement l'ampleur.
            if total_adj > self.total_cap:
                total_adj = self.total_cap
            elif total_adj < -self.total_cap:
                total_adj = -self.total_cap
            d_final = max(0.0, raw_d + total_adj)
            out.append({
                **r,
                "distance": d_final,
                "raw_distance": raw_d,
                "freshness_state": freshness_state(r.get("confirmed_until"), now),
                "freshness_adjustment": fresh_adj,
                "confidence_adjustment": conf_adj,
                "kind_adjustment": kind_adj,
                "total_adjustment": d_final - raw_d,
            })
        out.sort(key=lambda r: r["distance"])
        return out


# --------------------------------------------------------------------- budget par consommateur (DESIGN, pas calibré) — port verbatim
@dataclass
class ConsumerProfile:
    name: str
    budget_k: int
    require_high_band: bool  # canari strict : abstention franche si la bande != "high"


CONSUMER_PROFILES: dict[str, ConsumerProfile] = {
    # cortex/dédup : lookup ciblé, jamais le pipeline complet — k court.
    "cortex_dedup": ConsumerProfile("cortex_dedup", budget_k=3, require_high_band=False),
    # session interactive : profil PAR DÉFAUT (aligné budget_k=10 = k par
    # défaut de RecallRequest) — tant que rien ne threade de consommateur,
    # c'est lui qui s'applique.
    "session_interactive": ConsumerProfile("session_interactive", budget_k=10, require_high_band=False),
    # canari strict : identifiants exacts, tolérance ~0 — budget court ET
    # exige la bande "high", sinon abstention franche plutôt qu'une réponse
    # à confiance moyenne/faible.
    "canari_strict": ConsumerProfile("canari_strict", budget_k=3, require_high_band=True),
}
DEFAULT_CONSUMER_PROFILE = "session_interactive"


# --------------------------------------------------------------------- bundle gelé — variante ÉLAGUÉE de bench R3Calibration
@dataclass
class ShadowCalibration:
    """Bundle de calibration du shadow R3-pur SIMPLIFIÉ. Diffère du
    `R3Calibration` du banc par les organes retirés/désactivés : PAS de
    `gap_floor_by_stage` (arrêt budget-seul), PAS de `scope_boost` (désactivé,
    jamais exécuté). Le fichier JSON gelé, lui, reste la copie VERBATIM du
    banc (traçabilité) — c'est le LOADER qui élague."""

    bands: DistanceBands
    modifiers: BoundedModifiers
    consumer_profiles: dict[str, ConsumerProfile]
    version: str
    provenance: dict


def load_calibration(path: Path = _CALIBRATION_PATH) -> ShadowCalibration:
    """Charge la calibration GELÉE. IGNORE `gap_floor_by_stage` (organe
    retiré) et `scope_boost` (désactivé) ; FORCE `kind.enabled=False`
    (désactivé — déjà False dans le JSON gelé, forcé par défense en
    profondeur). Refuse toute version != CALIBRATION_VERSION."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if d["version"] != CALIBRATION_VERSION:
        raise ValueError(
            f"calibration inattendue: version={d['version']!r}, "
            f"attendue={CALIBRATION_VERSION!r} — une nouvelle calibration se "
            f"grave avec une nouvelle version, jamais en remplaçant la gelée"
        )
    mods = d["modifiers"]
    return ShadowCalibration(
        bands=DistanceBands(**d["bands"]),
        modifiers=BoundedModifiers(
            freshness=FreshnessModifier(**mods["freshness"]),
            confidence=ConfidenceModifier(**mods["confidence"]),
            kind=KindModifier(**{**mods["kind"], "enabled": False}),  # forcé OFF
            total_cap=mods["total_cap"],
        ),
        consumer_profiles={k: ConsumerProfile(**v) for k, v in d["consumer_profiles"].items()},
        version=d["version"],
        provenance=d["provenance"],
    )


#: Constante versionnée chargée UNE fois à l'import du module (jamais
#: recalculée) — les consommateurs (policy/shadow engine) l'utilisent telle
#: quelle. L'import de CE module reste hors de `app/context/__init__.py` :
#: un fichier gelé corrompu lèverait ici, chez le consommateur shadow
#: (bruyant), jamais au démarrage de l'API.
CALIBRATION: ShadowCalibration = load_calibration()
