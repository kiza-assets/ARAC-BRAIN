"""Tests UNITAIRES / robustness du bus inter-agents — Phase D.5 wave 2.

Complément du test_bus.py existant qui couvre l'E2E (vraie BDD + LISTEN/NOTIFY).
Ici on mocke `httpx` et `psycopg` pour exercer les chemins critiques :

  - `_channel_for` (sanitization → identifier PG safe)
  - `_api_url` (default + strip trailing slash)
  - `_dsn_or_raise` (RuntimeError explicite si env absent)
  - `send()` (payload conforme : kind, scope, key regex, source_ref merge)
  - `subscribe()` (handler exception isolée, ne tue pas la boucle)
  - `listen_inbox()` (backoff exponentiel sur OperationalError, sleep mocké)

Aucune BDD ni réseau requis. Doivent tourner même si `DATABASE_URL_APP` est unset
(la fixture conftest le set pour la session, on le pop là où on en a besoin).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import psycopg
import pytest

from agents.lib import bus


# ---------------------------------------------------------------------------
# _channel_for : sanitization → identifier PG safe
# ---------------------------------------------------------------------------


def test_channel_for_sanitizes_node_id():
    """`-` → `_` dans le nom de canal (LISTEN sans quoting)."""
    assert bus._channel_for("claude-developer") == "agent_inbox_claude_developer"
    assert bus._channel_for("a-b-c") == "agent_inbox_a_b_c"
    assert bus._channel_for("simple") == "agent_inbox_simple"


def test_channel_for_output_matches_identifier_charset():
    """Le canal produit doit matcher [a-z0-9_]+ — sinon LISTEN nu non sûr.

    Note : `_channel_for` n'implémente actuellement QUE le replace `-`→`_`.
    Pour les caractères dangereux (`;`, `'`, `.`, espace…) la docstring de
    `bus.listen_inbox` indique « _channel_for() garantit que node_id n'a que
    [a-z0-9_] » — la garantie repose sur la convention d'appel (node_id seed
    constitution). Ce test documente le comportement actuel et vérifie qu'au
    moins les inputs canoniques produisent un identifier safe.
    """
    safe_pattern = re.compile(r"^agent_inbox_[a-z0-9_]+$")
    for node in ("claude-developer", "codex-auditor", "test-node"):
        ch = bus._channel_for(node)
        assert safe_pattern.match(ch), f"channel non-safe pour {node!r} : {ch!r}"

    # Input dangereux : `_channel_for` ne le sanitize PAS actuellement.
    # On valide explicitement que les chars `;` et `'` PASSENT à travers,
    # ce qui justifie de ne JAMAIS appeler subscribe()/listen_inbox() avec
    # un node_id non-trusted. C'est un test de contrat (pas un bug).
    dangerous = bus._channel_for("foo;bar")
    assert ";" in dangerous, "Sanitization plus stricte ? mettre à jour la doc bus.py"


# ---------------------------------------------------------------------------
# _api_url : default + strip trailing slash
# ---------------------------------------------------------------------------


def test_api_url_sans_defaut_quand_env_absente(monkeypatch):
    """Sans ARAC_API_URL → rien. AUCUN défaut, et c'est le correctif.

    Ce test affirmait l'inverse : « sans ARAC_API_URL → http://127.0.0.1:8000 ».
    Il figeait donc le défaut au lieu de le surveiller. Sur une machine qui
    porte deux cerveaux — le cas que tout ce dépôt cherche à rendre sûr — le
    port 8000 est celui du PREMIER : un agent du second y publiait ses atomes,
    avec un jeton valide et un HTTP 200, dans la mémoire de quelqu'un d'autre.

    Un défaut plausible est plus dangereux qu'une panne : il produit un
    résultat crédible. On préfère donc le vide, qui se voit, à une adresse
    juste-mais-fausse, qui ne se voit pas. L'unité systemd engendrée par le
    bootstrap pose ARAC_API_URL ; son absence signale une installation
    incomplète, ce qui est une information.
    """
    monkeypatch.delenv("ARAC_API_URL", raising=False)
    assert bus._api_url() == ""


def test_api_url_strips_trailing_slash(monkeypatch):
    """Trailing slash retiré pour éviter `//v1/atoms` dans send()."""
    monkeypatch.setenv("ARAC_API_URL", "http://example.test:9000/")
    assert bus._api_url() == "http://example.test:9000"
    monkeypatch.setenv("ARAC_API_URL", "http://example.test:9000")
    assert bus._api_url() == "http://example.test:9000"


# ---------------------------------------------------------------------------
# _dsn_or_raise : RuntimeError explicite si env absent
# ---------------------------------------------------------------------------


def test_dsn_or_raise_raises_without_env(monkeypatch):
    """DATABASE_URL_APP absent → RuntimeError au message clair (mention .env)."""
    monkeypatch.delenv("DATABASE_URL_APP", raising=False)
    with pytest.raises(RuntimeError) as exc:
        bus._dsn_or_raise()
    msg = str(exc.value)
    assert "DATABASE_URL_APP" in msg
    assert "subscribe()" in msg
    # Le message doit pointer l'opérateur vers la racine (.env / systemd)
    assert ".env" in msg or "EnvironmentFile" in msg


def test_dsn_or_raise_returns_dsn_when_set(monkeypatch):
    monkeypatch.setenv("DATABASE_URL_APP", "postgres://fake:5432/x")
    assert bus._dsn_or_raise() == "postgres://fake:5432/x"


# ---------------------------------------------------------------------------
# send() : payload conforme
# ---------------------------------------------------------------------------


def _make_post_mock(returned_json: dict | None = None):
    """Forge un mock httpx.AsyncClient context-manager → .post() AsyncMock.

    Retourne (mock_client_ctor, mock_post) — `mock_post` est l'AsyncMock final
    sur lequel on inspecte `.await_args.kwargs["json"]`.
    """
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value=returned_json or {"id": "atom-123"})

    mock_post = AsyncMock(return_value=response)
    mock_client = MagicMock()
    mock_client.post = mock_post
    # AsyncClient(...) est utilisé en `async with` — mock le context-manager.
    mock_ctor = MagicMock()
    mock_ctor.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctor.return_value.__aexit__ = AsyncMock(return_value=None)
    return mock_ctor, mock_post


@pytest.mark.asyncio
async def test_send_posts_correct_payload(monkeypatch):
    """send() POST /v1/atoms avec kind/scope/key/source_ref attendus."""
    monkeypatch.setenv("ARAC_API_URL", "http://api.test:8000")
    monkeypatch.delenv("ARAC_SCOPE_AGENT_MESSAGE", raising=False)

    mock_ctor, mock_post = _make_post_mock({"id": "atom-abc"})
    with patch("agents.lib.bus.httpx.AsyncClient", mock_ctor):
        result = await bus.send(
            from_node="claude-orchestrator",
            to_node="claude-developer",
            value="ping",
        )

    assert result == {"id": "atom-abc"}
    # URL avec slash unique
    call_args = mock_post.await_args
    assert call_args.args[0] == "http://api.test:8000/v1/atoms"
    payload = call_args.kwargs["json"]
    assert payload["kind"] == "agent_message"
    assert payload["scope"] == bus._default_scope()  # déduit de la taxonomie
    assert payload["value"] == "ping"
    assert payload["node_id"] == "claude-orchestrator"
    # key regex : msg-<from>-to-<to>-<8 hex>
    assert re.match(
        r"^msg-claude-orchestrator-to-claude-developer-[a-f0-9]{8}$",
        payload["key"],
    ), f"key non conforme : {payload['key']!r}"
    assert payload["source_ref"] == {
        "to": "claude-developer",
        "from": "claude-orchestrator",
    }


@pytest.mark.asyncio
async def test_send_metadata_merged_in_source_ref(monkeypatch):
    """metadata={mission_id: ...} → mergé dans source_ref à côté de to/from."""
    monkeypatch.setenv("ARAC_API_URL", "http://api.test:8000")

    mock_ctor, mock_post = _make_post_mock()
    with patch("agents.lib.bus.httpx.AsyncClient", mock_ctor):
        await bus.send(
            from_node="A",
            to_node="B",
            value="v",
            metadata={"mission_id": "m-42", "dispute_hash": "deadbeef"},
        )

    payload = mock_post.await_args.kwargs["json"]
    sr = payload["source_ref"]
    assert sr["to"] == "B"
    assert sr["from"] == "A"
    assert sr["mission_id"] == "m-42"
    assert sr["dispute_hash"] == "deadbeef"


@pytest.mark.asyncio
async def test_send_respects_custom_scope(monkeypatch):
    """ARAC_SCOPE_AGENT_MESSAGE override le scope du payload."""
    monkeypatch.setenv("ARAC_API_URL", "http://api.test:8000")
    monkeypatch.setenv("ARAC_SCOPE_AGENT_MESSAGE", "missions")

    mock_ctor, mock_post = _make_post_mock()
    with patch("agents.lib.bus.httpx.AsyncClient", mock_ctor):
        await bus.send(from_node="A", to_node="B", value="v")

    assert mock_post.await_args.kwargs["json"]["scope"] == "missions"


# ---------------------------------------------------------------------------
# subscribe() : handler exception → log + continue (ne tue pas la boucle)
# ---------------------------------------------------------------------------


async def _async_iter(items):
    """Helper : transforme une liste en async iterator avec aclose()."""
    for it in items:
        yield it


class _FakeAsyncGen:
    """Faux async generator avec aclose() awaitable (mimic listen_inbox)."""

    def __init__(self, items):
        self._items = list(items)
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_subscribe_handler_exception_logged_not_crashed(monkeypatch, caplog):
    """Handler qui raise → log error + loop continue sur l'atome suivant."""
    atoms = [
        {"id": "a1", "value": "first"},
        {"id": "a2", "value": "second"},
    ]
    fake_iter = _FakeAsyncGen(atoms)
    monkeypatch.setattr(bus, "listen_inbox", lambda node_id: fake_iter)

    seen: list[str] = []

    async def bad_handler(atom):
        seen.append(atom["id"])
        if atom["id"] == "a1":
            raise ValueError("boom on first")
        # a2 passe normalement

    import logging
    caplog.set_level(logging.ERROR, logger="arac.bus")

    await bus.subscribe("claude-developer", bad_handler)

    # Les DEUX atomes ont été présentés au handler (la boucle n'a pas crashé)
    assert seen == ["a1", "a2"]
    # aclose() appelé en finally
    assert fake_iter.closed is True
    # L'erreur a été loggée en JSON structuré
    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert any("bus.handler_error" in r.getMessage() for r in error_records), (
        f"log error 'bus.handler_error' manquant — records={[r.getMessage() for r in error_records]}"
    )
    # Le détail JSON doit contenir le type d'exception
    err_msg = next(r.getMessage() for r in error_records if "bus.handler_error" in r.getMessage())
    payload = json.loads(err_msg)
    assert payload["error"] == "ValueError"
    assert payload["atom_id"] == "a1"


