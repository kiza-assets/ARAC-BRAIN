"""`verify_install.sh` mesure-t-il CE cerveau, ou ce qui traîne sur la machine ?

CE QUE CE FICHIER GARDE, ET POURQUOI IL EXISTE
==============================================

Un serveur peut porter plusieurs cerveaux, et il porte de toute façon les restes
des essais précédents. Trois ressources sont PARTAGÉES entre eux :

  · le dossier des sauvegardes  — `/var/backups/arac` pour tout le monde ;
  · les numéros de port         — 8000 et 8100 par défaut, pour tout le monde ;
  · les rôles PostgreSQL        — globaux au serveur, jamais à la base.

Un contrôle qui les mesure sans les CADRER rend un verdict sur la machine en
croyant le rendre sur ce cerveau-ci. C'était le cas du contrôle 7 : un cerveau
jamais sauvegardé recevait « ✓ dernière sauvegarde il y a 5 h — 4 au total »
grâce aux dumps d'un autre, et se voyait proposer de restaurer la mémoire de cet
autre dans sa propre base de test. C'est l'exacte inversion de la doctrine du
fichier — « je n'ai pas pu mesurer » plutôt qu'un faux vert — et cela portait sur
le filet de sécurité.

Les tests ci-dessous éprouvent les contrôles UN PAR UN, en leur servant un
décor : un dossier de sauvegardes, un `ss` et un `systemctl` de théâtre. Ni base,
ni réseau, ni root.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[1]
_VERIFY = _RACINE / "bootstrap" / "checks" / "verify_install.sh"


def _lancer(script: str, env: dict | None = None, prelude: str = "") -> subprocess.CompletedProcess:
    """Source `verify_install.sh` (sans le lancer) puis joue `script`."""
    plein = (
        "set -uo pipefail\n"
        f"ARAC_UI_COULEUR=jamais\n"
        f"{prelude}\n"
        f'source "{_VERIFY}"\n'
        f"{script}\n"
    )
    e = dict(os.environ)
    e["ARAC_UI_COULEUR"] = "jamais"
    e["NO_COLOR"] = "1"
    if env:
        e.update(env)
    return subprocess.run(
        ["bash", "-c", plein], capture_output=True, text=True, env=e, timeout=120
    )


def test_le_fichier_se_source_sans_sexecuter():
    """Un contrôle qu'on ne peut pas éprouver isolément n'est pas éprouvé."""
    r = _lancer('echo "SOURCE_OK"')
    assert "SOURCE_OK" in r.stdout, (
        "verify_install.sh lance `main` même quand on le SOURCE : impossible "
        "d'éprouver un contrôle seul.\n" + r.stdout[-2000:] + r.stderr[-2000:]
    )
    assert "Verdict" not in r.stdout


# ---------------------------------------------------------------------------
# Contrôle 7 — les sauvegardes, partagées entre tous les cerveaux
# ---------------------------------------------------------------------------

def _decor_sauvegardes(tmp_path, noms):
    d = tmp_path / "backups"
    d.mkdir()
    for n in noms:
        f = d / n
        f.write_bytes(b"x")
        os.utime(f, (time.time() - 3600, time.time() - 3600))
    return d


def _controle_sauvegardes(tmp_path, noms, base="mon_cerveau"):
    d = _decor_sauvegardes(tmp_path, noms)
    return _lancer(
        "controle_sauvegardes",
        prelude=(
            f'ARAC_DB={base}\n'
            f'ARAC_BACKUP_DIR="{d}"\n'
            f'ARAC_UNITE_PREFIXE=arac-{base}\n'
            f'ARAC_PG_SUPERUSER=postgres\n'
        ),
    )


def test_les_sauvegardes_dun_autre_cerveau_ne_valident_pas_celui_ci(tmp_path):
    """Le défaut, tel quel : quatre dumps d'« alex », zéro pour « mon_cerveau »."""
    r = _controle_sauvegardes(tmp_path, [
        "alex_brain-20260807T003109Z.dump",
        "alex_brain-20260807T063025Z.dump",
        "alex_brain-20260807T123028Z.dump",
        "alex_brain-20260807T183315Z.dump",
    ])
    assert "✓" not in r.stdout, (
        "Un cerveau JAMAIS sauvegardé est déclaré sain grâce aux dumps d'un "
        "autre — et se voit proposer de restaurer la mémoire de cet autre.\n"
        + r.stdout
    )
    assert "alex_brain-" not in r.stdout, (
        "Le remède nomme le dump d'un AUTRE cerveau : le suivre chargerait sa "
        "mémoire dans la base de test de celui-ci.\n" + r.stdout
    )
    assert "4" in r.stdout, (
        "Le message ne dit pas que quatre dumps d'un autre cerveau occupent le "
        "dossier : l'utilisateur ne comprendra pas ce qu'il voit.\n" + r.stdout
    )


