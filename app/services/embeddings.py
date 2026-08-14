"""app/services/embeddings.py — wrapper async OpenAI embeddings.

Choix de conception :
  - OpenAI `text-embedding-3-large` (3072 dim) Phase 2 → fin du
    projet. Pas d'inférence locale, jamais.
  - pas d'ORM. Communication directe avec OpenAI via le SDK officiel
    asynchrone.

API publique :
  - `embed(text, *, request_id=None) -> list[float]` : retourne 3072 floats
  - `close_client()` : appelé au lifespan shutdown FastAPI

Stratégie retry (tenacity) :
  - 3 attempts max (1 essai initial + 2 retries)
  - Wait exponentiel 1s/2s/4s (plafond 8s)
  - Retry uniquement sur transients : RateLimitError, APITimeoutError,
    APIConnectionError, InternalServerError
  - Fail-fast (pas de retry) sur AuthenticationError, PermissionDeniedError,
    BadRequestError, UnprocessableEntityError, NotFoundError, etc.
  - `reraise=True` → l'exception originale remonte au caller (pas RetryError)

Logging structuré (logger `arac.embeddings`) :
  - `embedding.request` (DEBUG) : silencieux par défaut, activable en cas d'enquête
  - `embedding.success` (INFO)  : usage tokens + latency
  - `embedding.failure` (ERROR) : type + message d'erreur
  - `embedding.retry` (WARNING) : auto-généré par tenacity.before_sleep_log
  - **Sécurité** : on ne logge ni l'input (PII potentielle) ni la clé API.
    Seul `input_chars` (longueur) est exposé.

Estimation de coût :
  - Phase 7 bootstrap (~150 atomes × ~200 tokens) : ~30 000 tokens = $0.0039
  - Phase 9+ (~10 000 atomes/an) : ~2M tokens = $0.26/an
  - Hard cap mensuel configuré côté OpenAI portal (montant à VOTRE main).
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Final

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.context import request_id_var
from app.journal import raison


# ============================================================================
# Constantes
# ============================================================================

_MODEL: Final[str] = "text-embedding-3-large"
_DIMENSIONS: Final[int] = 3072
_REQUEST_TIMEOUT_SEC: Final[float] = 30.0

# Retry config
_RETRY_MAX_ATTEMPTS: Final[int] = 3
_RETRY_WAIT_MIN_SEC: Final[float] = 1.0
_RETRY_WAIT_MAX_SEC: Final[float] = 8.0

# Exceptions transients → retry. Toutes les autres exceptions OpenAI
# (AuthenticationError, BadRequestError, etc.) propagent immédiatement.
_RETRYABLE_EXCEPTIONS: Final[tuple[type[Exception], ...]] = (
    RateLimitError,
    APITimeoutError,
    APIConnectionError,
    InternalServerError,
)


# ============================================================================
# L'absence de clé n'est pas une panne : c'est un mode annoncé
# ============================================================================
#
# Le bootstrap PROPOSE d'installer sans clé d'embeddings, pour découvrir la
# chaîne d'ingestion sans dépenser. Dans cet état, tout ce qui a besoin d'un
# vecteur est indisponible — le rappel, la création d'atome, la clôture de
# session. « Indisponible » doit s'entendre : un 503 qui nomme ce qui manque,
# jamais une 500 nue, qui ferait croire à un cerveau cassé le jour même de son
# installation.


class EmbeddingsIndisponibles(RuntimeError):
    """Le service d'embeddings ne peut pas être appelé (aucune clé configurée).

    Reste une `RuntimeError` : le code qui attrapait déjà `RuntimeError` autour
    d'`embed()` continue de fonctionner à l'identique.
    """


# ============================================================================
# State module-level
# ============================================================================

_client: AsyncOpenAI | None = None
_logger = logging.getLogger("arac.embeddings")


# ============================================================================
# Helpers privés
# ============================================================================


def _get_client() -> AsyncOpenAI:
    """Lazy init du client AsyncOpenAI.

    Lit `OPENAI_API_KEY` au premier appel — `EmbeddingsIndisponibles` si absente.
    Idempotent : retourne le même client (singleton) ensuite.
    """
    global _client
    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            # Type DÉDIÉ, et non `RuntimeError` : le mode dégradé est un état
            # ANNONCÉ par le bootstrap, pas un accident. Il doit donc produire
            # une réponse HTTP qui l'explique (503), ce que seule une exception
            # reconnaissable permet — cf app/errors.py.
            raise EmbeddingsIndisponibles(
                "aucune clé d'embeddings : OPENAI_API_KEY n'est pas dans "
                "l'environnement du service"
            )
        _client = AsyncOpenAI(api_key=api_key, timeout=_REQUEST_TIMEOUT_SEC)
    return _client


def _check_input(text: str) -> None:
    """Validation : input non vide (whitespace exclu)."""
    if not text or not text.strip():
        raise ValueError("text doit être une chaîne non vide (whitespace exclu)")


# ============================================================================
# Appel OpenAI brut (tenacity wrap les retries)
# ============================================================================


@retry(
    stop=stop_after_attempt(_RETRY_MAX_ATTEMPTS),
    wait=wait_exponential(
        multiplier=1, min=_RETRY_WAIT_MIN_SEC, max=_RETRY_WAIT_MAX_SEC
    ),
    retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
    before_sleep=before_sleep_log(_logger, logging.WARNING),
    reraise=True,
)
async def _call_openai_embeddings(text: str):
    """Appel brut à OpenAI Embeddings API. tenacity gère les retries.

    Note : on récupère le client à CHAQUE appel pour permettre les tests qui
    monkey-patchent `_get_client`. En prod, c'est le même client réutilisé
    (lazy singleton).
    """
    client = _get_client()
    return await client.embeddings.create(
        input=text,
        model=_MODEL,
        dimensions=_DIMENSIONS,
    )


# ============================================================================
# API publique
# ============================================================================


async def embed(text: str, *, request_id: str | None = None) -> list[float]:
    """Génère un embedding `text-embedding-3-large` 3072 dim pour `text`.

    Args:
        text: Texte à embeddre. Doit être non vide (whitespace exclu).
        request_id: ID optionnel pour traçage logs. Généré (uuid4) si absent.

    Returns:
        list[float] de longueur 3072.

    Raises:
        ValueError: si text vide ou whitespace-only.
        AuthenticationError, PermissionDeniedError, BadRequestError, etc. :
            non retry-able, propagation immédiate.
        RateLimitError, APITimeoutError, APIConnectionError, InternalServerError:
            après 3 attempts épuisées (reraise=True), l'exception originale
            est propagée au caller.
    """
    _check_input(text)
    # Priorité : argument explicite > ContextVar (set par middleware FastAPI) > uuid4 fresh
    rid = request_id or request_id_var.get() or str(uuid.uuid4())

    _logger.debug(
        "embedding.request",
        extra={
            "request_id": rid,
            "model": _MODEL,
            "dimensions": _DIMENSIONS,
            "input_chars": len(text),
        },
    )

    start = time.perf_counter()
    try:
        response = await _call_openai_embeddings(text)
    except Exception as e:
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        _logger.error(
            "embedding.failure",
            extra={
                "request_id": rid,
                "model": _MODEL,
                "dimensions": _DIMENSIONS,
                "input_chars": len(text),
                "latency_ms": latency_ms,
                "error_type": type(e).__name__,
                "raison": raison(e),
            },
        )
        raise

    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    embedding = response.data[0].embedding

    _logger.info(
        "embedding.success",
        extra={
            "request_id": rid,
            "model": _MODEL,
            "dimensions": _DIMENSIONS,
            "input_chars": len(text),
            "prompt_tokens": response.usage.prompt_tokens,
            "total_tokens": response.usage.total_tokens,
            "latency_ms": latency_ms,
        },
    )

    return embedding


async def close_client() -> None:
    """Ferme le client AsyncOpenAI (lifespan shutdown FastAPI).

    Idempotent : no-op si pas de client init (utile pour réinitialisations
    en tests).
    """
    global _client
    if _client is not None:
        await _client.close()
        _client = None
