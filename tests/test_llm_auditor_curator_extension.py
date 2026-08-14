"""Tests extension auditor LLM curator-ciblée — Vague 2 I9 (Q6 ciblé).

Cible : extension ajoutée à `agents/lib/llm_auditor.py` + nouveau handler
`_handle_curator_atom_audit_request` dans `agents/auditor/main.py`.

Q6 ciblé : gate auditeur LLM cross-provider (GPT-5.5) UNIQUEMENT pour atomes
extraits par curator avec kind STRICT (decision, gotcha, killed). Pas de
gate sur :
  - atomes STANDARD (pattern/state/todo/alert) extraits par curator
  - atomes LARGE (idea/insight/...) extraits par curator
  - atomes posés par d'autres nodes (claude-developer, codex-auditor, ...)

Stratégie : mock httpx.AsyncClient + bus.send (même pattern que
test_llm_auditor.py v0.4 Phase E).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from agents.auditor import main as auditor_main
from agents.lib import llm_auditor


# ===========================================================================
# Tests unitaires `should_gate_atom_curator` — pré-filtre Q6
# ===========================================================================


def test_should_gate_curator_decision_kind_true():
    """Atome arac-curator + kind=decision → gate (Q6 ciblé STRICT)."""
    atom = {
        "node_id": "arac-curator",
        "kind": "decision",
        "scope": "travail/strategie",
        "key": "bascule-capi",
        "value": "...",
    }
    assert llm_auditor.should_gate_atom_curator(atom) is True


def test_should_gate_curator_gotcha_kind_true():
    """Atome arac-curator + kind=gotcha → gate."""
    atom = {"node_id": "arac-curator", "kind": "gotcha", "scope": "outillage/assistants",
            "key": "x", "value": "y"}
    assert llm_auditor.should_gate_atom_curator(atom) is True


def test_should_gate_curator_killed_kind_true():
    """Atome arac-curator + kind=killed → gate."""
    atom = {"node_id": "arac-curator", "kind": "killed", "scope": "outillage/assistants",
            "key": "x", "value": "y"}
    assert llm_auditor.should_gate_atom_curator(atom) is True


def test_should_gate_curator_idea_kind_false():
    """Atome arac-curator + kind=idea (LARGE) → PAS de gate (Q6 ciblé)."""
    atom = {"node_id": "arac-curator", "kind": "idea", "scope": "travail/strategie",
            "key": "x", "value": "y"}
    assert llm_auditor.should_gate_atom_curator(atom) is False


def test_should_gate_curator_pattern_kind_false():
    """Atome arac-curator + kind=pattern (STANDARD) → PAS de gate."""
    atom = {"node_id": "arac-curator", "kind": "pattern", "scope": "outillage/assistants",
            "key": "x", "value": "y"}
    assert llm_auditor.should_gate_atom_curator(atom) is False


def test_should_gate_curator_alert_kind_false():
    """Atome arac-curator + kind=alert → PAS de gate (Q6 ciblé STRICT only)."""
    atom = {"node_id": "arac-curator", "kind": "alert", "scope": "outillage/infrastructure",
            "key": "x", "value": "y"}
    assert llm_auditor.should_gate_atom_curator(atom) is False


def test_should_gate_developer_decision_kind_false():
    """Atome claude-developer + kind=decision → PAS de gate (Q6 = curator only)."""
    atom = {"node_id": "claude-developer", "kind": "decision",
            "scope": "travail/strategie", "key": "x", "value": "y"}
    assert llm_auditor.should_gate_atom_curator(atom) is False


def test_should_gate_auditor_decision_kind_false():
    """Atome codex-auditor + kind=decision → PAS de gate."""
    atom = {"node_id": "codex-auditor", "kind": "decision",
            "scope": "travail/strategie", "key": "x", "value": "y"}
    assert llm_auditor.should_gate_atom_curator(atom) is False


def test_should_gate_malformed_atom_false():
    """Atome mal-formé / vide → False (fail-safe, pas d'appel LLM)."""
    assert llm_auditor.should_gate_atom_curator({}) is False
    assert llm_auditor.should_gate_atom_curator({"node_id": "arac-curator"}) is False
    assert llm_auditor.should_gate_atom_curator({"kind": "decision"}) is False
    assert llm_auditor.should_gate_atom_curator(None) is False  # type: ignore[arg-type]
    assert llm_auditor.should_gate_atom_curator("not a dict") is False  # type: ignore[arg-type]


# ===========================================================================
# Helpers pour tests intégration handler
# ===========================================================================


class _MockResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200, text: str = ""):
        self._payload = payload
        self.status_code = status_code
        self.text = text or json.dumps(payload)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"status={self.status_code}",
                request=httpx.Request("POST", "http://test"),
                response=httpx.Response(self.status_code),
            )

    def json(self) -> dict[str, Any]:
        return self._payload


