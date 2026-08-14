"""Tests unitaires pour agents/lib/commit_audit.py — Phase D.4.

Couvre l'audit statique du commit_proposal (Phase D.2). Aucun appel BDD,
aucun mock complexe : `commit_audit.audit(...)` est une fonction pure.

Cible : >70% de couverture sur les 6 règles d'audit (diff non vide, branche
feature/*, files <= MAX_FILES, diff <= MAX_DIFF_LINES, paths interdits,
regex secrets).
"""

from __future__ import annotations

import pytest

from agents.lib import commit_audit
from agents.lib.commit_audit import (
    AuditResult,
    MAX_DIFF_LINES,
    MAX_FILES,
    audit,
)


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_happy_path_small_diff_on_feature_branch():
    """Diff trivial sur feature/* avec fichiers banals → approved."""
    diff = "diff --git a/docs/x.md b/docs/x.md\n@@ -0,0 +1,1 @@\n+hello\n"
    r = audit(diff_text=diff, files=["docs/x.md"], branch="feature/d4-test")
    assert r.ok is True
    assert r.reasons == []


def test_happy_path_multiple_files_under_limit():
    """5 fichiers sur feature/* → approved."""
    diff = "diff content\n+line\n" * 5
    files = [f"docs/note-{i}.md" for i in range(5)]
    r = audit(diff_text=diff, files=files, branch="feature/abc")
    assert r.ok is True


# ---------------------------------------------------------------------------
# Diff vide
# ---------------------------------------------------------------------------


def test_empty_diff_and_no_files_rejected():
    """Pas de diff + pas de fichiers → rejected 'empty diff'."""
    r = audit(diff_text="", files=[], branch="feature/x")
    assert r.ok is False
    assert any("empty diff" in reason for reason in r.reasons)


def test_diff_whitespace_only_with_no_files_rejected():
    """Diff = whitespace seul + 0 fichiers → rejected."""
    r = audit(diff_text="   \n\n  \n", files=[], branch="feature/x")
    assert r.ok is False


def test_diff_empty_but_files_present_passes_diff_check():
    """Diff vide MAIS files non vide → passe le check #1, autres règles peuvent fail."""
    # Files non vide donc on ne déclenche pas 'empty diff'. Branche feature/* OK.
    r = audit(diff_text="", files=["docs/x.md"], branch="feature/x")
    # On accepte que ce cas passe puisque le test #1 demande explicitement "diff vide ET files vide".
    assert r.ok is True


# ---------------------------------------------------------------------------
# Branche
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("branch", ["main", "master"])
def test_forbidden_branch_main_or_master(branch):
    """Branches main/master interdites."""
    r = audit(diff_text="+x\n", files=["docs/x.md"], branch=branch)
    assert r.ok is False
    assert any("forbidden branch" in reason for reason in r.reasons)


def test_branch_not_starting_with_feature_rejected():
    """Branche `hotfix/critical-bug` rejetée (pas feature/*)."""
    r = audit(diff_text="+x\n", files=["docs/x.md"], branch="hotfix/critical")
    assert r.ok is False
    assert any("does not start with" in reason for reason in r.reasons)


def test_branch_none_rejected():
    """Branche None (rev-parse a échoué) → rejected."""
    r = audit(diff_text="+x\n", files=["docs/x.md"], branch=None)
    assert r.ok is False
    assert any("unknown branch" in reason for reason in r.reasons)


def test_branch_feature_exact_match_accepted():
    """`feature/` strict (juste le préfixe) est techniquement accepté."""
    r = audit(diff_text="+x\n", files=["docs/x.md"], branch="feature/x")
    assert r.ok is True


# ---------------------------------------------------------------------------
# Volume (files count + diff lines)
# ---------------------------------------------------------------------------


def test_too_many_files_rejected():
    """Plus de MAX_FILES → rejected."""
    files = [f"docs/f-{i}.md" for i in range(MAX_FILES + 5)]
    r = audit(diff_text="+x\n", files=files, branch="feature/big-refactor")
    assert r.ok is False
    assert any("too many files" in reason for reason in r.reasons)


def test_max_files_exactly_accepted():
    """Exactement MAX_FILES → accepté (borne inclusive)."""
    files = [f"docs/f-{i}.md" for i in range(MAX_FILES)]
    r = audit(diff_text="+x\n", files=files, branch="feature/exactly-max")
    assert r.ok is True


