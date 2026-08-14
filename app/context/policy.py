"""policy.py — décision PURE du shadow R3-pur simplifié.

PORT FIDÈLE du pipeline `Rung3Policy.decide` du banc V5
(rung R3 d'un banc de calibration mene hors depot) SANS les organes retires
(plancher de gap stratifié) ni les organes désactivés (kind-modifier no-op
dans la chaîne, scope_boost non exécuté). Fonction pure : aucune E/S, aucun
appel réseau/DB/LLM — le kNN et l'écriture du reçu appartiennent au moteur
shadow (`app/services/context_shadow.py`), pas à cette lib.

Ordre du pipeline (FIXÉ, reproduit identiquement au calibrage du banc —
c'est calibré ainsi, ne pas réordonner) :
  1. Pool candidats fourni par l'appelant en ORDRE kNN dense (distance
     croissante) — le classement prod reste INCHANGÉ en amont.
  2. Boost intra-scope : DÉSACTIVÉ — non exécuté, tracé
     `scope_boost_applied=False` (jamais perdu silencieusement).
  3. Modificateurs bornés fraîcheur -> confiance -> kind (no-op), composés
     dans cet ordre, cap total ±0.20 préservant le signe, RE-TRI stable par
     distance finale (`calibration.BoundedModifiers.apply`).
  4. Bande de confiance déclarée sur le top-1 POST-modificateurs (bande
     BRUTE) — {high<=0.15, medium<=0.23, low<=0.53, none au-delà}.
  5. Profil consommateur : `budget_k = min(profile.budget_k, k)` (le shadow
     respecte le k appelant, jamais plus) ; canari_strict rétrograde toute
     bande != "high" à "none" (abstention franche) — la bande BRUTE reste
     tracée dans `score_components["raw_band_before_profile_override"]`.
  6. Bande "none" -> abstention FRANCHE `no_confident_context` (zéro atome,
     l'abstention est une réponse de 1er rang, receipt-grade).
  7. Arrêt BUDGET-SEUL (plancher de gap RETIRÉ, décision round 3) :
     `kept = modified[:budget_k]`, stop_reason "budget" si le pool couvrait
     le budget, "exhausted" sinon — sémantique identique à
     `stop_by_floor_and_budget` du banc avec le plancher retiré.

Différences assumées vs le banc (documentées, pas des dérives) :
  - pas de `tokens_loaded` : la lib ne voit JAMAIS `value` (zéro texte, même
    doctrine que les reçus) ;
  - pas de `stage` A/B dans les composants : c'était la stratification du
    plancher de gap (retiré) sur les étages du banc, sans objet en prod ;
  - `no_embedding` est géré par le moteur shadow AVANT d'appeler `decide`
    (pas d'embedding -> pas de pool) ; ici seul `corpus_exhausted` (pool
    vide) subsiste.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .calibration import DEFAULT_CONSUMER_PROFILE, ShadowCalibration

#: stop_reason possibles de `decide` (le moteur shadow y ajoute
#: "no_embedding" en amont — cf CHECK de arac.context_receipts).
STOP_REASONS = ("budget", "exhausted", "no_confident_context", "corpus_exhausted")


@dataclass(frozen=True)
class Candidate:
    """Un candidat du pool kNN shadow — ids et signaux receipt-grade
    UNIQUEMENT, jamais de texte (`value`/`key` n'entrent pas dans la lib)."""

    atom_id: str
    distance: float
    scope: str | None = None
    kind: str | None = None
    confidence_score: int | None = None
    confirmed_until: datetime | None = None


@dataclass(frozen=True)
class SelectedItem:
    atom_id: str
    rank: int            # 1-indexé, ordre final post-modificateurs
    distance: float      # distance FINALE post-modificateurs
    band: str            # bande de la distance FINALE de CET item (informatif)


@dataclass
class Decision:
    """Résultat pur de la décision shadow — tout ce qu'il faut pour le reçu,
    rien de plus (zéro texte)."""

    selected: list[SelectedItem]
    stop_reason: str
    band_top1: str                 # bande FINALE (post-override profil)
    raw_band: str                  # bande AVANT override profil
    abstained: bool                # True ssi no_confident_context
    budget_k: int                  # budget effectif = min(profil, k appelant)
    score_components: dict = field(default_factory=dict)
    item_components: list[dict] = field(default_factory=list)  # pool COMPLET post-modificateurs, annoté


def _item_components(modified: list[dict]) -> list[dict]:
    """Composants par item du pool trié post-modificateurs (receipt-grade,
    ids + nombres uniquement)."""
    return [
        {
            "atom_id": r["id"],
            "raw_distance": r["raw_distance"],
            "distance_final": r["distance"],
            "freshness_state": r["freshness_state"],
            "freshness_adjustment": r["freshness_adjustment"],
            "confidence_adjustment": r["confidence_adjustment"],
            "kind_adjustment": r["kind_adjustment"],
            "total_adjustment": r["total_adjustment"],
        }
        for r in modified
    ]


def decide(
    candidates: list[Candidate],
    calibration: ShadowCalibration,
    k: int,
    consumer_profile: str = DEFAULT_CONSUMER_PROFILE,
    now: datetime | None = None,
) -> Decision:
    """Décision R3-pur simplifiée sur un pool kNN dense DÉJÀ classé
    (distance croissante, ordre prod inchangé). PURE et DÉTERMINISTE à
    `now` fixé (`now` injectable pour les tests ; défaut = utcnow, consommé
    uniquement par l'état de fraîcheur).

    `k` est le k du consommateur (RecallRequest.k) : le budget effectif est
    `min(profile.budget_k, k)` — jamais plus que ce que l'appelant demande.
    Un `consumer_profile` inconnu retombe sur le profil par défaut
    (session_interactive), le nom DEMANDÉ restant tracé dans les composants
    (`consumer_profile`) à côté du nom résolu (`consumer_profile_resolved`).
    """
    profile = calibration.consumer_profiles.get(
        consumer_profile, calibration.consumer_profiles[DEFAULT_CONSUMER_PROFILE])
    budget_k = min(profile.budget_k, k)
    if now is None:
        now = datetime.now(timezone.utc)

    if not candidates:
        return Decision(
            selected=[], stop_reason="corpus_exhausted", band_top1="none",
            raw_band="none", abstained=False, budget_k=budget_k,
            score_components={"calibration_version": calibration.version,
                              "consumer_profile": consumer_profile,
                              "consumer_profile_resolved": profile.name},
        )

    pool = [{"id": c.atom_id, "scope": c.scope, "kind": c.kind,
             "confidence_score": c.confidence_score,
             "confirmed_until": c.confirmed_until,
             "distance": float(c.distance)} for c in candidates]

    # (2) boost intra-scope DÉSACTIVÉ — non exécuté, tracé honnêtement.
    # (3) modificateurs bornés fraîcheur -> confiance -> kind (no-op).
    modified = calibration.modifiers.apply(pool, now)

    # (4) bande de confiance déclarée sur le top-1 POST-modificateurs.
    d0 = modified[0]["distance"]
    raw_band = calibration.bands.classify(d0)
    band = raw_band

    components = {
        "top1_distance_raw": modified[0]["raw_distance"],
        "top1_distance_final": d0,
        "calibration_version": calibration.version,
        "scope_boost_applied": False,   # désactivé en R3-pur simplifié
        "kind_modifier_applied": False,  # désactivé (no-op dans la chaîne)
        "freshness_state_top1": modified[0]["freshness_state"],
        "freshness_adjustment_top1": modified[0]["freshness_adjustment"],
        "confidence_adjustment_top1": modified[0]["confidence_adjustment"],
        "kind_adjustment_top1": modified[0]["kind_adjustment"],
        "consumer_profile": consumer_profile,
        "consumer_profile_resolved": profile.name,
        "budget_k": budget_k,
    }
    items = _item_components(modified)

    # (5) profil consommateur — canari strict : abstention franche hors "high".
    if profile.require_high_band and raw_band != "high":
        band = "none"
        components["raw_band_before_profile_override"] = raw_band

    if band == "none":
        # (6) abstention FRANCHE — ZÉRO atome, la bande BRUTE reste tracée
        # (jamais perdue silencieusement) même quand c'est le profil qui a
        # tranché. L'abstention est un fait receipt-grade : le moteur shadow
        # écrit quand même une row de reçu (shadow_ids=[]).
        return Decision(
            selected=[], stop_reason="no_confident_context", band_top1="none",
            raw_band=raw_band, abstained=True, budget_k=budget_k,
            score_components=components, item_components=items,
        )

    # (7) arrêt BUDGET-SEUL (plancher de gap retiré — round 3).
    if len(modified) >= budget_k:
        kept, stop_reason = modified[:budget_k], "budget"
    else:
        kept, stop_reason = modified, "exhausted"

    selected = [
        SelectedItem(atom_id=r["id"], rank=i + 1, distance=r["distance"],
                     band=calibration.bands.classify(r["distance"]))
        for i, r in enumerate(kept)
    ]
    return Decision(
        selected=selected, stop_reason=stop_reason, band_top1=band,
        raw_band=raw_band, abstained=False, budget_k=budget_k,
        score_components=components, item_components=items,
    )
