"""Tests agent MONITOR — v0.4 Bloc 8.

Couverture :
- Detection exit non-zero via journalctl JSON output.
- Detection restart loop via systemctl NRestarts (mock subprocess).
- Detection OOM via "Out of memory" dans MESSAGE.
- Format message bus : "ALERT: <service> <reason>".
- arac-monitor.service est exclu de l'auto-surveillance.

Strategie : tous les appels subprocess (journalctl, systemctl) sont mockes
via monkeypatch. Pas de BDD ni systemd reel pour ces tests purement unitaires.

Le test de la boucle complete (asyncio.run de amain) n'est pas couvert ici
- il necessite journalctl + bus + BDD live, ce que valide le deploiement live
(heartbeats arac-monitor dans arac.nodes_heartbeat_history).
"""

from __future__ import annotations

import asyncio
import inspect
import subprocess
import time

import pytest

from agents.monitor import main as monitor_main


# ---------------------------------------------------------------------------
# Structure / contracts
# ---------------------------------------------------------------------------


def test_monitor_node_id_constant():
    assert monitor_main._NODE_ID == "arac-monitor"


def test_monitor_bridge_node_id_constant():
    assert monitor_main._BRIDGE_NODE_ID == "arac-telegram-bridge"


def test_monitor_amain_is_coroutine():
    assert inspect.iscoroutinefunction(monitor_main.amain)


def test_monitor_run_loop_is_coroutine():
    assert inspect.iscoroutinefunction(monitor_main.run_monitor_loop)


def test_monitored_services_excludes_self(monkeypatch):
    """Le moniteur ne doit JAMAIS se surveiller lui-meme (auto-surveillance)."""
    monkeypatch.setenv("ARAC_UNIT_PREFIX", "arac-zoe_brain")
    assert "arac-zoe_brain-monitor.service" not in monitor_main._monitored_services()


def test_monitored_services_porte_le_nom_du_cerveau(monkeypatch):
    """Les services surveillés sont ceux de CE cerveau, pas ceux du voisin.

    La liste était écrite en dur — « arac-api.service », « arac-auditor.service »…
    — c'est-à-dire les unités du PREMIER cerveau de la machine. Un moniteur
    d'essai rapportait donc la santé des unités de PRODUCTION : des voyants
    verts qui ne parlaient pas du cerveau qu'on surveillait.
    """
    monkeypatch.setenv("ARAC_UNIT_PREFIX", "arac-zoe_brain")
    services = set(monitor_main._monitored_services())
    attendus = {
        "arac-zoe_brain-api.service",
        "arac-zoe_brain-auditor.service",
        "arac-zoe_brain-developer.service",
        "arac-zoe_brain-orchestrator.service",
        "arac-zoe_brain-telegram-bridge.service",
    }
    assert attendus.issubset(services)
    assert not any(s.startswith("arac-api") for s in services)


def test_monitored_services_vide_sans_prefixe(monkeypatch):
    """Sans préfixe déclaré : on ne surveille RIEN plutôt que le voisin.

    Surveiller les unités d'un autre cerveau et rendre « tout va bien » est
    pire qu'une absence de surveillance : c'est un diagnostic qui se trompe de
    sujet, exactement comme le /healthz servi par l'usurpateur de l'incident.
    """
    monkeypatch.delenv("ARAC_UNIT_PREFIX", raising=False)
    assert monitor_main._monitored_services() == ()


# ---------------------------------------------------------------------------
# Detection exit non-zero
# ---------------------------------------------------------------------------


def test_detect_exit_nonzero_main_process_exited():
    """Detecte 'Main process exited, code=exited, status=2'."""
    entries = [
        {
            "_SYSTEMD_UNIT": "arac-developer.service",
            "MESSAGE": "arac-developer.service: Main process exited, code=exited, status=2/INVALIDARGUMENT",
        }
    ]
    alerts = monitor_main.detect_exit_nonzero(entries)
    assert len(alerts) == 1
    assert alerts[0]["service"] == "arac-developer.service"
    assert "exit_nonzero" in alerts[0]["reason"]


