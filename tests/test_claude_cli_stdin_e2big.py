"""Tests du wrapper agents/lib/claude_cli.run_claude_subprocess — v0.5.1.

Couvre le passage du prompt par stdin :
  - C1 : le prompt passe par STDIN, jamais en argv (sinon execve E2BIG
    `[Errno 7] Argument list too long` au-delà de MAX_ARG_STRLEN=131072).
  - C2 : une OSError au spawn (E2BIG ou binaire absent) ne propage PAS ;
    elle retourne un dict ok=False (le caller marque alors la row 'failed'
    au lieu de laisser un orphelin status='processing').

Les fakes reproduisent l'API réelle utilisée par le code (streaming
proc.stdout/proc.stderr + proc.stdin + proc.wait), contrairement aux deux
anciens tests communicate()-based (dette héritée v0.5, supprimés).
"""

from __future__ import annotations

import asyncio

import pytest

from agents.lib import claude_cli

# MAX_ARG_STRLEN Linux = 32 * PAGE_SIZE(4096) = 131072 octets (cap single-arg).
MAX_ARG_STRLEN = 131072


class FakeStreamReader:
    """StreamReader minimal : renvoie `data` une fois puis EOF (b'')."""

    def __init__(self, data: bytes = b"") -> None:
        self._data = data
        self._done = False

    async def read(self, n: int = -1) -> bytes:
        if self._done:
            return b""
        self._done = True
        return self._data


class FakeStreamWriter:
    """StreamWriter minimal : capture les écritures stdin."""

    def __init__(self) -> None:
        self.buffer = bytearray()
        self.closed = False

    def write(self, data: bytes) -> None:
        self.buffer.extend(data)

    async def drain(self) -> None:  # noqa: D102
        return None

    def close(self) -> None:
        self.closed = True


