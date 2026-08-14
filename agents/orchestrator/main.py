"""Agent ORCHESTRATEUR — Phase D.1 MVP : router /dev <prompt> vers developer.

Phase A : pur heartbeat (sync).
Phase C : async + bus.subscribe + handler ping/pong (via reply_chat_id).
Phase D.1 (MVP) :
  - Détecte préfixe `/dev <prompt>` dans les messages depuis le bridge Telegram.
  - POST kind=mission via /v1/atoms (audit trail BDD).
  - Forward agent_message à `claude-developer` avec source_ref.mission_id +
    propagation de source_ref.reply_chat_id.
  - Sur réception d'une réponse du developer (sender=claude-developer +
    source_ref.mission_id présent), relais au bridge avec reply_chat_id.

Phase E (prospective, non démarrée) :
  - Réintroduira kind=mission_proposal avec attente verdict auditor avant dispatch.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import signal
import sys
from typing import Any

import httpx

from app.api_token import entetes_api
from agents.lib import bus
from agents.lib.heartbeat import run_heartbeat_loop_async
from agents.lib.log_capture import MissionLogger

logger = logging.getLogger("arac.orchestrator")

_NODE_ID = "claude-orchestrator"
_BRIDGE_NODE_ID = "arac-telegram-bridge"
_DEVELOPER_NODE_ID = "claude-developer"
_DEV_PREFIX = "/dev "


def _setup_logging() -> None:
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def _api_url() -> str:
    return os.environ.get("ARAC_API_URL", "").rstrip("/")


async def _post_mission(prompt: str, requester_chat_id: int | str | None) -> dict[str, Any]:
    """POST kind=mission via /v1/atoms — audit trail d'une mission D.1.

    Retourne le dict atome (champ `id` notamment).
    """
    key = f"mission-d1-{secrets.token_hex(4)}"
    source_ref: dict[str, Any] = {"phase": "D.1"}
    if requester_chat_id is not None:
        source_ref["requester_chat_id"] = requester_chat_id

    payload = {
        "kind": "mission",
        "scope": "arac-strategie",
        "key": key,
        "value": prompt,
        "node_id": _NODE_ID,
        "source_ref": source_ref,
    }

    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.post(
            f"{_api_url()}/v1/atoms", json=payload, headers=entetes_api()
        )
        r.raise_for_status()
        return r.json()


async def _handle_incoming(atom: dict[str, Any]) -> None:
    """Handler bus orchestrator — Phase D.1 routing."""
    text = (atom.get("value") or "").strip()
    source_ref = atom.get("source_ref") or {}
    sender = source_ref.get("from", "unknown")
    reply_chat_id = source_ref.get("reply_chat_id")
    mission_id = source_ref.get("mission_id")

    logger.info(json.dumps({
        "event": "orchestrator.incoming",
        "atom_id": atom.get("id"),
        "from": sender,
        "text_preview": text[:80],
        "reply_chat_id": reply_chat_id,
        "mission_id": mission_id,
    }))

    # --- Cas 1 : réponse depuis le developer pour une mission en cours ---
    if sender == _DEVELOPER_NODE_ID and mission_id:
        try:
            await bus.send(
                from_node=_NODE_ID,
                to_node=_BRIDGE_NODE_ID,
                value=text,
                metadata={"reply_chat_id": reply_chat_id, "mission_id": mission_id},
            )
            logger.info(json.dumps({
                "event": "orchestrator.relay_dev_to_bridge",
                "mission_id": mission_id,
                "reply_chat_id": reply_chat_id,
            }))
        except Exception as e:  # noqa: BLE001
            logger.error(json.dumps({
                "event": "orchestrator.relay_fail",
                "mission_id": mission_id,
                "error": type(e).__name__,
                "detail": str(e)[:200],
            }))
        return

    # --- Cas 2 : commande /dev <prompt> depuis le bridge Telegram ---
    if text == "/dev" or text.startswith(_DEV_PREFIX):
        prompt = text[len(_DEV_PREFIX):].strip() if text.startswith(_DEV_PREFIX) else ""
        if not prompt:
            await _reply(sender, "Usage: /dev <prompt>", reply_chat_id=reply_chat_id)
            return

        try:
            mission_atom = await _post_mission(prompt, requester_chat_id=reply_chat_id)
            mission_id = mission_atom["id"]
        except Exception as e:  # noqa: BLE001
            logger.error(json.dumps({
                "event": "orchestrator.mission_post_fail",
                "error": type(e).__name__,
                "detail": str(e)[:200],
            }))
            await _reply(
                sender,
                f"❌ Erreur création mission: {type(e).__name__}",
                reply_chat_id=reply_chat_id,
            )
            return

        logger.info(json.dumps({
            "event": "orchestrator.mission_created",
            "mission_id": mission_id,
            "prompt_preview": prompt[:80],
        }))

        # Bloc 9a (D.4) : ouvre transcript en append, émet mission.start côté
        # orchestrator + dispatch. PAS de close() ici : le developer rouvrira
        # en append puis fermera dans mission.end (cf D4 §3.5).
        try:
            orch_log = MissionLogger(mission_id)
            orch_log.write_event(
                "mission.start",
                agent=_NODE_ID,
                prompt=prompt,
                reply_chat_id=reply_chat_id,
            )
            orch_log.write_event(
                "orchestrator.dispatch",
                to=_DEVELOPER_NODE_ID,
                mission_id=mission_id,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(json.dumps({
                "event": "orchestrator.transcript_init_fail",
                "mission_id": mission_id,
                "err": str(e)[:200],
            }))

        # Forward au developer avec mission_id + reply_chat_id propagé
        try:
            await bus.send(
                from_node=_NODE_ID,
                to_node=_DEVELOPER_NODE_ID,
                value=prompt,
                metadata={"mission_id": mission_id, "reply_chat_id": reply_chat_id},
            )
        except Exception as e:  # noqa: BLE001
            logger.error(json.dumps({
                "event": "orchestrator.dispatch_fail",
                "mission_id": mission_id,
                "error": type(e).__name__,
                "detail": str(e)[:200],
            }))
            await _reply(
                sender,
                f"❌ Mission {mission_id[:8]} créée mais dispatch developer échoué.",
                reply_chat_id=reply_chat_id,
            )
            return

        # Accusé de réception à l'utilisateur Telegram
        await _reply(
            sender,
            f"📋 Mission {mission_id[:8]} dispatchée au developer. En cours...",
            reply_chat_id=reply_chat_id,
            mission_id=mission_id,
        )
        return

    # --- Cas 3 : handler Phase C (ping/pong + stub) ---
    if text.lower() == "ping":
        reply_value = "pong"
    else:
        reply_value = f"orchestrator-stub: reçu '{text[:50]}'"

    await _reply(sender, reply_value, reply_chat_id=reply_chat_id)


async def _reply(
    to: str,
    value: str,
    *,
    reply_chat_id: int | str | None = None,
    mission_id: str | None = None,
) -> None:
    """Helper d'envoi avec propagation reply_chat_id + mission_id si présents."""
    metadata: dict[str, Any] = {}
    if reply_chat_id is not None:
        metadata["reply_chat_id"] = reply_chat_id
    if mission_id is not None:
        metadata["mission_id"] = mission_id
    try:
        await bus.send(from_node=_NODE_ID, to_node=to, value=value, metadata=metadata)
        logger.info(json.dumps({
            "event": "orchestrator.replied",
            "to": to,
            "reply": value[:50],
        }))
    except Exception as e:  # noqa: BLE001
        logger.error(json.dumps({
            "event": "orchestrator.reply_fail",
            "to": to,
            "error": type(e).__name__,
            "detail": str(e)[:200],
        }))


async def amain() -> int:
    _setup_logging()
    logger.info(json.dumps({
        "event": "boot.ok",
        "node_id": _NODE_ID,
        "phase": "D.1",
        "mode": "async + bus subscribe + handler /dev (MVP, no auditor)",
    }))

    stop_event = asyncio.Event()

    tasks = [
        asyncio.create_task(run_heartbeat_loop_async(stop_event=stop_event), name="heartbeat"),
        asyncio.create_task(
            bus.subscribe(_NODE_ID, _handle_incoming, stop_event=stop_event),
            name="bus_subscribe",
        ),
    ]

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info(json.dumps({"event": "shutdown.clean", "node_id": _NODE_ID}))
    return 0


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    sys.exit(main())
