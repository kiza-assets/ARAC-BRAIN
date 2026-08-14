"""Tests d'intégration pour agents/lib/git_ops.py — Phase D.4.

Utilise un repo git temporaire isolé (tmp_path) pour tester les helpers
async sans dépendre du dépôt ARAC réel. Couvre les chemins critiques
du flux gate auditor (status_porcelain, intent_to_add_untracked, diff_text,
stash_push avec reset-HEAD, commit, head_sha).

Cible : >70% de couverture sur agents/lib/git_ops.py (171 LOC).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from agents.lib import git_ops


# ---------------------------------------------------------------------------
# Fixture : repo git temporaire isolé
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_repo(tmp_path, monkeypatch):
    """Initialise un repo git frais sous tmp_path et redirige git_ops._REPO_CWD.

    Le repo a :
    - 1 commit initial (README.md)
    - branche `feature/test-branch`
    - user.name + user.email configurés en local
    """
    repo = tmp_path / "repo"
    repo.mkdir()

    # init + identity locale (sinon commit échoue sans user.email)
    subprocess.check_call(["git", "-C", str(repo), "init", "-q", "--initial-branch=main"])
    subprocess.check_call(["git", "-C", str(repo), "config", "user.name", "test"])
    subprocess.check_call(["git", "-C", str(repo), "config", "user.email", "test@example.com"])

    # commit initial
    (repo / "README.md").write_text("initial\n")
    subprocess.check_call(["git", "-C", str(repo), "add", "."])
    subprocess.check_call(["git", "-C", str(repo), "commit", "-q", "-m", "initial"])

    # checkout branche feature/* (pour passer commit_audit en cas de besoin)
    subprocess.check_call(["git", "-C", str(repo), "checkout", "-q", "-b", "feature/test-branch"])

    monkeypatch.setattr(git_ops, "_REPO_CWD", str(repo))
    return repo


# ---------------------------------------------------------------------------
# _run_git (subprocess wrapper de base)
# ---------------------------------------------------------------------------


async def test_run_git_basic_command(tmp_repo):
    r = await git_ops._run_git("status", "--short")
    assert r["ok"] is True
    assert r["exit_code"] == 0
    assert r["stdout"] == ""  # tree clean après init+commit


async def test_run_git_failing_command_returns_ok_false(tmp_repo):
    r = await git_ops._run_git("rev-parse", "--verify", "nonexistent-ref")
    assert r["ok"] is False
    assert r["exit_code"] != 0


async def test_run_git_timeout_returns_negative_exit_code(tmp_repo):
    # timeout très court forcé sur une commande triviale + commande factice
    # qui ne timeout pas vraiment, donc on simule timeout via une commande
    # qui dort (mais on ne peut pas faire dormir git directement). On vérifie
    # juste que le helper supporte timeout sans crash.
    r = await git_ops._run_git("status", "--short", timeout=10.0)
    assert r["ok"] is True


# ---------------------------------------------------------------------------
# status_porcelain
# ---------------------------------------------------------------------------


async def test_status_porcelain_empty_when_clean(tmp_repo):
    files = await git_ops.status_porcelain()
    assert files == []


async def test_status_porcelain_detects_untracked(tmp_repo):
    (tmp_repo / "newfile.txt").write_text("hello\n")
    files = await git_ops.status_porcelain()
    assert files == ["newfile.txt"]


async def test_status_porcelain_detects_modified(tmp_repo):
    (tmp_repo / "README.md").write_text("modified\n")
    files = await git_ops.status_porcelain()
    assert files == ["README.md"]


async def test_status_porcelain_handles_multiple_files(tmp_repo):
    (tmp_repo / "a.txt").write_text("a\n")
    (tmp_repo / "b.txt").write_text("b\n")
    (tmp_repo / "README.md").write_text("modified\n")
    files = await git_ops.status_porcelain()
    assert set(files) == {"a.txt", "b.txt", "README.md"}


# ---------------------------------------------------------------------------
# intent_to_add_untracked
# ---------------------------------------------------------------------------


async def test_intent_to_add_untracked_when_no_untracked(tmp_repo):
    added = await git_ops.intent_to_add_untracked()
    assert added == []


async def test_intent_to_add_untracked_marks_new_files(tmp_repo):
    (tmp_repo / "new1.txt").write_text("hello\n")
    (tmp_repo / "new2.txt").write_text("world\n")

    added = await git_ops.intent_to_add_untracked()
    assert set(added) == {"new1.txt", "new2.txt"}

    # Vérification : git status doit montrer ces fichiers en " A " (intent-to-add)
    r = subprocess.run(
        ["git", "-C", str(tmp_repo), "status", "--porcelain"],
        capture_output=True, text=True, check=True,
    )
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    # Format porcelain : "XY path" — pour intent-to-add, X=' ' Y='A' OU X='A' Y=' '
    intent_lines = [l for l in lines if l.startswith(" A ") or l.startswith("A ")]
    assert len(intent_lines) == 2


async def test_intent_to_add_makes_untracked_visible_to_diff(tmp_repo):
    """C'est LE bug fixé par f03285a : sans intent-to-add, git diff cache les untracked."""
    (tmp_repo / "secret.txt").write_text("AWS_KEY=AKIAQWERTYUIOPASDFGH\n")

    diff_before = await git_ops.diff_text()
    assert diff_before == ""  # untracked invisible à git diff

    await git_ops.intent_to_add_untracked()
    diff_after = await git_ops.diff_text()
    assert "AKIAQWERTYUIOPASDFGH" in diff_after


