"""Ledger `arac.ingest_receipts` — une row par POST d'ingestion, refus inclus.

Chaîne de preuve amont (WP-B consommera cette table) : chaque appel à un
endpoint d'ingestion (`/v1/ingest/messages` et futurs) écrit UNE row ici,
QUE la requête soit acceptée, dédupliquée, ou REFUSÉE (400/403/413/422/409/
429/500). Sans ça, un refus silencieux (bug, quota, corruption body) laisse
un trou de couverture invisible — exactement le défaut que corrige ce
chantier. (`refused_403` ajouté après coup :
manquait dans le CHECK initial, le refus whitelist node n'écrivait aucun
reçu.)

Colonnes de comptage (`hash_divergences`, `empty_messages`,
`created_at_nullified`, `masked_messages`, `nul_stripped`) : NON destinées à
un usage typique (elles seront à 0 la quasi-totalité du temps) — ce sont des
compteurs de « heal » silencieux appliqués par le sensor/l'endpoint avant
stockage (ex: un `\\u0000` strippé plutôt que de faire échouer tout le
batch). `refusal_detail` est un texte MASQUÉ par l'appelant
(`_prepare_refusal_detail`, `app/services/ingest_receipts.py` — secrets via
`mask_recursive` PUIS e-mails via `_mask_emails`, tronqué à
`_MAX_REFUSAL_DETAIL_CHARS`) avant d'écrire ici — cette colonne peut
néanmoins contenir des fragments de contenu NON-PII (ex. un extrait de
message HTTP d'erreur Pydantic citant un bout de payload) : le masquage
couvre les secrets/e-mails connus, PAS une garantie d'anonymisation totale
du texte libre. Cette table ne doit jamais recevoir de contenu brut non
scrubé (cf `scrub_hits` qui consigne CE QUI a été masqué, pas la valeur).

`request_id` : identifiant de corrélation assigné par le serveur à CHAQUE
requête entrante (avant même le parsing du body) — permet de retrouver la
row même pour un refus précoce (body illisible) où `node_id`/
`conversation_uid` restent NULL faute d'avoir pu être extraits.

Index (WP-B / cockpit santé v2) :
  - (node_id, created_at)  : couverture par nœud dans le temps.
  - (outcome)               : compter les refus par type.
  - (request_id)            : retrouver la trace d'une requête précise.

Grants (moindre privilège) : `arac_app` (l'endpoint) INSERT/SELECT — JAMAIS
UPDATE/DELETE (un receipt est un fait immuable, on n'édite pas l'histoire).
`arac_agent` (santé v2 / cockpit) SELECT seul.

Downgrade : DROP TABLE (aucune autre table ne dépend de celle-ci).

Doctrine : le DDL est écrit à la main via op.execute. Jamais
l'autogenerate d'Alembic : un diff automatique propose de supprimer ce
qu'il ne comprend pas.

Revision ID: 0021_d063_ingest_receipts
Revises: 0020_d063_ingest_sources
Create Date: 2026-07-06
"""

from typing import Sequence, Union

from alembic import op
from db.alembic.roles import roles_arac

revision: str = "0021_d063_ingest_receipts"
down_revision: Union[str, None] = "0020_d063_ingest_sources"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    R = roles_arac()  # les cinq roles de CE cerveau (db/alembic/roles.py)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS arac.ingest_receipts (
            id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            request_id             uuid NOT NULL,
            node_id                text,
            source_type            text,
            conversation_uid       text,
            outcome                text NOT NULL CHECK (outcome IN (
                                       'accepted', 'duplicate_noop', 'refused_400',
                                       'refused_403', 'refused_413', 'refused_422',
                                       'refused_409', 'rate_limited_429', 'error_500'
                                   )),
            http_status            integer NOT NULL
                                       CHECK (http_status BETWEEN 100 AND 599),
            received                integer NOT NULL DEFAULT 0 CHECK (received >= 0),
            inserted                integer NOT NULL DEFAULT 0 CHECK (inserted >= 0),
            duplicates              integer NOT NULL DEFAULT 0 CHECK (duplicates >= 0),
            hash_divergences        integer NOT NULL DEFAULT 0 CHECK (hash_divergences >= 0),
            empty_messages          integer NOT NULL DEFAULT 0 CHECK (empty_messages >= 0),
            created_at_nullified    integer NOT NULL DEFAULT 0 CHECK (created_at_nullified >= 0),
            masked_messages         integer NOT NULL DEFAULT 0 CHECK (masked_messages >= 0),
            nul_stripped            integer NOT NULL DEFAULT 0 CHECK (nul_stripped >= 0),
            body_sha256             text,
            reconcile               boolean NOT NULL DEFAULT false,
            refusal_detail          text,
            scrub_hits              jsonb,
            sensor_version          text,
            origin_kind             text,
            hops                    integer CHECK (hops IS NULL OR hops >= 0),
            created_at              timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ingest_receipts_node_created "
        "ON arac.ingest_receipts (node_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ingest_receipts_outcome "
        "ON arac.ingest_receipts (outcome)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ingest_receipts_request_id "
        "ON arac.ingest_receipts (request_id)"
    )

    # Grants : arac_app (endpoint) écrit et lit, jamais n'édite/supprime un
    # receipt déjà posé. arac_agent (santé v2 / WP-B) lit seul.
    op.execute(f"GRANT SELECT, INSERT ON arac.ingest_receipts TO {R.app};")
    op.execute(f"GRANT SELECT ON arac.ingest_receipts TO {R.agent};")
    op.execute(f"GRANT SELECT ON arac.ingest_receipts TO {R.readonly};")
    # REVOKE défensifs (DEFAULT PRIVILEGES du schéma donnent arw à arac_app,
    # r à arac_agent — on ferme explicitement l'écriture pour les deux).
    op.execute(f"REVOKE UPDATE, DELETE ON arac.ingest_receipts FROM {R.app};")
    op.execute(f"REVOKE INSERT, UPDATE, DELETE ON arac.ingest_receipts FROM {R.agent};")

    op.execute(
        "DO $$ "
        "DECLARE seq_name text := pg_get_serial_sequence('arac.ingest_receipts', 'id'); "
        "BEGIN "
        f"  EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO {R.app}', seq_name); "
        f"  EXECUTE format('REVOKE USAGE ON SEQUENCE %s FROM {R.agent}', seq_name); "
        "END $$;"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS arac.ingest_receipts CASCADE")
