"""Helpers d'écriture `arac.ingest_receipts`.

Chaîne de preuve amont : chaque appel à un endpoint d'ingestion écrit UNE
row dans `arac.ingest_receipts`, acceptée ou refusée (cf docstring migration
`db/alembic/versions/0021_d063_ingest_receipts.py`, source canonique des
colonnes). Deux modes d'écriture, jamais interchangeables :

  - `write_accepted_receipt` : DANS la transaction d'ingestion en cours (même
    connexion que l'upsert conversation + boucle INSERT messages). N'attrape
    RIEN — un échec ici doit faire ROLLBACK toute la transaction (atomicité :
    pas de messages sans reçu, pas de reçu sans messages).
  - `write_refusal_receipt` : connexion AUTONOME (best-effort, ouverte et
    fermée ici), appelée depuis les handlers d'exception. Ne DOIT jamais
    lever : un échec d'écriture du reçu ne doit jamais masquer l'erreur
    d'origine (400/413/422/409/429/500) déjà en cours de propagation vers le
    client.

Le futur `reconcile_audit` (WP-B) et les tests s'appuient sur ce module —
ne pas dupliquer le SQL d'INSERT ailleurs.
"""

from __future__ import annotations

import json
import logging
import os
import re

import psycopg
from psycopg import AsyncConnection

from app.services.sanitize import mask_recursive
from app.journal import raison

_logger = logging.getLogger("arac.services.ingest_receipts")

# `refusal_detail` est un texte DÉJÀ MASQUÉ (mask_recursive + emails) et
# tronqué — cette table ne doit jamais recevoir de contenu brut non scrubé
# (cf docstring migration 0021 ; TODO coordination FIX-D : cette docstring
# dit encore « masqué secrets » seul, à corriger en « masqué secrets +
# emails, peut contenir d'autres fragments » — cf rapport de ce lot, finding
# 15, fichier hors périmètre de ce lot).
_MAX_REFUSAL_DETAIL_CHARS = 500

# Masquage PII léger (finding 15, aligné sur `agents/cortex/review_queue.py`
# `_mask_emails`) : regex simple volontairement (pas de RFC 5322
# complet) — suffisant pour éviter qu'une adresse traîne en clair dans un
# `refusal_detail` (ex. un email présent dans un `conversation_uid` ou un
# message d'erreur de validation pydantic échoué).
_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def _mask_emails(text: str) -> str:
    return _EMAIL_PATTERN.sub("[REDACTED:email]", text)


def _prepare_refusal_detail(detail: str) -> str:
    """Masque secrets (`mask_recursive`) + emails (`_mask_emails`), puis
    tronque à `_MAX_REFUSAL_DETAIL_CHARS`."""
    masked = mask_recursive(detail)
    if not isinstance(masked, str):
        masked = str(masked)
    return _mask_emails(masked)[:_MAX_REFUSAL_DETAIL_CHARS]