class FakeProc:
    def __init__(self, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
        self.stdin = FakeStreamWriter()
        self.stdout = FakeStreamReader(stdout)
        self.stderr = FakeStreamReader(stderr)
        self.returncode = returncode
        self.pid = 4242

    async def wait(self) -> int:
        return self.returncode

    def kill(self) -> None:
        self.returncode = -9


@pytest.mark.asyncio
async def test_prompt_goes_to_stdin_not_argv(monkeypatch):
    """C1 — un gros prompt (> MAX_ARG_STRLEN) ne doit JAMAIS être en argv ;
    il doit être écrit sur stdin. Garantit l'absence d'E2BIG."""
    captured: dict = {}
    fake = FakeProc(stdout=b"PONG", returncode=0)

    async def fake_exec(*args, **kwargs):
        captured["argv"] = args
        captured["stdin_kw"] = kwargs.get("stdin")
        return fake

    monkeypatch.setattr(claude_cli.asyncio, "create_subprocess_exec", fake_exec)

    big_prompt = "Z" * (MAX_ARG_STRLEN + 50_000)  # ~181 Ko, bien au-delà du cap
    result = await claude_cli.run_claude_subprocess(big_prompt, timeout_sec=10)

    # Le prompt n'est dans AUCUN argument de la ligne de commande.
    assert big_prompt not in captured["argv"]
    # Aucun argument ne dépasse MAX_ARG_STRLEN (donc pas d'E2BIG possible).
    assert all(len(str(a)) < MAX_ARG_STRLEN for a in captured["argv"])
    # stdin a été ouvert en PIPE et le prompt y a été écrit intégralement, puis fermé.
    assert captured["stdin_kw"] == asyncio.subprocess.PIPE
    assert fake.stdin.buffer.decode("utf-8") == big_prompt
    assert fake.stdin.closed is True
    # Sortie nominale.
    assert result["ok"] is True
    assert result["exit_code"] == 0
    assert "PONG" in result["stdout"]


@pytest.mark.asyncio
async def test_spawn_oserror_e2big_returns_failed_not_raises(monkeypatch):
    """C2 — une OSError E2BIG au spawn retourne ok=False (pas d'exception
    propagée), pour que _curate_one marque la row 'failed' au lieu d'orphelin."""

    async def fake_exec(*args, **kwargs):
        # Reproduit l'erreur observée le 2026-05-22 sur les 8 bundles.
        raise OSError(7, "Argument list too long", "/usr/bin/claude")

    monkeypatch.setattr(claude_cli.asyncio, "create_subprocess_exec", fake_exec)

    result = await claude_cli.run_claude_subprocess("x" * 200_000, timeout_sec=10)

    assert result["ok"] is False
    assert result["exit_code"] == -1
    assert result["timed_out"] is False
    assert "spawn" in result["stderr"].lower()


@pytest.mark.asyncio
async def test_spawn_filenotfound_exhausts_retries_then_failed(monkeypatch):
    """FileNotFoundError PERSISTANT (binaire jamais revenu) : retenté
    _SPAWN_MAX_ATTEMPTS fois, puis ok=False (caller marque 'failed', pas
    d'orphelin). Backoff mis à 0 pour rester rapide."""
    monkeypatch.setattr(claude_cli, "_SPAWN_RETRY_BACKOFF_SEC", (0, 0, 0))
    calls = {"n": 0}

    async def fake_exec(*args, **kwargs):
        calls["n"] += 1
        raise FileNotFoundError(2, "No such file or directory", "/usr/bin/claude")

    monkeypatch.setattr(claude_cli.asyncio, "create_subprocess_exec", fake_exec)

    result = await claude_cli.run_claude_subprocess("hello", timeout_sec=10)
    assert result["ok"] is False
    assert result["exit_code"] == -1
    # A bien retenté le nombre max de fois (et pas une seule).
    assert calls["n"] == claude_cli._SPAWN_MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_spawn_filenotfound_retries_then_succeeds(monkeypatch):
    """le binaire revient après le swap npm (claude root auto-update) :
    2 FileNotFoundError puis succès au 3e essai → ok=True. Le segment curator
    n'est PLUS perdu (régression du bug du 2026-05-23)."""
    monkeypatch.setattr(claude_cli, "_SPAWN_RETRY_BACKOFF_SEC", (0, 0, 0))
    calls = {"n": 0}
    fake = FakeProc(stdout=b"RECOVERED", returncode=0)

    async def fake_exec(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise FileNotFoundError(2, "No such file or directory", "/usr/bin/claude")
        return fake

    monkeypatch.setattr(claude_cli.asyncio, "create_subprocess_exec", fake_exec)

    result = await claude_cli.run_claude_subprocess("hello", timeout_sec=10)
    assert result["ok"] is True
    assert result["exit_code"] == 0
    assert "RECOVERED" in result["stdout"]
    assert calls["n"] == 3  # 2 échecs transitoires + 1 succès


@pytest.mark.asyncio
async def test_spawn_e2big_not_retried(monkeypatch):
    """une OSError NON-FileNotFound (E2BIG Errno 7) est PERMANENTE :
    elle ne doit PAS être retentée (un seul appel), retour ok=False immédiat."""
    monkeypatch.setattr(claude_cli, "_SPAWN_RETRY_BACKOFF_SEC", (0, 0, 0))
    calls = {"n": 0}

    async def fake_exec(*args, **kwargs):
        calls["n"] += 1
        raise OSError(7, "Argument list too long", "/usr/bin/claude")

    monkeypatch.setattr(claude_cli.asyncio, "create_subprocess_exec", fake_exec)

    result = await claude_cli.run_claude_subprocess("x" * 200_000, timeout_sec=10)
    assert result["ok"] is False
    assert result["exit_code"] == -1
    assert calls["n"] == 1  # pas de retry sur erreur permanente


@pytest.mark.asyncio
async def test_subprocess_success(monkeypatch):
    """Chemin nominal exit 0 (remplace l'ancien test communicate()-based)."""
    fake = FakeProc(stdout=b"hello world", returncode=0)

    async def fake_exec(*args, **kwargs):
        return fake

    monkeypatch.setattr(claude_cli.asyncio, "create_subprocess_exec", fake_exec)
    result = await claude_cli.run_claude_subprocess("test prompt", timeout_sec=10)

    assert result["ok"] is True
    assert result["exit_code"] == 0
    assert "hello world" in result["stdout"]
    assert result["timed_out"] is False


@pytest.mark.asyncio
async def test_subprocess_timeout(monkeypatch):
    """Hang → timeout déclenché, kill, ok=False (remplace l'ancien test cassé)."""

    class HangingReader:
        async def read(self, n: int = -1) -> bytes:
            await asyncio.sleep(60)
            return b""

    class HangingProc:
        def __init__(self) -> None:
            self.stdin = FakeStreamWriter()
            self.stdout = HangingReader()
            self.stderr = HangingReader()
            self.returncode = None
            self.pid = 8888

        async def wait(self) -> int:
            await asyncio.sleep(60)
            return -9

        def kill(self) -> None:
            self.returncode = -9

    async def fake_exec(*args, **kwargs):
        return HangingProc()

    monkeypatch.setattr(claude_cli.asyncio, "create_subprocess_exec", fake_exec)
    result = await claude_cli.run_claude_subprocess("test", timeout_sec=1)

    assert result["timed_out"] is True
    assert result["ok"] is False
    assert "TIMEOUT" in result["stderr"]
