"""Tests des migrations « Perception V4 » — 0020→0029, unitaires sans DB.

Ce fichier borne la VAGUE ENTIÈRE (9 migrations, label 0024
volontairement sauté/réservé pour la branche `context-engine-v4` — `0029` est
un ajout tardif de clôture Phase 1, fix D36, durcissement du trigger d'audit
d'exclusion posé par `0023`) :

  1. chaînage `down_revision` linéaire 0019 -> 0020 -> ... -> 0029 (pas de
     0024, pas de fork) ;
  2. présence des REVOKE défensifs par table (moindre privilège) ;
  3. forme de chaque migration (colonnes/tables/index créés, CHECK, grants) ;
  4. symétrie upgrade/downgrade (tout objet créé est retiré, à l'identique) ;
  5. idempotence textuelle (IF NOT EXISTS / IF EXISTS / ON CONFLICT présents
     partout où une ré-exécution doit être un no-op).

Les vérifications d'état LIVE (upgrade/downgrade réels sur une DB, lecture
des grants effectifs) restent une étape opérateur sur une DB docker jetable
(Docker absent sur cette machine — cf `db_admin`/`db_session` dans
conftest.py, qui SKIPPENT proprement si `DATABASE_URL_ADMIN_TEST` est absente).
Les 2 tests `test_live_*` en fin de fichier suivent ce même pattern.

Collisions de noms d'objets (tables/index) avec l'existant : vérifiées
MANUELLEMENT par `SELECT` en lecture seule contre la DB prod le 2026-07-06
(`pg_tables`/`pg_indexes` sur `arac`, zéro collision) — non ré-encodées ici
en test automatique pour ne jamais faire dépendre `make test` d'un accès à
la DB prod (interdit par le mandat de ce chantier).
"""

from __future__ import annotations

import glob
import importlib.util
import os
import re
import uuid

import pytest

_VERSIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "db", "alembic", "versions")

# Ordre de la vague « Perception V4 » + down_revision attendu pour chacune (chaîne linéaire,
# 0024 absent par construction).
_CHAIN = (
    ("0020_d063_ingest_sources", "0019_run_receipts"),
    ("0021_d063_ingest_receipts", "0020_d063_ingest_sources"),
    ("0022_d063_raw_message_revisions", "0021_d063_ingest_receipts"),
    ("0023_d063_conversation_exclusion", "0022_d063_raw_message_revisions"),
    ("0025_d063_schema_neutralizations", "0023_d063_conversation_exclusion"),
    ("0026_d063_capture_manifests", "0025_d063_schema_neutralizations"),
    ("0027_d063_run_receipts_conservation", "0026_d063_capture_manifests"),
    ("0028_d063_digestion_review_queue", "0027_d063_run_receipts_conserv"),
    ("0029_d063_exclusion_motive_audit", "0028_d063_digestion_review_queue"),
)


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


_MODULES = {name: _load(name) for name, _ in _CHAIN}


# ============================================================================
# 1. Chaîne + absence du label 0024
# ============================================================================

def test_no_0024_file_exists():
    """Le label 0024 est réservé/pris par la branche context-engine-v4 —
    aucun fichier `0024_*.py` ne doit exister dans cette vague."""
    matches = glob.glob(os.path.join(_VERSIONS_DIR, "0024_*.py"))
    assert matches == [], f"fichier 0024 inattendu trouvé : {matches}"


@pytest.mark.parametrize("name,expected_prev", _CHAIN)
def test_chain_down_revision(name, expected_prev):
    m = _MODULES[name]
    assert m.down_revision == expected_prev, (
        f"{name}: down_revision={m.down_revision!r} != attendu {expected_prev!r}"
    )


@pytest.mark.parametrize("name,_", _CHAIN)
def test_revision_fits_alembic_version_varchar32(name, _):
    m = _MODULES[name]
    assert len(m.revision) <= 32, f"{name}: revision {m.revision!r} > 32 chars"