def test_les_sauvegardes_de_ce_cerveau_sont_bien_comptees(tmp_path):
    """Cadrer ne doit pas rendre le contrôle aveugle à ce qu'il doit voir."""
    r = _controle_sauvegardes(tmp_path, [
        "mon_cerveau-20260807T183315Z.dump",
        "autre_brain-20260807T183315Z.dump",
    ])
    assert "✓" in r.stdout, r.stdout
    assert "mon_cerveau-20260807T183315Z.dump" in r.stdout
    assert "1" in r.stdout


# ---------------------------------------------------------------------------
# Le port : un numéro appartient à la machine, pas au cerveau
# ---------------------------------------------------------------------------

def _theatre_systemd(tmp_path, etat="active", main_pid="4242"):
    """Un `systemctl` et un `ss` de théâtre, sur le PATH."""
    b = tmp_path / "bin"
    b.mkdir(exist_ok=True)
    (b / "systemctl").write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        f'  *is-active*) echo {etat}; [ "{etat}" = active ] || exit 3 ;;\n'
        f'  *MainPID*)   echo {main_pid} ;;\n'
        "  *) echo '' ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    (b / "systemctl").chmod(0o755)
    return b


def _theatre_ss(b, pid):
    (b / "ss").write_text(
        "#!/bin/sh\n"
        'printf "LISTEN 0 2048 127.0.0.1:8100 0.0.0.0:* '
        f'users:((\\"uvicorn\\",pid={pid},fd=8))\\n"\n',
        encoding="utf-8",
    )
    (b / "ss").chmod(0o755)
    return b


def _port(tmp_path, pid_socket, main_pid="4242"):
    b = _theatre_systemd(tmp_path, main_pid=main_pid)
    _theatre_ss(b, pid_socket)
    return _lancer(
        '_port "cockpit" 8100 "arac-mon_cerveau-cockpit.service"',
        env={"PATH": f"{b}:{os.environ['PATH']}"},
    )


def test_le_port_tenu_par_un_autre_processus_ne_vaut_pas_verdict(tmp_path):
    """8100 est un numéro de la MACHINE : quelqu'un d'autre peut le tenir.

    `Type=simple` rend l'unité « active » dès le fork, AVANT que uvicorn ait
    seulement tenté d'ouvrir la socket. Un cockpit qui redémarre en boucle sur
    « address already in use » se voyait donc décerner un ✓ — le port étant
    bel et bien tenu, mais par le cerveau du voisin.
    """
    r = _port(tmp_path, pid_socket="9999", main_pid="4242")
    assert "✓" not in r.stdout, (
        "Le port est attribué à ce cerveau alors qu'un AUTRE processus le "
        "tient. Le contrôle mesure la machine, pas ce cerveau.\n" + r.stdout
    )


def test_le_port_tenu_par_notre_service_vaut_verdict(tmp_path):
    r = _port(tmp_path, pid_socket="4242", main_pid="4242")
    assert "✓" in r.stdout, r.stdout
    assert "boucle locale" in r.stdout


# ---------------------------------------------------------------------------
# Les rôles : globaux au serveur, jamais à la base
# ---------------------------------------------------------------------------

def _controle_roles(existe, connect):
    """`qq` de théâtre : le rôle existe-t-il, et peut-il joindre CETTE base ?"""
    # L'écrasement de `qq` vient APRÈS le `source` : sinon verify_install.sh
    # redéfinit la fonction et le décor n'aura servi à rien — le test
    # interrogerait la vraie grappe PostgreSQL de la machine, et rendrait un
    # verdict sur elle au lieu du cas qu'il prétend éprouver.
    return _lancer(
        (
            "qq() {\n"
            f'  case "$1" in\n'
            f'    *has_database_privilege*) echo "{connect}" ;;\n'
            f'    *pg_roles*)               echo "{existe}" ;;\n'
            "    *) echo '' ;;\n"
            "  esac\n"
            "}\n"
            "controle_roles\n"
        ),
        prelude=(
            "ARAC_DB=mon_cerveau\n"
            "ARAC_ROLE_PREFIX=arac\n"
            "ARAC_ENV_FILE=/inexistant/arac.env\n"
            "ARAC_SECRETS_ROLES=/inexistant/roles.env\n"
            "R_ADMIN=arac_admin; R_APP=arac_app\n"
            "R_AGENT=arac_agent; R_READONLY=arac_readonly\n"
            "ARAC_PG_SUPERUSER=postgres\n"
        ),
    )


def test_un_role_du_voisin_ne_vaut_pas_un_role_de_ce_cerveau():
    """Les rôles sont globaux au CLUSTER : leur seule présence ne prouve rien.

    Sur une machine ayant déjà hébergé un cerveau, `arac_admin` existe avant
    même qu'on ait rien installé. Quatre ✓ verts pour une base qui n'a jamais
    reçu le moindre GRANT.
    """
    r = _controle_roles(existe="1", connect="f")
    assert "✓ rôle arac_admin" not in r.stdout.replace("  ", " "), (
        "Un rôle qui EXISTE mais ne peut pas joindre cette base est déclaré "
        "sain : le contrôle mesure le serveur, pas ce cerveau.\n" + r.stdout
    )


def test_un_role_de_ce_cerveau_est_declare_sain():
    r = _controle_roles(existe="1", connect="t")
    assert r.stdout.count("✓") >= 4, r.stdout
