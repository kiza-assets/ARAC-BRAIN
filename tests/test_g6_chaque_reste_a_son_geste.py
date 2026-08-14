"""G6 — CHAQUE RESTE QUE LE CONTRÔLE DE DÉPART NOMME A SON GESTE.

CE QUE CE GARDE MESURE, EN UNE PHRASE
=====================================
`ops/uninstall_check.sh` est le dernier écran du cycle de vie : celui qu'on lit
le jour où l'on rend le serveur, pour savoir si l'on a su faire disparaître son
cerveau. Il ne détruit rien lui-même — il NOMME ce qui reste et PRESCRIT les
gestes. Un reste nommé sans geste est donc une impasse : le lecteur voit qu'il
lui reste une copie complète de sa mémoire, il lit « LES GESTES, DANS L'ORDRE
OÙ ILS PASSENT », et il n'y a rien dessous.

LE DÉFAUT, MESURÉ, QUI A DONNÉ CE GARDE
=======================================
Section 2, branche « le fichier déclare une empreinte, l'appelant n'en a donné
aucune, et le nom du cerveau écrit DANS le dump est le nôtre » — c'est-à-dire la
branche la plus courante de toutes, celle du lecteur qui suit le §13 sans avoir
l'uuid de son installation sous la main. Elle imprimait :

    ✗ copie complète de la mémoire : « /root/adieu-<cerveau>-….dump »
      ↳ elle se déclare du cerveau « <cerveau> »

… et AUCUN geste. Le rapport se fermait sur l'en-tête, ses dix lignes de
commentaires sur l'ordre des quatre temps, puis « # puis, pour vérifier ».
Zéro commande. Mesuré sur un cerveau réellement désinstallé : « VERDICT : 1
RESTE(S) », rc=1, et rien à faire.

Le pied de page aggravait la chose : la commande de suite qu'il imprimait
(`… --gestes`) recopiait la base et le port de l'invocation en cours et LAISSAIT
TOMBER `--empreinte`, l'argument dont ce même rapport dit deux écrans plus haut
« c'est elle qui tranche, pas le nom ». L'outil se citait lui-même, amputé.

CE QUE CE GARDE EXIGE, ET CE QU'IL N'EXIGE PAS
==============================================
Il exige qu'un rapport qui NOMME des restes et qu'on interroge avec `--gestes`
ne rende jamais une liste vide sans dire pourquoi, et que la commande de suite
qu'il imprime porte les mêmes options discriminantes que l'invocation qui
l'imprime — un outil qui se cite lui-même doit se citer entier.

Il n'exige PAS qu'un geste soit imprimé dans tous les cas : se taire est parfois
juste, et c'est même le cœur de ce fichier. Quand un homonyme a été vu sur la
machine, prescrire un `rm` à partir d'un nom coûterait la mémoire d'un voisin.
Ce qu'on refuse, c'est le silence SANS RAISON — l'en-tête suivi de rien.

POURQUOI ON EXÉCUTE LE SCRIPT AU LIEU DE LE LIRE
================================================
Une lecture statique de ce fichier ne peut pas dire si une branche `elif` sert
un geste : elle l'a d'ailleurs manqué pendant deux versions, sous les yeux de
tout le monde. On fabrique donc de VRAIS dumps — un en-tête `pg_dump` en texte
et la plaque `COMMENT ON SCHEMA` que `pg_dump` emporte — sous `tmp_path`, et on
lit ce que le produit imprime. Le contrôle ne touche rien : il ne détruit
jamais, et les `sudo` / `systemctl` qu'il tenterait sont arrêtés par le
répertoire de refus du garde hermétique (visible en fin de session).
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
CONTROLE = "ops/uninstall_check.sh"

#: Un port de grappe qui n'existe pas. Le contrôle interroge alors zéro serveur
#: — ni celui de production, ni celui d'un voisin — et le test ne dépend
#: d'aucune base. C'est la même discipline que le reste de la suite.
PORT_MUET = "5460"

CERVEAU = "sondeg6"
MON_EMPREINTE = "aaaabbbbccccddddeeeeffff00001111"
AUTRE_EMPREINTE = "99999999999999999999999999999999"


def _dump(chemin: Path, cerveau: str | None, empreinte: str | None) -> Path:
    """Un dump `plain` crédible : l'en-tête de pg_dump, et sa plaque.

    Le contrôle reconnaît un dump à sa FORME (`-- PostgreSQL database dump`),
    et son propriétaire à la plaque gravée dans le commentaire du schéma — que
    `pg_dump` emporte dans chaque copie. Plus de 1 kio, sinon il ne le regarde
    même pas (les archives minuscules ne portent pas de mémoire).
    """
    tete = "--\n-- PostgreSQL database dump\n--\nSET statement_timeout = 0;\n"
    if cerveau and empreinte:
        tete += ("COMMENT ON SCHEMA arac IS 'arac; cerveau=%s; empreinte=%s; "
                 "version=0.1.7';\n" % (cerveau, empreinte))
    chemin.write_text(tete + "-" * 2048, encoding="utf-8")
    return chemin


def _controle(*arguments: str, foyer: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", CONTROLE, CERVEAU, "--port", PORT_MUET, *arguments],
        cwd=str(RACINE), capture_output=True, text=True, timeout=600,
        env=dict(os.environ, HOME=str(foyer)))


def _gestes_imprimes(sortie: str) -> list[str]:
    """Les COMMANDES imprimées sous l'en-tête des gestes, sans les commentaires."""
    if "ORDRE OÙ ILS PASSENT" not in sortie:
        return []
    corps = sortie.split("ORDRE OÙ ILS PASSENT", 1)[1]
    return [l for l in corps.splitlines()
            if l.strip() and not l.lstrip().startswith(("#", "─"))]


