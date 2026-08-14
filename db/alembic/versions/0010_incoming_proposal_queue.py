"""V1.5B — table arac.incoming_proposal_queue (file des candidats NOUVEAUX issus de incoming).

Rationale :
    V1.5 a prouvé que arac.memory_review_queue est une file de REVUE D'ATOMES EXISTANTS
    (FK target_atom_id NOT NULL -> memory_atoms, CHECK no_value_change/no_scope_change TRUE).
    Les proposals issues de conversations (V1.4) sont des CANDIDATS NOUVEAUX sans atome cible.
    ADR V1.5B : table dédiée, sans FK vers
    memory_atoms, sans champ raw transcript. N'altère NI memory_atoms NI memory_review_queue.

Cette migration :
  1. CREATE TABLE arac.incoming_proposal_queue (18 colonnes, status CHECK, confidence CHECK,
     proposal_id UNIQUE ; AUCUN target_atom_id ; AUCUN champ raw transcript).
  2. 5 INDEX (status, source_hash, proposed_kind, created_at, human_required).
  3. GRANTs aux 4 rôles non-admin (doctrine : toute table arac, cf. migration 0009).

Doctrine : le DDL est écrit à la main via op.execute. Jamais
l'autogenerate d'Alembic : un diff automatique propose de supprimer ce
qu'il ne comprend pas.

Revision ID: 0010_incoming_proposal_queue
Revises: 0009_grants_raw_conv_node
Create Date: 2026-06-10
"""
from __future__ import annotations

from alembic import op
from db.alembic.roles import roles_arac

# revision identifiers, used by Alembic.  (28 chars <= 32, OK pour alembic_version)
revision = "0010_incoming_proposal_queue"
down_revision = "0009_grants_raw_conv_node"
branch_labels = None
depends_on = None


def upgrade() -> None:
    R = roles_arac()  # les cinq roles de CE cerveau (db/alembic/roles.py)
    op.execute(
        """
        CREATE TABLE arac.incoming_proposal_queue (
            id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            proposal_id       text NOT NULL,
            source_kind       text NOT NULL,
            source_file_id    text NOT NULL,
            source_hash       text NOT NULL,
            proposed_kind     text NOT NULL,
            proposed_scope    text NOT NULL,
            proposed_key      text,
            summary_redacted  text NOT NULL,
            confidence        double precision,
            risk_level        text NOT NULL,
            sensitive_flags   jsonb NOT NULL DEFAULT '{}'::jsonb,
            payload_redacted  jsonb NOT NULL DEFAULT '{}'::jsonb,
            status            text NOT NULL DEFAULT 'pending',
            human_required    boolean NOT NULL DEFAULT false,
            reject_reason     text,
            created_at        timestamptz NOT NULL DEFAULT now(),
            updated_at        timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_ipq_proposal_id UNIQUE (proposal_id),
            CONSTRAINT ck_ipq_status CHECK (
                status IN ('pending','approved','rejected','needs_human','superseded')),
            CONSTRAINT ck_ipq_confidence CHECK (
                confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
        );
        """
    )
    op.execute("COMMENT ON TABLE arac.incoming_proposal_queue IS "
               "'V1.5B file des candidats NOUVEAUX issus de incoming (pas de FK memory_atoms, pas de raw transcript).';")
    # Index
    op.execute("CREATE INDEX ix_ipq_status ON arac.incoming_proposal_queue (status);")
    op.execute("CREATE INDEX ix_ipq_source_hash ON arac.incoming_proposal_queue (source_hash);")
    op.execute("CREATE INDEX ix_ipq_proposed_kind ON arac.incoming_proposal_queue (proposed_kind);")
    op.execute("CREATE INDEX ix_ipq_created_at ON arac.incoming_proposal_queue (created_at);")
    op.execute("CREATE INDEX ix_ipq_human_required ON arac.incoming_proposal_queue (human_required);")
    # GRANTs (matrice alignée sur arac.memory_atoms / raw_conversations, cf. 0009)
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON arac.incoming_proposal_queue TO {R.app};")
    op.execute(f"GRANT SELECT, UPDATE ON arac.incoming_proposal_queue TO {R.agent};")
    op.execute(f"GRANT SELECT ON arac.incoming_proposal_queue TO {R.readonly};")
    op.execute(f"GRANT SELECT ON arac.incoming_proposal_queue TO {R.backup};")


def downgrade() -> None:
    # DROP de la SEULE table créée ici (index + contraintes tombent avec). Rien d'autre touché.
    op.execute("DROP TABLE IF EXISTS arac.incoming_proposal_queue;")
