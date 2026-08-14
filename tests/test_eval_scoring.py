"""Tests des fonctions PURES du banc d'éval retrieval (score/aggregate)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "evals"))
import run_eval as ev  # noqa: E402


def test_score_hit_rank1():
    s = ev.score(["travail/finance", "travail/strategie"], "travail/finance")
    assert s["hit"] and s["rank"] == 1 and s["rr"] == 1.0


def test_score_hit_rank3():
    s = ev.score(["a", "b", "travail/finance"], "travail/finance")
    assert s["hit"] and s["rank"] == 3 and round(s["rr"], 3) == 0.333


def test_score_miss():
    s = ev.score(["a", "b"], "travail/finance")
    assert not s["hit"] and s["rank"] == 0 and s["rr"] == 0.0


def test_aggregate():
    per = [
        {"hit": True, "rr": 1.0, "top1_distance": 0.3},
        {"hit": True, "rr": 0.5, "top1_distance": 0.5},
        {"hit": False, "rr": 0.0, "top1_distance": 0.7},
    ]
    a = ev.aggregate(per)
    assert a["n"] == 3
    assert a["recall_at_k"] == round(2 / 3, 3)
    assert a["mrr"] == round(1.5 / 3, 3)
    assert a["avg_top1_distance"] == 0.5


def test_aggregate_empty():
    a = ev.aggregate([])
    assert a["n"] == 0 and a["recall_at_k"] == 0.0


# --------------------------------------------------------------- v2 : score_atoms
def _atom(scope, status="active", source_ref=None, distance=0.3):
    return {"scope": scope, "status": status, "source_ref": source_ref, "distance": distance}


def test_score_atoms_backward_compat_with_score():
    """score_atoms doit donner les mêmes hit/rank/rr que score() sur les mêmes scopes."""
    atoms = [_atom("a"), _atom("travail/finance"), _atom("b")]
    m = ev.score_atoms(atoms, "travail/finance")
    base = ev.score(["a", "travail/finance", "b"], "travail/finance")
    assert (m["hit"], m["rank"], m["rr"]) == (base["hit"], base["rank"], base["rr"])


def test_score_atoms_top1_correct():
    hit_top1 = ev.score_atoms([_atom("travail/finance"), _atom("travail")], "travail/finance")
    assert hit_top1["top1_correct"] is True
    not_top1 = ev.score_atoms([_atom("travail"), _atom("travail/finance")], "travail/finance")
    assert not_top1["top1_correct"] is False
    empty = ev.score_atoms([], "travail/finance")
    assert empty["top1_correct"] is False


def test_score_atoms_superseded_count():
    atoms = [_atom("a", status="active"), _atom("b", status="superseded"),
             _atom("c", status="superseded")]
    m = ev.score_atoms(atoms, "a")
    assert m["n_returned"] == 3 and m["n_superseded"] == 2


def test_score_atoms_provenance_count():
    atoms = [
        _atom("a", source_ref={"ingest_node": "x", "extracted_by": "curator"}),
        _atom("b", source_ref=None),
        _atom("c", source_ref={}),  # dict vide => PAS de provenance
    ]
    m = ev.score_atoms(atoms, "a")
    assert m["n_provenance"] == 1


def test_has_provenance():
    assert ev._has_provenance(_atom("a", source_ref={"k": "v"})) is True
    assert ev._has_provenance(_atom("a", source_ref={})) is False
    assert ev._has_provenance(_atom("a", source_ref=None)) is False


def test_score_atoms_distinct_scopes():
    atoms = [_atom("travail/finance"), _atom("travail/finance"), _atom("travail"), _atom("outillage")]
    m = ev.score_atoms(atoms, "travail/finance")
    assert m["n_distinct_scopes"] == 3  # {travail/finance, travail, arac}


# --------------------------------------------------------------- v2 : aggregate
def _row(hit, rr, n_ret, n_sup, n_prov, n_dist, top1, dist=0.4, category=None):
    r = {"top1_distance": dist, "n_returned": n_ret, "n_superseded": n_sup,
         "n_provenance": n_prov, "n_distinct_scopes": n_dist}
    if category:
        r["category"] = category
    else:
        r.update({"hit": hit, "rr": rr, "top1_correct": top1})
    return r


def test_aggregate_v2_metrics():
    per = [
        _row(True, 1.0, 5, 0, 5, 3, True),
        _row(True, 0.5, 5, 0, 4, 2, False),
    ]
    a = ev.aggregate(per)
    assert a["precision_at_1"] == 0.5            # 1/2 top1 corrects
    assert a["superseded_rate"] == 0.0           # 0/10
    assert a["provenance_rate"] == 0.9           # 9/10
    assert a["source_diversity"] == 2.5          # (3+2)/2


def test_aggregate_excludes_anti_hallucination_from_recall():
    """Les requêtes anti-hallucination ne comptent ni dans recall@k ni dans MRR."""
    per = [
        _row(True, 1.0, 5, 0, 5, 2, True),                       # scorable, hit
        _row(False, 0.0, 5, 1, 5, 1, False, category="anti-hallucination"),
    ]
    a = ev.aggregate(per)
    assert a["n"] == 2 and a["n_scored"] == 1
    assert a["recall_at_k"] == 1.0               # 1 hit / 1 scorable (anti-halluc exclu)
    # superseded/provenance/diversity comptent TOUTES les lignes retournées
    assert a["superseded_rate"] == round(1 / 10, 3)
    assert a["source_diversity"] == round((2 + 1) / 2, 3)


def test_aggregate_v2_omitted_when_no_data():
    """Si aucune métrique v2 disponible (ancien format), elles sont OMISES, pas fabriquées."""
    per = [{"hit": True, "rr": 1.0, "top1_distance": 0.3}]
    a = ev.aggregate(per)
    assert "recall_at_k" in a and "mrr" in a
    assert "precision_at_1" not in a
    assert "superseded_rate" not in a
    assert "provenance_rate" not in a
    assert "source_diversity" not in a


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