def test_0025_docstring_documents_0024_reservation():
    """0025 doit documenter explicitement pourquoi 0024 est absent (contrat
    d'en-tête explicite)."""
    m = _MODULES["0025_d063_schema_neutralizations"]
    doc = m.__doc__ or ""
    assert "0024" in doc
    assert "context-engine-v4" in doc


# ============================================================================
# 2. REVOKE défensifs présents (moindre privilège par table)
# ============================================================================

_EXPECTED_REVOKES = {
    "0020_d063_ingest_sources": (
        "REVOKE INSERT, UPDATE ON arac.ingest_sources FROM arac_app;",
    ),
    "0021_d063_ingest_receipts": (
        "REVOKE UPDATE, DELETE ON arac.ingest_receipts FROM arac_app;",
        "REVOKE INSERT, UPDATE, DELETE ON arac.ingest_receipts FROM arac_agent;",
    ),
    "0022_d063_raw_message_revisions": (
        "REVOKE UPDATE, DELETE ON arac.raw_message_revisions FROM arac_app;",
        "REVOKE INSERT, UPDATE, DELETE ON arac.raw_message_revisions FROM arac_agent;",
    ),
    "0026_d063_capture_manifests": (
        "REVOKE UPDATE, DELETE ON arac.capture_manifests FROM arac_app;",
    ),
    "0028_d063_digestion_review_queue": (
        "REVOKE UPDATE, DELETE ON arac.digestion_review_queue FROM arac_app;",
        "REVOKE UPDATE, DELETE ON arac.digestion_review_queue FROM arac_agent;",
    ),
}


@pytest.mark.parametrize("name", list(_EXPECTED_REVOKES))
def test_revokes_present(name):
    m = _MODULES[name]
    up = _collect(m, m.upgrade)
    for stmt in _EXPECTED_REVOKES[name]:
        assert stmt in up, f"{name}: REVOKE attendu absent : {stmt!r}"


# ============================================================================
# 3. Forme par migration
# ============================================================================

def _node_id() -> str:
    """Le node_id sous lequel la migration a été rendue — le vôtre."""
    import arac_runtime

    return arac_runtime.node_id()


def test_0020_ingest_sources_shape():
    """Le registre est créé, et il ne peut pas contenir de ligne muette."""
    m = _MODULES["0020_d063_ingest_sources"]
    up = _collect(m, m.upgrade)
    assert "CREATE TABLE IF NOT EXISTS arac.ingest_sources" in up
    assert "CHECK (coverage_policy IN ('captured', 'excluded', 'uncovered'))" in up
    # La contrainte d'HONNÊTETÉ : `captured` exige un délai annoncé, tout le
    # reste exige un motif. Une source sans l'un ni l'autre serait un angle
    # mort déguisé en ligne de registre.
    assert "ingest_sources_honesty_check" in up
    assert "ON CONFLICT (node_id) DO NOTHING" in up
    assert "ON CONFLICT (source_key) DO NOTHING" in up


def test_0020_seeds_the_user_node_not_an_inherited_one():
    """AUCUN identifiant hérité : le seed porte le node_id de CE cerveau.

    C'est le test qui empêche la régression la plus facile à commettre —
    laisser filer dans une migration le nom de machine de quelqu'un d'autre.
    """
    m = _MODULES["0020_d063_ingest_sources"]
    up = _collect(m, m.upgrade)
    node = _node_id()
    assert f"'claude_code@{node}'" in up
    assert f"'{node}-server'" in up


def test_0020_downgrade_removes_seed_and_table():
    m = _MODULES["0020_d063_ingest_sources"]
    down = _collect(m, m.downgrade)
    assert f"DELETE FROM arac.nodes WHERE node_id = '{_node_id()}-server'" in down
    assert "DROP TABLE IF EXISTS arac.ingest_sources CASCADE" in down


def _seeded_coverage_policy(up: str, source_key: str) -> str:
    """La `coverage_policy` seedée pour `source_key` (5e champ du tuple)."""
    match = re.search(
        r"'" + re.escape(source_key) + r"',[^,]+,[^,]+,[^,]+,\s*'(captured|excluded|uncovered)'",
        up,
    )
    assert match, f"source_key {source_key!r} introuvable/forme inattendue dans le SQL seedé"
    return match.group(1)


