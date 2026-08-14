"""Phase G — cerveau code : tables code_* (repo/file/symbol/route/test/edge/link).

Ajout STRICTEMENT ADDITIF : 7 NOUVELLES tables dans le schéma `arac`, AUCUNE
table existante touchée, AUCUN atome modifié. Sépare physiquement la mémoire
CODE de la mémoire MÉTIER (memory_atoms). Indexation incrémentale : `code_file`
porte `sha256` + `last_commit` ; `code_repo.head_commit` permet de court-circuiter
un scan complet si HEAD inchangé.

Graphe d'impact : `code_edge` (src_file -> dst_file, kind='import'). Lien optionnel
code <-> décision métier : `code_atom_link` (advisory).

Hiérarchie ON DELETE CASCADE (repo -> file -> symbol/route/test) : ré-indexer =
remplacer proprement, sans orphelins.

Downgrade : DROP des 7 tables en ordre FK inverse. NON destructif des données
métier (ne touche QUE les tables code_*).

Doctrine : le DDL est écrit à la main via op.execute, jamais
l'autogenerate d'Alembic.

Revision ID: 0014_code_brain
Revises: 0013_business_memory
Create Date: 2026-06-30
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0014_code_brain"
down_revision: Union[str, None] = "0013_business_memory"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS arac.code_repo ("
        "  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "  name          TEXT NOT NULL UNIQUE, "
        "  root_path     TEXT NOT NULL, "
        "  default_branch TEXT, "
        "  head_commit   TEXT, "
        "  indexed_at    TIMESTAMPTZ DEFAULT NOW())"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS arac.code_file ("
        "  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "  repo_id     UUID NOT NULL REFERENCES arac.code_repo(id) ON DELETE CASCADE, "
        "  path        TEXT NOT NULL, "
        "  sha256      TEXT NOT NULL, "
        "  module      TEXT, "
        "  last_commit TEXT, "
        "  parse_error TEXT, "
        "  indexed_at  TIMESTAMPTZ DEFAULT NOW(), "
        "  UNIQUE (repo_id, path))"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS arac.code_symbol ("
        "  id      UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "  file_id UUID NOT NULL REFERENCES arac.code_file(id) ON DELETE CASCADE, "
        "  name    TEXT NOT NULL, "
        "  kind    TEXT NOT NULL CHECK (kind IN ('function','class','method')), "
        "  lineno  INT)"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS arac.code_route ("
        "  id      UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "  file_id UUID NOT NULL REFERENCES arac.code_file(id) ON DELETE CASCADE, "
        "  method  TEXT NOT NULL, "
        "  path    TEXT NOT NULL, "
        "  handler TEXT NOT NULL)"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS arac.code_test ("
        "  id      UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "  file_id UUID NOT NULL REFERENCES arac.code_file(id) ON DELETE CASCADE, "
        "  name    TEXT NOT NULL)"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS arac.code_edge ("
        "  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "  repo_id     UUID NOT NULL REFERENCES arac.code_repo(id) ON DELETE CASCADE, "
        "  src_file_id UUID NOT NULL REFERENCES arac.code_file(id) ON DELETE CASCADE, "
        "  dst_file_id UUID NOT NULL REFERENCES arac.code_file(id) ON DELETE CASCADE, "
        "  kind        TEXT NOT NULL DEFAULT 'import')"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS arac.code_atom_link ("
        "  id        UUID PRIMARY KEY DEFAULT gen_random_uuid(), "
        "  repo_id   UUID NOT NULL REFERENCES arac.code_repo(id) ON DELETE CASCADE, "
        "  code_path TEXT NOT NULL, "
        "  atom_id   UUID NOT NULL REFERENCES arac.memory_atoms(id) ON DELETE CASCADE, "
        "  kind      TEXT NOT NULL DEFAULT 'relates_to')"
    )
    # Index de requête (sobres).
    op.execute("CREATE INDEX IF NOT EXISTS idx_code_symbol_name ON arac.code_symbol (name)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_code_route_method_path ON arac.code_route (method, path)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_code_edge_dst ON arac.code_edge (dst_file_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_code_file_repo_path ON arac.code_file (repo_id, path)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_code_atom_link_atom ON arac.code_atom_link (atom_id)")


def downgrade() -> None:
    # Ordre FK inverse (enfants d'abord).
    for tbl in ("code_atom_link", "code_edge", "code_test", "code_route",
                "code_symbol", "code_file", "code_repo"):
        op.execute(f"DROP TABLE IF EXISTS arac.{tbl} CASCADE")
