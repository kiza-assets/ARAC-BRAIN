"""tests/test_embeddings.py — wrapper app.services.embeddings.

5 tests mockés (CI-safe, aucun appel API réel) :
  1. test_embed_returns_3072_floats        — cas nominal
  2. test_embed_retries_on_rate_limit      — RateLimitError au 1er → succès au 2e
  3. test_embed_retries_exhausted_raises   — 3 RateLimitError → propagation
  4. test_embed_fails_fast_on_auth_error   — AuthenticationError → 1 appel, pas de retry
  5. test_embed_rejects_empty_input        — ValueError sur input vide/whitespace

1 test live (marker `@pytest.mark.live_api`, **skip par défaut**) :
  6. test_embed_live_api_returns_3072_dim — ⚠️ HIT L'API OpenAI RÉELLE
     Coût ~1 token = $0.000013. Activer via `pytest -m live_api`.
     Garde-fou contre régression sur le param `dimensions=` (qui ferait tomber
     sur le default OpenAI).
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, Mock

import pytest
from openai import AuthenticationError, RateLimitError

from app.services.embeddings import embed


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_openai_response():
    """Construit un faux openai response avec embedding 3072 dim."""
    response = Mock()
    # Embedding fake déterministe — différent du zero vector pour spotcheck
    response.data = [Mock(embedding=[0.001 * i for i in range(3072)])]
    response.usage = Mock(prompt_tokens=5, total_tokens=5)
    response.model = "text-embedding-3-large"
    return response


@pytest.fixture
def mock_client(monkeypatch, mock_openai_response):
    """Patche `_get_client()` pour retourner un AsyncMock client."""
    client = AsyncMock()
    client.embeddings.create = AsyncMock(return_value=mock_openai_response)
    monkeypatch.setattr("app.services.embeddings._get_client", lambda: client)
    return client


# ============================================================================
# Tests mockés (CI-safe, aucun appel API réel)
# ============================================================================


async def test_embed_returns_3072_floats(mock_client):
    """Cas nominal : retour 3072 floats + paramètres OpenAI corrects."""
    result = await embed("ping test", request_id="test-001")

    assert isinstance(result, list)
    assert len(result) == 3072
    assert all(isinstance(x, float) for x in result[:5])

    mock_client.embeddings.create.assert_awaited_once_with(
        input="ping test",
        model="text-embedding-3-large",
        dimensions=3072,
    )


async def test_embed_retries_on_rate_limit(monkeypatch, mock_openai_response):
    """RateLimitError au 1er essai → succès au 2e. 2 appels au total."""
    client = AsyncMock()
    rate_limit_error = RateLimitError(
        message="rate limited",
        response=Mock(status_code=429),
        body=None,
    )
    client.embeddings.create = AsyncMock(
        side_effect=[rate_limit_error, mock_openai_response]
    )
    monkeypatch.setattr("app.services.embeddings._get_client", lambda: client)

    result = await embed("retry test")

    assert len(result) == 3072
    assert client.embeddings.create.await_count == 2


async def test_embed_retries_exhausted_raises(monkeypatch):
    """3 RateLimitError consécutives → 3 appels max, RateLimitError propagée."""
    client = AsyncMock()
    rate_limit_error = RateLimitError(
        message="rate limited",
        response=Mock(status_code=429),
        body=None,
    )
    # On en met 5 pour vérifier que tenacity arrête bien après 3
    client.embeddings.create = AsyncMock(side_effect=[rate_limit_error] * 5)
    monkeypatch.setattr("app.services.embeddings._get_client", lambda: client)

    with pytest.raises(RateLimitError):
        await embed("retry exhausted")

    assert client.embeddings.create.await_count == 3


async def test_embed_fails_fast_on_auth_error(monkeypatch):
    """AuthenticationError → 1 seul appel, pas de retry, erreur propagée."""
    client = AsyncMock()
    auth_error = AuthenticationError(
        message="invalid api key",
        response=Mock(status_code=401),
        body=None,
    )
    client.embeddings.create = AsyncMock(side_effect=auth_error)
    monkeypatch.setattr("app.services.embeddings._get_client", lambda: client)

    with pytest.raises(AuthenticationError):
        await embed("auth fail")

    assert client.embeddings.create.await_count == 1


async def test_embed_rejects_empty_input(mock_client):
    """Input vide ou whitespace → ValueError immédiat, aucun appel client."""
    with pytest.raises(ValueError, match="non vide"):
        await embed("")

    with pytest.raises(ValueError, match="non vide"):
        await embed("   \t\n   ")

    mock_client.embeddings.create.assert_not_awaited()


# ============================================================================
# Test live_api (⚠️ HIT API RÉELLE — skip par défaut)
# ============================================================================
#
# Activation :
#     pytest -m live_api tests/test_embeddings.py
#
# Skip par défaut : pytest.ini `addopts = -m "not live_api"`.
# Coût : ~1 token = $0.000013 par run. Le plafond mensuel configuré côté OpenAI protège
# contre runs en boucle.
#
# But : régression-guard sur le paramètre `dimensions=`. Si on perdait ce
# paramètre, OpenAI retournerait la dim native (3072 par chance pour text-
# embedding-3-large, mais c'est fragile). Ce test vérifie EXPLICITEMENT
# `len(result) == 3072`.


@pytest.mark.live_api
async def test_embed_live_api_returns_3072_dim():
    """⚠️ HIT L'API OpenAI réelle. Coût ~$0.000013.

    Vérifie que `embed()` retourne bien 3072 floats (et pas 1024/256/autre).
    Régression-guard sur le param `dimensions=`.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY non définie dans l'environnement")

    result = await embed("ping")

    assert isinstance(result, list)
    assert len(result) == 3072, (
        f"dim attendue 3072 (text-embedding-3-large + dimensions=3072), "
        f"reçu {len(result)} — possible régression sur le param `dimensions=` ?"
    )
    assert all(isinstance(x, (int, float)) for x in result[:10])