class _MockAsyncClient:
    """Routeur d'URLs (cohérent avec test_llm_auditor.py)."""

    def __init__(
        self,
        *,
        openai_response: _MockResponse | Exception | list,
        api_response: _MockResponse,
        foundations_response: _MockResponse | Exception | None = None,
        calls_log: list[dict[str, Any]],
    ):
        self._openai = openai_response
        self._api = api_response
        self._foundations = foundations_response
        self._calls = calls_log
        if isinstance(openai_response, list):
            self._openai_queue: list | None = list(openai_response)
        else:
            self._openai_queue = None

    async def __aenter__(self) -> "_MockAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def post(self, url: str, json: dict[str, Any] | None = None, **kwargs: Any) -> _MockResponse:
        self._calls.append({"method": "POST", "url": url, "json": json})
        if "api.openai.com" in url:
            return self._serve_openai()
        return self._api

    async def get(self, url: str, **kwargs: Any) -> _MockResponse:
        self._calls.append({"method": "GET", "url": url})
        if "foundations" in url:
            if self._foundations is None:
                return _MockResponse([])
            if isinstance(self._foundations, Exception):
                raise self._foundations
            return self._foundations
        return self._api

    def _serve_openai(self) -> _MockResponse:
        target = self._openai_queue.pop(0) if self._openai_queue else self._openai
        if isinstance(target, Exception):
            raise target
        return target


def _openai_chat_response(
    *,
    verdict: str = "approve",
    reasons: list[str] | None = None,
    confidence: float = 0.9,
) -> _MockResponse:
    content = json.dumps({
        "verdict": verdict,
        "reasons": reasons or [],
        "confidence": confidence,
    })
    return _MockResponse({
        "choices": [{"message": {"role": "assistant", "content": content}}],
    })


def _install_clients(
    monkeypatch: pytest.MonkeyPatch,
    *,
    openai_response: _MockResponse | Exception | list,
    api_response: _MockResponse | None = None,
    foundations_response: _MockResponse | Exception | None = None,
) -> list[dict[str, Any]]:
    if api_response is None:
        api_response = _MockResponse({"id": "verdict-atom-curator-mocked"})
    calls: list[dict[str, Any]] = []

    def _factory(*args: Any, **kwargs: Any) -> _MockAsyncClient:
        return _MockAsyncClient(
            openai_response=openai_response,
            api_response=api_response,
            foundations_response=foundations_response,
            calls_log=calls,
        )

    monkeypatch.setattr(llm_auditor.httpx, "AsyncClient", _factory)
    monkeypatch.setattr(auditor_main.httpx, "AsyncClient", _factory)
    return calls


