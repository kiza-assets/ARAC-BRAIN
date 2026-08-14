"""Tests migration 0011_imported_conversation_kind (V1.6B) — unitaires sans DB.

Les vérifications d'état live (constraint en BDD) se font en Phase 8 post-validation ;
ici on borne le MODULE de migration : chaînage, ajout d'UNE seule valeur, préservation
exacte des 19 kinds existants, symétrie upgrade/downgrade.
"""
import importlib.util
import os

_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "alembic", "versions",
                     "0011_imported_conversation_kind.py")
_spec = importlib.util.spec_from_file_location("migration_0011", _PATH)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

_EXISTING_19 = (
    "decision", "pattern", "gotcha", "state", "todo", "killed", "note", "idea",
    "insight", "question", "reference", "alert", "validation", "contradiction",
    "suggestion", "agent_message", "mission_proposal", "mission", "delivery",
)


def test_revision_chained_on_0010():
    assert m.revision == "0011_imported_conversation_kind"
    assert len(m.revision) <= 32                      # limite alembic_version
    assert m.down_revision == "0010_incoming_proposal_queue"


def test_exactly_one_kind_added():
    added = set(m._KIND_VALUES_V11) - set(_EXISTING_19)
    assert added == {"imported_conversation_summary"}
    assert len(m._KIND_VALUES_V11) == 20


def test_all_existing_kinds_preserved_in_order():
    assert m._KIND_VALUES_V11[:19] == _EXISTING_19    # aucun kind modifié/réordonné
    assert "conversation" not in m._KIND_VALUES_V11   # kind écarté par décision Option C


def test_upgrade_downgrade_symmetry(monkeypatch):
    executed = []
    monkeypatch.setattr(m.op, "execute", executed.append, raising=False)
    m.upgrade()
    up_sql = "\n".join(executed)
    executed.clear()
    m.downgrade()
    down_sql = "\n".join(executed)
    assert "imported_conversation_summary" in up_sql
    assert "imported_conversation_summary" not in down_sql
    for k in _EXISTING_19:                            # les 19 présents des deux côtés
        assert f"'{k}'::text" in up_sql and f"'{k}'::text" in down_sql
    for sql in (up_sql, down_sql):                    # DDL borné au seul CHECK kind
        assert "memory_atoms_kind_check" in sql
        assert "UPDATE" not in sql and "DELETE" not in sql and "INSERT" not in sql
        assert "DROP TABLE" not in sql and "GRANT" not in sql and "REVOKE" not in sql
