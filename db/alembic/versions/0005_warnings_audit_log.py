"""Phase 4.6 — persistence warnings anti-drift dans arac.audit_log.

Ajouts cette migration :
  1. Colonne `warning_code` TEXT — code court du warning (W-001..W-007).
     NULL pour les entrées audit_log non-warning (action='read', 'write', ...).
  2. Colonne `warning_context` JSONB — payload riche du warning
     (severity, message, context, remediation_hint).
  3. Index partial `ix_audit_log_warning_code` WHERE warning_code IS NOT NULL —
     accélère le dashboard analytics Phase 6+ qui ne lit que les lignes
     warning (cf agent R1 vague 1 spec, audit_log router I3).

Schéma cible (rappel) :
    arac.audit_log (
      id BIGSERIAL,
      node_id TEXT NOT NULL FK arac.nodes,
      action TEXT NOT NULL,        -- 'warning' Phase 4.6 (en plus de read/write)
      tool_name TEXT,
      target_atom_id UUID,
      query TEXT,
      result_summary JSONB,
      tokens_used INTEGER,
      latency_ms INTEGER,
      success BOOLEAN DEFAULT TRUE,
      error_message TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      warning_code TEXT,           -- NEW Phase 4.6
      warning_context JSONB        -- NEW Phase 4.6
    )

Doctrine : le DDL est écrit à la main via op.execute. Jamais
l'autogenerate d'Alembic : un diff automatique propose de supprimer ce
qu'il ne comprend pas.

Revision ID: 0005_warnings_audit_log
Revises: 0004_delivery_immo_scopes
Create Date: 2026-05-20
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_warnings_audit_log"
down_revision: Union[str, None] = "0004_delivery_immo_scopes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE arac.audit_log
          ADD COLUMN warning_code TEXT,
          ADD COLUMN warning_context JSONB
        """
    )
    op.execute(
        """
        CREATE INDEX ix_audit_log_warning_code
          ON arac.audit_log(warning_code)
          WHERE warning_code IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS arac.ix_audit_log_warning_code")
    op.execute(
        """
        ALTER TABLE arac.audit_log
          DROP COLUMN IF EXISTS warning_context,
          DROP COLUMN IF EXISTS warning_code
        """
    )