def test_0020_declares_only_what_is_really_armed():
    """Le piège de la fenêtre d'installation, et pourquoi il compte.

    Le chien de garde n'évalue que les sources `captured`. Déclarer capté ce
    qui n'est pas encore armé le fait donc hurler en continu pendant toute
    l'installation — et on apprend à ignorer l'alarme. Le jour où elle a
    raison, plus personne ne l'écoute.

    Seul le pont Mac (l'exportateur que l'utilisateur installe en premier) est
    `captured`. Les deux autres sont `uncovered` : des trous ASSUMÉS, visibles
    au cockpit avec leur motif, à basculer quand ils tourneront vraiment.
    """
    m = _MODULES["0020_d063_ingest_sources"]
    up = _collect(m, m.upgrade)
    node = _node_id()
    assert _seeded_coverage_policy(up, f"claude_code@{node}") == "captured"
    assert _seeded_coverage_policy(up, "desktop_chat@claude.ai") == "uncovered"
    assert _seeded_coverage_policy(up, f"claude_code@{node}-server") == "uncovered"


def test_0020_uncovered_sources_say_how_to_flip_them():
    """Un `uncovered` doit dire comment il cesse de l'être.

    Sans cela, un trou déclaré devient un trou permanent : personne ne sait
    plus quel geste le referme, donc personne ne le referme.
    """
    m = _MODULES["0020_d063_ingest_sources"]
    up = _collect(m, m.upgrade)
    doc = m.__doc__ or ""
    assert "desktop_chat@claude.ai" in doc
    assert "UPDATE arac.ingest_sources" in doc
    assert "coverage_policy = 'captured'" in doc
    # Et le motif consigné en base doit lui aussi désigner le geste.
    assert "captured" in up


def test_0021_ingest_receipts_shape():
    m = _MODULES["0021_d063_ingest_receipts"]
    up = _collect(m, m.upgrade)
    assert "CREATE TABLE IF NOT EXISTS arac.ingest_receipts" in up
    for outcome in (
        "accepted", "duplicate_noop", "refused_400", "refused_413",
        "refused_422", "refused_409", "rate_limited_429", "error_500",
    ):
        assert f"'{outcome}'" in up
    for idx in (
        "idx_ingest_receipts_node_created", "idx_ingest_receipts_outcome",
        "idx_ingest_receipts_request_id",
    ):
        assert f"CREATE INDEX IF NOT EXISTS {idx}" in up
    down = _collect(m, m.downgrade)
    assert down.strip() == "DROP TABLE IF EXISTS arac.ingest_receipts CASCADE"


def test_0022_raw_message_revisions_shape():
    m = _MODULES["0022_d063_raw_message_revisions"]
    up = _collect(m, m.upgrade)
    assert "CREATE TABLE IF NOT EXISTS arac.raw_message_revisions" in up
    assert "REFERENCES arac.raw_messages(id) ON DELETE RESTRICT" in up
    assert "REFERENCES arac.conversations(id) ON DELETE RESTRICT" in up
    assert "CHECK (reason IN ('hash_divergence', 'healing'))" in up
    down = _collect(m, m.downgrade)
    assert down.strip() == "DROP TABLE IF EXISTS arac.raw_message_revisions CASCADE"


def test_0023_conversation_exclusion_shape():
    m = _MODULES["0023_d063_conversation_exclusion"]
    up = _collect(m, m.upgrade)
    for col in ("exclusion_reason", "exclusion_category", "excluded_at", "excluded_by"):
        assert f"ADD COLUMN IF NOT EXISTS {col}" in up
    for cat in (
        "anthropic_temporary_purged", "duplicate_source", "no_curable_content",
        "operator_manual", "test",
    ):
        assert f"'{cat}'" in up
    assert "CHECK (acked = false OR exclusion_reason IS NOT NULL) NOT VALID" in up
    assert "VALIDATE CONSTRAINT conversations_exclusion_ack_check" in up
    assert "SECURITY DEFINER" in up
    assert "SET search_path = arac, pg_catalog" in up
    assert "CREATE OR REPLACE TRIGGER trg_conversations_ack_audit" in up
    assert "BEFORE UPDATE ON arac.conversations" in up
    assert "INSERT INTO arac.audit_log" in up
    # aucune donnée existante touchée (ADD COLUMN nullable + NOT VALID + trigger)
    for forbidden in ("DROP TABLE", "DELETE FROM", "TRUNCATE"):
        assert forbidden not in up


