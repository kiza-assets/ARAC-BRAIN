"""LE RIDEAU DE LECTURE NE LIT PAS LE `/proc` D'UN AUTRE PROCESSUS.

CE QUE CE GARDE EMPÊCHE, EN UNE PHRASE
======================================
`/proc/<pid>/environ` d'un service arac est la copie VERBATIM de son coffre :
l'unité systemd d'un cerveau porte ``EnvironmentFile=/etc/arac/<lui>/arac.env``
(`bootstrap/lib/services.sh`), le noyau recopie ce fichier dans l'environnement
du service, et le lire rend le JETON PORTEUR et le DSN avec son mot de passe —
en clair, sans jamais ouvrir `/etc/arac`.

LE DÉFAUT, ET LA PHRASE QUI L'A GARDÉ EN VIE DEUX MANCHES
=========================================================
Le rideau de lecture accordait `/proc` EN ENTIER, et il écrivait sa raison :

    « `/proc` et `/sys` ne portent le cerveau de personne »

C'était faux, et c'est la seconde faute qui coûte le plus cher. Un trou seul se
retrouve en relisant ; un trou AVEC sa justification écrite ne se rouvre jamais,
parce que la ligne a déjà l'air examinée. Le constat a été porté « mineur » une
manche, requalifié « majeur » la suivante, et il est resté ouvert tout ce temps
— exactement le sort qu'on réserve à une exception qui se justifie.

CE QUI EST MESURÉ ICI, ET DANS QUEL RÉGIME
==========================================
Le dépôt tient DEUX barrières, et elles ne disent pas la même chose :

· **Landlock** (`tests/seconde_barriere.py`), quand le noyau la porte. Barrière
  posée, `/proc/<un autre>/environ` est refusé par le NOYAU (EACCES) : un
  processus restreint ne peut plus tracer un processus qui ne l'est pas. Mais
  `/proc/<un autre>/cmdline` et `.../status` se lisent TOUJOURS — mesuré, 10 et
  200 octets rendus, barrière posée. Or `cmdline` porte le DSN de tout
  `psql "postgresql://arac_admin:<mdp>@…"` en cours.
· **Le rideau de Python** (`tests/garde_hermetique.py`), qui est la SEULE maille
  en régime de repli — noyau sans Landlock, macOS, `ARAC_SANS_SECONDE_BARRIERE=1`
  — régime que ce dépôt documente comme supporté, et pour lequel il écrit
  lui-même « la suite ne tient alors que par la porte de Python ».

Ces tests-ci éprouvent le rideau de Python, parce que c'est lui qui doit tenir
seul. La preuve du régime de repli a été jouée à la main avant d'être écrite :
un faux voisin portant `ARAC_BEARER_TOKEN=SENTINELLE-DU-VOISIN` dans son
`environ`, rideau seul, `open('/proc/<lui>/environ')` → avant : la sentinelle
LUE ; après : `RefusDeFichier`.

POURQUOI CE GRAIN-LÀ, ET PAS « FERMER `/proc` »
===============================================
Fermer `/proc` casserait du code RÉEL qui n'a rien demandé :
`control_center/collectors/system_metrics.py` lit `/proc/loadavg` et
`/proc/net/tcp`, `collectors/sobriety.py` fait `os.listdir('/proc')`. On ferme
donc le répertoire d'un AUTRE processus, en entier — `environ` n'est pas seul :
`cmdline` porte les DSN. `/proc/self`, `/proc/thread-self`, notre propre pid et
les pseudo-fichiers globaux passent ce refus-là sans un mot.

LE SECOND TROU, QUE LA PHRASE CI-DESSUS A TENU OUVERT UNE MANCHE DE PLUS
========================================================================
Cette page ajoutait, dans la même phrase : « `fd/`, `root/` et `cwd/` rouvrent
tout le disque par un lien ». C'était vrai — et le lecteur en concluait que ces
trois-là étaient fermés. Ils ne l'étaient QUE POUR UN AUTRE PID.

`/proc/self/root/<chemin absolu>` et `/proc/self/cwd/../<chemin>` sont les
liens magiques de NOTRE PROPRE processus. Ils ne portent aucun chiffre à
comparer ; après `os.path.abspath` — qui est du calcul de TEXTE et ne suit
aucun lien — ils restent sous la racine accordée `/proc` ; et le noyau, lui,
les réécrit vers `/` et vers le répertoire courant, c'est-à-dire vers TOUT LE
DISQUE, sans passer par le `/proc` de personne d'autre.

MESURÉ, RIDEAU SEUL, AVANT LA CORRECTION, sur un faux voisin posé par la
manche (`/var/tmp/faux-voisin-…/arac.env`, jeton `SENTINELLE-…` et DSN avec mot
de passe) : `/proc/self/root/<ce coffre>` LU par `open`, par `pathlib` et par
`cat` en sous-processus ; le coffre ÉCRASÉ ; son dump DÉTRUIT ;
`/proc/self/root/etc/shadow` lu. Après : refusé par les quatre portes.

LE CRITÈRE, ET POURQUOI IL N'EST PAS UNE EXCEPTION DE PLUS
==========================================================
On aurait pu ajouter `self`, `thread-self`, `<notre pid>`, `root`, `cwd`, `fd`
à une liste de préfixes interdits — et manquer le septième. La leçon de dix
manches dit l'inverse : **ne juge pas un chemin sur son texte quand le noyau
juge sur sa résolution.** `_lecture_toleree` soumet donc au MÊME périmètre le
chemin normalisé ET le chemin que `realpath` atteint ; il faut que les deux
passent. Aucun préfixe n'est nommé, et le lien magique qu'on n'a pas listé
tombe comme les autres.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from tests import garde_hermetique as g
from tests.garde_hermetique import RefusHermetique

RACINE = Path(__file__).resolve().parents[1]

#: Un pid qui n'est PAS le nôtre. On ne va chercher aucun service de la machine
#: pour composer cette liste — ce serait énumérer l'hôte, et c'est précisément
#: ce que la suite s'interdit. `1` existe sur tout Linux, et le grand nombre
#: n'existe nulle part : le refus ne doit dépendre d'aucune des deux choses.
AUTRUI = ("/proc/1/environ", "/proc/1/cmdline", "/proc/1/status",
          "/proc/1/maps", "/proc/1/fd/0", "/proc/1/root/etc/arac",
          "/proc/1/cwd", "/proc/1", "/proc/4194303/environ")


@pytest.mark.parametrize("chemin", AUTRUI)
def test_le_proc_d_un_autre_processus_n_est_pas_lisible(chemin):
    """Le coffre du voisin ne se lit pas par la fenêtre de `/proc`.

    On éprouve les deux portes que le rideau enveloppe — `open` (le builtin) et
    `os.open` — parce qu'un garde qui n'en couvre qu'une est un garde qu'on
    contourne par l'autre sans le vouloir.
    """
    assert g._lecture_toleree(chemin) is False
    assert g._donnee_toleree(chemin) is False
    with pytest.raises(RefusHermetique):
        open(chemin, "rb")
    with pytest.raises(RefusHermetique):
        os.open(chemin, os.O_RDONLY)


def test_le_refus_dit_pourquoi_plutot_que_de_dire_non():
    """Un refus qui n'enseigne pas se contourne, puis se désactive.

    Celui-ci doit nommer ce qu'il protège — le coffre, le jeton — et dire ce
    qui RESTE ouvert, sinon le lecteur conclut que `/proc` est fermé et va
    chercher une autre porte pour ce qu'il avait le droit de faire.
    """
    with pytest.raises(RefusHermetique) as capture:
        open("/proc/1/environ", "rb")
    dit = str(capture.value)
    assert "environ" in dit
    assert "coffre" in dit
    assert "/proc/self" in dit


def test_le_lien_de_proc_self_root_ne_rouvre_pas_la_porte():
    """`/proc/self/root` est `/` — et `/proc/self` ne porte pas de chiffre.

    Un rideau qui ne jugerait que le chemin normalisé laisserait passer
    `/proc/self/root/proc/<voisin>/environ` : `abspath` ne suit pas les liens.
    Mesuré avant d'être écrit — c'est pourquoi la résolution réelle est jugée
    elle aussi.
    """
    detour = "/proc/self/root/proc/1/environ"
    assert g._lecture_toleree(detour) is False
    with pytest.raises(RefusHermetique):
        open(detour, "rb")


# ---------------------------------------------------------------------------
# LES LIENS MAGIQUES DE NOTRE PROPRE PROCESSUS
# ---------------------------------------------------------------------------
#
# Ces épreuves-ci ne tiennent que là où `/proc/<pid>/root` EXISTE et est un
# lien, c'est-à-dire sous Linux. Ce n'est pas une commodité : le vecteur lui
# même est un lien magique du `procfs` de Linux, et il n'existe pas sur un
# macOS, qui n'a pas de `/proc` du tout. On le dit plutôt que de laisser croire
# à une couverture universelle.
_A_DES_LIENS_MAGIQUES = os.path.islink("/proc/self/root")
sans_proc = pytest.mark.skipif(
    not _A_DES_LIENS_MAGIQUES,
    reason="pas de /proc/<pid>/root sur cette machine : le vecteur n'existe pas")

#: Les trois noms sous lesquels NOTRE PROPRE processus se désigne. Aucun ne
#: porte le chiffre d'un tiers ; c'est très exactement pour cela que le refus
#: qui comptait les pids ne pouvait pas les voir.
NOUS_MEMES = ("/proc/self", "/proc/thread-self", f"/proc/{os.getpid()}")

#: Des endroits de l'hôte que la suite n'a jamais eu le droit de toucher. Aucun
#: nom de cerveau réel : `/etc/arac/<imaginaire>` suffit à poser la question, et
#: `/etc/shadow` est le témoin qui existe sur toute machine Linux.
DEHORS = ("/etc/shadow", "/etc/arac/cerveau_imaginaire_du_garde/arac.env",
          "/var/backups/arac", "/root/.pgpass", "/etc/ssl/private")


@sans_proc
@pytest.mark.parametrize("nous", NOUS_MEMES)
@pytest.mark.parametrize("dehors", DEHORS)
def test_le_lien_magique_de_notre_propre_processus_ne_rouvre_pas_le_disque(
        nous, dehors):
    """`/proc/self/root/etc/…` s'écrit dans `/proc` et ouvre `/etc`.

    Quatre portes éprouvées, parce qu'un garde qui n'en couvre que trois se
    contourne par la quatrième sans même le vouloir : `_lecture_toleree`, le
    `open` du langage, `os.open`, et le CHEMIN remis à un sous-processus.
    """
    detour = nous + "/root" + dehors
    assert g._lecture_toleree(detour) is False
    assert g._donnee_toleree(detour) is False
    with pytest.raises(RefusHermetique):
        open(detour, "rb")
    with pytest.raises(RefusHermetique):
        os.open(detour, os.O_RDONLY)
    with pytest.raises(RefusHermetique):
        subprocess.run(["cat", detour], capture_output=True)


@sans_proc
def test_le_lien_magique_du_repertoire_courant_ne_rouvre_pas_le_disque():
    """`/proc/self/cwd/../x` : le `..` que `abspath` replie et que le noyau suit.

    C'est la forme la plus discrète des deux, et celle qu'un garde textuel ne
    peut pas voir : `abspath` replie le `..` AVANT le lien et rend
    `/proc/self/x`, qui est dans le périmètre ; le noyau, lui, résout d'abord
    `cwd` — le répertoire courant — puis remonte d'un cran depuis LÀ. Les deux
    chemins n'ont plus rien à voir l'un avec l'autre.
    """
    parent = os.path.dirname(os.getcwd().rstrip("/")) or "/"
    detour = "/proc/self/cwd/../"
    # Ce que le texte prétend, et ce que le noyau atteint : on le CONSTATE au
    # lieu de le supposer, sinon l'épreuve pourrait passer pour une raison
    # étrangère à ce qu'elle croit mesurer.
    assert os.path.abspath(detour).rstrip("/") == "/proc/self"
    assert os.path.realpath(detour).rstrip("/") == parent.rstrip("/")
    if g._lecture_toleree(parent):
        pytest.skip(f"le parent du répertoire courant ({parent}) est lui-même "
                    "dans le périmètre : ce détour n'ouvre rien")
    assert g._lecture_toleree(detour) is False
    with pytest.raises(RefusHermetique):
        os.listdir(detour)


@sans_proc
@pytest.mark.parametrize("nous", NOUS_MEMES)
def test_le_lien_magique_ne_rouvre_ni_l_ecriture_ni_l_effacement(nous):
    """Écrire est pire que lire, et le même détour y menait.

    Les chemins visés n'existent pas : si ce garde tombait, l'appel échouerait
    en `ENOENT` sans rien abîmer. Une épreuve de destruction ne doit pas
    pouvoir détruire quand elle échoue.
    """
    absent = "/var/tmp/arac-ce-chemin-n-existe-pas-lew/temoin"
    detour = nous + "/root" + absent
    assert not os.path.exists(absent)
    with pytest.raises(RefusHermetique):
        os.unlink(detour)
    with pytest.raises(RefusHermetique):
        os.mkdir(detour)
    with pytest.raises(RefusHermetique):
        os.rename(detour, detour + "-bis")


@sans_proc
def test_le_refus_du_lien_magique_montre_la_reecriture_du_noyau():
    """Un refus qui n'explique pas le détour envoie chercher un autre détour.

    Celui-ci doit dire les deux chemins — celui qu'on écrit et celui qui
    s'ouvre —, sans quoi le lecteur croit à un caprice sur `/proc`, qui est
    pourtant accordé.
    """
    with pytest.raises(RefusHermetique) as capture:
        open("/proc/self/root/etc/shadow", "rb")
    dit = str(capture.value)
    assert "/etc/shadow" in dit, "le refus ne nomme pas ce qui s'ouvrait"
    assert "lien" in dit.lower() or "réécrit" in dit


@sans_proc
@pytest.mark.parametrize("nous", NOUS_MEMES)
def test_notre_propre_processus_reste_lisible_par_ses_liens_legitimes(nous):
    """Le grain reste fin : ce qui se résout DANS le périmètre passe toujours.

    `/proc/self/cwd` est le dépôt, `/proc/self/root/<le dépôt>` est le dépôt :
    le critère ne ferme pas les liens magiques, il ferme ce qu'ils ATTEIGNENT
    hors du périmètre. Un garde qui refuserait les deux serait débranché.
    """
    assert g._lecture_toleree(nous + "/status") is True
    assert g._lecture_toleree(nous + "/cwd") is True
    assert g._lecture_toleree(nous + "/root" + str(RACINE)) is True
    assert g._lecture_toleree(nous + "/root" + str(RACINE / "Makefile")) is True
    with open(nous + "/root" + str(RACINE / "Makefile"), "rb") as fh:
        assert fh.read(4)


@pytest.mark.parametrize("chemin", [
    "/proc/self/status",
    "/proc/thread-self/status",
    "/proc/meminfo",
    "/proc/loadavg",
    "/proc/net/tcp",
    "/proc/cpuinfo",
])
def test_la_sonde_legitime_passe_toujours(chemin):
    """Le grain doit être fin, sinon il ne survit pas à sa première gêne.

    Ces chemins-là sont ceux que le code TESTÉ ouvre pour de vrai
    (`system_metrics.py` lit `/proc/loadavg` et `/proc/net/tcp`). Un garde qui
    les refuserait serait débranché à la première session — et c'est ainsi
    qu'on perd une défense, pas par une attaque.
    """
    assert g._lecture_toleree(chemin) is True
    if os.path.exists(chemin):
        with open(chemin, "rb") as fh:
            fh.read(16)


def test_notre_propre_processus_reste_lisible():
    """On ne se ferme pas à soi-même : le pid courant passe, par les deux noms."""
    assert g._lecture_toleree(f"/proc/{os.getpid()}/status") is True
    assert g._lecture_toleree(f"/proc/{os.getpid()}/environ") is True
    with open(f"/proc/{os.getpid()}/status", "rb") as fh:
        assert fh.read(6)
    # `/proc` LUI-MÊME SE LISTE, et c'est nécessaire : `collectors/sobriety.py`
    # fait exactement cet appel pour compter les `claude` en cours. Le grain
    # porte sur le contenu du répertoire d'un tiers, pas sur son existence.
    assert [p for p in os.listdir("/proc") if p.isdigit()]


def test_le_sous_processus_ne_recoit_pas_le_proc_du_voisin_en_argument():
    """Lire n'est pas la seule porte : `cat /proc/<lui>/environ` en est une.

    Le garde des sous-processus juge les CHEMINS passés en argument avec le
    même périmètre que la lecture. Fermer l'un sans l'autre laisserait la
    moitié du trou — et c'est la moitié qui s'écrit en une ligne de shell.
    """
    with pytest.raises(RefusHermetique):
        subprocess.run(["cat", "/proc/1/environ"], capture_output=True)


def test_la_raison_ecrite_ne_redevient_pas_fausse():
    """LE GARDE DE LA PHRASE, ET C'EST LUI QUI COMPTE LE PLUS.

    Le trou se referme en huit lignes de code. Ce qui l'avait tenu ouvert deux
    manches, c'est la phrase qui le justifiait : « `/proc` et `/sys` ne portent
    le cerveau de personne ». Tant que cette phrase est là, personne ne relit la
    ligne qu'elle couvre. On refuse donc mécaniquement son retour, et on exige
    que la raison écrite nomme ce qui est vrai : `environ`, et le coffre.

    Ce garde-ci vise le texte, pas le code, et c'est délibéré : le dépôt a déjà
    payé deux fois pour avoir cru qu'une justification n'était que du
    commentaire.
    """
    source = (RACINE / "tests" / "garde_hermetique.py").read_text(encoding="utf-8")
    # Le texte se juge en PHRASES, pas en lignes : la phrase fautive tenait sur
    # deux lignes de commentaire, et un garde qui lit ligne à ligne se contourne
    # en poussant un retour à la ligne au bon endroit. On recolle donc les
    # commentaires avant de lire.
    plat = re.sub(r"\s*\n\s*#:?\s*", " ", source)
    fautives = [m.group(0) for m in
                re.finditer(r"[^.]*?/proc[^.]{0,80}?ne porten?t? le cerveau "
                            r"de personne", plat)]
    for phrase in fautives:
        # UNE CITATION N'EST PAS UNE JUSTIFICATION. Le post-mortem de ce trou
        # cite la phrase fausse — il faut bien la nommer pour la condamner. Ce
        # qu'on refuse, c'est qu'elle revienne comme raison VIVANTE : on exige
        # donc qu'elle soit, partout où elle apparaît, à portée de main du mot
        # qui la déclare fausse.
        autour = plat[max(0, plat.index(phrase) - 400):
                      plat.index(phrase) + len(phrase) + 400]
        assert "FAUX" in autour or "faux" in autour, (
            "La justification fausse est revenue comme raison vivante : "
            "« /proc ne porte le cerveau de personne ». /proc/<pid>/environ "
            "d'un service arac EST son coffre — jeton porteur et DSN avec mot "
            f"de passe. Voir tests/{Path(__file__).name}. Phrase : "
            f"{phrase.strip()[:200]}")
    assert "_proc_d_un_autre" in source
    # LE CRITÈRE LUI-MÊME, ET PAS SEULEMENT SON EFFET. Les épreuves ci-dessus
    # mesurent des chemins ; celle-ci refuse que le rideau revienne à un
    # jugement de TEXTE, qui les laisserait toutes passer par une écriture
    # qu'on n'a pas listée. `abspath` calcule, `realpath` demande au disque :
    # c'est la seule des deux qui juge la même chose que le noyau.
    assert "_ce_que_le_noyau_atteint" in source, (
        "Le rideau ne juge plus la RÉSOLUTION des chemins. `abspath` est du "
        "calcul de texte : `/proc/self/root/etc/arac/<voisin>/arac.env` reste "
        "pour lui un chemin de `/proc`, et ouvre le coffre du voisin.")
    assert "realpath" in source
    assert "EnvironmentFile" in source, (
        "La raison VRAIE a disparu : elle doit dire d'où vient le coffre dans "
        "l'environnement d'un service (EnvironmentFile=/etc/arac/<lui>/arac.env)."
    )
