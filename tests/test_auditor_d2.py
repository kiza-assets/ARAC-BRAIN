"""Tests unitaires Phase D.2 — agents/auditor/main.py.

Couverture cible : `_handle_incoming`, `_parse_proposal_value`,
`_post_verdict_atom` du gate commit_audit Phase D.2.

Stratégie :
- Tests UNITAIRES purs (pas de BDD, pas de réseau).
- Mock `httpx.AsyncClient` via monkeypatch (context manager async).
- Mock `agents.lib.bus.send` (async fake).
- Mock `agents.lib.commit_audit.audit` quand on veut forcer ok/ko sans
  passer par un vrai diff (utile pour découpler les tests par responsabilité).

Référence : rapport agent 5 RECON — main.py auditor à 0% de couverture (P0 gap).
"""

from __future__ import annotations

from typing import Any

import pytest

from agents.auditor import main as auditor_main
from agents.lib import commit_audit


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_commit_proposal_atom(
    *,
    atom_id: str = "11111111-2222-3333-4444-555555555555",
    mission_id: str = "mission-uuid-abcdef01",
    branch: str = "feature/d2-test",
    files: list[str] | None = None,
    diff: str = "+hello\n-world\n",
    reply_chat_id: int | None = 1000000001,
) -> dict[str, Any]:
    files = files if files is not None else ["docs/test.md"]
    value = (
        f"Commit proposal mission={mission_id} branch={branch}\n"
        f"{auditor_main._DIFF_DELIM}\n{diff}"
    )
    source_ref: dict[str, Any] = {
        "from": "claude-developer",
        "type": "commit_proposal",
        "mission_id": mission_id,
        "branch": branch,
        "files_changed": files,
    }
    if reply_chat_id is not None:
        source_ref["reply_chat_id"] = reply_chat_id
    return {"id": atom_id, "value": value, "source_ref": source_ref}


