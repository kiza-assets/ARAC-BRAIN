"""Control Center — collecteurs système (READ-ONLY strict via allowlist).

Doctrine : OBSERVE FIRST. DO NOT CONTROL. + READ ONLY.

Toute exécution de commande système passe par ``_run_readonly(cmd_list)`` qui
REFUSE :
  1. tout binaire hors de l'ALLOWLIST {git, df, ss, tmux, systemctl} ;
  2. tout argument contenant un verbe mutateur (start, stop, restart, enable,
     disable, kill, rm, reload, mask, ...) ;
  3. ``systemctl`` avec un sous-commande autre que les sous-commandes de LECTURE
     autorisées (is-active, status, show, list-*).

Chaque subprocess a un timeout (5 s), capture stderr, et ne doit jamais
laisser fuiter un secret dans sa sortie (les commandes de l'allowlist ne lisent
ni ``.env`` ni token).

Les lectures de pseudo-fichiers (``/proc/loadavg``) se font directement par
``open()`` — pas de subprocess, donc pas de surface mutatrice.

Aucune sonde réseau SORTANTE : ``ssh_tunnel_status`` lit seulement l'état du
listener LOCAL (``ss -ltn``), il ne contacte jamais le Mac (pas de ssh sortant,
pas d'effet de bord distant).
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

# ============================================================================
# Allowlist & garde-fous
# ============================================================================

# Seuls ces binaires peuvent être exécutés. Tout autre → refus immédiat.
_ALLOWED_BINARIES = frozenset({"git", "df", "ss", "tmux", "systemctl"})

# Verbes mutateurs interdits N'IMPORTE OÙ dans les arguments. Si l'un d'eux
# apparaît comme token d'argument, la commande est refusée (défense en
# profondeur, même pour un binaire de l'allowlist).
_MUTATING_VERBS = frozenset(
    {
        "start",
        "stop",
        "restart",
        "reload",
        "enable",
        "disable",
        "kill",
        "rm",
        "mask",
        "unmask",
        "edit",
        "set-property",
        "daemon-reload",
        "reset-failed",
    }
)

# Sous-commandes systemctl autorisées (lecture seule). systemctl est le seul
# binaire de l'allowlist dont le 1er argument est un sous-verbe à filtrer.
# NOTE : 'show' et 'cat' RETIRÉS (red-team V1.7B) — show expose les variables
# d'environnement inline des unit files ; cat expose le fichier unit complet.
# Réintroduire uniquement si un collecteur futur en a besoin, avec test de
# non-fuite des secrets d'env.
_SYSTEMCTL_READ_SUBCOMMANDS = frozenset(
    {"is-active", "is-enabled", "is-failed", "list-units", "list-timers"}
)

# Sous-commandes git autorisées (lecture seule). git peut muter le repo
# (push/commit/add/merge/...) — on n'autorise donc QUE les sous-commandes de
# lecture utilisées par les collecteurs. Tout le reste (push, commit, reset...)
# est refusé même si le verbe n'est pas dans _MUTATING_VERBS — défense en
# profondeur par allowlist positive.
# NOTE : 'show', 'branch', 'status' RETIRÉS (red-team V1.7B) — show expose le
# contenu de n'importe quel fichier du dépôt via 'git show HEAD:<path>'.
# Réintroduire uniquement si un collecteur futur en a besoin.
_GIT_READ_SUBCOMMANDS = frozenset(
    {"rev-parse", "describe", "log", "tag", "for-each-ref"}
)

# Timeout uniforme appliqué à chaque subprocess (secondes).
_TIMEOUT_SEC = 5


class CommandNotAllowed(ValueError):
    """Levée par ``_run_readonly`` quand une commande viole l'allowlist."""


