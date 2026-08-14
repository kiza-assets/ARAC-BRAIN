"""Tests unitaires Phase E — agents/lib/llm_auditor.py + intégration auditor/main.py.

Cible : module `llm_auditor` (cross-provider OpenAI) + wiring dans le handler
auditor (`_handle_incoming`).

Stratégie :
- 100% mock httpx (pas d'appel OpenAI réel).
- Mock `httpx.AsyncClient` au niveau de `agents.lib.llm_auditor.httpx` ET
  `agents.auditor.main.httpx` (POST atomes API ARAC), via _MockAsyncClient
  qui distingue les URLs (api.openai.com vs 127.0.0.1:8000).
- Mock `agents.lib.bus.send` (async fake).

Couverture cible : 5 tests pierre-angulaire (statique OK + LLM approve,
statique OK + LLM reject, statique fail → LLM PAS appelé, LLM timeout
fail-open, LLM 429 fail-open) + bonus secret base64.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from agents.auditor import main as auditor_main
from agents.lib import commit_audit, llm_auditor


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_commit_proposal_atom(
    *,
    atom_id: str = "11111111-2222-3333-4444-555555555555",
    mission_id: str = "mission-uuid-phasee01",
    branch: str = "feature/phase-e-test",
    files: list[str] | None = None,
    diff: str = "+hello\n-world\n",
) -> dict[str, Any]:
    files = files if files is not None else ["docs/test.md"]
    value = (
        f"Commit proposal mission={mission_id} branch={branch}\n"
        f"{auditor_main._DIFF_DELIM}\n{diff}"
    )
    return {
        "id": atom_id,
        "value": value,
        "source_ref": {
            "from": "claude-developer",
            "type": "commit_proposal",
            "mission_id": mission_id,
            "branch": branch,
            "files_changed": files,
            "reply_chat_id": 1000000001,
        },
    }


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
    """Routeur d'URLs : distingue OpenAI vs API ARAC vs foundations."""

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
        # Si openai_response est une liste : pop séquentiel (utile pour retries).
        if isinstance(self._openai, list):
            self._openai_queue = list(self._openai)
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
    """Construit une réponse OpenAI chat completions standard."""
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
    """Mock httpx.AsyncClient dans llm_auditor ET auditor.main."""
    if api_response is None:
        api_response = _MockResponse({"id": "verdict-atom-mocked"})
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


