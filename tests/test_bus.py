"""Tests bus inter-agent — Phase B triade.

Couverture :
- E2E send→subscribe : A POST agent_message vers B, B reçoit l'atome via LISTEN
  en moins de 1 seconde (critère 'Done' du plan Phase B).
- NOTIFY trigger conditional : un atome agent_message SANS source_ref.to
  n'émet pas de NOTIFY.
- NOTIFY trigger conditional : un atome NON agent_message (kind=note) avec
  source_ref.to ne déclenche pas le trigger.
- Channel sanitization : node_id avec `-` se traduit en channel avec `_`.

Stratégie : send() utilise l'AsyncClient pytest sur l'app FastAPI (mock_embed
patché). subscribe() utilise psycopg AsyncConnection directe sur la BDD.
Les deux conversent via le trigger PG (vraie BDD, pas mock).
"""

from __future__ import annotations

import asyncio
import os
import time

import psycopg
import pytest

from agents.lib import bus

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL_ADMIN"),
    reason="DB reelle requise",
)


@pytest.mark.asyncio
async def test_bus_send_receive_under_1s(client, mock_embed, monkeypatch):
    """A→B en moins d'1s. Critère 'Done' Phase B."""
    # Forcer l'URL API du bus.send() à pointer vers le testClient (impossible
    # avec httpx.AsyncClient direct — on patch send() pour qu'il utilise le
    # client de test à la place de httpx.AsyncClient().
    async def _test_send(*, from_node, to_node, value, metadata=None, timeout_sec=5.0):
        import secrets as _s
        source_ref = {"to": to_node, "from": from_node}
        if metadata:
            source_ref.update(metadata)
        payload = {
            "kind": "agent_message",
            "scope": "outillage/automatisations",
            "key": f"test-msg-{from_node}-to-{to_node}-{_s.token_hex(4)}",
            "value": value,
            "node_id": from_node,
            "source_ref": source_ref,
        }
        r = await client.post("/v1/atoms", json=payload)
        r.raise_for_status()
        return r.json()
    monkeypatch.setattr(bus, "send", _test_send)

    # Override fetch_atom pour utiliser le testClient (sinon httpx direct loopback)
    async def _test_fetch(atom_id, timeout_sec=5.0):
        r = await client.get(f"/v1/atoms/{atom_id}")
        r.raise_for_status()
        return r.json()
    monkeypatch.setattr(bus, "fetch_atom", _test_fetch)

    # 1. Lancer le subscribe en background. Premier message → on l'attrape.
    received: list[dict] = []
    stop_event = asyncio.Event()

    async def handler(atom):
        received.append(atom)
        stop_event.set()

    sub_task = asyncio.create_task(
        bus.subscribe("claude-developer", handler, stop_event=stop_event)
    )
    # Petit yield pour laisser le LISTEN s'établir avant le SEND.
    await asyncio.sleep(0.2)

    t0 = time.perf_counter()
    sent = await bus.send(
        from_node="claude-orchestrator",
        to_node="claude-developer",
        value="test-ping-2026-05-18",
    )

    # Attente borne haute 1.5s pour absorber CI lent ; le critère "< 1s"
    # est mesuré dans `elapsed` ci-dessous.
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=1.5)
    except asyncio.TimeoutError:
        sub_task.cancel()
        pytest.fail("subscribe n'a pas reçu le NOTIFY dans la fenêtre 1.5s")

    elapsed = time.perf_counter() - t0
    sub_task.cancel()
    try:
        await sub_task
    except asyncio.CancelledError:
        pass

    assert len(received) == 1
    assert received[0]["id"] == sent["id"]
    assert received[0]["value"] == "test-ping-2026-05-18"
    assert received[0]["source_ref"]["to"] == "claude-developer"
    assert received[0]["source_ref"]["from"] == "claude-orchestrator"

    # Critère Done Phase B : < 1s end-to-end
    assert elapsed < 1.0, f"latence E2E = {elapsed:.3f}s > 1s (critère Done Phase B)"


@pytest.mark.asyncio
async def test_trigger_no_notify_without_source_ref_to(client, mock_embed):
    """agent_message sans source_ref.to → trigger ne fait rien (RETURN NEW)."""
    # On subscribe sur un canal qui ne devrait recevoir aucun NOTIFY,
    # puis on insère un agent_message sans `to` dans source_ref.
    dsn = os.environ["DATABASE_URL_APP"]
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        await conn.execute("LISTEN agent_inbox_claude_developer")

        # POST atome sans source_ref.to
        r = await client.post(
            "/v1/atoms",
            json={
                "kind": "agent_message",
                "scope": "outillage/automatisations",
                "key": f"test-no-to-{os.urandom(4).hex()}",
                "value": "agent_message sans destinataire",
                "node_id": "claude-orchestrator",
                "source_ref": {"misc": "no-to-here"},
            },
        )
        assert r.status_code == 201

        # Attendre 0.3s pour laisser un éventuel NOTIFY arriver
        await asyncio.sleep(0.3)

        # Aucune notification ne devrait être en attente
        gen = conn.notifies()
        await asyncio.sleep(0)
        # On consomme avec un timeout court — rien ne doit arriver
        try:
            n = await asyncio.wait_for(gen.__anext__(), timeout=0.2)
            await gen.aclose()
            pytest.fail(f"NOTIFY inattendu reçu : {n.payload}")
        except asyncio.TimeoutError:
            pass  # OK, rien reçu
        await gen.aclose()


@pytest.mark.asyncio
async def test_trigger_no_notify_for_non_agent_message_kind(client, mock_embed):
    """kind=note avec source_ref.to → trigger ne fait rien (filtre kind)."""
    dsn = os.environ["DATABASE_URL_APP"]
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        await conn.execute("LISTEN agent_inbox_claude_developer")

        r = await client.post(
            "/v1/atoms",
            json={
                "kind": "note",
                "scope": "outillage/automatisations",
                "key": f"test-note-with-to-{os.urandom(4).hex()}",
                "value": "note avec source_ref.to — ne doit pas déclencher NOTIFY",
                "node_id": "test-node",
                "source_ref": {"to": "claude-developer"},
            },
        )
        assert r.status_code == 201

        await asyncio.sleep(0.3)
        gen = conn.notifies()
        try:
            n = await asyncio.wait_for(gen.__anext__(), timeout=0.2)
            await gen.aclose()
            pytest.fail(f"NOTIFY inattendu reçu pour kind=note : {n.payload}")
        except asyncio.TimeoutError:
            pass
        await gen.aclose()


def test_channel_sanitization():
    """node_id avec `-` → channel avec `_` (sanitization psycopg LISTEN safe)."""
    assert bus._channel_for("claude-orchestrator") == "agent_inbox_claude_orchestrator"
    assert bus._channel_for("codex-auditor") == "agent_inbox_codex_auditor"
    assert bus._channel_for("simple") == "agent_inbox_simple"
    assert bus._channel_for("a-b-c-d") == "agent_inbox_a_b_c_d"
