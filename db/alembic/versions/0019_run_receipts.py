"""Table `run_receipts` — ledger de dépense IA write-ahead en DB.

V3 §3.3 : « fait office de ledger de dépense : INSERT write-ahead dans la
MÊME transaction qui réclame le travail, AVANT le spawn — un crash
sous-dépense, jamais ne sur-dépense ». Une row par run ET par skip avec
raison. Remplace le ledger FICHIER `ai_spend_ledger.json` comme source de
vérité des caps journaliers (le kill-switch RESTE un fichier — il doit
fonctionner DB down).

Points de design (arbitrage double avis) :
  - table PLATE, une row par run (pas de polymorphisme run/work/skip — refusé,
    machinerie de concurrence pour un mono-instance par construction) ;
  - `slot_key` UNIQUE = anti double-fire du même créneau circadien ;
  - `spawns`/`items` compteurs (pas un booléen) : l'interface SpendLedger
    est générique (plusieurs spawns/run pendant la transition batch->cortex) ;
  - comptage PARESSEUX préservé : un run qui ne dépense pas (skipped/empty)
    a spawns=0 et ne consomme NI le cap runs/jour NI l'intervalle minimal
    (sémantique existante de SpendGuard, spend_guard.py:374) ;
  - quarantaine EN DB (bytea <= 1 MiB + sha256) — jamais un fichier libre
    (fragments potentiellement sensibles), auditable par la conservation ;
  - grants: arac_agent RW (le cortex écrit), arac_app/readonly SELECT
    (cockpit) + REVOKE défensifs (DEFAULT PRIVILEGES du schéma, leçon 0015).

Downgrade : DROP TABLE (le ledger fichier reste utilisable par l'ancien code).

Revision ID: 0019_run_receipts
Revises: 0018_kind_allowlist_not_valid
Create Date: 2026-07-03
"""

from typing import Sequence, Union

from alembic import op
from db.alembic.roles import roles_arac

revision: str = "0019_run_receipts"
down_revision: Union[str, None] = "0018_kind_allowlist_not_valid"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    R = roles_arac()  # les cinq roles de CE cerveau (db/alembic/roles.py)
    op.execute(
        "CREATE TABLE IF NOT EXISTS arac.run_receipts ("
        "  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
        "  slot_key          text NOT NULL UNIQUE, "
        "  trigger           text NOT NULL CHECK (trigger IN "
        "                      ('circadian_0400','circadian_1300','circadian_2100',"
        "'manual','replay','legacy_batch')), "
        "  model             text NOT NULL, "
        "  status            text NOT NULL CHECK (status IN "
        "                      ('started','skipped','empty','spawning','spawn_failed',"
        "'quarantined','disposing','dispose_interrupted','done')), "
        "  skip_reason       text, "
        "  spawns            smallint NOT NULL DEFAULT 0 CHECK (spawns >= 0), "
        "  items             smallint NOT NULL DEFAULT 0 CHECK (items >= 0), "
        "  est_input_tokens  integer NOT NULL DEFAULT 0 CHECK (est_input_tokens >= 0), "
        "  first_spawn_at    timestamptz, "
        "  outcome           text, "
        "  pack              jsonb, "
        "  progress          jsonb, "
        "  atoms_created     integer NOT NULL DEFAULT 0, "
        "  atoms_superseded  integer NOT NULL DEFAULT 0, "
        "  atoms_confirmed   integer NOT NULL DEFAULT 0, "
        "  atoms_kept_lower_confidence integer NOT NULL DEFAULT 0, "
        "  atoms_policy_skips integer NOT NULL DEFAULT 0, "
        "  atoms_quarantined integer NOT NULL DEFAULT 0, "
        "  conflicts_409     integer NOT NULL DEFAULT 0, "
        "  quarantine_output bytea CHECK (quarantine_output IS NULL "
        "                                 OR octet_length(quarantine_output) <= 1048576), "
        "  quarantine_sha256 varchar(64) CHECK (quarantine_sha256 IS NULL "
        "                                       OR quarantine_sha256 ~ '^[0-9a-f]{64}$'), "
        "  quarantine_errors jsonb, "
        "  stop_reason       text, "
        "  utc_day           date NOT NULL DEFAULT (now() AT TIME ZONE 'utc')::date, "
        "  started_at        timestamptz NOT NULL DEFAULT now(), "
        "  ended_at          timestamptz)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_run_receipts_day_spend "
        "ON arac.run_receipts (utc_day) WHERE spawns > 0"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_run_receipts_open "
        "ON arac.run_receipts (status) "
        "WHERE status IN ('started','spawning','disposing','dispose_interrupted')"
    )

    # Grants : le cortex (arac_agent) écrit ; cockpit lit.
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON arac.run_receipts TO {R.agent};")
    op.execute(f"GRANT SELECT ON arac.run_receipts TO {R.app};")
    op.execute(f"GRANT SELECT ON arac.run_receipts TO {R.readonly};")
    # REVOKE défensifs (les DEFAULT PRIVILEGES du schéma donnent arw à arac_app).
    op.execute(f"REVOKE INSERT, UPDATE ON arac.run_receipts FROM {R.app};")
    op.execute(f"REVOKE DELETE ON arac.run_receipts FROM {R.agent};")
    op.execute(
        "DO $$ "
        "DECLARE seq_name text := pg_get_serial_sequence('arac.run_receipts', 'id'); "
        "BEGIN "
        f"  EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO {R.agent}', seq_name); "
        f"  EXECUTE format('REVOKE USAGE ON SEQUENCE %s FROM {R.app}', seq_name); "
        "END $$;"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS arac.run_receipts CASCADE")
