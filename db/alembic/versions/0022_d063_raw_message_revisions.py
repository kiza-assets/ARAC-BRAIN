"""Lignée `arac.raw_message_revisions` — divergence de hash / healing sur un message brut.

`arac.raw_messages` (0015) est append-only PAR GRANT (aucun UPDATE possible
pour `arac_app`/`arac_agent`). Mais deux situations légitimes exigent de
tracer un CHANGEMENT de contenu observé pour le même message logique
(`dedup_key`) sans jamais réécrire silencieusement la row brute :

  - `hash_divergence` : un même `dedup_key` (uuid stable ou fallback hash)
    arrive une 2e fois avec un `content_hash` DIFFÉRENT de la row déjà en
    base (édition côté client, corruption, ou collision) — on consigne
    l'écart plutôt que de l'ignorer ou d'écraser.
  - `healing` : une correction a posteriori d'un contenu déjà stocké
    (ex: masquage appliqué rétroactivement) — même logique de traçabilité,
    jamais un UPDATE en place.

Chaque row pointe le message brut concerné (`raw_message_id`) et sa
conversation (`conversation_id`, dénormalisé pour requêtage direct — même
choix que `raw_messages.node_id`/`conversation_id`). `incoming_content_masked`
est le contenu ENTRANT déjà masqué par l'appelant avant écriture (jamais de
contenu brut non scrubé stocké ici — même discipline que `ingest_receipts.
refusal_detail`).

`actor` : identifiant du COMPOSANT/rôle ayant produit la révision (ex:
`ingest_v3_healer`, `endpoint_ingest_messages`) — JAMAIS un prénom/nom
d'opérateur (règle no-PII des audit-refs).

Append-only PAR GRANT (même discipline que `raw_messages`) : `arac_app`
INSERT/SELECT, REVOKE UPDATE/DELETE.

Downgrade : DROP TABLE (aucune autre table ne dépend de celle-ci).

Doctrine : le DDL est écrit à la main via op.execute. Jamais
l'autogenerate d'Alembic : un diff automatique propose de supprimer ce
qu'il ne comprend pas.

Revision ID: 0022_d063_raw_message_revisions
Revises: 0021_d063_ingest_receipts
Create Date: 2026-07-06
"""

from typing import Sequence, Union

from alembic import op
from db.alembic.roles import roles_arac

revision: str = "0022_d063_raw_message_revisions"
down_revision: Union[str, None] = "0021_d063_ingest_receipts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    R = roles_arac()  # les cinq roles de CE cerveau (db/alembic/roles.py)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS arac.raw_message_revisions (
            id                        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            raw_message_id            bigint NOT NULL
                                         REFERENCES arac.raw_messages(id) ON DELETE RESTRICT,
            conversation_id           uuid NOT NULL
                                         REFERENCES arac.conversations(id) ON DELETE RESTRICT,
            dedup_key                 text NOT NULL
                                         CHECK (length(btrim(dedup_key)) > 0),
            existing_content_hash     varchar(64) NOT NULL
                                         CHECK (existing_content_hash ~ '^[0-9a-f]{64}$'),
            incoming_content_hash     varchar(64) NOT NULL
                                         CHECK (incoming_content_hash ~ '^[0-9a-f]{64}$'),
            incoming_content_masked   text NOT NULL,
            reason                    text NOT NULL
                                         CHECK (reason IN ('hash_divergence', 'healing')),
            request_id                uuid,
            actor                     text NOT NULL
                                         CHECK (length(btrim(actor)) > 0),
            created_at                timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_raw_msg_revisions_message "
        "ON arac.raw_message_revisions (raw_message_id, created_at)"
    )

    # Append-only PAR GRANT (même discipline que raw_messages, 0015).
    op.execute(f"GRANT SELECT, INSERT ON arac.raw_message_revisions TO {R.app};")
    op.execute(f"GRANT SELECT ON arac.raw_message_revisions TO {R.agent};")
    op.execute(f"GRANT SELECT ON arac.raw_message_revisions TO {R.readonly};")
    op.execute(f"REVOKE UPDATE, DELETE ON arac.raw_message_revisions FROM {R.app};")
    op.execute(f"REVOKE INSERT, UPDATE, DELETE ON arac.raw_message_revisions FROM {R.agent};")

    op.execute(
        "DO $$ "
        "DECLARE seq_name text := pg_get_serial_sequence('arac.raw_message_revisions', 'id'); "
        "BEGIN "
        f"  EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO {R.app}', seq_name); "
        f"  EXECUTE format('REVOKE USAGE ON SEQUENCE %s FROM {R.agent}', seq_name); "
        "END $$;"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS arac.raw_message_revisions CASCADE")
