"""Bus de communication inter-agents — Phase B triade.

Architecture :

  - SEND : un agent A crée un atome `kind=agent_message` via POST /v1/atoms
    avec `source_ref={"to": "<node_id_B>", "from": "<node_id_A>"}`.
    Le trigger PG `tg_agent_message_notify` (migration 0002) émet alors
    `pg_notify('agent_inbox_<sanitized_B>', atom_id)`.

  - SUBSCRIBE : l'agent B ouvre une AsyncConnection psycopg en autocommit,
    `LISTEN agent_inbox_<sanitized_B>`, et itère sur `conn.notifies()`. Pour
    chaque NOTIFY reçu, il fetch l'atome via GET /v1/atoms/{id} et passe à
    son handler.

Convention canal : `agent_inbox_<node_id.replace('-', '_')>` — la
sanitization évite le quoting d'identifier PG côté LISTEN.

Reconnexion (risque #1 Phase B) : boucle `while not _shutdown:` avec
backoff exponentiel 1s → 2s → 4s → 8s → 16s → 30s plafond, LISTEN
re-souscrit à chaque reconnect.

Env vars utilisées :
  - ARAC_API_URL              obligatoire (aucun défaut, voir plus bas)
  - ARAC_API_BEARER_TOKEN     le jeton porteur, exigé par l'API de TOUTE
                              requête depuis que la boucle locale n'est plus
                              une exemption (`app/auth.py`). Il est déjà dans
                              l'environnement des unités systemd ; on ne le
                              lit jamais soi-même, `app/api_token.py` s'en
                              charge pour tous les appelants du dépôt.
  - DATABASE_URL_APP          obligatoire pour subscribe() (LISTEN PG)
  - ARAC_SCOPE_AGENT_MESSAGE  scope des atomes de bus. Sans valeur, il est
                              DÉDUIT de votre taxonomie (cf `_default_scope`).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from typing import Any, AsyncIterator, Awaitable, Callable

import httpx
import psycopg

from app.api_token import entetes_api
from app.journal import raison

logger = logging.getLogger("arac.bus")

_BACKOFF_SEQUENCE_SEC = (1, 2, 4, 8, 16, 30)


def _default_scope() -> str:
    """Où ranger un message de bus quand personne n'a rien dit.

    AUCUN scope n'est écrit en dur ici, et c'est le point : un scope hérité
    d'une autre taxonomie n'existerait pas dans la vôtre, et chaque message
    de bus partirait en 422 (l'énumération de l'API le refuserait) sans que
    rien ne dise pourquoi.

    On prend donc une FEUILLE réelle de votre taxonomie, en préférant celle
    qui parle d'outillage — un message d'agent est de la mécanique, pas du
    savoir. À défaut, la première feuille par ordre alphabétique : stable
    d'un démarrage à l'autre, ce qui compte plus que d'être « la bonne ».

    Pour choisir vous-même : ARAC_SCOPE_AGENT_MESSAGE="racine/feuille".
    """
    from app.schemas.scope import LEAVES

    feuilles = sorted(LEAVES)
    if not feuilles:
        raise RuntimeError(
            "aucun scope déclaré — lancez `python3 bootstrap/wizard.py` puis "
            "`make scopes` avant de démarrer le bus."
        )
    for prefixe in ("outillage/", "outil"):
        for f in feuilles:
            if f.startswith(prefixe):
                return f
    return feuilles[0]


def _channel_for(node_id: str) -> str:
    """Sanitize un node_id en nom de canal PG (remplace `-` par `_`)."""
    return f"agent_inbox_{node_id.replace('-', '_')}"


def _api_url() -> str:
    return os.environ.get("ARAC_API_URL", "").rstrip("/")


def _agent_message_scope() -> str:
    return os.environ.get("ARAC_SCOPE_AGENT_MESSAGE") or _default_scope()


def _dsn_or_raise() -> str:
    dsn = os.environ.get("DATABASE_URL_APP")
    if not dsn:
        raise RuntimeError(
            "DATABASE_URL_APP non défini — subscribe() impossible. "
            "Vérifier $ARAC_HOME/.env (mode 0600) et "
            "EnvironmentFile= du service systemd."
        )
    return dsn


# ---------------------------------------------------------------------------
# SEND
# ---------------------------------------------------------------------------


async def send(
    *,
    from_node: str,
    to_node: str,
    value: str,
    metadata: dict[str, Any] | None = None,
    timeout_sec: float = 5.0,
) -> dict[str, Any]:
    """Envoie un agent_message de `from_node` vers `to_node`.

    Le payload `value` est le corps du message (libre, sera embeddé par l'API).
    `metadata` est mergé dans `source_ref` à côté de `to`/`from` (utile pour
    `dispute_hash`, `mission_id`, etc. en Phases ultérieures).

    Retourne le dict atome retourné par l'API (champ `id` notamment).
    """
    key = f"msg-{from_node}-to-{to_node}-{secrets.token_hex(4)}"
    source_ref: dict[str, Any] = {"to": to_node, "from": from_node}
    if metadata:
        source_ref.update(metadata)

    payload = {
        "kind": "agent_message",
        "scope": _agent_message_scope(),
        "key": key,
        "value": value,
        "node_id": from_node,
        "source_ref": source_ref,
    }

    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        r = await client.post(f"{_api_url()}/v1/atoms", json=payload,
                              headers=entetes_api())
        r.raise_for_status()
        return r.json()


async def fetch_atom(atom_id: str, timeout_sec: float = 5.0) -> dict[str, Any]:
    """GET /v1/atoms/{id} — utilisé par subscribe pour matérialiser un NOTIFY."""
    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        r = await client.get(f"{_api_url()}/v1/atoms/{atom_id}",
                             headers=entetes_api())
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# SUBSCRIBE
# ---------------------------------------------------------------------------


async def listen_inbox(node_id: str) -> AsyncIterator[dict[str, Any]]:
    """Itérateur async qui yield les atomes reçus pour `node_id`.

    Reconnect automatique avec backoff exponentiel sur perte de connexion PG.
    Sortie : appeler `aclose()` sur l'itérateur (ou casser la boucle consommatrice).

    Usage :
        async for msg in listen_inbox("claude-developer"):
            print(msg["value"])
    """
    channel = _channel_for(node_id)
    dsn = _dsn_or_raise()
    backoff_idx = 0

    while True:
        try:
            async with await psycopg.AsyncConnection.connect(
                dsn, autocommit=True
            ) as conn:
                # IMPORTANT : channel name doit être un identifier SQL sûr.
                # _channel_for() garantit que node_id n'a que [a-z0-9_].
                await conn.execute(f"LISTEN {channel}")
                logger.info(
                    json.dumps({"event": "bus.listening", "node_id": node_id, "channel": channel})
                )
                backoff_idx = 0  # reset après une connexion réussie

                async for notify in conn.notifies():
                    atom_id = notify.payload
                    try:
                        atom = await fetch_atom(atom_id)
                    except httpx.HTTPError as e:
                        logger.warning(json.dumps({
                            "event": "bus.fetch_fail",
                            "atom_id": atom_id,
                            "raison": raison(e),
                        }))
                        continue
                    yield atom

        except (psycopg.OperationalError, OSError) as e:
            wait = _BACKOFF_SEQUENCE_SEC[min(backoff_idx, len(_BACKOFF_SEQUENCE_SEC) - 1)]
            logger.warning(json.dumps({
                "event": "bus.reconnect_after_error",
                "node_id": node_id,
                "error": type(e).__name__,
                "wait_sec": wait,
                "backoff_idx": backoff_idx,
            }))
            await asyncio.sleep(wait)
            backoff_idx += 1


async def subscribe(
    node_id: str,
    handler: Callable[[dict[str, Any]], Awaitable[None]],
    *,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Boucle subscribe → handler. Termine quand `stop_event` est set.

    Le handler est awaitable. Exception dans handler = log + continue
    (un message corrompu ne tue pas la boucle).
    """
    iterator = listen_inbox(node_id)
    try:
        async for atom in iterator:
            if stop_event is not None and stop_event.is_set():
                break
            try:
                await handler(atom)
            except Exception as e:  # noqa: BLE001
                logger.error(json.dumps({
                    "event": "bus.handler_error",
                    "node_id": node_id,
                    "atom_id": atom.get("id"),
                    "error": type(e).__name__,
                    "raison": raison(e),
                }))
    finally:
        await iterator.aclose()
