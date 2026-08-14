"""Tests migration 0013_business_memory (cerveau métier) — unitaires sans DB.

Borne le MODULE : chaînage sur 0012, slug <= 32, upgrade additif (6 colonnes
IF NOT EXISTS + 3 index + élargissement du CHECK status à 8 valeurs), downgrade
qui retire UNIQUEMENT ces objets et restaure le CHECK d'origine (5 valeurs).
Les vérifs d'état live se font en Phase 8 (Docker absent ici).
"""
import importlib.util
import os

_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "alembic", "versions",
                     "0013_business_memory.py")
_spec = importlib.util.spec_from_file_location("migration_0013", _PATH)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

_NEW_COLUMNS = ("supersedes", "dedupe_key", "semantic_hash", "observed_at",
                "last_verified_at", "confirmed_until")
_NEW_STATUSES = ("disputed", "pending_review", "blocked")
_OLD_STATUSES = ("active", "draft", "superseded", "archived", "low_confidence_archive")


def _collect(fn):
    executed = []
    orig = m.op.execute
    try:
        m.op.execute = executed.append
        fn()
    finally:
        m.op.execute = orig
    return "\n".join(executed)


def test_revision_chained_on_0012():
    assert m.revision == "0013_business_memory"
    assert len(m.revision) <= 32
    assert m.down_revision == "0012_raw_conv_retry_journal"


def test_upgrade_adds_columns_indexes_and_widens_status():
    up = _collect(m.upgrade)
    for col in _NEW_COLUMNS:
        assert f"ADD COLUMN IF NOT EXISTS {col}" in up
    for idx in ("idx_memory_atoms_dedupe_key", "idx_memory_atoms_semantic_hash",
                "idx_memory_atoms_supersedes"):
        assert f"CREATE INDEX IF NOT EXISTS {idx}" in up
    # le nouveau CHECK contient les 8 statuts (5 anciens + 3 neufs)
    for st in _OLD_STATUSES + _NEW_STATUSES:
        assert f"'{st}'" in up
    assert "ADD CONSTRAINT memory_atoms_status_check" in up


def test_upgrade_not_data_destructive():
    up = _collect(m.upgrade)
    # widening du CHECK -> DROP CONSTRAINT attendu, mais AUCUNE op sur la donnée
    for forbidden in ("DROP TABLE", "DROP COLUMN", "DELETE FROM", "TRUNCATE",
                      "ALTER COLUMN", "GRANT", "REVOKE", "UPDATE "):
        assert forbidden not in up, f"upgrade ne doit pas contenir {forbidden!r}"


def test_downgrade_drops_new_objects_and_restores_old_check():
    down = _collect(m.downgrade)
    for col in _NEW_COLUMNS:
        assert f"DROP COLUMN IF EXISTS {col}" in down
    for idx in ("idx_memory_atoms_dedupe_key", "idx_memory_atoms_semantic_hash",
                "idx_memory_atoms_supersedes"):
        assert f"DROP INDEX IF EXISTS arac.{idx}" in down
    # restaure le CHECK d'origine (5 statuts), sans les 3 neufs
    for st in _NEW_STATUSES:
        # les 3 neufs ne doivent PAS apparaître dans le CHECK restauré
        # (ils peuvent apparaître nulle part dans le downgrade)
        assert f"'{st}'" not in down, f"downgrade ne doit pas réintroduire {st!r}"
    for forbidden in ("DROP TABLE", "DELETE FROM", "TRUNCATE"):
        assert forbidden not in down
