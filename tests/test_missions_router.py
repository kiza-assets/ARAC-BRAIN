"""Tests du router missions — Bloc 9b v0.4.

Cible : `app/routers/missions.py` (GET /v1/missions, GET /v1/missions/{id}/transcript).

Stratégie :
  - Pas besoin de la fixture `initialized_pool` (router 100% filesystem,
    aucun accès BDD). On override `ARAC_MISSIONS_DIR` via monkeypatch
    avant import de l'app pour pointer vers un tmp_path.
  - On utilise httpx.AsyncClient + ASGITransport directement comme
    conftest, mais sans dépendance pool DB (le lifespan n'est pas
    invoqué via AsyncClient — cf docstring conftest).
  - Couverture :
        1. GET /v1/missions retourne liste triée par mtime DESC.
        2. GET /v1/missions retourne [] si dossier absent.
        3. GET .../transcript renvoie text/plain pour Accept text/plain.
        4. GET .../transcript renvoie JSON list pour Accept JSON.
        5. GET .../transcript?summary=true renvoie métadonnées.
        6. GET .../transcript = 404 si fichier absent.
        7. GET .../transcript = 403 si mission_id contient '..' ou '/'.

Doctrine : tests stack-as-prod côté logique, mais le FS est isolé en tmp.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


# ============================================================================
# Fixtures locales — pas de DB, FS isolé via monkeypatch
# ============================================================================


@pytest.fixture
def transcripts_dir(tmp_path, monkeypatch):
    """Crée un dossier tmp et l'expose via ARAC_MISSIONS_DIR.

    Patch ÉGALEMENT l'attribut `_TRANSCRIPTS_DIR` directement dans le module
    `app.routers.missions` (car celui-ci est résolu à l'import, donc setenv
    seul ne suffit pas si le module est déjà chargé en mémoire par d'autres
    tests).
    """
    d = tmp_path / "agents"
    d.mkdir()
    monkeypatch.setenv("ARAC_MISSIONS_DIR", str(d))

    # Patch dynamique du module si déjà importé.
    from app.routers import missions as missions_mod

    monkeypatch.setattr(missions_mod, "_TRANSCRIPTS_DIR", Path(str(d)))
    return d


# Un poste déclaré, et son jeton — comme sur une vraie installation.
_JETON_DE_TEST = "d" * 64


@pytest_asyncio.fixture
async def client_no_db(monkeypatch):
    """AsyncClient FastAPI sans init du pool DB (router missions = FS only).

    Le router missions n'utilise aucune Depends(get_db) — il est sûr de
    ne pas initialiser le pool. Les autres endpoints sont inaccessibles
    sans pool mais ce n'est pas notre cible.

    LE CLIENT PORTE SON JETON, ET CE N'EST PAS UN DÉTAIL DE PLOMBERIE.
    Ces tests passaient sans authentification parce que `ASGITransport` se
    présente par défaut sur 127.0.0.1, et que la boucle locale était exemptée.
    Elle ne l'est plus : le jeton est exigé de toute requête (`app/auth.py`).
    Poser l'en-tête ici n'est donc pas contourner la garde, c'est reproduire
    ce que fait désormais tout appelant réel — le pont, le cycle, le cockpit,
    les agents. Un test qui parlerait encore sans jeton ne testerait plus le
    produit livré.
    """
    from app import auth
    from app import main as app_main

    for cle in list(os.environ):
        if cle.startswith(auth._ENV_PREFIX):
            monkeypatch.delenv(cle, raising=False)
    monkeypatch.setenv("ARAC_NODE_TOKEN_POSTE_DE_TEST", _JETON_DE_TEST)
    monkeypatch.setattr(auth, "_tokens_cache", None)

    transport = ASGITransport(app=app_main.app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {_JETON_DE_TEST}"},
    ) as c:
        yield c
    auth._tokens_cache = None


# ============================================================================
# Helpers
# ============================================================================


def _write_jsonl(dir_path: Path, mission_id: str, events: list[dict]) -> Path:
    fp = dir_path / f"{mission_id}.jsonl"
    with fp.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")
    return fp


# ============================================================================
# GET /v1/missions
# ============================================================================


async def test_list_missions_empty_when_dir_missing(client_no_db, tmp_path, monkeypatch):
    """Si _TRANSCRIPTS_DIR n'existe pas, on retourne [] sans crasher."""
    missing = tmp_path / "does-not-exist"
    monkeypatch.setenv("ARAC_MISSIONS_DIR", str(missing))
    from app.routers import missions as missions_mod
    monkeypatch.setattr(missions_mod, "_TRANSCRIPTS_DIR", Path(str(missing)))

    r = await client_no_db.get("/v1/missions")
    assert r.status_code == 200, r.text
    assert r.json() == []