@pytest.fixture(autouse=True)
def _setup_env(monkeypatch):
    """Force OPENAI_API_KEY présent + LLM activé pour tous les tests."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key-for-mock-only")
    monkeypatch.setenv("ARAC_AUDITOR_LLM_ENABLED", "true")
    monkeypatch.setenv("ARAC_AUDITOR_LLM_MODEL", "gpt-5.5-turbo")
    monkeypatch.setenv("ARAC_AUDITOR_LLM_TIMEOUT_SEC", "30")
    monkeypatch.setenv("ARAC_AUDITOR_LLM_FAIL_MODE", "open")


@pytest.fixture
def _fake_bus_send(monkeypatch):
    """Mock bus.send → capture les envois sortants."""
    sent: list[dict[str, Any]] = []

    async def fake_send(**kwargs):
        sent.append(kwargs)
        return {"id": "send-ok"}

    monkeypatch.setattr(auditor_main.bus, "send", fake_send)
    return sent


# ===========================================================================
# Tests pierre-angulaire (D5 §A7)
# ===========================================================================


async def test_static_ok_llm_approve_yields_approve(monkeypatch, _fake_bus_send):
    """T1 — Statique OK + LLM approve → verdict final approved.

    Vérifie : POST kind=validation (pas alert), bus.send verdict=approved,
    et que l'appel OpenAI a bien eu lieu.
    """
    calls = _install_clients(
        monkeypatch,
        openai_response=_openai_chat_response(verdict="approve", confidence=0.95),
    )

    atom = _make_commit_proposal_atom(diff="+print('hello')\n")
    await auditor_main._handle_incoming(atom)

    # OpenAI a été appelé
    openai_calls = [c for c in calls if "api.openai.com" in c.get("url", "")]
    assert len(openai_calls) == 1, f"openai calls: {openai_calls}"
    assert openai_calls[0]["json"]["model"] == "gpt-5.5-turbo"
    assert openai_calls[0]["json"]["response_format"] == {"type": "json_object"}

    # Verdict approved sur le bus
    assert len(_fake_bus_send) == 1
    assert _fake_bus_send[0]["metadata"]["verdict"] == "approved"

    # POST atome kind=validation
    api_posts = [c for c in calls if "/v1/atoms" in c.get("url", "") and c["method"] == "POST"]
    assert len(api_posts) == 1
    assert api_posts[0]["json"]["kind"] == "validation"


async def test_static_ok_llm_reject_yields_reject(monkeypatch, _fake_bus_send):
    """T2 — Statique OK + LLM reject → verdict final rejected (LLM override)."""
    calls = _install_clients(
        monkeypatch,
        openai_response=_openai_chat_response(
            verdict="reject",
            reasons=["secret encodé en base64 détecté", "violation source-of-truth"],
            confidence=0.85,
        ),
    )

    atom = _make_commit_proposal_atom(diff="+x=1\n")
    await auditor_main._handle_incoming(atom)

    # bus.send verdict=rejected
    assert len(_fake_bus_send) == 1
    assert _fake_bus_send[0]["metadata"]["verdict"] == "rejected"
    reasons = _fake_bus_send[0]["metadata"]["reasons"]
    assert any("llm:" in r for r in reasons), f"reasons={reasons}"
    assert any("base64" in r for r in reasons)

    # POST atome kind=alert
    api_posts = [c for c in calls if "/v1/atoms" in c.get("url", "") and c["method"] == "POST"]
    assert len(api_posts) == 1
    assert api_posts[0]["json"]["kind"] == "alert"


async def test_static_fail_skips_llm(monkeypatch, _fake_bus_send):
    """T3 — Statique fail → reject immédiat, LLM JAMAIS appelé (économie API)."""
    calls = _install_clients(
        monkeypatch,
        # Si LLM est appelé, ce side_effect lèvera l'exception → test échoue.
        openai_response=AssertionError("LLM ne devrait PAS être appelé !"),
    )

    # Diff avec branche interdite → static fail
    atom = _make_commit_proposal_atom(
        branch="main",  # interdit
        diff="+harmless\n",
    )
    await auditor_main._handle_incoming(atom)

    # Aucun appel OpenAI
    openai_calls = [c for c in calls if "api.openai.com" in c.get("url", "")]
    assert openai_calls == [], f"LLM appelé alors qu'il ne devrait pas: {openai_calls}"

    # Reject sur bus
    assert _fake_bus_send[0]["metadata"]["verdict"] == "rejected"

    # kind=alert posté
    api_posts = [c for c in calls if "/v1/atoms" in c.get("url", "") and c["method"] == "POST"]
    assert api_posts[0]["json"]["kind"] == "alert"


async def test_llm_timeout_fail_open_approves(monkeypatch, _fake_bus_send):
    """T4 — LLM timeout (network) → fail-open default → approve.

    Simule httpx.ReadTimeout (retry interne dans audit_with_llm n'aboutit
    pas), puis vérifie que le verdict final est approved car FAIL_MODE=open.
    """
    monkeypatch.setattr(llm_auditor.asyncio, "sleep", _no_op_sleep)  # accélère le retry
    timeout_exc = httpx.ReadTimeout("simulated read timeout")

    # 3 tentatives sur primary + 3 sur fallback = 6 timeouts max
    calls = _install_clients(
        monkeypatch,
        openai_response=[timeout_exc] * 6,
    )

    atom = _make_commit_proposal_atom(diff="+benign\n")
    await auditor_main._handle_incoming(atom)

    # Verdict approved malgré le LLM down (fail-open)
    assert _fake_bus_send[0]["metadata"]["verdict"] == "approved"
    api_posts = [c for c in calls if "/v1/atoms" in c.get("url", "") and c["method"] == "POST"]
    assert api_posts[0]["json"]["kind"] == "validation"


async def test_llm_rate_limit_fail_open_approves(monkeypatch, _fake_bus_send):
    """T5 — LLM 429 → pas de retry → fail-open default → approve + alert Telegram."""
    rate_limit_resp = _MockResponse(
        {"error": {"message": "rate limited"}},
        status_code=429,
        text='{"error": {"message": "rate limited"}}',
    )

    calls = _install_clients(monkeypatch, openai_response=rate_limit_resp)

    atom = _make_commit_proposal_atom(diff="+benign\n")
    await auditor_main._handle_incoming(atom)

    # 429 n'est PAS retryé en interne (raise immédiate) → 1 seul appel OpenAI
    openai_calls = [c for c in calls if "api.openai.com" in c.get("url", "")]
    assert len(openai_calls) == 1

    # 2 envois bus.send : 1 alert Telegram + 1 verdict developer
    assert len(_fake_bus_send) == 2
    telegram_msgs = [s for s in _fake_bus_send if s["to_node"] == "arac-telegram-bridge"]
    developer_msgs = [s for s in _fake_bus_send if s["to_node"] == "claude-developer"]
    assert len(telegram_msgs) == 1, f"sent={_fake_bus_send}"
    assert len(developer_msgs) == 1
    assert developer_msgs[0]["metadata"]["verdict"] == "approved"  # fail-open


# ===========================================================================
# Bonus tests
# ===========================================================================


async def test_llm_disabled_skips_llm_and_approves(monkeypatch, _fake_bus_send):
    """ARAC_AUDITOR_LLM_ENABLED=false → étape 2 court-circuitée."""
    monkeypatch.setenv("ARAC_AUDITOR_LLM_ENABLED", "false")
    calls = _install_clients(
        monkeypatch,
        openai_response=AssertionError("LLM désactivé : ne doit PAS être appelé"),
    )

    atom = _make_commit_proposal_atom(diff="+ok\n")
    await auditor_main._handle_incoming(atom)

    openai_calls = [c for c in calls if "api.openai.com" in c.get("url", "")]
    assert openai_calls == []
    assert _fake_bus_send[0]["metadata"]["verdict"] == "approved"


async def test_llm_malformed_json_rejects_and_posts_gotcha(monkeypatch, _fake_bus_send):
    """JSON malformé → reject + POST atome kind=gotcha."""
    bad_response = _MockResponse({
        "choices": [{"message": {"content": "not a valid json at all !!!"}}],
    })
    calls = _install_clients(monkeypatch, openai_response=bad_response)

    atom = _make_commit_proposal_atom(diff="+benign\n")
    await auditor_main._handle_incoming(atom)

    # verdict rejected
    assert _fake_bus_send[0]["metadata"]["verdict"] == "rejected"
    assert any("malformed" in r.lower() for r in _fake_bus_send[0]["metadata"]["reasons"])

    # 2 POST atomes : 1 gotcha + 1 alert verdict
    api_posts = [c for c in calls if "/v1/atoms" in c.get("url", "") and c["method"] == "POST"]
    kinds = sorted([p["json"]["kind"] for p in api_posts])
    assert "gotcha" in kinds
    assert "alert" in kinds


async def test_llm_rate_limit_fail_closed_rejects(monkeypatch, _fake_bus_send):
    """FAIL_MODE=closed + 429 → reject."""
    monkeypatch.setenv("ARAC_AUDITOR_LLM_FAIL_MODE", "closed")
    rate_limit_resp = _MockResponse(
        {"error": "rl"}, status_code=429, text='{"error": "rl"}',
    )
    _install_clients(monkeypatch, openai_response=rate_limit_resp)

    atom = _make_commit_proposal_atom(diff="+ok\n")
    await auditor_main._handle_incoming(atom)

    developer_msgs = [s for s in _fake_bus_send if s["to_node"] == "claude-developer"]
    assert developer_msgs[0]["metadata"]["verdict"] == "rejected"
    assert any("llm_rate_limit_fail_closed" in r for r in developer_msgs[0]["metadata"]["reasons"])


async def test_static_secret_base64_blocked_before_llm(monkeypatch, _fake_bus_send):
    """Bonus — Si statique catche le secret (regex password) → reject sans LLM."""
    calls = _install_clients(
        monkeypatch,
        openai_response=AssertionError("LLM ne doit PAS être appelé sur static fail"),
    )

    # password assignment → catché par _SECRET_PATTERNS
    atom = _make_commit_proposal_atom(
        diff='+password="foo123secret"\n',
        files=["agents/leak.py"],
        branch="feature/sneaky",
    )
    await auditor_main._handle_incoming(atom)

    # Pas d'appel OpenAI (static fail-fast)
    openai_calls = [c for c in calls if "api.openai.com" in c.get("url", "")]
    assert openai_calls == []
    assert _fake_bus_send[0]["metadata"]["verdict"] == "rejected"


# ===========================================================================
# Tests unitaires sur le module llm_auditor lui-même
# ===========================================================================


def test_parse_llm_response_valid_approve():
    """JSON bien formé approve → dict propre."""
    raw = json.dumps({"verdict": "approve", "reasons": [], "confidence": 0.92})
    out = llm_auditor._parse_llm_response(raw)
    assert out["verdict"] == "approve"
    assert out["confidence"] == 0.92
    assert out["reasons"] == []


def test_parse_llm_response_invalid_verdict_raises():
    """verdict='maybe' → LLMMalformedException."""
    raw = json.dumps({"verdict": "maybe", "reasons": [], "confidence": 0.5})
    with pytest.raises(llm_auditor.LLMMalformedException):
        llm_auditor._parse_llm_response(raw)


def test_parse_llm_response_confidence_clipped():
    """confidence > 1 → clip à 1.0 (pas de raise)."""
    raw = json.dumps({"verdict": "approve", "reasons": [], "confidence": 2.5})
    out = llm_auditor._parse_llm_response(raw)
    assert out["confidence"] == 1.0


def test_parse_llm_response_invalid_json_raises():
    """JSON cassé → LLMMalformedException."""
    with pytest.raises(llm_auditor.LLMMalformedException):
        llm_auditor._parse_llm_response("not json at all {")


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------


async def _no_op_sleep(*args, **kwargs):
    return None
