"""Helper heartbeat partagé par les agents systemd.

Phase A — squelette sync. Le helper ne fait QUE le heartbeat ; la logique
métier (lecture atomes, dispatch missions, audit diff) arrive en Phase B+.
Phase C — ajout de run_heartbeat_loop_async pour les agents qui combinent
heartbeat + bus subscribe (orchestrator, telegram_bridge).

Mécanique sync (Phase A) :
  - Boucle infinie : POST /v1/heartbeat toutes les `HEARTBEAT_INTERVAL_SEC` secondes.
  - SIGTERM (systemctl stop) : exit propre, dernier heartbeat optionnel, code 0.
  - SIGINT (Ctrl-C) : idem.
  - HTTPError ou ConnectError : log warn, attendre, retenter au prochain tick.

Mécanique async (Phase C) :
  - Coroutine `run_heartbeat_loop_async(stop_event)` — même comportement mais
    asyncio-friendly, conçue pour `asyncio.gather` avec bus.subscribe().
  - SIGTERM/SIGINT handlers définis APRÈS asyncio.run() au niveau du main.

Variables d'env (lues au boot, fail-fast si manquantes) :
  - ARAC_NODE_ID         (obligatoire) — node_id auquel le heartbeat est attribué
  - ARAC_API_URL         (obligatoire — aucun défaut, voir plus bas)
  - ARAC_HEARTBEAT_SEC   (défaut 30)
  - ARAC_HEARTBEAT_TIMEOUT_SEC (défaut 5)

Logging :
  - stderr en JSON simple (capté par journald via systemd).
  - Pas de jsonlogger ici (dépendance app/) — agents minimaux.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time
from typing import Any

import httpx

from app.api_token import entetes_api
from app.journal import raison

logger = logging.getLogger("arac.agent")

_SHUTDOWN = False


def _handle_signal(signum: int, _frame: Any) -> None:
    global _SHUTDOWN
    logger.info(
        json.dumps({"event": "shutdown.signal_received", "signal": signum})
    )
    _SHUTDOWN = True


def _setup_logging() -> None:
    """JSON simple sur stderr — capté par journald via systemd."""
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def run_heartbeat_loop() -> int:
    """Boucle heartbeat. Retourne le code de sortie process.

    Lit la config via env vars (fail-fast si ARAC_NODE_ID manquant).
    Exit propre sur SIGTERM/SIGINT (code 0).
    """
    _setup_logging()

    node_id = os.environ.get("ARAC_NODE_ID")
    if not node_id:
        logger.error(json.dumps({"event": "boot.fail", "reason": "ARAC_NODE_ID manquant"}))
        return 2

    api_url = os.environ.get("ARAC_API_URL", "").rstrip("/")
    interval = float(os.environ.get("ARAC_HEARTBEAT_SEC", "30"))
    timeout = float(os.environ.get("ARAC_HEARTBEAT_TIMEOUT_SEC", "5"))

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info(json.dumps({
        "event": "boot.ok",
        "node_id": node_id,
        "api_url": api_url,
        "interval_sec": interval,
    }))

    consecutive_failures = 0
    while not _SHUTDOWN:
        try:
            with httpx.Client(timeout=timeout) as client:
                r = client.post(
                    f"{api_url}/v1/heartbeat",
                    json={"node_id": node_id, "metadata": {"phase": "A"}},
                    headers=entetes_api(),
                )
                r.raise_for_status()
            consecutive_failures = 0
            logger.info(json.dumps({
                "event": "heartbeat.ok",
                "node_id": node_id,
                "status": r.status_code,
            }))
        except (httpx.HTTPError, httpx.ConnectError) as e:
            consecutive_failures += 1
            logger.warning(json.dumps({
                "event": "heartbeat.fail",
                "node_id": node_id,
                "error": type(e).__name__,
                "raison": raison(e),
                "consecutive_failures": consecutive_failures,
            }))
        except Exception as e:  # noqa: BLE001
            logger.error(json.dumps({
                "event": "heartbeat.unexpected_error",
                "node_id": node_id,
                "error": type(e).__name__,
                "raison": raison(e),
            }))

        # Sleep interruptible : poll _SHUTDOWN toutes les 1s pour réactivité SIGTERM.
        slept = 0.0
        while slept < interval and not _SHUTDOWN:
            time.sleep(1.0)
            slept += 1.0

    logger.info(json.dumps({"event": "shutdown.clean", "node_id": node_id}))
    return 0


# ---------------------------------------------------------------------------
# Variante async — Phase C+ pour agents combinant heartbeat + bus subscribe.
# ---------------------------------------------------------------------------


async def run_heartbeat_loop_async(stop_event: asyncio.Event | None = None) -> int:
    """Variante asyncio de run_heartbeat_loop().

    Conçue pour `asyncio.gather(heartbeat_task, subscribe_task)`. Termine
    quand `stop_event` est set OU sur SIGTERM/SIGINT signal classique.
    """
    _setup_logging()

    node_id = os.environ.get("ARAC_NODE_ID")
    if not node_id:
        logger.error(json.dumps({"event": "boot.fail", "reason": "ARAC_NODE_ID manquant"}))
        return 2

    api_url = os.environ.get("ARAC_API_URL", "").rstrip("/")
    interval = float(os.environ.get("ARAC_HEARTBEAT_SEC", "30"))
    timeout = float(os.environ.get("ARAC_HEARTBEAT_TIMEOUT_SEC", "5"))

    logger.info(json.dumps({
        "event": "boot.ok",
        "node_id": node_id,
        "api_url": api_url,
        "interval_sec": interval,
        "mode": "async",
    }))

    consecutive_failures = 0
    while True:
        if stop_event is not None and stop_event.is_set():
            break
        if _SHUTDOWN:
            break
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(
                    f"{api_url}/v1/heartbeat",
                    json={"node_id": node_id, "metadata": {"phase": "C", "mode": "async"}},
                    headers=entetes_api(),
                )
                r.raise_for_status()
            consecutive_failures = 0
            logger.info(json.dumps({
                "event": "heartbeat.ok",
                "node_id": node_id,
                "status": r.status_code,
            }))
        except (httpx.HTTPError, httpx.ConnectError) as e:
            consecutive_failures += 1
            logger.warning(json.dumps({
                "event": "heartbeat.fail",
                "node_id": node_id,
                "error": type(e).__name__,
                "raison": raison(e),
                "consecutive_failures": consecutive_failures,
            }))
        except Exception as e:  # noqa: BLE001
            logger.error(json.dumps({
                "event": "heartbeat.unexpected_error",
                "node_id": node_id,
                "error": type(e).__name__,
                "raison": raison(e),
            }))

        # Sleep interruptible asyncio
        try:
            await asyncio.wait_for(
                stop_event.wait() if stop_event else asyncio.sleep(interval),
                timeout=interval if stop_event else None,
            )
            break  # stop_event set during sleep
        except asyncio.TimeoutError:
            pass  # tick écoulé, continue
        except asyncio.CancelledError:
            break

    logger.info(json.dumps({"event": "shutdown.clean.async", "node_id": node_id}))
    return 0
