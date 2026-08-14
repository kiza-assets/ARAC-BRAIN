"""Tests d'intégration API audit_log — Phase 4.6 / D.6 (agent I3, vague 2).

Cible : `GET /v1/audit_log` exposé par app/routers/audit_log.py.

Stratégie :
- Pré-insère des rows arac.audit_log via DATABASE_URL_ADMIN (connexion ad-hoc,
  cohérent avec doctrine du soft-delete : `arac_app` n'a pas INSERT direct sur audit_log
  côté tests — Phase 4.6 c'est le router atoms qui écrira en prod).
- Cleanup : DELETE WHERE node_id IN ('test-audit-…') ; on utilise un préfixe
  dédié AVEC un node_id valide existant (FK arac.nodes), et on tagge le
  warning_code par un préfixe 'W-TEST-…' pour cibler le cleanup.
- Skip si DATABASE_URL_APP/ADMIN absents (cohérent test_dashboard.py).
- Fixture audit_seed insère 5-10 entries variées (warning_code différents,
  node_id, created_at, target_atom_id), retourne les IDs insérés.

Convention : warning_code commence par 'W-TEST-' pour ne pas polluer la prod
et garantir un cleanup ciblé. node_id = 'claude-code-serveur' (existant).
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
import pytest_asyncio


# ============================================================================
# Skip global si DB indisponible
# ============================================================================

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL_ADMIN"),
    reason="DATABASE_URL_APP/ADMIN absent — tests audit_log nécessitent BDD réelle",
)


_TEST_WARNING_PREFIX = "W-TEST-"
_TEST_NODE_ID = "claude-code-serveur"   # FK arac.nodes valide


# ============================================================================
# Helpers BDD admin
# ============================================================================


async def _cleanup_test_audit_log() -> None:
    """Supprime toutes les rows audit_log avec warning_code LIKE 'W-TEST-%'."""
    admin_dsn = os.environ["DATABASE_URL_ADMIN"]
    async with await psycopg.AsyncConnection.connect(
        admin_dsn, autocommit=True
    ) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM arac.audit_log WHERE warning_code LIKE %s",
                (_TEST_WARNING_PREFIX + "%",),
            )


async def _insert_audit_rows(rows: list[dict]) -> list[int]:
    """Insère des rows audit_log via admin, retourne les IDs."""
    admin_dsn = os.environ["DATABASE_URL_ADMIN"]
    ids: list[int] = []
    async with await psycopg.AsyncConnection.connect(
        admin_dsn, autocommit=True
    ) as conn:
        async with conn.cursor() as cur:
            for r in rows:
                await cur.execute(
                    """
                    INSERT INTO arac.audit_log
                        (node_id, action, target_atom_id, warning_code,
                         warning_context, created_at)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                    RETURNING id
                    """,
                    (
                        r.get("node_id", _TEST_NODE_ID),
                        r.get("action", "warning"),
                        r.get("target_atom_id"),
                        r["warning_code"],
                        json.dumps(r.get("warning_context", {})),
                        r.get("created_at", datetime.now(timezone.utc)),
                    ),
                )
                row = await cur.fetchone()
                ids.append(row[0])
    return ids


# ============================================================================
# Fixtures
# ============================================================================


@pytest_asyncio.fixture
async def audit_seed():
    """Pré-insère 6 entries audit_log variées + cleanup avant/après.

    Couvre :
      - 3 warning_code différents (W-TEST-001, W-TEST-002, W-TEST-003)
      - 2 entries 'récentes' + 4 entries 'anciennes' (since filter)
      - 1 entry avec target_atom_id, 5 sans
      - severity + message + context dans warning_context
    """
    await _cleanup_test_audit_log()

    now = datetime.now(timezone.utc)
    old_ts = now - timedelta(days=10)

    target_uuid = uuid.uuid4()

    rows = [
        {
            "warning_code": "W-TEST-001",
            "warning_context": {
                "severity": "warn",
                "message": "Test warning 001 récent",
                "context": {"foo": "bar", "n": 1},
            },
            "created_at": now - timedelta(minutes=1),
        },
        {
            "warning_code": "W-TEST-001",
            "warning_context": {
                "severity": "info",
                "message": "Test warning 001 récent #2",
                "context": {"n": 2},
            },
            "created_at": now - timedelta(minutes=2),
        },
        {
            "warning_code": "W-TEST-002",
            "warning_context": {
                "severity": "critical",
                "message": "Test warning 002 ancien",
                "context": {},
            },
            "created_at": old_ts,
            "target_atom_id": target_uuid,
        },
        {
            "warning_code": "W-TEST-002",
            "warning_context": {"severity": "warn", "message": "002 b"},
            "created_at": old_ts - timedelta(days=1),
        },
        {
            "warning_code": "W-TEST-003",
            "warning_context": {"severity": "info"},
            "created_at": old_ts - timedelta(days=2),
        },
        {
            "warning_code": "W-TEST-003",
            "warning_context": {},
            "created_at": old_ts - timedelta(days=3),
        },
    ]
    ids = await _insert_audit_rows(rows)
    try:
        yield {
            "ids": ids,
            "now": now,
            "old_ts": old_ts,
            "target_uuid": target_uuid,
            "rows": rows,
        }
    finally:
        await _cleanup_test_audit_log()


# ============================================================================
# Tests
# ============================================================================


async def test_list_audit_log_empty(client):
    """Aucune row W-TEST-% en BDD → endpoint retourne 200 + structure valide.

    Note : la BDD prod peut contenir d'autres warnings (W-001..W-007). On
    s'assure juste que la structure est correcte ET que nos rows test
    n'apparaissent pas (cleanup en début/fin de test).
    """
    await _cleanup_test_audit_log()
    try:
        r = await client.get(
            "/v1/audit_log",
            params={"warning_code": "W-TEST-001", "limit": 50},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "entries" in body
        assert "total" in body
        assert "limit" in body
        assert "offset" in body
        assert isinstance(body["entries"], list)
        # Aucun de nos test rows (filtré sur W-TEST-001 spécifique)
        assert body["total"] == 0
        assert body["entries"] == []
    finally:
        await _cleanup_test_audit_log()


async def test_list_audit_log_filter_by_warning_code(client, audit_seed):
    """Filtre warning_code='W-TEST-001' → 2 entries."""
    r = await client.get(
        "/v1/audit_log",
        params={"warning_code": "W-TEST-001", "limit": 50},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    assert len(body["entries"]) == 2
    for e in body["entries"]:
        assert e["warning_code"] == "W-TEST-001"
    # severity + message hissés à la racine
    severities = {e["severity"] for e in body["entries"]}
    assert severities == {"warn", "info"}
    messages = {e["message"] for e in body["entries"]}
    assert "Test warning 001 récent" in messages


async def test_list_audit_log_filter_by_since(client, audit_seed):
    """Filtre since=now-1h → uniquement les 2 entries récentes (W-TEST-001).

    Les 4 entries 'old_ts' (>= 10 jours) doivent être exclues.
    """
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    r = await client.get(
        "/v1/audit_log",
        params={"since": since, "limit": 50},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Au moins nos 2 récentes ; on filtre sur préfixe test pour isoler.
    test_entries = [
        e for e in body["entries"]
        if e["warning_code"] and e["warning_code"].startswith(_TEST_WARNING_PREFIX)
    ]
    assert len(test_entries) == 2
    for e in test_entries:
        assert e["warning_code"] == "W-TEST-001"


async def test_list_audit_log_filter_by_target_atom_id(client, audit_seed):
    """Filtre target_atom_id → unique row W-TEST-002 'ancien'."""
    target = audit_seed["target_uuid"]
    r = await client.get(
        "/v1/audit_log",
        params={"target_atom_id": str(target), "limit": 50},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert len(body["entries"]) == 1
    e = body["entries"][0]
    assert e["target_atom_id"] == str(target)
    assert e["warning_code"] == "W-TEST-002"
    assert e["severity"] == "critical"


async def test_list_audit_log_pagination(client, audit_seed):
    """Pagination limit=2 sur les 6 entries test_*.

    On filtre les résultats par préfixe test côté assert pour isoler de la prod.
    Deux pages successives ne doivent pas se chevaucher.
    """
    # Page 1 (limit=2)
    r1 = await client.get(
        "/v1/audit_log",
        params={"limit": 2, "offset": 0},
    )
    # Page 2 (limit=2, offset=2)
    r2 = await client.get(
        "/v1/audit_log",
        params={"limit": 2, "offset": 2},
    )
    assert r1.status_code == 200
    assert r2.status_code == 200
    b1 = r1.json()
    b2 = r2.json()
    assert b1["limit"] == 2
    assert b1["offset"] == 0
    assert b2["limit"] == 2
    assert b2["offset"] == 2
    assert len(b1["entries"]) <= 2
    assert len(b2["entries"]) <= 2
    ids1 = {e["id"] for e in b1["entries"]}
    ids2 = {e["id"] for e in b2["entries"]}
    assert ids1.isdisjoint(ids2), f"overlap: {ids1 & ids2}"


async def test_list_audit_log_ordering_desc(client, audit_seed):
    """Tri created_at DESC : entries récentes en tête (filtré sur préfixe test)."""
    r = await client.get(
        "/v1/audit_log",
        params={"warning_code": "W-TEST-001", "limit": 50},
    )
    assert r.status_code == 200
    entries = r.json()["entries"]
    assert len(entries) == 2
    ts = [datetime.fromisoformat(e["created_at"].replace("Z", "+00:00"))
          for e in entries]
    assert ts[0] >= ts[1], f"tri DESC attendu, reçu {ts}"


async def test_list_audit_log_invalid_params_422(client):
    """Params hors-bornes → 422 Pydantic Query validation."""
    # limit > 200
    r1 = await client.get("/v1/audit_log", params={"limit": 500})
    assert r1.status_code == 422, r1.text

    # limit < 1
    r2 = await client.get("/v1/audit_log", params={"limit": 0})
    assert r2.status_code == 422, r2.text

    # offset négatif
    r3 = await client.get("/v1/audit_log", params={"offset": -1})
    assert r3.status_code == 422, r3.text

    # target_atom_id pas un UUID
    r4 = await client.get(
        "/v1/audit_log",
        params={"target_atom_id": "not-a-uuid"},
    )
    assert r4.status_code == 422, r4.text


async def test_list_audit_log_warning_context_exposes_context_dict(
    client, audit_seed
):
    """warning_context exposé = sous-objet `context` du JSONB stocké."""
    r = await client.get(
        "/v1/audit_log",
        params={"warning_code": "W-TEST-001", "limit": 50},
    )
    assert r.status_code == 200
    entries = r.json()["entries"]
    # Cherche l'entry avec context={"foo": "bar", "n": 1}
    matching = [e for e in entries
                if isinstance(e.get("warning_context"), dict)
                and e["warning_context"].get("foo") == "bar"]
    assert len(matching) == 1
    assert matching[0]["warning_context"] == {"foo": "bar", "n": 1}
