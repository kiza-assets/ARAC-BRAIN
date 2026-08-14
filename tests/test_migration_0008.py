"""Tests migration 0008_raw_conv_ingest_node (V0.5 Cerveau Vivant Bloc I2).

Objectifs :
  - Etat post-UP : table arac.raw_conversations existe avec colonnes attendues.
  - FK node_id -> arac.nodes(node_id) ON DELETE RESTRICT presente et active.
  - Trigger trg_raw_conv_notify + fonction notify_conversation_ingested
    presents et fonctionnels (test live via LISTEN/NOTIFY async).
  - CHECK status (5 valeurs autorisees) rejette statut invalide.
  - UNIQUE content_hash : INSERT duplique rejete (idempotence ingest).
  - Node 'poste-ingest' present post-migration avec seuils
    silent_warn=300, silent_critical=600 (decision Q4 Alice).
  - 4 INDEX presents (pkey + 3 idx_raw_conv_*).

Strategie :
  - Tests "etat" : lecture seule arac.raw_conversations + arac.nodes
    post-migration deja appliquee (alembic head = 0008). Pas de seed.
  - Tests INSERT contraintes : utilisation prefixe content_hash 'test-0008-'
    pour cleanup propre.
  - Test live NOTIFY : connexion psycopg async dediee LISTEN + INSERT,
    timeout 5s sur reception payload.
  - Tests idempotence UP / down reverse : MARQUES SKIP (mutating BDD live),
    pattern identique a test_migration_0007.

Cf doctrine du soft-delete : cleanup via DATABASE_URL_ADMIN, jamais pool arac_app.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import AsyncIterator, Iterator

import psycopg
import pytest
import pytest_asyncio


_REVISION = "0008_raw_conv_ingest_node"
_TEST_HASH_PREFIX = "test-0008-"
_INGEST_NODE_ID = "poste-ingest"
_NOTIFY_CHANNEL = "conversation_ingested"

# Colonnes attendues sur arac.raw_conversations (14 colonnes + ordre).
_EXPECTED_COLUMNS: tuple[str, ...] = (
    "id",
    "received_at",
    "node_id",
    "session_uuid",
    "source_path",
    "content_gz",
    "content_size",
    "content_hash",
    "message_count",
    "status",
    "curated_at",
    "atoms_generated",
    "atoms_rejected",
    "expires_at",
)

# CHECK constraint status : 5 valeurs autorisees.
_VALID_STATUSES: tuple[str, ...] = (
    "pending", "processing", "curated", "failed", "purged",
)


def _admin_dsn() -> str:
    dsn = os.environ.get("DATABASE_URL_ADMIN")
    if not dsn:
        pytest.skip("DATABASE_URL_ADMIN absent — skip migration 0008 tests.")
    return dsn


@pytest.fixture
def admin_conn() -> Iterator[psycopg.Connection]:
    """Connexion arac_admin autocommit, cleanup raw_conv test- avant/apres."""
    dsn = _admin_dsn()
    conn = psycopg.connect(dsn, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM arac.raw_conversations "
                "WHERE content_hash LIKE %s",
                (f"{_TEST_HASH_PREFIX}%",),
            )
        yield conn
    finally:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM arac.raw_conversations "
                "WHERE content_hash LIKE %s",
                (f"{_TEST_HASH_PREFIX}%",),
            )
        conn.close()


# ============================================================================
# TESTS ETAT POST-UP (alembic head = 0008 deja applique sur arac live)
# ============================================================================


def test_alembic_head_is_0008(admin_conn):
    """alembic_version.version_num doit etre '0008_raw_conv_ingest_node'."""
    with admin_conn.cursor() as cur:
        cur.execute("SELECT version_num FROM arac.alembic_version")
        version = cur.fetchone()[0]
    assert version == _REVISION, (
        f"alembic_version doit etre {_REVISION}, trouve {version}."
    )


def test_raw_conversations_table_exists(admin_conn):
    """Table arac.raw_conversations presente avec 14 colonnes attendues."""
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'arac'
              AND table_name = 'raw_conversations'
            ORDER BY ordinal_position
            """
        )
        cols = tuple(r[0] for r in cur.fetchall())
    assert cols == _EXPECTED_COLUMNS, (
        f"Colonnes raw_conversations inattendues :\n"
        f"  expected: {_EXPECTED_COLUMNS}\n"
        f"  got:      {cols}"
    )