async def test_list_missions_returns_sorted_by_mtime_desc(
    client_no_db, transcripts_dir
):
    """Crée 3 missions avec mtimes décalés → ordre attendu : plus récente d'abord."""
    p1 = _write_jsonl(transcripts_dir, "mission-aaa", [{"event": "start"}])
    p2 = _write_jsonl(transcripts_dir, "mission-bbb", [{"event": "start"}])
    p3 = _write_jsonl(transcripts_dir, "mission-ccc", [{"event": "start"}])

    # mtimes explicites : ccc plus récent que bbb plus récent que aaa
    now = time.time()
    os.utime(p1, (now - 300, now - 300))
    os.utime(p2, (now - 200, now - 200))
    os.utime(p3, (now - 100, now - 100))

    r = await client_no_db.get("/v1/missions?limit=20")
    assert r.status_code == 200, r.text
    body = r.json()
    ids = [m["mission_id"] for m in body]
    assert ids == ["mission-ccc", "mission-bbb", "mission-aaa"]
    # Schéma items
    for m in body:
        assert set(m.keys()) >= {"mission_id", "mtime", "size_bytes"}
        assert isinstance(m["size_bytes"], int)
        assert m["size_bytes"] > 0


async def test_list_missions_respects_limit(client_no_db, transcripts_dir):
    """limit=2 doit tronquer la liste à 2 entrées."""
    for i in range(5):
        _write_jsonl(transcripts_dir, f"mission-{i}", [{"event": "start"}])

    r = await client_no_db.get("/v1/missions?limit=2")
    assert r.status_code == 200, r.text
    assert len(r.json()) == 2


async def test_list_missions_ignores_non_jsonl(client_no_db, transcripts_dir):
    """Les fichiers sans suffixe .jsonl ne doivent pas apparaître."""
    _write_jsonl(transcripts_dir, "mission-ok", [{"event": "start"}])
    (transcripts_dir / "notes.txt").write_text("ignore me")
    (transcripts_dir / "subdir").mkdir()

    r = await client_no_db.get("/v1/missions")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["mission_id"] == "mission-ok"


# ============================================================================
# GET /v1/missions/{id}/transcript
# ============================================================================


async def test_transcript_raw_text_plain(client_no_db, transcripts_dir):
    """Par défaut (Accept absent), retourne text/plain JSONL brut."""
    events = [
        {"event": "start", "ts": 1000.0, "sha_before": "abc123"},
        {"event": "commit", "ts": 1005.5, "sha_after": "def456"},
    ]
    _write_jsonl(transcripts_dir, "mission-raw", events)

    r = await client_no_db.get("/v1/missions/mission-raw/transcript")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/plain")
    # Chaque ligne doit être parsable en JSON
    lines = [l for l in r.text.splitlines() if l.strip()]
    assert len(lines) == 2
    parsed = [json.loads(l) for l in lines]
    assert parsed[0]["event"] == "start"
    assert parsed[1]["sha_after"] == "def456"


