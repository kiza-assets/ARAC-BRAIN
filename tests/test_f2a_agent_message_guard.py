"""Tests F2A — garde-fous agent_message archived + scopes R1 (v0.7 phase2).

Ferme les deux trous rouges :
- S2 : kind='agent_message' ne doit JAMAIS redevenir status='active' via l'API
  (create_atom le force 'archived' ; update_atom PATCH le refuse 422).
- Anti-regression sur la serialisation AtomRead des 40 scopes (le bug 500 vecu
  quand un scope re-roote n'etait pas encore dans l'enum Pydantic).

DB reelle `arac`, cleanup via `key LIKE 'test-%'` (conftest). mock_embed actif
(pas d'appel OpenAI). Node seede FK-valide : test-node.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.schemas.atom import AtomRead
from app.schemas.scope import Scope

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL_ADMIN"),
    reason="DB reelle requise",
)

SEED_NODE = "test-node"
AM_SCOPE = "outillage/automatisations"


def _agent_message_payload(key: str, value: str = "test agent_message f2a") -> dict:
    return {
        "kind": "agent_message",
        "scope": AM_SCOPE,
        "key": key,
        "value": value,
        "node_id": SEED_NODE,
        "source_ref": {"to": "claude-developer", "from": "claude-orchestrator"},
    }


# ---------------------------------------------------------------------------
# P1 — create_atom force archived (non-overrideable)
# ---------------------------------------------------------------------------


async def test_post_agent_message_is_archived(client, mock_embed) -> None:
    """POST kind=agent_message -> 201 et status='archived' (force serveur-side)."""
    r = await client.post("/v1/atoms", json=_agent_message_payload("test-f2a-am-archived"))
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "archived"


async def test_post_rejects_explicit_status_field(client, mock_embed) -> None:
    """POST avec un champ `status` -> 422 (AtomCreate model_config extra='forbid')."""
    payload = _agent_message_payload("test-f2a-am-statusfield")
    payload["status"] = "active"
    r = await client.post("/v1/atoms", json=payload)
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# S2 — update_atom PATCH ne peut pas reactiver un agent_message archived
# ---------------------------------------------------------------------------


async def test_patch_cannot_reactivate_agent_message(client, mock_embed) -> None:
    """PATCH {status:'active'} sur un agent_message archived -> 422, message clair."""
    create = await client.post("/v1/atoms", json=_agent_message_payload("test-f2a-am-reactivate"))
    assert create.status_code == 201, create.text
    atom_id = create.json()["id"]
    assert create.json()["status"] == "archived"

    patch = await client.patch(f"/v1/atoms/{atom_id}", json={"status": "active"})
    assert patch.status_code == 422, patch.text
    assert "agent_message cannot be reactivated" in patch.text

    # toujours archived apres la tentative
    after = await client.get(f"/v1/atoms/{atom_id}")
    assert after.status_code == 200
    assert after.json()["status"] == "archived"


# ---------------------------------------------------------------------------
# Transport — GET par id fonctionne sur un agent_message archived
# ---------------------------------------------------------------------------


async def test_get_archived_agent_message_works(client, mock_embed) -> None:
    """GET /{id} d'un agent_message archived -> 200 (transport bus intact)."""
    create = await client.post("/v1/atoms", json=_agent_message_payload("test-f2a-am-get"))
    assert create.status_code == 201, create.text
    atom_id = create.json()["id"]
    r = await client.get(f"/v1/atoms/{atom_id}")
    assert r.status_code == 200
    assert r.json()["id"] == atom_id
    assert r.json()["status"] == "archived"


# ---------------------------------------------------------------------------
# Retrieval — recall n'inclut jamais un agent_message archived
# ---------------------------------------------------------------------------


async def test_recall_excludes_archived_agent_message(client, mock_embed) -> None:
    """recall (filtre status='active') ne retourne pas l'agent_message archived."""
    create = await client.post(
        "/v1/atoms",
        json=_agent_message_payload("test-f2a-am-recall", value="test f2a recall exclusion zztoken"),
    )
    assert create.status_code == 201, create.text
    atom_id = create.json()["id"]

    r = await client.post("/v1/atoms/recall", json={"query": "zztoken", "k": 25})
    assert r.status_code == 200, r.text
    returned_ids = {x["id"] for x in r.json()}
    assert atom_id not in returned_ids
    # et aucun agent_message dans les resultats
    assert all(x["kind"] != "agent_message" for x in r.json())


# ---------------------------------------------------------------------------
# Anti-regression serialisation — AtomRead accepte les 45 scopes
# ---------------------------------------------------------------------------


def test_atomread_serializes_all_45_scopes() -> None:
    """AtomRead doit serialiser CHAQUE scope de l'enum (45), incl. v0.15 Phase A.

    Reproduit le scenario du bug 500 : un atome re-roote vers un scope absent
    de l'enum faisait planter la validation AtomRead. Tous les scopes utilises
    en base doivent etre dans l'enum.
    """
    now = datetime.now(timezone.utc)
    base = {
        "kind": "note",
        "key": "test-serialize",
        "value": "x",
        "id": uuid4(),
        "desc_hash": "0" * 64,
        "status": "active",
        "superseded_by": None,
        "confidence": "producer",
        "audit_source": None,
        "node_id": SEED_NODE,
        "session_id": None,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    assert len(Scope) == 45
    for s in Scope:
        AtomRead.model_validate({**base, "scope": s.value})