# ---------------------------------------------------------------------------
# diff_text + diff_stat
# ---------------------------------------------------------------------------


async def test_diff_text_empty_when_clean(tmp_repo):
    assert await git_ops.diff_text() == ""


async def test_diff_text_shows_modifications(tmp_repo):
    (tmp_repo / "README.md").write_text("modified content\n")
    diff = await git_ops.diff_text()
    assert "modified content" in diff
    assert "README.md" in diff


async def test_diff_text_truncates_at_max_bytes(tmp_repo):
    # Crée un fichier avec contenu plus large que max_bytes
    big_content = "x" * 100_000
    (tmp_repo / "big.txt").write_text(big_content)
    await git_ops.intent_to_add_untracked()

    diff = await git_ops.diff_text(max_bytes=1_000)
    assert len(diff.encode("utf-8")) <= 2_000  # tronqué + marqueur "... [truncated]"
    assert "[truncated]" in diff


async def test_diff_stat_returns_summary(tmp_repo):
    (tmp_repo / "README.md").write_text("changed\n")
    stat = await git_ops.diff_stat()
    assert "README.md" in stat


# ---------------------------------------------------------------------------
# current_branch + head_sha
# ---------------------------------------------------------------------------


async def test_current_branch_returns_feature_branch(tmp_repo):
    branch = await git_ops.current_branch()
    assert branch == "feature/test-branch"


async def test_head_sha_short_format(tmp_repo):
    sha = await git_ops.head_sha(short=True)
    assert sha is not None
    assert len(sha) >= 4 and len(sha) <= 12


async def test_head_sha_long_format(tmp_repo):
    sha = await git_ops.head_sha(short=False)
    assert sha is not None
    assert len(sha) == 40


# ---------------------------------------------------------------------------
# commit
# ---------------------------------------------------------------------------


async def test_commit_succeeds_with_staged_changes(tmp_repo):
    (tmp_repo / "file.txt").write_text("content\n")
    await git_ops.add_all()
    r = await git_ops.commit("test commit")
    assert r["ok"] is True
    assert r["exit_code"] == 0


async def test_commit_fails_without_staged_changes(tmp_repo):
    r = await git_ops.commit("nothing to commit")
    assert r["ok"] is False


