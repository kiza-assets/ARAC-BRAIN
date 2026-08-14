"""Phase D.5 vague 2 — backfill residuel kind=delivery (filet de securite).

Contexte :
- Migration `0004_delivery_immo_scopes` a deja :
    1. Ajoute `delivery` au CHECK constraint `memory_atoms_kind_check` (19e kind).
    2. Reclassifie les atomes `kind=state` + `key LIKE delivery-mission-%`
       preexistants vers `kind=delivery`.
- Le code `agents/developer/main.py` continuait neanmoins a POST avec
  `kind=state` (note obsolete : whitelist 18 kinds) jusqu'a cette vague.
  -> des atomes residuels mal types ont pu etre crees entre 0004 et le patch
    de `_post_delivery`.

Cette migration 0006 est un **filet de securite idempotent** : elle
reapplique le retro-typage `state -> delivery` pour toute key residuelle
`delivery-mission-%`. Si aucun atome residuel n'existe (etat nominal apres
patch du code), 0 ligne affectee — la migration reste safe a relancer.

Doctrine : le DDL/DML est écrit à la main via op.execute. Jamais
l'autogenerate d'Alembic : un diff automatique propose de supprimer ce
qu'il ne comprend pas.
Doctrine ARAC anti-fabulation : la migration 0006 ne *cree pas* le kind
`delivery` (deja present depuis 0004) ; elle se contente du rattrapage data.

Revision ID: 0006_developer_delivery_backfill
Revises: 0005_warnings_audit_log
Create Date: 2026-05-22
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_developer_delivery_backfill"
down_revision: Union[str, None] = "0005_warnings_audit_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rattrapage : tout atome encore type state alors qu'il est une delivery
    # (key prefixee delivery-mission-) repasse a kind=delivery.
    # Idempotent : seconde execution => 0 ligne (le filtre kind=state ne match plus).
    op.execute(
        """
        UPDATE arac.memory_atoms
        SET kind = 'delivery'
        WHERE kind = 'state' AND key LIKE 'delivery-mission-%'
        """
    )


def downgrade() -> None:
    # Symetrique : seuls les atomes delivery-mission-% repassent a state.
    # Idempotent : seconde execution => 0 ligne.
    op.execute(
        """
        UPDATE arac.memory_atoms
        SET kind = 'state'
        WHERE kind = 'delivery' AND key LIKE 'delivery-mission-%'
        """
    )
