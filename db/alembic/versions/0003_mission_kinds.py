"""Phase D plumbing — ajout des kinds `mission_proposal` et `mission`.

Ajouts cette migration :
  1. Extension du CHECK constraint `memory_atoms_kind_check` pour autoriser
     les valeurs `mission_proposal` et `mission`.

Pas de nouveau trigger : le routage bus continue de reposer sur
`agent_message` (cf migration 0002). Les atomes `mission_proposal`/`mission`
sont des artefacts doctrinaux pilotés par l'orchestrator/auditor ; le
dispatch developer en Phase D.1+ passe par un atome `agent_message` séparé
qui pointe vers la mission (source_ref.mission_atom_id).

Doctrine : le DDL est écrit à la main via op.execute. Jamais
l'autogenerate d'Alembic : un diff automatique propose de supprimer ce
qu'il ne comprend pas.

Revision ID: 0003_mission_kinds
Revises: 0002_agent_message_bus
Create Date: 2026-05-19
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_mission_kinds"
down_revision: Union[str, None] = "0002_agent_message_bus"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_KIND_VALUES_V3 = (
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
    "mission_proposal",  # nouveau Phase D — orchestrator propose une mission
    "mission",           # nouveau Phase D — proposal validée par l'auditeur
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE arac.memory_atoms DROP CONSTRAINT memory_atoms_kind_check"
    )
    quoted = ", ".join(f"'{k}'::text" for k in _KIND_VALUES_V3)
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
        for k in _KIND_VALUES_V3
        if k not in ("mission_proposal", "mission")
    )
    op.execute(
        f"ALTER TABLE arac.memory_atoms ADD CONSTRAINT memory_atoms_kind_check "
        f"CHECK (kind = ANY (ARRAY[{quoted_old}]))"
    )
