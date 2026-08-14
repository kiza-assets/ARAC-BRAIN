"""Routeur de contexte — tests E2E (Phase H). Purs (aucune DB/réseau)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.services import business_memory as bm
from app.services import code_brain as cb
from app.services import context_router as cr

_NOW = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)


def _atom(id, project="myguestbox", kind="decision", key=None, value="v",
          status="active", source=True):
    src = {"source_path": f"conv/{id}.json", "type": "conversation"} if source else None
    return bm.BrainAtom(id=id, kind=kind, scope=project, key=key or f"k-{id}",
                        value=value, status=status, source_ref=src,
                        node_id="arac-curator", confidence_score=80, project=project)


_SCHEMA_KEYS = {"task_summary", "project_context", "business_memory", "code_memory",
                "contradictions", "uncertainties", "excluded_memory", "token_budget",
                "provenance", "freshness_report", "warnings"}


def test_output_schema_complete():
    ctx = cr.build_task_context({"task": "x", "project": "myguestbox"}, atoms=[], now=_NOW)
    assert set(ctx.keys()) == _SCHEMA_KEYS


# --- MYGUESTBOX sans pollution TRAVAIL -----------------------------------------
def test_myguestbox_resume_no_travail_pollution():
    atoms = [
        _atom("m1", project="myguestbox", key="db", value="Postgres pour myguestbox"),
        _atom("m2", project="myguestbox", key="auth", value="OAuth pour myguestbox"),
        _atom("k1", project="travail", key="pos", value="Shopify POS pour travail"),
        _atom("k2", project="travail", key="theme", value="streetwear travail"),
    ]
    ctx = cr.build_task_context(
        {"task": "reprendre myguestbox db et auth", "project": "myguestbox", "need_code": False},
        atoms=atoms, now=_NOW,
    )
    ids = {b["id"] for b in ctx["business_memory"]}
    assert ids <= {"m1", "m2"}                       # aucun atome TRAVAIL
    excl_other = [e for e in ctx["excluded_memory"] if e["reason"] == "other_project"]
    assert {e["id"] for e in excl_other} == {"k1", "k2"}   # TRAVAIL tracé exclu


# --- superseded exclu par défaut --------------------------------------------
def test_superseded_excluded_by_default():
    atoms = [
        _atom("new", key="db", value="Postgres 17"),
        _atom("old", key="db", value="Postgres 16", status="superseded"),
    ]
    ctx = cr.build_task_context(
        {"task": "db postgres", "project": "myguestbox", "need_code": False},
        atoms=atoms, now=_NOW,
    )
    ids = {b["id"] for b in ctx["business_memory"]}
    assert "new" in ids and "old" not in ids
    assert any(e["id"] == "old" and e["reason"].startswith("status_") for e in ctx["excluded_memory"])


# --- 1000+ atomes : contexte borné ------------------------------------------
def test_thousand_atoms_context_stays_bounded():
    atoms = [_atom(f"a{i}", key=f"topic-{i}", value="postgres " + "x" * 200)
             for i in range(1200)]
    budget = cr.TokenBudget(memory_max=8000, max_results=40)
    ctx = cr.build_task_context(
        {"task": "postgres", "project": "myguestbox", "need_code": False},
        atoms=atoms, now=_NOW, budget=budget,
    )
    assert ctx["token_budget"]["business_tokens"] <= 8000
    assert ctx["token_budget"]["within_budget"] is True
    assert len(ctx["business_memory"]) <= 40
    # le surplus est TRACÉ (pas silencieusement perdu)
    assert any(e["reason"] == "memory_budget" for e in ctx["excluded_memory"])


# --- requête ambiguë -> incertitude visible ---------------------------------
def test_ambiguous_query_surfaces_uncertainty():
    atoms = [_atom("m1", key="db", value="Postgres")]
    ctx = cr.build_task_context(
        {"task": "zzzz quelque chose sans rapport wxyz", "project": "myguestbox", "need_code": False},
        atoms=atoms, now=_NOW,
    )
    assert "ambiguous_or_no_business_match" in ctx["warnings"]
    assert ctx["business_memory"] == []


# --- bug ARAC : fichiers + tests précis -------------------------------------
def test_arac_bug_returns_files_and_tests():
    src_files = {
        "agents/lib/curator_lib.py": "def claim_for_recuration():\n    return 1\n",
        "tests/test_curator.py": "from agents.lib.curator_lib import claim_for_recuration\n"
                                  "def test_claim():\n    assert claim_for_recuration()\n",
    }
    index, _ = cb.index_files(src_files, head="h1")
    ctx = cr.build_task_context(
        {"task": "bug dans claim_for_recuration", "repo": "arac", "need_business": False,
         "need_code": True},
        atoms=[], code_index=index, now=_NOW,
    )
    cm = ctx["code_memory"]
    assert "agents/lib/curator_lib.py" in [f["path"] for f in cm["files"]]
    assert "tests/test_curator.py" in cm["tests"]


def test_code_noise_paths_excluded():
    src_files = {
        "agents/x.py": "def foo():\n    return 1\n",
        "node_modules/pkg/y.py": "def foo():\n    return 2\n",
    }
    index, _ = cb.index_files(src_files, head="h1")
    ctx = cr.build_task_context(
        {"task": "foo", "repo": "arac", "need_business": False, "need_code": True},
        atoms=[], code_index=index, now=_NOW,
    )
    paths = [f["path"] for f in ctx["code_memory"]["files"]]
    assert "agents/x.py" in paths
    assert "node_modules/pkg/y.py" not in paths
    assert any(e.get("reason") == "noise_path" for e in ctx["excluded_memory"])


# --- contradiction remontée -------------------------------------------------
def test_contradiction_surfaced():
    atoms = [
        _atom("a", key="pay", value="On part sur Stripe"),
        _atom("b", key="pay", value="On part sur PayPal"),
    ]
    # même (scope,key) actifs -> contradiction ; la diversité n'en garde qu'un en
    # business_memory mais la contradiction est détectée AVANT la coupe.
    ctx = cr.build_task_context(
        {"task": "pay stripe paypal", "project": "myguestbox", "need_code": False},
        atoms=atoms, now=_NOW,
    )
    assert ctx["contradictions"]
    assert "contradictions_present" in ctx["warnings"]


# --- incertitude : source absente -------------------------------------------
def test_missing_source_flagged_uncertain():
    atoms = [_atom("d1", key="db", value="Postgres decision", source=False)]
    ctx = cr.build_task_context(
        {"task": "db postgres decision", "project": "myguestbox", "need_code": False},
        atoms=atoms, now=_NOW,
    )
    assert any(u["id"] == "d1" and u["reason"] == "missing_source" for u in ctx["uncertainties"])


# --- reproductibilité -------------------------------------------------------
def test_reproducible_same_inputs_same_output():
    atoms = [_atom(f"a{i}", key=f"k{i}", value=f"postgres topic {i}") for i in range(20)]
    req = {"task": "postgres topic", "project": "myguestbox", "need_code": False}
    c1 = cr.build_task_context(req, atoms=atoms, now=_NOW)
    c2 = cr.build_task_context(req, atoms=list(atoms), now=_NOW)
    assert c1 == c2
    assert [p["id"] for p in c1["provenance"]] == [p["id"] for p in c2["provenance"]]


# --- budgets respectés + passes bornées -------------------------------------
def test_retrieval_passes_bounded():
    atoms = [_atom("m1", key="db", value="Postgres")]
    ctx = cr.build_task_context(
        {"task": "db", "project": "myguestbox", "need_code": False},
        atoms=atoms, now=_NOW,
    )
    assert ctx["token_budget"]["retrieval_passes"] <= ctx["token_budget"]["max_passes"]


# --- régressions revue adversariale -----------------------------------------
def test_contradiction_detected_even_if_conflicting_atom_not_keyword_relevant():
    # a matche la requête ; b (même scope+key, valeur en conflit) NE matche PAS
    # les mots-clés -> doit quand même être détecté en contradiction.
    atoms = [
        _atom("a", key="pay", value="stripe est retenu"),
        _atom("b", key="pay", value="paypal zzz"),   # 'paypal zzz' hors requête
    ]
    ctx = cr.build_task_context(
        {"task": "stripe", "project": "myguestbox", "need_code": False},
        atoms=atoms, now=_NOW,
    )
    assert ctx["contradictions"]                       # conflit non masqué
    assert "contradictions_present" in ctx["warnings"]


def test_task_summary_truncated_by_real_token_counter():
    # compteur réel = 1 token / caractère -> une tâche de 5000 chars dépasse 2000.
    big = "x" * 5000
    ctx = cr.build_task_context(
        {"task": big, "project": "myguestbox", "need_code": False},
        atoms=[], now=_NOW, counter=len,
    )
    assert "task_summary_truncated" in ctx["warnings"]
    assert len(ctx["task_summary"]) <= 2000            # borné en tokens (=chars ici)


def test_project_context_no_false_truncation_warning():
    atoms = [_atom("m1", key="db", value="Postgres")]
    ctx = cr.build_task_context(
        {"task": "db", "project": "myguestbox", "need_code": False},
        atoms=atoms, now=_NOW,
    )
    # peu d'atomes -> pas de troncature -> pas de warning fantôme
    assert "project_context_truncated" not in ctx["warnings"]


def test_code_memory_token_bounded():
    src = {f"agents/m{i}.py": f"def foo{i}():\n    return {i}\n" for i in range(200)}
    index, _ = cb.index_files(src, head="h")
    budget = cr.TokenBudget(memory_max=40, max_results=999)
    # tâche citant tous les symboles foo* -> sans budget, 200 fichiers surfacés
    ctx = cr.build_task_context(
        {"task": " ".join(f"foo{i}" for i in range(200)), "repo": "arac",
         "need_business": False, "need_code": True},
        atoms=[], code_index=index, now=_NOW, budget=budget,
    )
    assert ctx["token_budget"]["code_tokens"] <= 40 + 8   # borné
    assert any(e.get("reason") == "code_budget" for e in ctx["excluded_memory"])


def test_provenance_present_for_each_included_atom():
    atoms = [_atom("m1", key="db", value="Postgres"), _atom("m2", key="auth", value="OAuth")]
    ctx = cr.build_task_context(
        {"task": "db auth postgres oauth", "project": "myguestbox", "need_code": False},
        atoms=atoms, now=_NOW,
    )
    prov_ids = {p["id"] for p in ctx["provenance"] if p.get("type") == "business_atom"}
    biz_ids = {b["id"] for b in ctx["business_memory"]}
    assert biz_ids <= prov_ids       # chaque atome injecté a sa provenance
