"""Tests migration 0031 `arac.memory_atom_reprs` (FOLD V2) — même
convention que `tests/test_context_receipts_migration.py` :

  1. chaînage `down_revision` (0030 -> 0031, linéaire, pas de fork) ;
  2. forme (colonnes/PK composite/FK CASCADE/index HNSW partiel/COMMENT —
     dont le contrat ZÉRO texte de span / ZÉRO PII) ;
  3. append-only par grants (GRANT SELECT,INSERT à arac_app + REVOKE
     UPDATE/DELETE défensifs, arac_agent/arac_readonly lecture seule,
     AUCUNE séquence — PK composite) ;
  4. idempotence textuelle (IF NOT EXISTS partout, downgrade IF EXISTS) ;
  5. symétrie upgrade/downgrade (DROP TABLE CASCADE, rien d'autre).

Les vérifications LIVE (table réelle, grants effectifs, append-only prouvé
par UPDATE/DELETE refusés, FK CASCADE, unicité (atom_id, repr_version))
suivent le pattern `db_admin`/`db_session` de conftest.py : elles SKIPPENT
proprement si `DATABASE_URL_ADMIN_TEST`/`DATABASE_URL_APP_TEST` sont
absentes, et supposent `alembic upgrade head` déjà appliqué sur la DB de
test (port 5433).
"""

from __future__ import annotations

import importlib.util
import os
import re
import uuid

import pytest

_VERSIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "db", "alembic", "versions")
_NAME = "0031_memory_atom_reprs"


def _load(name: str):
    path = os.path.join(_VERSIONS_DIR, f"{name}.py")
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _collect(m, fn) -> str:
    executed = []
    orig = m.op.execute
    try:
        m.op.execute = executed.append
        fn()
    finally:
        m.op.execute = orig
    return "\n".join(executed)


_M = _load(_NAME)
_UP = _collect(_M, _M.upgrade)
_DOWN = _collect(_M, _M.downgrade)


# ============================================================================
# 1. Chaîne
# ============================================================================

def test_chain_down_revision():
    assert _M.revision == "0031_memory_atom_reprs"
    assert _M.down_revision == "0030_context_receipts"


def test_revision_fits_alembic_version_varchar32():
    assert len(_M.revision) <= 32


# ============================================================================
# 2. Forme
# ============================================================================

def test_table_and_columns_shape():
    assert "CREATE TABLE IF NOT EXISTS arac.memory_atom_reprs" in _UP
    for col in (
        "atom_id", "repr_version", "embedding", "manifest_sha",
        "doc_sha256", "build", "created_at",
    ):
        assert col in _UP, f"colonne absente : {col}"
    assert re.search(r"embedding\s+halfvec\(3072\) NOT NULL", _UP)
    assert re.search(r"manifest_sha\s+text NOT NULL", _UP)
    assert re.search(r"build\s+jsonb", _UP)
    assert re.search(r"created_at\s+timestamptz NOT NULL DEFAULT now\(\)", _UP)


def test_pk_composite_and_fk_cascade():
    assert "PRIMARY KEY (atom_id, repr_version)" in _UP
    assert "REFERENCES arac.memory_atoms(id) ON DELETE CASCADE" in _UP


def test_hnsw_index_shape():
    """Index HNSW modèle ix_memory_atoms_embedding (m=16, ef_construction=64,
    paramètres HNSW épinglés), partiel sur la seule version observée
    rm1-fold-a50."""
    assert "CREATE INDEX IF NOT EXISTS ix_memory_atom_reprs_embedding" in _UP
    assert "USING hnsw (embedding halfvec_cosine_ops)" in _UP
    assert "WITH (m = 16, ef_construction = 64)" in _UP
    assert "WHERE repr_version = 'rm1-fold-a50'" in _UP


def test_no_span_text_no_pii_contract():
    """Contrat ZÉRO texte de span / ZÉRO PII : aucune colonne de texte de doc
    ou de message — doc_sha256 est une empreinte seulement, consigné en
    COMMENT au plus près de la donnée."""
    for forbidden in ("doc_text", "span_text", "message_text", "user_text"):
        assert forbidden not in _UP
    assert "COMMENT ON TABLE arac.memory_atom_reprs" in _UP
    assert "ZERO texte de span" in _UP
    assert "COMMENT ON COLUMN arac.memory_atom_reprs.doc_sha256" in _UP
    assert "JAMAIS le texte" in _UP


def test_comments_on_key_columns():
    for col in ("embedding", "manifest_sha", "doc_sha256", "build"):
        assert f"COMMENT ON COLUMN arac.memory_atom_reprs.{col}" in _UP, (
            f"COMMENT absent : {col}"
        )


