"""Client API atomes du DISPOSANT cortex — httpx synchrone, loopback.

Le disposant possède TOUTES les écritures d'atomes (le LLM n'a plus d'outils).

AUTHENTIFICATION — ce paragraphe disait exactement l'inverse de la vérité
d'aujourd'hui, et c'est la raison du changement. Il annonçait « loopback
127.0.0.1 sans bearer (l'edge est protégé par Caddy) ». Il n'y a pas de Caddy
dans l'installation que ce dépôt décrit, et « loopback » ne veut pas dire
« à moi » : sur une machine à deux cerveaux, la boucle locale est un couloir
partagé. Le jeton est désormais exigé de toute requête (`app/auth.py`), et le
cycle le porte comme tout le monde, via `app.api_token.entetes_api()`.

L'auth de provenance ne change pas : le node_id reste posé PAR LE CODE dans
les payloads (`policy.finalize_atom`). Le jeton dit « je suis un poste
connu » ; le node_id dit « voici qui parle ». Les deux, pas l'un ou l'autre.

Chaque appel = connexion httpx COURTE ;
aucune exception avalée côté réseau : le disposant décide (dispose_interrupted).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from app.api_token import entetes_api

API_URL = os.environ.get("ARAC_API_URL", "").rstrip("/")
TIMEOUT = float(os.environ.get("ARAC_TIMEOUT", "20"))


class AtomsApiDown(Exception):
    """Réseau/5xx — l'API est indisponible : le disposant s'interrompt
    (status dispose_interrupted), curseur NON avancé, reprise idempotente."""


def _client() -> httpx.Client:
    # Les en-têtes sont relus à CHAQUE client, jamais figés à l'import : une
    # rotation de jeton suivie d'un redémarrage de l'API ne doit pas laisser
    # un cycle de longue haleine parler avec un jeton révoqué.
    return httpx.Client(base_url=API_URL, timeout=TIMEOUT, headers=entetes_api())


def _raise_if_down(resp: httpx.Response) -> None:
    if resp.status_code >= 500:
        raise AtomsApiDown(f"HTTP {resp.status_code} sur {resp.request.url.path}")


def post_atom(payload: dict[str, Any]) -> tuple[int, dict[str, Any] | None]:
    """POST /v1/atoms. Retourne (status_code, body|None).

    Codes attendus par le disposant : 200/201 créé ; 409 conflit (résolution
    OBLIGATOIRE) ; 422 dérive de contrat (quarantaine d'atome) ; 5xx/réseau
    -> AtomsApiDown."""
    try:
        with _client() as c:
            r = c.post("/v1/atoms", json=payload)
    except httpx.HTTPError as e:
        raise AtomsApiDown(f"{type(e).__name__}: {e}") from e
    _raise_if_down(r)
    try:
        body = r.json()
    except ValueError:
        body = None
    return r.status_code, body


def get_by_key(scope: str, key: str) -> dict[str, Any] | None:
    """GET /v1/atoms/by-key — l'atome ACTIF du slot, ou None (404)."""
    try:
        with _client() as c:
            r = c.get("/v1/atoms/by-key", params={"scope": scope, "key": key})
    except httpx.HTTPError as e:
        raise AtomsApiDown(f"{type(e).__name__}: {e}") from e
    if r.status_code == 404:
        return None
    _raise_if_down(r)
    if r.status_code >= 400:
        # 4xx inattendu (ex. API pas au niveau du contrat) : mieux vaut
        # interrompre proprement (reprise idempotente) que crasher le cycle.
        raise AtomsApiDown(f"by-key HTTP {r.status_code}")
    return r.json()


def supersede(incumbent_id: str, *, new_value: str, new_rationale: str | None,
              new_confidence_score: int, new_node_id: str,
              new_source_ref: dict[str, Any]) -> tuple[int, dict[str, Any] | None]:
    """POST /v1/atoms/{id}/supersede — nouvelle version active, l'ancienne
    pointe superseded_by. `new_tags` ABSENT = héritage (préserve
    pierre-angulaire, cf design §4). 409 possible sur course (re-fetch)."""
    payload: dict[str, Any] = {
        "new_value": new_value,
        "new_confidence_score": new_confidence_score,
        "new_node_id": new_node_id,
        "new_source_ref": new_source_ref,
    }
    if new_rationale:
        payload["new_rationale"] = new_rationale
    try:
        with _client() as c:
            r = c.post(f"/v1/atoms/{incumbent_id}/supersede", json=payload)
    except httpx.HTTPError as e:
        raise AtomsApiDown(f"{type(e).__name__}: {e}") from e
    _raise_if_down(r)
    try:
        body = r.json()
    except ValueError:
        body = None
    return r.status_code, body


def confirm_unchanged(incumbent: dict[str, Any]) -> tuple[int, dict[str, Any] | None]:
    """PATCH /v1/atoms/{id} — « confirmed-unchanged » (design §4.3) :
    `source_ref.curator_confirmations += 1` + `last_confirmed_at` -> bump
    `updated_at` : l'atome reste FRAIS sans nouvelle version (anti-
    fossilisation par confirmation, réalise l'idée confirmed_until)."""
    src = dict(incumbent.get("source_ref") or {})
    src["curator_confirmations"] = int(src.get("curator_confirmations") or 0) + 1
    src["last_confirmed_at"] = datetime.now(timezone.utc).isoformat()
    try:
        with _client() as c:
            r = c.patch(f"/v1/atoms/{incumbent['id']}", json={"source_ref": src})
    except httpx.HTTPError as e:
        raise AtomsApiDown(f"{type(e).__name__}: {e}") from e
    _raise_if_down(r)
    try:
        body = r.json()
    except ValueError:
        body = None
    return r.status_code, body


def recall(query: str, *, scope: str | None = None, k: int = 3,
           consumer: str | None = None) -> list[dict[str, Any]]:
    """POST /v1/atoms/recall — backstop de dédup sémantique du disposant
    (cosine >= 0.92 même kind => résolution incumbent au lieu d'un POST).

    `consumer` (gap G1) : identité déclarée au Context Engine —
    le disposant passe "cortex_dedup" (profil budget_k=3). Optionnel : sans
    lui, l'API traite l'appel comme `unknown` (profil par défaut)."""
    payload: dict[str, Any] = {"query": query, "k": k}
    if scope:
        payload["scope"] = scope
    if consumer:
        payload["consumer"] = consumer
    try:
        with _client() as c:
            r = c.post("/v1/atoms/recall", json=payload)
    except httpx.HTTPError as e:
        raise AtomsApiDown(f"{type(e).__name__}: {e}") from e
    _raise_if_down(r)
    if r.status_code >= 400:
        # Le backstop sémantique est une OPTIMISATION : indisponible -> on
        # continue, la dédup exacte du POST (desc_hash + unique scope,key)
        # reste la barrière. Mais JAMAIS en silence : un 4xx persistant
        # (ex. 422 si l'API ne connaît pas encore le champ `consumer` —
        # rollback API sans rollback agents/) désactiverait toute la dédup
        # sémantique sans aucun signal.
        _log_recall_degraded(r.status_code)
        return []
    return r.json()


def _log_recall_degraded(status_code: int) -> None:
    """WARNING une-ligne JSON (style journald du cortex) — le backstop de
    dédup sémantique vient d'être court-circuité par un 4xx."""
    logging.getLogger("arac.cortex.atoms_client").warning(json.dumps({
        "event": "atoms_client.recall_degraded",
        "status_code": status_code,
        "effect": "semantic-dedup backstop skipped (hits=[])",
    }, ensure_ascii=False))
