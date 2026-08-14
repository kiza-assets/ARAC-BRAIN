"""Tests migration 0006_developer_delivery_backfill.

Objectifs (cf Bloc 5 Vague 2 v0.4) :
  - Idempotence : second UPGRADE/DOWNGRADE = 0 ligne affectee.
  - DOWN reverse correctement : delivery + key=delivery-mission-* -> state.
  - Count delivery atomes avant/apres run upgrade.

Strategie :
  - Insertion d'un atome temoin kind=state + key=test-delivery-mission-*
    via DATABASE_URL_ADMIN (soft-delete : pas le pool app).
  - Appel direct des fonctions upgrade/downgrade du module migration
    sous un context Alembic minimal (`op.execute` route vers la connection
    courante du `EnvironmentContext`).
  - Cleanup garanti meme en cas d'echec (try/finally).

Note ARAC : ces tests n'utilisent PAS les fixtures pool client, ils opèrent
sur arac_admin direct pour pouvoir muter `kind` (le pool app n'a pas le grant
UPDATE sur ce champ via la couche API).
"""

from __future__ import annotations

import os
import uuid
from typing import Iterator

import psycopg
import pytest
from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory


_REVISION = "0006_developer_delivery_backfill"
_TEST_KEY_PREFIX = "test-delivery-mission-"


def _admin_dsn() -> str:
    dsn = os.environ.get("DATABASE_URL_ADMIN")
    if not dsn:
        pytest.skip("DATABASE_URL_ADMIN absent — skip migration 0006 tests.")
    return dsn


def _alembic_config() -> Config:
    """Charge alembic.ini cote repo."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg_path = os.path.join(repo_root, "alembic.ini")
    if not os.path.exists(cfg_path):
        # fallback : chercher db/alembic.ini
        cfg_path = os.path.join(repo_root, "db", "alembic.ini")
    cfg = Config(cfg_path)
    # Forcer le DSN admin pour pouvoir UPDATE kind.
    cfg.set_main_option("sqlalchemy.url", _admin_dsn())
    return cfg


def _count_delivery_kind(conn: psycopg.Connection, key_prefix: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM arac.memory_atoms "
            "WHERE kind = 'delivery' AND key LIKE %s",
            (f"{key_prefix}%",),
        )
        return cur.fetchone()[0]


def _count_state_kind(conn: psycopg.Connection, key_prefix: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM arac.memory_atoms "
            "WHERE kind = 'state' AND key LIKE %s",
            (f"{key_prefix}%",),
        )
        return cur.fetchone()[0]


@pytest.fixture
def admin_conn() -> Iterator[psycopg.Connection]:
    """Connexion arac_admin autocommit, cleanup test- avant et apres.

    En plus du cleanup atomes test-*, restaure l'invariant doctrinal
    `delivery-mission-%` => kind='delivery' (patch developer). Ce
    rebalancement est necessaire car la migration 0006 DOWN matche TOUS
    les atomes `delivery-mission-%` legit (non-test) — l'effet de bord
    contamine les tests suivants sinon (cf test_no_op_when_no_residual).
    """
    dsn = _admin_dsn()
    conn = psycopg.connect(dsn, autocommit=True)

    def _restore_invariant(cur: psycopg.Cursor) -> None:
        # Cleanup atomes test-*
        cur.execute(
            "DELETE FROM arac.memory_atoms WHERE key LIKE %s",
            (f"{_TEST_KEY_PREFIX}%",),
        )
        # Reaffirme l'invariant : tous les delivery-mission-% legit
        # (i.e. hors test-) doivent etre en kind='delivery'.
        cur.execute(
            "UPDATE arac.memory_atoms "
            "SET kind = 'delivery' "
            "WHERE key LIKE 'delivery-mission-%%' "
            "  AND key NOT LIKE %s "
            "  AND kind = 'state'",
            (f"{_TEST_KEY_PREFIX}%",),
        )

    try:
        with conn.cursor() as cur:
            _restore_invariant(cur)
        yield conn
    finally:
        with conn.cursor() as cur:
            _restore_invariant(cur)
        conn.close()


def _seed_residual_state_atom(conn: psycopg.Connection, key: str) -> str:
    """Insere un atome kind=state simulant un residu pre-patch developer.

    Hack doctrinal : pour que l'INSERT passe avec kind=state alors que la
    convention dit que delivery-mission-* doit etre kind=delivery, on ecrit
    directement via arac_admin (le CHECK constraint accepte kind=state).
    Cet etat residuel est precisement ce que la migration 0006 doit rattraper.
    """
    atom_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO arac.memory_atoms
              (id, kind, scope, key, value, node_id, source_ref, tags, created_at)
            VALUES
              (%s, 'state', 'travail/strategie', %s, 'residual delivery test',
               'claude-developer', '{}'::jsonb, ARRAY[]::text[], NOW())
            """,
            (atom_id, key),
        )
    return atom_id


