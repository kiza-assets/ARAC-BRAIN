"""Kill Switch — v0.21 (PUR, lecture seule). Claude Code CLI only.

Mécanisme d'ARRÊT du night-shift : la présence d'un fichier « kill switch » interdit
le démarrage ou stoppe entre deux cycles. **Ne supprime JAMAIS le kill switch
automatiquement** (un humain décide de le retirer). Aucune écriture, aucun réseau,
aucun subprocess.

Emplacements AUTORISÉS du fichier kill switch :
  - sous le repo `var/` (défaut : `var/autonomy/KILL_SWITCH`) ;
  - sous le répertoire temporaire système (`tempfile.gettempdir()`, ex. `/tmp`).
Tout autre chemin (ex. `/etc/...`, `docs/...`, `scripts/...`) ou tout traversal `..`
est REFUSÉ (ValueError) — on ne laisse pas pointer le kill switch n'importe où.

Usage :
    from kill_switch import is_active, resolve_switch_path, DEFAULT_KILL_SWITCH
"""
from __future__ import annotations

import os
import tempfile

import arac_runtime

DEFAULT_KILL_SWITCH = str(arac_runtime.var_dir() / "autonomy" / "KILL_SWITCH")
_REPO_VAR = str(arac_runtime.var_dir())


def resolve_switch_path(path: str | None = None) -> str:
    """Valide et retourne le chemin du kill switch. ValueError si non autorisé.

    Refuse le traversal `..` et tout emplacement hors `repo/var/` ou tempdir système."""
    raw = path or DEFAULT_KILL_SWITCH
    if ".." in str(raw).replace("\\", "/").split("/"):
        raise ValueError(f"kill switch : traversal '..' interdit — {raw!r}")
    absp = os.path.normpath(os.path.abspath(raw))
    repo_var = os.path.normpath(_REPO_VAR)
    tmp = os.path.normpath(tempfile.gettempdir())
    allowed = (absp == repo_var or absp.startswith(repo_var + os.sep)
               or absp == tmp or absp.startswith(tmp + os.sep))
    if not allowed:
        raise ValueError(
            f"kill switch : emplacement non autorisé {raw!r} "
            f"(attendu : sous repo var/ ou {tmp}/)")
    return absp


def is_active(path: str | None = None) -> bool:
    """True si le fichier kill switch existe à un emplacement autorisé.

    Un chemin non autorisé lève ValueError (fail-closed : on ne devine pas)."""
    return os.path.isfile(resolve_switch_path(path))


def status(path: str | None = None) -> dict:
    """État structuré du kill switch (sans jamais le supprimer)."""
    resolved = resolve_switch_path(path)
    return {"path": resolved, "active": os.path.isfile(resolved),
            "auto_removed": False}