def test_0023_downgrade_drops_only_new_objects():
    m = _MODULES["0023_d063_conversation_exclusion"]
    down = _collect(m, m.downgrade)
    assert "DROP TRIGGER IF EXISTS trg_conversations_ack_audit ON arac.conversations" in down
    assert "DROP FUNCTION IF EXISTS arac.conversations_ack_audit()" in down
    assert "DROP CONSTRAINT IF EXISTS conversations_exclusion_ack_check" in down
    for col in ("exclusion_reason", "exclusion_category", "excluded_at", "excluded_by"):
        assert f"DROP COLUMN IF EXISTS {col}" in down
    assert "DROP TABLE" not in down


def test_0023_downgrade_resets_acked_before_dropping_exclusion_reason():
    """Finding 26 (revue adversariale, prouvé sur cluster jetable) : sans ce
    reset, une conversation exclue (`acked=true` + `exclusion_reason`) perd
    son motif au DROP COLUMN mais reste `acked=true` — un re-`upgrade`
    ultérieur échoue alors à la `VALIDATE CONSTRAINT`
    (`conversations_exclusion_ack_check`, `exclusion_reason` ré-ajoutée à
    NULL par défaut). Le `UPDATE` doit s'exécuter AVANT le `DROP COLUMN
    exclusion_reason` (sinon la condition `exclusion_reason IS NOT NULL` ne
    peut plus rien filtrer)."""
    m = _MODULES["0023_d063_conversation_exclusion"]
    down = _collect(m, m.downgrade)
    assert (
        "UPDATE arac.conversations SET acked = false "
        "WHERE acked = true AND exclusion_reason IS NOT NULL" in down
    ), "le downgrade doit remettre acked=false sur les conversations exclues avant le DROP"
    idx_update = down.index("UPDATE arac.conversations SET acked = false")
    idx_drop_reason = down.index("DROP COLUMN IF EXISTS exclusion_reason")
    assert idx_update < idx_drop_reason, (
        "le reset acked=false doit précéder le DROP COLUMN exclusion_reason "
        "(sinon la condition WHERE ne peut plus rien filtrer)"
    )


def test_0025_schema_neutralizations_shape():
    m = _MODULES["0025_d063_schema_neutralizations"]
    up = _collect(m, m.upgrade)
    assert "DROP INDEX IF EXISTS arac.idx_raw_conv_expires" in up
    assert "ALTER TABLE arac.raw_conversations DROP COLUMN IF EXISTS expires_at" in up
    assert (
        "ALTER TABLE arac.raw_messages "
        "ADD COLUMN IF NOT EXISTS was_masked boolean NOT NULL DEFAULT false"
    ) in up
    # zéro row touchée : uniquement du DDL, aucun DML
    for forbidden in ("DELETE FROM", "TRUNCATE", "UPDATE "):
        assert forbidden not in up


def test_0025_downgrade_recreates_expires_at_identically():
    m = _MODULES["0025_d063_schema_neutralizations"]
    down = _collect(m, m.downgrade)
    assert "ALTER TABLE arac.raw_messages DROP COLUMN IF EXISTS was_masked" in down
    assert "now() + interval '90 days'" in down
    assert "NOT NULL" in down
    assert "WHERE status != 'purged'" in down
    assert "CREATE INDEX IF NOT EXISTS idx_raw_conv_expires" in down


def test_0026_capture_manifests_shape():
    m = _MODULES["0026_d063_capture_manifests"]
    up = _collect(m, m.upgrade)
    assert "CREATE TABLE IF NOT EXISTS arac.capture_manifests" in up
    assert "messages_filtered" in up and "jsonb" in up
    assert "state_sha256" in up
    down = _collect(m, m.downgrade)
    assert down.strip() == "DROP TABLE IF EXISTS arac.capture_manifests CASCADE"


