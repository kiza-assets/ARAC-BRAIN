"""Tests bridge Telegram — Phase C triade.

Couverture (sans appel réel à api.telegram.org) :
- _parse_chat_ids : "12345" → {12345}, "12345,67890" → {12345, 67890}, "" → ∅
- _process_update : chat whitelist → bus.send appelé avec to=claude-orchestrator
  et metadata.reply_chat_id propagé.
- _process_update : chat non-whitelist → bus.send PAS appelé (log unauthorized).
- _process_update : update sans .message.text → ignoré silencieusement.
- outbound_handler : atom avec reply_chat_id → POST sendMessage avec chat_id+text.
- outbound_handler : atom sans reply_chat_id → ne POST rien (log no_chat_id).
- _config_or_raise : TOKEN ou CHAT_IDS manquant → RuntimeError au boot.

Stratégie : on patch agents.lib.bus.send et on instrumente httpx via
unittest.mock.AsyncMock. Pas de dépendance respx/pytest-httpx ajoutée.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.telegram_bridge import main as bridge


def test_parse_chat_ids_single():
    assert bridge._parse_chat_ids("12345") == {12345}


def test_parse_chat_ids_multiple():
    assert bridge._parse_chat_ids("12345, 67890,42") == {12345, 67890, 42}


def test_parse_chat_ids_empty():
    assert bridge._parse_chat_ids("") == set()
    assert bridge._parse_chat_ids("   ") == set()


def test_config_or_raise_missing_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "12345")
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        bridge._config_or_raise()


def test_config_or_raise_missing_chat_ids(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake:token")
    monkeypatch.delenv("TELEGRAM_ALLOWED_CHAT_IDS", raising=False)
    with pytest.raises(RuntimeError, match="TELEGRAM_ALLOWED_CHAT_IDS"):
        bridge._config_or_raise()


def test_config_or_raise_ok(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake:token")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "12345,67890")
    token, chat_ids, poll_interval, poll_timeout = bridge._config_or_raise()
    assert token == "fake:token"
    assert chat_ids == {12345, 67890}
    assert poll_interval == 25.0  # default
    assert poll_timeout == 30.0


@pytest.mark.asyncio
async def test_process_update_whitelist_routes_to_orchestrator(monkeypatch):
    """Chat whitelist → bus.send vers orchestrator avec reply_chat_id."""
    sent = []

    async def fake_send(*, from_node, to_node, value, metadata=None, **kwargs):
        sent.append({"from_node": from_node, "to_node": to_node, "value": value, "metadata": metadata})
        return {"id": "fake-atom-id"}

    monkeypatch.setattr(bridge.bus, "send", fake_send)

    update = {
        "update_id": 100,
        "message": {
            "message_id": 1,
            "from": {"id": 12345, "first_name": "Alice"},
            "chat": {"id": 12345, "type": "private"},
            "date": 1700000000,
            "text": "ping",
        },
    }

    await bridge._process_update(update, allowed_chat_ids={12345})

    assert len(sent) == 1
    assert sent[0]["from_node"] == "arac-telegram-bridge"
    assert sent[0]["to_node"] == "claude-orchestrator"
    assert sent[0]["value"] == "ping"
    assert sent[0]["metadata"]["reply_chat_id"] == 12345
    assert sent[0]["metadata"]["command"] == "ping"


@pytest.mark.asyncio
async def test_process_update_unauthorized_silent(monkeypatch):
    """Chat non-whitelist → bus.send PAS appelé."""
    send_mock = AsyncMock()
    monkeypatch.setattr(bridge.bus, "send", send_mock)

    update = {
        "update_id": 101,
        "message": {
            "message_id": 2,
            "from": {"id": 99999, "first_name": "Inconnu"},
            "chat": {"id": 99999, "type": "private"},
            "date": 1700000000,
            "text": "go phase 6",
        },
    }

    await bridge._process_update(update, allowed_chat_ids={12345})

    send_mock.assert_not_called()


@pytest.mark.asyncio
async def test_process_update_no_text_ignored(monkeypatch):
    """Update sans message ou sans .text (sticker, photo) → ignoré."""
    send_mock = AsyncMock()
    monkeypatch.setattr(bridge.bus, "send", send_mock)

    update_no_message = {"update_id": 102}
    update_no_text = {
        "update_id": 103,
        "message": {
            "message_id": 3,
            "chat": {"id": 12345, "type": "private"},
            "date": 1700000000,
            # pas de "text"
        },
    }

    await bridge._process_update(update_no_message, allowed_chat_ids={12345})
    await bridge._process_update(update_no_text, allowed_chat_ids={12345})

    send_mock.assert_not_called()


@pytest.mark.asyncio
async def test_outbound_handler_with_chat_id_posts_sendmessage(monkeypatch):
    """atom avec reply_chat_id → POST sendMessage avec body correct."""
    posted_url = None
    posted_json = None

    class FakeResponse:
        def raise_for_status(self):
            pass

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, json=None):
            nonlocal posted_url, posted_json
            posted_url = url
            posted_json = json
            return FakeResponse()

    def fake_async_client(*args, **kwargs):
        return FakeClient()

    monkeypatch.setattr(bridge.httpx, "AsyncClient", fake_async_client)

    atom = {
        "id": "fake-atom-id",
        "value": "pong",
        "source_ref": {"reply_chat_id": 12345, "from": "claude-orchestrator"},
    }

    await bridge.outbound_handler("fake:token", atom)

    assert posted_url == "https://api.telegram.org/botfake:token/sendMessage"
    assert posted_json == {"chat_id": 12345, "text": "pong"}


@pytest.mark.asyncio
async def test_outbound_handler_without_chat_id_skips(monkeypatch):
    """atom sans reply_chat_id → ne POST rien."""
    called = False

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            nonlocal called
            called = True

    monkeypatch.setattr(bridge.httpx, "AsyncClient", lambda *a, **k: FakeClient())

    atom = {
        "id": "fake-atom-id",
        "value": "pong",
        "source_ref": {"from": "claude-orchestrator"},  # pas de reply_chat_id
    }

    await bridge.outbound_handler("fake:token", atom)

    assert called is False
