"""Contrat du endpoint d'ingestion v1 GELÉ (étape 0017).

L'ingestion v1 par-snapshot est terminée : POST /v1/ingest/conversations
répond 410 Gone et pointe vers /v1/ingest/messages (V2, par-message).
`raw_conversations` est gelée lecture-seule (migration 0017) — table de
LIGNÉE des atomes déjà curés, jamais backfillée, jamais droppée.

Les 15 anciens tests de comportement v1 (idempotence snapshot, caps NDJSON,
UPSERT…) testaient un contrat désormais gelé : retirés (historique git
`git log -- tests/test_ingest_endpoint.py`). Les helpers partagés survivants
(_decompress_if_gzip, _get_max_size, _resolve_node_id) sont testés via
tests/test_ingest_v2_contract.py.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException


async def test_ingest_v1_route_is_gone_410():
    """Le handler v1 lève 410 immédiatement — aucune DB, aucune écriture."""
    from app.routers.ingest import ingest_conversations

    with pytest.raises(HTTPException) as exc_info:
        await ingest_conversations(request=None)  # le handler n'y touche pas
    assert exc_info.value.status_code == 410
    assert "/v1/ingest/messages" in str(exc_info.value.detail)


def test_both_ingest_routes_still_mounted():
    """La route v1 reste MONTÉE (410 explicite ≠ 404 silencieux) ; la v2 vit."""
    from app.main import app

    # Selon la version de FastAPI, `app.routes` contient soit des routes à
    # plat, soit des routeurs inclus qui portent leurs propres routes. On
    # descend donc l'arbre : un test qui ne trouve pas une route à cause de
    # la version de la bibliothèque affirme une régression qui n'existe pas.
    # La forme la plus stable d'une version de FastAPI à l'autre : le schéma
    # OpenAPI, qui est le contrat PUBLIÉ. `app.routes` a changé de structure
    # (routes à plat, puis routeurs inclus qui gardent les leurs) ; le schéma,
    # lui, dit ce que le monde extérieur voit — c'est ça qu'on veut tester.
    paths = set(app.openapi()["paths"])
    assert "/v1/ingest/conversations" in paths
    assert "/v1/ingest/messages" in paths