def test_detect_exit_nonzero_failed_result():
    """Detecte UNIT_RESULT='failed'."""
    entries = [
        {
            "_SYSTEMD_UNIT": "arac-auditor.service",
            "MESSAGE": "arac-auditor.service: Failed with result 'exit-code'.",
            "UNIT_RESULT": "failed",
        }
    ]
    alerts = monitor_main.detect_exit_nonzero(entries)
    assert len(alerts) == 1
    assert alerts[0]["service"] == "arac-auditor.service"


def test_detect_exit_nonzero_ignores_status_0():
    """status=0 = exit propre, pas d'alerte."""
    entries = [
        {
            "_SYSTEMD_UNIT": "arac-backup.service",
            "MESSAGE": "arac-backup.service: Main process exited, code=exited, status=0/SUCCESS",
        }
    ]
    alerts = monitor_main.detect_exit_nonzero(entries)
    assert alerts == []


def test_detect_exit_nonzero_ignores_non_arac():
    """Services hors arac-* ignores."""
    entries = [
        {
            "_SYSTEMD_UNIT": "postgresql.service",
            "MESSAGE": "postgresql.service: Failed with result 'exit-code'.",
            "UNIT_RESULT": "failed",
        }
    ]
    alerts = monitor_main.detect_exit_nonzero(entries)
    assert alerts == []


def test_detect_exit_nonzero_excludes_monitor_itself():
    """arac-monitor.service ne doit jamais s'auto-signaler."""
    entries = [
        {
            "_SYSTEMD_UNIT": "arac-monitor.service",
            "MESSAGE": "arac-monitor.service: Failed with result 'exit-code'.",
            "UNIT_RESULT": "failed",
        }
    ]
    alerts = monitor_main.detect_exit_nonzero(entries)
    assert alerts == []


def test_detect_exit_nonzero_dedup_same_unit():
    """Plusieurs entries pour le meme service = 1 seule alerte."""
    entries = [
        {
            "_SYSTEMD_UNIT": "arac-developer.service",
            "MESSAGE": "arac-developer.service: Main process exited, code=exited, status=1",
        },
        {
            "_SYSTEMD_UNIT": "arac-developer.service",
            "MESSAGE": "arac-developer.service: Failed with result 'exit-code'.",
            "UNIT_RESULT": "failed",
        },
    ]
    alerts = monitor_main.detect_exit_nonzero(entries)
    assert len(alerts) == 1


# ---------------------------------------------------------------------------
# Detection OOM
# ---------------------------------------------------------------------------


def test_detect_oom_with_systemd_unit():
    """OOM avec _SYSTEMD_UNIT directement."""
    entries = [
        {
            "_SYSTEMD_UNIT": "arac-developer.service",
            "MESSAGE": "Out of memory: Killed process 12345 (python)",
        }
    ]
    alerts = monitor_main.detect_oom(entries)
    assert len(alerts) == 1
    assert alerts[0]["service"] == "arac-developer.service"
    assert "oom" in alerts[0]["reason"]


def test_detect_oom_kernel_message_with_unit_in_text(monkeypatch):
    """OOM kernel sans _SYSTEMD_UNIT mais nom de service dans le message.

    Le nom cherché porte le préfixe de CE cerveau : sur une machine à deux
    cerveaux, un OOM tuant l'orchestrateur du voisin ne doit pas lever une
    alerte au nom du nôtre.
    """
    monkeypatch.setenv("ARAC_UNIT_PREFIX", "arac-zoe_brain")
    entries = [
        {
            "MESSAGE": "Out of memory: arac-zoe_brain-orchestrator killed",
        }
    ]
    alerts = monitor_main.detect_oom(entries)
    # Le pattern matche le nom de service dans le message (lowercase)
    assert len(alerts) == 1
    assert alerts[0]["service"] == "arac-zoe_brain-orchestrator.service"


def test_detect_oom_no_match():
    """Pas d'OOM = pas d'alerte."""
    entries = [
        {
            "_SYSTEMD_UNIT": "arac-api.service",
            "MESSAGE": "INFO: heartbeat ok",
        }
    ]
    alerts = monitor_main.detect_oom(entries)
    assert alerts == []


