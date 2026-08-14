"""Non-régression — statut HTTP de GET /v1/brain/proposals/{id}.

Un id au charset slug inoffensif mais introuvable doit renvoyer 404 (cohérence REST
avec sessions/atoms/scope), pas 400. Un id réellement dangereux reste un 400. La
défense path-traversal du store n'est PAS modifiée (le fix est purement côté routeur).
Test indépendant de la DB (l'endpoint lit le FS via le store).
"""
import pytest
from fastapi import FastAPI, HTTPException
from starlette.testclient import TestClient

import app.routers.brain as brain


def _app():
    a = FastAPI()
    a.include_router(brain.router, prefix="/v1/brain")
    return a


def test_clean_nonexistent_id_returns_404():
    r = TestClient(_app()).get("/v1/brain/proposals/abc123")
    assert r.status_code == 404


def test_inexistant_xyz_returns_404():
    r = TestClient(_app()).get("/v1/brain/proposals/inexistant-xyz")
    assert r.status_code == 404


def test_valid_slug_but_absent_returns_404():
    # slug csp_<hex> bien formé mais aucun fichier -> introuvable -> 404
    r = TestClient(_app()).get("/v1/brain/proposals/csp_deadbeefdeadbeef")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_dangerous_id_still_400():
    # charset dangereux (hors slug inoffensif) -> rejet 400, jamais 404
    with pytest.raises(HTTPException) as ei:
        await brain.get_proposal("..%2f..%2fetc%2fpasswd")
    assert ei.value.status_code == 400


# -----------------------------------------------------------------
def test_proposals_list_signals_absent_dir(monkeypatch, tmp_path):
    # dir absent -> count=0 MAIS proposal_dir_exists=False (honnêteté : pas une
    # fausse assurance "0 proposition", la surface fichier n'est pas initialisée).
    monkeypatch.setenv("ARAC_PROPOSAL_DIR", str(tmp_path / "absent"))
    body = TestClient(_app()).get("/v1/brain/proposals").json()
    assert body["count"] == 0
    assert body["proposal_dir_exists"] is False


def test_proposals_list_signals_present_dir(monkeypatch, tmp_path):
    d = tmp_path / "props"
    d.mkdir()
    monkeypatch.setenv("ARAC_PROPOSAL_DIR", str(d))
    body = TestClient(_app()).get("/v1/brain/proposals").json()
    assert body["proposal_dir_exists"] is True
