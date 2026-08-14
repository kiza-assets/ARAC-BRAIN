"""Phase D.5 — ajout du kind `delivery` (artefact developer post-mission).

Ajouts cette migration :
  1. Extension du CHECK constraint `memory_atoms_kind_check` pour autoriser
     la valeur `delivery` (19e kind ARAC).
  2. Reclassification des atomes existants déjà postés en `kind=state` avec
     `key LIKE 'delivery-mission-%'` vers le nouveau `kind=delivery`
     (rétro-typage propre — ces atomes étaient des deliveries déguisés en
     state faute du kind dédié avant cette migration).

Sémantique `delivery` : atome posté par le developer en fin de mission
attestant du livrable produit (PR, fichier, commit hash) — distinct d'un
simple snapshot d'état (state) qui décrit "où en est le module à l'instant
T" sans engagement de livraison.

Pas de nouveau trigger ni nouvelle table : `delivery` rejoint la famille
producteurs (cf app/schemas/kind.py PRODUCER_KINDS).

Doctrine : le DDL est écrit à la main via op.execute. Jamais
l'autogenerate d'Alembic : un diff automatique propose de supprimer ce
qu'il ne comprend pas.

Revision ID: 0004_delivery_immo_scopes
Revises: 0003_mission_kinds
Create Date: 2026-05-20
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_delivery_immo_scopes"
down_revision: Union[str, None] = "0003_mission_kinds"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_KIND_VALUES_V4 = (
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
    "delivery",  # nouveau Phase D.5 — atome developer post-mission
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE arac.memory_atoms DROP CONSTRAINT memory_atoms_kind_check"
    )
    quoted = ", ".join(f"'{k}'::text" for k in _KIND_VALUES_V4)
    op.execute(
        f"ALTER TABLE arac.memory_atoms ADD CONSTRAINT memory_atoms_kind_check "
        f"CHECK (kind = ANY (ARRAY[{quoted}]))"
    )
    # Rétro-typage : les deliveries déjà postées en kind=state passent en kind=delivery.
    op.execute(
        "UPDATE arac.memory_atoms "
        "SET kind = 'delivery' "
        "WHERE kind = 'state' AND key LIKE 'delivery-mission-%'"
    )


def downgrade() -> None:
    # Rétro-typage inverse avant retrait de la valeur du CHECK.
    op.execute(
        "UPDATE arac.memory_atoms "
        "SET kind = 'state' "
        "WHERE kind = 'delivery'"
    )
    op.execute(
        "ALTER TABLE arac.memory_atoms DROP CONSTRAINT memory_atoms_kind_check"
    )
    quoted_old = ", ".join(
        f"'{k}'::text"
        for k in _KIND_VALUES_V4
        if k != "delivery"
    )
    op.execute(
        f"ALTER TABLE arac.memory_atoms ADD CONSTRAINT memory_atoms_kind_check "
        f"CHECK (kind = ANY (ARRAY[{quoted_old}]))"
    )
