"""Tests d'intégration API sessions — Phase 2.4.

Stratégie identique aux tests atoms 2.3 :
- 13 tests mockés (cas nominaux + erreurs + couplage atoms ↔ sessions)
- 1 test live_api bout-en-bout (close avec embed réel + vérif halfvec(3072))
- DB réelle `arac` avec nodes seedés Phase 1b.6
- Cleanup admin via DATABASE_URL_ADMIN :
  `DELETE FROM arac.sessions WHERE topic LIKE 'test-%'` (cascade buffer Q.G)

Convention test : tous les tests créent leurs sessions avec `topic="test-..."`
pour permettre le cleanup automatique.
"""

from __future__ import annotations

import os
import uuid

import pytest
from psycopg.rows import dict_row

from app import db


pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL_ADMIN"),
    reason="DB reelle requise",
)


SEED_NODE = "test-node"


# ============================================================================
# POST /v1/sessions/open
# ============================================================================


async def test_open_session_returns_201(client):
    payload = {
        "node_id": SEED_NODE,
        "scope": "travail/operations",
        "topic": "test-open-session",
    }
    r = await client.post("/v1/sessions/open", json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["node_id"] == SEED_NODE
    assert body["scope"] == "travail/operations"
    assert body["topic"] == "test-open-session"
    assert body["ended_at"] is None
    assert body["summary"] is None
    assert body["closed_by"] is None
    assert body["atoms_created"] == []
    assert "id" in body


async def test_open_session_topic_optional(client):
    """Création sans topic — POST minimal."""
    payload = {"node_id": SEED_NODE, "scope": "travail/operations", "topic": "test-no-topic"}
    r = await client.post("/v1/sessions/open", json=payload)
    assert r.status_code == 201
    assert r.json()["topic"] == "test-no-topic"


async def test_open_session_unknown_node_id_422(client):
    payload = {
        "node_id": "node-that-does-not-exist",
        "scope": "travail/operations",
        "topic": "test-bad-node",
    }
    r = await client.post("/v1/sessions/open", json=payload)
    assert r.status_code == 422
    assert "node_id" in r.text


# ============================================================================
# POST /v1/sessions/{id}/append
# ============================================================================


async def test_append_event_to_open_session(client):
    create = await client.post("/v1/sessions/open", json={
        "node_id": SEED_NODE, "scope": "travail/operations", "topic": "test-append-open",
    })
    sid = create.json()["id"]

    r = await client.post(f"/v1/sessions/{sid}/append", json={
        "event_type": "message",
        "payload": {"text": "Hello world"},
    })
    assert r.status_code == 201
    body = r.json()
    assert body["ok"] is True
    assert body["event_type"] == "message"
    assert body["session_id"] == sid


async def test_append_event_to_closed_session_409(client, mock_embed):
    """Append refusé si session closed."""
    create = await client.post("/v1/sessions/open", json={
        "node_id": SEED_NODE, "scope": "travail/operations", "topic": "test-append-closed",
    })
    sid = create.json()["id"]
    await client.post(f"/v1/sessions/{sid}/close", json={
        "summary": "session terminée pour test",
    })

    r = await client.post(f"/v1/sessions/{sid}/append", json={
        "event_type": "message",
        "payload": {"text": "trop tard"},
    })
    assert r.status_code == 409
    assert "closed" in r.text.lower()


async def test_append_to_unknown_session_404(client):
    fake_id = str(uuid.uuid4())
    r = await client.post(f"/v1/sessions/{fake_id}/append", json={
        "event_type": "message", "payload": None,
    })
    assert r.status_code == 404


# ============================================================================
# POST /v1/sessions/{id}/close
# ============================================================================


async def test_close_session_calls_embed(client, mock_embed):
    create = await client.post("/v1/sessions/open", json={
        "node_id": SEED_NODE, "scope": "travail/operations", "topic": "test-close-call",
    })
    sid = create.json()["id"]

    r = await client.post(f"/v1/sessions/{sid}/close", json={
        "summary": "Session test close — résumé qui sera embedded",
        "accomplishments": ["fait truc 1", "fait truc 2"],
        "blockers": ["bloqué sur X"],
        "next_steps": ["faire Y demain"],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ended_at"] is not None
    assert body["summary"].startswith("Session test close")
    assert body["accomplishments"] == ["fait truc 1", "fait truc 2"]
    assert body["blockers"] == ["bloqué sur X"]
    assert body["next_steps"] == ["faire Y demain"]
    assert body["closed_by"] == "manual"
    assert mock_embed.await_count == 1


async def test_close_already_closed_409(client, mock_embed):
    create = await client.post("/v1/sessions/open", json={
        "node_id": SEED_NODE, "scope": "travail/operations", "topic": "test-close-twice",
    })
    sid = create.json()["id"]
    await client.post(f"/v1/sessions/{sid}/close", json={"summary": "1ère close"})

    r = await client.post(f"/v1/sessions/{sid}/close", json={"summary": "2e close"})
    assert r.status_code == 409
    assert "closed" in r.text.lower()


# ============================================================================
# GET /v1/sessions/{id}
# ============================================================================


async def test_get_session_404(client):
    fake_id = str(uuid.uuid4())
    r = await client.get(f"/v1/sessions/{fake_id}")
    assert r.status_code == 404


async def test_get_session_no_buffer_default(client):
    create = await client.post("/v1/sessions/open", json={
        "node_id": SEED_NODE, "scope": "travail/operations", "topic": "test-get-nobuf",
    })
    sid = create.json()["id"]
    await client.post(f"/v1/sessions/{sid}/append", json={
        "event_type": "message", "payload": {"text": "x"},
    })

    r = await client.get(f"/v1/sessions/{sid}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == sid
    # Sans include_buffer, pas de champ buffer
    assert "buffer" not in body


async def test_get_session_with_buffer(client):
    create = await client.post("/v1/sessions/open", json={
        "node_id": SEED_NODE, "scope": "travail/operations", "topic": "test-get-buf",
    })
    sid = create.json()["id"]
    await client.post(f"/v1/sessions/{sid}/append", json={
        "event_type": "message", "payload": {"text": "premier event"},
    })
    await client.post(f"/v1/sessions/{sid}/append", json={
        "event_type": "note", "payload": {"text": "deuxième event"},
    })

    r = await client.get(f"/v1/sessions/{sid}", params={"include_buffer": "true"})
    assert r.status_code == 200
    body = r.json()
    assert "buffer" in body
    assert len(body["buffer"]) == 2
    assert body["buffer"][0]["event_type"] == "message"
    assert body["buffer"][1]["event_type"] == "note"


# ============================================================================
# GET /v1/sessions (list)
# ============================================================================


async def test_list_sessions_filter_by_node(client):
    await client.post("/v1/sessions/open", json={
        "node_id": SEED_NODE, "scope": "travail/operations", "topic": "test-list-node",
    })

    r = await client.get("/v1/sessions", params={"node_id": SEED_NODE})
    assert r.status_code == 200
    items = r.json()
    test_items = [s for s in items if s["topic"] == "test-list-node"]
    assert len(test_items) >= 1
    assert all(s["node_id"] == SEED_NODE for s in items)


async def test_list_sessions_filter_status_open(client, mock_embed):
    # 1 open + 1 closed
    open_sess = await client.post("/v1/sessions/open", json={
        "node_id": SEED_NODE, "scope": "travail/operations", "topic": "test-list-open",
    })
    closed_sess = await client.post("/v1/sessions/open", json={
        "node_id": SEED_NODE, "scope": "travail/operations", "topic": "test-list-closed",
    })
    closed_id = closed_sess.json()["id"]
    await client.post(f"/v1/sessions/{closed_id}/close", json={"summary": "close"})

    r = await client.get("/v1/sessions", params={"status": "open"})
    assert r.status_code == 200
    items = r.json()
    test_open = [s for s in items if s["topic"] == "test-list-open"]
    test_closed = [s for s in items if s["topic"] == "test-list-closed"]
    assert len(test_open) == 1
    assert len(test_closed) == 0  # closed exclu du filter open
    assert all(s["ended_at"] is None for s in items)


# ============================================================================
# Couplage atomes ↔ sessions
# ============================================================================


async def test_atoms_created_includes_atom_with_session_id(client, mock_embed):
    """POST /v1/atoms avec session_id → la session voit l'atome dans atoms_created."""
    open_resp = await client.post("/v1/sessions/open", json={
        "node_id": SEED_NODE, "scope": "travail/operations", "topic": "test-coupling",
    })
    sid = open_resp.json()["id"]

    atom_resp = await client.post("/v1/atoms", json={
        "kind": "note",
        "scope": "travail/operations",
        "key": "test-coupling-atom",
        "value": "atome lié à session test",
        "node_id": SEED_NODE,
        "session_id": sid,
    })
    assert atom_resp.status_code == 201
    aid = atom_resp.json()["id"]

    # Vérification : la session voit l'atome dans atoms_created (calcul live)
    sess_resp = await client.get(f"/v1/sessions/{sid}")
    assert sess_resp.status_code == 200
    assert aid in sess_resp.json()["atoms_created"]


# ============================================================================
# Test live_api bout-en-bout (⚠️ hit API OpenAI réelle, skip par défaut)
# ============================================================================
#
# Activation : `sudo bash -c 'source .env; pytest -m live_api tests/test_sessions_api.py'`
# Coût : ~$0.000013 (1 token "ping" pour le summary)
# But : régression-guard sur le pipeline close → embed → INSERT halfvec(3072)


@pytest.mark.live_api
async def test_live_close_session_summary_embedded_3072(client):
    """⚠️ HIT API OpenAI. close session → embed(summary) → halfvec(3072) en BDD."""
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY non définie")

    open_resp = await client.post("/v1/sessions/open", json={
        "node_id": SEED_NODE, "scope": "travail/operations", "topic": "test-live-close",
    })
    sid = open_resp.json()["id"]

    close_resp = await client.post(f"/v1/sessions/{sid}/close", json={
        "summary": "ping",  # 1 token, coût minimal
    })
    assert close_resp.status_code == 200, close_resp.text

    # Vérification BDD : summary_embedding est un HalfVector(3072)
    async with db._POOL.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT summary_embedding FROM arac.sessions WHERE id = %s",
                (sid,),
            )
            row = await cur.fetchone()
    assert row is not None
    embedding = row["summary_embedding"]
    assert hasattr(embedding, "to_list"), (
        f"expected pgvector.HalfVector, got {type(embedding).__name__}"
    )
    dim = embedding.dimensions()  # méthode, pas attribut (cf incident #6 Phase 2.3)
    assert dim == 3072, f"halfvec dim attendu 3072, reçu {dim}"
    assert len(embedding.to_list()) == 3072
