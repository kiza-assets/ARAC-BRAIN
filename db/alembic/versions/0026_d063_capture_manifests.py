"""`arac.capture_manifests` — un manifeste par run de scan de capture.

Chaque exécution d'un scanner de capture (Mac `arac-ingest-v2` existant, et
futur self-capture serveur WP-A) écrit UN manifeste résumant ce qu'elle a vu
ET ce qu'elle a filtré — la contrepartie « amont » de `run_receipts` (0019,
qui documente la dépense IA côté digestion) et d'`ingest_receipts` (0021,
qui documente chaque POST réseau). Le manifeste répond à « le scanner a-t-il
seulement REGARDÉ tout ce qu'il devait regarder ? » — question distincte de
« le serveur a-t-il accepté ce qu'on lui a envoyé ? ».

`messages_filtered` (jsonb, motif→count) : ex `{"empty_content": 3,
"non_curable_role": 1}` — un scanner qui filtre silencieusement doit
consigner CHAQUE motif de filtrage, jamais juste un total opaque.

`state_sha256` : empreinte de l'état de progression du scanner (curseur de
fichiers/sessions déjà vus) — permet de détecter une divergence d'état entre
deux runs consécutifs (WP-B/watchdog v4).

`ack_mismatches` : nombre de messages que le scanner croyait avoir déjà
envoyés (état local) mais que le serveur ne connaît pas (ou l'inverse) —
détecté par réconciliation (WP-B), 0 en fonctionnement normal.

Index (node_id, run_started_at DESC) : historique par nœud, le plus récent
en tête (cockpit santé v2, watchdog).

Grants : `arac_app` (le process de capture, qu'il tourne sur Mac ou serveur,
s'authentifie comme un rôle applicatif) INSERT/SELECT — REVOKE UPDATE/DELETE
(un manifeste est un fait clos, jamais réédité ; un run interrompu écrit un
NOUVEAU manifeste au prochain essai plutôt que de corriger l'ancien).

Downgrade : DROP TABLE (aucune autre table ne dépend de celle-ci).

Doctrine : le DDL est écrit à la main via op.execute. Jamais
l'autogenerate d'Alembic : un diff automatique propose de supprimer ce
qu'il ne comprend pas.

Revision ID: 0026_d063_capture_manifests
Revises: 0025_d063_schema_neutralizations
Create Date: 2026-07-06
"""

from typing import Sequence, Union

from alembic import op
from db.alembic.roles import roles_arac

revision: str = "0026_d063_capture_manifests"
down_revision: Union[str, None] = "0025_d063_schema_neutralizations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    R = roles_arac()  # les cinq roles de CE cerveau (db/alembic/roles.py)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS arac.capture_manifests (
            id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            node_id             text NOT NULL
                                  REFERENCES arac.nodes(node_id) ON DELETE RESTRICT,
            source_type         text NOT NULL
                                  CHECK (source_type ~ '^[a-z][a-z0-9_]{0,63}$'),
            run_started_at      timestamptz NOT NULL,
            run_ended_at        timestamptz,
            files_scanned       integer NOT NULL DEFAULT 0 CHECK (files_scanned >= 0),
            sessions            integer NOT NULL DEFAULT 0 CHECK (sessions >= 0),
            messages_read       integer NOT NULL DEFAULT 0 CHECK (messages_read >= 0),
            messages_emitted    integer NOT NULL DEFAULT 0 CHECK (messages_emitted >= 0),
            messages_filtered   jsonb,
            batches_ok          integer NOT NULL DEFAULT 0 CHECK (batches_ok >= 0),
            batches_failed      integer NOT NULL DEFAULT 0 CHECK (batches_failed >= 0),
            ack_mismatches      integer NOT NULL DEFAULT 0 CHECK (ack_mismatches >= 0),
            state_sha256        varchar(64)
                                  CHECK (state_sha256 IS NULL OR state_sha256 ~ '^[0-9a-f]{64}$'),
            archive_bytes       bigint CHECK (archive_bytes IS NULL OR archive_bytes >= 0),
            created_at          timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_capture_manifests_node_started "
        "ON arac.capture_manifests (node_id, run_started_at DESC)"
    )

    op.execute(f"GRANT SELECT, INSERT ON arac.capture_manifests TO {R.app};")
    op.execute(f"GRANT SELECT ON arac.capture_manifests TO {R.agent};")
    op.execute(f"GRANT SELECT ON arac.capture_manifests TO {R.readonly};")
    op.execute(f"REVOKE UPDATE, DELETE ON arac.capture_manifests FROM {R.app};")

    op.execute(
        "DO $$ "
        "DECLARE seq_name text := pg_get_serial_sequence('arac.capture_manifests', 'id'); "
        "BEGIN "
        f"  EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO {R.app}', seq_name); "
        f"  EXECUTE format('REVOKE USAGE ON SEQUENCE %s FROM {R.agent}', seq_name); "
        "END $$;"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS arac.capture_manifests CASCADE")
