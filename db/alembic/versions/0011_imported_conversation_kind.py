"""V1.6B — ajout du kind `imported_conversation_summary` (Option C validée).

Ajout STRICTEMENT BORNÉ : une seule valeur ajoutée au CHECK constraint
`memory_atoms_kind_check` (20e kind ARAC). Aucun autre kind modifié,
aucun atome existant touché, aucune table/index/grant modifié.

Sémantique : résumé redacted issu d'un IMPORT de conversation (pipeline
incoming → incoming_proposal_queue → semantic dry-run → human approval →
memory_atoms). Le nom porte la provenance (`imported_`) — anti-fabulation by
design : ce n'est ni du transcript brut, ni une pensee native de l'utilisateur.
Decision de conception (cf journal des decisions du projet,
analyse).

Downgrade : restaure la liste à 19 kinds. ⚠️ échouera (violation CHECK) tant
qu'il existe des lignes `kind='imported_conversation_summary'` — il faut
d'abord supprimer/requalifier ces atomes (procédure : requalifier avant d'appliquer
section rollback). C'est voulu : un downgrade ne doit jamais invalider
silencieusement des données vivantes.

Doctrine : le DDL est écrit à la main via op.execute. Jamais
l'autogenerate d'Alembic : un diff automatique propose de supprimer ce
qu'il ne comprend pas.

Revision ID: 0011_imported_conversation_kind
Revises: 0010_incoming_proposal_queue
Create Date: 2026-06-11
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.  (31 chars <= 32, OK pour alembic_version)
revision: str = "0011_imported_conversation_kind"
down_revision: Union[str, None] = "0010_incoming_proposal_queue"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Les 19 kinds existants (état live vérifié 2026-06-11, read-only) + le nouveau.
_KIND_VALUES_V11 = (
    "decision",
    "pattern",
    "gotcha",
    "state",
    "todo",
    "killed",
    "note",
    "idea",
    "insight",
    "question",
    "reference",
    "alert",
    "validation",
    "contradiction",
    "suggestion",
    "agent_message",
    "mission_proposal",
    "mission",
    "delivery",
    "imported_conversation_summary",  # nouveau V1.6B — Option C, pilote 1 atome
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE arac.memory_atoms DROP CONSTRAINT memory_atoms_kind_check"
    )
    quoted = ", ".join(f"'{k}'::text" for k in _KIND_VALUES_V11)
    op.execute(
        f"ALTER TABLE arac.memory_atoms ADD CONSTRAINT memory_atoms_kind_check "
        f"CHECK (kind = ANY (ARRAY[{quoted}]))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE arac.memory_atoms DROP CONSTRAINT memory_atoms_kind_check"
    )
    quoted_old = ", ".join(
        f"'{k}'::text"
        for k in _KIND_VALUES_V11
        if k != "imported_conversation_summary"
    )
    op.execute(
        f"ALTER TABLE arac.memory_atoms ADD CONSTRAINT memory_atoms_kind_check "
        f"CHECK (kind = ANY (ARRAY[{quoted_old}]))"
    )
