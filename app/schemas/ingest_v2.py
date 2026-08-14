"""Schemas Pydantic v2 pour POST /v1/ingest/messages — Ingestion V2.

Contrat de référence : ce module + `app/routers/ingest_v2.py` font foi.

Doctrine ARAC :
- Pydantic v2 strict (`@field_validator`, `ConfigDict`).
- `extra="forbid"` sur tous les niveaux (batch + message) — refus de champs
  inconnus, top-level et par-message.
- Les caps « durs » (≤2000 messages/batch, ≤512 KB/message) sont volontai-
  rement HORS pydantic : ils doivent lever 400 (avec le `message_uuid`
  fautif pour le cap par-message), pas 422 — cf app/routers/ingest_v2.py
  `_enforce_batch_caps`. Ici on ne valide QUE la forme (schéma) et les
  contraintes structurelles bon marché (régex, non-vide, enum role).
- `message_uuid` est OPTIONNEL (contrairement à une lecture naïve du
  contrat) : la table `arac.raw_messages` autorise NULL et la colonne
  générée `dedup_key` bascule sur `'h:'||content_hash` dans ce cas
  (colonne `message_uuid` — « peut être NULL »).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


# ============================================================================
# Constantes (caps durs — cf design §Contrat)
# ============================================================================

MAX_MESSAGES_PER_BATCH = 2000
MAX_MESSAGE_BYTES = 512 * 1024  # 512 KB par message (JSON sérialisé)

# Régex source_type (cf migration 0015 : CHECK identique côté DB, défense
# en profondeur — même contrainte des deux côtés).
SOURCE_TYPE_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"


# ============================================================================
# Schemas IN
# ============================================================================


class IngestV2MessageIn(BaseModel):
    """Un message du batch (après decompress + parse JSON, avant sanitize).

    `role` restreint à `('user','assistant')` — mirror strict du CHECK DB
    (migration 0015). `content_hash` n'est PAS un champ d'entrée : il est
    calculé SERVEUR, après sanitize (cf router).
    """

    model_config = ConfigDict(extra="forbid")

    message_uuid: str | None = Field(
        None,
        description="Clé naturelle du message (peut être absente → fallback hash)",
    )
    parent_uuid: str | None = Field(None, description="uuid du message parent (informatif)")
    role: Literal["user", "assistant"]
    content: str
    created_at: str | None = Field(
        None,
        description="Timestamp du message côté source (texte, jamais reformaté client-side)",
    )

    @field_validator("message_uuid")
    @classmethod
    def _blank_uuid_is_null(cls, v: str | None) -> str | None:
        """'' ou blanc → None (revue adversariale 2026-07-03, S6) : sinon deux
        messages distincts à uuid vide partagent `dedup_key=''` et le second
        est silencieusement avalé par ON CONFLICT DO NOTHING."""
        if v is None:
            return None
        v = v.strip()
        return v or None

    @field_validator("content")
    @classmethod
    def _strip_nul_bytes(cls, v: str, info: ValidationInfo) -> str:
        """Strip des `\\u0000` : jamais 500, jamais 422 — un
        rejet bloquerait la conversation à jamais (le contenu vient d'une
        source déjà acceptée ailleurs). Compté dans
        `info.context["counts"]["nul_stripped"]` quand un contexte est fourni
        (cf app/routers/ingest_v2.py `_build_batch_model`, pour
        `ingest_receipts.nul_stripped`) ; sans contexte (construction directe
        du modèle, ex. tests), le strip a lieu sans comptage."""
        if "\x00" not in v:
            return v
        ctx = info.context or {}
        counts = ctx.get("counts")
        if counts is not None:
            counts["nul_stripped"] = counts.get("nul_stripped", 0) + 1
        return v.replace("\x00", "")

    @field_validator("created_at")
    @classmethod
    def _unparseable_timestamp_is_null(cls, v: str | None, info: ValidationInfo) -> str | None:
        """Timestamp non parsable → None, jamais 500 (revue adversariale, M2) :
        la valeur part telle quelle dans un cast timestamptz PostgreSQL ; une
        chaîne arbitraire ferait échouer TOUT le batch (500 + retries client
        inutiles). Tolerant reader : le timestamp est une métadonnée optionnelle
        (le gate curateur fait COALESCE sur received_at) — on préfère perdre la
        métadonnée que bloquer l'ingestion. Une chaîne VALIDE est renvoyée NON
        reformatée (le content_hash serveur doit rester stable au rejeu).

        Le passage à None PAR NULLIFICATION (valeur non-vide mais non
        parsable) est compté dans `info.context["counts"]["created_at_nullified"]`
        (`ingest_receipts.created_at_nullified`) — un `created_at`
        déjà absent/blanc côté client n'est PAS compté (rien n'a été « guéri »)."""
        if v is None:
            return None
        s = v.strip()
        if not s:
            return None
        from datetime import datetime

        try:
            datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            ctx = info.context or {}
            counts = ctx.get("counts")
            if counts is not None:
                counts["created_at_nullified"] = counts.get("created_at_nullified", 0) + 1
            return None
        return v


class IngestV2BatchIn(BaseModel):
    """Payload accepté par /v1/ingest/messages (après decompress + parse JSON).

    Une conversation par batch. Caps durs (≤2000 messages, ≤512 KB/message)
    appliqués EN AMONT (400) — cf app/routers/ingest_v2.py.
    """

    model_config = ConfigDict(extra="forbid")

    source_type: str = Field(..., pattern=SOURCE_TYPE_PATTERN)
    conversation_uid: str
    title: str | None = None
    messages: list[IngestV2MessageIn]

    @field_validator("conversation_uid")
    @classmethod
    def _conversation_uid_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("conversation_uid must not be empty")
        return v


# ============================================================================
# Schema OUT
# ============================================================================


class IngestV2Out(BaseModel):
    """Réponse de /v1/ingest/messages.

    - 202 si `inserted > 0` (au moins un message nouveau inséré).
    - 200 si no-op (tous les messages du batch étaient déjà connus —
      `duplicates` = preuve en ligne du zéro-churn, cf design).

    `request_id` : écho du header `X-ARAC-Request-Id` (ou
    généré serveur si absent/invalide) — même valeur que le header de
    réponse et que `ingest_receipts.request_id`.
    """

    request_id: UUID
    conversation_id: UUID
    received: int = Field(..., ge=0, description="Nombre de messages reçus dans le batch")
    inserted: int = Field(..., ge=0, description="Nombre de messages effectivement insérés")
    duplicates: int = Field(..., ge=0, description="Nombre de messages déjà connus (dedup)")
    msg_count: int = Field(..., ge=0, description="COUNT(*) raw_messages de la conversation")
    curated_through_message_id: int = Field(
        ..., ge=0, description="Curseur de curation courant (watermark)"
    )
    new_uncurated: int = Field(
        ..., ge=0, description="COUNT raw_messages WHERE id > curated_through_message_id"
    )



# ============================================================================
# Schemas — POST /v1/ingest/capture-manifest
# ============================================================================
#
# Source canonique : db/alembic/versions/0026_d063_capture_manifests.py.
# Un manifeste par run de scan de capture (Mac `arac-ingest-v2.py`, self-
# capture serveur `claude_code_selfcapture.py`) — la contrepartie AMONT de
# `ingest_receipts` (« ai-je REGARDÉ tout ce que je devais regarder ? »,
# distinct de « le serveur a-t-il ACCEPTÉ ce que je lui ai envoyé ? »).
#
# PAS de `node_id` dans le body (contrairement à une lecture naïve) : même
# doctrine que `IngestV2BatchIn` — le node_id est résolu SERVEUR depuis les
# headers d'auth (`_resolve_node_id`, cf app/routers/ingest_v2.py), jamais
# accepté du corps (anti-usurpation, un node ne peut pas se faire passer
# pour un autre en changeant juste son payload JSON).


class CaptureManifestIn(BaseModel):
    """Payload accepté par POST /v1/ingest/capture-manifest.

    `messages_filtered` : dict motif -> count (ex. `{"control_line": 3}`).
    Aucune contrainte de clés connues côté serveur (le client — cf
    `jsonl_capture_lib.py:build_manifest` — reclasse déjà tout motif inconnu
    en `'other'` avant l'envoi) ; seule la NON-NÉGATIVITÉ des valeurs est
    vérifiée ici (défense en profondeur)."""

    model_config = ConfigDict(extra="forbid")

    source_type: str = Field(..., pattern=SOURCE_TYPE_PATTERN)
    run_started_at: datetime
    run_ended_at: datetime | None = None
    files_scanned: int = Field(0, ge=0)
    sessions: int = Field(0, ge=0)
    messages_read: int = Field(0, ge=0)
    messages_emitted: int = Field(0, ge=0)
    messages_filtered: dict[str, int] = Field(default_factory=dict)
    batches_ok: int = Field(0, ge=0)
    batches_failed: int = Field(0, ge=0)
    ack_mismatches: int = Field(0, ge=0)
    state_sha256: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")
    archive_bytes: int | None = Field(None, ge=0)

    @field_validator("messages_filtered")
    @classmethod
    def _filtered_counts_non_negative(cls, v: dict[str, int]) -> dict[str, int]:
        for motif, count in v.items():
            if count < 0:
                raise ValueError(f"messages_filtered[{motif!r}] must be >= 0")
        return v


class CaptureManifestOut(BaseModel):
    """Réponse de POST /v1/ingest/capture-manifest — l'id de la row créée."""

    id: int


__all__: list[str] = [
    "MAX_MESSAGES_PER_BATCH",
    "MAX_MESSAGE_BYTES",
    "SOURCE_TYPE_PATTERN",
    "IngestV2MessageIn",
    "IngestV2BatchIn",
    "IngestV2Out",
    "CaptureManifestIn",
    "CaptureManifestOut",
]
