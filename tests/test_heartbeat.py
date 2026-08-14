"""Tests endpoint POST /v1/heartbeat — Phase A triade.

Couverture :
- Cas nominal : node_id valide + metadata None → 201 + ligne dans history + last_heartbeat updated
- Cas nominal : node_id valide + metadata dict → idem + metadata JSONB persistée
- Validation : node_id inconnu (FK violation) → 422
- Validation : node_id manquant → 422 (Pydantic)
- Validation : node_id vide → 422 (Pydantic min_length=1)

Cleanup : on n'efface PAS les lignes nodes_heartbeat_history créées par les
tests — c'est de la time series qui grandit naturellement en prod, et le
volume des tests est négligeable. last_heartbeat sur arac.nodes est juste
écrasée à chaque ping (pas de cleanup nécessaire).
"""

from __future__ import annotations

import os

import psycopg
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL_ADMIN"),
    reason="DB reelle requise",
)


async def _admin_conn():
    dsn = os.environ.get("DATABASE_URL_ADMIN")
    if not dsn:
        pytest.skip("DATABASE_URL_ADMIN non définie")
    return await psycopg.AsyncConnection.connect(dsn, autocommit=True)


async def _count_heartbeats(node_id: str) -> int:
    conn = await _admin_conn()
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT COUNT(*) FROM arac.nodes_heartbeat_history WHERE node_id = %s",
                (node_id,),
            )
            row = await cur.fetchone()
            return row[0] if row else 0
    finally:
        await conn.close()


async def _last_heartbeat(node_id: str):
    conn = await _admin_conn()
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT last_heartbeat FROM arac.nodes WHERE node_id = %s",
                (node_id,),
            )
            row = await cur.fetchone()
            return row[0] if row else None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_heartbeat_nominal_no_metadata(client):
    """POST /v1/heartbeat avec node_id valide sans metadata → 201."""
    # On utilise test-node (existe Phase 1b.6) plutôt que les agents
    # claude-orchestrator/developer/codex-auditor qui ne sont enregistrés
    # qu'au déploiement Phase A (idempotent — ce test ne dépend pas de ça).
    node_id = "test-node"
    before = await _count_heartbeats(node_id)

    r = await client.post("/v1/heartbeat", json={"node_id": node_id})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["node_id"] == node_id
    assert body["heartbeat_at"]  # ISO timestamp non vide

    after = await _count_heartbeats(node_id)
    assert after == before + 1, "exactement 1 ligne insérée dans nodes_heartbeat_history"

    # last_heartbeat sur nodes doit être récent (< 5s après le POST)
    last = await _last_heartbeat(node_id)
    assert last is not None


@pytest.mark.asyncio
async def test_heartbeat_with_metadata(client):
    """metadata={...} → JSONB persistée."""
    node_id = "test-node"
    meta = {"phase": "A", "test": True, "counter": 42}

    r = await client.post(
        "/v1/heartbeat",
        json={"node_id": node_id, "metadata": meta},
    )
    assert r.status_code == 201, r.text

    # Vérifier que la dernière ligne pour ce node contient le metadata
    conn = await _admin_conn()
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT metadata FROM arac.nodes_heartbeat_history "
                "WHERE node_id = %s ORDER BY heartbeat_at DESC LIMIT 1",
                (node_id,),
            )
            row = await cur.fetchone()
            assert row is not None
            persisted = row[0]
            assert persisted == meta
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_heartbeat_unknown_node_id_returns_422(client):
    """node_id absent de arac.nodes → 422 (FK violation)."""
    r = await client.post(
        "/v1/heartbeat",
        json={"node_id": "node-qui-nexiste-pas-2026-05"},
    )
    assert r.status_code == 422, r.text
    assert "inconnu" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_heartbeat_missing_node_id_returns_422(client):
    """Body sans node_id → 422 (Pydantic)."""
    r = await client.post("/v1/heartbeat", json={})
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_heartbeat_empty_node_id_returns_422(client):
    """node_id vide → 422 (min_length=1)."""
    r = await client.post("/v1/heartbeat", json={"node_id": ""})
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_heartbeat_extra_field_rejected(client):
    """extra='forbid' → champ inconnu = 422."""
    r = await client.post(
        "/v1/heartbeat",
        json={"node_id": "test-node", "unknown_field": "x"},
    )
    assert r.status_code == 422, r.text
