"""Service ARAC Telegram bridge — Phase C triade.

Architecture (phase C) :

  Telegram (l'opérateur, depuis son téléphone)
    ⇕ HTTP long-polling Bot API
  arac-telegram-bridge (ce service, node_id=arac-telegram-bridge)
    ⇕ bus inter-agent (PG LISTEN/NOTIFY + agent_message)
  claude-orchestrator (subscribe inbox + handler ping→pong)

Flux ENTRANT (opérateur → orchestrateur) :
  1. Bridge poll GET https://api.telegram.org/bot<TOKEN>/getUpdates (long-poll 25s)
  2. Pour chaque message :
     - Whitelist chat_id check (TELEGRAM_ALLOWED_CHAT_IDS env)
     - Si pas whitelisté → log "telegram.unauthorized" + ignore silencieux
     - Si whitelisté → bus.send(to=claude-orchestrator, from=arac-telegram-bridge,
       value=<texte>, metadata={"reply_chat_id": <int>, "command": <text>})

Flux SORTANT (orchestrateur → opérateur) :
  1. Bridge subscribe son inbox bus (agent_inbox_arac_telegram_bridge)
  2. Pour chaque agent_message reçu :
     - Extrait source_ref.reply_chat_id (le bridge l'avait posé en émettant l'entrée)
     - POST https://api.telegram.org/bot<TOKEN>/sendMessage
     - Si reply_chat_id absent → log "telegram.outbound.no_chat_id" + skip

3 coroutines tournent en parallèle :
  - run_heartbeat_loop_async (heartbeat /v1/heartbeat toutes 30s)
  - telegram_poll_loop (entrée Telegram → bus)
  - bus.subscribe (sortie bus → Telegram)

Phase C MINIMUM : ping → pong via orchestrator. La logique "go <mission>" →
kind=mission_proposal arrive en Phase D (migration alembic 0003 ajoutera
les kinds mission_proposal / mission / mission_done).

Env vars (lues au boot, fail-fast si TOKEN ou CHAT_IDS manquants) :
  - TELEGRAM_BOT_TOKEN         (obligatoire)
  - TELEGRAM_ALLOWED_CHAT_IDS  (obligatoire, format "12345" ou "12345,67890")
  - TELEGRAM_POLL_INTERVAL_SEC (défaut 25)
  - TELEGRAM_POLL_TIMEOUT_SEC  (défaut 30)
  - ARAC_NODE_ID               (forcé à arac-telegram-bridge par systemd Environment=)
  - ARAC_API_URL, DATABASE_URL_APP, etc. : héritées du EnvironmentFile=.env
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any

import httpx

from agents.lib import bus
from agents.lib.heartbeat import run_heartbeat_loop_async

logger = logging.getLogger("arac.telegram_bridge")

_BRIDGE_NODE_ID = "arac-telegram-bridge"
_ORCHESTRATOR_NODE_ID = "claude-orchestrator"


def _setup_logging() -> None:
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def _parse_chat_ids(raw: str) -> set[int]:
    return {int(x.strip()) for x in raw.split(",") if x.strip()}


def _config_or_raise() -> tuple[str, set[int], float, float]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_ids_raw = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN manquant — bridge ne peut pas démarrer")
    if not chat_ids_raw:
        raise RuntimeError("TELEGRAM_ALLOWED_CHAT_IDS manquant — pas de whitelist = pas de bridge")
    chat_ids = _parse_chat_ids(chat_ids_raw)
    poll_interval = float(os.environ.get("TELEGRAM_POLL_INTERVAL_SEC", "25"))
    poll_timeout = float(os.environ.get("TELEGRAM_POLL_TIMEOUT_SEC", "30"))
    return token, chat_ids, poll_interval, poll_timeout


# ---------------------------------------------------------------------------
# Flux ENTRANT — Telegram → bus → orchestrator
# ---------------------------------------------------------------------------


async def telegram_poll_loop(
    token: str,
    allowed_chat_ids: set[int],
    poll_interval: float,
    poll_timeout: float,
    stop_event: asyncio.Event,
) -> None:
    """Long-poll Telegram getUpdates, route les messages whitelist vers le bus."""
    api_base = f"https://api.telegram.org/bot{token}"
    offset = 0  # in-memory ; redémarrage = replay des updates non-acquittés (Telegram retient ~24h)

    async with httpx.AsyncClient(timeout=poll_timeout + 5) as client:
        while not stop_event.is_set():
            try:
                r = await client.get(
                    f"{api_base}/getUpdates",
                    params={"offset": offset, "timeout": int(poll_interval)},
                )
                r.raise_for_status()
                body = r.json()
                if not body.get("ok"):
                    logger.warning(json.dumps({
                        "event": "telegram.getupdates.not_ok",
                        "body": str(body)[:200],
                    }))
                    await asyncio.sleep(5)
                    continue

                for update in body.get("result", []):
                    offset = max(offset, update["update_id"] + 1)
                    await _process_update(update, allowed_chat_ids)

            except httpx.HTTPError as e:
                logger.warning(json.dumps({
                    "event": "telegram.poll.http_error",
                    "error": type(e).__name__,
                    "detail": str(e)[:200],
                }))
                await asyncio.sleep(5)
            except Exception as e:  # noqa: BLE001
                logger.error(json.dumps({
                    "event": "telegram.poll.unexpected",
                    "error": type(e).__name__,
                    "detail": str(e)[:200],
                }))
                await asyncio.sleep(5)


async def _process_update(update: dict[str, Any], allowed_chat_ids: set[int]) -> None:
    msg = update.get("message")
    if not msg or not msg.get("text"):
        return
    chat_id = msg.get("chat", {}).get("id")
    if chat_id not in allowed_chat_ids:
        logger.warning(json.dumps({
            "event": "telegram.unauthorized",
            "chat_id": chat_id,
            "text_preview": str(msg.get("text"))[:50],
        }))
        return

    text = msg["text"].strip()
    logger.info(json.dumps({
        "event": "telegram.incoming",
        "chat_id": chat_id,
        "text": text[:200],
    }))

    # Forward vers l'orchestrator via le bus.
    try:
        await bus.send(
            from_node=_BRIDGE_NODE_ID,
            to_node=_ORCHESTRATOR_NODE_ID,
            value=text,
            metadata={"reply_chat_id": chat_id, "command": text},
        )
    except Exception as e:  # noqa: BLE001
        logger.error(json.dumps({
            "event": "telegram.bus_send_fail",
            "error": type(e).__name__,
            "detail": str(e)[:200],
        }))


# ---------------------------------------------------------------------------
# Flux SORTANT — bus inbox → Telegram sendMessage
# ---------------------------------------------------------------------------


async def outbound_handler(token: str, atom: dict[str, Any]) -> None:
    """Handler appelé pour chaque agent_message reçu sur l'inbox du bridge."""
    source_ref = atom.get("source_ref") or {}
    chat_id = source_ref.get("reply_chat_id")
    if chat_id is None:
        logger.warning(json.dumps({
            "event": "telegram.outbound.no_chat_id",
            "atom_id": atom.get("id"),
            "source_ref": source_ref,
        }))
        return
    text = atom.get("value", "")
    api_base = f"https://api.telegram.org/bot{token}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{api_base}/sendMessage",
                json={"chat_id": chat_id, "text": text},
            )
            r.raise_for_status()
        logger.info(json.dumps({
            "event": "telegram.outbound.sent",
            "chat_id": chat_id,
            "atom_id": atom.get("id"),
        }))
    except httpx.HTTPError as e:
        logger.warning(json.dumps({
            "event": "telegram.outbound.http_error",
            "chat_id": chat_id,
            "error": type(e).__name__,
            "detail": str(e)[:200],
        }))


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


