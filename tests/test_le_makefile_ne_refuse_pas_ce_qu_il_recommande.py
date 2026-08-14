"""Un outil qui propose un geste et le refuse ensuite accuse l'utilisateur.

LE DÉFAUT, MESURÉ
-----------------
Le `Makefile` annonçait `make test PY=python3` à DEUX endroits — en tête de
fichier (« Redéfinissable : `make test PY=python3` ») et dans le message
d'erreur de sa propre garde — comme l'alternative à `.venv`. Et sa garde le
refusait :

    $ make test PY=python3
    L'environnement Python n'existe pas encore : python3 est introuvable.
    […] (Ou lancez la suite avec votre interpréteur : make test PY=python3)

La même sortie donnait le geste et le déclarait impossible. La cause : la
garde testait `test -x "$(PY)"`, qui pour `python3` cherche un FICHIER de ce
nom dans le répertoire courant — jamais dans le PATH. Le défaut par défaut
(`.venv/bin/python`, un chemin relatif qui existe) masquait le problème :
la seule forme qui échouait était celle qu'on recommandait.

CE QUE CE FICHIER GARDE
-----------------------
Que tout interpréteur que le Makefile RECOMMANDE passe sa propre garde. Le
contrôle ne code en dur aucun nom : il EXTRAIT les recommandations du texte
du Makefile, puis évalue le prédicat réel de la garde, lui aussi extrait du
Makefile. Les deux côtés viennent du fichier — c'est ce qui fait qu'ils ne
peuvent pas diverger sans que ce test le voie.

Hermétique : lit un fichier, évalue un test shell. Ni base, ni réseau.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest


MAKEFILE = Path(__file__).resolve().parent.parent / "Makefile"
TEXTE = MAKEFILE.read_text(encoding="utf-8")


def _interpreteurs_recommandes() -> set[str]:
    """Tout ce que le Makefile propose derrière `PY=`, en prose ou en message."""
    return {m.group(1) for m in re.finditer(r"\bPY=([A-Za-z0-9_./-]+)", TEXTE)}


def _predicat_de_la_garde(interpreteur: str) -> str:
    """Le prédicat de `_exige-venv`, PRIS dans le Makefile, `$(PY)` substitué.

    On le prend au lieu de le recopier : un test qui recopie le prédicat qu'il
    vérifie ne vérifie que lui-même, et resterait vert si le Makefile changeait.
    """
    ligne = TEXTE.split("_exige-venv:", 1)[1].lstrip("\n").splitlines()[0]
    return ligne.lstrip("\t@").split("|| {", 1)[0].strip().replace("$(PY)", interpreteur)


def test_le_makefile_recommande_bien_quelque_chose():
    """Si plus rien n'est recommandé, ce fichier n'a plus d'objet — qu'on le sache."""
    assert _interpreteurs_recommandes(), (
        "aucun `PY=…` dans le Makefile : le contrôle ci-dessous ne mord plus."
    )


@pytest.mark.parametrize("interpreteur", sorted(_interpreteurs_recommandes()))
def test_la_garde_accepte_ce_que_le_makefile_recommande(interpreteur, tmp_path):
    """La garde `_exige-venv` doit laisser passer chaque interpréteur annoncé.

    On évalue le prédicat RÉEL, dans un répertoire VIDE — c'est-à-dire dans la
    situation du dépôt fraîchement cloné dont le message parle. Un `test -x`
    sur un nom nu y échoue ; un `command -v` y réussit si le PATH le porte.
    """
    if shutil.which(interpreteur) is None and not Path(interpreteur).exists():
        pytest.skip(f"{interpreteur} n'est pas installé sur cette machine")

    predicat = _predicat_de_la_garde(interpreteur)

    rc = subprocess.run(
        ["bash", "-c", predicat], cwd=tmp_path, capture_output=True
    ).returncode
    assert rc == 0, (
        f"le Makefile recommande `make test PY={interpreteur}` et sa propre garde "
        f"le refuse (prédicat : {predicat}). Un outil qui propose un geste puis "
        "le déclare impossible accuse l'utilisateur de sa propre erreur."
    )


def test_la_garde_refuse_toujours_un_interpreteur_absent(tmp_path):
    """L'inverse doit rester vrai : la garde existe pour attraper le clone neuf.

    Sans ce contrôle, « faire passer python3 » pourrait se régler en supprimant
    la garde — ce qui rendrait « /bin/sh: .venv/bin/python: not found », code
    127, à qui vient de cloner.
    """
    predicat = _predicat_de_la_garde(str(tmp_path / "interpreteur-inexistant"))

    rc = subprocess.run(
        ["bash", "-c", predicat], cwd=tmp_path, capture_output=True
    ).returncode
    assert rc != 0, "la garde ne refuse plus un interpréteur absent : elle ne garde rien"