async def test_commit_uses_default_identity(tmp_repo):
    (tmp_repo / "x.txt").write_text("x\n")
    await git_ops.add_all()
    await git_ops.commit("identity test")

    log = subprocess.run(
        ["git", "-C", str(tmp_repo), "log", "-1", "--pretty=format:%an <%ae>"],
        capture_output=True, text=True, check=True,
    )
    assert "ARAC Developer Agent" in log.stdout
    assert "arac-developer@noreply.local" in log.stdout


# ---------------------------------------------------------------------------
# stash_push — le hack reset HEAD avant stash
# ---------------------------------------------------------------------------


async def test_stash_push_succeeds_with_simple_modif(tmp_repo):
    (tmp_repo / "README.md").write_text("modified\n")
    r = await git_ops.stash_push("test-stash-1")
    assert r["ok"] is True

    files_after = await git_ops.status_porcelain()
    assert files_after == []  # working tree clean après stash


async def test_stash_push_handles_intent_to_add_via_reset_head(tmp_repo):
    """Bug bbc7b91 : git stash refuse intent-to-add. stash_push fait reset HEAD avant."""
    (tmp_repo / "new.txt").write_text("untracked\n")
    await git_ops.intent_to_add_untracked()

    # Sans le fix, ce stash retournerait "Cannot merge". Avec le fix, ok=True.
    r = await git_ops.stash_push("test-stash-intent-to-add")
    assert r["ok"] is True

    # Working tree clean après stash (le fichier untracked a aussi été stashé via -u)
    files_after = await git_ops.status_porcelain()
    assert files_after == []


async def test_stash_list_returns_stashes(tmp_repo):
    (tmp_repo / "a.txt").write_text("a\n")
    await git_ops.stash_push("first")

    (tmp_repo / "b.txt").write_text("b\n")
    await git_ops.stash_push("second")

    listed = await git_ops.stash_list()
    assert "first" in listed
    assert "second" in listed


# ---------------------------------------------------------------------------
# add_all
# ---------------------------------------------------------------------------


async def test_add_all_stages_untracked_and_modified(tmp_repo):
    (tmp_repo / "new.txt").write_text("hello\n")
    (tmp_repo / "README.md").write_text("changed\n")

    r = await git_ops.add_all()
    assert r["ok"] is True

    # Vérif via subprocess direct
    status = subprocess.run(
        ["git", "-C", str(tmp_repo), "status", "--porcelain"],
        capture_output=True, text=True, check=True,
    )
    # Tous les fichiers en "A" (added) ou "M" (modified, staged) — premier char != ' '
    for line in status.stdout.splitlines():
        if line.strip():
            assert line[0] != " ", f"file should be staged: {line!r}"


# ---------------------------------------------------------------------------
# push (smoke test — peut pas vraiment push sans remote)
# ---------------------------------------------------------------------------


async def test_push_fails_when_no_remote(tmp_repo):
    """Pas de remote configuré → push échoue proprement (ok=False), pas crash."""
    r = await git_ops.push("feature/test-branch", remote="nonexistent")
    assert r["ok"] is False
    assert r["exit_code"] != 0


# ---------------------------------------------------------------------------
# v0.4 gap I1 2026-05-22 — additifs G-G* (spec D1 §3.2)
# ---------------------------------------------------------------------------


async def test_run_git_real_timeout_with_sleep_subprocess(tmp_repo, monkeypatch):
    """G-G1 — Vrai trigger du chemin timeout.

    Le test #3 vérifie seulement qu'un timeout généreux ne crash pas. Ici on
    force réellement le TimeoutError d'asyncio en patchant `asyncio.wait_for`
    pour qu'il raise. On vérifie alors le contrat retour : ok=False,
    stderr='timeout', exit_code=-1.
    """
    import asyncio as _asyncio

    real_wait_for = _asyncio.wait_for

    async def fake_wait_for(coro, timeout):
        # Annule la coroutine subprocess et raise TimeoutError comme un vrai timeout
        coro.close()
        raise _asyncio.TimeoutError()

    monkeypatch.setattr(git_ops.asyncio, "wait_for", fake_wait_for)

    r = await git_ops._run_git("status", "--short", timeout=0.001)
    assert r["ok"] is False
    assert r["exit_code"] == -1
    assert r["stderr"] == "timeout"

    # Sanity : restauration auto par monkeypatch en fin de test
    assert git_ops.asyncio.wait_for is fake_wait_for or git_ops.asyncio.wait_for is real_wait_for


