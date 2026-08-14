"""Tests migration 0012_raw_conv_retry_journal (F2) — unitaires sans DB.

Borne le MODULE : chaînage sur 0011, slug <= 32, upgrade STRICTEMENT additif
(ADD COLUMN IF NOT EXISTS + CREATE INDEX + un seed UPDATE qui n'écrit QUE la
colonne neuve `acked`), downgrade qui ne supprime QUE les 5 colonnes + l'index.
Les vérifs d'état live (colonnes réellement en base) se font en Phase 8.
"""
import importlib.util
import os

_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "alembic", "versions",
                     "0012_raw_conv_retry_journal.py")
_spec = importlib.util.spec_from_file_location("migration_0012", _PATH)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

_NEW_COLUMNS = ("retry_count", "last_error", "acked", "next_retry_at", "processing_started_at")


def _collect(fn):
    executed = []
    orig = m.op.execute
    try:
        m.op.execute = executed.append
        fn()
    finally:
        m.op.execute = orig
    return "\n".join(executed)


def test_revision_chained_on_0011():
    assert m.revision == "0012_raw_conv_retry_journal"
    assert len(m.revision) <= 32                       # limite alembic_version
    assert m.down_revision == "0011_imported_conversation_kind"


def test_upgrade_is_additive_only():
    up = _collect(m.upgrade)
    # 5 colonnes ajoutées, toutes IF NOT EXISTS (idempotent / non destructif)
    for col in _NEW_COLUMNS:
        assert f"ADD COLUMN IF NOT EXISTS {col}" in up
    assert "CREATE INDEX IF NOT EXISTS idx_raw_conv_retry_catchup" in up
    # Le seed d'acquittement n'est émis QUE si l'opérateur a déclaré des ids ;
    # sans ids, la migration ne doit toucher aucune ligne (défaut du dépôt).
    if m._TERMINAL_ACKED_IDS:
        assert "SET acked = true" in up
        for _id in m._TERMINAL_ACKED_IDS:
            assert _id in up
    else:
        assert "SET acked = true" not in up
    # AUCUNE opération destructive sur l'existant
    for forbidden in ("DROP TABLE", "DROP COLUMN", "DELETE", "TRUNCATE",
                      "ALTER COLUMN", "DROP CONSTRAINT", "GRANT", "REVOKE"):
        assert forbidden not in up, f"upgrade ne doit pas contenir {forbidden!r}"


def test_downgrade_drops_only_new_objects():
    down = _collect(m.downgrade)
    assert "DROP INDEX IF EXISTS arac.idx_raw_conv_retry_catchup" in down
    for col in _NEW_COLUMNS:
        assert f"DROP COLUMN IF EXISTS {col}" in down
    # ne touche QUE les nouveaux objets, jamais la table ni des données
    for forbidden in ("DROP TABLE", "DELETE", "TRUNCATE", "memory_atoms"):
        assert forbidden not in down


def test_seed_only_known_terminal_ids():
    # Garde-fou : la liste de seed reste BORNÉE et n'appartient qu'à ce
    # cerveau-ci. Un identifiant hérité d'une autre base ne désignerait rien
    # ici ; le dépôt livre donc une liste vide, à VOUS de la remplir.
    assert isinstance(m._TERMINAL_ACKED_IDS, tuple)
    assert all(isinstance(i, str) and len(i) == 36 for i in m._TERMINAL_ACKED_IDS)
    assert len(m._TERMINAL_ACKED_IDS) <= 8, (
        "une liste d'acquittement qui s'allonge n'acquitte plus, elle masque"
    )
