"""LE CORPUS DES GARDES DOCUMENTAIRES — et ce qu'il fait quand `git` n'est pas là.

POURQUOI CE MODULE EXISTE
=========================
Deux gardes de ce dépôt — « aucune trace de l'auteur » et « la doc dit vrai » —
se donnent pour corpus *tout ce que `git` transporte*. C'est le bon corpus, et
c'est une leçon payée cinq manches : le Markdown seul laissait survivre dans le
code les faussetés corrigées dans les manuels.

Mais ils l'obtenaient par ``subprocess.run([... "git", "ls-files" ...],
check=True)``, **au niveau du module** — à la ligne ``PERIMETRE = perimetre()``,
qui s'exécute à la COLLECTE. Quelqu'un qui télécharge une archive au lieu de
cloner, ou qui travaille dans une copie privée de son ``.git``, voyait donc
ceci :

    ERROR tests/test_f1_aucune_trace_de_l_auteur.py - subprocess.CalledProcessError
    ERROR tests/test_la_doc_dit_vrai.py - subprocess.CalledProcessError
    !!!!!! Interrupted: 2 errors during collection !!!!!!
    make: *** [Makefile:104: test] Error 2

Pas un test exécuté. Aucune phrase ne disait pourquoi. La suite n'était pas
cassée : elle était **inaccessible**, et un inconnu en conclut que le dépôt ne
marche pas chez lui — c'est-à-dire exactement ce que tous les gardes de ce
dépôt existent pour empêcher.

LA RÈGLE QU'ON SE DONNE ICI
===========================
**Un effondrement muet est interdit.** Il reste deux conduites permises, et ce
module choisit la première :

  1. **le repli explicite** — on continue, par un autre chemin, et on DIT
     lequel, en une phrase que quelqu'un peut lire dans la sortie de `pytest` ;
  2. le refus clair — on s'arrête, et le message enseigne le geste.

Le repli est préférable ici parce que le corpus est *approchable sans `git`* :
un dépôt, c'est d'abord des fichiers sur un disque. Refuser de balayer une
archive téléchargée reviendrait à apprendre à celui qui la lit que la suite ne
le concerne pas.

CE QUE LE REPLI FAIT, EXACTEMENT — et ce qu'il ne fait pas
==========================================================
Il parcourt le disque depuis la racine du dépôt et applique ``.gitignore``
lui-même, par un lecteur volontairement petit dont voici les limites,
écrites plutôt que découvertes :

  · il honore les motifs simples : ``nom``, ``*.ext``, ``dossier/``,
    ``chemin/vers/fichier``, et les réadmissions ``!motif`` ;
  · il n'honore PAS les ``**`` de git, ni les ``.gitignore`` imbriqués, ni
    ``.git/info/exclude``, ni les motifs ancrés par un ``/`` de tête.

Ce dépôt n'utilise aucune de ces quatre formes, et
``test_le_repli_rend_exactement_le_meme_corpus_que_git`` le PROUVE à chaque
passage — là où `git` est disponible, les deux chemins doivent rendre le même
ensemble, au fichier près. Le jour où quelqu'un écrit un motif que ce lecteur
ne sait pas lire, c'est ce test qui rougit, dans un dépôt où `git` marche :
la panne se découvre chez nous, jamais chez l'inconnu.

Hors-ligne : ce module ne lit que des fichiers. Aucun réseau, aucune base.
"""

from __future__ import annotations

import fnmatch
import pathlib
import subprocess
import warnings

RACINE = pathlib.Path(__file__).resolve().parents[1]

#: Les deux régimes possibles. Le second n'est pas un mode dégradé honteux :
#: c'est le régime NORMAL de quiconque a reçu une archive.
REGIME_GIT = "git"
REGIME_DISQUE = "disque"

#: Ce qu'on ne parcourt jamais, quel que soit le régime. `.git` en fait
#: partie : c'est l'historique, pas le dépôt de travail.
DOSSIERS_JAMAIS_PARCOURUS = {".git"}


def _git_rend_la_liste() -> list[str] | None:
    """Ce que `git` rendrait à un inconnu qui clone — ou None s'il ne peut pas.

    ``--cached`` seul rendrait zéro fichier tant que le dépôt n'a pas
    d'historique : le garde serait vert par vacuité, très exactement la panne
    qu'il existe pour empêcher. ``--others --exclude-standard`` ajoute donc ce
    qui partirait au premier ``git add .``.

    Aucun ``check=True`` : c'est lui qui faisait tomber la collecte. On rend
    ``None``, et l'appelant décide — c'est une décision, pas une exception.
    """
    try:
        sortie = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=RACINE, capture_output=True, text=True,
        )
    except (OSError, ValueError):        # `git` absent de la machine
        return None
    if sortie.returncode != 0:           # pas un dépôt, ou dépôt inutilisable
        return None
    return [f for f in sortie.stdout.split("\n") if f]