def test_0027_run_receipts_conservation_columns_symmetric():
    m = _MODULES["0027_d063_run_receipts_conservation"]
    up = _collect(m, m.upgrade)
    down = _collect(m, m.downgrade)
    cols = (
        "messages_reported", "messages_truncated", "oversized_messages",
        "coverage_presented", "coverage_covered", "coverage_no_new_knowledge",
        "coverage_omitted", "quarantine_attributed_uids",
    )
    for col in cols:
        assert f"ADD COLUMN IF NOT EXISTS {col}" in up, f"colonne absente de l'upgrade : {col}"
        assert f"DROP COLUMN IF EXISTS {col}" in down, f"colonne absente du downgrade : {col}"
    for forbidden in ("DROP TABLE", "DELETE FROM", "TRUNCATE", "GRANT", "REVOKE"):
        assert forbidden not in up
        assert forbidden not in down


def test_0028_digestion_review_queue_shape():
    m = _MODULES["0028_d063_digestion_review_queue"]
    up = _collect(m, m.upgrade)
    assert "CREATE TABLE IF NOT EXISTS arac.digestion_review_queue" in up
    for reason in (
        "kept_lower_confidence", "policy_skip", "atom_quarantine",
        "coverage_omitted", "oversized_message",
    ):
        assert f"'{reason}'" in up
    for status in ("pending", "reviewed_kept", "reviewed_dropped"):
        assert f"'{status}'" in up
    assert "DEFAULT 'pending'" in up
    # déviation documentée vs : memory_atoms.id est uuid (pas bigint)
    assert "incumbent_atom_id   uuid" in up
    assert "REFERENCES arac.memory_atoms(id) ON DELETE SET NULL" in up
    down = _collect(m, m.downgrade)
    assert down.strip() == "DROP TABLE IF EXISTS arac.digestion_review_queue CASCADE"


def test_0029_exclusion_motive_audit_adds_second_branch_keeps_first():
    """Fix D36 : la fonction étendue doit CONSERVER la branche 0023
    (`conversation_ack_exclusion`, transition false->true) ET AJOUTER la
    nouvelle branche (`conversation_exclusion_motive_changed`, mutation d'un
    motif déjà consigné) — jamais un remplacement qui perdrait la 1ère."""
    m = _MODULES["0029_d063_exclusion_motive_audit"]
    up = _collect(m, m.upgrade)
    assert "CREATE OR REPLACE FUNCTION arac.conversations_ack_audit() RETURNS trigger" in up
    assert "SECURITY DEFINER" in up
    assert "SET search_path = arac, pg_catalog" in up
    # branche existante (0023) préservée
    assert "IF OLD.acked = false AND NEW.acked = true THEN" in up
    assert "'conversation_ack_exclusion'" in up
    # branche nouvelle
    assert "ELSIF OLD.acked = true AND NEW.acked = true AND (" in up
    assert "'conversation_exclusion_motive_changed'" in up
    for col in ("exclusion_reason", "exclusion_category", "excluded_by"):
        assert f"NEW.{col} IS DISTINCT FROM OLD.{col}" in up
    for field in ("old_reason", "old_category", "old_excluded_by", "new_reason", "new_category", "new_excluded_by"):
        assert f"'{field}'" in up
    assert "CREATE OR REPLACE TRIGGER trg_conversations_ack_audit" in up
    # aucun nouveau trigger, aucune donnée existante touchée
    assert up.count("CREATE OR REPLACE TRIGGER") == 1
    for forbidden in ("DROP TABLE", "DELETE FROM", "TRUNCATE", "CREATE TABLE", "ALTER TABLE"):
        assert forbidden not in up


