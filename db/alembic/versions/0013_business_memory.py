"""Phase F — cerveau métier : statuts étendus + colonnes de mémoire métier.

Ajout STRICTEMENT ADDITIF sur `arac.memory_atoms` :

  1. Élargit `memory_atoms_status_check` avec 3 statuts : 'disputed',
     'pending_review', 'blocked' (le gate I9 et la supersession en ont besoin).
     C'est un ÉLARGISSEMENT du domaine autorisé -> toutes les lignes existantes
     restent valides (aucune réécriture de donnée).
  2. Ajoute 6 colonnes nullable (metadata-only PG11+, pas de réécriture de table) :
       - supersedes        : pointeur INVERSE de `superseded_by` (déjà présent).
       - dedupe_key        : clé d'identité exacte (scope/kind/key normalisé).
       - semantic_hash     : sha256 du `value` normalisé (dédup sémantique).
       - observed_at       : quand le FAIT a été observé (≠ created_at = ingested_at).
       - last_verified_at  : dernière revérification (fraîcheur).
       - confirmed_until   : validité affirmée jusqu'à (fraîcheur / péremption).
  3. Index partiels : dedupe_key, semantic_hash, supersedes (WHERE … IS NOT NULL).

Colonnes DÉJÀ présentes réutilisées (cf 01_init.sql) : `superseded_by`,
`source_ref` (source), `created_at` (= ingested_at), `desc_hash`, `confidence`,
`confidence_score`.

Downgrade : retire les 6 colonnes + 3 index, et RESTAURE le CHECK d'origine (5
statuts). NON destructif des données existantes, MAIS échoue volontairement si un
atome porte un des 3 nouveaux statuts (sinon on créerait une donnée invalide) —
c'est le comportement correct : déclasser/migrer ces atomes AVANT de downgrader.

Doctrine : le DDL est écrit à la main via op.execute. Jamais
l'autogenerate d'Alembic : un diff automatique propose de supprimer ce
qu'il ne comprend pas.

Revision ID: 0013_business_memory
Revises: 0012_raw_conv_retry_journal
Create Date: 2026-06-30
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0013_business_memory"
down_revision: Union[str, None] = "0012_raw_conv_retry_journal"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUSES_NEW = (
    "active", "draft", "superseded", "archived", "low_confidence_archive",
    "disputed", "pending_review", "blocked",
)
_STATUSES_OLD = (
    "active", "draft", "superseded", "archived", "low_confidence_archive",
)


def _check_in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    # 1. Élargir le CHECK status (drop l'inline auto-nommé puis re-add nommé).
    op.execute(
        "ALTER TABLE arac.memory_atoms DROP CONSTRAINT IF EXISTS memory_atoms_status_check"
    )
    op.execute(
        "ALTER TABLE arac.memory_atoms ADD CONSTRAINT memory_atoms_status_check "
        f"CHECK (status IN ({_check_in(_STATUSES_NEW)}))"
    )
    # 2. Colonnes additives nullable (metadata-only).
    op.execute(
        "ALTER TABLE arac.memory_atoms "
        "  ADD COLUMN IF NOT EXISTS supersedes        UUID REFERENCES arac.memory_atoms(id) ON DELETE SET NULL, "
        "  ADD COLUMN IF NOT EXISTS dedupe_key        TEXT, "
        "  ADD COLUMN IF NOT EXISTS semantic_hash     TEXT, "
        "  ADD COLUMN IF NOT EXISTS observed_at       TIMESTAMPTZ, "
        "  ADD COLUMN IF NOT EXISTS last_verified_at  TIMESTAMPTZ, "
        "  ADD COLUMN IF NOT EXISTS confirmed_until   TIMESTAMPTZ"
    )
    # 3. Index partiels (sobres : uniquement les lignes pertinentes).
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_atoms_dedupe_key "
        "ON arac.memory_atoms (dedupe_key) WHERE dedupe_key IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_atoms_semantic_hash "
        "ON arac.memory_atoms (semantic_hash) WHERE semantic_hash IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_atoms_supersedes "
        "ON arac.memory_atoms (supersedes) WHERE supersedes IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS arac.idx_memory_atoms_supersedes")
    op.execute("DROP INDEX IF EXISTS arac.idx_memory_atoms_semantic_hash")
    op.execute("DROP INDEX IF EXISTS arac.idx_memory_atoms_dedupe_key")
    op.execute(
        "ALTER TABLE arac.memory_atoms "
        "  DROP COLUMN IF EXISTS confirmed_until, "
        "  DROP COLUMN IF EXISTS last_verified_at, "
        "  DROP COLUMN IF EXISTS observed_at, "
        "  DROP COLUMN IF EXISTS semantic_hash, "
        "  DROP COLUMN IF EXISTS dedupe_key, "
        "  DROP COLUMN IF EXISTS supersedes"
    )
    # Restaure le CHECK d'origine. Échoue si un atome porte un statut neuf
    # (disputed/pending_review/blocked) — déclasser ces atomes AVANT downgrade.
    op.execute(
        "ALTER TABLE arac.memory_atoms DROP CONSTRAINT IF EXISTS memory_atoms_status_check"
    )
    op.execute(
        "ALTER TABLE arac.memory_atoms ADD CONSTRAINT memory_atoms_status_check "
        f"CHECK (status IN ({_check_in(_STATUSES_OLD)}))"
    )
