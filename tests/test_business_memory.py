"""Cerveau métier — 11 cas obligatoires (Phase F), PURS (aucune DB).

Mapping aux exigences mission :
  1 décision A active ; 2 B remplace A ; 3 recherche normale -> B ; 4 recherche
  historique -> A+B + relations ; 5 contradiction détectée ; 6 source absente
  rejetée ; 7 doublon détecté ; 8 mémoire obsolète signalée ; 9 source tronquée
  bloquée ; 10 reconstruction projet (fixtures synthétiques, pas de vraie donnée
  MYGUESTBOX) ; 11 réponse 'incertain' si preuves insuffisantes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services import business_memory as bm

_NOW = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)


def _atom(id, kind="decision", scope="myguestbox", key="db-choice", value="v",
          status="active", source=True, **kw):
    src = {"source_path": f"conv/{id}.json", "type": "conversation",
           "date": "2026-06-01T10:00:00Z"} if source else None
    base = dict(id=id, kind=kind, scope=scope, key=key, value=value, status=status,
                source_ref=src, node_id="arac-curator", confidence_score=80)
    base.update(kw)
    return bm.BrainAtom(**base)


# 1. décision A active
def test_1_decision_a_active():
    a = _atom("A", value="Postgres 16")
    assert a.status == bm.BrainStatus.ACTIVE.value
    assert bm.can_be_active(a)


# 2. décision B remplace A
def test_2_b_supersedes_a():
    a = _atom("A", value="Postgres 16")
    b = _atom("B", value="Postgres 17")
    plan = bm.supersession_plan(b, a)
    assert plan.old_id == "A" and plan.new_id == "B"
    assert plan.old_new_status == "superseded"
    assert plan.old_superseded_by == "B"
    assert plan.new_supersedes == "A"
    assert plan.new_status == "active"


def _apply_supersession(a, b):
    """Applique le plan en renvoyant des copies (A superseded, B active liée)."""
    plan = bm.supersession_plan(b, a)
    a.status = plan.old_new_status
    a.superseded_by = plan.old_superseded_by
    b.supersedes = plan.new_supersedes
    return a, b


# 3. recherche normale retourne B (pas A)
def test_3_normal_search_returns_b_only():
    a, b = _apply_supersession(_atom("A", value="PG16"), _atom("B", value="PG17"))
    res = bm.search([a, b], scope="myguestbox", key="db-choice")
    ids = {x.id for x in res}
    assert ids == {"B"}                      # A superseded -> exclu


# 4. recherche historique retourne A + B avec relations
def test_4_historical_search_returns_both_with_relations():
    a, b = _apply_supersession(_atom("A", value="PG16"), _atom("B", value="PG17"))
    res = bm.search([a, b], scope="myguestbox", key="db-choice", historical=True)
    by_id = {x.id: x for x in res}
    assert set(by_id) == {"A", "B"}
    assert by_id["A"].superseded_by == "B"   # relation visible
    assert by_id["B"].supersedes == "A"


# 5. contradiction détectée
def test_5_contradiction_detected():
    a = _atom("A", value="On part sur Stripe")
    b = _atom("B", value="On part sur PayPal")   # même scope+key, valeurs differentes
    assert bm.detect_contradiction(a, b) is True
    assert bm.find_contradictions([a, b]) == [("A", "B")]


def test_5b_no_contradiction_if_one_superseded():
    a, b = _apply_supersession(_atom("A", value="Stripe"), _atom("B", value="PayPal"))
    assert bm.detect_contradiction(a, b) is False   # A superseded -> pas une contradiction


# 6. source absente rejetée
def test_6_missing_source_rejected_for_active():
    a = _atom("A", source=False)
    reasons = bm.validate_for_active(a)
    assert "missing_source" in reasons
    assert not bm.can_be_active(a)


# 7. doublon détecté
def test_7_duplicate_detected_by_key_and_by_hash():
    existing = [_atom("A", value="Postgres 16 nu")]
    # même (scope,kind,key) -> doublon par dedupe_key
    dup_key = _atom("B", value="texte different")
    assert bm.find_duplicate(dup_key, existing) is not None
    # même value normalisée mais key differente -> doublon par semantic_hash
    dup_hash = _atom("C", key="other-key", value="postgres 16   nu")
    assert bm.find_duplicate(dup_hash, existing) is not None
    # ni l'un ni l'autre
    fresh = _atom("D", key="unrelated", value="quelque chose de tout a fait autre")
    assert bm.find_duplicate(fresh, existing) is None


# 8. mémoire obsolète signalée
def test_8_stale_memory_flagged():
    fresh = _atom("F", confirmed_until=_NOW + timedelta(days=10))
    stale = _atom("S", confirmed_until=_NOW - timedelta(days=1))
    no_expiry = _atom("N", confirmed_until=None)
    assert bm.is_stale(stale, _NOW) is True
    assert bm.is_stale(fresh, _NOW) is False
    assert bm.is_stale(no_expiry, _NOW) is False
    rep = bm.freshness_report([fresh, stale, no_expiry], _NOW)
    assert rep["stale"] == ["S"]
    assert set(rep["fresh"]) == {"F", "N"}


# 9. source tronquée bloquée
def test_9_truncated_source_blocked():
    a = _atom("A")
    reasons = bm.validate_for_active(a, source_truncated=True)
    assert "source_truncated" in reasons
    assert not bm.can_be_active(a, source_truncated=True)


# 10. reconstruction projet depuis sources (fixtures synthétiques)
def test_10_reconstruct_project_state():
    atoms = [
        _atom("d1", kind="decision", key="db-choice", value="Postgres 16"),
        _atom("c1", kind="gotcha", key="rate-limit", value="API plafonnée 100/min"),
        _atom("t1", kind="todo", key="ship-mvp", value="Livrer le MVP"),
        _atom("old", kind="decision", key="db-choice", value="MySQL", status="superseded",
              superseded_by="d1"),
        _atom("other", scope="travail", kind="decision", key="x", value="hors projet"),
    ]
    rep = bm.reconstruct_project_state(atoms, "myguestbox")
    assert rep["project"] == "myguestbox"
    assert "d1" in rep["decisions"] and "old" not in rep["decisions"]   # superseded exclu
    assert "c1" in rep["constraints"]
    assert "t1" in rep["tasks"]
    # l'atome d'un autre projet n'est pas mélangé
    assert "other" not in rep["decisions"]


# 11. réponse 'incertain' si preuves insuffisantes
def test_11_uncertain_when_evidence_insufficient():
    assert bm.assess_certainty(supporting=0, has_source=False, contradicted=False) == "uncertain"
    assert bm.assess_certainty(supporting=2, has_source=False, contradicted=False) == "uncertain"
    assert bm.assess_certainty(supporting=2, has_source=True, contradicted=True) == "uncertain"
    assert bm.assess_certainty(supporting=2, has_source=True, contradicted=False) == "certain"


def test_11b_reconstruct_flags_uncertainty_when_source_missing():
    atoms = [
        _atom("d1", kind="decision", key="db", value="Postgres", source=False),  # pas de source
        _atom("d2", kind="decision", key="auth", value="OAuth"),                  # avec source
    ]
    rep = bm.reconstruct_project_state(atoms, "myguestbox")
    assert "d1" in rep["uncertainties"]
    assert rep["verdict"] == "uncertain"


# --- garde-fous additionnels ------------------------------------------------
def test_fragile_source_not_active():
    a = _atom("A")
    a.source_ref = {"source_path": "x", "reliability": "low"}
    assert "fragile_source" in bm.validate_for_active(a)


def test_uncertain_kind_not_active():
    q = _atom("Q", kind="question", value="On migre ?")
    assert "uncertain_kind" in bm.validate_for_active(q)


# --- régressions revue adversariale -----------------------------------------
def test_dedupe_key_no_delimiter_injection_collision():
    # un scope contenant '/' ne doit pas collisionner avec un autre découpage
    assert bm.compute_dedupe_key("a/b", "decision", "c") != \
           bm.compute_dedupe_key("a", "decision", "b/c")


def test_find_duplicate_empty_value_not_false_positive():
    # deux atomes SANS value (value='') et clés différentes ne sont PAS doublons
    a = bm.BrainAtom(id="1", kind="decision", scope="s", key="k1", value="")
    b = bm.BrainAtom(id="2", kind="decision", scope="s", key="k2", value="")
    assert bm.find_duplicate(a, [b]) is None


def test_prod_source_ref_schema_recognized_as_sourced():
    # schéma RÉEL prod : source_ref = curator_raw_id/message_indices/extracted_by/
    # ingest_node (pas source_path). Doit être reconnu comme SOURCÉ (shadow Phase 2).
    a = bm.BrainAtom(id="p1", kind="decision", scope="travail", key="k1", value="v",
                     status="active", confidence_score=80, node_id="arac-curator",
                     source_ref={"curator_raw_id": "abc", "message_indices": [1, 2],
                                 "extracted_by": "curator", "ingest_node": "local-mac"})
    assert "missing_source" not in bm.validate_for_active(a)
    assert bm._source_present(a) is True


def test_find_duplicate_still_matches_real_dup_by_hash():
    a = bm.BrainAtom(id="1", kind="decision", scope="s", key="k1", value="Postgres 16 nu")
    b = bm.BrainAtom(id="2", kind="decision", scope="s", key="k2", value="postgres 16   nu")
    assert bm.find_duplicate(b, [a]) is not None      # vraie dédup sémantique préservée