def test_0029_downgrade_restores_0023_body_exactly():
    """Symétrie upgrade/downgrade : le downgrade restaure EXACTEMENT le
    corps `0023` (une seule branche) — jamais la 2e branche qui traînerait
    après un rollback de schéma."""
    m0023 = _MODULES["0023_d063_conversation_exclusion"]
    m0029 = _MODULES["0029_d063_exclusion_motive_audit"]
    up_0023 = _collect(m0023, m0023.upgrade)
    down_0029 = _collect(m0029, m0029.downgrade)

    # Le corps CREATE OR REPLACE FUNCTION de 0023 (extrait entre les deux
    # marqueurs stables) doit être retrouvé À L'IDENTIQUE dans le downgrade
    # de 0029.
    start = up_0023.index("CREATE OR REPLACE FUNCTION arac.conversations_ack_audit()")
    end = up_0023.index("CREATE OR REPLACE TRIGGER trg_conversations_ack_audit")
    body_0023 = up_0023[start:end]
    assert body_0023 in down_0029, (
        "le downgrade de 0029 doit restaurer le corps EXACT de la fonction 0023"
    )
    assert "conversation_exclusion_motive_changed" not in down_0029
    assert "ELSIF" not in down_0029
    assert "CREATE OR REPLACE TRIGGER trg_conversations_ack_audit" in down_0029
    for forbidden in ("DROP FUNCTION", "DROP TRIGGER"):
        assert forbidden not in down_0029


def test_0029_motive_change_branch_scoped_to_motive_columns_only():
    """Non-régression (finding du design) : la condition `IS DISTINCT FROM`
    ne porte QUE sur les 3 colonnes de motif -- un `UPDATE` qui touche
    `curated_through_message_id` (rembobinage `heal_empty_messages.py`) sans
    toucher `exclusion_*`/`excluded_by` ne doit JAMAIS entrer dans cette
    condition SQL (vérifié textuellement : aucune colonne hors motif dans le
    bloc `ELSIF`)."""
    m = _MODULES["0029_d063_exclusion_motive_audit"]
    up = _collect(m, m.upgrade)
    start = up.index("ELSIF OLD.acked = true")
    end = up.index("INSERT INTO arac.audit_log", start)
    condition_block = up[start:end]
    assert "curated_through_message_id" not in condition_block


# ============================================================================
# 4. Idempotence textuelle — chaque migration rejouée deux fois doit être un no-op
# ============================================================================

_IDEMPOTENCE_MARKERS = {
    "0020_d063_ingest_sources": ("CREATE TABLE IF NOT EXISTS", "ON CONFLICT"),
    "0021_d063_ingest_receipts": ("CREATE TABLE IF NOT EXISTS", "CREATE INDEX IF NOT EXISTS"),
    "0022_d063_raw_message_revisions": ("CREATE TABLE IF NOT EXISTS", "CREATE INDEX IF NOT EXISTS"),
    "0023_d063_conversation_exclusion": ("ADD COLUMN IF NOT EXISTS", "DROP CONSTRAINT IF EXISTS",
                                         "CREATE OR REPLACE FUNCTION", "CREATE OR REPLACE TRIGGER"),
    "0025_d063_schema_neutralizations": ("DROP INDEX IF EXISTS", "DROP COLUMN IF EXISTS",
                                         "ADD COLUMN IF NOT EXISTS"),
    "0026_d063_capture_manifests": ("CREATE TABLE IF NOT EXISTS", "CREATE INDEX IF NOT EXISTS"),
    "0027_d063_run_receipts_conservation": ("ADD COLUMN IF NOT EXISTS",),
    "0028_d063_digestion_review_queue": ("CREATE TABLE IF NOT EXISTS", "CREATE INDEX IF NOT EXISTS"),
    "0029_d063_exclusion_motive_audit": ("CREATE OR REPLACE FUNCTION", "CREATE OR REPLACE TRIGGER"),
}


@pytest.mark.parametrize("name", list(_IDEMPOTENCE_MARKERS))
def test_upgrade_is_replay_safe_textually(name):
    """Chaque motif structurant de l'upgrade utilise une forme idempotente
    (IF NOT EXISTS / ON CONFLICT / CREATE OR REPLACE / DROP ... IF EXISTS
    avant re-ADD) — un replay de la migration ne doit jamais lever d'erreur
    « already exists »."""
    m = _MODULES[name]
    up = _collect(m, m.upgrade)
    for marker in _IDEMPOTENCE_MARKERS[name]:
        assert marker in up, f"{name}: marqueur d'idempotence absent : {marker!r}"


