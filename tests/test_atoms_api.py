"""Tests d'intégration API atoms — Phase 2.3.

Stratégie :
- 90% mock_embed (économie API + latence + zéro coût)
- 1 test live_api bout-en-bout (skip par défaut, marker @pytest.mark.live_api) :
  POST /v1/atoms vraie API OpenAI → vérif HalfVector(3072) en BDD → DELETE cleanup
- DB réelle `arac` avec nodes seedés 1b.6 ; cleanup via `key LIKE 'test-%'`

Couvre :
- /healthz : OK
- POST atoms : nominal, validations Pydantic, FK invalide, doublon scope+key
- GET single : 404 + nominal
- GET list : filtres scope/kind/status/tag
- PATCH : recalcul embed si value change, no-op si rien à modifier
- DELETE : soft archived, double-delete → 409
- POST supersede : version+1, status transitions, héritage tags/rationale
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


# Node seedé Phase 1b.6, FK valide pour les INSERT tests.
# 10 nodes en BDD : test-node, claude-code-serveur, claude-code-poste-2,
# claude-code-serveur, agent-{backfill-embeddings, daily-brief,
# garbage-collector, heartbeat-monitor, pattern-curator, stale-closer}.
SEED_NODE = "test-node"


# ============================================================================
# Healthz
# ============================================================================


async def test_healthz_returns_ok(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["db"]["ok"] is True


# ============================================================================
# POST /v1/atoms
# ============================================================================


async def test_create_note_nominal(client, mock_embed):
    payload = {
        "kind": "note",
        "scope": "travail/operations",
        "key": "test-create-001",
        "value": "Note test phase 2.3",
        "node_id": SEED_NODE,
    }
    r = await client.post("/v1/atoms", json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "note"
    assert body["scope"] == "travail/operations"
    assert body["key"] == "test-create-001"
    assert body["status"] == "active"
    assert body["version"] == 1
    assert body["confidence"] == "producer"
    assert body["audit_source"] is None
    assert "id" in body
    assert "desc_hash" in body
    assert mock_embed.await_count == 1


async def test_create_decision_without_rationale_returns_422(client, mock_embed):
    payload = {
        "kind": "decision",
        "scope": "travail/operations",
        "key": "test-no-rat",
        "value": "On bascule X",
        "node_id": SEED_NODE,
    }
    r = await client.post("/v1/atoms", json=payload)
    assert r.status_code == 422
    assert "rationale" in r.text.lower()
    assert mock_embed.await_count == 0  # bloqué avant embed


async def test_create_unknown_node_id_returns_422(client, mock_embed):
    payload = {
        "kind": "note",
        "scope": "travail/operations",
        "key": "test-bad-node",
        "value": "x",
        "node_id": "node-that-does-not-exist",
    }
    r = await client.post("/v1/atoms", json=payload)
    assert r.status_code == 422
    assert "node_id" in r.text


async def test_create_duplicate_active_returns_409(client, mock_embed):
    payload = {
        "kind": "note",
        "scope": "travail/operations",
        "key": "test-duplicate",
        "value": "first",
        "node_id": SEED_NODE,
    }
    r1 = await client.post("/v1/atoms", json=payload)
    assert r1.status_code == 201

    r2 = await client.post("/v1/atoms", json=payload)
    assert r2.status_code == 409
    assert "supersede" in r2.text.lower()


async def test_create_mission_proposal_nominal(client, mock_embed):
    payload = {
        "kind": "mission_proposal",
        "scope": "outillage/automatisations",
        "key": f"test-mp-{uuid.uuid4().hex[:8]}",
        "value": "Proposition de mission test : ajouter /v1/ping qui retourne 200.",
        "node_id": "claude-orchestrator",
    }
    r = await client.post("/v1/atoms", json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "mission_proposal"
    assert body["confidence"] == "producer"
    assert body["audit_source"] is None
    assert body["status"] == "active"


async def test_create_mission_nominal(client, mock_embed):
    payload = {
        "kind": "mission",
        "scope": "outillage/automatisations",
        "key": f"test-mission-{uuid.uuid4().hex[:8]}",
        "value": "Mission dispatchable : implémenter endpoint /v1/ping (test).",
        "node_id": "claude-orchestrator",
    }
    r = await client.post("/v1/atoms", json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "mission"
    assert body["confidence"] == "producer"
    assert body["status"] == "active"


# ============================================================================
# GET /v1/atoms/{id}
# ============================================================================


async def test_get_atom_404(client, mock_embed):
    fake_id = str(uuid.uuid4())
    r = await client.get(f"/v1/atoms/{fake_id}")
    assert r.status_code == 404


async def test_get_atom_existing(client, mock_embed):
    create = await client.post("/v1/atoms", json={
        "kind": "note", "scope": "travail/operations", "key": "test-get-existing",
        "value": "x", "node_id": SEED_NODE,
    })
    aid = create.json()["id"]
    r = await client.get(f"/v1/atoms/{aid}")
    assert r.status_code == 200
    assert r.json()["id"] == aid


# ============================================================================
# GET /v1/atoms (list)
# ============================================================================


async def test_list_atoms_filter_by_scope(client, mock_embed):
    await client.post("/v1/atoms", json={
        "kind": "note", "scope": "travail/operations", "key": "test-list-kpos",
        "value": "a", "node_id": SEED_NODE,
    })
    await client.post("/v1/atoms", json={
        "kind": "note", "scope": "perso/logement", "key": "test-list-tm",
        "value": "b", "node_id": SEED_NODE,
    })
    r = await client.get("/v1/atoms", params={"scope": "travail/operations"})
    assert r.status_code == 200
    items = r.json()
    keys_filtered = [item["key"] for item in items if item["key"].startswith("test-list-")]
    assert "test-list-kpos" in keys_filtered
    assert "test-list-tm" not in keys_filtered


# ============================================================================
# PATCH /v1/atoms/{id}
# ============================================================================


async def test_patch_value_recomputes_embedding(client, mock_embed):
    create = await client.post("/v1/atoms", json={
        "kind": "note", "scope": "travail/operations", "key": "test-patch-val",
        "value": "original", "node_id": SEED_NODE,
    })
    aid = create.json()["id"]
    initial_hash = create.json()["desc_hash"]
    assert mock_embed.await_count == 1

    r = await client.patch(f"/v1/atoms/{aid}", json={"value": "updated"})
    assert r.status_code == 200
    body = r.json()
    assert body["value"] == "updated"
    assert body["desc_hash"] != initial_hash  # hash recalculé
    assert mock_embed.await_count == 2  # embed re-appelé


async def test_patch_noop_returns_200(client, mock_embed):
    """PATCH avec body vide → atome inchangé, 200."""
    create = await client.post("/v1/atoms", json={
        "kind": "note", "scope": "travail/operations", "key": "test-patch-noop",
        "value": "x", "node_id": SEED_NODE,
    })
    aid = create.json()["id"]

    r = await client.patch(f"/v1/atoms/{aid}", json={})
    assert r.status_code == 200
    assert r.json()["id"] == aid
    assert r.json()["value"] == "x"


# ============================================================================
# DELETE /v1/atoms/{id} (soft)
# ============================================================================


async def test_soft_delete_returns_archived(client, mock_embed):
    create = await client.post("/v1/atoms", json={
        "kind": "note", "scope": "travail/operations", "key": "test-delete-soft",
        "value": "x", "node_id": SEED_NODE,
    })
    aid = create.json()["id"]

    r = await client.delete(f"/v1/atoms/{aid}")
    assert r.status_code == 200
    assert r.json()["status"] == "archived"


async def test_soft_delete_already_archived_returns_409(client, mock_embed):
    create = await client.post("/v1/atoms", json={
        "kind": "note", "scope": "travail/operations", "key": "test-delete-twice",
        "value": "x", "node_id": SEED_NODE,
    })
    aid = create.json()["id"]
    await client.delete(f"/v1/atoms/{aid}")  # première fois → archived

    r = await client.delete(f"/v1/atoms/{aid}")
    assert r.status_code == 409


async def test_soft_delete_404(client, mock_embed):
    fake_id = str(uuid.uuid4())
    r = await client.delete(f"/v1/atoms/{fake_id}")
    assert r.status_code == 404


# ============================================================================
# POST /v1/atoms/{id}/supersede
# ============================================================================


async def test_supersede_creates_v2_archives_v1(client, mock_embed):
    create = await client.post("/v1/atoms", json={
        "kind": "decision",
        "scope": "travail/operations",
        "key": "test-supersede-v1",
        "value": "On fait X",
        "rationale": "Parce que Y",
        "node_id": SEED_NODE,
    })
    old_id = create.json()["id"]

    r = await client.post(f"/v1/atoms/{old_id}/supersede", json={
        "new_value": "On fait X version 2",
        "new_node_id": SEED_NODE,
    })
    assert r.status_code == 201, r.text
    new_atom = r.json()
    assert new_atom["version"] == 2
    assert new_atom["status"] == "active"
    assert new_atom["id"] != old_id
    # Convention héritage : rationale=None → hérité
    assert new_atom["rationale"] == "Parce que Y"

    # Old atom doit être superseded
    old_check = await client.get(f"/v1/atoms/{old_id}")
    assert old_check.status_code == 200
    assert old_check.json()["status"] == "superseded"
    assert old_check.json()["superseded_by"] == new_atom["id"]


async def test_supersede_inactive_atom_returns_409(client, mock_embed):
    create = await client.post("/v1/atoms", json={
        "kind": "note", "scope": "travail/operations", "key": "test-supersede-archived",
        "value": "x", "node_id": SEED_NODE,
    })
    aid = create.json()["id"]
    await client.delete(f"/v1/atoms/{aid}")  # archive

    r = await client.post(f"/v1/atoms/{aid}/supersede", json={
        "new_value": "y", "new_node_id": SEED_NODE,
    })
    assert r.status_code == 409


# ============================================================================
# Test live_api bout-en-bout (⚠️ HIT API OpenAI réelle, skip par défaut)
# ============================================================================
#
# Activation :
#     sudo bash -c 'source $ARAC_HOME/.env; pytest -m live_api tests/'
#
# But : régression-guard sur le pipeline complet POST → embed() → INSERT
# halfvec(3072) → SELECT pgvector. Si on perdait `dimensions=3072` ou si
# l'adapter halfvec cassait, ce test le détecterait.
#
# Coût : ~$0.000013 (1 token "ping").


@pytest.mark.live_api
async def test_live_api_full_pipeline(client):
    """⚠️ HIT l'API OpenAI réelle. Pipeline complet POST → embed → INSERT halfvec.

    Vérifie en BDD que l'embedding stocké est bien un HalfVector de 3072 dim.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY non définie dans l'environnement")

    payload = {
        "kind": "note",
        "scope": "travail/operations",
        "key": "test-live-pipeline",
        "value": "ping",
        "node_id": SEED_NODE,
    }
    r = await client.post("/v1/atoms", json=payload)
    assert r.status_code == 201, r.text
    aid = r.json()["id"]

    # Vérification BDD : SELECT embedding et check HalfVector.dimensions
    async with db._POOL.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT embedding FROM arac.memory_atoms WHERE id = %s",
                (aid,),
            )
            row = await cur.fetchone()
    assert row is not None
    embedding = row["embedding"]
    # `HalfVector.dimensions` est une méthode (callable), pas un attribut —
    # erreur loupée Phase 2.1 où j'avais listé `dimensions` dans dir() sans
    # tester l'usage. Découvert par ce test live_api en Phase 2.3 (incident #6
    # "preuve par exécution"). On appelle la méthode + double-check via to_list().
    assert hasattr(embedding, "to_list"), (
        f"expected pgvector.HalfVector, got {type(embedding).__name__}"
    )
    dim_via_method = embedding.dimensions()
    dim_via_list = len(embedding.to_list())
    assert dim_via_method == 3072, (
        f"halfvec dim attendu 3072, reçu {dim_via_method} (méthode dimensions())"
    )
    assert dim_via_list == 3072, (
        f"halfvec to_list() len attendu 3072, reçu {dim_via_list}"
    )
