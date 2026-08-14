"""Tests — scripts SQL rôles least-privilege V1.6D (statiques, 0 DB).

La matrice live est vérifiée par has_table_privilege/has_column_privilege (cf doc V1.6D) ;
ici on borne le CONTENU des scripts : additif only, colonnes UPDATE exactes, rollback
inverse, zéro password, zéro REVOKE sur les rôles existants dans l'apply.
"""
import os
import re

_DIR = os.path.join(os.path.dirname(__file__), "..", "db", "migrations")


def _sql_only(path):
    """SQL effectif : lignes de commentaires retirées (les `--` expliquent, ne s'exécutent pas)."""
    lines = open(path, encoding="utf-8").read().splitlines()
    return "\n".join(ln for ln in lines if not ln.lstrip().startswith("--"))


APPLY = _sql_only(os.path.join(_DIR, "07_roles_least_privilege_v1_6d.sql"))
ROLLBACK = _sql_only(os.path.join(_DIR, "07_roles_least_privilege_v1_6d_rollback.sql"))


def test_apply_is_transactional_and_idempotent():
    assert "BEGIN;" in APPLY and "COMMIT;" in APPLY
    assert "IF NOT EXISTS" in APPLY                  # ré-exécution sûre


def test_apply_creates_only_the_two_nologin_roles():
    assert APPLY.count("CREATE ROLE") == 2
    assert "arac_proposal_queue_writer NOLOGIN" in APPLY
    assert "arac_memory_writer NOLOGIN" in APPLY
    assert "LOGIN PASSWORD" not in APPLY             # jamais de credential dans le repo


def test_apply_grants_are_bounded():
    # memory_writer : INSERT+SELECT sur memory_atoms only — jamais UPDATE/DELETE
    assert "GRANT SELECT, INSERT ON arac.memory_atoms TO arac_memory_writer" in APPLY
    assert not re.search(r"GRANT[^;]*UPDATE[^;]*memory_atoms", APPLY)
    assert not re.search(r"GRANT[^;]*DELETE", APPLY)
    # proposal_queue_writer : UPDATE par liste de colonnes de cycle de vie uniquement
    assert "UPDATE (status, reject_reason, updated_at)" in APPLY
    # aucune autre table accordée
    for forbidden in ("memory_review_queue", "raw_conversations", "audit_log"):
        assert forbidden not in APPLY


def test_apply_never_revokes_existing_roles():
    assert "REVOKE" not in APPLY
    for role in ("arac_app", "arac_agent", "arac_readonly", "arac_review_writer"):
        assert role not in APPLY                     # additive only, rôles existants intouchés


def test_rollback_is_exact_inverse():
    assert "BEGIN;" in ROLLBACK and "COMMIT;" in ROLLBACK
    assert "REVOKE ALL ON arac.incoming_proposal_queue FROM arac_proposal_queue_writer" in ROLLBACK
    assert "REVOKE ALL ON arac.memory_atoms FROM arac_memory_writer" in ROLLBACK
    assert ROLLBACK.count("DROP ROLE IF EXISTS") == 2
    for role in ("arac_app", "arac_agent"):
        assert role not in ROLLBACK                  # le rollback ne touche pas l'existant


def test_no_password_or_dsn_anywhere():
    for blob in (APPLY, ROLLBACK):
        assert "PASSWORD" not in blob.upper()        # aucun credential dans le SQL effectif
        assert "postgresql://" not in blob
