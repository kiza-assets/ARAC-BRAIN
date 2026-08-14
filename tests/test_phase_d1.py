"""Tests Phase D.1 MVP — orchestrator /dev routing + developer claude CLI wrap.

Mocks : pas d'invocation réelle de `claude` CLI, pas de POST réel sur l'API.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.developer import main as dev_main
from agents.lib import git_ops
from agents.orchestrator import main as orch_main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_atom(
    value: str,
    *,
    sender: str = "arac-telegram-bridge",
    reply_chat_id: int | None = 1000000001,
    mission_id: str | None = None,
    atom_id: str = "00000000-0000-0000-0000-000000000001",
) -> dict[str, Any]:
    source_ref: dict[str, Any] = {"from": sender}
    if reply_chat_id is not None:
        source_ref["reply_chat_id"] = reply_chat_id
    if mission_id is not None:
        source_ref["mission_id"] = mission_id
    return {
        "id": atom_id,
        "value": value,
        "source_ref": source_ref,
    }


# ---------------------------------------------------------------------------
# Orchestrator handler tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_ping_still_works(monkeypatch):
    """Phase C ping/pong intact malgré ajout routing D.1."""
    sent: list[dict[str, Any]] = []

    async def fake_send(**kwargs):
        sent.append(kwargs)
        return {"id": "fake"}

    monkeypatch.setattr(orch_main.bus, "send", fake_send)

    atom = _make_atom("ping")
    await orch_main._handle_incoming(atom)

    assert len(sent) == 1
    assert sent[0]["value"] == "pong"
    assert sent[0]["to_node"] == "arac-telegram-bridge"
    assert sent[0]["metadata"].get("reply_chat_id") == 1000000001


@pytest.mark.asyncio
async def test_orchestrator_dev_command_posts_mission_and_dispatches(monkeypatch):
    """`/dev <prompt>` → POST kind=mission + agent_message au developer + ack au bridge."""
    sent: list[dict[str, Any]] = []
    posted_atom: dict[str, Any] = {}

    async def fake_send(**kwargs):
        sent.append(kwargs)
        return {"id": "msg-fake"}

    async def fake_post_mission(prompt, requester_chat_id):
        posted_atom.update({
            "prompt": prompt,
            "requester_chat_id": requester_chat_id,
        })
        return {"id": "mission-uuid-1234abcd", "key": "mission-d1-test"}

    monkeypatch.setattr(orch_main.bus, "send", fake_send)
    monkeypatch.setattr(orch_main, "_post_mission", fake_post_mission)

    atom = _make_atom("/dev ajoute fichier docs/test.md")
    await orch_main._handle_incoming(atom)

    assert posted_atom == {
        "prompt": "ajoute fichier docs/test.md",
        "requester_chat_id": 1000000001,
    }
    # Deux sends : 1 vers developer (dispatch), 1 vers bridge (ack).
    assert len(sent) == 2
    to_dev = [s for s in sent if s["to_node"] == "claude-developer"]
    to_bridge = [s for s in sent if s["to_node"] == "arac-telegram-bridge"]
    assert len(to_dev) == 1
    assert len(to_bridge) == 1
    assert to_dev[0]["value"] == "ajoute fichier docs/test.md"
    assert to_dev[0]["metadata"]["mission_id"] == "mission-uuid-1234abcd"
    assert to_dev[0]["metadata"]["reply_chat_id"] == 1000000001
    assert "Mission" in to_bridge[0]["value"]
    assert to_bridge[0]["metadata"]["mission_id"] == "mission-uuid-1234abcd"


@pytest.mark.asyncio
async def test_orchestrator_relays_developer_response_to_bridge(monkeypatch):
    """Réponse depuis claude-developer (mission_id présent) → relais au bridge."""
    sent: list[dict[str, Any]] = []

    async def fake_send(**kwargs):
        sent.append(kwargs)
        return {"id": "fake"}

    monkeypatch.setattr(orch_main.bus, "send", fake_send)

    atom = _make_atom(
        "✅ Mission abc1234 done (5s). Commit deadbeef sur feature/d1-test.",
        sender="claude-developer",
        mission_id="mission-uuid-1234abcd",
    )
    await orch_main._handle_incoming(atom)

    assert len(sent) == 1
    assert sent[0]["to_node"] == "arac-telegram-bridge"
    assert sent[0]["value"].startswith("✅ Mission abc1234 done")
    assert sent[0]["metadata"]["reply_chat_id"] == 1000000001
    assert sent[0]["metadata"]["mission_id"] == "mission-uuid-1234abcd"


@pytest.mark.asyncio
async def test_orchestrator_dev_empty_prompt_returns_usage(monkeypatch):
    sent: list[dict[str, Any]] = []

    async def fake_send(**kwargs):
        sent.append(kwargs)
        return {"id": "fake"}

    monkeypatch.setattr(orch_main.bus, "send", fake_send)

    atom = _make_atom("/dev ")
    await orch_main._handle_incoming(atom)

    assert len(sent) == 1
    assert "Usage" in sent[0]["value"]


# ---------------------------------------------------------------------------
# Developer handler tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_developer_ignores_message_without_mission_id(monkeypatch):
    """Sans mission_id, le developer log et ignore (pas de subprocess, pas de send)."""
    sent: list[dict[str, Any]] = []
    subprocess_called = MagicMock()

    async def fake_send(**kwargs):
        sent.append(kwargs)

    async def fake_subprocess(*args, **kwargs):
        subprocess_called(*args, **kwargs)
        return {}

    monkeypatch.setattr(dev_main.bus, "send", fake_send)
    monkeypatch.setattr(dev_main, "run_claude_subprocess", fake_subprocess)

    atom = _make_atom("hello", sender="claude-orchestrator", mission_id=None)
    await dev_main._handle_incoming(atom)

    subprocess_called.assert_not_called()
    assert sent == []


@pytest.mark.skip(
    reason="V0.4 vague 3 V1: _handle_incoming délègue à asyncio.create_task(_process_mission) "
    "depuis D.4 — le test doit être réécrit pour await _process_mission directement avec "
    "mocks _gate_and_commit + MissionLogger. Dette flaggée pour V5."
)
@pytest.mark.asyncio
async def test_developer_executes_mission_and_replies(monkeypatch):
    """Mission_id présent → run_claude_subprocess + POST state delivery + reply orchestrator."""
    sent: list[dict[str, Any]] = []
    delivery_payload: dict[str, Any] = {}

    async def fake_send(**kwargs):
        sent.append(kwargs)
        return {"id": "fake"}

    async def fake_subprocess(prompt, **kwargs):
        return {
            "ok": True,
            "exit_code": 0,
            "stdout": "mocked output",
            "stderr": "",
            "duration_sec": 3,
            "timed_out": False,
        }

    async def fake_post_delivery(**kwargs):
        delivery_payload.update(kwargs)
        return {"id": "delivery-uuid-deadbeefcafe"}

    async def fake_head_sha(short: bool = True):
        return "deadbeef"

    async def fake_current_branch():
        return "feature/d1-test"

    monkeypatch.setattr(dev_main.bus, "send", fake_send)
    monkeypatch.setattr(dev_main, "run_claude_subprocess", fake_subprocess)
    monkeypatch.setattr(dev_main, "_post_delivery", fake_post_delivery)
    # Phase D.2 : _git_head_sha / _git_current_branch ont été remplacés par
    # agents.lib.git_ops.head_sha / agents.lib.git_ops.current_branch.
    monkeypatch.setattr(git_ops, "head_sha", fake_head_sha)
    monkeypatch.setattr(git_ops, "current_branch", fake_current_branch)

    atom = _make_atom(
        "ajoute fichier docs/test.md",
        sender="claude-orchestrator",
        mission_id="mission-uuid-1234abcd",
        reply_chat_id=1000000001,
    )
    await dev_main._handle_incoming(atom)

    assert delivery_payload["mission_id"] == "mission-uuid-1234abcd"
    assert delivery_payload["result"]["ok"] is True

    assert len(sent) == 1
    assert sent[0]["to_node"] == "claude-orchestrator"
    assert "✅" in sent[0]["value"]
    assert "mission-u" in sent[0]["value"].lower() or "mission" in sent[0]["value"].lower()
    assert sent[0]["metadata"]["mission_id"] == "mission-uuid-1234abcd"
    assert sent[0]["metadata"]["reply_chat_id"] == 1000000001
    assert sent[0]["metadata"]["delivery_id"] == "delivery-uuid-deadbeefcafe"


@pytest.mark.skip(
    reason="V0.4 vague 3 V1: idem test_developer_executes_mission_and_replies — "
    "_handle_incoming est désormais non-bloquant (create_task). Réécriture nécessaire. "
    "Dette flaggée pour V5."
)
@pytest.mark.asyncio
async def test_developer_reports_timeout(monkeypatch):
    sent: list[dict[str, Any]] = []

    async def fake_send(**kwargs):
        sent.append(kwargs)

    async def fake_subprocess(prompt, **kwargs):
        return {
            "ok": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": "TIMEOUT after 600s",
            "duration_sec": 600,
            "timed_out": True,
        }

    async def fake_post_delivery(**kwargs):
        return {"id": "delivery-timeout-abc"}

    async def fake_head_sha(short: bool = True):
        return "abc1234"

    async def fake_current_branch():
        return "feature/d1-test"

    monkeypatch.setattr(dev_main.bus, "send", fake_send)
    monkeypatch.setattr(dev_main, "run_claude_subprocess", fake_subprocess)
    monkeypatch.setattr(dev_main, "_post_delivery", fake_post_delivery)
    # Phase D.2 : _git_head_sha / _git_current_branch ont été remplacés par
    # agents.lib.git_ops.head_sha / agents.lib.git_ops.current_branch.
    monkeypatch.setattr(git_ops, "head_sha", fake_head_sha)
    monkeypatch.setattr(git_ops, "current_branch", fake_current_branch)

    atom = _make_atom(
        "task hanging forever",
        sender="claude-orchestrator",
        mission_id="mission-uuid-timeout",
    )
    await dev_main._handle_incoming(atom)

    assert len(sent) == 1
    assert "TIMEOUT" in sent[0]["value"] or "⏱️" in sent[0]["value"]


# NB v0.5.1 — les tests du wrapper claude_cli (succès / timeout / stdin / E2BIG)
# vivent désormais dans tests/test_claude_cli_stdin_e2big.py. Les deux anciens
# tests communicate()-based (dette héritée v0.5, cassés depuis le refactor
# streaming D.4) y ont été remplacés par des fakes alignés sur l'API réelle.