# ---------------------------------------------------------------------------
# Detection restart loop (via systemctl NRestarts mock)
# ---------------------------------------------------------------------------


def test_detect_restart_loop_below_threshold(monkeypatch):
    """NRestarts qui monte mais moins que threshold = pas d'alerte."""
    # Mock systemctl show: NRestarts=2 (en dessous du threshold=3)
    def fake_get_nrestarts(svc):
        return 2 if svc == "arac-developer.service" else 0
    monkeypatch.setattr(monitor_main, "get_nrestarts", fake_get_nrestarts)

    state: dict = {}
    now = time.time()
    # On simule 2 ticks ou NRestarts a augmente (de 0 a 1 puis a 2)
    state["arac-developer.service"] = {"last_count": 0, "tx": [], "last_alert_count": -1}
    # Tick 1 : 0 -> 1 (mais on a mock a 2 direct, donc 0->2 en un tick)
    alerts = monitor_main.detect_restart_loop(
        ["arac-developer.service"],
        state,
        threshold=3,
        window_sec=300,
        now=now,
    )
    # 1 increment seul, en dessous de threshold=3
    assert alerts == []


def test_detect_restart_loop_above_threshold(monkeypatch):
    """NRestarts qui monte X fois >= threshold en window = alerte."""
    counter = {"n": 3}
    def fake_get_nrestarts(svc):
        if svc == "arac-developer.service":
            return counter["n"]
        return 0
    monkeypatch.setattr(monitor_main, "get_nrestarts", fake_get_nrestarts)

    state: dict = {}
    now = time.time()
    # 3 ticks consecutifs ou NRestarts augmente : 3, 4, 5
    monitor_main.detect_restart_loop(["arac-developer.service"], state, 3, 300, now - 200)
    counter["n"] = 4
    monitor_main.detect_restart_loop(["arac-developer.service"], state, 3, 300, now - 100)
    counter["n"] = 5
    alerts = monitor_main.detect_restart_loop(["arac-developer.service"], state, 3, 300, now)

    assert len(alerts) == 1
    assert alerts[0]["service"] == "arac-developer.service"
    assert "restart_loop" in alerts[0]["reason"]


def test_detect_restart_loop_outside_window(monkeypatch):
    """Restarts hors fenetre = expires, pas d'alerte."""
    counter = {"n": 3}
    def fake_get_nrestarts(svc):
        if svc == "arac-developer.service":
            return counter["n"]
        return 0
    monkeypatch.setattr(monitor_main, "get_nrestarts", fake_get_nrestarts)

    state: dict = {}
    now = time.time()
    # Premier increment il y a 1000s (hors fenetre 300s)
    monitor_main.detect_restart_loop(["arac-developer.service"], state, 3, 300, now - 1000)
    counter["n"] = 4
    monitor_main.detect_restart_loop(["arac-developer.service"], state, 3, 300, now - 500)
    counter["n"] = 5
    # Au moment de l'appel "now", les 2 premiers sont expires (>300s)
    alerts = monitor_main.detect_restart_loop(["arac-developer.service"], state, 3, 300, now)

    # Au "now" final, seul l'increment now-500 est expire ou pas selon window.
    # Avec window=300 : cutoff = now - 300. now-1000 et now-500 sont expires.
    # Donc tx = [] au moment du dernier call -> pas d'alerte.
    assert alerts == []


def test_detect_restart_loop_excludes_monitor(monkeypatch):
    """arac-monitor.service jamais surveille pour restart loop."""
    def fake_get_nrestarts(svc):
        return 99  # threshold largement depasse
    monkeypatch.setattr(monitor_main, "get_nrestarts", fake_get_nrestarts)

    state: dict = {}
    alerts = monitor_main.detect_restart_loop(
        ["arac-monitor.service", "arac-developer.service"],
        state,
        threshold=3,
        window_sec=300,
        now=time.time(),
    )
    # Aucun arac-monitor.service dans les alertes
    for a in alerts:
        assert a["service"] != "arac-monitor.service"