@pytest.mark.parametrize("name,_", _CHAIN)
def test_downgrade_uses_if_exists_forms(name, _):
    """Tout DROP/ALTER du downgrade est en forme `IF EXISTS` (un downgrade
    déjà appliqué, rejoué, ne doit jamais échouer)."""
    m = _MODULES[name]
    down = _collect(m, m.downgrade)
    for drop_stmt in re.findall(r"DROP (?:TABLE|INDEX|TRIGGER|FUNCTION|COLUMN)\b[^\n;]*", down):
        assert "IF EXISTS" in drop_stmt, f"{name}: DROP sans IF EXISTS : {drop_stmt!r}"


# ============================================================================
# 5. Vérifications LIVE (DB docker jetable UNIQUEMENT — skip proprement sinon)
# ============================================================================
#
# Docker est absent sur cette machine : ces 2 tests SKIPPENT
# via la fixture `db_admin` (conftest.py, cf sa docstring) et ne s'exécutent
# que sur une machine où `make test-db-up` a préalablement appliqué
# `alembic upgrade head` (le cycle DB réel reste une étape opérateur, cf
# Makefile — même doctrine que test_migration_reversibility.py).


async def test_live_d063_tables_and_columns_exist(db_admin):
    async with db_admin.cursor() as cur:
        await cur.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'arac' "
            "AND tablename = ANY(%s)",
            (["ingest_sources", "ingest_receipts", "raw_message_revisions",
              "capture_manifests", "digestion_review_queue"],),
        )
        found = {row[0] for row in await cur.fetchall()}
    assert found == {
        "ingest_sources", "ingest_receipts", "raw_message_revisions",
        "capture_manifests", "digestion_review_queue",
    }


async def test_live_0029_motive_change_on_already_excluded_conversation_is_audited(db_admin):
    """Fix D36, vérification LIVE : un `UPDATE` qui mute `exclusion_reason`
    sur une conversation DÉJÀ `acked=true` produit 1 row `audit_log`
    `action='conversation_exclusion_motive_changed'` — MÊME hors du CLI
    `exclude_conversation.py` (SQL direct ici), preuve de la
    non-contournabilité (SECURITY DEFINER)."""
    conv_uid = f"test-motive-audit-{uuid.uuid4()}"
    async with db_admin.cursor() as cur:
        await cur.execute(
            "INSERT INTO arac.conversations "
            "(source_type, conversation_uid, node_id, acked, exclusion_reason, "
            " exclusion_category, excluded_by, excluded_at) "
            "VALUES ('desktop_chat', %s, 'poste-ingest', true, 'motif initial', "
            " 'test', 'operator_review', now()) RETURNING id",
            (conv_uid,),
        )
        (conv_id,) = await cur.fetchone()
    try:
        async with db_admin.cursor() as cur:
            await cur.execute(
                "SELECT count(*) FROM arac.audit_log WHERE action = "
                "'conversation_exclusion_motive_changed' AND (result_summary->>'conversation_id')::uuid = %s",
                (conv_id,),
            )
            (before,) = await cur.fetchone()
        assert before == 0

        async with db_admin.cursor() as cur:
            await cur.execute(
                "UPDATE arac.conversations SET exclusion_reason = 'motif modifié' WHERE id = %s",
                (conv_id,),
            )

        async with db_admin.cursor() as cur:
            await cur.execute(
                "SELECT result_summary FROM arac.audit_log WHERE action = "
                "'conversation_exclusion_motive_changed' AND (result_summary->>'conversation_id')::uuid = %s",
                (conv_id,),
            )
            rows = await cur.fetchall()
        assert len(rows) == 1, "exactement 1 nouvelle row audit_log pour cette mutation de motif"
        summary = rows[0][0]
        assert summary["old_reason"] == "motif initial"
        assert summary["new_reason"] == "motif modifié"
        assert summary["conversation_uid"] == conv_uid
    finally:
        async with db_admin.cursor() as cur:
            await cur.execute(
                "DELETE FROM arac.audit_log WHERE (result_summary->>'conversation_id')::uuid = %s",
                (conv_id,),
            )
            await cur.execute("DELETE FROM arac.conversations WHERE id = %s", (conv_id,))


