"""Cerveau code — tests PURS (Phase G). ast déterministe, aucun OpenAI, aucune DB."""

from __future__ import annotations

from app.services import code_brain as cb

_FILES = {
    "agents/curator/main.py": (
        "from agents.lib import curator_lib\n"
        "def curate_one():\n"
        "    return curator_lib.claim_for_recuration()\n"
    ),
    "agents/lib/curator_lib.py": (
        "def claim_for_recuration():\n"
        "    return 1\n"
        "class Curator:\n"
        "    def run(self):\n"
        "        return 2\n"
    ),
    "app/routers/atoms.py": (
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        "@router.get('/v1/atoms')\n"
        "async def list_atoms():\n"
        "    return []\n"
    ),
    "tests/test_curator.py": (
        "from agents.lib.curator_lib import claim_for_recuration\n"
        "def test_claim():\n"
        "    assert claim_for_recuration() == 1\n"
    ),
}


def _index(head="c1", files=None):
    idx, stats = cb.index_files(files or _FILES, head)
    return idx, stats


# --- parsing & extraction ---------------------------------------------------
def test_module_name_mapping():
    assert cb.module_name_for("agents/curator/main.py") == "agents.curator.main"
    assert cb.module_name_for("pkg/__init__.py") == "pkg"


def test_symbols_and_methods_extracted():
    idx, _ = _index()
    rec = idx.files["agents/lib/curator_lib.py"]
    names = {s.name for s in rec.symbols}
    assert "claim_for_recuration" in names
    assert "Curator" in names
    assert "Curator.run" in names


# --- symbol -> file + tests -------------------------------------------------
def test_symbol_to_file_exact():
    idx, _ = _index()
    assert cb.symbol_to_files(idx, "claim_for_recuration") == ["agents/lib/curator_lib.py"]


def test_symbol_to_tests():
    idx, _ = _index()
    assert cb.symbol_to_tests(idx, "claim_for_recuration") == ["tests/test_curator.py"]


# --- route -> handler -------------------------------------------------------
def test_route_to_handler():
    idx, _ = _index()
    h = cb.route_to_handler(idx, "get", "/v1/atoms")
    assert h is not None
    assert h["file"] == "app/routers/atoms.py"
    assert h["handler"] == "list_atoms"


def test_route_unknown_is_none():
    idx, _ = _index()
    assert cb.route_to_handler(idx, "post", "/nope") is None


# --- modified file -> dependents + impact -----------------------------------
def test_file_dependents():
    idx, _ = _index()
    deps = cb.file_dependents(idx, "agents/lib/curator_lib.py")
    assert "agents/curator/main.py" in deps
    assert "tests/test_curator.py" in deps


def test_impacted_by_transitive():
    idx, _ = _index()
    impacted = cb.impacted_by(idx, "agents/lib/curator_lib.py")
    assert "agents/curator/main.py" in impacted


# --- incrémentalité : HEAD inchangé -> pas de re-scan -----------------------
def test_head_unchanged_no_rescan():
    idx, _ = _index(head="c1")
    idx2, stats = cb.index_files(_FILES, "c1", prev=idx)
    assert stats.head_unchanged is True
    assert stats.rescanned is False
    assert stats.reindexed == 0
    assert idx2 is idx               # index réutilisé tel quel


def test_incremental_reparses_only_changed():
    idx, _ = _index(head="c1")
    changed = dict(_FILES)
    changed["agents/lib/curator_lib.py"] = changed["agents/lib/curator_lib.py"] + "\ndef extra():\n    return 9\n"
    idx2, stats = cb.index_files(changed, "c2", prev=idx)
    assert stats.reindexed == 1      # un seul fichier re-parsé
    assert stats.reused == len(_FILES) - 1
    assert "extra" in {s.name for s in idx2.files["agents/lib/curator_lib.py"].symbols}


# --- erreur parser isolée ---------------------------------------------------
def test_parser_error_isolated():
    files = dict(_FILES)
    files["agents/broken.py"] = "def oops(:\n  syntax error\n"
    idx, stats = cb.index_files(files, "c3")
    assert stats.parse_errors == 1
    assert idx.files["agents/broken.py"].parse_error is not None
    # l'index global reste utilisable : les requêtes sur les bons fichiers marchent
    assert cb.symbol_to_files(idx, "claim_for_recuration") == ["agents/lib/curator_lib.py"]
    assert cb.route_to_handler(idx, "get", "/v1/atoms") is not None


# --- fichier non indexé -> incertitude explicite ----------------------------
def test_unindexed_file_is_uncertain():
    idx, _ = _index()
    r = cb.resolve(idx, "agents/does_not_exist.py")
    assert r["indexed"] is False
    assert r["uncertain"] is True
    assert r["reason"] == "file_not_indexed"


def test_resolve_indexed_file():
    idx, _ = _index()
    r = cb.resolve(idx, "app/routers/atoms.py")
    assert r["indexed"] is True
    assert r["uncertain"] is False
    assert any(rt["handler"] == "list_atoms" for rt in r["routes"])


# --- changement technique -> revalidation décision --------------------------
def test_decisions_to_revalidate():
    links = {
        "atom-1": ["agents/lib/curator_lib.py"],
        "atom-2": ["app/routers/atoms.py"],
    }
    flagged = cb.decisions_to_revalidate(["agents/lib/curator_lib.py"], links)
    assert flagged == ["atom-1"]


# --- budget : aucun appel réseau/LLM ----------------------------------------
# --- régressions revue adversariale -----------------------------------------
def test_relative_imports_resolved_in_dependents():
    files = {
        "agents/curator/main.py": "from ..lib import curator_lib\nfrom . import policy\n"
                                  "def f():\n    return 1\n",
        "agents/lib/curator_lib.py": "def g():\n    return 2\n",
        "agents/curator/policy.py": "def p():\n    return 3\n",
    }
    idx, _ = cb.index_files(files, "h")
    assert "agents/curator/main.py" in cb.file_dependents(idx, "agents/lib/curator_lib.py")
    assert "agents/curator/main.py" in cb.file_dependents(idx, "agents/curator/policy.py")


def test_package_init_relative_import_resolved():
    files = {
        "pkg/__init__.py": "from . import sub\n",
        "pkg/sub.py": "def s():\n    return 1\n",
    }
    idx, _ = cb.index_files(files, "h")
    assert "pkg/__init__.py" in cb.file_dependents(idx, "pkg/sub.py")


def test_impacted_by_excludes_self_on_cycle():
    files = {"a.py": "import b\n", "b.py": "import a\n"}
    idx, _ = cb.index_files(files, "h")
    assert "a.py" not in cb.impacted_by(idx, "a.py")
    assert "b.py" in cb.impacted_by(idx, "a.py")


def test_indexing_is_pure_no_network():
    # Sanity : l'indexeur n'IMPORTE ni openai ni httpx (coût LLM nul par design).
    import inspect
    for line in inspect.getsource(cb).splitlines():
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            assert "openai" not in stripped
            assert "httpx" not in stripped
            assert "anthropic" not in stripped
