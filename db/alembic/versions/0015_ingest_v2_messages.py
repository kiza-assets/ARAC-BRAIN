"""V2 ingestion par-message — tables conversations + raw_messages.

Ajout STRICTEMENT ADDITIF : 2 NOUVELLES tables dans le schéma `arac`
(`conversations`, `raw_messages`), AUCUNE table existante touchée, AUCUN
atome modifié. Coexiste avec le legacy `raw_conversations` (GELÉ lecture-
seule, JAMAIS backfillé ni droppé par cette migration — lignée des atomes
déjà curés préservée à jamais).

Schéma (additif) :
  - `arac.conversations` : 1 row / conversation source, clé naturelle
    UNIQUE(source_type, conversation_uid). Curseur de curation
    `curated_through_message_id` = watermark GLOBAL sur `raw_messages.id`
    (PAS un compteur par-conversation, PAS de seq dénormalisé) + colonnes
    retry/ack : mêmes sémantiques bornées que curator_lib legacy (backoff
    linéaire, cap).
  - `arac.raw_messages` : 1 row / message, `id` GENERATED ALWAYS AS IDENTITY
    = watermark d'arrivée global (ordre attribué PAR LE SERVEUR — un
    message tardif prend le rang suivant, jamais de ré-ordonnancement).
    `dedup_key` GENERATED ALWAYS AS (COALESCE(message_uuid, 'h:'||content_hash))
    STORED → idempotence via UNIQUE(conversation_id, dedup_key) même si le
    client ne fournit pas d'uuid stable (fallback hash).
  - CHECK de discipline (bon marché, attrape la corruption) : format
    `source_type`, `conversation_uid` non-vide, `role IN ('user','assistant')`,
    `content_hash` format sha256 hex, `curated_through_message_id >= 0`.
  - 3 index : (conversation_id, id) pour le gate curateur v2, (conversation_id,
    msg_created_at) pour le tri chronologique, (received_at) pour le
    dead-man / cockpit sobriety.

Grants (moindre privilège par chemin d'écriture réel — S9 revue adversariale) :
  - arac_app (endpoint) : SELECT,INSERT,UPDATE conversations + SELECT,INSERT
    raw_messages (append-only : PAS d'UPDATE sur le brut) + séquence identity.
  - arac_agent (curateur v2) : SELECT,UPDATE conversations (curseur) +
    SELECT raw_messages. N'insère rien, ne modifie jamais le brut.
  - arac_readonly : SELECT sur les 2 tables (dashboard).

Downgrade : DROP des 2 tables en ordre FK inverse (`raw_messages` avant
`conversations`). Non destructif du legacy `raw_conversations` (jamais
touché par cette migration).

Doctrine : le DDL est écrit à la main via op.execute. Jamais
l'autogenerate d'Alembic : un diff automatique propose de supprimer ce
qu'il ne comprend pas.

Revision ID: 0015_ingest_v2_messages
Revises: 0014_code_brain
Create Date: 2026-07-02
"""

from typing import Sequence, Union

from alembic import op
from db.alembic.roles import roles_arac