@pytest.fixture()
def foyer(tmp_path: Path) -> Path:
    """Un foyer VIDE, distinct du répertoire fouillé.

    Le contrôle fouille le foyer de qui l'appelle. Si le dump y vivait AUSSI,
    il serait trouvé deux fois — deux racines qui se recouvrent — et le test
    mesurerait un artefact de son propre montage plutôt que le produit.
    """
    f = tmp_path / "foyer"
    f.mkdir()
    return f


def test_une_copie_de_memoire_nommee_sans_empreinte_recoit_son_geste(tmp_path, foyer):
    """LE DÉFAUT LUI-MÊME. Sans lui, le rapport nomme et ne prescrit rien."""
    coffre = tmp_path / "coffre"
    coffre.mkdir()
    dump = _dump(coffre / f"adieu-{CERVEAU}-20260101T000000Z.dump",
                 CERVEAU, MON_EMPREINTE)

    vu = _controle("--fouiller", str(coffre), "--gestes", foyer=foyer)

    assert "copie complète de la mémoire" in vu.stdout, vu.stdout[-2000:]
    gestes = _gestes_imprimes(vu.stdout)
    assert any(str(dump) in g for g in gestes), (
        "Le contrôle NOMME cette copie complète de la mémoire et ne prescrit "
        "aucun geste pour elle : le lecteur qui suit le rapport garde son "
        f"cerveau entier sur la machine.\n{vu.stdout[-3000:]}")