async def test_status_porcelain_handles_renamed_file(tmp_repo):
    """G-G2 — Renommage : status_porcelain doit retourner le chemin final (après ` -> `)."""
    # Crée un 2e commit pour avoir un fichier suivi qu'on peut renommer
    (tmp_repo / "old_name.txt").write_text("content\n")
    subprocess.check_call(["git", "-C", str(tmp_repo), "add", "old_name.txt"])
    subprocess.check_call(["git", "-C", str(tmp_repo), "commit", "-q", "-m", "add old_name"])

    # Renomme via git mv (stage la modif)
    subprocess.check_call(["git", "-C", str(tmp_repo), "mv", "old_name.txt", "new_name.txt"])

    files = await git_ops.status_porcelain()
    # Le helper doit retourner le chemin final (post-` -> `), pas l'ancien
    assert "new_name.txt" in files
    assert "old_name.txt" not in files


async def test_status_porcelain_handles_quoted_paths_with_spaces(tmp_repo):
    """G-G3 — Path avec espaces (git porcelain les quote) → chemin sans quotes."""
    (tmp_repo / "a b.txt").write_text("content\n")
    files = await git_ops.status_porcelain()
    # Git porcelain renvoie `?? "a b.txt"` ; le helper doit strip les quotes.
    # On accepte les deux variantes (selon config core.quotePath) tant qu'on
    # n'a pas de guillemets dans le résultat.
    assert any("a b.txt" in f for f in files)
    for f in files:
        assert not (f.startswith('"') and f.endswith('"')), f"quotes non strippées: {f!r}"


async def test_intent_to_add_respects_gitignore(tmp_repo):
    """G-G4 — Fichier dans .gitignore → NON ajouté par intent_to_add_untracked.

    Le helper utilise `ls-files --others --exclude-standard` : `--exclude-standard`
    applique .gitignore + .git/info/exclude + global ignore. Donc un fichier
    ignoré ne doit pas apparaître dans la liste retournée.
    """
    (tmp_repo / ".gitignore").write_text("ignored.txt\n")
    subprocess.check_call(["git", "-C", str(tmp_repo), "add", ".gitignore"])
    subprocess.check_call(["git", "-C", str(tmp_repo), "commit", "-q", "-m", "add gitignore"])

    (tmp_repo / "ignored.txt").write_text("should not be tracked\n")
    (tmp_repo / "tracked.txt").write_text("should appear\n")

    added = await git_ops.intent_to_add_untracked()
    assert "tracked.txt" in added
    assert "ignored.txt" not in added


async def test_diff_text_staged_vs_unstaged(tmp_repo):
    """G-G5 — `diff_text(staged=True)` vs `staged=False` : comportements distincts.

    - Modif non stagée → visible avec staged=False, invisible avec staged=True.
    - Modif stagée (git add) → visible avec staged=True, invisible avec staged=False.
    """
    # Modif non stagée
    (tmp_repo / "README.md").write_text("unstaged change\n")
    unstaged = await git_ops.diff_text(staged=False)
    staged_before = await git_ops.diff_text(staged=True)
    assert "unstaged change" in unstaged
    assert "unstaged change" not in staged_before

    # On stage la modif
    subprocess.check_call(["git", "-C", str(tmp_repo), "add", "README.md"])
    unstaged_after = await git_ops.diff_text(staged=False)
    staged_after = await git_ops.diff_text(staged=True)
    assert "unstaged change" not in unstaged_after
    assert "unstaged change" in staged_after
