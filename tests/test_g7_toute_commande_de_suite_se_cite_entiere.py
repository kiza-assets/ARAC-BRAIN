"""G7 — UNE COMMANDE QUE LE PRODUIT IMPRIME POUR LUI-MÊME SE CITE ENTIÈRE.

CE QUE CE GARDE MESURE, EN UNE PHRASE
=====================================
Quand le bootstrap IMPRIME une invocation de lui-même — « Pour agir : … »,
« relancez : … », « pour tout reprendre : … » —, cette ligne doit atterrir sur
la MÊME grappe et les MÊMES ports que l'invocation qui vient de l'imprimer.

LE DÉFAUT QU'IL EXISTE POUR EMPÊCHER, ET IL EST MESURÉ
======================================================
Une simulation lancée sur une grappe dédiée :

    ARAC_DB_PORT=5640 ARAC_API_PORT=8290 ./bootstrap/bootstrap.sh --dry-run

annonçait « serveur 127.0.0.1:5640 », « Ce cluster PostgreSQL (port 5640) »,
« ports 8290 (API) · 8292 (cockpit) » — puis se terminait ainsi :

    [simulation] Aucun changement n'a été appliqué.
    Pour agir :
        sudo ./bootstrap/bootstrap.sh

C'est la DERNIÈRE ligne que l'utilisateur lit, et la seule qui dise « pour
agir » : c'est donc celle qu'il recopie. Recopiée telle quelle, elle rend
« serveur 127.0.0.1:5432 » — la grappe par défaut de la machine, c'est-à-dire,
sur un serveur qui héberge déjà un cerveau, celle du voisin. Mesuré des deux
côtés, sur la même machine, à la même minute.

Et c'est l'endroit du parcours où l'erreur ne se rattrape pas : une fois le
port retenu dans le coffre, ce bootstrap REFUSE (code 6) d'en changer, parce
que déplacer un cerveau d'une grappe à une autre est une migration de données
(`docs/INSTALLATION.md` §12.f).

CE QU'IL EXIGE, ET COMMENT ON S'Y CONFORME
==========================================
Toute citation de `./bootstrap/bootstrap.sh` dans un texte imprimé passe par
`geste_bootstrap` (`bootstrap/lib/core.sh`), qui reporte les variables
d'implantation posées par l'appelant et que le coffre ne rendra pas tout seul.

Trois formes restent licites, et elles sont NOMMÉES ici plutôt que devinées :
  · la RECETTE de la grappe dédiée, qui porte déjà `ARAC_DB_PORT=<port>` — elle
    n'a rien à reporter, elle enseigne la variable ;
  · le SYNOPSIS de `--help`, qui décrit la commande sans prescrire un pas
    suivant ;
  · les COMMENTAIRES, qui ne s'impriment pas.

POURQUOI CE GARDE EST D'UNE AUTRE NATURE QUE G3
================================================
G3 exige qu'une commande `libpq` imprimée porte `-p` : il regarde ce qui
s'adresse à PostgreSQL. Celui-ci regarde ce que le produit dit de LUI-MÊME.
C'est la même maladie — un nom donné par omission — sur l'outil qui pose le
cerveau plutôt que sur celui qui l'interroge, donc au seul moment du parcours
où la faute ne se répare pas.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]

#: Les fichiers qui PARLENT au nom du bootstrap. `bootstrap/checks/` et `ops/`
#: en sont exclus : ce sont des outils SÉPARÉS, qui tournent sur un cerveau
#: déjà installé — le coffre existe alors, et il rend le port de lui-même.
#: Cette exclusion est un fait vérifié, pas une commodité : voir
#: `test_le_coffre_rend_le_port_a_une_invocation_nue`.
SOURCES = [
    RACINE / "bootstrap" / "bootstrap.sh",
    *sorted((RACINE / "bootstrap" / "lib").glob("*.sh")),
]

#: `./bootstrap/bootstrap.sh` cité en clair, quelle que soit la tête de ligne.
_CITATION = re.compile(r"\./bootstrap/bootstrap\.sh")

#: La recette du §12.f : elle ENSEIGNE `ARAC_DB_PORT`, elle ne le reporte pas.
_RECETTE = re.compile(r"ARAC_DB_PORT=<port>\s+\./bootstrap/bootstrap\.sh")

#: Le synopsis de `--help` : il DÉCRIT l'outil, il ne prescrit pas un pas
#: suivant — personne ne le lit en panne, et une ligne d'exemple qui porterait
#: le port d'une machine qui n'existe pas encore enseignerait le contraire de
#: ce qu'elle veut dire. On le borne à la fonction qui l'imprime.
_DEBUT_AIDE = re.compile(r"^\s*afficher_aide\(\)\s*\{")
_FIN_AIDE = re.compile(r"^\}")

#: Le renvoi vers `--help` lui-même : il ne vise aucune grappe.
_VERS_AIDE = re.compile(r"\./bootstrap/bootstrap\.sh --help")


def _lignes_prescriptives(chemin: Path) -> list[tuple[int, str]]:
    """Les lignes qui citent le bootstrap et prescrivent un geste."""
    dans_aide = False
    trouvees: list[tuple[int, str]] = []
    for n, ligne in enumerate(chemin.read_text(encoding="utf-8").splitlines(), 1):
        if _DEBUT_AIDE.match(ligne):
            dans_aide = True
        elif dans_aide and _FIN_AIDE.match(ligne):
            dans_aide = False
        if dans_aide:
            continue
        if ligne.lstrip().startswith("#"):
            continue          # un commentaire ne s'imprime pas
        if not _CITATION.search(ligne):
            continue
        if "geste_bootstrap" in ligne or "prefixe_invocation" in ligne:
            continue          # se cite entière, par construction
        if _RECETTE.search(ligne):
            continue          # enseigne la variable au lieu de la reporter
        if _VERS_AIDE.search(ligne):
            continue          # `--help` ne s'adresse à aucune grappe
        trouvees.append((n, ligne.rstrip()))
    return trouvees


def test_aucune_citation_du_bootstrap_ne_perd_son_implantation():
    fautes = [(p, n, l) for p in SOURCES for n, l in _lignes_prescriptives(p)]
    assert not fautes, (
        "Ces lignes impriment une invocation du bootstrap sans reporter ce que\n"
        "l'invocation courante a employé. Recopiées sur une machine qui héberge\n"
        "déjà un cerveau, elles s'adressent à la grappe du voisin.\n"
        "Le geste : passer par `geste_bootstrap` (bootstrap/lib/core.sh).\n\n"
        + "\n".join(f"  {p.relative_to(RACINE)}:{n}  {l.strip()}" for p, n, l in fautes)
    )


# ---------------------------------------------------------------------------
# LE COMPORTEMENT, PAS SEULEMENT LA FORME
# ---------------------------------------------------------------------------
#
# Un garde qui n'inspecte que le texte se laisse satisfaire par un
# `geste_bootstrap` qui ne reporterait rien. On exerce donc la fonction
# elle-même, dans un bash nu, sur les quatre cas qui décident.

_SOCLE = """
set -euo pipefail
ARAC_HOME={racine}
source {racine}/bootstrap/lib/ui.sh
source {racine}/bootstrap/lib/core.sh
"""


def _prefixe(tmp_path: Path, env: dict[str, str], coffre: str = "") -> str:
    script = _SOCLE.format(racine=RACINE)
    if coffre:
        script += f'ARAC_ENV_FILE="{coffre}"\n'
    script += "geste_bootstrap \"--from services\"\n"
    # On PART de l'environnement du test — le garde hermétique y a déjà posé
    # son PATH de refus — et on RETIRE les quatre variables d'implantation
    # avant de poser celles du cas : nommer une racine de binaires ici serait
    # exactement le contournement que `test_la_porte_du_sous_processus_est_fermee`
    # existe pour attraper.
    plein = {k: v for k, v in os.environ.items() if not k.startswith("ARAC_")}
    plein.update(env)
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                       env=plein, cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_le_port_pose_par_l_appelant_est_reporte(tmp_path):
    """Sans coffre, ce que l'appelant a posé doit voyager dans la commande."""
    rendu = _prefixe(tmp_path, {"ARAC_DB_PORT": "5640"})
    assert rendu == "sudo ARAC_DB_PORT=5640 ./bootstrap/bootstrap.sh --from services", rendu


