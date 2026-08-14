"""Patch GRANTs raw_conversations + nodes — catch-up oubli migration 0008.

Revision ID: 0009_grants_raw_conv_node
Revises: 0008_raw_conv_ingest_node
Create Date: 2026-05-22

Rationale :
    Migration 0008 (raw_conversations + INSERT de VOTRE node source)
    a omis les GRANTs nécessaires pour les rôles non-admin (arac_app, arac_agent,
    arac_readonly) sur la nouvelle table arac.raw_conversations. Découvert par
    agent I8 (tests endpoint ingest) : 8/15 tests fail
    'permission denied for table raw_conversations' sur le pool runtime arac_app.

    Matrice cible alignée sur arac.memory_atoms (même matrice que memory_atoms) :
      - arac_app     : SELECT, INSERT, UPDATE  (endpoint /v1/ingest + idempotence check)
      - arac_agent   : SELECT, UPDATE          (curator UPDATE status + atoms_generated)
      - arac_readonly: SELECT                  (dashboard /v1/dashboard/ingest_stats)
      - arac_backup  : SELECT                  (pg_dump quotidien)

    Sur arac.nodes : déjà OK (arac_app=arw, arac_agent=r+last_heartbeat write,
    arac_readonly=r) — pas de modification nécessaire.

    Trace doctrine : atome gotcha `gotcha-migration-grants-oubli-raw-conv-2026-05-22`
    posé en parallèle dans scope travail/strategie pour figer le pattern "toute
    migration alembic créant une table dans schéma arac DOIT inclure les GRANTs
    aux 3 rôles non-admin".
"""
from __future__ import annotations

from alembic import op
from db.alembic.roles import roles_arac

# revision identifiers, used by Alembic.
revision = "0009_grants_raw_conv_node"
down_revision = "0008_raw_conv_ingest_node"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Pose les GRANTs manquants alignés sur la matrice arac.memory_atoms."""
    # arac_app : endpoint POST /v1/ingest + idempotence SELECT
    R = roles_arac()  # les cinq roles de CE cerveau (db/alembic/roles.py)
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON arac.raw_conversations TO {R.app};")

    # arac_agent : curator UPDATE status, atoms_generated, curated_at
    op.execute(f"GRANT SELECT, UPDATE ON arac.raw_conversations TO {R.agent};")

    # arac_readonly : dashboard ingest_stats
    op.execute(f"GRANT SELECT ON arac.raw_conversations TO {R.readonly};")

    # arac_backup (cohérence avec memory_atoms — pg_dump quotidien)
    op.execute(f"GRANT SELECT ON arac.raw_conversations TO {R.backup};")


def downgrade() -> None:
    """REVOKE symétrique (ordre inverse)."""
    R = roles_arac()  # les cinq roles de CE cerveau (db/alembic/roles.py)
    op.execute(f"REVOKE SELECT ON arac.raw_conversations FROM {R.backup};")
    op.execute(f"REVOKE SELECT ON arac.raw_conversations FROM {R.readonly};")
    op.execute(f"REVOKE SELECT, UPDATE ON arac.raw_conversations FROM {R.agent};")
    op.execute(f"REVOKE SELECT, INSERT, UPDATE ON arac.raw_conversations FROM {R.app};")
