"""CHECK allowlist de `kind` resserré — les 4 kinds du BUS bannis à l'INSERT.

V3 (§1 L6, §3.1) : « le bus ne remontera plus jamais sur le cerveau » — les
142 atomes `agent_message` (tous inactifs, la garde F2A les archivait au POST)
sont le récit édifiant. Le CHECK existant (20 kinds) acceptait encore les
kinds du bus mort : `agent_message`, `mission_proposal`, `mission`, `delivery`.

**NOT VALID** (le point clé de gouvernance) : la contrainte ne s'applique
qu'aux NOUVELLES rows — les rows historiques des kinds bannis (142
agent_message + 21 mission + 21 delivery) restent en place, intactes.
La PURGE de ces rows (le « 0018 » du design d'ingestion V2) reste une opération
IRRÉVERSIBLE → GO humain explicite, désormais purement cosmétique : le bus
est déjà bloqué à l'écriture par cette contrainte.

Conservés (16) : les 12 kinds de connaissance (decision, pattern, gotcha,
state, todo, killed, note, idea, insight, question, reference,
imported_conversation_summary) + les 4 kinds d'audit (alert — posé par le
curateur HYBRID, validation, contradiction, suggestion — annotations de
connaissance, pas du bus).

NB : l'API (app/schemas/kind.py) accepte encore les 4 kinds bannis → un POST
de bus mourrait en erreur DB (aucune écriture) et non en 422 propre. Chemin
mort (daemons du bus masqués/archivés) ; le retrait des kinds côté API + la
démolition du code F2A/bus = vague Phase 3.

Downgrade : restaure le CHECK 20-kinds d'origine (relevé en prod 2026-07-03).

Revision ID: 0018_kind_allowlist_not_valid
Revises: 0017_freeze_raw_conversations
Create Date: 2026-07-03
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0018_kind_allowlist_not_valid"
down_revision: Union[str, None] = "0017_freeze_raw_conversations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ALLOWED_16 = (
    "'decision','pattern','gotcha','state','todo','killed','note','idea',"
    "'insight','question','reference','imported_conversation_summary',"
    "'alert','validation','contradiction','suggestion'"
)

_LEGACY_20 = (
    "'decision','pattern','gotcha','state','todo','killed','note','idea',"
    "'insight','question','reference','alert','validation','contradiction',"
    "'suggestion','agent_message','mission_proposal','mission','delivery',"
    "'imported_conversation_summary'"
)


def upgrade() -> None:
    op.execute("ALTER TABLE arac.memory_atoms DROP CONSTRAINT memory_atoms_kind_check")
    op.execute(
        "ALTER TABLE arac.memory_atoms ADD CONSTRAINT memory_atoms_kind_check "
        f"CHECK (kind IN ({_ALLOWED_16})) NOT VALID"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE arac.memory_atoms DROP CONSTRAINT memory_atoms_kind_check")
    op.execute(
        "ALTER TABLE arac.memory_atoms ADD CONSTRAINT memory_atoms_kind_check "
        f"CHECK (kind IN ({_LEGACY_20}))"
    )
