"""Un environnement Python DÉPLACÉ est mort — et il a l'air vivant.

CE QUE CE FICHIER GARDE, ET POURQUOI IL EXISTE
==============================================

Le remède « recommandé » de l'étape 9 est `sudo mv $ARAC_HOME /opt/<base>`.
L'étape 5 est censée rattraper le coup en reconstruisant l'environnement
Python — elle ne le faisait pas, parce que son garde était :

    if [[ ! -x "$ARAC_VENV/bin/python" ]]; then   # créer le venv

Or `bin/python` est un LIEN vers `python3`, lui-même vers `/usr/bin/python3` :
il reste parfaitement exécutable après n'importe quel déplacement. Le garde
concluait donc « venv sain », ne reconstruisait rien, et l'étape repartait sur
des exécutables morts. Ce qui meurt au déplacement, ce n'est pas
l'interpréteur : ce sont les SCRIPTS de `bin/` (pip, alembic, uvicorn), dont la
première ligne porte le chemin ABSOLU de l'ancien emplacement. Chacun rend :

    …/pip: cannot execute: required file not found        (code 127)

Les deux remèdes offerts à l'utilisateur étaient donc inopérants, chacun pour
une raison différente. Ce fichier borne le garde : il doit éprouver ce dont
l'étape a réellement besoin — qu'un SCRIPT du venv s'exécute.

Ni base, ni réseau, ni root.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[1]
_LIB = _RACINE / "bootstrap" / "lib"


def _verdict(venv: Path) -> int:
    script = (
        "set -uo pipefail\n"
        "ARAC_UI_COULEUR=jamais\n"
        f'ARAC_VENV="{venv}"\n'
        "ARAC_HOME=/opt/mon-cerveau\n"
        f'source "{_LIB}/ui.sh"\n'
        f'source "{_LIB}/core.sh"\n'
        f'source "{_LIB}/database.sh"\n'
        "venv_utilisable; echo \"RC=$?\"\n"
    )
    e = dict(os.environ)
    e["ARAC_UI_COULEUR"] = "jamais"
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                       env=e, timeout=120)
    assert "RC=" in r.stdout, r.stdout + r.stderr
    return int(r.stdout.rsplit("RC=", 1)[1].split()[0])


def _venv_de_theatre(d: Path, shebang: str) -> Path:
    """Un venv dont l'interpréteur marche et dont les SCRIPTS pointent où l'on veut."""
    b = d / "bin"
    b.mkdir(parents=True)
    (b / "python").symlink_to(sys.executable)
    (b / "pip").write_text(f"#!{shebang}\nprint('pip 25.0')\n", encoding="utf-8")
    (b / "pip").chmod(0o755)
    (d / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    return d


def test_un_venv_sain_est_reconnu_sain(tmp_path):
    v = _venv_de_theatre(tmp_path / "vivant", sys.executable)
    assert _verdict(v) == 0


def test_un_venv_deplace_est_reconnu_mort(tmp_path):
    """Le cas exact : l'interpréteur répond, les scripts sont morts."""
    v = _venv_de_theatre(tmp_path / "deplace", "/ancien/chemin/qui/nexiste/plus/bin/python")
    assert (v / "bin" / "python").exists() and os.access(v / "bin" / "python", os.X_OK), (
        "le décor du test est faux : bin/python doit rester exécutable"
    )
    assert _verdict(v) == 1, (
        "Un venv déplacé a été déclaré utilisable.\n"
        "L'étape 5 ne le reconstruira pas, et repartira sur des exécutables "
        "morts : pip, alembic et uvicorn rendront « required file not found ».\n"
        "Le garde éprouve l'interpréteur, qui survit à tout, au lieu d'un "
        "SCRIPT, qui est ce qui meurt."
    )


def test_un_venv_absent_est_reconnu_absent(tmp_path):
    assert _verdict(tmp_path / "rien") == 1


def test_letape_des_migrations_consulte_ce_garde():
    """Le garde ne sert à rien s'il n'est pas celui que l'étape 5 interroge."""
    src = (_LIB / "database.sh").read_text(encoding="utf-8")
    assert "venv_utilisable" in src
    corps = src.split("etape_migrations()", 1)[1]
    assert "venv_utilisable" in corps, (
        "etape_migrations n'appelle pas venv_utilisable : le garde existe mais "
        "personne ne le consulte."
    )
    assert '[[ ! -x "$ARAC_VENV/bin/python" ]]' not in corps, (
        "L'ancien garde — celui qu'un venv déplacé trompe — est toujours en place."
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash requis")
def test_le_venv_est_reconstruit_avec_clear():
    """Recréer par-dessus un venv mort exige `--clear` : sinon rien ne change.

    `python3 -m venv <dir>` sur un répertoire existant ne réécrit pas les
    scripts de `bin/` — c'est `--clear` qui les refait. Sans lui, la
    reconstruction serait un geste vide.
    """
    src = (_LIB / "database.sh").read_text(encoding="utf-8")
    corps = src.split("etape_migrations()", 1)[1]
    assert "--clear" in corps, (
        "La reconstruction du venv ne passe pas --clear : sur un venv mort "
        "mais présent, elle ne réparerait rien."
    )
