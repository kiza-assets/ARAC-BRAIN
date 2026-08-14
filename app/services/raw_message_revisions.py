"""Écriture append-only `arac.raw_message_revisions` — divergence de hash.

Cf docstring migration `db/alembic/versions/0022_d063_raw_message_revisions.py`
(source canonique des colonnes) : quand un `dedup_key` déjà en base (édition
côté client, corruption, collision) ré-arrive avec un `content_hash`
DIFFÉRENT, on consigne l'écart plutôt que de l'ignorer ou d'écraser —
`arac.raw_messages` reste append-only PAR GRANT, aucun UPDATE n'est jamais
émis sur cette table (cf app/routers/ingest_v2.py, boucle d'INSERT).

`write_hash_divergence_revision` participe à l'atomicité de la transaction
d'ingestion (même connexion que l'upsert conversation + boucle INSERT
messages + `write_accepted_receipt`, cf app/services/ingest_receipts.py) :
n'attrape RIEN — un échec ici doit faire ROLLBACK toute la transaction
appelante.
"""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection

from app.services.sanitize import mask_recursive


async def write_hash_divergence_revision(
    conn: AsyncConnection,
    *,
    raw_message_id: int,
    conversation_id: Any,
    dedup_key: str,
    existing_content_hash: str,
    incoming_content_hash: str,
    incoming_content_masked: str,
    request_id: str,
    actor: str = "ingest_v2",
) -> None:
    """INSERT append-only `reason='hash_divergence'` DANS la transaction en cours.

    `raw_message_id` : id de la row DÉJÀ en base pour ce `dedup_key` (jamais
    la tentative d'INSERT entrante, avalée par `ON CONFLICT DO NOTHING`).
    `incoming_content_masked` repasse par `mask_recursive` avant écriture —
    défense en profondeur (même discipline que `ingest_receipts.
    refusal_detail`, cf `app/services/ingest_receipts.py::_prepare_refusal_
    detail`) même si l'appelant a déjà sanitizé le contenu avant hash.
    """
    masked = mask_recursive(incoming_content_masked)
    if not isinstance(masked, str):
        masked = str(masked)
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO arac.raw_message_revisions (
                raw_message_id, conversation_id, dedup_key,
                existing_content_hash, incoming_content_hash,
                incoming_content_masked, reason, request_id, actor
            ) VALUES (
                %s, %s, %s, %s, %s, %s, 'hash_divergence', %s, %s
            )
            """,
            (
                raw_message_id,
                conversation_id,
                dedup_key,
                existing_content_hash,
                incoming_content_hash,
                masked,
                request_id,
                actor,
            ),
        )


__all__ = ["write_hash_divergence_revision"]