def test_diff_too_large_rejected():
    """Diff > MAX_DIFF_LINES → rejected."""
    diff = "+line\n" * (MAX_DIFF_LINES + 5)
    r = audit(diff_text=diff, files=["src/big.py"], branch="feature/huge")
    assert r.ok is False
    assert any("diff too large" in reason for reason in r.reasons)


def test_diff_at_max_lines_accepted():
    """Diff = exactement MAX_DIFF_LINES (borne) → accepté."""
    diff = "+line\n" * MAX_DIFF_LINES
    r = audit(diff_text=diff, files=["src/medium.py"], branch="feature/edge")
    assert r.ok is True


# ---------------------------------------------------------------------------
# Paths interdits
# ---------------------------------------------------------------------------


def test_forbidden_path_founding_atoms_rejected():
    """Modifier data/founding-atoms/ → rejected."""
    r = audit(
        diff_text="+constitution change\n",
        files=["data/founding-atoms/anti-fabulation.json"],
        branch="feature/sneak",
    )
    assert r.ok is False
    assert any("forbidden path" in reason and "founding-atoms" in reason for reason in r.reasons)


def test_forbidden_path_aracagent_home_rejected():
    """Modifier data/aracagent-home/ → rejected."""
    r = audit(
        diff_text="+x\n",
        files=["data/aracagent-home/.claude/leak.json"],
        branch="feature/x",
    )
    assert r.ok is False


def test_forbidden_path_dotenv_rejected():
    """Modifier .env → rejected."""
    r = audit(
        diff_text="+SECRET=foo\n",
        files=[".env"],
        branch="feature/x",
    )
    assert r.ok is False
    assert any("forbidden path" in reason for reason in r.reasons)


def test_mixed_files_allowed_and_forbidden_rejected():
    """1 fichier ok + 1 fichier interdit → rejected."""
    r = audit(
        diff_text="+x\n",
        files=["docs/x.md", "data/founding-atoms/anti.json"],
        branch="feature/x",
    )
    assert r.ok is False
    assert any("founding-atoms" in reason for reason in r.reasons)


# ---------------------------------------------------------------------------
# Regex secrets
# ---------------------------------------------------------------------------


def test_secret_aws_access_key_detected():
    """AKIA + 16 chars uppercase/digits → rejected."""
    diff = "+AWS_KEY=AKIAQWERTYUIOPASDFGH\n"
    r = audit(diff_text=diff, files=["agents/foo.py"], branch="feature/x")
    assert r.ok is False
    assert any("aws_access_key" in reason for reason in r.reasons)


def test_secret_anthropic_api_key_detected():
    """sk-ant-* → rejected."""
    diff = "+ANTHROPIC_API_KEY=sk-ant-abc123xyz456def789ghi\n"
    r = audit(diff_text=diff, files=["agents/foo.py"], branch="feature/x")
    assert r.ok is False
    assert any("anthropic_api_key" in reason for reason in r.reasons)


def test_secret_github_token_detected():
    """ghp_* (30+ chars) → rejected."""
    diff = "+GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz0123456789\n"
    r = audit(diff_text=diff, files=["agents/foo.py"], branch="feature/x")
    assert r.ok is False
    assert any("github_token" in reason for reason in r.reasons)


def test_secret_private_key_header_detected():
    """BEGIN PRIVATE KEY → rejected."""
    diff = "+-----BEGIN OPENSSH PRIVATE KEY-----\n+abc\n+-----END OPENSSH PRIVATE KEY-----\n"
    r = audit(diff_text=diff, files=["data/key"], branch="feature/x")
    assert r.ok is False
    assert any("private_key_header" in reason for reason in r.reasons)


def test_secret_jwt_detected():
    """JWT eyJ... → rejected."""
    diff = "+token = 'eyJabcdefghijklmnopqrstu.eyJabcdefghijklmnopqrstu.sig'\n"
    r = audit(diff_text=diff, files=["agents/foo.py"], branch="feature/x")
    assert r.ok is False
    assert any("jwt" in reason for reason in r.reasons)


def test_secret_password_assignment_detected():
    """password = '...' → rejected."""
    diff = '+password = "supersecret123"\n'
    r = audit(diff_text=diff, files=["agents/foo.py"], branch="feature/x")
    assert r.ok is False
    assert any("password_assignment" in reason for reason in r.reasons)


