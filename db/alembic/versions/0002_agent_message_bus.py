"""Phase B triade — kind `agent_message` + trigger PG NOTIFY.

Ajouts cette migration :
  1. Extension du CHECK constraint `memory_atoms_kind_check` pour autoriser
     la valeur 'agent_message' (bus de communication inter-agents).
  2. Fonction plpgsql `arac.notify_agent_message()` qui émet
     `pg_notify('agent_inbox_' || replace(target_node_id, '-', '_'), atom_id)`
     quand un atome `kind='agent_message'` est inséré ET porte
     `source_ref->>'to'`.
  3. Trigger AFTER INSERT sur `arac.memory_atoms` qui appelle cette fonction.

Convention canal : `agent_inbox_<sanitized_node_id>` où les `-` sont
remplacés par `_` (les channel names PG sont des identifiers ; on sanitize
pour éviter les soucis de quoting côté psycopg `LISTEN`).

Payload NOTIFY : UUID de l'atome (texte). Le subscriber fait ensuite
`GET /v1/atoms/{id}` pour récupérer le contenu (value, rationale, source_ref).

Doctrine : le DDL est écrit à la main via op.execute. Jamais
l'autogenerate d'Alembic : un diff automatique propose de supprimer ce
qu'il ne comprend pas.

Revision ID: 0002_agent_message_bus
Revises: 0001_baseline_phase1b
Create Date: 2026-05-18
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_agent_message_bus"
down_revision: Union[str, None] = "0001_baseline_phase1b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_KIND_VALUES_V2 = (
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
    "agent_message",  # nouveau Phase B
)


def upgrade() -> None:
    # 1. Étendre le CHECK constraint kind
    op.execute(
        "ALTER TABLE arac.memory_atoms DROP CONSTRAINT memory_atoms_kind_check"
    )
    quoted = ", ".join(f"'{k}'::text" for k in _KIND_VALUES_V2)
    op.execute(
        f"ALTER TABLE arac.memory_atoms ADD CONSTRAINT memory_atoms_kind_check "
        f"CHECK (kind = ANY (ARRAY[{quoted}]))"
    )

    # 2. Fonction trigger NOTIFY
    op.execute("""
    CREATE OR REPLACE FUNCTION arac.notify_agent_message()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    DECLARE
        target_node text;
        channel text;
    BEGIN
        IF NEW.kind <> 'agent_message' THEN
            RETURN NEW;
        END IF;
        IF NEW.source_ref IS NULL OR NEW.source_ref->>'to' IS NULL THEN
            RETURN NEW;
        END IF;
        target_node := NEW.source_ref->>'to';
        channel := 'agent_inbox_' || replace(target_node, '-', '_');
        PERFORM pg_notify(channel, NEW.id::text);
        RETURN NEW;
    END;
    $$;
    """)

    # 3. Trigger AFTER INSERT
    op.execute("""
    CREATE TRIGGER tg_agent_message_notify
    AFTER INSERT ON arac.memory_atoms
    FOR EACH ROW
    EXECUTE FUNCTION arac.notify_agent_message();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS tg_agent_message_notify ON arac.memory_atoms")
    op.execute("DROP FUNCTION IF EXISTS arac.notify_agent_message()")

    # Restaurer l'ancien CHECK constraint sans 'agent_message'
    op.execute(
        "ALTER TABLE arac.memory_atoms DROP CONSTRAINT memory_atoms_kind_check"
    )
    quoted_old = ", ".join(
        f"'{k}'::text" for k in _KIND_VALUES_V2 if k != "agent_message"
    )
    op.execute(
        f"ALTER TABLE arac.memory_atoms ADD CONSTRAINT memory_atoms_kind_check "
        f"CHECK (kind = ANY (ARRAY[{quoted_old}]))"
    )
