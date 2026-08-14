"""V0.5 Cerveau Vivant — Bloc I2 — table arac.raw_conversations + trigger
NOTIFY (Bus-2) + declaration de VOTRE node source + seuils heartbeat.

LA REGLE QUE CETTE MIGRATION POSE :
  FK node_id raw_conversations -> arac.nodes : une conversation ne peut pas
  arriver d'un poste non declare. C'est CE garde-fou qui empeche le cerveau
  d'avaler n'importe quoi.

Cette migration :
  1. CREATE TABLE arac.raw_conversations (15 colonnes, FK node_id, CHECK status).
  2. 3 INDEX (status+received_at, expires_at partial, node_id+received_at DESC).
  3. CREATE FUNCTION arac.notify_conversation_ingested() (trigger Bus-2).
  4. CREATE TRIGGER trg_raw_conv_notify AFTER INSERT (canal conversation_ingested).
  5. INSERT du node d'ingestion dans arac.nodes (ON CONFLICT DO NOTHING).
     Son identifiant est VOTRE node_id (config/brain.toml, ou ARAC_NODE_ID) :
     c'est le poste depuis lequel vos conversations arriveront.
     - role='service', account='human', owner='owner'
     - silent_warn_minutes=300, silent_critical_minutes=600 : la synchro tourne
       toutes les quelques heures, un portable dort, un reseau tombe. Alerter
       plus tot ne signalerait que la vie normale.
  6. Pas d'INSERT arac.nodes_heartbeat (table inexistante en v0.5 — seule
     arac.nodes_heartbeat_history existe, append-only, sans seuils).
     Les seuils sont donc directement sur arac.nodes (colonnes existantes).

Doctrine : le DDL/DML est ecrit a la main via op.execute. Jamais
l'autogenerate d'Alembic : un diff automatique propose de supprimer ce
qu'il ne comprend pas.

Revision ID: 0008_raw_conv_ingest_node
Revises: 0007_scopes_hierarchique
Create Date: 2026-05-22

Note nommage : le slug est volontairement court (25 chars) car
arac.alembic_version.version_num est varchar(32) — un slug plus long
(p.ex. 0008_raw_conversations_and_ingest_node = 38 chars) casse le
UPDATE alembic_version avec StringDataRightTruncation.
"""

from typing import Sequence, Union

from alembic import op

import arac_runtime


def _node_id() -> str:
    """Le poste source declare a l'installation.

    Echouer ici est PREFERABLE a inventer : un node_id devine ouvrirait la
    porte a des conversations que le cerveau devrait refuser.
    """
    return arac_runtime.node_id()


def _sql_literal(value: str) -> str:
    """Un litteral SQL. Alembic n'expose pas de parametrage sur `op.execute`
    en mode offline (`--sql`), donc on echappe explicitement."""
    return "'" + value.replace("'", "''") + "'"

# revision identifiers, used by Alembic.
revision: str = "0008_raw_conv_ingest_node"
down_revision: Union[str, None] = "0007_scopes_hierarchique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === ETAPE 1 : CREATE TABLE arac.raw_conversations ===
    # La forme de cette table est celle que la migration pose ci-dessus :
    # c'est ce fichier qui fait foi, pas un document.
    # FK node_id Q4 + UNIQUE content_hash pour idempotence ingest (cf D2 spec).
    op.execute(
        """
        CREATE TABLE arac.raw_conversations (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            received_at     timestamptz NOT NULL DEFAULT now(),
            node_id         varchar(64) NOT NULL
                            REFERENCES arac.nodes(node_id) ON DELETE RESTRICT,
            session_uuid    uuid NULL,
            source_path     varchar(512) NOT NULL,
            content_gz      bytea NOT NULL,
            content_size    integer NOT NULL,
            content_hash    varchar(64) UNIQUE NOT NULL,
            message_count   integer NOT NULL,
            status          varchar(32) NOT NULL DEFAULT 'pending'
                            CHECK (status IN (
                                'pending', 'processing', 'curated',
                                'failed', 'purged'
                            )),
            curated_at      timestamptz NULL,
            atoms_generated integer NOT NULL DEFAULT 0,
            atoms_rejected  integer NOT NULL DEFAULT 0,
            expires_at      timestamptz NOT NULL
                            DEFAULT (now() + interval '90 days')
        )
        """
    )

    # === ETAPE 2 : 3 INDEX ===
    op.execute(
        """
        CREATE INDEX idx_raw_conv_status
            ON arac.raw_conversations (status, received_at)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_raw_conv_expires
            ON arac.raw_conversations (expires_at)
            WHERE status != 'purged'
        """
    )
    op.execute(
        """
        CREATE INDEX idx_raw_conv_node
            ON arac.raw_conversations (node_id, received_at DESC)
        """
    )

    # === ETAPE 3 : FONCTION TRIGGER Bus-2 (A1) ===
    # Pattern modele : arac.notify_agent_message (pg_proc existant v0.4).
    # Canal fixe 'conversation_ingested'. Payload JSON (raw_id, message_count,
    # node_id) pour permettre au listener (orchestrator/curator) de filtrer
    # ou batch sans relire la BDD.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION arac.notify_conversation_ingested()
        RETURNS trigger AS $$
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
        $$ LANGUAGE plpgsql
        """
    )

    # === ETAPE 4 : TRIGGER AFTER INSERT ===
    op.execute(
        """
        CREATE TRIGGER trg_raw_conv_notify
            AFTER INSERT ON arac.raw_conversations
            FOR EACH ROW
            EXECUTE FUNCTION arac.notify_conversation_ingested()
        """
    )

    # === ETAPE 5 : declarer VOTRE poste source ===
    # Le node_id vient de config/brain.toml (ou de ARAC_NODE_ID) : il n'est pas
    # ecrit dans cette migration, parce qu'il vous appartient.
    #
    # role='service'  : l'ingestion est un batch, sans intervention humaine.
    # account='human' : les conversations viennent de VOTRE abonnement.
    # owner='owner'   : le savoir est route vers VOTRE cerveau.
    node_id = _node_id()
    op.execute(
        """
        INSERT INTO arac.nodes (
            node_id, owner, account, role,
            silent_warn_minutes, silent_critical_minutes,
            active
        )
        VALUES (
            %(node_id)s, 'owner', 'human', 'service',
            300, 600,
            true
        )
        ON CONFLICT (node_id) DO NOTHING
        """.replace("%(node_id)s", _sql_literal(node_id))
    )


def downgrade() -> None:
    # === ETAPE 1 : DELETE le node source declare par l'entretien ===
    # Ordre : avant DROP TABLE (FK node_id depend de ce node, mais comme on
    # va DROP la table juste apres, ca passe ; DELETE en premier garde la
    # propriete que si raw_conversations est vide, la suppression est propre).
    op.execute(
        "DELETE FROM arac.nodes WHERE node_id = " + _sql_literal(_node_id())
    )

    # === ETAPE 2 : DROP TRIGGER ===
    op.execute(
        "DROP TRIGGER IF EXISTS trg_raw_conv_notify "
        "ON arac.raw_conversations"
    )

    # === ETAPE 3 : DROP FUNCTION ===
    op.execute(
        "DROP FUNCTION IF EXISTS arac.notify_conversation_ingested()"
    )

    # === ETAPE 4 : DROP TABLE (CASCADE pour les 3 index) ===
    op.execute("DROP TABLE IF EXISTS arac.raw_conversations CASCADE")
