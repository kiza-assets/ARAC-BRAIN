"""Tests migration 0014_code_brain — unitaires sans DB (shape uniquement)."""
import importlib.util
import os

_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "alembic", "versions",
                     "0014_code_brain.py")
_spec = importlib.util.spec_from_file_location("migration_0014", _PATH)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

_TABLES = ("code_repo", "code_file", "code_symbol", "code_route", "code_test",
           "code_edge", "code_atom_link")


def _collect(fn):
    executed = []
    orig = m.op.execute
    try:
        m.op.execute = executed.append
        fn()
    finally:
        m.op.execute = orig
    return "\n".join(executed)


def test_revision_chained_on_0013():
    assert m.revision == "0014_code_brain"
    assert len(m.revision) <= 32
    assert m.down_revision == "0013_business_memory"


def test_upgrade_creates_all_code_tables():
    up = _collect(m.upgrade)
    for tbl in _TABLES:
        assert f"CREATE TABLE IF NOT EXISTS arac.{tbl}" in up
    # incrémentalité : sha256 + last_commit + head_commit présents
    assert "sha256" in up and "last_commit" in up and "head_commit" in up
    # ne touche AUCUNE table existante (sauf FK référence à memory_atoms, pas ALTER)
    for forbidden in ("DROP TABLE", "ALTER TABLE arac.memory_atoms",
                      "ALTER TABLE arac.raw_conversations", "DELETE FROM", "TRUNCATE"):
        assert forbidden not in up


def test_downgrade_drops_all_code_tables_only():
    down = _collect(m.downgrade)
    for tbl in _TABLES:
        assert f"DROP TABLE IF EXISTS arac.{tbl} CASCADE" in down
    # ne supprime QUE des tables code_* (jamais memory_atoms / raw_conversations)
    assert "memory_atoms" not in down
    assert "raw_conversations" not in down


def test_atom_link_references_memory_atoms():
    up = _collect(m.upgrade)
    # le lien optionnel code<->métier référence bien arac.memory_atoms(id)
    assert "atom_id   UUID NOT NULL REFERENCES arac.memory_atoms(id)" in up
