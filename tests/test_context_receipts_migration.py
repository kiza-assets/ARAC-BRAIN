"""Tests migration 0030 `arac.context_receipts` (shadow Context
Engine) — même convention que `tests/test_d063_migrations.py` :

  1. chaînage `down_revision` (0029 -> 0030, linéaire, pas de fork) ;
  2. forme (colonnes/CHECK/index/COMMENT — dont le contrat ZÉRO PII) ;
  3. append-only par grants (GRANT INSERT à arac_app + REVOKE UPDATE/DELETE
     défensifs, arac_agent lecture seule, séquence via bloc DO $$) ;
  4. idempotence textuelle (IF NOT EXISTS partout, downgrade IF EXISTS) ;
  5. symétrie upgrade/downgrade (DROP TABLE CASCADE, rien d'autre).

Les vérifications LIVE (upgrade/downgrade réels, grants effectifs,
append-only prouvé par un DELETE refusé) suivent le pattern `db_admin`/
`db_session` de conftest.py : elles SKIPPENT proprement si
`DATABASE_URL_ADMIN_TEST`/`DATABASE_URL_APP_TEST` sont absentes, et
supposent `alembic upgrade head` déjà appliqué sur la DB de test (même
doctrine que les `test_live_*` de test_d063_migrations.py).
"""

from __future__ import annotations

import importlib.util
import os
import re

import pytest

_VERSIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "db", "alembic", "versions")
_NAME = "0030_context_receipts"


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
    assert _M.revision == "0030_context_receipts"
    assert _M.down_revision == "0029_d063_exclusion_motive_audit"


def test_revision_fits_alembic_version_varchar32():
    assert len(_M.revision) <= 32


# ============================================================================
# 2. Forme
# ============================================================================

def test_table_and_columns_shape():
    assert "CREATE TABLE IF NOT EXISTS arac.context_receipts" in _UP
    for col in (
        "request_id", "consumer", "engine_version", "calibration_version",
        "query_sha256", "scope_filter", "kind_filter", "k_requested",
        "budget_k", "served_ids", "shadow_ids", "shadow_distances",
        "top1_distance_raw", "top1_distance_final", "raw_band", "final_band",
        "stop_reason", "scope_prefix_gain", "shadow_latency_ms",
        "shadow_error", "created_at",
    ):
        assert col in _UP, f"colonne absente : {col}"
    # ids servis/shadow = uuid[], distances alignées = real[]
    assert re.search(r"served_ids\s+uuid\[\] NOT NULL", _UP)
    assert re.search(r"shadow_ids\s+uuid\[\] NOT NULL", _UP)
    assert re.search(r"shadow_distances\s+real\[\] NOT NULL", _UP)


def test_checks_shape():
    # sha256 hex strict : le seul reflet de la requête, jamais son texte
    assert "CHECK (query_sha256 ~ '^[0-9a-f]{64}$')" in _UP
    assert "CHECK (k_requested BETWEEN 1 AND 100)" in _UP
    assert "CHECK (budget_k >= 1)" in _UP
    assert "CHECK (scope_prefix_gain >= 0)" in _UP
    for band_col in ("raw_band", "final_band"):
        assert f"CHECK ({band_col} IN ('high', 'medium', 'low', 'none'))" in _UP
    for reason in (
        "budget", "exhausted", "no_confident_context",
        "no_embedding", "corpus_exhausted",
    ):
        assert f"'{reason}'" in _UP


def test_no_pii_no_query_text_columns():
    """Contrat ZÉRO PII : aucune colonne de texte de requête ni de contenu
    d'atome — le hash est la seule trace de la query."""
    for forbidden in ("query_text", "query text", "atom_value", "atom_key"):
        assert forbidden not in _UP
    # le contrat est consigné en COMMENT au plus près de la donnée
    assert "COMMENT ON TABLE arac.context_receipts" in _UP
    assert "JAMAIS le texte" in _UP


def test_indexes_shape():
    for idx in (
        "idx_context_receipts_created",
        "idx_context_receipts_consumer",
        "idx_context_receipts_band",
    ):
        assert f"CREATE INDEX IF NOT EXISTS {idx}" in _UP


# ============================================================================
# 3. Append-only par grants (mirror 0021)
# ============================================================================

def test_grants_append_only():
    assert "GRANT SELECT, INSERT ON arac.context_receipts TO arac_app;" in _UP
    assert "GRANT SELECT ON arac.context_receipts TO arac_agent;" in _UP
    assert "GRANT SELECT ON arac.context_receipts TO arac_readonly;" in _UP
    assert "REVOKE UPDATE, DELETE ON arac.context_receipts FROM arac_app;" in _UP
    assert "REVOKE INSERT, UPDATE, DELETE ON arac.context_receipts FROM arac_agent;" in _UP
    # jamais de GRANT UPDATE/DELETE à qui que ce soit
    assert "GRANT UPDATE" not in _UP
    assert "GRANT DELETE" not in _UP