def _motifs_gitignore() -> tuple[list[str], list[str]]:
    """Les motifs de `.gitignore`, séparés en exclusions et réadmissions."""
    fichier = RACINE / ".gitignore"
    exclus: list[str] = []
    readmis: list[str] = []
    if not fichier.is_file():
        return exclus, readmis
    for ligne in fichier.read_text(encoding="utf-8", errors="ignore").split("\n"):
        motif = ligne.strip()
        if not motif or motif.startswith("#"):
            continue
        (readmis if motif.startswith("!") else exclus).append(motif.lstrip("!"))
    return exclus, readmis


def _motif_atteint(motif: str, rel: str) -> bool:
    """Ce chemin relatif est-il visé par ce motif de `.gitignore` ?

    Trois formes, dans l'ordre où git les distingue : un motif terminé par
    ``/`` vise un DOSSIER (et tout ce qu'il contient) ; un motif qui contient
    un ``/`` vise un chemin ; un motif nu vise un NOM, à n'importe quelle
    profondeur — c'est ce qui fait que ``*.log`` attrape ``logs/a/b.log``.
    """
    parts = rel.split("/")
    if motif.endswith("/"):
        return motif[:-1] in parts[:-1]
    if "/" in motif:
        return fnmatch.fnmatch(rel, motif) or rel.startswith(motif.rstrip("/") + "/")
    return any(fnmatch.fnmatch(p, motif) for p in parts)


def _sans_prefixe_local(chemin: str) -> str:
    """« ./x » et « x » désignent le même fichier.

    Écrit `lstrip("./")`, ce retrait mangeait le point de tête d'un nom
    caché : `.env` devenait `env`, et la question « git l'ignore-t-il ? »
    rendait « non » sur le fichier le plus sensible du dépôt. `lstrip` retire
    des CARACTÈRES, pas un préfixe.
    """
    return chemin[2:] if chemin.startswith("./") else chemin


def _ignore(rel: str, exclus: list[str], readmis: list[str]) -> bool:
    if not any(_motif_atteint(m, rel) for m in exclus):
        return False
    return not any(_motif_atteint(m, rel) for m in readmis)


def _parcours_du_disque() -> list[str]:
    """Le même corpus, obtenu sans `git` : le disque, filtré par `.gitignore`."""
    exclus, readmis = _motifs_gitignore()
    vus: list[str] = []
    for p in RACINE.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(RACINE).as_posix()
        if any(part in DOSSIERS_JAMAIS_PARCOURUS for part in rel.split("/")):
            continue
        if _ignore(rel, exclus, readmis):
            continue
        vus.append(rel)
    return sorted(vus)


#: La phrase que le repli DIT de lui-même. Elle est ici, nommée, pour que le
#: message d'un garde puisse la citer sans la réinventer.
PHRASE_DU_REPLI = (
    "corpus obtenu SANS git : `git ls-files` n'a pas répondu (git absent, ou "
    "ce dossier n'est pas un dépôt — c'est le cas d'une archive téléchargée). "
    "Les gardes documentaires balaient donc le disque, filtré par .gitignore. "
    "Ce n'est pas une panne : la suite tourne, et son corpus est le même à "
    "quelques artefacts près. Pour retrouver le régime nominal : "
    "git init && git add -A"
)


def _decider() -> tuple[list[str], str]:
    depuis_git = _git_rend_la_liste()
    if depuis_git is not None:
        return depuis_git, REGIME_GIT
    warnings.warn(PHRASE_DU_REPLI, UserWarning, stacklevel=2)
    return _parcours_du_disque(), REGIME_DISQUE


_FICHIERS, REGIME = _decider()


def fichiers_du_depot() -> list[str]:
    """Les chemins relatifs de tout ce que le dépôt transporte.

    Un seul appel à `git` par session : la liste est décidée à l'import, et
    `REGIME` dit par quel chemin. Les deux gardes documentaires l'appellent —
    deux corpus qui se ressemblent finissent par diverger, et le jour où ils
    divergent, personne ne sait lequel des deux ment.
    """
    return list(_FICHIERS)


def est_ignore(chemin: str) -> bool:
    """« `git` exclurait-il ce chemin ? » — répondu dans les deux régimes.

    Le garde documentaire pose cette question pour refuser qu'un texte
    déclare « versionné » un fichier que `.gitignore` exclut. En régime
    `git`, on demande à `git`, qui est le seul juge. Sans `git`, la question
    reste POSABLE — c'est la même lecture de `.gitignore` que le repli du
    corpus — et y répondre « non » par défaut aurait désarmé la règle en
    silence, ce qui est la conduite que ce module interdit.
    """
    if REGIME == REGIME_GIT:
        return subprocess.run(
            ["git", "check-ignore", "-q", chemin],
            cwd=RACINE, capture_output=True,
        ).returncode == 0
    exclus, readmis = _motifs_gitignore()
    return _ignore(_sans_prefixe_local(chemin), exclus, readmis)