def test_un_en_tete_de_gestes_n_est_jamais_suivi_de_rien(tmp_path, foyer):
    """L'INVARIANT, ET IL VAUT POUR TOUTES LES BRANCHES À VENIR.

    Un homonyme vu sur la machine fait taire tous les gestes fondés sur le nom
    — c'est juste. Ce qui ne l'est pas, c'est d'annoncer « LES GESTES, DANS
    L'ORDRE OÙ ILS PASSENT » pour ne rien mettre dessous : le lecteur cherche
    ce qui manque chez lui plutôt que de lire la raison.
    """
    coffre = tmp_path / "coffre"
    coffre.mkdir()
    # (a) la mémoire d'un AUTRE cerveau qui porte notre nom : l'homonyme.
    _dump(coffre / "dump-du-voisin.dump", CERVEAU, AUTRE_EMPREINTE)
    # (b) une archive à notre nom, SANS plaque : reconnue sur son NOM SEUL,
    #     donc retenue dès qu'un homonyme existe.
    _dump(coffre / f"vieux-{CERVEAU}-sans-plaque.sql", None, None)

    vu = _controle("--empreinte", "11112222333344445555666677778888",
                   "--fouiller", str(coffre), "--gestes", foyer=foyer)

    assert "RESTE(S)" in vu.stdout
    if not _gestes_imprimes(vu.stdout):
        assert "AUCUN GESTE" in vu.stdout, (
            "Une liste de gestes vide a été annoncée sans être expliquée. Un "
            "en-tête suivi de rien envoie le lecteur chercher la panne chez "
            f"lui.\n{vu.stdout[-3000:]}")
        assert "empreinte" in vu.stdout


def test_la_commande_de_suite_porte_l_argument_qui_tranche(tmp_path, foyer):
    """UN OUTIL QUI SE CITE LUI-MÊME DOIT SE CITER ENTIER.

    Le rapport sans `--gestes` se ferme sur « Pour les commandes exactes, dans
    le bon ordre : … --gestes ». Cette invitation perdait `--empreinte` —
    c'est-à-dire, de l'aveu du rapport lui-même, « ce qui tranche ». Le lecteur
    recopiait, et obtenait une liste amputée.
    """
    coffre = tmp_path / "coffre"
    coffre.mkdir()
    _dump(coffre / f"adieu-{CERVEAU}-20260101T000000Z.dump", CERVEAU, MON_EMPREINTE)

    vu = _controle("--empreinte", MON_EMPREINTE, "--fouiller", str(coffre),
                   foyer=foyer)

    suite = [l.strip() for l in vu.stdout.splitlines()
             if l.strip().startswith(CONTROLE)]
    assert suite, vu.stdout[-2000:]
    for ligne in suite:
        assert f"--empreinte {MON_EMPREINTE}" in ligne, (
            "La commande de suite laisse tomber l'empreinte, alors que "
            "l'invocation qui l'imprime la porte. Sans elle, ce contrôle "
            "retombe sur le NOM SEUL et n'imprime plus les mêmes gestes.\n"
            f"{ligne}")
        assert f"--port {PORT_MUET}" in ligne


def test_l_empreinte_lue_est_proposee_mais_jamais_glissee_dans_la_commande(
        tmp_path, foyer):
    """CE QUE LE RAPPORT SAIT, IL LE DIT — ET IL NE DÉCIDE PAS À VOTRE PLACE.

    Quand l'appelant n'a pas donné d'empreinte mais que les objets en portent
    une, le rapport la connaît : il l'imprime déjà, objet par objet. Il doit la
    proposer en pied de page, parce que c'est elle qui rendra les gestes
    certains. Il ne doit PAS la coller dans la commande qu'on recopie : ce
    serait promouvoir une reconnaissance PAR LE NOM en certitude par
    l'empreinte, sans que personne n'ait reconnu quoi que ce soit — et c'est le
    geste exact par lequel on détruit la mémoire d'un homonyme.
    """
    coffre = tmp_path / "coffre"
    coffre.mkdir()
    _dump(coffre / f"adieu-{CERVEAU}-20260101T000000Z.dump", CERVEAU, MON_EMPREINTE)

    vu = _controle("--fouiller", str(coffre), foyer=foyer)

    assert MON_EMPREINTE in vu.stdout
    assert re.search(r"SI vous la reconnaissez", vu.stdout), vu.stdout[-2000:]
    suite = [l.strip() for l in vu.stdout.splitlines()
             if l.strip().startswith(CONTROLE)]
    assert suite
    for ligne in suite:
        assert "--empreinte" not in ligne, (
            "L'empreinte LUE dans un fichier a été glissée dans la commande "
            "qu'on recopie sans réfléchir. Reconnaître son empreinte est un "
            f"acte de l'opérateur, pas une déduction de ce script.\n{ligne}")