def test_sequence_grant_block_present():
    assert "pg_get_serial_sequence('arac.context_receipts', 'id')" in _UP
    assert "GRANT USAGE, SELECT ON SEQUENCE %s TO arac_app" in _UP
    assert "REVOKE USAGE ON SEQUENCE %s FROM arac_agent" in _UP


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
    assert _DOWN.strip() == "DROP TABLE IF EXISTS arac.context_receipts CASCADE"


def test_downgrade_uses_if_exists_forms():
    for drop_stmt in re.findall(r"DROP (?:TABLE|INDEX|TRIGGER|FUNCTION|COLUMN)\b[^\n;]*", _DOWN):
        assert "IF EXISTS" in drop_stmt, f"DROP sans IF EXISTS : {drop_stmt!r}"


def test_docstring_documents_prod_head_gap():
    """La docstring doit noter que la prod est au head 0019 et que 0030
    s'empile sur la lignée 0020→0029 NON appliquée (déploiement = GO humain,
    hors périmètre shadow) — piège n°9 de."""
    doc = _M.__doc__ or ""
    assert "0019" in doc
    assert "GO humain" in doc


# ============================================================================
# LIVE (DB de test 5433 uniquement — skip proprement sinon)
# ============================================================================

async def test_live_context_receipts_table_exists(db_admin):
    async with db_admin.cursor() as cur:
        await cur.execute(
            "SELECT count(*) FROM pg_tables "
            "WHERE schemaname = 'arac' AND tablename = 'context_receipts'"
        )
        (n,) = await cur.fetchone()
    assert n == 1


async def test_live_grants_effective_append_only(db_admin):
    """Grants effectifs : arac_app = SELECT+INSERT seulement ; arac_agent et
    arac_readonly = SELECT seulement."""
    async with db_admin.cursor() as cur:
        await cur.execute(
            "SELECT grantee, privilege_type FROM information_schema.role_table_grants "
            "WHERE table_schema = 'arac' AND table_name = 'context_receipts' "
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
    """Preuve append-only vécue : `arac_app` INSERT une row de reçu (forme
    minimale valide) puis se voit REFUSER UPDATE et DELETE dessus."""
    sha = "0" * 64
    async with db_session.cursor() as cur:
        await cur.execute(
            "INSERT INTO arac.context_receipts "
            "(consumer, engine_version, calibration_version, query_sha256, "
            " k_requested, budget_k, served_ids, shadow_ids, shadow_distances, "
            " stop_reason, shadow_latency_ms) "
            "VALUES ('unknown', 'ce-shadow-r3pur-v1', 'r3-calib-v1-20260708', %s, "
            " 10, 10, '{}', '{}', '{}', 'no_confident_context', 1.5) "
            "RETURNING id",
            (sha,),
        )
        (row_id,) = await cur.fetchone()
    try:
        import psycopg

        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            async with db_session.cursor() as cur:
                await cur.execute(
                    "UPDATE arac.context_receipts SET consumer = 'x' WHERE id = %s",
                    (row_id,),
                )
        await db_session.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            async with db_session.cursor() as cur:
                await cur.execute(
                    "DELETE FROM arac.context_receipts WHERE id = %s", (row_id,)
                )
        await db_session.rollback()
    finally:
        # cleanup via admin (seul rôle autorisé à effacer — c'est le point)
        async with db_admin.cursor() as cur:
            await cur.execute(
                "DELETE FROM arac.context_receipts WHERE id = %s", (row_id,)
            )


async def test_live_check_constraints_enforced(db_admin):
    """Les CHECK vivent : sha non-hex refusé, stop_reason inconnu refusé."""
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        async with db_admin.cursor() as cur:
            await cur.execute(
                "INSERT INTO arac.context_receipts "
                "(engine_version, calibration_version, query_sha256, k_requested, "
                " budget_k, served_ids, shadow_ids, shadow_distances, stop_reason, "
                " shadow_latency_ms) "
                "VALUES ('v', 'v', 'PAS-UN-SHA', 10, 10, '{}', '{}', '{}', "
                " 'budget', 1.0)"
            )
    # db_admin est autocommit : le statement refusé ne poisonne pas la connexion.
    with pytest.raises(psycopg.errors.CheckViolation):
        async with db_admin.cursor() as cur:
            await cur.execute(
                "INSERT INTO arac.context_receipts "
                "(engine_version, calibration_version, query_sha256, k_requested, "
                " budget_k, served_ids, shadow_ids, shadow_distances, stop_reason, "
                " shadow_latency_ms) "
                "VALUES ('v', 'v', %s, 10, 10, '{}', '{}', '{}', "
                " 'raison_inconnue', 1.0)",
                ("0" * 64,),
            )
