"""Le juge ne tire pas au sort — aucun texte n'entre dans un `grep` par un tuyau.

CE QUE CE FICHIER GARDE, ET POURQUOI IL EXISTE
==============================================

`make acceptance` est le critère de réussite du framework. Il a condamné une
exécution sur sept, et son motif était démenti six lignes plus bas par ce qu'il
imprimait lui-même : « le contrôle des restes ne nomme pas le gabarit » suivi,
dans le même écran, de la sortie du contrôle qui nommait le gabarit.

LA CAUSE, ET ELLE N'EST PAS DANS LE CODE MESURÉ
-----------------------------------------------

`tests/acceptance/acceptance.sh` arme `set -o pipefail`. Ses conditions
s'écrivaient :

    printf '%s' "$sortie" | grep -q MOTIF

`grep -q` sort au PREMIER appariement et ferme sa lecture. Le producteur, qui
n'a pas fini d'écrire, reçoit alors SIGPIPE et meurt avec le code 141 ;
`pipefail` remonte 141 comme code du pipeline, et la condition devient FAUSSE
alors que le motif est là. Ce n'est pas une preuve verte par construction :
c'est une preuve ROUGE par construction, et c'est pire — un juge qui condamne
au hasard, on apprend à le relancer jusqu'à l'acquittement, et le jour où la
chose mesurée cassera vraiment, son rouge sera lu comme « encore le hasard ».

MESURÉ, sur la sortie réelle de `ops/uninstall_check.sh --gestes` (7 458
octets) et sur la condition exacte de l'étape 8 :

    forme au tuyau      → 10 condamnations à tort sur 3 000 (code 141)
    forme en chaîne ici →  0 condamnation  à tort sur 3 000

Dix-sept conditions de cette forme vivaient dans `acceptance.sh`, dont une
jouée cinq fois par exécution : de quoi condamner une exécution sur sept.

LE REMÈDE, ET IL EST DE FORME
-----------------------------

On ne retire pas `pipefail` — il attrape de vraies pannes. On retire le TUYAU :

    grep -q MOTIF <<<"$sortie"

Une chaîne ici ne crée aucun processus producteur : bash place le texte dans le
descripteur avant d'exécuter `grep`. Aucun SIGPIPE n'est possible, et le code
rendu est celui de `grep` seul.

TROIS TESTS, ET LE PREMIER REJOUE LE MÉCANISME
   1. le mécanisme est REPRODUIT par exécution — la forme au tuyau rend 141,
      la forme en chaîne ici rend 0. Un test qui se contenterait d'interdire un
      motif garderait une interdiction dont plus personne ne saurait la raison ;
   2. aucun fichier de `tests/` qui arme `pipefail` ne fait entrer du texte
      dans un `grep -q` par un tuyau ;
   3. les fichiers HORS de ce dossier qui portent encore la forme fragile sont
      NOMMÉS ici, un par un. La liste ne peut que rétrécir : toute nouvelle
      occurrence, où que ce soit dans le dépôt, rend ce test rouge.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[1]

#: Un tuyau shell qui alimente `grep` — jamais `||`, jamais un `|` cité.
_TUYAU_VERS_GREP = re.compile(r"(?<![|&>])\|(?!\|)\s*grep\b")
#: Une option `-q` de `grep` (seule ou groupée : -q, -qx, -qi, -qE, -qF…).
_OPTION_Q = re.compile(r"(?<![\w-])-[A-Za-z]*q")
#: Ce qui est entre guillemets n'est pas de la syntaxe shell.
_CITATIONS = re.compile(r"'[^']*'|\"[^\"]*\"")

#: LES SURVIVANCES CONNUES, HORS DE CE DOSSIER — chacune nommée avec sa raison.
#:
#: Ce lot ne possède que `tests/`, `tests/acceptance/` et le `Makefile`. Les
#: trois fichiers ci-dessous portent la même forme fragile et appartiennent à
#: d'autres périmètres. Les taire les rendrait invisibles ; les corriger d'ici
#: serait déborder. On les nomme, et la liste est FERMÉE : toute occurrence qui
#: n'y figure pas fait rougir ce test.
SURVIVANCES = {
    "bootstrap/bootstrap.sh": (
        "`locale -a | grep -qix 'C.utf8'` — un faux négatif ferait croire que "
        "la machine n'a pas de locale UTF-8 et déclencherait un repli inutile."
    ),
    "deploy/ssh/rendre-pont.sh": (
        "`printf '%s' \"$rendu\" | grep -q '^Match User '` — exactement la "
        "forme mesurée à 10/3 000 ; un faux négatif refuserait un fichier de "
        "configuration SSH pourtant correct."
    ),
    "mac/arac-pont.sh": (
        "`launchctl list | grep -q \"$etiquette\"` — un faux négatif ferait "
        "conclure que l'agent n'est pas chargé alors qu'il l'est."
    ),
}


def _fichiers_shell() -> list[Path]:
    """Les fichiers `.sh` du dépôt — suivis par git, ou simplement là.

    Sur un clone sans `.git`, `git ls-files` ne répond pas : on retombe sur le
    disque. Un test structurel qui ne s'exécuterait que dans un dépôt git ne
    garderait rien chez celui qui télécharge une archive.
    """
    try:
        sortie = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=_RACINE, capture_output=True, text=True, timeout=30, check=False,
        )
        noms = [n for n in sortie.stdout.split("\n") if n.strip()]
        if sortie.returncode == 0 and noms:
            return [_RACINE / n for n in noms if n.endswith(".sh")]
    except (OSError, subprocess.SubprocessError):
        pass
    ignores = {".git", ".venv", "node_modules", "__pycache__"}
    return [
        p for p in _RACINE.rglob("*.sh")
        if not (ignores & set(p.relative_to(_RACINE).parts))
    ]


def _occurrences(fichier: Path) -> list[tuple[int, str]]:
    """Les lignes où du texte entre dans un `grep -q` par un tuyau."""
    texte = fichier.read_text(encoding="utf-8", errors="replace")
    if "pipefail" not in texte:
        return []
    trouvees = []
    for numero, ligne in enumerate(texte.splitlines(), 1):
        nue = _CITATIONS.sub("", ligne)
        appariement = _TUYAU_VERS_GREP.search(nue)
        if appariement and _OPTION_Q.search(nue[appariement.start():]):
            trouvees.append((numero, ligne.strip()))
    return trouvees


# ---------------------------------------------------------------------------
# 1. LE MÉCANISME, REJOUÉ — pas décrit, exécuté
# ---------------------------------------------------------------------------

_MECANISME = r"""
set -uo pipefail
# Un producteur qui a encore quelque chose à écrire quand `grep -q` s'en va.
{ printf 'MOTIF\n'; sleep 0.05; printf 'reste\n'; } | grep -q MOTIF
echo "tuyau=$?"
texte="$(printf 'MOTIF\nreste\n')"
grep -q MOTIF <<<"$texte"
echo "chaine_ici=$?"
"""


def test_le_mecanisme_est_reel_et_la_chaine_ici_en_est_exempte():
    """La forme au tuyau rend 141 ; la forme en chaîne ici rend 0."""
    r = subprocess.run(["bash", "-c", _MECANISME],
                       capture_output=True, text=True, timeout=60)
    sortie = r.stdout
    assert "tuyau=141" in sortie, (
        "Le mécanisme n'a pas été reproduit. Attendu « tuyau=141 » : `grep -q` "
        "ferme le tuyau, le producteur meurt de SIGPIPE, et `pipefail` remonte "
        f"141 comme code de la CONDITION.\nObtenu :\n{sortie}"
    )
    assert "chaine_ici=0" in sortie, (
        "La chaîne ici doit rendre le code de `grep` seul, quel que soit le "
        f"texte.\nObtenu :\n{sortie}"
    )


def test_la_chaine_ici_ne_condamne_jamais_a_tort_sur_une_charge_reelle():
    """500 tours sur une charge de la taille d'une sortie d'`uninstall_check`."""
    script = r"""