async def test_transcript_json_when_accept_json(client_no_db, transcripts_dir):
    """Accept: application/json doit retourner une liste parsée."""
    events = [{"event": "a"}, {"event": "b"}]
    _write_jsonl(transcripts_dir, "mission-json", events)

    r = await client_no_db.get(
        "/v1/missions/mission-json/transcript",
        headers={"Accept": "application/json"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 2
    assert body[0]["event"] == "a"


async def test_transcript_summary(client_no_db, transcripts_dir):
    """?summary=true retourne métadonnées : counts, durée, sha, verdict."""
    events = [
        {"event": "start", "ts": 100.0, "sha_before": "sha-before-xyz"},
        {"event": "diff", "ts": 102.0},
        {"event": "commit", "ts": 105.0, "sha_after": "sha-after-xyz"},
        {"event": "audit", "ts": 110.0, "verdict": "GO"},
    ]
    _write_jsonl(transcripts_dir, "mission-sum", events)

    r = await client_no_db.get(
        "/v1/missions/mission-sum/transcript?summary=true"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mission_id"] == "mission-sum"
    assert body["event_count"] == 4
    assert body["event_types_distribution"] == {
        "start": 1, "diff": 1, "commit": 1, "audit": 1,
    }
    # 110 - 100 = 10s = 10000 ms
    assert body["duration_ms"] == pytest.approx(10000.0)
    assert body["sha_before"] == "sha-before-xyz"
    assert body["sha_after"] == "sha-after-xyz"
    assert body["verdict"] == "GO"


async def test_transcript_summary_tolerates_missing_fields(
    client_no_db, transcripts_dir
):
    """Mission en cours (pas de sha_after / verdict) → champs None."""
    events = [{"event": "start", "ts": 100.0, "sha_before": "abc"}]
    _write_jsonl(transcripts_dir, "mission-partial", events)

    r = await client_no_db.get(
        "/v1/missions/mission-partial/transcript?summary=true"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["event_count"] == 1
    assert body["sha_before"] == "abc"
    assert body["sha_after"] is None
    assert body["verdict"] is None
    # 1 seul event → pas de durée calculable
    assert body["duration_ms"] is None


async def test_transcript_404_if_missing(client_no_db, transcripts_dir):
    """Fichier absent → 404."""
    r = await client_no_db.get("/v1/missions/does-not-exist/transcript")
    assert r.status_code == 404, r.text


async def test_transcript_path_traversal_with_encoded_slash_blocked(
    client_no_db, transcripts_dir
):
    """URL `..%2Fevil` : Starlette décode `%2F` en `/` au routing, donc la
    route `{mission_id}` (single path segment) ne matche pas et FastAPI
    renvoie 404. C'est une défense framework-level équivalente : le handler
    n'est jamais atteint et aucun path traversal n'est possible.
    """
    r = await client_no_db.get("/v1/missions/..%2Fevil/transcript")
    # 404 OU 403 : deux mécanismes de protection valides selon routing.
    assert r.status_code in (403, 404), r.text


async def test_transcript_path_traversal_with_slash_blocked(
    client_no_db, transcripts_dir
):
    """URL `foo%2Fbar` : Starlette décode `%2F` en `/` → 404 routing mismatch.

    Comme le test précédent : protection framework-level + validateur applicatif
    forment ensemble une garantie zero path traversal.
    """
    r = await client_no_db.get("/v1/missions/foo%2Fbar/transcript")
    assert r.status_code in (403, 404), r.text


async def test_transcript_403_path_traversal_dotdot_no_slash(
    client_no_db, transcripts_dir
):
    """mission_id avec '..' sans slash → 403 (filtre défensif)."""
    r = await client_no_db.get("/v1/missions/foo..bar/transcript")
    assert r.status_code == 403, r.text


# ============================================================================
# Tests unitaires _validate_mission_id (preuve de défense applicative)
# ============================================================================


def test_validate_mission_id_rejects_dotdot():
    """Le validateur applicatif rejette explicitement '..', '/' et '\\\\'."""
    from fastapi import HTTPException

    from app.routers.missions import _validate_mission_id

    for bad in ["..", "../evil", "foo/bar", "foo\\bar", "..%00", "\x00name", ""]:
        with pytest.raises(HTTPException) as exc:
            _validate_mission_id(bad)
        assert exc.value.status_code == 403


def test_validate_mission_id_accepts_uuid_like():
    """Les UUID et noms simples passent."""
    from app.routers.missions import _validate_mission_id

    # Aucune levée d'exception attendue
    _validate_mission_id("6263a6b4-1234-5678-9abc-def012345678")
    _validate_mission_id("manual-test-001")
    _validate_mission_id("a")


async def test_transcript_empty_jsonl(client_no_db, transcripts_dir):
    """Fichier vide → 200 mais event_count=0 en summary."""
    fp = transcripts_dir / "mission-empty.jsonl"
    fp.write_text("")

    r = await client_no_db.get(
        "/v1/missions/mission-empty/transcript?summary=true"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["event_count"] == 0
    assert body["duration_ms"] is None