@pytest.mark.asyncio
async def test_subscribe_respects_stop_event(monkeypatch):
    """stop_event set entre deux atomes → handler n'est plus appelé."""
    atoms = [{"id": "a1"}, {"id": "a2"}, {"id": "a3"}]
    fake_iter = _FakeAsyncGen(atoms)
    monkeypatch.setattr(bus, "listen_inbox", lambda node_id: fake_iter)

    seen: list[str] = []
    stop = asyncio.Event()

    async def handler(atom):
        seen.append(atom["id"])
        if atom["id"] == "a1":
            stop.set()

    await bus.subscribe("claude-developer", handler, stop_event=stop)

    # Après a1, stop_event set → la boucle break AVANT de traiter a2
    assert seen == ["a1"]
    assert fake_iter.closed is True


# ---------------------------------------------------------------------------
# listen_inbox() : backoff exponentiel sur OperationalError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_listen_inbox_backoff_on_operational_error(monkeypatch):
    """psycopg.OperationalError → asyncio.sleep(1), puis 2, puis 4 (backoff exp).

    On laisse 3 échecs consécutifs puis on raise CancelledError pour sortir.
    Vérifie que asyncio.sleep est appelé avec les valeurs de
    `_BACKOFF_SEQUENCE_SEC` dans l'ordre.
    """
    monkeypatch.setenv("DATABASE_URL_APP", "postgres://fake/x")

    call_count = {"n": 0}

    async def fake_connect(dsn, autocommit=True):
        call_count["n"] += 1
        if call_count["n"] <= 3:
            raise psycopg.OperationalError("connection refused (fake)")
        # 4e appel : sort proprement via CancelledError
        raise asyncio.CancelledError()

    sleeps: list[float] = []

    async def fake_sleep(sec):
        sleeps.append(sec)

    monkeypatch.setattr(bus.psycopg.AsyncConnection, "connect", fake_connect)
    monkeypatch.setattr(bus.asyncio, "sleep", fake_sleep)

    gen = bus.listen_inbox("claude-developer")
    with pytest.raises(asyncio.CancelledError):
        await gen.__anext__()

    # 3 échecs → 3 sleeps avec les 3 premières valeurs du backoff (1, 2, 4)
    assert sleeps == [1, 2, 4], f"backoff incorrect : {sleeps}"
    assert call_count["n"] == 4  # 3 fails + 1 cancel


