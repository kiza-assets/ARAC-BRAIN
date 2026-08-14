"""Tests unitaires `recall_for_dedup` (MCP retrieval tool, v0.5 Cerveau Vivant).

Helper utilisé par le curator agent (Vague 2 I4) en pré-commit `create_atom`
pour détecter les quasi-doublons sémantiques. Convention :
    similarity = 1 - distance   (pgvector cosine distance ARAC)

Stratégie de test :
- On mock `_post` du module `arac_mcp.client` pour simuler la réponse de
  /v1/atoms/recall sans toucher la BDD ni l'API embeddings.
- Pas de mock du transport MCP : on appelle directement la fonction Python
  attachée via mcp.tool() (cf test_mcp_tools_registration.py pour le pattern).

Cas couverts :
  1. top match au-dessus du seuil → matched=True + atom + score
  2. tous les candidats sous le seuil → matched=False + top_score
  3. scope est bien propagé au payload /v1/atoms/recall
  4. threshold custom (0.80 vs 0.92) modifie la décision sur le même set
  5. liste vide / dégradés (atomes sans `distance`) → matched=False
  6. exception HTTP côté API → matched=False + error structuré
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Bootstrap sys.path : permettre l'import de arac_mcp.tools.retrieval
# (mêmes contraintes que test_mcp_tools_registration.py)
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[1]
_MCP_DIR = _REPO_ROOT / "mcp"
_ARAC_MCP_DIR = _MCP_DIR / "arac_mcp"

for p in (str(_ARAC_MCP_DIR), str(_MCP_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Le serveur MCP — le pont par lequel Claude Code parle au cerveau — n'est pas
# livré avec le moteur. Sans lui, ces tests n'ont rien à vérifier : on SAUTE
# le module entier plutôt que de faire échouer une suite qui teste autre chose.
pytestmark = pytest.mark.skipif(
    not (_ARAC_MCP_DIR / "tools" / "retrieval.py").is_file(),
    reason="aucun serveur MCP n'est livre par ce depot",
)

# cwd-safe avant import de FastMCP (pydantic_settings inspecte `.env`)
_SAFE_CWD = _REPO_ROOT / "data" / "agent-home"
if _SAFE_CWD.is_dir():
    os.chdir(str(_SAFE_CWD))


# ---------------------------------------------------------------------------
# Fixtures : mock du client HTTP partagé
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_recall_atoms(monkeypatch):
    """Mock `_post` dans arac_mcp.tools.retrieval pour retourner une liste
    d'atomes synthétiques avec distances contrôlées.

    Retourne une closure `set_atoms(atoms_list, capture=None)` :
      - atoms_list : liste de dicts atomes à renvoyer pour le prochain appel
      - capture    : dict optionnel `{}` rempli avec `path`/`payload` du dernier
                     appel _post (pour vérifier la propagation du scope).
    """
    from arac_mcp.tools import retrieval as retrieval_mod

    state: dict = {"atoms": [], "capture": None, "raise": None}

    def fake_post(path: str, payload: dict):
        if state["capture"] is not None:
            state["capture"]["path"] = path
            state["capture"]["payload"] = payload
        if state["raise"] is not None:
            raise state["raise"]
        return state["atoms"]

    monkeypatch.setattr(retrieval_mod, "_post", fake_post)

    def configure(atoms_list=None, capture=None, raise_exc=None):
        state["atoms"] = atoms_list or []
        state["capture"] = capture
        state["raise"] = raise_exc

    return configure


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_match_above_threshold(mock_recall_atoms):
    """Cas 1 — un voisin avec distance=0.05 → similarity=0.95 ≥ 0.92 → matched."""
    from arac_mcp.tools.retrieval import recall_for_dedup

    mock_recall_atoms(atoms_list=[
        {"id": "uuid-a", "key": "atom-a", "value": "v-a", "distance": 0.05},
        {"id": "uuid-b", "key": "atom-b", "value": "v-b", "distance": 0.30},
        {"id": "uuid-c", "key": "atom-c", "value": "v-c", "distance": 0.42},
    ])

    result = recall_for_dedup("texte candidat", scope="claude-config")
    assert result["matched"] is True
    assert result["atom_id"] == "uuid-a"
    assert result["score"] == pytest.approx(0.95)
    assert result["threshold"] == 0.92
    assert result["atom"]["key"] == "atom-a"


def test_no_match_below_threshold(mock_recall_atoms):
    """Cas 2 — tous les candidats sous le seuil → matched=False + top_score."""
    from arac_mcp.tools.retrieval import recall_for_dedup

    mock_recall_atoms(atoms_list=[
        # similarities : 0.85, 0.70, 0.55 — toutes < 0.92
        {"id": "uuid-a", "key": "atom-a", "value": "v-a", "distance": 0.15},
        {"id": "uuid-b", "key": "atom-b", "value": "v-b", "distance": 0.30},
        {"id": "uuid-c", "key": "atom-c", "value": "v-c", "distance": 0.45},
    ])

    result = recall_for_dedup("texte candidat", scope="claude-config")
    assert result["matched"] is False
    assert result["top_score"] == pytest.approx(0.85)
    assert result["threshold"] == 0.92
    assert result["scope"] == "claude-config"


def test_scope_propagated_to_payload(mock_recall_atoms):
    """Cas 3 — le scope passé en argument est bien envoyé à /v1/atoms/recall."""
    from arac_mcp.tools.retrieval import recall_for_dedup

    captured: dict = {}
    mock_recall_atoms(
        atoms_list=[{"id": "uuid-x", "distance": 0.50}],
        capture=captured,
    )

    recall_for_dedup("query", scope="immobilier")
    assert captured["path"] == "/v1/atoms/recall"
    assert captured["payload"]["query"] == "query"
    assert captured["payload"]["scope"] == "immobilier"
    assert captured["payload"]["k"] == 3

    # Sans scope, la clé ne doit PAS être présente dans le payload.
    captured2: dict = {}
    mock_recall_atoms(
        atoms_list=[{"id": "uuid-x", "distance": 0.50}],
        capture=captured2,
    )
    recall_for_dedup("query")
    assert "scope" not in captured2["payload"]


def test_threshold_custom_changes_decision(mock_recall_atoms):
    """Cas 4 — même set d'atomes, seuil 0.80 matche, seuil 0.92 ne matche pas.

    Le top atome a distance=0.15 → similarity=0.85, qui est :
      - ≥ 0.80 → matched (seuil custom permissif)
      - < 0.92 → not matched (seuil défaut)
    """
    from arac_mcp.tools.retrieval import recall_for_dedup

    atoms = [
        {"id": "uuid-a", "key": "atom-a", "value": "v-a", "distance": 0.15},
        {"id": "uuid-b", "key": "atom-b", "value": "v-b", "distance": 0.40},
    ]

    # Seuil défaut (0.92) → not matched
    mock_recall_atoms(atoms_list=list(atoms))
    r_strict = recall_for_dedup("texte", scope="claude-config")
    assert r_strict["matched"] is False
    assert r_strict["top_score"] == pytest.approx(0.85)

    # Seuil custom (0.80) → matched
    mock_recall_atoms(atoms_list=list(atoms))
    r_loose = recall_for_dedup("texte", scope="claude-config", threshold=0.80)
    assert r_loose["matched"] is True
    assert r_loose["atom_id"] == "uuid-a"
    assert r_loose["score"] == pytest.approx(0.85)
    assert r_loose["threshold"] == 0.80


def test_empty_or_distanceless_candidates(mock_recall_atoms):
    """Cas 5 — liste vide ou atomes sans `distance` → matched=False propre.

    Sous-cas a : API renvoie [] → matched=False, top_score=None.
    Sous-cas b : API renvoie des atomes SANS champ distance → matched=False,
                  top_score=None (filtrage défensif).
    """
    from arac_mcp.tools.retrieval import recall_for_dedup

    # Sous-cas a : aucun candidat
    mock_recall_atoms(atoms_list=[])
    r_empty = recall_for_dedup("texte")
    assert r_empty["matched"] is False
    assert r_empty["top_score"] is None
    assert r_empty["threshold"] == 0.92

    # Sous-cas b : atomes sans distance (cas dégradé API)
    mock_recall_atoms(atoms_list=[
        {"id": "uuid-x", "key": "broken"},
        {"id": "uuid-y", "key": "also-broken", "distance": None},
    ])
    r_broken = recall_for_dedup("texte")
    assert r_broken["matched"] is False
    assert r_broken["top_score"] is None


def test_http_exception_returns_structured_error(mock_recall_atoms):
    """Cas 6 — exception côté _post (API down, timeout) → matched=False + error."""
    from arac_mcp.tools.retrieval import recall_for_dedup

    mock_recall_atoms(raise_exc=ConnectionError("API down"))
    result = recall_for_dedup("texte", scope="claude-config")
    assert result["matched"] is False
    assert result["top_score"] is None
    assert result["threshold"] == 0.92
    assert result["error"] == "ConnectionError"
    assert "API down" in result["detail"]