class _MockResponse:
    """Fake httpx.Response : raise_for_status no-op + .json() statique."""

    def __init__(self, payload: dict[str, Any], status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._payload


class _MockAsyncClient:
    """Fake httpx.AsyncClient utilisable comme context manager async.

    Capture les payloads POSTés sur self.calls (liste partagée via factory).
    """

    def __init__(self, *, calls: list[dict[str, Any]], response: _MockResponse, raises: Exception | None = None):
        self._calls = calls
        self._response = response
        self._raises = raises

    async def __aenter__(self) -> "_MockAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def post(self, url: str, json: dict[str, Any] | None = None, **kwargs: Any) -> _MockResponse:
        self._calls.append({"url": url, "json": json})
        if self._raises is not None:
            raise self._raises
        return self._response


def _install_httpx_mock(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response_payload: dict[str, Any] | None = None,
    raises: Exception | None = None,
) -> list[dict[str, Any]]:
    """Patch `auditor_main.httpx.AsyncClient` avec un fake. Retourne la liste
    `calls` partagée (chaque entrée = {url, json})."""
    calls: list[dict[str, Any]] = []
    payload = response_payload if response_payload is not None else {"id": "verdict-atom-uuid-abc"}
    response = _MockResponse(payload)

    def _factory(*args: Any, **kwargs: Any) -> _MockAsyncClient:
        return _MockAsyncClient(calls=calls, response=response, raises=raises)

    monkeypatch.setattr(auditor_main.httpx, "AsyncClient", _factory)
    return calls


# ---------------------------------------------------------------------------
# _parse_proposal_value
# ---------------------------------------------------------------------------


def test_parse_proposal_value_extracts_diff():
    """value avec marqueur `--- DIFF ---` → extrait correctement le diff."""
    value = "header text\n--- DIFF ---\n+added\n-removed\n"
    result = auditor_main._parse_proposal_value(value)
    assert result == "+added\n-removed\n"


def test_parse_proposal_value_empty_when_no_marker():
    """value sans marqueur → chaîne vide."""
    value = "blob without diff marker at all"
    assert auditor_main._parse_proposal_value(value) == ""


# ---------------------------------------------------------------------------
# _post_verdict_atom
# ---------------------------------------------------------------------------


async def test_post_verdict_atom_ok_creates_validation(monkeypatch):
    """ok=True → kind=validation + audit_source=autonomous_agent_suggest +
    confidence=agent_suggest + source_ref.target_atom_id correct."""
    calls = _install_httpx_mock(monkeypatch, response_payload={"id": "v-ok-1"})

    out = await auditor_main._post_verdict_atom(
        ok=True,
        proposal_atom_id="prop-atom-id-ok",
        mission_id="mission-uuid-abcdef01",
        reasons=[],
        branch="feature/x",
        files=["docs/a.md"],
    )

    assert out == {"id": "v-ok-1"}
    assert len(calls) == 1
    payload = calls[0]["json"]
    assert payload["kind"] == "validation"
    assert payload["audit_source"] == "autonomous_agent_suggest"
    assert payload["confidence"] == "agent_suggest"
    assert payload["node_id"] == auditor_main._NODE_ID
    assert payload["source_ref"]["type"] == "commit_verdict"
    assert payload["source_ref"]["target_atom_id"] == "prop-atom-id-ok"
    assert payload["source_ref"]["reasons"] == []  # ok → reasons vide
    assert "APPROVED" in payload["value"]


async def test_post_verdict_atom_ko_creates_alert(monkeypatch):
    """ok=False → kind=alert + reasons[] dans source_ref + rationale dans value."""
    calls = _install_httpx_mock(monkeypatch, response_payload={"id": "v-ko-1"})

    reasons = ["forbidden path: .env", "branch 'main' is disallowed"]
    out = await auditor_main._post_verdict_atom(
        ok=False,
        proposal_atom_id="prop-atom-id-ko",
        mission_id="mission-uuid-deadbeef",
        reasons=reasons,
        branch="main",
        files=[".env"],
    )

    assert out == {"id": "v-ko-1"}
    payload = calls[0]["json"]
    assert payload["kind"] == "alert"
    assert payload["source_ref"]["reasons"] == reasons
    assert payload["source_ref"]["target_atom_id"] == "prop-atom-id-ko"
    assert "REJECTED" in payload["value"]


async def test_post_verdict_atom_rationale_present_for_alert(monkeypatch):
    """Pour kind=alert : la `value` doit contenir un rationale lisible
    (mention REJECTED + listing des reasons), conforme audit_source rules
    qui exigent du contexte humainement vérifiable pour un alert agent."""
    # v0.4 gap I1 2026-05-22 — fix doublon : un seul install (le 2e écrasait le 1er)
    calls = _install_httpx_mock(monkeypatch)

    out = await auditor_main._post_verdict_atom(
        ok=False,
        proposal_atom_id="prop-id",
        mission_id="mission-uuid",
        reasons=["forbidden path: data/founding-atoms/x.md", "diff too large: 500 lines"],
        branch="feature/x",
        files=["data/founding-atoms/x.md"],
    )

    assert out["id"]
    payload = calls[0]["json"]
    value = payload["value"]
    # Rationale : on doit retrouver verdict + reasons explicites
    assert "REJECTED" in value
    assert "forbidden path: data/founding-atoms/x.md" in value
    assert "diff too large: 500 lines" in value
    assert len(value) > 50  # pas vide / pas tronqué


async def test_verdict_atom_includes_target_atom_id(monkeypatch):
    """Sanity : target_atom_id propagé tel quel depuis proposal_atom_id."""
    calls = _install_httpx_mock(monkeypatch)

    await auditor_main._post_verdict_atom(
        ok=True,
        proposal_atom_id="UNIQUE-PROP-ID-42",
        mission_id="m",
        reasons=[],
        branch="feature/y",
        files=[],
    )

    assert calls[0]["json"]["source_ref"]["target_atom_id"] == "UNIQUE-PROP-ID-42"


# ---------------------------------------------------------------------------
# _handle_incoming — branche non-commit_proposal
# ---------------------------------------------------------------------------


async def test_handle_incoming_ignores_non_commit_proposal(monkeypatch):
    """Atome dont source_ref.type != 'commit_proposal' → log + no-op.
    Aucun POST httpx, aucun bus.send."""
    httpx_calls = _install_httpx_mock(monkeypatch)
    sent: list[dict[str, Any]] = []

    async def fake_send(**kwargs: Any) -> dict[str, Any]:
        sent.append(kwargs)
        return {"id": "should-not-be-called"}

    monkeypatch.setattr(auditor_main.bus, "send", fake_send)

    atom = {
        "id": "00000000-0000-0000-0000-0000000000aa",
        "value": "random",
        "source_ref": {"from": "claude-orchestrator", "type": "other"},
    }
    result = await auditor_main._handle_incoming(atom)

    assert result is None
    assert httpx_calls == []
    assert sent == []


# ---------------------------------------------------------------------------
# _handle_incoming — full path commit_proposal
# ---------------------------------------------------------------------------


async def test_handle_incoming_with_commit_proposal_calls_audit(monkeypatch):
    """Commit proposal → commit_audit.audit() est appelé avec
    diff_text/files/branch issus de l'atome."""
    _install_httpx_mock(monkeypatch)

    async def fake_send(**kwargs: Any) -> dict[str, Any]:
        return {"id": "send-ok"}

    monkeypatch.setattr(auditor_main.bus, "send", fake_send)

    audit_calls: list[dict[str, Any]] = []

    def fake_audit(*, diff_text: str, files: list[str], branch: str | None):
        audit_calls.append({"diff_text": diff_text, "files": files, "branch": branch})
        return commit_audit.AuditResult(ok=True, reasons=[])

    monkeypatch.setattr(auditor_main.commit_audit, "audit", fake_audit)

    atom = _make_commit_proposal_atom(
        diff="+ligne1\n+ligne2\n",
        files=["docs/x.md"],
        branch="feature/d2",
    )
    await auditor_main._handle_incoming(atom)

    assert len(audit_calls) == 1
    assert audit_calls[0]["diff_text"] == "+ligne1\n+ligne2\n"
    assert audit_calls[0]["files"] == ["docs/x.md"]
    assert audit_calls[0]["branch"] == "feature/d2"


async def test_handle_incoming_sends_commit_verdict_message(monkeypatch):
    """Le bus.send final doit pousser un agent_message avec
    metadata.type='commit_verdict' vers claude-developer + verdict_atom_id
    issu du POST atom."""
    _install_httpx_mock(monkeypatch, response_payload={"id": "verdict-real-id-42"})

    sent: list[dict[str, Any]] = []

    async def fake_send(**kwargs: Any) -> dict[str, Any]:
        sent.append(kwargs)
        return {"id": "send-ok"}

    monkeypatch.setattr(auditor_main.bus, "send", fake_send)

    # Force ok=True pour avoir un chemin déterministe
    monkeypatch.setattr(
        auditor_main.commit_audit,
        "audit",
        lambda **kw: commit_audit.AuditResult(ok=True, reasons=[]),
    )

    atom = _make_commit_proposal_atom()
    await auditor_main._handle_incoming(atom)

    assert len(sent) == 1
    payload = sent[0]
    assert payload["from_node"] == auditor_main._NODE_ID
    assert payload["to_node"] == auditor_main._DEVELOPER_NODE_ID
    md = payload["metadata"]
    assert md["type"] == "commit_verdict"
    assert md["verdict"] == "approved"
    assert md["verdict_atom_id"] == "verdict-real-id-42"
    assert md["proposal_atom_id"] == atom["id"]


async def test_handle_incoming_handles_post_verdict_failure_gracefully(monkeypatch):
    """Si httpx POST raise → log error, pas de crash, verdict_atom_id='post-failed'
    propagé dans le bus.send vers le developer."""
    _install_httpx_mock(monkeypatch, raises=RuntimeError("simulated network down"))

    sent: list[dict[str, Any]] = []

    async def fake_send(**kwargs: Any) -> dict[str, Any]:
        sent.append(kwargs)
        return {"id": "send-after-fail"}

    monkeypatch.setattr(auditor_main.bus, "send", fake_send)
    monkeypatch.setattr(
        auditor_main.commit_audit,
        "audit",
        lambda **kw: commit_audit.AuditResult(ok=True, reasons=[]),
    )

    atom = _make_commit_proposal_atom()
    # Ne doit PAS raise
    await auditor_main._handle_incoming(atom)

    # Le bus.send aval doit quand même partir avec verdict_atom_id='post-failed'
    assert len(sent) == 1
    assert sent[0]["metadata"]["verdict_atom_id"] == "post-failed"


# ---------------------------------------------------------------------------
# v0.4 gap I1 2026-05-22 — additifs G-D* (spec D1 §4.2)
# ---------------------------------------------------------------------------


async def test_post_verdict_atom_payload_includes_audit_source_for_alert(monkeypatch):
    """G-D1 — Symétrise le test #3 : kind=alert porte aussi
    `audit_source=autonomous_agent_suggest` + `confidence=agent_suggest`.

    Le test #3 vérifie ces champs pour kind=validation uniquement. On lock le
    même contrat pour kind=alert (doctrine ARAC : tout atome d'agent autonome
    doit porter ces deux champs, peu importe le verdict).
    """
    calls = _install_httpx_mock(monkeypatch, response_payload={"id": "v-alert-1"})

    await auditor_main._post_verdict_atom(
        ok=False,
        proposal_atom_id="prop-alert",
        mission_id="mission-alert-uuid",
        reasons=["forbidden path: .env"],
        branch="feature/x",
        files=[".env"],
    )

    payload = calls[0]["json"]
    assert payload["kind"] == "alert"
    assert payload["audit_source"] == "autonomous_agent_suggest"
    assert payload["confidence"] == "agent_suggest"
    assert payload["node_id"] == auditor_main._NODE_ID


async def test_post_verdict_atom_key_is_unique_per_call(monkeypatch):
    """G-D2 — Le suffixe `secrets.token_hex(4)` rend la clé unique entre 2 appels."""
    calls = _install_httpx_mock(monkeypatch)

    await auditor_main._post_verdict_atom(
        ok=True, proposal_atom_id="p", mission_id="m-uuid-12345678",
        reasons=[], branch="feature/x", files=[],
    )
    await auditor_main._post_verdict_atom(
        ok=True, proposal_atom_id="p", mission_id="m-uuid-12345678",
        reasons=[], branch="feature/x", files=[],
    )

    assert len(calls) == 2
    key1 = calls[0]["json"]["key"]
    key2 = calls[1]["json"]["key"]
    assert key1 != key2, f"clés doivent être uniques (token_hex): {key1!r} vs {key2!r}"
    # Sanity : préfixe commun verdict-validation-<short_mid>-
    assert key1.startswith("verdict-validation-m-uuid-1-")
    assert key2.startswith("verdict-validation-m-uuid-1-")


async def test_handle_incoming_logs_proposal_received_with_diff_bytes(monkeypatch, caplog):
    """G-D3 — `caplog` doit capturer event `auditor.proposal_received` avec champ `diff_bytes`."""
    import json as _json
    import logging as _logging

    _install_httpx_mock(monkeypatch)

    async def fake_send(**kwargs):
        return {"id": "send-ok"}

    monkeypatch.setattr(auditor_main.bus, "send", fake_send)
    monkeypatch.setattr(
        auditor_main.commit_audit, "audit",
        lambda **kw: commit_audit.AuditResult(ok=True, reasons=[]),
    )

    diff = "+line1\n+line2\n+line3\n"  # 21 bytes ASCII
    atom = _make_commit_proposal_atom(diff=diff)

    with caplog.at_level(_logging.INFO, logger="arac.auditor"):
        await auditor_main._handle_incoming(atom)

    # Cherche le record event=auditor.proposal_received
    parsed_records = []
    for rec in caplog.records:
        try:
            parsed_records.append(_json.loads(rec.getMessage()))
        except (ValueError, TypeError):
            continue

    received = [r for r in parsed_records if r.get("event") == "auditor.proposal_received"]
    assert len(received) == 1, f"event auditor.proposal_received absent ; records={parsed_records}"
    assert received[0]["diff_bytes"] == len(diff)


async def test_handle_incoming_propagates_reply_chat_id_to_bus_send(monkeypatch):
    """G-D4 — `reply_chat_id` du proposal doit apparaître dans metadata du bus.send aval (chemin Telegram)."""
    _install_httpx_mock(monkeypatch)
    sent: list[dict[str, Any]] = []

    async def fake_send(**kwargs):
        sent.append(kwargs)
        return {"id": "send-ok"}

    monkeypatch.setattr(auditor_main.bus, "send", fake_send)
    monkeypatch.setattr(
        auditor_main.commit_audit, "audit",
        lambda **kw: commit_audit.AuditResult(ok=True, reasons=[]),
    )

    atom = _make_commit_proposal_atom(reply_chat_id=42424242)
    await auditor_main._handle_incoming(atom)

    assert len(sent) == 1
    assert sent[0]["metadata"]["reply_chat_id"] == 42424242


async def test_handle_incoming_with_audit_ko_sends_alert_and_rejected_verdict(monkeypatch):
    """G-D5 — Intégration mock-only : proposal avec secret AKIA → audit ko réel
    (pas de monkeypatch sur `audit`) → POST kind=alert + bus.send verdict=rejected.
    Couvre le chemin que les tests 1-10 contournent en forçant ok=True.
    """
    httpx_calls = _install_httpx_mock(monkeypatch, response_payload={"id": "verdict-rejected-99"})
    sent: list[dict[str, Any]] = []

    async def fake_send(**kwargs):
        sent.append(kwargs)
        return {"id": "send-ok"}

    monkeypatch.setattr(auditor_main.bus, "send", fake_send)
    # PAS de monkeypatch sur audit : on laisse le vrai audit déclencher ko via secret AKIA.

    atom = _make_commit_proposal_atom(
        diff="+AWS_KEY=AKIAQWERTYUIOPASDFGH\n",
        files=["agents/leak.py"],
        branch="feature/sneaky",
    )
    await auditor_main._handle_incoming(atom)

    # POST atom kind=alert
    assert len(httpx_calls) == 1
    posted = httpx_calls[0]["json"]
    assert posted["kind"] == "alert"
    assert any("aws_access_key" in r for r in posted["source_ref"]["reasons"])

    # bus.send avec verdict=rejected
    assert len(sent) == 1
    md = sent[0]["metadata"]
    assert md["verdict"] == "rejected"
    assert md["verdict_atom_id"] == "verdict-rejected-99"


async def test_handle_incoming_with_missing_mission_id_uses_nomid(monkeypatch):
    """G-D6 — mission_id absent/vide dans source_ref → key contient le fallback `nomid`."""
    calls = _install_httpx_mock(monkeypatch)

    async def fake_send(**kwargs):
        return {"id": "send-ok"}

    monkeypatch.setattr(auditor_main.bus, "send", fake_send)
    monkeypatch.setattr(
        auditor_main.commit_audit, "audit",
        lambda **kw: commit_audit.AuditResult(ok=True, reasons=[]),
    )

    # Construit un atom sans mission_id
    atom = _make_commit_proposal_atom()
    atom["source_ref"]["mission_id"] = ""  # vide → fallback "nomid"

    await auditor_main._handle_incoming(atom)

    assert len(calls) == 1
    key = calls[0]["json"]["key"]
    assert "nomid" in key, f"fallback 'nomid' absent de la key: {key!r}"
