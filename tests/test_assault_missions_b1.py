"""Non-régression — robustesse FS du router missions.

Quand le dossier des transcripts existe mais est ILLISIBLE (permissions), les
endpoints ne doivent plus lever un 500 non géré : `GET /v1/missions` -> [] (200),
`GET /v1/missions/{id}/transcript` -> 503 explicite. Le chemin nominal (dossier
lisible) reste correct. Test indépendant de la DB et insensible à l'uid (root
contournerait un chmod) : on simule la PermissionError via un faux dossier.
"""
from fastapi import FastAPI
from starlette.testclient import TestClient

import app.routers.missions as missions


def _app():
    a = FastAPI()
    a.include_router(missions.router, prefix="/v1/missions")
    return a


class _FakePath:
    def exists(self):
        raise PermissionError(13, "Permission denied")

    def read_text(self, *a, **k):
        raise PermissionError(13, "Permission denied")


class _UnreadableDir:
    def exists(self):
        return True

    def iterdir(self):
        raise PermissionError(13, "Permission denied")

    def __truediv__(self, other):
        return _FakePath()


def test_list_missions_unreadable_dir_returns_empty_200(monkeypatch):
    monkeypatch.setattr(missions, "_TRANSCRIPTS_DIR", _UnreadableDir())
    r = TestClient(_app()).get("/v1/missions")
    assert r.status_code == 200
    assert r.json() == []


def test_transcript_unreadable_returns_503(monkeypatch):
    monkeypatch.setattr(missions, "_TRANSCRIPTS_DIR", _UnreadableDir())
    r = TestClient(_app()).get("/v1/missions/m1/transcript")
    assert r.status_code == 503


def test_list_missions_happy_path(monkeypatch, tmp_path):
    d = tmp_path / "agents"
    d.mkdir()
    (d / "alpha.jsonl").write_text('{"event":"x"}\n', encoding="utf-8")
    monkeypatch.setattr(missions, "_TRANSCRIPTS_DIR", d)
    r = TestClient(_app()).get("/v1/missions")
    assert r.status_code == 200
    assert "alpha" in [m["mission_id"] for m in r.json()]


def test_list_missions_absent_dir_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(missions, "_TRANSCRIPTS_DIR", tmp_path / "nope")
    r = TestClient(_app()).get("/v1/missions")
    assert r.status_code == 200
    assert r.json() == []
