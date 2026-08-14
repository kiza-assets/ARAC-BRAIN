"""Tests HERMÉTIQUES de la lib pure `app/context/` (shadow R3-pur).

Aucune DB, aucun réseau, aucun .env : la lib est pure par construction
(policy/calibration/receipts/shadow_scope), `now` est injecté — décisions
100 % déterministes. Le moteur shadow (kNN + INSERT reçu) est testé à part
(test_context_shadow.py).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import fields
from datetime import datetime, timedelta, timezone

import pytest

from app.context.calibration import (
    CALIBRATION,
    CALIBRATION_VERSION,
    BoundedModifiers,
    ConfidenceModifier,
    ConsumerProfile,
    DistanceBands,
    FreshnessModifier,
    KindModifier,
    ShadowCalibration,
    freshness_state,
    load_calibration,
)
from app.context.policy import Candidate, Decision, decide
from app.context.receipts import (
    INSERT_COLUMNS,
    ContextReceipt,
    query_sha256,
)
from app.context.shadow_scope import (
    SCOPE_PREFIX_CLAUSE,
    is_prefix_gain,
    scope_matches,
    scope_prefix_params,
)

NOW = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)
SHA_OK = "a" * 64


def _cands(*distances: float, **overrides) -> list[Candidate]:
    """Candidats neutres (confiance/fraîcheur inconnues) en ordre kNN."""
    return [Candidate(atom_id=f"atom-{i}", distance=d, **overrides)
            for i, d in enumerate(distances)]


def _receipt(**overrides) -> ContextReceipt:
    base = dict(
        consumer="session_interactive", engine_version="ce-shadow-r3pur-v1",
        calibration_version=CALIBRATION_VERSION, query_sha256=SHA_OK,
        k_requested=10, budget_k=10, served_ids=["s1"], shadow_ids=["s1"],
        shadow_distances=[0.1], stop_reason="budget", shadow_latency_ms=1.5,
    )
    base.update(overrides)
    return ContextReceipt(**base)


# ============================================================ calibration gelée
class TestCalibrationGelee:
    def test_version_et_valeurs_gelees(self):
        assert CALIBRATION.version == CALIBRATION_VERSION == "r3-calib-v1-20260708"
        assert (CALIBRATION.bands.high_max, CALIBRATION.bands.medium_max,
                CALIBRATION.bands.abstain_min) == (0.15, 0.23, 0.53)
        f = CALIBRATION.modifiers.freshness
        assert (f.enabled, f.stale_penalty, f.fresh_boost) == (True, 0.02, 0.0)
        c = CALIBRATION.modifiers.confidence
        assert (c.enabled, c.low_threshold, c.high_threshold,
                c.low_penalty, c.high_boost) == (True, 50, 85, 0.03, 0.03)
        assert CALIBRATION.modifiers.kind.enabled is False   # désactivé
        assert CALIBRATION.modifiers.total_cap == 0.2
        assert {n: (p.budget_k, p.require_high_band)
                for n, p in CALIBRATION.consumer_profiles.items()} == {
            "cortex_dedup": (3, False),
            "session_interactive": (10, False),
            "canari_strict": (3, True),
        }

    def test_loader_refuse_version_inattendue(self, tmp_path):
        from app.context import calibration as calib_mod
        src = json.loads(calib_mod._CALIBRATION_PATH.read_text(encoding="utf-8"))
        src["version"] = "r3-calib-v2-fake"
        p = tmp_path / "bad.json"
        p.write_text(json.dumps(src), encoding="utf-8")
        with pytest.raises(ValueError, match="version"):
            load_calibration(p)

    def test_loader_force_kind_off_et_ignore_organes_retires(self, tmp_path):
        from app.context import calibration as calib_mod
        src = json.loads(calib_mod._CALIBRATION_PATH.read_text(encoding="utf-8"))
        src["modifiers"]["kind"]["enabled"] = True  # tentative de réactivation
        p = tmp_path / "kind_on.json"
        p.write_text(json.dumps(src), encoding="utf-8")
        calib = load_calibration(p)
        assert calib.modifiers.kind.enabled is False
        # organes retirés/désactivés : absents du bundle élagué
        assert not hasattr(calib, "gap_floor_by_stage")
        assert not hasattr(calib, "scope_boost")


# ============================================================ bandes aux frontières
class TestBandesFrontieres:
    @pytest.mark.parametrize("d, band", [
        (0.0, "high"), (0.15, "high"),            # borne high INCLUSE
        (0.150001, "medium"), (0.23, "medium"),   # borne medium INCLUSE
        (0.230001, "low"), (0.53, "low"),         # borne abstain INCLUSE en low
        (0.530001, "none"), (1.0, "none"),
        (None, "none"),
    ])
    def test_classify(self, d, band):
        assert CALIBRATION.bands.classify(d) == band

    def test_frontiere_via_decide(self):
        # top-1 EXACTEMENT à 0.53 (candidat neutre) : encore "low", PAS d'abstention.
        dec = decide(_cands(0.53), CALIBRATION, k=10, now=NOW)
        assert dec.band_top1 == "low" and not dec.abstained
        assert [s.atom_id for s in dec.selected] == ["atom-0"]


# ============================================================ abstention franche
class TestAbstention:
    def test_abstention_top1_au_dela_de_053(self):
        dec = decide(_cands(0.531, 0.6, 0.7), CALIBRATION, k=10, now=NOW)
        assert dec.abstained is True
        assert dec.stop_reason == "no_confident_context"
        assert dec.selected == []
        assert dec.band_top1 == "none" and dec.raw_band == "none"
        # l'abstention reste receipt-grade : composants du pool conservés
        assert len(dec.item_components) == 3

    def test_jamais_abstention_si_top1_sous_008_meme_pire_cas(self):
        # pire cas de pénalité avec la calibration GELÉE : stale (+0.02) +
        # confiance basse (+0.03) = +0.05 -> 0.08 devient 0.13 <= 0.15 (high).
        worst = [Candidate("w-0", 0.08, confidence_score=5,
                           confirmed_until=NOW - timedelta(days=30))]
        for profile in ("session_interactive", "cortex_dedup", "canari_strict"):
            dec = decide(worst, CALIBRATION, k=10, consumer_profile=profile, now=NOW)
            assert dec.abstained is False, profile
            assert dec.band_top1 == "high", profile
            assert dec.score_components["top1_distance_final"] == pytest.approx(0.13)

    def test_canari_strict_retrograde_medium_en_abstention(self):
        dec = decide(_cands(0.20), CALIBRATION, k=10,
                     consumer_profile="canari_strict", now=NOW)
        assert dec.abstained is True and dec.stop_reason == "no_confident_context"
        assert dec.band_top1 == "none"
        assert dec.raw_band == "medium"  # bande BRUTE jamais perdue
        assert dec.score_components["raw_band_before_profile_override"] == "medium"

    def test_corpus_vide(self):
        dec = decide([], CALIBRATION, k=10, now=NOW)
        assert dec.stop_reason == "corpus_exhausted"
        assert dec.selected == [] and dec.abstained is False
        assert dec.band_top1 == "none"


# ============================================================ profils & budget
class TestProfilsBudget:
    def test_dedup_top3_ordre_dense(self):
        # preuve profil dedup : candidats NEUTRES -> modificateurs tous nuls
        # -> l'ordre final EST l'ordre dense kNN, coupé au budget k=3.
        dec = decide(_cands(0.05, 0.06, 0.07, 0.08, 0.09), CALIBRATION,
                     k=10, consumer_profile="cortex_dedup", now=NOW)
        assert dec.abstained is False and dec.stop_reason == "budget"
        assert dec.budget_k == 3
        assert [(s.atom_id, s.rank) for s in dec.selected] == [
            ("atom-0", 1), ("atom-1", 2), ("atom-2", 3)]
        assert [s.distance for s in dec.selected] == [0.05, 0.06, 0.07]

    def test_budget_k10_session_interactive(self):
        dec = decide(_cands(*[0.10 + i * 0.001 for i in range(30)]),
                     CALIBRATION, k=10, now=NOW)
        assert len(dec.selected) == 10 and dec.stop_reason == "budget"
        assert dec.budget_k == 10

    def test_budget_respecte_le_k_appelant(self):
        # k appelant < budget profil : le shadow ne sert JAMAIS plus que k.
        dec = decide(_cands(*[0.10 + i * 0.001 for i in range(30)]),
                     CALIBRATION, k=4, now=NOW)
        assert dec.budget_k == 4 and len(dec.selected) == 4
        # k appelant > budget profil : c'est le profil qui borne.
        dec = decide(_cands(*[0.10 + i * 0.001 for i in range(30)]),
                     CALIBRATION, k=100, consumer_profile="cortex_dedup", now=NOW)
        assert dec.budget_k == 3 and len(dec.selected) == 3

    def test_exhausted_si_pool_plus_court_que_budget(self):
        dec = decide(_cands(0.10, 0.11, 0.12), CALIBRATION, k=10, now=NOW)
        assert dec.stop_reason == "exhausted" and len(dec.selected) == 3

    def test_profil_inconnu_retombe_sur_defaut_et_trace(self):
        dec = decide(_cands(0.10), CALIBRATION, k=10,
                     consumer_profile="profil-fantome", now=NOW)
        assert dec.budget_k == 10
        assert dec.score_components["consumer_profile"] == "profil-fantome"
        assert dec.score_components["consumer_profile_resolved"] == "session_interactive"


# ============================================================ modificateurs bornés
class TestModificateurs:
    def test_unknown_neutre_jamais_fresh(self):
        assert freshness_state(None, NOW) == "unknown"
        dec = decide(_cands(0.10), CALIBRATION, k=10, now=NOW)
        it = dec.item_components[0]
        assert it["freshness_state"] == "unknown"
        assert it["freshness_adjustment"] == 0.0
        assert it["total_adjustment"] == 0.0

    def test_stale_penalise_fresh_neutre_calibration_gelee(self):
        stale = decide([Candidate("s", 0.10, confirmed_until=NOW - timedelta(days=1))],
                       CALIBRATION, k=10, now=NOW)
        assert stale.item_components[0]["freshness_adjustment"] == pytest.approx(0.02)
        assert stale.score_components["top1_distance_final"] == pytest.approx(0.12)
        # fresh_boost GELÉ à 0.0 : une date future est neutre (pas de boost).
        fresh = decide([Candidate("f", 0.10, confirmed_until=NOW + timedelta(days=1))],
                       CALIBRATION, k=10, now=NOW)
        assert fresh.item_components[0]["freshness_state"] == "fresh"
        assert fresh.item_components[0]["freshness_adjustment"] == 0.0

    def test_confiance_low50_high85(self):
        low = decide([Candidate("l", 0.10, confidence_score=50)], CALIBRATION, k=10, now=NOW)
        assert low.item_components[0]["confidence_adjustment"] == pytest.approx(0.03)
        high = decide([Candidate("h", 0.10, confidence_score=85)], CALIBRATION, k=10, now=NOW)
        assert high.item_components[0]["confidence_adjustment"] == pytest.approx(-0.03)
        mid = decide([Candidate("m", 0.10, confidence_score=70)], CALIBRATION, k=10, now=NOW)
        assert mid.item_components[0]["confidence_adjustment"] == 0.0
        none = decide([Candidate("n", 0.10)], CALIBRATION, k=10, now=NOW)
        assert none.item_components[0]["confidence_adjustment"] == 0.0  # NULL = neutre

    def test_modificateurs_reordonnent_sans_jamais_exclure(self):
        # A dense-1er mais confiance basse ; B dense-2e mais confiance haute
        # -> B passe devant A ; les DEUX restent servis (pondération douce).
        dec = decide([Candidate("A", 0.10, confidence_score=40),
                      Candidate("B", 0.12, confidence_score=90)],
                     CALIBRATION, k=10, now=NOW)
        assert [s.atom_id for s in dec.selected] == ["B", "A"]
        assert [s.distance for s in dec.selected] == [pytest.approx(0.09), pytest.approx(0.13)]

    def test_cap_total_020_preserve_le_signe(self):
        # calibration synthétique aux bornes DURES par organe (0.15 + 0.10 =
        # 0.25 > cap 0.20) — le cap tronque l'ampleur, jamais le signe.
        mods = BoundedModifiers(
            freshness=FreshnessModifier(enabled=True, stale_penalty=0.15, fresh_boost=0.15),
            confidence=ConfidenceModifier(enabled=True, low_threshold=50,
                                          high_threshold=85, low_penalty=0.10, high_boost=0.10),
            kind=KindModifier(enabled=False),
        )
        calib = ShadowCalibration(
            bands=CALIBRATION.bands, modifiers=mods,
            consumer_profiles=CALIBRATION.consumer_profiles,
            version="test-cap", provenance={})
        pen = decide([Candidate("p", 0.30, confidence_score=10,
                                confirmed_until=NOW - timedelta(days=1))], calib, k=10, now=NOW)
        assert pen.item_components[0]["total_adjustment"] == pytest.approx(0.20)
        assert pen.score_components["top1_distance_final"] == pytest.approx(0.50)
        boost = decide([Candidate("b", 0.30, confidence_score=95,
                                  confirmed_until=NOW + timedelta(days=1))], calib, k=10, now=NOW)
        assert boost.item_components[0]["total_adjustment"] == pytest.approx(-0.20)
        assert boost.score_components["top1_distance_final"] == pytest.approx(0.10)

    def test_bornes_dures_par_organe(self):
        # une calibration aberrante (pénalité 0.5) est tronquée à la borne DURE.
        f = FreshnessModifier(enabled=True, stale_penalty=0.5, fresh_boost=0.5)
        assert f.adjust(0.10, NOW - timedelta(days=1), NOW) == pytest.approx(0.25)  # +0.15 max
        c = ConfidenceModifier(enabled=True, low_threshold=50, high_threshold=85,
                               low_penalty=0.5, high_boost=0.5)
        assert c.adjust(0.30, 10) == pytest.approx(0.40)  # +0.10 max

    def test_scope_boost_et_kind_traces_desactives(self):
        dec = decide(_cands(0.10), CALIBRATION, k=10, now=NOW)
        assert dec.score_components["scope_boost_applied"] is False
        assert dec.score_components["kind_modifier_applied"] is False
        assert dec.item_components[0]["kind_adjustment"] == 0.0


# ============================================================ déterminisme
class TestDeterminisme:
    def test_meme_entree_meme_decision(self):
        cands = [Candidate(f"a-{i}", 0.10 + i * 0.01,
                           confidence_score=90 if i % 2 else 30,
                           confirmed_until=NOW - timedelta(days=i) if i % 3 == 0 else None)
                 for i in range(20)]
        d1 = decide(cands, CALIBRATION, k=10, now=NOW)
        d2 = decide(cands, CALIBRATION, k=10, now=NOW)
        assert d1 == d2  # égalité dataclass profonde (selected, composants, tout)

    def test_tri_stable_a_distance_egale(self):
        # distances FINALES identiques -> l'ordre kNN d'entrée est préservé.
        dec = decide(_cands(0.10, 0.10, 0.10), CALIBRATION, k=10, now=NOW)
        assert [s.atom_id for s in dec.selected] == ["atom-0", "atom-1", "atom-2"]


# ============================================================ reçus (zéro texte)
class TestReceipts:
    def test_recu_valide_et_serialisation(self):
        r = _receipt()
        d = r.to_dict()
        assert tuple(d.keys()) == INSERT_COLUMNS
        assert r.to_params() == tuple(d.values())
        assert d["query_sha256"] == SHA_OK and d["stop_reason"] == "budget"

    def test_zero_texte_par_construction(self):
        champs = {f.name for f in fields(ContextReceipt)}
        for interdit in ("query", "query_text", "value", "key", "text"):
            assert interdit not in champs

    def test_query_sha256_helper(self):
        q = "où est le serveur travail ?"
        assert query_sha256(q) == hashlib.sha256(q.encode("utf-8")).hexdigest()
        assert len(query_sha256(q)) == 64

    @pytest.mark.parametrize("bad", [
        dict(query_sha256="pas-un-sha"),
        dict(query_sha256="A" * 64),                 # majuscules refusées
        dict(stop_reason="floor"),                    # stop_reason du plancher RETIRÉ
        dict(shadow_ids=["x"], shadow_distances=[]),  # désalignés
        dict(k_requested=0),
        dict(k_requested=101),
        dict(budget_k=0),
        dict(final_band="banana"),
        dict(scope_prefix_gain=5),                    # > len(shadow_ids)
        dict(consumer="Alice Exemple"),      # libellé humain (PII) refusé
        dict(consumer="UPPER"),                       # slug lowercase seul
        dict(consumer=""),
    ])
    def test_validation_refuse(self, bad):
        with pytest.raises(ValueError):
            _receipt(**bad)

    def test_abstention_est_un_recu_valide(self):
        r = _receipt(shadow_ids=[], shadow_distances=[],
                     stop_reason="no_confident_context", final_band="none",
                     raw_band="none", scope_prefix_gain=0)
        assert r.to_dict()["shadow_ids"] == []


# ============================================================ fix scope-préfixe
class TestShadowScope:
    @pytest.mark.parametrize("cand, ref, expected", [
        ("travail", "travail", True),
        ("travail/finance", "travail", True),
        ("travail/finance/visuels", "travail", True),
        ("travail", "travail/finance", False),   # un seul sens : candidat SOUS ref
        ("travailx", "travail", False),      # frontière = '/'
        ("outillage", "travail", False),
        (None, "travail", False),
        ("travail", None, False),
        ("", "", False),
    ])
    def test_scope_matches(self, cand, ref, expected):
        assert scope_matches(cand, ref) is expected

    def test_is_prefix_gain(self):
        assert is_prefix_gain("travail/finance", "travail") is True     # atteint GRÂCE au fix
        assert is_prefix_gain("travail", "travail") is False        # égalité stricte : prod l'avait
        assert is_prefix_gain("outillage", "travail") is False
        assert is_prefix_gain(None, "travail") is False
        assert is_prefix_gain("travail/finance", None) is False

    def test_clause_sql_placeholders_et_pourcent_double(self):
        assert SCOPE_PREFIX_CLAUSE.count("%s") == 3
        # le % littéral du LIKE est DOUBLÉ (piège psycopg3, spec §pièges n°4)
        assert "'/%%'" in SCOPE_PREFIX_CLAUSE
        # après résolution client-side psycopg (%% -> %), le serveur voit '/%'
        assert SCOPE_PREFIX_CLAUSE.replace("%s", "NULL").replace("%%", "%").endswith("LIKE NULL || '/%')")
        assert scope_prefix_params("travail") == ("travail", "travail", "travail")
        assert scope_prefix_params(None) == (None, None, None)


# ============================================================ compat package
class TestCompatPackage:
    def test_request_id_var_import_preserve(self):
        # `app/context.py` -> package `app/context/` : l'import public
        # historique DOIT rester intact (main.py, embeddings.py).
        from app.context import request_id_var
        assert request_id_var.get() is None

    def test_init_n_importe_pas_la_lib(self):
        # garde anti-régression : une calibration corrompue ne doit jamais
        # pouvoir faire échouer `import app.context` (démarrage API).
        import pathlib

        import app.context
        src = pathlib.Path(app.context.__file__).read_text(encoding="utf-8")
        for mod in ("calibration", "policy", "receipts", "shadow_scope"):
            assert f"from .{mod}" not in src and f"import {mod}" not in src
