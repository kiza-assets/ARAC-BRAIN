"""Réversibilité des migrations 0012/0013/0014 — symétrie upgrade↔downgrade.

Validation STATIQUE (sans DB, Docker absent) mais FORTE : tout objet créé par
`upgrade()` (colonne / table / index) doit être supprimé par `downgrade()`, et
réciproquement aucun objet supprimé au downgrade ne doit échapper à l'upgrade.
Attrape les régressions « ajoute mais oublie de retirer » que les tests de forme
par-migration ne croisent pas.

NB : la validation LIVE (upgrade/downgrade réels sur une DB) reste une étape
opérateur (cf brain-autopilot-final-report — `make test` sur hôte Docker).
"""

from __future__ import annotations

import importlib.util
import os
import re

import pytest

_VERSIONS = os.path.join(os.path.dirname(__file__), "..", "db", "alembic", "versions")

_MIGRATIONS = (
    "0012_raw_conv_retry_journal",
    "0013_business_memory",
    "0014_code_brain",
)


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_VERSIONS, f"{name}.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _collect(m, fn):
    executed = []
    orig = m.op.execute
    try:
        m.op.execute = executed.append
        fn()
    finally:
        m.op.execute = orig
    return "\n".join(executed)


_ADD_COL = re.compile(r"ADD COLUMN IF NOT EXISTS\s+(\w+)", re.IGNORECASE)
_DROP_COL = re.compile(r"DROP COLUMN IF EXISTS\s+(\w+)", re.IGNORECASE)
_CREATE_TBL = re.compile(r"CREATE TABLE IF NOT EXISTS\s+arac\.(\w+)", re.IGNORECASE)
_DROP_TBL = re.compile(r"DROP TABLE IF EXISTS\s+arac\.(\w+)", re.IGNORECASE)
_CREATE_IDX = re.compile(r"CREATE INDEX IF NOT EXISTS\s+(\w+)", re.IGNORECASE)
_DROP_IDX = re.compile(r"DROP INDEX IF EXISTS\s+(?:arac\.)?(\w+)", re.IGNORECASE)
# CREATE INDEX <name> ON arac.<table> — pour savoir si un index est couvert par
# un DROP TABLE (les index tombent avec leur table).
_IDX_ON_TABLE = re.compile(
    r"CREATE INDEX IF NOT EXISTS\s+(\w+)\s+ON\s+arac\.(\w+)", re.IGNORECASE)


@pytest.mark.parametrize("name", _MIGRATIONS)
def test_added_columns_are_dropped(name):
    m = _load(name)
    up, down = _collect(m, m.upgrade), _collect(m, m.downgrade)
    added = set(_ADD_COL.findall(up))
    dropped = set(_DROP_COL.findall(down))
    assert added == dropped, f"{name}: colonnes ajoutées {added} != supprimées {dropped}"


@pytest.mark.parametrize("name", _MIGRATIONS)
def test_created_tables_are_dropped(name):
    m = _load(name)
    up, down = _collect(m, m.upgrade), _collect(m, m.downgrade)
    created = set(_CREATE_TBL.findall(up))
    dropped = set(_DROP_TBL.findall(down))
    assert created == dropped, f"{name}: tables créées {created} != supprimées {dropped}"


@pytest.mark.parametrize("name", _MIGRATIONS)
def test_created_indexes_are_reversed(name):
    """Tout index créé est RÉVERSÉ : soit explicitement DROP INDEX, soit couvert
    par le DROP TABLE de sa table (les index tombent avec leur table)."""
    m = _load(name)
    up, down = _collect(m, m.upgrade), _collect(m, m.downgrade)
    created = set(_CREATE_IDX.findall(up))
    dropped_idx = set(_DROP_IDX.findall(down))
    dropped_tables = set(_DROP_TBL.findall(down))
    idx_table = {idx: tbl for idx, tbl in _IDX_ON_TABLE.findall(up)}
    for idx in created:
        covered = idx in dropped_idx or idx_table.get(idx) in dropped_tables
        assert covered, (f"{name}: index {idx} ni droppé explicitement ni couvert "
                         f"par un DROP TABLE (table={idx_table.get(idx)})")


def test_migration_chain_is_linear_0011_to_0014():
    """Chaîne 0011 -> 0012 -> 0013 -> 0014 sans trou ni fork."""
    expected_prev = {
        "0012_raw_conv_retry_journal": "0011_imported_conversation_kind",
        "0013_business_memory": "0012_raw_conv_retry_journal",
        "0014_code_brain": "0013_business_memory",
    }
    for name, prev in expected_prev.items():
        m = _load(name)
        assert m.down_revision == prev, f"{name}: down_revision {m.down_revision} != {prev}"
        assert len(m.revision) <= 32         # contrainte alembic_version varchar(32)


@pytest.mark.parametrize("name", _MIGRATIONS)
def test_upgrade_never_data_destructive(name):
    """upgrade() ne contient aucune opération destructrice de DONNÉES existantes."""
    m = _load(name)
    up = _collect(m, m.upgrade)
    for forbidden in ("DROP TABLE", "DELETE FROM", "TRUNCATE", "DROP COLUMN"):
        assert forbidden not in up, f"{name}: upgrade contient {forbidden!r}"