def test_no_secret_in_clean_diff():
    """Diff sans aucun secret matché → ok."""
    diff = "+def hello():\n+    return 'world'\n"
    r = audit(diff_text=diff, files=["agents/foo.py"], branch="feature/x")
    assert r.ok is True
    assert r.reasons == []


def test_secret_preview_is_masked():
    """Le secret matché est masqué dans la reason (6 premiers chars + ***)."""
    diff = "+key=AKIAQWERTYUIOPASDFGH\n"
    r = audit(diff_text=diff, files=["agents/foo.py"], branch="feature/x")
    # Le reason doit contenir "AKIAQW***" (pas le secret complet)
    reasons_str = " ".join(r.reasons)
    assert "AKIAQW***" in reasons_str
    assert "ASDFGH" not in reasons_str  # le suffixe ne doit PAS apparaître


# ---------------------------------------------------------------------------
# AuditResult dataclass
# ---------------------------------------------------------------------------


def test_auditresult_default_ok_true():
    r = AuditResult(ok=True)
    assert r.ok is True
    assert r.reasons == []


def test_auditresult_add_flips_ok_false():
    r = AuditResult(ok=True)
    r.add("some reason")
    assert r.ok is False
    assert r.reasons == ["some reason"]


# ---------------------------------------------------------------------------
# Combinatoire — plusieurs problèmes en même temps
# ---------------------------------------------------------------------------


def test_multiple_violations_all_reported():
    """Branch main + path founding-atoms + AKIA → 3 reasons."""
    diff = "+AKIAQWERTYUIOPASDFGH\n"
    r = audit(
        diff_text=diff,
        files=["data/founding-atoms/x.json"],
        branch="main",
    )
    assert r.ok is False
    reasons_str = " ".join(r.reasons)
    assert "forbidden branch" in reasons_str
    assert "founding-atoms" in reasons_str
    assert "aws_access_key" in reasons_str


# ---------------------------------------------------------------------------
# v0.4 gap I1 2026-05-22 — additifs G-A* (spec D1 §2.2)
# ---------------------------------------------------------------------------


def test_secret_inside_diff_minus_line_still_caught():
    """G-A1 — Secret sur ligne de suppression (préfixe `-`) doit être détecté.

    Le regex secret ne dépend pas du préfixe diff (`+`/`-`/contexte). On fige
    le comportement par test pour éviter une régression silencieuse si
    quelqu'un ajoutait un filtre `if line.startswith('+')`.
    """
    diff = (
        "diff --git a/agents/foo.py b/agents/foo.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-AWS_KEY=AKIAQWERTYUIOPASDFGH\n"
        "+AWS_KEY=removed\n"
    )
    r = audit(diff_text=diff, files=["agents/foo.py"], branch="feature/cleanup")
    assert r.ok is False
    assert any("aws_access_key" in reason for reason in r.reasons)


def test_unicode_path_in_files_handled():
    """G-A2 — Path avec caractère unicode ne crash pas l'audit.

    Vérifie qu'un fichier `docs/évolution.md` (accent) passe l'audit sans
    UnicodeError ni TypeError. Le path n'est pas dans FORBIDDEN_PATHS donc
    le résultat doit être ok=True.
    """
    r = audit(
        diff_text="+contenu\n",
        files=["docs/évolution.md", "tests/ünïcode.py"],
        branch="feature/i18n",
    )
    assert r.ok is True
    assert r.reasons == []


def test_audit_idempotent_on_same_input():
    """G-A3 — Fonction pure : 2 appels successifs identiques → mêmes ok+reasons."""
    diff = "+x\n"
    files = ["data/founding-atoms/x.json", "docs/y.md"]
    branch = "feature/idem"
    r1 = audit(diff_text=diff, files=files, branch=branch)
    r2 = audit(diff_text=diff, files=files, branch=branch)
    assert r1.ok == r2.ok
    assert r1.reasons == r2.reasons


def test_max_diff_lines_constant_is_200():
    """G-A4a — Lock-test constante MAX_DIFF_LINES = 200.

    Anti-régression : empêche qu'un changement silencieux baisse la limite
    sans validation doctrinale (plafond de commits de la constitution).
    """
    assert commit_audit.MAX_DIFF_LINES == 200


def test_max_files_constant_is_50():
    """G-A4b — Lock-test constante MAX_FILES = 50. Anti-régression."""
    assert commit_audit.MAX_FILES == 50