def _assert_readonly(cmd_list: list[str]) -> None:
    """Valide ``cmd_list`` contre l'allowlist. Lève ``CommandNotAllowed`` sinon.

    Règles (toutes doivent passer) :
      - liste non vide ;
      - binaire (``cmd_list[0]``) dans ``_ALLOWED_BINARIES`` ;
      - aucun argument n'est un verbe mutateur ``_MUTATING_VERBS`` ;
      - si binaire == ``systemctl`` : le 1er sous-argument doit appartenir à
        ``_SYSTEMCTL_READ_SUBCOMMANDS`` (sinon refus — couvre les sous-verbes
        de lecture comme ``list-units`` via le préfixe ``list-``) ;
      - si binaire == ``git`` : le 1er sous-argument doit appartenir à
        ``_GIT_READ_SUBCOMMANDS`` (allowlist positive — refuse push/commit/...).
    """
    if not cmd_list:
        raise CommandNotAllowed("commande vide refusée")

    binary = cmd_list[0]
    if binary not in _ALLOWED_BINARIES:
        raise CommandNotAllowed(f"binaire hors allowlist : {binary!r}")

    args = cmd_list[1:]

    # Verbe mutateur n'importe où dans les arguments → refus.
    for tok in args:
        low = tok.lower()
        if low in _MUTATING_VERBS:
            raise CommandNotAllowed(f"verbe mutateur interdit : {tok!r}")

    # systemctl : seul un sous-verbe de LECTURE est toléré.
    if binary == "systemctl":
        if not args:
            raise CommandNotAllowed("systemctl sans sous-commande refusé")
        sub = args[0].lower()
        is_read = sub in _SYSTEMCTL_READ_SUBCOMMANDS or sub.startswith("list-")
        if not is_read:
            raise CommandNotAllowed(
                f"systemctl autorisé en lecture uniquement, refusé : {sub!r}"
            )

    # git : allowlist positive de sous-commandes de lecture seule.
    if binary == "git":
        if not args:
            raise CommandNotAllowed("git sans sous-commande refusé")
        sub = args[0].lower()
        if sub not in _GIT_READ_SUBCOMMANDS:
            raise CommandNotAllowed(
                f"git autorisé en lecture uniquement, refusé : {sub!r}"
            )