async def amain() -> int:
    _setup_logging()
    try:
        token, chat_ids, poll_interval, poll_timeout = _config_or_raise()
    except RuntimeError as e:
        logger.error(json.dumps({"event": "boot.fail", "reason": str(e)}))
        return 2

    logger.info(json.dumps({
        "event": "boot.ok",
        "node_id": _BRIDGE_NODE_ID,
        "allowed_chat_ids": sorted(chat_ids),
        "poll_interval_sec": poll_interval,
    }))

    stop_event = asyncio.Event()

    async def _outbound_wrapper(atom):
        await outbound_handler(token, atom)

    tasks = [
        asyncio.create_task(run_heartbeat_loop_async(stop_event=stop_event), name="heartbeat"),
        asyncio.create_task(
            telegram_poll_loop(token, chat_ids, poll_interval, poll_timeout, stop_event),
            name="telegram_poll",
        ),
        asyncio.create_task(
            bus.subscribe(_BRIDGE_NODE_ID, _outbound_wrapper, stop_event=stop_event),
            name="bus_subscribe",
        ),
    ]

    # SIGTERM/SIGINT → set stop_event proprement.
    loop = asyncio.get_running_loop()
    import signal as _signal  # noqa: PLC0415
    for sig in (_signal.SIGTERM, _signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info(json.dumps({"event": "shutdown.clean", "node_id": _BRIDGE_NODE_ID}))
    return 0


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    sys.exit(main())