def test_raw_conversations_indexes_present(admin_conn):
    """4 index attendus : pkey + idx_raw_conv_status/expires/node."""
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT indexname FROM pg_indexes
            WHERE schemaname = 'arac'
              AND tablename = 'raw_conversations'
            ORDER BY indexname
            """
        )
        names = {r[0] for r in cur.fetchall()}
    expected = {
        "raw_conversations_pkey",
        "raw_conversations_content_hash_key",  # UNIQUE genere par contrainte
        "idx_raw_conv_status",
        "idx_raw_conv_expires",
        "idx_raw_conv_node",
    }
    missing = expected - names
    assert not missing, f"Index manquants : {missing} (presents : {names})"


def test_fk_node_id_present(admin_conn):
    """FK raw_conversations.node_id -> arac.nodes(node_id) presente."""
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT conname, confdeltype
            FROM pg_constraint
            WHERE conrelid = 'arac.raw_conversations'::regclass
              AND contype = 'f'
            """
        )
        rows = cur.fetchall()
    # confdeltype : 'r' = RESTRICT (cf doc PG pg_constraint).
    fk_names = {r[0] for r in rows}
    assert "raw_conversations_node_id_fkey" in fk_names, (
        f"FK node_id absente. Trouvees : {fk_names}"
    )
    # Verifie ON DELETE RESTRICT
    for name, deltype in rows:
        if name == "raw_conversations_node_id_fkey":
            assert deltype == "r", (
                f"FK node_id doit etre ON DELETE RESTRICT (r), trouve {deltype}"
            )


def test_fk_rejects_unknown_node_id(admin_conn):
    """INSERT avec node_id inexistant -> ForeignKeyViolation (23503)."""
    test_hash = f"{_TEST_HASH_PREFIX}fk-reject-{uuid.uuid4().hex[:8]}"
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with admin_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO arac.raw_conversations
                    (node_id, source_path, content_gz, content_size,
                     content_hash, message_count)
                VALUES
                    ('node-does-not-exist', '/test/x.jsonl',
                     '\\xdeadbeef'::bytea, 4, %s, 0)
                """,
                (test_hash,),
            )


def test_fk_accepts_local_mac_ingest_node(admin_conn):
    """INSERT avec node_id='poste-ingest' OK (seede par migration)."""
    test_hash = f"{_TEST_HASH_PREFIX}fk-accept-{uuid.uuid4().hex[:8]}"
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO arac.raw_conversations
                (node_id, source_path, content_gz, content_size,
                 content_hash, message_count)
            VALUES
                (%s, '/test/x.jsonl', '\\xdeadbeef'::bytea, 4, %s, 0)
            RETURNING id
            """,
            (_INGEST_NODE_ID, test_hash),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] is not None  # uuid genere


def test_status_check_rejects_invalid(admin_conn):
    """CHECK status : INSERT avec statut hors enum rejete."""
    test_hash = f"{_TEST_HASH_PREFIX}status-bad-{uuid.uuid4().hex[:8]}"
    with pytest.raises(psycopg.errors.CheckViolation):
        with admin_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO arac.raw_conversations
                    (node_id, source_path, content_gz, content_size,
                     content_hash, message_count, status)
                VALUES
                    (%s, '/test/x.jsonl', '\\xdeadbeef'::bytea, 4, %s, 0,
                     'invalid_status_xyz')
                """,
                (_INGEST_NODE_ID, test_hash),
            )


def test_status_check_accepts_all_valid_values(admin_conn):
    """CHECK status : les 5 valeurs autorisees passent toutes."""
    for status in _VALID_STATUSES:
        test_hash = (
            f"{_TEST_HASH_PREFIX}status-{status}-{uuid.uuid4().hex[:8]}"
        )
        with admin_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO arac.raw_conversations
                    (node_id, source_path, content_gz, content_size,
                     content_hash, message_count, status)
                VALUES
                    (%s, '/test/x.jsonl', '\\xdeadbeef'::bytea, 4, %s, 0,
                     %s)
                """,
                (_INGEST_NODE_ID, test_hash, status),
            )


def test_content_hash_unique_idempotence(admin_conn):
    """UNIQUE content_hash : 2eme INSERT avec meme hash -> UniqueViolation."""
    test_hash = f"{_TEST_HASH_PREFIX}unique-{uuid.uuid4().hex[:8]}"
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO arac.raw_conversations
                (node_id, source_path, content_gz, content_size,
                 content_hash, message_count)
            VALUES
                (%s, '/test/x.jsonl', '\\xdeadbeef'::bytea, 4, %s, 0)
            """,
            (_INGEST_NODE_ID, test_hash),
        )
    with pytest.raises(psycopg.errors.UniqueViolation):
        with admin_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO arac.raw_conversations
                    (node_id, source_path, content_gz, content_size,
                     content_hash, message_count)
                VALUES
                    (%s, '/test/y.jsonl', '\\xdeadbeef'::bytea, 4, %s, 1)
                """,
                (_INGEST_NODE_ID, test_hash),
            )