# ---------------------------------------------------------------------------
# Format message bus
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_alert_format(monkeypatch):
    """Le bus.send doit etre appele avec value='ALERT: <service> <reason>'."""
    calls: list[dict] = []

    async def fake_bus_send(*, from_node, to_node, value, metadata=None, timeout_sec=5.0):
        calls.append({
            "from_node": from_node,
            "to_node": to_node,
            "value": value,
            "metadata": metadata,
        })
        return {"id": "fake-atom-id"}

    monkeypatch.setattr(monitor_main.bus, "send", fake_bus_send)

    await monitor_main.send_alert("arac-developer.service", "exit_nonzero: crash")

    assert len(calls) == 1
    call = calls[0]
    assert call["from_node"] == "arac-monitor"
    assert call["to_node"] == "arac-telegram-bridge"
    assert call["value"] == "ALERT: arac-developer.service exit_nonzero: crash"
    assert call["metadata"]["type"] == "monitor_alert"
    assert call["metadata"]["service"] == "arac-developer.service"
    assert call["metadata"]["reason"] == "exit_nonzero: crash"


# ---------------------------------------------------------------------------
# fetch_journal_lines (subprocess mock)
# ---------------------------------------------------------------------------


def test_fetch_journal_lines_parses_json(monkeypatch):
    """Parse les lignes JSON output de journalctl."""
    stdout = (
        '{"_SYSTEMD_UNIT": "arac-api.service", "MESSAGE": "boot ok"}\n'
        '{"_SYSTEMD_UNIT": "arac-developer.service", "MESSAGE": "tick"}\n'
        '\n'  # ligne vide ignoree
        'not json\n'  # ligne invalide ignoree silencieusement
    )

    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    fake_result = FakeResult()
    fake_result.stdout = stdout
    monkeypatch.setattr(
        monitor_main.subprocess,
        "run",
        lambda *a, **kw: fake_result,
    )

    entries = monitor_main.fetch_journal_lines(60)
    assert len(entries) == 2
    assert entries[0]["_SYSTEMD_UNIT"] == "arac-api.service"
    assert entries[1]["_SYSTEMD_UNIT"] == "arac-developer.service"


def test_fetch_journal_lines_handles_failure(monkeypatch):
    """Si journalctl exit != 0, retourne [] sans crash."""
    class FakeResult:
        returncode = 1
        stdout = ""
        stderr = "permission denied"

    monkeypatch.setattr(
        monitor_main.subprocess,
        "run",
        lambda *a, **kw: FakeResult(),
    )

    entries = monitor_main.fetch_journal_lines(60)
    assert entries == []


def test_fetch_journal_lines_handles_missing_binary(monkeypatch):
    """Si journalctl absent (FileNotFoundError), retourne [] sans crash."""
    def raise_fnf(*a, **kw):
        raise FileNotFoundError("journalctl")

    monkeypatch.setattr(monitor_main.subprocess, "run", raise_fnf)
    entries = monitor_main.fetch_journal_lines(60)
    assert entries == []


# ---------------------------------------------------------------------------
# get_nrestarts (subprocess mock)
# ---------------------------------------------------------------------------


def test_get_nrestarts_parses_value(monkeypatch):
    """systemctl show -p NRestarts --value retourne un int parseable."""
    class FakeResult:
        returncode = 0
        stdout = "5\n"
        stderr = ""

    monkeypatch.setattr(
        monitor_main.subprocess,
        "run",
        lambda *a, **kw: FakeResult(),
    )

    n = monitor_main.get_nrestarts("arac-developer.service")
    assert n == 5


def test_get_nrestarts_returns_minus_one_on_error(monkeypatch):
    """En cas d'erreur (rc != 0), retourne -1 (sentinelle 'inconnu')."""
    class FakeResult:
        returncode = 1
        stdout = ""
        stderr = "no such unit"

    monkeypatch.setattr(
        monitor_main.subprocess,
        "run",
        lambda *a, **kw: FakeResult(),
    )

    n = monitor_main.get_nrestarts("arac-doesnotexist.service")
    assert n == -1
