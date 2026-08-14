"""F2 — retry/journaling pour la curation : colonnes + index catch-up + seed ack.

Ajout STRICTEMENT ADDITIF (faille F2 « échecs silencieux de la curation ») :
5 colonnes nullable/defaultées sur `arac.raw_conversations` + 1 index partiel +
un seed `acked=true` BORNÉ aux échecs terminaux que VOUS déclarez (par défaut :
aucun). AUCUNE colonne existante modifiée, AUCUN atome touché, AUCUNE autre
table / grant / index modifié.

Colonnes :
  - retry_count           : compteur d'essais borné (anti-boucle, cap MAX_RETRIES).
  - last_error            : motif INTERNE d'échec/skip (jamais du contenu de
                            conversation — uniquement des raisons structurées :
                            'chunks_failed:[...]', 'superseded_by_newer_snapshot:<id>',
                            'decompress_fail:<Type>', 'zero_atoms:...').
  - acked                 : suppression opérateur (terminal/non-rejouable).
                            SOURCE UNIQUE partagée avec l'ingest_watchdog.
  - next_retry_at         : planning du backoff linéaire (anti-martèlement).
  - processing_started_at : horodatage du passage en 'processing' (âge RÉEL,
                            distinct de received_at = heure d'ingestion) — permet
                            une alerte stuck-processing correcte.

DEFAULT constant (retry_count 0, acked false) = metadata-only en PG11+ (pas de
réécriture de table). Grants hérités de 0009 (arac_app/arac_agent/arac_readonly).
Le seed UPDATE n'écrit QUE la colonne neuve `acked` (additif, perdu au downgrade).

Downgrade : DROP des 5 colonnes + index, et rien d'autre — jamais une donnée
existante. Non destructif (perd seulement le book-keeping de retry).

Doctrine : le DDL est écrit à la main via `op.execute`, jamais engendré par
l'autogenerate d'Alembic. Une migration doit dire exactement ce qu'elle fait —
un diff automatique, lui, propose parfois de supprimer ce qu'il ne comprend pas.

Revision ID: 0012_raw_conv_retry_journal
Revises: 0011_imported_conversation_kind
Create Date: 2026-06-25
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers (26 chars <= 32, OK pour alembic_version varchar(32)).
revision: str = "0012_raw_conv_retry_journal"
down_revision: Union[str, None] = "0011_imported_conversation_kind"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Échecs de curation TERMINAUX (non-rejouables) à pré-acquitter, pour que le
# boot catch-up F2 ne les re-cure JAMAIS automatiquement — une re-curation
# automatique d'un échec terminal brûle du quota sans rien produire.
#
# VIDE PAR CONSTRUCTION, ET C'EST VOULU. Un identifiant de conversation n'a de
# sens que dans LA base où il existe : celui d'un autre cerveau ne
# correspondrait à aucune ligne ici. Le mécanisme reste, la donnée non.
#
# Quand vous en aurez un — typiquement une conversation trop massive dont la
# curation échoue de façon reproductible —, deux façons de l'acquitter :
#   - à chaud, sans migration : ARAC_INGEST_ACK_FAILED_IDS="<uuid>,<uuid>"
#     (lu par `app/perception/ingest_watchdog.py`, qui partage cette notion) ;
#   - durablement : ajoutez l'UUID ci-dessous dans VOTRE dépôt, ce qui rejoue
#     le seed au prochain `alembic upgrade`.
# La liste doit rester courte : elle dit « je renonce », pas « j'ignore ».
_TERMINAL_ACKED_IDS: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute(
        "ALTER TABLE arac.raw_conversations "
        "  ADD COLUMN IF NOT EXISTS retry_count           integer     NOT NULL DEFAULT 0, "
        "  ADD COLUMN IF NOT EXISTS last_error            text, "
        "  ADD COLUMN IF NOT EXISTS acked                 boolean     NOT NULL DEFAULT false, "
        "  ADD COLUMN IF NOT EXISTS next_retry_at         timestamptz, "
        "  ADD COLUMN IF NOT EXISTS processing_started_at timestamptz"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_raw_conv_retry_catchup "
        "ON arac.raw_conversations (status, next_retry_at) "
        "WHERE status IN ('pending', 'processing', 'failed')"
    )
    if _TERMINAL_ACKED_IDS:
        quoted = ", ".join(f"'{i}'::uuid" for i in _TERMINAL_ACKED_IDS)
        op.execute(
            "UPDATE arac.raw_conversations SET acked = true "
            f"WHERE id IN ({quoted}) AND status = 'failed'"
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS arac.idx_raw_conv_retry_catchup")
    op.execute(
        "ALTER TABLE arac.raw_conversations "
        "  DROP COLUMN IF EXISTS processing_started_at, "
        "  DROP COLUMN IF EXISTS next_retry_at, "
        "  DROP COLUMN IF EXISTS acked, "
        "  DROP COLUMN IF EXISTS last_error, "
        "  DROP COLUMN IF EXISTS retry_count"
    )