async def write_accepted_receipt(
    conn: AsyncConnection,
    *,
    request_id: str,
    node_id: str,
    source_type: str,
    conversation_uid: str,
    http_status: int,
    received: int,
    inserted: int,
    duplicates: int,
    hash_divergences: int = 0,
    empty_messages: int = 0,
    created_at_nullified: int = 0,
    masked_messages: int = 0,
    nul_stripped: int = 0,
    body_sha256: str | None = None,
    reconcile: bool = False,
    scrub_hits: dict[str, int] | None = None,
    sensor_version: str | None = None,
    origin_kind: str | None = None,
    hops: int | None = None,
) -> None:
    """Écrit le reçu `outcome='accepted'` DANS la transaction en cours.

    Participe à l'atomicité (cf en-tête module) : n'attrape aucune exception
    — un échec de cet INSERT doit faire ROLLBACK la transaction appelante
    (conversation + messages inclus), jamais un accepted muet.

    `reconcile` (correctif issu de la revue adversariale)
    : `True` quand le batch appartient à une passe `--reconcile` (header
    `X-ARAC-Reconcile` résolu côté routeur, cf app/routers/ingest_v2.py
    `_resolve_reconcile`) — colonne `arac.ingest_receipts.reconcile`
    (existante depuis la migration 0021, jamais peuplée avant ce correctif).
    Consommée par `scripts/ops/reconcile_audit.py:collect_reconcile` pour la
    preuve zéro-perte périodique.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO arac.ingest_receipts (
                request_id, node_id, source_type, conversation_uid,
                outcome, http_status, received, inserted, duplicates,
                hash_divergences, empty_messages, created_at_nullified,
                masked_messages, nul_stripped, body_sha256, reconcile,
                scrub_hits, sensor_version, origin_kind, hops
            ) VALUES (
                %s, %s, %s, %s, 'accepted', %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s
            )
            """,
            (
                request_id,
                node_id,
                source_type,
                conversation_uid,
                http_status,
                received,
                inserted,
                duplicates,
                hash_divergences,
                empty_messages,
                created_at_nullified,
                masked_messages,
                nul_stripped,
                body_sha256,
                reconcile,
                json.dumps(scrub_hits) if scrub_hits is not None else None,
                sensor_version,
                origin_kind,
                hops,
            ),
        )


async def write_refusal_receipt(
    *,
    dsn: str | None = None,
    request_id: str,
    outcome: str,
    http_status: int,
    refusal_detail: str,
    node_id: str | None = None,
    source_type: str | None = None,
    conversation_uid: str | None = None,
    received: int = 0,
    empty_messages: int = 0,
    created_at_nullified: int = 0,
    masked_messages: int = 0,
    nul_stripped: int = 0,
    body_sha256: str | None = None,
    scrub_hits: dict[str, int] | None = None,
    sensor_version: str | None = None,
    origin_kind: str | None = None,
    hops: int | None = None,
) -> None:
    """Écrit un reçu de refus en connexion AUTONOME — best-effort, NE LÈVE JAMAIS.

    `dsn` par défaut `DATABASE_URL_APP` (env) — paramétrable pour les tests.
    Cf en-tête module : un échec d'écriture ici (DB indisponible, pool app
    épuisé, connexion déjà en erreur suite au refus d'origine) ne doit
    JAMAIS masquer l'erreur déjà en cours de propagation vers le client.
    Toute exception est loggée (`event=ingest_receipts.write_failed`) puis
    avalée.
    """
    effective_dsn = dsn or os.environ.get("DATABASE_URL_APP")
    if not effective_dsn:
        _logger.warning(
            "ingest_receipts.no_dsn",
            extra={"event": "ingest_receipts.write_skipped", "outcome": outcome},
        )
        return

    safe_detail = _prepare_refusal_detail(refusal_detail)

    try:
        async with await psycopg.AsyncConnection.connect(
            effective_dsn, autocommit=True
        ) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO arac.ingest_receipts (
                        request_id, node_id, source_type, conversation_uid,
                        outcome, http_status, received, empty_messages,
                        created_at_nullified, masked_messages, nul_stripped,
                        body_sha256, refusal_detail, scrub_hits, sensor_version,
                        origin_kind, hops
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s::jsonb, %s,
                        %s, %s
                    )
                    """,
                    (
                        request_id,
                        node_id,
                        source_type,
                        conversation_uid,
                        outcome,
                        http_status,
                        received,
                        empty_messages,
                        created_at_nullified,
                        masked_messages,
                        nul_stripped,
                        body_sha256,
                        safe_detail,
                        json.dumps(scrub_hits) if scrub_hits is not None else None,
                        sensor_version,
                        origin_kind,
                        hops,
                    ),
                )
    except Exception as exc:  # noqa: BLE001 — best-effort volontaire, cf docstring
        _logger.warning(
            "ingest_receipts.write_failed",
            extra={
                "event": "ingest_receipts.write_failed",
                "outcome": outcome,
                "request_id": request_id,
                "error": raison(exc),
            },
        )


__all__ = ["write_accepted_receipt", "write_refusal_receipt"]
