"""Schemas Pydantic v2 pour POST /v1/ingest/conversations — Bloc Cerveau Vivant v0.5.

Contrat de référence : ce module fait foi.

Doctrine ARAC :
- Pydantic v2 strict (`@field_validator`, `ConfigDict`).
- `extra="forbid"` sur l input — refus de fields top-level inconnus.
- `messages: list[dict]` reste libre (schéma JSONL natif Claude Code non figé).
- Sanitize defense-in-depth fait dans le router (pas dans Pydantic) car
  modifierait la donnée silencieusement à l input.
"""

from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ============================================================================
# Constantes
# ============================================================================

MAX_MESSAGES_PER_BUNDLE = 5000


# ============================================================================
# Enums
# ============================================================================


class IngestStatus(str, Enum):
    """État d ingestion d un bundle conversation (mirror BDD CHECK constraint
    arac.raw_conversations.status — cf migration 0008).
    """

    PENDING = "pending"          # ingéré, en attente de curation
    PROCESSING = "processing"    # en cours de curation par arac-curator
    CURATED = "curated"          # curation OK, atomes générés
    FAILED = "failed"            # curation échouée
    PURGED = "purged"            # purgé par TTL 90j


# ============================================================================
# Schemas IN/OUT
# ============================================================================


class ConversationBundleIn(BaseModel):
    """Payload accepté par /v1/ingest/conversations (après decompress + NDJSON parse).

    `messages` est libre (schéma JSONL natif Claude Code, non figé v0.5).
    Validation stricte : non-vide, taille bornée, source_path borné.
    """

    model_config = ConfigDict(extra="forbid")

    source_path: str = Field(
        ...,
        max_length=512,
        description="Path source sur Mac (déjà sanitized côté agent ingest)",
    )
    session_uuid: UUID | None = Field(
        None,
        description="UUID session Claude Code (extrait des messages si possible)",
    )
    messages: list[dict[str, Any]] = Field(
        ...,
        description="Liste de messages JSONL natifs (1..5000)",
    )

    @field_validator("source_path")
    @classmethod
    def _source_path_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("source_path must not be empty")
        return v

    @field_validator("messages")
    @classmethod
    def _messages_bounded(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not v:
            raise ValueError("empty bundle")
        if len(v) > MAX_MESSAGES_PER_BUNDLE:
            raise ValueError(
                f"bundle too large: {len(v)} > {MAX_MESSAGES_PER_BUNDLE} messages"
            )
        return v


class ConversationBundleOut(BaseModel):
    """Réponse de /v1/ingest/conversations.

    - 202 + queued_for_curation=True sur ingest nouveau.
    - 200 + queued_for_curation=False sur idempotence hit (même content_hash
      déjà en BDD).
    """

    raw_id: UUID = Field(..., description="UUID du row arac.raw_conversations")
    message_count: int = Field(..., ge=0)
    queued_for_curation: bool = Field(
        ...,
        description="True si nouvel insert (NOTIFY conversation_ingested déclenché)",
    )