@pytest.mark.asyncio
async def test_listen_inbox_backoff_caps_at_30s(monkeypatch):
    """Au-delà de len(_BACKOFF_SEQUENCE_SEC) échecs → plafonne à 30s."""
    monkeypatch.setenv("DATABASE_URL_APP", "postgres://fake/x")

    # 8 échecs successifs : la séquence est (1,2,4,8,16,30) puis plafond 30
    fail_budget = {"n": 8}

    async def fake_connect(dsn, autocommit=True):
        fail_budget["n"] -= 1
        if fail_budget["n"] >= 0:
            raise psycopg.OperationalError("fake")
        raise asyncio.CancelledError()

    sleeps: list[float] = []

    async def fake_sleep(sec):
        sleeps.append(sec)

    monkeypatch.setattr(bus.psycopg.AsyncConnection, "connect", fake_connect)
    monkeypatch.setattr(bus.asyncio, "sleep", fake_sleep)

    gen = bus.listen_inbox("claude-developer")
    with pytest.raises(asyncio.CancelledError):
        await gen.__anext__()

    # 8 sleeps : 1, 2, 4, 8, 16, 30, 30, 30 (les 2 derniers plafonnés)
    assert sleeps == [1, 2, 4, 8, 16, 30, 30, 30], f"backoff cap : {sleeps}"


@pytest.mark.asyncio
async def test_listen_inbox_raises_runtime_error_when_dsn_missing(monkeypatch):
    """Sans DATABASE_URL_APP → RuntimeError remonté avant tout LISTEN."""
    monkeypatch.delenv("DATABASE_URL_APP", raising=False)
    gen = bus.listen_inbox("claude-developer")
    with pytest.raises(RuntimeError, match="DATABASE_URL_APP"):
        await gen.__anext__()