def test_les_ports_de_service_voyagent_aussi(tmp_path):
    rendu = _prefixe(tmp_path, {"ARAC_DB_PORT": "5640", "ARAC_API_PORT": "8290"})
    assert "ARAC_DB_PORT=5640" in rendu and "ARAC_API_PORT=8290" in rendu, rendu


def test_une_invocation_nue_reste_nue(tmp_path):
    """Rien à reporter : la ligne ne doit pas s'alourdir d'un rappel inutile."""
    rendu = _prefixe(tmp_path, {})
    assert rendu == "sudo ./bootstrap/bootstrap.sh --from services", rendu


def test_le_coffre_rend_le_port_a_une_invocation_nue(tmp_path):
    """CE QUI JUSTIFIE L'OMISSION — et c'est la moitié la plus importante.

    Quand le coffre porte DÉJÀ la valeur, le bootstrap la relit (`config.sh`,
    « ce que le coffre a retenu fait autorité quand l'appelant se tait ») : la
    reporter n'apprendrait rien et allongerait une ligne qu'on recopie. Ce
    test est ce qui autorise `ops/` et `bootstrap/checks/` à citer le
    bootstrap nu — ils ne tournent que sur un cerveau déjà installé.
    """
    coffre = tmp_path / "arac.env"
    coffre.write_text("ARAC_DB=essai\nARAC_DB_PORT=5640\n", encoding="utf-8")
    rendu = _prefixe(tmp_path, {"ARAC_DB_PORT": "5640"}, coffre=str(coffre))
    assert rendu == "sudo ./bootstrap/bootstrap.sh --from services", rendu

    # …et un port QUI DIFFÈRE du coffre est reporté : c'est le cas où le
    # bootstrap refusera (code 6), et la ligne doit dire pourquoi.
    autre = _prefixe(tmp_path, {"ARAC_DB_PORT": "5999"}, coffre=str(coffre))
    assert "ARAC_DB_PORT=5999" in autre, autre


@pytest.mark.parametrize("fichier", [p for p in SOURCES], ids=lambda p: p.name)
def test_chaque_source_est_syntaxiquement_valide(fichier):
    """Un `$(…)` mal fermé dans une chaîne imprimée casse au pire moment."""
    r = subprocess.run(["bash", "-n", str(fichier)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