def _make_audit_request_atom(
    *,
    proposed_node_id: str = "arac-curator",
    proposed_kind: str = "decision",
    proposed_value: str = "Décision de bascule CAPI Shopify.",
    proposed_scope: str = "travail/strategie",
    proposed_key: str = "test-bascule-capi",
    raw_id: str = "11111111-2222-3333-4444-555555555555",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construit un agent_message bus type=curator_atom_audit_request."""
    proposed = {
        "node_id": proposed_node_id,
        "kind": proposed_kind,
        "scope": proposed_scope,
        "key": proposed_key,
        "value": proposed_value,
        "tags": ["test", "i9"],
        "source_ref": {"curator_raw_id": raw_id, "message_index": 0},
        "audit_source": "curator_extraction",
        "confidence": "curator_strict",
    }
    if extra:
        proposed.update(extra)
    return {
        "id": "audit-req-atom-id",
        "value": "curator_atom_audit_request",
        "source_ref": {
            "type": "curator_atom_audit_request",
            "curator_raw_id": raw_id,
            "proposed_atom": proposed,
            "reply_to": "arac-curator",
        },
    }


@pytest.fixture(autouse=True)
def _setup_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key-for-mock-only")
    monkeypatch.setenv("ARAC_AUDITOR_LLM_ENABLED", "true")
    monkeypatch.setenv("ARAC_AUDITOR_LLM_MODEL", "gpt-5.5-turbo")
    monkeypatch.setenv("ARAC_AUDITOR_LLM_TIMEOUT_SEC", "30")
    monkeypatch.setenv("ARAC_AUDITOR_LLM_FAIL_MODE", "open")


@pytest.fixture
def _fake_bus_send(monkeypatch):
    sent: list[dict[str, Any]] = []

    async def fake_send(**kwargs):
        sent.append(kwargs)
        return {"id": "send-ok"}

    monkeypatch.setattr(auditor_main.bus, "send", fake_send)
    return sent


async def _no_op_sleep(*args, **kwargs):
    return None


# ===========================================================================
# Tests intégration handler `_handle_curator_atom_audit_request`
# ===========================================================================


async def test_curator_decision_strict_gate_llm_called(monkeypatch, _fake_bus_send):
    """T-A — Atome posé par arac-curator kind=decision → gate LLM appelé.

    Mock LLM répond approve. Vérifie : 1 POST OpenAI, verdict=approved
    relayé au curator via bus, pas de POST kind=verdict_rejected.
    """
    calls = _install_clients(
        monkeypatch,
        openai_response=_openai_chat_response(verdict="approve", confidence=0.92),
    )

    atom = _make_audit_request_atom(proposed_kind="decision")
    await auditor_main._handle_curator_atom_audit_request(atom)

    # LLM a bien été appelé (Q6 STRICT déclenche gate)
    openai_calls = [c for c in calls if "api.openai.com" in c.get("url", "")]
    assert len(openai_calls) == 1, f"openai calls: {openai_calls}"

    # Bus message vers curator avec verdict approved
    curator_msgs = [s for s in _fake_bus_send if s.get("to_node") == "arac-curator"]
    assert len(curator_msgs) == 1
    assert curator_msgs[0]["metadata"]["verdict"] == "approved"

    # Aucun POST kind=verdict_rejected (verdict approuvé)
    api_posts = [c for c in calls if c["method"] == "POST"
                 and "/v1/atoms" in c.get("url", "")]
    assert api_posts == [], f"expected no atom POST on approve, got {api_posts}"


async def test_curator_idea_large_gate_llm_NOT_called(monkeypatch, _fake_bus_send):
    """T-B — Atome posé par arac-curator kind=idea (LARGE) → gate LLM PAS appelé.

    Q6 ciblé : seules les kinds STRICT déclenchent le gate. Pour idea,
    l'auditeur renvoie verdict=approved direct sans toucher OpenAI.
    """
    calls = _install_clients(
        monkeypatch,
        # Si LLM appelé, AssertionError remontera dans le handler.
        openai_response=AssertionError("LLM ne doit PAS être appelé pour kind=idea"),
    )

    atom = _make_audit_request_atom(proposed_kind="idea",
                                     proposed_scope="travail/strategie",
                                     proposed_key="test-idea-no-gate")
    await auditor_main._handle_curator_atom_audit_request(atom)

    openai_calls = [c for c in calls if "api.openai.com" in c.get("url", "")]
    assert openai_calls == [], (
        f"Q6 ciblé violation : LLM appelé sur kind=idea (LARGE). Calls: {openai_calls}"
    )

    # Verdict approved direct (skip_reason=not_strict_kind)
    curator_msgs = [s for s in _fake_bus_send if s.get("to_node") == "arac-curator"]
    assert len(curator_msgs) == 1
    assert curator_msgs[0]["metadata"]["verdict"] == "approved"
    assert curator_msgs[0]["metadata"].get("skip_reason") == "not_strict_kind"


async def test_developer_decision_gate_llm_NOT_called(monkeypatch, _fake_bus_send):
    """T-C — Atome posé par claude-developer kind=decision → gate LLM PAS appelé.

    Q6 ciblé = curator only. Le developer reste audité via commit_audit v0.4
    (sur commit_proposal), pas via ce nouveau hook.
    """
    calls = _install_clients(
        monkeypatch,
        openai_response=AssertionError("LLM ne doit PAS être appelé pour developer"),
    )

    atom = _make_audit_request_atom(
        proposed_node_id="claude-developer",
        proposed_kind="decision",
        proposed_scope="travail/strategie",
        proposed_key="test-dev-decision-no-gate",
    )
    await auditor_main._handle_curator_atom_audit_request(atom)

    openai_calls = [c for c in calls if "api.openai.com" in c.get("url", "")]
    assert openai_calls == [], (
        f"Q6 violation : gate LLM curator appelé sur claude-developer. {openai_calls}"
    )

    curator_msgs = [s for s in _fake_bus_send if s.get("to_node") == "arac-curator"]
    assert len(curator_msgs) == 1
    assert curator_msgs[0]["metadata"]["verdict"] == "approved"
    assert curator_msgs[0]["metadata"].get("skip_reason") == "not_strict_kind"


async def test_curator_gotcha_strict_gate_llm_called(monkeypatch, _fake_bus_send):
    """T-D — Atome posé par arac-curator kind=gotcha → gate LLM appelé.

    Couvre le 2e kind STRICT (decision + gotcha + killed = 3 kinds gated).
    """
    calls = _install_clients(
        monkeypatch,
        openai_response=_openai_chat_response(verdict="approve", confidence=0.88),
    )

    atom = _make_audit_request_atom(
        proposed_kind="gotcha",
        proposed_value="Attention : le pixel iOS 17 loupe les achats.",
        proposed_scope="travail/finance",
        proposed_key="test-gotcha-pixel-ios",
    )
    await auditor_main._handle_curator_atom_audit_request(atom)

    openai_calls = [c for c in calls if "api.openai.com" in c.get("url", "")]
    assert len(openai_calls) == 1

    curator_msgs = [s for s in _fake_bus_send if s.get("to_node") == "arac-curator"]
    assert curator_msgs[0]["metadata"]["verdict"] == "approved"


async def test_curator_decision_llm_reject_yields_rejected_and_telegram_alert(
    monkeypatch, _fake_bus_send
):
    """T-E — LLM reject sur curator decision → POST kind=verdict_rejected
    + alert Telegram bridge + bus.send verdict=rejected vers curator.
    """
    calls = _install_clients(
        monkeypatch,
        openai_response=_openai_chat_response(
            verdict="reject",
            reasons=["fabrication suspectée", "scope incohérent"],
            confidence=0.82,
        ),
    )

    atom = _make_audit_request_atom(proposed_kind="decision")
    await auditor_main._handle_curator_atom_audit_request(atom)

    # 1 appel OpenAI (le gate s'est déclenché)
    openai_calls = [c for c in calls if "api.openai.com" in c.get("url", "")]
    assert len(openai_calls) == 1

    # POST kind=verdict_rejected
    rejected_posts = [
        c for c in calls
        if c["method"] == "POST"
        and "/v1/atoms" in c.get("url", "")
        and (c.get("json") or {}).get("kind") == "verdict_rejected"
    ]
    assert len(rejected_posts) == 1, (
        f"expected 1 POST kind=verdict_rejected, got: {[c.get('json', {}).get('kind') for c in calls if c['method']=='POST']}"
    )
    rejected_payload = rejected_posts[0]["json"]
    assert rejected_payload["source_ref"]["verdict"] == "rejected"
    assert rejected_payload["source_ref"]["proposed_atom"]["kind"] == "decision"
    # reasons LLM bien propagées
    reasons_concat = " ".join(rejected_payload["source_ref"]["reasons"])
    assert "fabrication" in reasons_concat or "scope" in reasons_concat

    # Alert Telegram envoyée (1 message vers arac-telegram-bridge)
    telegram_msgs = [s for s in _fake_bus_send
                     if s.get("to_node") == "arac-telegram-bridge"]
    assert len(telegram_msgs) == 1
    assert "REJETÉ" in telegram_msgs[0]["value"] or "rejet" in telegram_msgs[0]["value"].lower()

    # Verdict rejected relayé au curator
    curator_msgs = [s for s in _fake_bus_send if s.get("to_node") == "arac-curator"]
    assert len(curator_msgs) == 1
    assert curator_msgs[0]["metadata"]["verdict"] == "rejected"


async def test_curator_decision_llm_timeout_fail_open_approves(monkeypatch, _fake_bus_send):
    """T-F — LLM timeout (network) sur curator decision → fail-open default
    → verdict final approved (cohérent v0.4 commit_proposal).
    """
    monkeypatch.setattr(llm_auditor.asyncio, "sleep", _no_op_sleep)
    timeout_exc = httpx.ReadTimeout("simulated read timeout")

    # 6 timeouts (3 retries primary + 3 fallback)
    calls = _install_clients(monkeypatch, openai_response=[timeout_exc] * 6)

    atom = _make_audit_request_atom(proposed_kind="decision")
    await auditor_main._handle_curator_atom_audit_request(atom)

    # Verdict approved malgré LLM down (fail-open default)
    curator_msgs = [s for s in _fake_bus_send if s.get("to_node") == "arac-curator"]
    assert len(curator_msgs) == 1
    assert curator_msgs[0]["metadata"]["verdict"] == "approved"

    # Aucun POST kind=verdict_rejected (fail-open laisse passer)
    rejected_posts = [
        c for c in calls
        if c["method"] == "POST"
        and "/v1/atoms" in c.get("url", "")
        and (c.get("json") or {}).get("kind") == "verdict_rejected"
    ]
    assert rejected_posts == []


# ===========================================================================
# Test wiring : dispatch _handle_incoming → _handle_curator_atom_audit_request
# ===========================================================================


async def test_handle_incoming_routes_curator_audit_request(monkeypatch, _fake_bus_send):
    """Vérifie que le dispatcher principal `_handle_incoming` route bien
    les messages avec source_ref.type='curator_atom_audit_request' vers le
    nouveau handler, sans toucher au flow commit_proposal v0.4.
    """
    calls = _install_clients(
        monkeypatch,
        openai_response=_openai_chat_response(verdict="approve", confidence=0.91),
    )

    atom = _make_audit_request_atom(proposed_kind="decision")
    # Appel via le dispatcher général
    await auditor_main._handle_incoming(atom)

    # LLM appelé via la branche curator (donc handler routé)
    openai_calls = [c for c in calls if "api.openai.com" in c.get("url", "")]
    assert len(openai_calls) == 1

    curator_msgs = [s for s in _fake_bus_send if s.get("to_node") == "arac-curator"]
    assert len(curator_msgs) == 1
    assert curator_msgs[0]["metadata"]["verdict"] == "approved"
    # Pas de message vers claude-developer (qui est le destinataire du flow v0.4)
    dev_msgs = [s for s in _fake_bus_send if s.get("to_node") == "claude-developer"]
    assert dev_msgs == []
