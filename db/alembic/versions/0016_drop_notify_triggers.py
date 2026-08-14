"""DROP des 2 triggers NOTIFY legacy (V3 « rien ne réveille rien »).

Cible V3 : un événement est une transition de
row durable ; la table + curseur EST la file. Les 2 triggers NOTIFY sont du
legacy à ZÉRO consommateur (prouvé : le daemon curateur LISTEN est retiré+masqué
depuis l'incident coût, le bus agents est mort) :

  - `trg_raw_conv_notify` sur `arac.raw_conversations` (channel
    `conversation_ingested`) — consommateur = daemon curateur legacy, masqué.
  - `tg_agent_message_notify` sur `arac.memory_atoms` (channels
    `agent_inbox_*`) — consommateur = bus agents, mort des deux côtés.

RÉVERSIBLE (classe « autonome » du design d'ingestion V2) : le downgrade recrée
triggers + functions à L'IDENTIQUE des définitions relevées en prod le
2026-07-03 (`pg_get_triggerdef`/`pg_get_functiondef`). Les functions sont
conservées par l'upgrade ? NON — droppées aussi (aucun autre call site :
vérifié par grep repo + pg_proc), le downgrade les recrée.

Revision ID: 0016_drop_notify_triggers
Revises: 0015_ingest_v2_messages
Create Date: 2026-07-03
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0016_drop_notify_triggers"
down_revision: Union[str, None] = "0015_ingest_v2_messages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_raw_conv_notify ON arac.raw_conversations")
    op.execute("DROP FUNCTION IF EXISTS arac.notify_conversation_ingested()")
    op.execute("DROP TRIGGER IF EXISTS tg_agent_message_notify ON arac.memory_atoms")
    op.execute("DROP FUNCTION IF EXISTS arac.notify_agent_message()")


def downgrade() -> None:
    # Recréation à l'identique (définitions prod relevées 2026-07-03).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION arac.notify_conversation_ingested()
         RETURNS trigger
         LANGUAGE plpgsql
        AS $function$
                BEGIN
                    PERFORM pg_notify(
                        'conversation_ingested',
                        json_build_object(
                            'raw_id', NEW.id::text,
                            'message_count', NEW.message_count,
                            'node_id', NEW.node_id
                        )::text
                    );
                    RETURN NEW;
                END;
                $function$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_raw_conv_notify AFTER INSERT ON arac.raw_conversations "
        "FOR EACH ROW EXECUTE FUNCTION arac.notify_conversation_ingested()"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION arac.notify_agent_message()
         RETURNS trigger
         LANGUAGE plpgsql
        AS $function$
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
        $function$
        """
    )
    op.execute(
        "CREATE TRIGGER tg_agent_message_notify AFTER INSERT ON arac.memory_atoms "
        "FOR EACH ROW EXECUTE FUNCTION arac.notify_agent_message()"
    )
