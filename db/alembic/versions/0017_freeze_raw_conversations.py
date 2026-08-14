"""GEL lecture-seule de arac.raw_conversations (étape 0017).

La file vivante est désormais V2 (`arac.conversations` / `arac.raw_messages`,
migration 0015) : exporteurs Mac basculés, curateur v2 actif (flag), curseurs
initialisés depuis l'historique curé. `raw_conversations` devient une table
de LIGNÉE : les atomes créés avant la bascule pointent
`source_ref.curator_raw_id` vers ses rows — elle n'est JAMAIS backfillée,
JAMAIS droppée. Sur un cerveau installé après la bascule, elle reste vide, et
c'est normal : le gel protège une lignée, il ne la fabrique pas (cf DESIGN-INGEST-V2
« GELÉE lecture-seule, JAMAIS backfillée ni droppée »).

Ce gel rend l'immutabilité vraie PAR GRANT (pas par convention) :
  - REVOKE INSERT/UPDATE/DELETE aux rôles applicatifs (arac_app, arac_agent).
  - arac_admin (opérateur) conserve tout — les corrections restent possibles
    sous GO humain.
  - SELECT conservé partout (lignée consultable, dashboard, backups).

TTL/purge : AUCUN job vivant ne purge par `expires_at` (vérifié par grep
2026-07-03 — le mécanisme était prospectif). Si un job de rétention naît un
jour (hygiene V3), il DOIT exclure cette table : la lignée des atomes n'a
pas de TTL.

Le pendant applicatif (route POST /v1/ingest/conversations → 410 Gone) est
un changement de code app/, hors migration.

Downgrade : restaure les grants relevés en prod le 2026-07-03
(app: SELECT,INSERT,UPDATE ; agent: SELECT,UPDATE).

Revision ID: 0017_freeze_raw_conversations
Revises: 0016_drop_notify_triggers
Create Date: 2026-07-03
"""

from typing import Sequence, Union

from alembic import op
from db.alembic.roles import roles_arac

revision: str = "0017_freeze_raw_conversations"
down_revision: Union[str, None] = "0016_drop_notify_triggers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    R = roles_arac()  # les cinq roles de CE cerveau (db/alembic/roles.py)
    op.execute(f"REVOKE INSERT, UPDATE, DELETE ON arac.raw_conversations FROM {R.app}")
    op.execute(f"REVOKE INSERT, UPDATE, DELETE ON arac.raw_conversations FROM {R.agent}")


def downgrade() -> None:
    # Grants pré-gel relevés en prod (2026-07-03).
    R = roles_arac()  # les cinq roles de CE cerveau (db/alembic/roles.py)
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON arac.raw_conversations TO {R.app}")
    op.execute(f"GRANT SELECT, UPDATE ON arac.raw_conversations TO {R.agent}")