# ============================================================================
# 3. Append-only par grants (spec §3.4, mirror 0021/0030)
# ============================================================================

def test_grants_append_only():
    assert "GRANT SELECT, INSERT ON arac.memory_atom_reprs TO arac_app;" in _UP
    assert "GRANT SELECT ON arac.memory_atom_reprs TO arac_agent;" in _UP
    assert "GRANT SELECT ON arac.memory_atom_reprs TO arac_readonly;" in _UP
    assert "REVOKE UPDATE, DELETE ON arac.memory_atom_reprs FROM arac_app;" in _UP
    assert "REVOKE INSERT, UPDATE, DELETE ON arac.memory_atom_reprs FROM arac_agent;" in _UP
    # jamais de GRANT UPDATE/DELETE à qui que ce soit
    assert "GRANT UPDATE" not in _UP
    assert "GRANT DELETE" not in _UP


def test_no_sequence_grant_needed():
    """PK composite (atom_id, repr_version), pas d'IDENTITY — aucune séquence
    à granter (contrairement à 0030)."""
    assert "SEQUENCE" not in _UP
    assert "pg_get_serial_sequence" not in _UP


# ============================================================================
# 4. Idempotence textuelle + 5. symétrie downgrade
# ============================================================================

def test_upgrade_is_replay_safe_textually():
    assert "CREATE TABLE IF NOT EXISTS" in _UP
    assert "CREATE INDEX IF NOT EXISTS" in _UP
    # aucune donnée existante touchée
    for forbidden in ("DROP TABLE", "DELETE FROM", "TRUNCATE", "UPDATE "):
        assert forbidden not in _UP


def test_downgrade_drops_only_the_table():
    assert _DOWN.strip() == "DROP TABLE IF EXISTS arac.memory_atom_reprs CASCADE"


def test_downgrade_uses_if_exists_forms():
    for drop_stmt in re.findall(r"DROP (?:TABLE|INDEX|TRIGGER|FUNCTION|COLUMN)\b[^\n;]*", _DOWN):
        assert "IF EXISTS" in drop_stmt, f"DROP sans IF EXISTS : {drop_stmt!r}"


def test_docstring_documents_go_gate_and_no_serve():
    """La docstring doit consigner : déploiement = GO humain (prospectif),
    aucun flag serve-v2 dans ce chantier, jamais de trigger/NOTIFY.

    Le « jamais de trigger/NOTIFY » n'est pas un détail de style : depuis
    l'ingestion V2, RIEN ne réveille rien en base. Un trigger qui notifierait
    ferait repartir une boucle d'agents que le système a délibérément arrêtée.
    """
    doc = _M.__doc__ or ""
    assert "GO humain" in doc
    assert "serve-v2" in doc
    assert "NOTIFY" in doc


# ============================================================================
# LIVE (DB de test 5433 uniquement — skip proprement sinon)
# ============================================================================

_TEST_KEY_PREFIX = "test-reprs-mig"


async def _seed_atom(db_admin) -> str:
    """Crée un atome minimal valide (kind/status/key conformes aux CHECK,
    node seedé pour la FK node_id) et retourne son id. Cleanup par le caller
    (DELETE admin — cascade attendue)."""
    async with db_admin.cursor() as cur:
        await cur.execute(
            "INSERT INTO arac.nodes (node_id, account, owner, role) "
            "VALUES ('test-node', 'system', 'system', 'service') "
            "ON CONFLICT (node_id) DO NOTHING"
        )
        await cur.execute(
            "INSERT INTO arac.memory_atoms (kind, scope, key, value, node_id) "
            "VALUES ('note', 'arac', %s, 'test atom for 0031 live checks', "
            "'test-node') RETURNING id",
            (f"{_TEST_KEY_PREFIX}-{uuid.uuid4().hex[:8]}",),
        )
        (atom_id,) = await cur.fetchone()
    return atom_id


def _vec3072() -> str:
    return "[" + ",".join(["0.01"] * 3072) + "]"


async def test_live_memory_atom_reprs_table_exists(db_admin):
    async with db_admin.cursor() as cur:
        await cur.execute(
            "SELECT count(*) FROM pg_tables "
            "WHERE schemaname = 'arac' AND tablename = 'memory_atom_reprs'"
        )
        (n,) = await cur.fetchone()
    assert n == 1


