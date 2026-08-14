"""0032 project_registry — cache dérivé (centroïdes par scope) pour le routeur de projet.

Couche de LIENS connaissances<->projets (P-V6-013..017). ADDITIF et RÉVERSIBLE
(downgrade = DROP TABLE). La table est un CACHE DÉRIVÉ des `memory_atoms` (un centroïde
par leaf-scope), recalculé à chaque tick cortex AVANT le spend gate — donc frais même
quand l'IA payante est OFF. Départ ASSUMÉ de l'append-only : table MUTABLE par design
(analogue à un index HNSW), jamais source de vérité. Zéro impact sur recall /
context_router / curateur (endpoint + outil MCP `resume` séparés, flag OFF par défaut).

Doctrine : le DDL est écrit à la main via op.execute. Jamais
l'autogenerate d'Alembic : un diff automatique propose de supprimer ce
qu'il ne comprend pas.
"""
from __future__ import annotations
from typing import Union
from alembic import op
from db.alembic.roles import roles_arac

revision: str = "0032_project_registry"
down_revision: Union[str, None] = "0031_memory_atom_reprs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    R = roles_arac()  # les cinq roles de CE cerveau (db/alembic/roles.py)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS arac.project_registry (
            scope         text PRIMARY KEY,
            centroid      halfvec(3072) NOT NULL,
            member_count  integer      NOT NULL,
            updated_at    timestamptz  NOT NULL DEFAULT now()
        )
        """
    )
    # index de fraîcheur (alerte possible si flag ON mais updated_at vieux)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_project_registry_updated_at "
        "ON arac.project_registry (updated_at)"
    )
    # Grants — CACHE MUTABLE (PAS append-only) : le cortex (arac_agent) recalcule
    # (INSERT/UPDATE/DELETE) ; l'API (arac_app) et l'analyse (arac_readonly) LISENT.
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON arac.project_registry TO {R.agent};")
    op.execute(f"GRANT SELECT ON arac.project_registry TO {R.app};")
    op.execute(f"GRANT SELECT ON arac.project_registry TO {R.readonly};")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS arac.project_registry")