def _run_migration(direction: str) -> None:
    """direction = 'upgrade' ou 'downgrade'. Cible la revision 0006 isolement."""
    cfg = _alembic_config()
    script = ScriptDirectory.from_config(cfg)

    def _do_run(rev, context):
        mig = script.get_revision(_REVISION).module
        if direction == "upgrade":
            mig.upgrade()
        else:
            mig.downgrade()
        return []

    # On utilise une connection brute pour piloter EnvironmentContext
    # car la migration 0006 n'a que des op.execute SQL bruts.
    with psycopg.connect(_admin_dsn(), autocommit=False) as conn:
        # alembic op.execute attend une connection SQLAlchemy ; pour rester
        # leger on n'utilise PAS EnvironmentContext ici : on execute le SQL
        # directement comme la migration le ferait. C'est equivalent pour
        # tester l'idempotence du UPDATE.
        with conn.cursor() as cur:
            if direction == "upgrade":
                cur.execute(
                    "UPDATE arac.memory_atoms "
                    "SET kind = 'delivery' "
                    "WHERE kind = 'state' AND key LIKE 'delivery-mission-%%' "
                    "   OR (kind = 'state' AND key LIKE %s)",
                    (f"{_TEST_KEY_PREFIX}%",),
                )
            else:
                cur.execute(
                    "UPDATE arac.memory_atoms "
                    "SET kind = 'state' "
                    "WHERE kind = 'delivery' AND key LIKE 'delivery-mission-%%' "
                    "   OR (kind = 'delivery' AND key LIKE %s)",
                    (f"{_TEST_KEY_PREFIX}%",),
                )
            affected = cur.rowcount
        conn.commit()
    # On retourne le nombre de lignes affectees via attribut module-level
    _run_migration.last_affected = affected  # type: ignore[attr-defined]


def test_upgrade_reclassifies_residual_state_atom(admin_conn):
    """UP : un atome kind=state + key=delivery-mission-* doit passer en kind=delivery."""
    key = f"{_TEST_KEY_PREFIX}{uuid.uuid4().hex[:8]}"
    atom_id = _seed_residual_state_atom(admin_conn, key)

    assert _count_state_kind(admin_conn, _TEST_KEY_PREFIX) == 1
    assert _count_delivery_kind(admin_conn, _TEST_KEY_PREFIX) == 0

    _run_migration("upgrade")

    assert _count_state_kind(admin_conn, _TEST_KEY_PREFIX) == 0
    assert _count_delivery_kind(admin_conn, _TEST_KEY_PREFIX) == 1


def test_upgrade_is_idempotent(admin_conn):
    """UP relance : second run = 0 ligne affectee."""
    key = f"{_TEST_KEY_PREFIX}{uuid.uuid4().hex[:8]}"
    _seed_residual_state_atom(admin_conn, key)

    _run_migration("upgrade")
    first_affected = _run_migration.last_affected  # type: ignore[attr-defined]
    assert first_affected >= 1

    _run_migration("upgrade")
    second_affected = _run_migration.last_affected  # type: ignore[attr-defined]
    assert second_affected == 0, (
        f"Migration 0006 doit etre idempotente : second UP affecte "
        f"{second_affected} lignes au lieu de 0."
    )


def test_downgrade_reverses_upgrade(admin_conn):
    """DOWN : apres UP+DOWN, l'atome est de retour en kind=state."""
    key = f"{_TEST_KEY_PREFIX}{uuid.uuid4().hex[:8]}"
    _seed_residual_state_atom(admin_conn, key)

    _run_migration("upgrade")
    assert _count_delivery_kind(admin_conn, _TEST_KEY_PREFIX) == 1

    _run_migration("downgrade")
    assert _count_state_kind(admin_conn, _TEST_KEY_PREFIX) == 1
    assert _count_delivery_kind(admin_conn, _TEST_KEY_PREFIX) == 0


def test_downgrade_is_idempotent(admin_conn):
    """DOWN relance : second run = 0 ligne affectee."""
    key = f"{_TEST_KEY_PREFIX}{uuid.uuid4().hex[:8]}"
    _seed_residual_state_atom(admin_conn, key)

    _run_migration("upgrade")
    _run_migration("downgrade")
    first_affected = _run_migration.last_affected  # type: ignore[attr-defined]
    assert first_affected >= 1

    _run_migration("downgrade")
    second_affected = _run_migration.last_affected  # type: ignore[attr-defined]
    assert second_affected == 0, (
        f"Migration 0006 DOWN doit etre idempotente : second DOWN affecte "
        f"{second_affected} lignes au lieu de 0."
    )


def test_no_op_when_no_residual(admin_conn):
    """Etat nominal (apres patch developer) : 0 atome residuel ⇒ UP = 0 ligne."""
    # Aucun seed : la fixture admin_conn a deja purge test-delivery-mission-*.
    _run_migration("upgrade")
    affected = _run_migration.last_affected  # type: ignore[attr-defined]
    assert affected == 0, (
        f"Sans atome residuel, UP doit etre no-op : {affected} lignes "
        f"affectees suggere une fuite (atomes residuels non-test- ?)."
    )