async def test_live_hnsw_partial_index_exists(db_admin):
    async with db_admin.cursor() as cur:
        await cur.execute(
            "SELECT indexdef FROM pg_indexes WHERE schemaname = 'arac' "
            "AND indexname = 'ix_memory_atom_reprs_embedding'"
        )
        row = await cur.fetchone()
    assert row is not None, "index HNSW absent"
    indexdef = row[0]
    assert "hnsw" in indexdef
    assert "halfvec_cosine_ops" in indexdef
    assert "m='16'" in indexdef and "ef_construction='64'" in indexdef
    assert "rm1-fold-a50" in indexdef  # partiel sur la version observée


async def test_live_grants_effective_append_only(db_admin):
    """Grants effectifs : arac_app = SELECT+INSERT seulement ; arac_agent et
    arac_readonly = SELECT seulement."""
    async with db_admin.cursor() as cur:
        await cur.execute(
            "SELECT grantee, privilege_type FROM information_schema.role_table_grants "
            "WHERE table_schema = 'arac' AND table_name = 'memory_atom_reprs' "
            "AND grantee IN ('arac_app', 'arac_agent', 'arac_readonly')"
        )
        rows = await cur.fetchall()
    privs: dict[str, set[str]] = {}
    for grantee, priv in rows:
        privs.setdefault(grantee, set()).add(priv)
    assert privs.get("arac_app") == {"SELECT", "INSERT"}
    assert privs.get("arac_agent") == {"SELECT"}
    assert privs.get("arac_readonly") == {"SELECT"}


async def test_live_insert_then_update_delete_refused_for_app(db_session, db_admin):
    """Preuve append-only vécue : `arac_app` INSERT une repr (forme minimale
    valide) puis se voit REFUSER UPDATE et DELETE dessus."""
    import psycopg

    atom_id = await _seed_atom(db_admin)
    try:
        async with db_session.cursor() as cur:
            await cur.execute(
                "INSERT INTO arac.memory_atom_reprs "
                "(atom_id, repr_version, embedding, manifest_sha, doc_sha256, build) "
                "VALUES (%s, 'rm1-fold-a50', %s::halfvec, %s, %s, "
                "'{\"user_spans\": 0, \"fallback\": \"t_meta_only\"}'::jsonb)",
                (atom_id, _vec3072(), "a" * 64, "b" * 64),
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            async with db_session.cursor() as cur:
                await cur.execute(
                    "UPDATE arac.memory_atom_reprs SET manifest_sha = 'x' "
                    "WHERE atom_id = %s",
                    (atom_id,),
                )
        await db_session.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            async with db_session.cursor() as cur:
                await cur.execute(
                    "DELETE FROM arac.memory_atom_reprs WHERE atom_id = %s",
                    (atom_id,),
                )
        await db_session.rollback()
    finally:
        # cleanup via admin — le DELETE de l'atome doit CASCADEr sur la repr
        async with db_admin.cursor() as cur:
            await cur.execute(
                "DELETE FROM arac.memory_atoms WHERE id = %s", (atom_id,)
            )


async def test_live_pk_conflict_and_fk_cascade(db_admin):
    """Unicité (atom_id, repr_version) : le 2e INSERT identique lève
    UniqueViolation (le backfill utilisera ON CONFLICT DO NOTHING dessus) ;
    et DELETE de l'atome CASCADE la repr (purge admin sans orphelin)."""
    import psycopg

    atom_id = await _seed_atom(db_admin)
    insert_sql = (
        "INSERT INTO arac.memory_atom_reprs "
        "(atom_id, repr_version, embedding, manifest_sha) "
        "VALUES (%s, 'rm1-fold-a50', %s::halfvec, %s)"
    )
    try:
        async with db_admin.cursor() as cur:
            await cur.execute(insert_sql, (atom_id, _vec3072(), "c" * 64))
        with pytest.raises(psycopg.errors.UniqueViolation):
            async with db_admin.cursor() as cur:
                await cur.execute(insert_sql, (atom_id, _vec3072(), "c" * 64))
        # idempotence backfill : ON CONFLICT DO NOTHING = 0 row, pas d'erreur
        async with db_admin.cursor() as cur:
            await cur.execute(
                insert_sql + " ON CONFLICT (atom_id, repr_version) DO NOTHING",
                (atom_id, _vec3072(), "c" * 64),
            )
            assert cur.rowcount == 0
    finally:
        async with db_admin.cursor() as cur:
            await cur.execute(
                "DELETE FROM arac.memory_atoms WHERE id = %s", (atom_id,)
            )
    # cascade prouvée : plus aucune repr pour cet atome
    async with db_admin.cursor() as cur:
        await cur.execute(
            "SELECT count(*) FROM arac.memory_atom_reprs WHERE atom_id = %s",
            (atom_id,),
        )
        (n,) = await cur.fetchone()
    assert n == 0