set -uo pipefail
texte="MOTIF_EN_TETE
$(head -c 7000 /dev/zero | tr '\0' 'x')"
faux=0
for ((i=0;i<500;i++)); do
    grep -q 'MOTIF_EN_TETE' <<<"$texte" || faux=$((faux+1))
done
echo "faux=$faux"
"""
    r = subprocess.run(["bash", "-c", script],
                       capture_output=True, text=True, timeout=120)
    assert "faux=0" in r.stdout, (
        "La forme retenue doit être STABLE : c'est tout l'objet de ce lot.\n"
        f"Obtenu :\n{r.stdout}\n{r.stderr}"
    )


# ---------------------------------------------------------------------------
# 2. LE DOSSIER QUE CE LOT POSSÈDE
# ---------------------------------------------------------------------------

def test_aucun_texte_n_entre_dans_un_grep_par_un_tuyau_sous_tests():
    coupables = []
    for fichier in _fichiers_shell():
        chemin = fichier.relative_to(_RACINE).as_posix()
        if not chemin.startswith("tests/"):
            continue
        for numero, ligne in _occurrences(fichier):
            coupables.append(f"{chemin}:{numero}: {ligne}")
    assert not coupables, (
        "Sous `pipefail`, `grep -q` ferme le tuyau et le producteur meurt de "
        "SIGPIPE : la condition rend 141 ALORS QUE LE MOTIF EST LÀ.\n"
        "Donnez le texte à `grep` par une chaîne ici :\n"
        "    grep -q MOTIF <<<\"$variable\"\n"
        "Si le texte vient d'une commande, capturez-la d'abord dans une "
        "variable.\n\n" + "\n".join(coupables)
    )


def test_l_acceptance_arme_toujours_pipefail():
    """Sans `pipefail`, l'interdiction ci-dessus n'aurait plus de raison d'être.

    Et sans elle, on la retirerait — puis `pipefail` reviendrait, et la panne
    avec lui. On garde donc les deux ensemble.
    """
    texte = (_RACINE / "tests/acceptance/acceptance.sh").read_text(encoding="utf-8")
    assert re.search(r"^set -uo pipefail$", texte, re.M), (
        "tests/acceptance/acceptance.sh n'arme plus `pipefail`. Si c'est "
        "voulu, retirez aussi ce garde et dites POURQUOI dans le CHANGELOG."
    )


# ---------------------------------------------------------------------------
# 3. CE QUI RESTE AILLEURS — nommé, et la liste ne peut que rétrécir
# ---------------------------------------------------------------------------

def test_les_survivances_hors_perimetre_sont_nommees_et_la_liste_est_fermee():
    trouvees: dict[str, list[str]] = {}
    for fichier in _fichiers_shell():
        chemin = fichier.relative_to(_RACINE).as_posix()
        if chemin.startswith("tests/"):
            continue
        lignes = _occurrences(fichier)
        if lignes:
            trouvees[chemin] = [f"{n}: {l}" for n, l in lignes]

    inconnues = {c: l for c, l in trouvees.items() if c not in SURVIVANCES}
    assert not inconnues, (
        "UNE NOUVELLE OCCURRENCE DE LA FORME FRAGILE. Elle rendra un jour un "
        "verdict faux, au hasard, avec un motif démenti par sa propre sortie.\n"
        "Écrivez `grep -q MOTIF <<<\"$variable\"`, ou — si vous ne pouvez "
        "vraiment pas — ajoutez le fichier à SURVIVANCES avec sa raison.\n\n"
        + "\n".join(f"{c}\n    " + "\n    ".join(l) for c, l in inconnues.items())
    )


@pytest.mark.parametrize("chemin", sorted(SURVIVANCES))
def test_une_survivance_corrigee_sort_de_la_liste(chemin: str):
    """La liste ne doit pas pourrir : une entrée guérie doit être retirée.

    C'est la même discipline que `tests/test_depot_propre.py` applique à sa
    table d'artefacts. Une liste d'exceptions qu'on n'entretient pas devient
    une liste de fichiers qu'on ne regarde plus.
    """
    fichier = _RACINE / chemin
    if not fichier.exists():
        pytest.skip(f"{chemin} n'existe plus dans ce dépôt")
    assert _occurrences(fichier), (
        f"{chemin} ne porte plus la forme fragile — excellente nouvelle.\n"
        f"Retirez-le de SURVIVANCES dans {Path(__file__).name} : une liste "
        "d'exceptions qui garde des entrées guéries finit par ne plus rien "
        "garder du tout."
    )