def _run_readonly(cmd_list: list[str]) -> dict[str, Any]:
    """Exécute une commande de l'allowlist en lecture seule, avec timeout.

    Retourne ::

        {"ok": True,  "stdout": <str>, "stderr": <str>, "returncode": <int>}
        {"ok": False, "error": <str>}        # refus allowlist / timeout / exec

    Ne lève jamais : tout échec (refus, timeout, binaire introuvable) est
    converti en dict ``{"ok": False, "error": ...}`` — résilience cockpit.
    """
    try:
        _assert_readonly(cmd_list)
    except CommandNotAllowed as exc:
        return {"ok": False, "error": f"not_allowed: {exc}"}

    try:
        proc = subprocess.run(  # noqa: S603 — cmd_list validé par _assert_readonly
            cmd_list,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SEC,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    except FileNotFoundError:
        return {"ok": False, "error": "binary_not_found"}
    except Exception as exc:  # pragma: no cover — garde-fou ultime
        return {"ok": False, "error": f"{type(exc).__name__}"}

    return {
        "ok": True,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "returncode": proc.returncode,
    }


# ============================================================================
# API publique
# ============================================================================


def git_version() -> dict[str, Any]:
    """État de version Git du repo.

    Forme nominale ::

        {
            "branch": <str>,
            "head_commit": <str>,        # git rev-parse HEAD
            "describe": <str>,           # git describe --tags --always
            "last_commits": [<str>, ...] # git log -n 5 --oneline
        }

    Champs indisponibles → ``None`` (branch/head_commit/describe) ou ``[]``
    (last_commits). Si Git est totalement injoignable, tous les champs sont
    dégradés mais la fonction ne lève pas.
    """
    branch_r = _run_readonly(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    head_r = _run_readonly(["git", "rev-parse", "HEAD"])
    describe_r = _run_readonly(["git", "describe", "--tags", "--always"])
    log_r = _run_readonly(["git", "log", "-n", "5", "--oneline"])

    last_commits: list[str] = []
    if log_r.get("ok") and log_r.get("stdout"):
        last_commits = [ln for ln in log_r["stdout"].splitlines() if ln.strip()]

    return {
        "branch": branch_r.get("stdout") if branch_r.get("ok") else None,
        "head_commit": head_r.get("stdout") if head_r.get("ok") else None,
        "describe": describe_r.get("stdout") if describe_r.get("ok") else None,
        "last_commits": last_commits,
    }


def server_health() -> dict[str, Any]:
    """Santé serveur : loadavg, disque /opt, état (lecture) du service arac-api.

    Forme nominale ::

        {
            "loadavg": {"1m": float, "5m": float, "15m": float} | None,
            "disk": <str> | None,          # sortie brute `df -h /opt`
            "arac_api_status": <str>,      # active / inactive / failed / unknown
        }

    ``arac_api_status`` est obtenu via ``systemctl is-active arac-api`` — LECTURE
    SEULE, jamais start/stop/restart. Tout échec dégrade le champ concerné sans
    lever.
    """
    # loadavg : lecture directe du pseudo-fichier (pas de subprocess).
    loadavg: dict[str, float] | None
    try:
        with open("/proc/loadavg", encoding="utf-8") as fh:
            parts = fh.read().split()
        loadavg = {
            "1m": float(parts[0]),
            "5m": float(parts[1]),
            "15m": float(parts[2]),
        }
    except Exception:
        loadavg = None

    # disque : df -h /opt (lecture).
    disk_r = _run_readonly(["df", "-h", "/opt"])
    disk = disk_r.get("stdout") if disk_r.get("ok") else None

    # statut service : systemctl is-active (lecture seule, --quiet n'émet rien
    # sur stdout mais positionne le returncode ; on lit le stdout de is-active
    # sans --quiet pour avoir le label 'active'/'inactive'/'failed').
    # DE QUEL CERVEAU CE COCKPIT EST-IL LE COCKPIT ?
    #
    # Cette ligne demandait l'état de « arac-api », écrit en dur, sans jamais
    # poser la question. Sur cette machine, deux cockpits d'ESSAI rapportaient
    # ainsi la santé de l'unité de PRODUCTION : trois tuiles vertes qui ne
    # parlaient pas du cerveau qu'on regardait. Un diagnostic qui ment en
    # disant « tout va bien » est pire qu'une absence de diagnostic — c'est
    # exactement la panne de l'incident d'origine, où /healthz répondait 200
    # servi par l'usurpateur.
    #
    # L'unité du cockpit pose ARAC_UNIT_API. Sans elle, on ne devine pas : on
    # rend « inconnu », qui est vrai, plutôt que l'état du voisin, qui est
    # crédible et faux.
    unite_api = (os.environ.get("ARAC_UNIT_API") or "").strip()
    if not unite_api:
        arac_api_status = "unknown"
    else:
        status_r = _run_readonly(["systemctl", "is-active", unite_api])
        if status_r.get("ok"):
            arac_api_status = status_r.get("stdout") or "unknown"
        else:
            arac_api_status = "unknown"

    return {
        "loadavg": loadavg,
        "disk": disk,
        "arac_api_status": arac_api_status,
    }


def tmux_sessions() -> list[str]:
    """Liste des sessions tmux (``tmux ls``).

    Retourne une liste de lignes (une par session). Si tmux est absent, n'a
    aucune session, ou échoue, retourne ``[]`` — jamais d'exception.
    """
    result = _run_readonly(["tmux", "ls"])
    if not result.get("ok"):
        return []
    out = result.get("stdout") or ""
    return [ln for ln in out.splitlines() if ln.strip()]


def ssh_tunnel_status() -> dict[str, Any]:
    """État du LISTENER local du tunnel SSH (port 2223) — lecture pure.

    Vérifie via ``ss -ltn`` si un socket écoute sur 2223. NE SONDE PAS le Mac
    (aucun ssh sortant, aucun effet de bord distant) — on observe seulement
    l'état local.

    Forme ::

        {"listener_2223": bool, "note": <str>}
    """
    result = _run_readonly(["ss", "-ltn"])
    note = "ss indisponible — état listener inconnu"
    listening = False
    if result.get("ok"):
        out = result.get("stdout") or ""
        # match conservateur : ':2223' présent dans une ligne LISTEN.
        listening = any(":2223" in ln for ln in out.splitlines())
        note = (
            "listener local 2223 détecté"
            if listening
            else "aucun listener local sur 2223"
        )
    return {"listener_2223": listening, "note": note}


# Port 18100 en hexadécimal majuscule (pour matching /proc/net/tcp*)
_COCKPIT_TUNNEL_PORT_HEX = "46B4"

# État LISTEN dans /proc/net/tcp* (colonne st)
_TCP_STATE_LISTEN = "0A"

# Chemins par défaut de /proc/net/tcp et tcp6 (injectable pour les tests)
_DEFAULT_PROC_TCP_PATHS = ("/proc/net/tcp", "/proc/net/tcp6")


def cockpit_tunnel_status(
    _proc_paths: tuple[str, ...] | None = None,
) -> str:
    """Détection UP/DOWN du tunnel cockpit autossh V1.7E — lecture pure.

    Le tunnel cockpit établit un reverse-forward ``-R 127.0.0.1:18100:127.0.0.1:8100``.
    Quand le tunnel est vivant, sshd crée un socket LISTEN sur le port 18100
    (loopback). Quand le tunnel est down, ce port n'écoute pas.

    Ce signal est observable en lisant ``/proc/net/tcp`` et ``/proc/net/tcp6``
    (pseudo-fichiers noyau, lisibles sans privilège, sans subprocess, sans sonde
    réseau sortante).

    Parsing /proc/net/tcp :
      - colonnes séparées par espaces
      - index 1 = ``local_address`` au format ``HEXIP:HEXPORT`` (octets inversés)
      - index 3 = ``st`` = état TCP en hex (``0A`` = LISTEN)
      - Port 18100 = ``46B4`` (majuscule)

    On cherche un socket dont :
      - la partie ``HEXPORT`` du ``local_address`` vaut ``46B4`` ;
      - l'état ``st`` vaut ``0A`` (LISTEN).

    On n'exige pas de matcher l'IP exacte (``0100007F`` en tcp, ``::1`` en tcp6)
    car c'est le seul service qui écoute sur 18100 en pratique — ce port n'est
    bindé que par sshd via le reverse-forward du tunnel cockpit loopback.

    Retourne :
      ``"up"``      — si un LISTEN sur 46B4 est trouvé ;
      ``"down"``    — si aucun LISTEN sur 46B4 ;
      ``"unknown"`` — si les fichiers /proc/net/tcp* sont illisibles (fail-safe).

    Ne lève jamais d'exception. Tout échec → ``"unknown"``.

    Paramètre :
      _proc_paths : tuple de chemins de fichiers proc à inspecter (injectable pour
                    les tests via monkeypatch ou argument direct). Si ``None``
                    (défaut), utilise ``_DEFAULT_PROC_TCP_PATHS`` lu au moment de
                    l'appel (pas à la définition) — ce qui permet le monkeypatch
                    du module en test.
    """
    resolved_paths = _proc_paths if _proc_paths is not None else _DEFAULT_PROC_TCP_PATHS
    try:
        for proc_path in resolved_paths:
            try:
                with open(proc_path, encoding="ascii") as fh:
                    lines = fh.readlines()
            except OSError:
                # fichier absent ou illisible → on passe au suivant
                continue

            # Première ligne = en-tête, on la saute
            for line in lines[1:]:
                parts = line.split()
                if len(parts) < 4:
                    continue
                local_address = parts[1]  # format "HEXIP:HEXPORT"
                state = parts[3]          # état TCP hex
                # On cherche un LISTEN (0A) sur le port 46B4
                if state.upper() == _TCP_STATE_LISTEN:
                    # local_address = "HEXIP:HEXPORT"
                    colon_pos = local_address.rfind(":")
                    if colon_pos >= 0:
                        port_hex = local_address[colon_pos + 1:].upper()
                        if port_hex == _COCKPIT_TUNNEL_PORT_HEX:
                            return "up"

        # Aucun LISTEN sur 46B4 trouvé dans les fichiers lus
        return "down"

    except Exception:  # pragma: no cover — garde-fou ultime
        return "unknown"
