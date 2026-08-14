"""Le dépôt ne se salit pas tout seul — les artefacts d'un passage réel sont ignorés.

CE QUE CE FICHIER GARDE, ET POURQUOI IL EXISTE
==============================================

Une installation réelle laisse des fichiers dans le dépôt. Trois d'entre eux
n'étaient couverts par aucune règle de `.gitignore` :

  · `.bootstrap-install.state` et `.bootstrap-install.<base>.state` —
    l'avancement du bootstrap. Publiés, ils font hériter le cloneur de
    l'avancement de QUELQU'UN D'AUTRE : sept étapes sur onze sont alors sautées
    en silence, dont la base, les migrations, les secrets et les services. Le
    bootstrap n'affiche plus que quatre en-têtes d'étape sur onze — F3, « chaque
    étape dit pourquoi elle existe », tombe sans qu'une ligne ait été mal écrite.

  · `.bootstrap-state.json` — l'entretien interrompu, c'est-à-dire les RÉPONSES
    de l'utilisateur : son prénom, le nom de son cerveau, l'identifiant de son
    poste, sa taxonomie. Le publier viole F1 et F2 d'un seul geste.

Ce ne sont pas des oublis cosmétiques : `git add .` les emporte, et l'historique
de git n'oublie rien.

TROIS TESTS, ET LE TROISIÈME EMPÊCHE LA LISTE DE POURRIR
   1. chaque artefact connu est ignoré par git ;
   2. aucun artefact ne traîne aujourd'hui dans l'arborescence, non suivi ET
      non ignoré ;
   3. les noms de cette liste sont ENCORE ceux que le code écrit — sinon le
      test garderait une liste de fichiers que plus personne ne produit,
      pendant que les vrais artefacts repartiraient dans le dépôt.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[1]

#: (chemin d'exemple, fichier qui l'écrit, motif qui doit s'y trouver encore)
#:
#: Le troisième champ est ce qui empêche cette table de mentir : il est
#: recherché dans le producteur. Renommer l'artefact sans toucher ici rend le
#: test rouge, au lieu de le rendre silencieusement inutile.
ARTEFACTS = (
    (
        ".bootstrap-install.state",
        "bootstrap/lib/core.sh",
        r"\.bootstrap-install\.state",
    ),
    (
        ".bootstrap-install.mon_cerveau.state",
        "bootstrap/lib/core.sh",
        r"\.bootstrap-install\.\$ARAC_DB\.state",
    ),
    (
        ".bootstrap-state.json",
        "bootstrap/wizard.py",
        r"\.bootstrap-state\.json",
    ),
    (
        "config/brain.toml",
        "bootstrap/wizard.py",
        r'conf / "brain\.toml"',
    ),
    (
        "config/scopes.toml",
        "bootstrap/wizard.py",
        r'conf / "scopes\.toml"',
    ),
    (
        "app/schemas/scope_generated.py",
        "bootstrap/generate_scopes.py",
        r"app/schemas/scope_generated\.py",
    ),
    (
        "db/seeds/scopes.sql",
        "bootstrap/generate_scopes.py",
        r"db/seeds/scopes\.sql",
    ),
)

#: Ce à quoi ressemble un artefact d'exécution à la racine. Sert au balayage du
#: test 2 : on ne peut pas prédire le nom de la base d'un inconnu, on peut
#: prédire la FORME de ce que le bootstrap laisse.
MOTIFS_RACINE = (".bootstrap-install", ".bootstrap-state")


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(_RACINE), *args], capture_output=True, text=True
    )


def _git_dispo() -> bool:
    return _git("rev-parse", "--git-dir").returncode == 0


pytestmark = pytest.mark.skipif(
    not _git_dispo(), reason="hors dépôt git — .gitignore n'a pas de sens ici"
)


@pytest.mark.parametrize("chemin,_producteur,_motif", ARTEFACTS)
def test_lartefact_est_ignore_par_git(chemin, _producteur, _motif):
    """`git add .` ne doit emporter aucun de ces fichiers."""
    r = _git("check-ignore", "-q", "--no-index", chemin)
    assert r.returncode == 0, (
        f"« {chemin} » n'est couvert par AUCUNE règle de .gitignore.\n"
        f"Un « git add . » le publierait, et celui qui clonerait ensuite "
        f"hériterait de l'état — ou de l'identité — de quelqu'un d'autre."
    )


@pytest.mark.parametrize("chemin,producteur,motif", ARTEFACTS)
def test_le_producteur_ecrit_encore_ce_nom(chemin, producteur, motif):
    """La liste ci-dessus décrit-elle encore la réalité du code ?"""
    source = (_RACINE / producteur).read_text(encoding="utf-8")
    assert re.search(motif, source), (
        f"{producteur} n'écrit plus « {chemin} » sous ce nom.\n"
        f"La règle .gitignore qui le couvre est peut-être devenue inutile, et "
        f"le NOUVEAU nom, lui, n'est peut-être couvert par rien. Mettez cette "
        f"table à jour — c'est tout ce qu'elle sert à provoquer."
    )


def test_aucun_artefact_ne_traine_dans_larborescence():
    """Rien, aujourd'hui, n'est à la fois non suivi et non ignoré."""
    r = _git("status", "--porcelain", "--untracked-files=all")
    assert r.returncode == 0, r.stderr
    coupables = []
    for ligne in r.stdout.splitlines():
        if not ligne.startswith("?? "):
            continue
        chemin = ligne[3:].strip().strip('"')
        nom = Path(chemin).name
        if any(nom.startswith(m) for m in MOTIFS_RACINE):
            coupables.append(chemin)
    assert not coupables, (
        "Ces artefacts d'un passage réel sont visibles de git :\n  "
        + "\n  ".join(coupables)
        + "\nIls doivent être ignorés ET retirés de l'arborescence."
    )