revision: str = "0015_ingest_v2_messages"
down_revision: Union[str, None] = "0014_code_brain"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    R = roles_arac()  # les cinq roles de CE cerveau (db/alembic/roles.py)
    op.execute(
        "CREATE TABLE IF NOT EXISTS arac.conversations ("
        "  id                          uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
        "  source_type                 text NOT NULL DEFAULT 'claude_code' "
        "                                 CHECK (source_type ~ '^[a-z][a-z0-9_]{0,63}$'), "
        "  conversation_uid            text NOT NULL "
        "                                 CHECK (length(btrim(conversation_uid)) > 0), "
        "  node_id                     varchar(64) NOT NULL "
        "                                 REFERENCES arac.nodes(node_id) ON DELETE RESTRICT, "
        "  title                       text, "
        "  curated_through_message_id  bigint NOT NULL DEFAULT 0 "
        "                                 CHECK (curated_through_message_id >= 0), "
        "  curated_at                  timestamptz, "
        "  atoms_generated             integer NOT NULL DEFAULT 0, "
        "  last_curation_error         text, "
        "  retry_count                 integer NOT NULL DEFAULT 0, "
        "  acked                       boolean NOT NULL DEFAULT false, "
        "  next_retry_at               timestamptz, "
        "  created_at                  timestamptz NOT NULL DEFAULT now(), "
        "  updated_at                  timestamptz NOT NULL DEFAULT now(), "
        "  CONSTRAINT conversations_uid_uq UNIQUE (source_type, conversation_uid))"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS arac.raw_messages ("
        "  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
        "  conversation_id  uuid NOT NULL "
        "                     REFERENCES arac.conversations(id) ON DELETE RESTRICT, "
        "  message_uuid     text, "
        "  parent_uuid      text, "
        "  role             text NOT NULL CHECK (role IN ('user','assistant')), "
        "  content          text NOT NULL, "
        "  content_hash     varchar(64) NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'), "
        "  dedup_key        text GENERATED ALWAYS AS "
        "                     (COALESCE(message_uuid, 'h:'||content_hash)) STORED, "
        "  msg_created_at   timestamptz, "
        "  received_at      timestamptz NOT NULL DEFAULT now(), "
        "  node_id          varchar(64) NOT NULL "
        "                     REFERENCES arac.nodes(node_id) ON DELETE RESTRICT, "
        "  CONSTRAINT raw_messages_dedup_uq UNIQUE (conversation_id, dedup_key))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_rawmsg_conv_id "
        "ON arac.raw_messages (conversation_id, id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_rawmsg_conv_created "
        "ON arac.raw_messages (conversation_id, msg_created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_rawmsg_received "
        "ON arac.raw_messages (received_at)"
    )

    # Grants — MOINDRE PRIVILÈGE par chemin d'écriture réel (revue
    # adversariale 2026-07-03, S9 : « immuable » doit être vrai par GRANT,
    # pas par convention) :
    #   - arac_app (endpoint) : upsert conversations + INSERT raw_messages.
    #     JAMAIS d'UPDATE sur raw_messages (append-only).
    #   - arac_agent (curateur) : lit raw_messages, avance le curseur sur
    #     conversations. N'insère rien, ne modifie jamais le brut.
    #   - arac_readonly : SELECT (dashboard).
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON arac.conversations TO {R.app};")
    op.execute(f"GRANT SELECT, UPDATE ON arac.conversations TO {R.agent};")
    op.execute(f"GRANT SELECT ON arac.conversations TO {R.readonly};")

    op.execute(f"GRANT SELECT, INSERT ON arac.raw_messages TO {R.app};")
    op.execute(f"GRANT SELECT ON arac.raw_messages TO {R.agent};")
    op.execute(f"GRANT SELECT ON arac.raw_messages TO {R.readonly};")

    # Les DEFAULT PRIVILEGES du schéma arac (owner postgres) donnent `arw`
    # (SELECT,INSERT,UPDATE) à arac_app sur TOUTE nouvelle table — REVOKE
    # explicite pour que « append-only » soit vrai PAR GRANT, pas par
    # convention (vérifié sur clone prod : sans ce REVOKE, UPDATE fuit).
    op.execute(f"REVOKE UPDATE ON arac.raw_messages FROM {R.app};")
    op.execute(f"REVOKE INSERT, UPDATE ON arac.raw_messages FROM {R.agent};")

    # Séquence identity raw_messages.id : nom résolu dynamiquement (colonne
    # IDENTITY, pas un `serial` classique — on ne fige pas le nom en dur).
    # Seul arac_app insère -> seul lui a besoin de la séquence.
    op.execute(
        "DO $$ "
        "DECLARE seq_name text := pg_get_serial_sequence('arac.raw_messages', 'id'); "
        "BEGIN "
        f"  EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO {R.app}', seq_name); "
        f"  EXECUTE format('REVOKE USAGE ON SEQUENCE %s FROM {R.agent}', seq_name); "
        "END $$;"
    )


def downgrade() -> None:
    # Ordre FK inverse (enfants d'abord) — legacy raw_conversations JAMAIS touché.
    op.execute("DROP TABLE IF EXISTS arac.raw_messages CASCADE")
    op.execute("DROP TABLE IF EXISTS arac.conversations CASCADE")
