"""LA DÉPENDANCE QUI N'EST DÉCLARÉE NULLE PART, ET QU'ON NE VOIT QUE SUR UNE
MACHINE NEUVE.

CE QUE CE FICHIER GARDE
=======================
`POST /cc/login` est la SEULE route non-GET de tout le cockpit. C'est donc la
seule porte d'entrée : sans elle, personne ne voit sa mémoire. Elle lit un
formulaire (``await request.form()``), et Starlette délègue l'analyse d'un
corps ``multipart/form-data`` à une bibliothèque tierce, ``python-multipart``.

Cette bibliothèque n'est déclarée ni dans ``requirements.txt``, ni dans
``requirements.lock.txt``. Elle est pourtant présente dans l'environnement
Python de l'installation d'origine — posée un jour, par autre chose, et jamais
remontée dans le fichier canonique.

Conséquence sur une installation NEUVE, qui n'a que ce que ``requirements.txt``
demande : le cockpit démarre, ``/cc/healthz`` rend 200, ``provisioned`` est vrai
partout — et toute tentative de connexion rend **500 en texte brut**, sans une
ligne dans le journal applicatif. Tout dit que l'installation est saine, et
personne ne peut entrer.

C'est la forme la plus coûteuse d'une dépendance manquante : elle est
INVISIBLE partout où le paquet est déjà là, c'est-à-dire sur la machine de qui
a écrit le code. Elle a été trouvée par ``tests/acceptance/acceptance.sh``, qui
installe sur une base vierge — mais un test d'acceptation dure un quart
d'heure et demande root. Cette garde-ci dure une milliseconde et tourne dans
``make test``, sur un dépôt fraîchement cloné.

POURQUOI LA RÈGLE EST ÉCRITE SOUS CETTE FORME
=============================================
On ne vérifie pas « python-multipart est dans requirements.txt » — ce serait
une constante, et elle survivrait à la disparition de la route qui la justifie.
On vérifie l'IMPLICATION :

    s'il existe une route qui lit un formulaire, alors la bibliothèque qui sait
    lire un formulaire doit être déclarée.

Le jour où le cockpit n'aura plus de formulaire, ce test cessera d'exiger quoi
que ce soit, tout seul. Et le jour où quelqu'un ajoutera un second formulaire
ailleurs, il sera couvert sans qu'on y pense.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


_RACINE = Path(__file__).resolve().parent.parent.parent

#: `request.form()` — l'appel qui met Starlette en position d'avoir besoin d'un
#: analyseur de formulaire. La parenthèse est dans le motif : on cherche
#: l'APPEL, pas une mention dans un commentaire.
_LIT_UN_FORMULAIRE = re.compile(r"\.form\s*\(")

#: Le nom de la DISTRIBUTION, tel qu'il s'écrit dans requirements.txt. Le
#: module, lui, s'importe sous le nom `multipart` — les deux diffèrent, et
#: c'est une des raisons pour lesquelles l'absence passe inaperçue.
_DISTRIBUTION = "python-multipart"

_SOURCES = ("control_center", "app")


def _fichiers_python() -> list[Path]:
    fichiers: list[Path] = []
    for dossier in _SOURCES:
        base = _RACINE / dossier
        if base.is_dir():
            fichiers += [
                f for f in base.rglob("*.py")
                if "__pycache__" not in f.parts
            ]
    return fichiers


def _routes_qui_lisent_un_formulaire() -> list[str]:
    """Les fichiers servis qui appellent `request.form()`.

    On ignore les lignes commentées : un fichier qui EXPLIQUE l'analyse des
    formulaires n'en fait pas.
    """
    trouves: list[str] = []
    for f in _fichiers_python():
        for ligne in f.read_text(encoding="utf-8", errors="replace").splitlines():
            nu = ligne.lstrip()
            if nu.startswith("#"):
                continue
            if _LIT_UN_FORMULAIRE.search(ligne):
                trouves.append(f"{f.relative_to(_RACINE)} : {nu.strip()}")
                break
    return trouves


def _declarations() -> str:
    """Le texte des deux fichiers de dépendances, concaténé et normalisé.

    Les deux comptent : `requirements.txt` est ce qu'installe le bootstrap,
    `requirements.lock.txt` est ce qui fige les versions. Une dépendance
    présente dans l'un et pas dans l'autre est un piège différent, mais un
    piège quand même — ici on demande simplement qu'elle soit quelque part.
    """
    texte = ""
    for nom in ("requirements.txt", "requirements.lock.txt"):
        chemin = _RACINE / nom
        if chemin.is_file():
            texte += chemin.read_text(encoding="utf-8").lower()
    return texte


def test_le_depot_declare_bien_des_dependances():
    """Sans ce garde-fou, tous les suivants passeraient sur un dépôt vide."""
    assert _declarations().strip(), "aucun fichier de dépendances lisible"


def test_une_route_qui_lit_un_formulaire_exige_son_analyseur():
    routes = _routes_qui_lisent_un_formulaire()
    if not routes:
        pytest.skip(
            "aucune route ne lit de formulaire — la règle ne s'applique plus, "
            "et c'est très bien : ce test s'efface tout seul."
        )

    declare = _DISTRIBUTION in _declarations()
    assert declare, (
        "Ces routes lisent un formulaire :\n    "
        + "\n    ".join(routes)
        + f"\n\nOr « {_DISTRIBUTION} » n'est déclaré ni dans requirements.txt, "
        "ni dans requirements.lock.txt.\n\n"
        "Sur une installation neuve — celle d'un inconnu qui vient de cloner —\n"
        "Starlette lève à l'analyse du corps, et la route rend 500 en texte\n"
        "brut. Le cockpit démarre pourtant, /cc/healthz rend 200, et rien dans\n"
        "le journal applicatif ne dit ce qui manque : la seule porte d'entrée\n"
        "de la mémoire est fermée sans qu'aucun contrôle ne s'en aperçoive.\n\n"
        "Le geste : ajouter une ligne à requirements.txt.\n"
        f"    {_DISTRIBUTION}>=0.0.9\n\n"
        "Ce défaut est INVISIBLE sur toute machine où le paquet est déjà là —\n"
        "c'est-à-dire sur celle qui a servi à écrire le code. Il a été trouvé\n"
        "par tests/acceptance/acceptance.sh, qui installe sur une base vierge."
    )


def test_le_module_importe_et_la_distribution_declaree_ne_portent_pas_le_meme_nom():
    """Une note exécutable, et la raison pour laquelle l'absence se cache si bien.

    On importe ``multipart`` ; on déclare ``python-multipart``. Chercher le nom
    d'import dans requirements.txt ne trouve rien — et donne l'impression que
    la dépendance est absente alors qu'elle est là, ou l'inverse. Ce test fige
    la distinction pour que le prochain lecteur ne s'y reprenne pas à deux fois.
    """
    assert _DISTRIBUTION != "multipart"
    assert _DISTRIBUTION.endswith("multipart")