def test_local_mac_ingest_node_present_with_thresholds(admin_conn):
    """Node 'poste-ingest' seede par migration avec seuils Q4."""
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT owner, account, role,
                   silent_warn_minutes, silent_critical_minutes, active
            FROM arac.nodes
            WHERE node_id = %s
            """,
            (_INGEST_NODE_ID,),
        )
        row = cur.fetchone()
    assert row is not None, (
        f"Node {_INGEST_NODE_ID} doit etre seede par migration 0008."
    )
    owner, account, role, warn, critical, active = row
    assert owner == "alice", f"owner: {owner}"
    assert account == "human", f"account: {account}"
    assert role == "service", f"role: {role}"
    assert warn == 300, f"silent_warn_minutes Q4: attendu 300, got {warn}"
    assert critical == 600, (
        f"silent_critical_minutes Q4: attendu 600, got {critical}"
    )
    assert active is True


def test_notify_function_exists(admin_conn):
    """Fonction arac.notify_conversation_ingested presente (plpgsql)."""
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT routine_name, routine_type, external_language
            FROM information_schema.routines
            WHERE routine_schema = 'arac'
              AND routine_name = 'notify_conversation_ingested'
            """
        )
        row = cur.fetchone()
    assert row is not None, "Fonction notify_conversation_ingested absente."
    name, kind, lang = row
    assert kind == "FUNCTION"
    # PG retourne 'PLPGSQL' en majuscules dans information_schema.
    assert lang and lang.upper() == "PLPGSQL", f"langage: {lang}"


def test_notify_trigger_present_after_insert(admin_conn):
    """Trigger trg_raw_conv_notify present, AFTER INSERT, FOR EACH ROW."""
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT trigger_name, event_manipulation,
                   action_timing, action_orientation
            FROM information_schema.triggers
            WHERE event_object_schema = 'arac'
              AND event_object_table = 'raw_conversations'
            """
        )
        rows = cur.fetchall()
    assert rows, "Aucun trigger trouve sur arac.raw_conversations."
    found = False
    for name, event, timing, orient in rows:
        if name == "trg_raw_conv_notify":
            assert event == "INSERT", f"event: {event}"
            assert timing == "AFTER", f"timing: {timing}"
            assert orient == "ROW", f"orient: {orient}"
            found = True
    assert found, (
        f"Trigger trg_raw_conv_notify absent. Triggers : {rows}"
    )


# ============================================================================
# TEST LIVE TRIGGER NOTIFY (psycopg async LISTEN/NOTIFY)
# ============================================================================


@pytest_asyncio.fixture
async def admin_async_conn() -> AsyncIterator[psycopg.AsyncConnection]:
    dsn = _admin_dsn()
    conn = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
    try:
        yield conn
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_trigger_notify_fires_with_correct_payload():
    """INSERT raw_conversations declenche NOTIFY conversation_ingested.

    Payload JSON contient raw_id (UUID inserted), message_count, node_id.
    Timeout 5s. Cleanup la row test via finally.
    """
    dsn = _admin_dsn()

    listener_conn = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
    writer_conn = await psycopg.AsyncConnection.connect(dsn, autocommit=True)

    test_hash = f"{_TEST_HASH_PREFIX}notify-{uuid.uuid4().hex[:8]}"

    try:
        await listener_conn.execute(f"LISTEN {_NOTIFY_CHANNEL}")

        received = []

        async def collect():
            async for n in listener_conn.notifies():
                received.append(n)
                return

        task = asyncio.create_task(collect())

        # Petit delay pour s'assurer LISTEN actif
        await asyncio.sleep(0.3)

        async with writer_conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO arac.raw_conversations
                    (node_id, source_path, content_gz, content_size,
                     content_hash, message_count)
                VALUES
                    (%s, '/test/notify.jsonl', '\\xdeadbeef'::bytea, 4,
                     %s, 7)
                RETURNING id::text
                """,
                (_INGEST_NODE_ID, test_hash),
            )
            inserted_id = (await cur.fetchone())[0]

        await asyncio.wait_for(task, timeout=5.0)

        assert received, "Aucun NOTIFY recu en 5s."
        n = received[0]
        assert n.channel == _NOTIFY_CHANNEL
        payload = json.loads(n.payload)
        assert payload["raw_id"] == inserted_id
        assert payload["message_count"] == 7
        assert payload["node_id"] == _INGEST_NODE_ID

    finally:
        # Cleanup
        async with writer_conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM arac.raw_conversations "
                "WHERE content_hash = %s",
                (test_hash,),
            )
        await listener_conn.close()
        await writer_conn.close()


# ============================================================================
# TESTS IDEMPOTENCE UP / DOWN REPLAY
# (NB : skip par defaut — mutating BDD live, pattern test_migration_0007.)
# ============================================================================


@pytest.mark.skip(
    reason=(
        "Test mutating BDD live (down/up). A executer manuellement en dev "
        "avec backup pg_dump restorable. Cf pattern test_migration_0007."
    )
)
def test_down_then_up_idempotent(admin_conn):
    """Migration 0008 down + up = etat initial preserve (placeholder skip)."""
    with admin_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM arac.raw_conversations")
        count_before = cur.fetchone()[0]
    assert count_before >= 0  # placeholder
