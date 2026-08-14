"""Runner Lock — v0.42 (PUR, single-writer guard ; AUCUN subprocess).

Empêche **deux runners longs simultanés**. Verrou fichier confiné, créé en
exclusif (``O_CREAT|O_EXCL|O_NOFOLLOW``), avec détection de verrou périmé (stale)
déterministe via un timestamp injecté.

Le verrou doit vivre sous ``$ARAC_HOME/var/`` (ou un répertoire déclaré par
``ARAC_LOCK_ROOT``) : un verrou posé n'importe où sur le disque est un verrou
qu'on oublie, et qu'on retrouve un an plus tard en se demandant ce qu'il
bloque. N'importe jamais ``subprocess`` : un garde-fou qui lance des processus
n'est plus un garde-fou.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import arac_runtime

GENERATED_BY = "runner_lock@v0.42"
DEFAULT_LOCK_PATH = str(arac_runtime.var_dir() / "autonomy" / "long_runs" / "RUNNER.lock")
DEFAULT_TTL_SECONDS = 3600          # 1 h sans heartbeat => verrou périmé
#: Le verrou doit rester CONFINÉ. On n'énumère pas des chemins interdits (une
#: liste noire oublie toujours un cas) : on déclare le seul endroit permis.
_ALLOWED_ROOT = os.path.realpath(
    os.environ.get("ARAC_LOCK_ROOT") or str(arac_runtime.var_dir())
)


class RunnerLockError(Exception):
    """Erreur de structure / sécurité du verrou."""


def _is_forbidden(path: str) -> bool:
    """Vrai si le chemin sort de la zone permise (liens symboliques résolus)."""
    rp = os.path.realpath(path) if path else ""
    if not rp:
        return True
    return not (rp == _ALLOWED_ROOT or rp.startswith(_ALLOWED_ROOT + os.sep))


def resolve_lock_path(path: str | None = None) -> str:
    raw = path or DEFAULT_LOCK_PATH
    if _is_forbidden(raw):
        raise RunnerLockError(
            f"verrou hors de la zone permise ({_ALLOWED_ROOT}) : {raw!r}. "
            "Un verrou pose ailleurs est un verrou qu'on oublie."
        )
    return os.path.realpath(raw)


def _read_lock(path: str) -> dict | None:
    if os.path.islink(path) or not os.path.isfile(path):
        return None
    try:
        d = json.loads(open(path, encoding="utf-8").read())
        return d if isinstance(d, dict) else None
    except (ValueError, OSError):
        return None


def _is_stale(lock: dict, *, now_epoch: int, ttl_seconds: int) -> bool:
    try:
        acq = int(lock.get("acquired_at_epoch") or 0)
    except (TypeError, ValueError):
        return True
    return (now_epoch - acq) > ttl_seconds


def acquire_lock(path: str | None = None, *, run_id: str, owner: str | None = None,
                 pid: int | None = None, now_epoch: int, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> dict:
    """Acquiert le verrou (atomique). Si un verrou périmé existe, le récupère.
    Retourne {acquired, reason, reclaimed, lock}. Aucun subprocess."""
    lp = resolve_lock_path(path)
    os.makedirs(os.path.dirname(lp), exist_ok=True)
    payload = {
        "schema_version": "v0.42", "generated_by": GENERATED_BY,
        "run_id": run_id, "owner": owner or run_id,
        "pid": int(pid) if pid is not None else os.getpid(),
        "acquired_at_epoch": int(now_epoch), "ttl_seconds": int(ttl_seconds),
    }
    blob = json.dumps(payload, ensure_ascii=False, indent=2)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(lp, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(blob)
        return {"acquired": True, "reason": "lock_created", "reclaimed": False, "lock": payload}
    except FileExistsError:
        existing = _read_lock(lp)
        if existing is None:
            return {"acquired": False, "reason": "lock_unreadable", "reclaimed": False, "lock": None}
        if existing.get("run_id") == run_id:
            return {"acquired": True, "reason": "already_owned", "reclaimed": False, "lock": existing}
        if _is_stale(existing, now_epoch=now_epoch, ttl_seconds=ttl_seconds):
            # verrou périmé : on le récupère (réécriture atomique via remplacement).
            tmp = lp + ".tmp"
            tfd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(tfd, "w", encoding="utf-8") as fh:
                fh.write(blob)
            os.replace(tmp, lp)
            return {"acquired": True, "reason": "stale_reclaimed", "reclaimed": True, "lock": payload}
        return {"acquired": False, "reason": "locked_by_other", "reclaimed": False, "lock": existing}


def release_lock(path: str | None = None, *, run_id: str) -> dict:
    """Libère le verrou — SEUL le propriétaire (run_id) peut libérer."""
    lp = resolve_lock_path(path)
    existing = _read_lock(lp)
    if existing is None:
        return {"released": False, "reason": "no_lock"}
    if existing.get("run_id") != run_id:
        return {"released": False, "reason": "not_owner"}
    try:
        os.unlink(lp)
        return {"released": True, "reason": "released"}
    except OSError as exc:
        return {"released": False, "reason": f"unlink_failed:{type(exc).__name__}"}


def lock_status(path: str | None = None, *, now_epoch: int | None = None,
                ttl_seconds: int = DEFAULT_TTL_SECONDS) -> dict:
    lp = resolve_lock_path(path)
    existing = _read_lock(lp)
    if existing is None:
        return {"locked": False, "stale": False, "owner": None}
    stale = _is_stale(existing, now_epoch=now_epoch, ttl_seconds=ttl_seconds) if now_epoch is not None else None
    return {"locked": True, "stale": stale, "owner": existing.get("owner"),
            "run_id": existing.get("run_id"), "pid": existing.get("pid"),
            "acquired_at_epoch": existing.get("acquired_at_epoch")}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Runner Lock — v0.42 (single-writer guard).")
    parser.add_argument("--path")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--now-epoch", type=int)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        st = lock_status(args.path, now_epoch=args.now_epoch)
    except RunnerLockError as exc:
        print(f"[runner-lock] refus : {exc}", file=sys.stderr)
        return 2
    print(json.dumps(st, ensure_ascii=False, indent=2) if args.json else
          f"locked={st['locked']} stale={st.get('stale')} owner={st.get('owner')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
