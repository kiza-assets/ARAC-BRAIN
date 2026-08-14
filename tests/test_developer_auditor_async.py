"""Tests structure async des agents developer + auditor — Phase D.0 plumbing.

Couverture :
- Les modules exposent `amain` coroutine + `_handle_incoming` coroutine.
- Le node_id privé est cohérent avec le systemd unit.
- Le handler stub ne lève pas et ne retourne rien (log-only, pas de reply).

Pas de test de la boucle complète (asyncio.run de amain) — ça nécessite
BDD live et systemd, c'est couvert par le déploiement live + heartbeats
en arac.nodes_heartbeat_history.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from agents.auditor import main as auditor_main
from agents.developer import main as developer_main


def test_developer_node_id_constant():
    assert developer_main._NODE_ID == "claude-developer"


def test_auditor_node_id_constant():
    assert auditor_main._NODE_ID == "codex-auditor"


def test_developer_amain_is_coroutine():
    assert inspect.iscoroutinefunction(developer_main.amain)


def test_auditor_amain_is_coroutine():
    assert inspect.iscoroutinefunction(auditor_main.amain)


def test_developer_handler_is_coroutine():
    assert inspect.iscoroutinefunction(developer_main._handle_incoming)


def test_auditor_handler_is_coroutine():
    assert inspect.iscoroutinefunction(auditor_main._handle_incoming)


@pytest.mark.asyncio
async def test_developer_handler_stub_no_raise():
    atom = {
        "id": "00000000-0000-0000-0000-000000000001",
        "value": "test message",
        "source_ref": {"from": "claude-orchestrator"},
    }
    result = await developer_main._handle_incoming(atom)
    assert result is None


@pytest.mark.asyncio
async def test_auditor_handler_stub_no_raise():
    atom = {
        "id": "00000000-0000-0000-0000-000000000002",
        "value": "test mission_proposal",
        "source_ref": {"from": "claude-orchestrator"},
    }
    result = await auditor_main._handle_incoming(atom)
    assert result is None


@pytest.mark.asyncio
async def test_developer_handler_handles_missing_source_ref():
    """source_ref absent ne doit pas casser le handler stub."""
    atom = {"id": "x", "value": "y"}
    result = await developer_main._handle_incoming(atom)
    assert result is None


@pytest.mark.asyncio
async def test_auditor_handler_handles_missing_value():
    """value absente ne doit pas casser le handler stub."""
    atom = {"id": "x", "source_ref": {"from": "claude-orchestrator"}}
    result = await auditor_main._handle_incoming(atom)
    assert result is None
