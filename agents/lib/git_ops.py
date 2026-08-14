"""Helpers git asynchrones pour le flux gate auditor — Phase D.2.

Tous les helpers délèguent à `git` via `asyncio.create_subprocess_exec` (sans
shell) sur `cwd=arac_runtime.home()` — la racine d'installation, jamais un
chemin en dur. Retournent un dict
`{ok: bool, stdout: str, stderr: str, exit_code: int}` ou des types
spécialisés (str/list[str]) selon le helper.

Pré-requis : git refuse d'opérer sur un dépôt dont il n'est pas propriétaire.
L'installation étant partagée entre root (qui écrit) et le compte de service
(qui lit et commite), il faut le déclarer une fois :

    git config --global --add safe.directory "$ARAC_HOME"

Sans cela tous les helpers ci-dessous rendent `ok=False` avec un stderr
« dubious ownership » — panne fréquente et déroutante à la première
installation.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import arac_runtime

#: Le dépôt sur lequel les agents opèrent : l'installation elle-même.
#: `ARAC_REPO_CWD` permet de viser un autre dépôt (tests, worktree).
_REPO_CWD = os.environ.get("ARAC_REPO_CWD") or str(arac_runtime.home())


async def _run_git(*args: str, timeout: float = 30.0) -> dict[str, Any]:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=_REPO_CWD,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return {"ok": False, "stdout": "", "stderr": "timeout", "exit_code": -1}
    return {
        "ok": proc.returncode == 0,
        "stdout": out.decode(errors="replace"),
        "stderr": err.decode(errors="replace"),
        "exit_code": proc.returncode or 0,
    }


async def status_porcelain() -> list[str]:
    """Liste les fichiers modifiés/ajoutés/supprimés via `git status --porcelain`.

    Format retourné : liste de chemins (sans le préfixe XY). Liste vide si
    working tree propre.
    """
    r = await _run_git("status", "--porcelain")
    if not r["ok"]:
        return []
    files: list[str] = []
    for line in r["stdout"].splitlines():
        if len(line) < 4:
            continue
        # Format : "XY path" ou "XY orig -> new" pour rename. On garde le chemin
        # final (après " -> " si présent).
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        # Strip quotes éventuels pour chemins avec espaces/unicode
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        files.append(path)
    return files


async def intent_to_add_untracked() -> list[str]:
    """`git add -N <untracked>` — rend les fichiers nouveaux visibles à `git diff`.

    Sans ça, les nouveaux fichiers créés par claude (untracked) sont absents
    du diff et passeraient sous le radar du gate auditor — failure mode
    critique observé Phase D.2 test reject (mission bab22208, fichier
    contenant un faux AKIA approuvé à tort sur diff vide).

    Réversible : `git stash push -u` clean le tree incluant l'intent-to-add,
    `git reset HEAD <path>` annule la marque ponctuellement.

    Retourne la liste des fichiers marqués (pour log / debug).
    """
    r = await _run_git("ls-files", "--others", "--exclude-standard", "-z")
    if not r["ok"]:
        return []
    untracked = [p for p in r["stdout"].split("\0") if p]
    if not untracked:
        return []
    await _run_git("add", "-N", "--", *untracked)
    return untracked


async def diff_text(staged: bool = False, max_bytes: int = 50_000) -> str:
    """Renvoie `git diff` (ou `git diff --staged`). Tronqué à max_bytes.

    Pour inclure les fichiers untracked, appeler `intent_to_add_untracked()`
    AVANT — sinon les nouveaux fichiers seront absents du diff.
    """
    args = ["diff"]
    if staged:
        args.append("--staged")
    r = await _run_git(*args)
    out = r["stdout"]
    if len(out.encode("utf-8")) > max_bytes:
        b = out.encode("utf-8")[:max_bytes]
        out = b.decode("utf-8", errors="replace") + "\n... [truncated]"
    return out


async def diff_stat(staged: bool = False) -> str:
    args = ["diff", "--stat"]
    if staged:
        args.append("--staged")
    r = await _run_git(*args)
    return r["stdout"]


async def current_branch() -> str | None:
    r = await _run_git("rev-parse", "--abbrev-ref", "HEAD")
    return r["stdout"].strip() if r["ok"] else None


async def head_sha(short: bool = True) -> str | None:
    args = ["rev-parse"]
    if short:
        args.append("--short")
    args.append("HEAD")
    r = await _run_git(*args)
    return r["stdout"].strip() if r["ok"] else None


async def add_all() -> dict[str, Any]:
    """`git add -A` — stage toutes les modifs (incluant untracked, hors .gitignore).

    DÉPRÉCIÉ pour le flux developer (Phase E.2) : le commit du developer passe
    désormais par `add_paths()` (stage UNIQUEMENT les fichiers du diff audité,
    jamais un `-A` aveugle). Conservé pour compat/outillage hors chemin sensible.
    """
    return await _run_git("add", "-A")


async def add_paths(paths: list[str]) -> dict[str, Any]:
    """`git add -- <paths>` — stage UNIQUEMENT les chemins listés (PAS de `-A`).

    Utilisé par le garde-fou developer : on ne stage que les fichiers qui ont été
    présentés à l'auditeur (le diff audité), jamais un fichier apparu APRÈS l'audit.
    `--` sépare les chemins des options (anti-injection d'un chemin commençant par
    `-`). Renvoie un échec explicite si `paths` est vide (rien à committer).
    """
    cleaned = [p for p in paths if p and p.strip()]
    if not cleaned:
        return {"ok": False, "stdout": "", "stderr": "add_paths: empty path list",
                "exit_code": 1}
    return await _run_git("add", "--", *cleaned)


async def commit(
    message: str,
    author_name: str = "ARAC Developer Agent",
    author_email: str = "arac-developer@noreply.local",
) -> dict[str, Any]:
    """Crée un commit avec identité agent. Échoue si rien de staged."""
    return await _run_git(
        "-c", f"user.name={author_name}",
        "-c", f"user.email={author_email}",
        "commit", "-m", message,
        timeout=60.0,
    )


async def push(branch: str, remote: str = "origin") -> dict[str, Any]:
    """Push direct (pas force). Échoue si branche divergente."""
    return await _run_git("push", remote, branch, timeout=120.0)


async def stash_push(message: str) -> dict[str, Any]:
    """Sauvegarde les modifs (incluant untracked via -u) en stash, working tree clean.

    Hack git : `git stash -u` refuse de stasher quand un fichier est en
    intent-to-add (`A ` dans porcelain) — cf "Entry X not uptodate. Cannot
    merge.". On reset d'abord l'index pour annuler les intent-to-add, puis
    on stash normalement.
    """
    reset_r = await _run_git("reset", "HEAD")
    if not reset_r["ok"]:
        # Best-effort : on continue quand même, stash pourra encore réussir
        # si l'index est déjà clean.
        pass
    return await _run_git("stash", "push", "-u", "-m", message)


async def stash_list() -> str:
    r = await _run_git("stash", "list")
    return r["stdout"]
