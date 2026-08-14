"""Neutralisations de schéma mort + unité masquée sur `raw_messages`.

⚠️ NUMÉROTATION — label `0024` VOLONTAIREMENT SAUTÉ/RÉSERVÉ. La vague
« Perception V4 » partage l'autorité de numérotation Alembic avec une
branche prospective `context-engine-v4`, qui avait déjà réservé le slug de
migration `0024`. Résultat : la chaîne Alembic reste
UNIQUE et linéaire (0019→0020→0021→0022→0023→**0025**→0026→0027→0028, PAS
de 0024 dans cette vague) — un multi-head aurait cassé `alembic upgrade
head`. Si la branche `context-engine-v4` merge un jour un fichier `0024_*`,
il devra se chaîner sur `0023_d063_conversation_exclusion` (down_revision),
exactement comme celui-ci — jamais l'inverse (ce fichier ne dépend PAS de
lui, il vient AVANT dans la chaîne par ce simple accord de label).

Ce fichier fait deux choses SANS AUCUN RAPPORT entre elles (regroupées ici
uniquement parce que ce sont les deux dernières neutralisations de schéma
mort identifiées par l'audit WP-D avant que les tables du reste de la
chaîne « Perception V4 » ne soient posées) :

  1. DROP COLUMN `raw_conversations.expires_at` + DROP INDEX
     `idx_raw_conv_expires`. Legacy V1 (0008) : un TTL de purge à 90 jours
     qui n'a JAMAIS été consommé par un job vivant (0017 l'avait déjà
     documenté : « AUCUN job vivant ne purge par expires_at »; re-vérifié
     par grep 2026-07-06 — les seuls autres `expires_at` du repo sont des
     champs JSON de `app/brain/proposal_lifecycle.py`, sans rapport).
     **ZÉRO ROW TOUCHÉE** (`raw_conversations` = 388 rows, GELÉE lecture
     seule depuis 0017 — ce DROP retire une colonne morte, ne réécrit
     aucune donnée). Downgrade : recrée la colonne (même défaut `now() +
     interval '90 days'`, NOT NULL) + le même index partiel
     (`WHERE status != 'purged'`) — relevés en prod 2026-07-06 par `\\d
     arac.raw_conversations` / `pg_indexes`.
  2. ADD COLUMN `raw_messages.was_masked boolean NOT NULL DEFAULT false` —
     additif pur. Permet au futur code de capture/healing (WP-A/B) de
     signaler qu'un message a subi un masquage avant stockage (dérivé du
     même besoin que `ingest_receipts.masked_messages` / `scrub_hits`, mais
     au niveau du message individuel plutôt qu'agrégé par POST).

Doctrine : le DDL est écrit à la main via op.execute. Jamais
l'autogenerate d'Alembic : un diff automatique propose de supprimer ce
qu'il ne comprend pas.

Revision ID: 0025_d063_schema_neutralizations
Revises: 0023_d063_conversation_exclusion
Create Date: 2026-07-06
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0025_d063_schema_neutralizations"
down_revision: Union[str, None] = "0023_d063_conversation_exclusion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS arac.idx_raw_conv_expires")
    op.execute(
        "ALTER TABLE arac.raw_conversations DROP COLUMN IF EXISTS expires_at"
    )
    op.execute(
        "ALTER TABLE arac.raw_messages "
        "ADD COLUMN IF NOT EXISTS was_masked boolean NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE arac.raw_messages DROP COLUMN IF EXISTS was_masked"
    )
    op.execute(
        "ALTER TABLE arac.raw_conversations "
        "ADD COLUMN IF NOT EXISTS expires_at timestamptz NOT NULL "
        "DEFAULT (now() + interval '90 days')"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_raw_conv_expires "
        "ON arac.raw_conversations (expires_at) WHERE status != 'purged'"
    )