async def test_live_0029_non_motive_update_does_not_spam_audit_log(db_admin):
    """Non-régression : un `UPDATE` qui touche `curated_through_message_id`
    (rembobinage `heal_empty_messages.py`) SANS toucher les colonnes de motif
    ne déclenche PAS la nouvelle branche — 0 nouvelle row `audit_log`."""
    conv_uid = f"test-motive-audit-norewind-{uuid.uuid4()}"
    async with db_admin.cursor() as cur:
        await cur.execute(
            "INSERT INTO arac.conversations "
            "(source_type, conversation_uid, node_id, acked, exclusion_reason, "
            " exclusion_category, excluded_by, excluded_at) "
            "VALUES ('desktop_chat', %s, 'poste-ingest', true, 'motif stable', "
            " 'test', 'operator_review', now()) RETURNING id",
            (conv_uid,),
        )
        (conv_id,) = await cur.fetchone()
    try:
        async with db_admin.cursor() as cur:
            await cur.execute(
                "UPDATE arac.conversations SET curated_through_message_id = 42 WHERE id = %s",
                (conv_id,),
            )
        async with db_admin.cursor() as cur:
            await cur.execute(
                "SELECT count(*) FROM arac.audit_log WHERE action = "
                "'conversation_exclusion_motive_changed' AND (result_summary->>'conversation_id')::uuid = %s",
                (conv_id,),
            )
            (n,) = await cur.fetchone()
        assert n == 0
    finally:
        async with db_admin.cursor() as cur:
            await cur.execute("DELETE FROM arac.conversations WHERE id = %s", (conv_id,))


async def test_live_0029_first_ack_still_uses_original_action_name(db_admin):
    """Non-régression : la transition `acked` false->true (1ère exclusion)
    déclenche TOUJOURS `action='conversation_ack_exclusion'` (branche 0023
    inchangée), jamais la nouvelle `conversation_exclusion_motive_changed`."""
    conv_uid = f"test-motive-audit-firstack-{uuid.uuid4()}"
    async with db_admin.cursor() as cur:
        await cur.execute(
            "INSERT INTO arac.conversations (source_type, conversation_uid, node_id) "
            "VALUES ('desktop_chat', %s, 'poste-ingest') RETURNING id",
            (conv_uid,),
        )
        (conv_id,) = await cur.fetchone()
    try:
        async with db_admin.cursor() as cur:
            await cur.execute(
                "UPDATE arac.conversations SET acked = true, exclusion_reason = 'motif', "
                "exclusion_category = 'test', excluded_by = 'operator_review' WHERE id = %s",
                (conv_id,),
            )
        async with db_admin.cursor() as cur:
            await cur.execute(
                "SELECT action FROM arac.audit_log WHERE (result_summary->>'conversation_id')::uuid = %s "
                "ORDER BY created_at",
                (conv_id,),
            )
            actions = [row[0] for row in await cur.fetchall()]
        assert actions == ["conversation_ack_exclusion"]
    finally:
        async with db_admin.cursor() as cur:
            await cur.execute(
                "DELETE FROM arac.audit_log WHERE (result_summary->>'conversation_id')::uuid = %s",
                (conv_id,),
            )
            await cur.execute("DELETE FROM arac.conversations WHERE id = %s", (conv_id,))


async def test_live_d063_ingest_sources_seed_present(db_admin):
    async with db_admin.cursor() as cur:
        await cur.execute(
            "SELECT source_key, coverage_policy FROM arac.ingest_sources "
            "ORDER BY source_key"
        )
        rows = dict(await cur.fetchall())
    assert rows.get("claude_code@mac") == "captured"
    assert rows.get("claude_code@travail") == "uncovered"
    assert rows.get("claude_code@mac-mini") == "excluded"
