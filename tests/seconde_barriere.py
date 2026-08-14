"""LA SECONDE BARRIÈRE — celle qui rend une évasion SANS EFFET.

POURQUOI CE FICHIER EXISTE
==========================

Le garde hermétique est une PORTE, et on sait qu'elle a des mailles. Quatre
manches l'ont montré, chaque fois de la même façon : une maille fermée là où on
a regardé, ouverte juste à côté. La cinquième le montrera encore — parce que le
dispositif est écrit en espace utilisateur, dans le processus même qu'il garde,
et que ce processus peut toujours écrire ``ctypes.CDLL("libc.so.6").fopen``.

`ZONES_NON_COUVERTES_DE_LA_PORTE` le déclare depuis le début, dans sa dernière
zone : « toutes les évasions ci-dessus n'atteignent un cerveau réel que parce
que le processus en a le DROIT ». C'était vrai, c'était honnête, et cela restait
un constat. Ce fichier en fait un dispositif.

LE BUT N'EST PAS UN GARDE PARFAIT
=================================

Le but est qu'aucun test ne puisse toucher la base, les services ou les fichiers
d'un cerveau réel. Puisqu'aucune liste ne sera jamais complète, on cherche une
barrière qui ne dépende d'AUCUNE liste : quelque chose qui, une fois posé, rende
sans effet les évasions qu'on n'a pas vues — y compris celles qui n'existent pas
encore.

Le noyau Linux en offre une depuis la version 5.13, et elle est faite très
exactement pour cela : **Landlock**. Un processus NON PRIVILÉGIÉ peut s'imposer
à lui-même, et à toute sa descendance, une restriction du système de fichiers.
Trois propriétés en font la bonne réponse ici :

1. **Elle s'applique au NOYAU, pas à Python.** `head`, `rm -rf`, `find -delete`,
   `ctypes.CDLL("libc.so.6").fopen`, une extension C, un binaire statique, un
   chemin calculé à l'exécution : tous passent par `openat(2)`, et tous sont
   arrêtés là. Le rideau de lecture écrit en Python ne voit que ce qu'un test
   écrit en Python ; celui-ci voit tout ce qui touche un inode.
2. **Elle est héréditaire et irréversible.** Un descendant à n'importe quelle
   profondeur — le `bash` d'un script, le `python` qu'il lance, le fils de ce
   fils — la porte encore. Personne ne peut la retirer, pas même le processus
   qui l'a posée : il n'y a pas de geste pour l'annuler.
3. **Elle ne peut rien casser d'autre que nous.** Landlock RETIRE des droits au
   processus appelant et à ses enfants. Elle n'en donne jamais, elle ne touche
   aucun autre processus, aucun montage, aucun fichier. C'est ce qui la
   distingue d'un espace de noms de montage : masquer `/etc/arac` dans un
   *mount namespace* mal propagé le masquerait pour l'API de PRODUCTION. Ici,
   le pire échec possible est que notre propre suite se refuse un fichier.

LE PÉRIMÈTRE N'EST PAS UN SECOND PÉRIMÈTRE
==========================================

Il aurait été facile d'écrire ici une seconde liste de répertoires — et ç'aurait
été la faute que ce dépôt corrige depuis cinq manches, commise une fois de plus.
Le périmètre appliqué au noyau est **exactement celui que le rideau de lecture
déclare déjà**, et cela veut dire **CINQ** constantes, pas quatre :
`garde_hermetique._racines_de_lecture()`, `_FICHIERS_DE_LA_MACHINERIE`,
`_RACINES_SANS_CERVEAU`, `_PORTES_DE_DEV` — **et `_RETRANCHEES`, celle qui
protège les voisins**, qui se SOUSTRAIT.

CETTE PHRASE A NOMMÉ QUATRE CONSTANTES ET OUBLIÉ LA CINQUIÈME, ET LE CODE
FAISAIT COMME ELLE. Conséquence, mesurée par `ctypes` — qui ne passe par aucun
garde de Python, donc qui mesure le NOYAU et rien d'autre — barrière annoncée
« POSÉE » : **quatre des onze zones retranchées restaient accordées en lecture
au noyau**. `_racines_de_lecture()` contient `/usr` (par `sys.base_prefix`) et
`/usr/lib` ; `poser_depuis_le_garde` unissait sans jamais retrancher ; le noyau
ouvrait donc encore `/usr/local` — dont le commentaire de `_RETRANCHEES` dit
lui-même qu'il « porte du cerveau », le bootstrap y installant
`arac-depot-sauvegardes` —, `/usr/lib/systemd`, `/usr/lib/tmpfiles.d` et
`/usr/lib/sysusers.d`. La seconde barrière n'était pas le périmètre du rideau :
elle en était une version plus large, et une défense en profondeur plus large
que la porte qu'elle double ne double rien du tout.

Landlock n'ayant pas de règle négative, on ne soustrait pas : on n'accorde plus
la racine qui contient une zone retranchée, on accorde ses enfants,
récursivement, en sautant la zone (`_eclater_autour_des_retranchees`). Le
périmètre calculé est rendu par `perimetre_depuis_le_garde()`, et c'est CE
calcul-là que le contrôle relit — jamais une copie recomposée à la main.

Une seule définition de « ce que la suite a le droit de toucher », deux
exécutions : l'une en Python, qui explique et enseigne ; l'autre dans le noyau,
qui ne discute pas.

Ce paragraphe disait « un espion posé sur `open` a compté zéro ouverture hors de
lui ». Ce n'est plus vrai depuis que le périmètre s'est RESSERRÉ : 241
ouvertures sont refusées par session, toutes sous le `/proc/<pid>/` d'un tiers,
et le détail est écrit là où la mesure vit — au-dessus de `LECTURES_DECLAREES`.
Aucune n'est un besoin : chacune tombe dans un code qui a son chemin
d'indisponibilité. Les deux couches ne coïncident d'ailleurs plus exactement, et
c'est écrit dans `poser_depuis_le_garde` : une règle Landlock s'attache à un
répertoire, elle ne sait pas dire « le mien ».

CE QU'ELLE NE FAIT PAS, ET C'EST DIT ICI PLUTÔT QUE DÉCOUVERT
=============================================================

· **Elle ne ferme pas le réseau ni la base.** L'ABI 4 de Landlock sait restreindre
  `connect(2)` en TCP, mais la suite ouvre et joint de vrais ports de la boucle
  locale pour s'éprouver elle-même (`test_g2` en ouvre un). Fermer le TCP au
  noyau casserait ces épreuves. La socket UNIX de PostgreSQL, elle, n'est pas
  gouvernée par les droits de fichier de Landlock. Le réseau et la base restent
  donc gardés par la porte de Python — et par le compte, qui reste la barrière
  ultime.
· **Elle ne remplace pas un compte non privilégié.** Sous `root`, un test peut
  encore parler à `systemd` et envoyer un signal. Landlock ferme les FICHIERS,
  c'est-à-dire le coffre et la sauvegarde — la moitié qui coûte le plus cher, et
  celle qu'aucune des quatre manches n'avait su fermer pour de bon.

  CETTE PHRASE DISAIT AUSSI « lire `/proc/<pid>/environ` d'un service voisin »,
  ET C'EST DEVENU FAUX — mesuré, dans les deux sens. Une fois la barrière posée,
  `open('/proc/<un autre>/environ')` rend EACCES : un processus restreint par
  Landlock ne peut plus tracer un processus qui ne l'est pas, et lire l'`environ`
  d'autrui demande `PTRACE_MODE_READ`. Mais la protection s'arrête là :
  `/proc/<un autre>/cmdline` et `/proc/<un autre>/status` se lisent TOUJOURS
  (mesuré : 10 et 200 octets rendus, barrière posée), et `cmdline` porte le DSN
  de tout `psql "postgresql://arac_admin:<mdp>@…"` en cours. Ce qui ferme le
  répertoire de processus d'un tiers est donc le rideau de Python
  (`garde_hermetique._proc_d_un_autre`), pas le noyau — et le noyau ne le ferme
  pas du tout en régime de repli.
· **Elle n'existe pas partout.** Noyau trop ancien, Landlock désactivé, macOS :
  la fonction rend alors une phrase qui le dit, et la suite continue avec la
  seule porte de Python. Une barrière absente qu'on annonce vaut mieux qu'une
  barrière supposée.
"""

from __future__ import annotations

import ctypes
import os
import sys

#: Les numéros d'appel système de Landlock. Ils sont les mêmes sur x86-64, sur
#: arm64 et sur les autres architectures récentes : les trois ont été ajoutés
#: d'un bloc en 5.13, à la suite des numéros existants.
_NR_CREATE_RULESET = 444
_NR_ADD_RULE = 445
_NR_RESTRICT_SELF = 446

_PR_SET_NO_NEW_PRIVS = 38
_LANDLOCK_CREATE_RULESET_VERSION = 1 << 0
_LANDLOCK_RULE_PATH_BENEATH = 1
_O_PATH = 0o10000000
_O_CLOEXEC = 0o2000000

#: Les droits de fichier que Landlock sait gouverner, par ordre d'apparition.
#: On les nomme pour pouvoir dire ce qu'on accorde — un droit accordé en bloc
#: sous un chiffre hexadécimal est un droit que personne ne relit.
EXECUTE = 1 << 0
WRITE_FILE = 1 << 1
READ_FILE = 1 << 2
READ_DIR = 1 << 3
REMOVE_DIR = 1 << 4
REMOVE_FILE = 1 << 5
MAKE_CHAR = 1 << 6
MAKE_DIR = 1 << 7
MAKE_REG = 1 << 8
MAKE_SOCK = 1 << 9
MAKE_FIFO = 1 << 10
MAKE_BLOCK = 1 << 11
MAKE_SYM = 1 << 12
REFER = 1 << 13
TRUNCATE = 1 << 14

#: Le dernier droit connu de chaque version de l'interface. On ne demande jamais
#: à gouverner un droit que le noyau courant ignore : il refuserait tout le
#: jeu de règles, et la barrière ne serait pas posée du tout.
_DERNIER_DROIT_PAR_ABI = {1: MAKE_SYM, 2: REFER, 3: TRUNCATE, 4: TRUNCATE,
                          5: TRUNCATE}

LECTURE = EXECUTE | READ_FILE | READ_DIR
ECRITURE_COMPLETE = (
    LECTURE | WRITE_FILE | REMOVE_DIR | REMOVE_FILE | MAKE_CHAR | MAKE_DIR
    | MAKE_REG | MAKE_SOCK | MAKE_FIFO | MAKE_BLOCK | MAKE_SYM | REFER
    | TRUNCATE
)


class _AttrJeuDeRegles(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64),
                ("handled_access_net", ctypes.c_uint64)]


class _AttrCheminSous(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64),
                ("parent_fd", ctypes.c_int32)]


def version_de_l_interface() -> int:
    """La version de Landlock de ce noyau, ou 0 si elle n'existe pas."""
    if not sys.platform.startswith("linux"):
        return 0
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        rendu = libc.syscall(ctypes.c_long(_NR_CREATE_RULESET), None,
                             ctypes.c_size_t(0),
                             ctypes.c_uint32(_LANDLOCK_CREATE_RULESET_VERSION))
    except Exception:  # pragma: no cover — plateforme sans libc utilisable
        return 0
    return rendu if rendu and rendu > 0 else 0


def poser_la_seconde_barriere(lecture_seule, lecture_ecriture,
                              fichiers_lisibles=(),
                              fichiers_ecrivables=()) -> str:
    """Impose au NOYAU le périmètre que le rideau de lecture déclare.

    Rend la phrase à imprimer en fin de session : ce qui a été posé, ou pourquoi
    rien ne l'a été. Ne lève jamais — une barrière en profondeur qui ferait
    échouer la session qu'elle protège serait un troisième dégât.
    """
    abi = version_de_l_interface()
    if abi == 0:
        return ("PAS POSÉE — ce noyau n'a pas Landlock (ou il est désactivé). "
                "La suite ne tient alors que par la porte de Python, et par le "
                "compte sous lequel elle tourne.")
    if os.environ.get("ARAC_SANS_SECONDE_BARRIERE"):
        return ("PAS POSÉE — ARAC_SANS_SECONDE_BARRIERE est dans "
                "l'environnement. Ce qui suit ne tient que par la porte de "
                "Python.")

    libc = ctypes.CDLL(None, use_errno=True)
    dernier = _DERNIER_DROIT_PAR_ABI.get(abi, TRUNCATE)
    gouvernes = (dernier << 1) - 1
    attr = _AttrJeuDeRegles(handled_access_fs=gouvernes, handled_access_net=0)
    # ABI 1 ne connaît pas le champ « réseau » : on ne lui passe que la
    # première moitié de la structure, sinon il refuse tout.
    taille = ctypes.sizeof(attr) if abi >= 4 else ctypes.sizeof(ctypes.c_uint64)
    jeu = libc.syscall(ctypes.c_long(_NR_CREATE_RULESET), ctypes.byref(attr),
                       ctypes.c_size_t(taille), ctypes.c_uint32(0))
    if jeu < 0:  # pragma: no cover — noyau qui annonce puis refuse
        return (f"PAS POSÉE — le noyau annonce Landlock v{abi} mais refuse le "
                f"jeu de règles (errno {ctypes.get_errno()}).")

    # UN CHEMIN, UN DROIT — on unit, on ne remplace pas : un répertoire qui est
    # à la fois sous la lecture et sous l'écriture doit garder les deux.
    droits: dict[str, int] = {}
    for chemin in lecture_seule:
        droits[chemin] = droits.get(chemin, 0) | LECTURE
    for chemin in fichiers_lisibles:
        droits[chemin] = droits.get(chemin, 0) | READ_FILE
    # UN FICHIER QUI S'ÉCRIT N'EST PAS UN RÉPERTOIRE QUI S'ÉCRIT. `/dev/null`
    # doit s'ouvrir en écriture ; `/dev` ENTIER n'a jamais eu à l'être, et
    # c'est pourtant ce qui était accordé — donc `/dev/sda` et `/dev/mem` avec.
    for chemin in fichiers_ecrivables:
        droits[chemin] = droits.get(chemin, 0) | READ_FILE | WRITE_FILE | TRUNCATE
    for chemin in lecture_ecriture:
        droits[chemin] = droits.get(chemin, 0) | ECRITURE_COMPLETE

    # ON N'OUVRE PAS PAR `os.open`, ET LA RAISON EST INSTRUCTIVE : à ce moment
    # de la session, le rideau de lecture enveloppe déjà `os.open` et REFUSE
    # tout ce qui est hors de son périmètre — c'est-à-dire précisément les
    # racines de l'hôte qu'on vient ici accorder EN LECTURE SEULE. Le refus
    # étant un `PermissionError`, il serait avalé par le `except OSError`
    # ci-dessous, et la barrière se poserait sans ces racines : `git` perdrait
    # `/etc/gitconfig`, le corpus basculerait sur son repli, et la suite
    # changerait de régime sans que personne ne sache pourquoi. Mesuré.
    accordes = 0
    for chemin, droit in sorted(droits.items()):
        fd = libc.open(chemin.encode("utf-8"), _O_PATH | _O_CLOEXEC)
        if fd < 0:
            continue  # le chemin n'existe pas ici : rien à accorder
        try:
            regle = _AttrCheminSous(allowed_access=droit & gouvernes,
                                    parent_fd=fd)
            if libc.syscall(ctypes.c_long(_NR_ADD_RULE), ctypes.c_int(jeu),
                            ctypes.c_uint32(_LANDLOCK_RULE_PATH_BENEATH),
                            ctypes.byref(regle), ctypes.c_uint32(0)) == 0:
                accordes += 1
        finally:
            libc.close(fd)

    # `no_new_privs` est exigé par Landlock, et il vaut par lui-même : il
    # interdit à tout descendant de GAGNER des droits par un binaire `setuid`.
    # `sudo` cesse d'être `sudo` — ce qui est précisément l'évasion par laquelle
    # « sudo -u postgres psql -p 5432 » atteignait la grappe de production.
    if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:  # pragma: no cover
        os.close(jeu)
        return (f"PAS POSÉE — `no_new_privs` refusé (errno "
                f"{ctypes.get_errno()}).")
    pose = libc.syscall(ctypes.c_long(_NR_RESTRICT_SELF), ctypes.c_int(jeu),
                        ctypes.c_uint32(0))
    os.close(jeu)
    if pose != 0:  # pragma: no cover
        return (f"PAS POSÉE — le noyau a refusé de s'appliquer la restriction "
                f"(errno {ctypes.get_errno()}).")
    return (
        f"POSÉE — Landlock v{abi}, {accordes} racines accordées, tout le reste "
        "du disque REFUSÉ par le noyau à cette session et à toute sa "
        "descendance. `head /etc/arac/<un autre>/arac.env` et `rm -rf` d'un "
        "coffre voisin échouent maintenant dans le noyau, quelle que soit la "
        "maille par laquelle on y arrive — y compris celles qu'on n'a pas "
        "trouvées. `no_new_privs` est posé : aucun `setuid` ne rend plus rien."
    )


#: CE QUE LES OUTILS DU DÉPÔT LISENT ET QUE PYTHON NE VOIT JAMAIS.
#:
#: Le périmètre du rideau de lecture a été mesuré sur les ouvertures PYTHON. Les
#: sous-processus, eux, en ouvrent d'autres — et `git` est le cas qui coûte :
#: privé de `/etc/gitconfig` et de `~/.gitconfig`, il ne se contente pas d'un
#: avertissement, il rend « fatal: unknown error » et `git ls-files` échoue.
#: Le corpus du dépôt bascule alors sur son repli disque, la suite change de
#: régime, et vingt-neuf tests s'ignorent sans que personne ne sache pourquoi.
#: Mesuré ici avant d'être écrit. Ce sont des FICHIERS, nommés un par un, et
#: aucun ne porte de cerveau : une configuration de `git` n'est pas un coffre.
def _fichiers_des_outils() -> tuple[str, ...]:
    maison = os.path.expanduser("~")
    return tuple(c for c in (
        "/etc/gitconfig",
        os.path.join(maison, ".gitconfig"),
        os.path.join(maison, ".config", "git"),
        "/etc/xdg/git",
    ) if c)


def _eclater_autour_des_retranchees(chemin: str, retranchees) -> set[str]:
    """Accorde ce chemin — SAUF ce qu'il contient et qui est retranché.

    LANDLOCK N'A PAS DE RÈGLE NÉGATIVE. Une règle s'attache à un répertoire et
    accorde tout ce qui est dessous : accorder `/usr` accorde `/usr/local`, que
    le rideau de Python retranche depuis qu'on a mesuré que le bootstrap y
    installe `arac-depot-sauvegardes` — « `/usr/local` porte du cerveau ». On ne
    peut donc pas soustraire ; on n'accorde pas la racine, on accorde ses
    ENFANTS, récursivement, en sautant la zone retranchée.

    FAIL-CLOSED SI L'ON NE PEUT PAS ÉNUMÉRER. Si le répertoire ne se liste pas,
    on n'accorde RIEN plutôt que d'accorder le tout : accorder par défaut est
    exactement la faute que ce dépôt corrige partout ailleurs.

    ON JUGE LE TEXTE **ET** LA RÉSOLUTION, ET CE N'EST PAS UNE PRÉCAUTION
    THÉORIQUE — C'ÉTAIT LA SIXIÈME INSTANCE. Le premier jet de cette fonction
    ne comparait que le chemin ÉCRIT. Sur Debian, les six répertoires de
    compatibilité de la racine — celui des bibliothèques, ses trois variantes
    d'architecture et les deux qui portent les programmes — sont des LIENS vers
    leurs homonymes sous `/usr`, et `_RACINES_SANS_CERVEAU` les accorde. Aucune
    zone retranchée ne commence par leur nom, ils étaient donc accordés d'un
    bloc — et `libc.open(…, O_PATH)` SUIT LE LIEN : le noyau recevait l'inode
    de `/usr/lib`, c'est-à-dire `/usr/lib/systemd`, `/usr/lib/tmpfiles.d` et
    `/usr/lib/sysusers.d`, que l'on venait de retrancher deux lignes plus haut.
    Mesuré : trois zones encore ouvertes, barrière annoncée POSÉE,
    retranchement « appliqué ». C'est mot pour mot la phrase du dépôt — ne juge
    pas un chemin sur son TEXTE quand le noyau juge sur sa RÉSOLUTION —
    commise dans le correctif même qui la cite.

    ON ÉNUMÈRE SOUS LE NOM RÉSOLU, ET C'EST LA MÊME RAISON. Le rideau de
    lecture de Python refuse `os.listdir` sur un répertoire hors de son
    périmètre : lister le lien échouerait et cette fonction se refermerait sur
    tout un sous-arbre, en silence. On liste donc la CIBLE, qui est dans le
    périmètre, et l'on accorde ses enfants : c'est le même inode, sous son
    autre nom, et c'est justement le nom que le noyau emploie.
    """
    chemin = chemin.rstrip("/") or "/"
    try:
        reel = os.path.realpath(chemin).rstrip("/") or "/"
    except (OSError, ValueError):  # pragma: no cover — chemin illisible
        return set()
    vus = (chemin,) if reel == chemin else (chemin, reel)
    if any(vu == r or vu.startswith(r + "/")
           for vu in vus for r in retranchees):
        return set()  # la zone elle-même, ou dedans — par l'un de ses deux noms
    dessous = [r for r in retranchees
               for vu in vus if r.startswith(vu + "/")]
    if not dessous:
        return {chemin}
    accordes: set[str] = set()
    try:
        entrees = sorted(os.listdir(reel))
    except OSError:
        return set()
    for entree in entrees:
        accordes |= _eclater_autour_des_retranchees(
            os.path.join(reel, entree), retranchees)
    return accordes


def perimetre_depuis_le_garde() -> tuple[list[str], list[str], list[str], list[str]]:
    """Le périmètre EXACT qui sera remis au noyau — lecture, écriture, fichiers.

    Rendu à part pour que le contrôle qui le relit (`test_la_porte_du_sous_
    processus_est_fermee.test_aucune_racine_de_cerveau_n_est_accordee`) juge ce
    que le code CALCULE, et non une copie recomposée à la main. Une copie
    diverge le jour où l'une seule des deux est corrigée : c'est la faute que ce
    dépôt a déjà payée trois fois sur une liste de chemins.
    """
    from tests import garde_hermetique as g

    retranchees = tuple(r.rstrip("/") for r in g._RETRANCHEES)
    lecture = set(g._racines_de_lecture()) | set(g._RACINES_SANS_CERVEAU)
    ecriture = {str(g.RACINE_DEPOT)}
    jetable = os.environ.get("ARAC_GARDE_JETABLE")
    if jetable:
        ecriture.add(jetable)
        lecture.discard(jetable)
    # `/dev` : DES FICHIERS NOMMÉS, PAS UNE RACINE. Ce répertoire était accordé
    # en ÉCRITURE COMPLÈTE pour une raison qui n'en couvrait que deux entrées
    # (« `/dev/null` s'écrit, `/dev/urandom` se lit »). Sous `root`, la même
    # règle ouvrait `/dev/sda` et `/dev/mem` : les disques bruts et la mémoire
    # vive, c'est-à-dire tous les coffres de la machine à la fois. On accorde
    # désormais la liste que `garde_hermetique` a MESURÉE, et les deux
    # répertoires dont les noms se composent à l'exécution (`/dev/pts` pour les
    # pseudo-terminaux — `pty.openpty` s'ouvre dans la libc, ce rideau-ci ne le
    # voit pas, le noyau si —, `/dev/fd`).
    lecture.discard("/dev")
    ecriture.update(g._RACINES_DE_DEV)
    lecture -= ecriture
    fichiers = set(g._FICHIERS_DE_LA_MACHINERIE) | set(_fichiers_des_outils())

    # LE RETRANCHEMENT, APPLIQUÉ AU NOYAU COMME IL L'EST À PYTHON. Sans ces
    # quatre lignes, la seconde barrière n'était pas le périmètre du rideau :
    # `_racines_de_lecture()` contient `/usr` (par `sys.base_prefix`) et
    # `/usr/lib`, si bien que le NOYAU accordait quatre des onze zones que le
    # rideau retranche — `/usr/local`, `/usr/lib/systemd`, `/usr/lib/tmpfiles.d`
    # et `/usr/lib/sysusers.d`. Mesuré par `ctypes`, qui ne passe par aucun
    # garde de Python : 4 zones sur 11 encore ouvertes au noyau, barrière
    # annoncée POSÉE — dont celle que le dépôt qualifie lui-même de « porteuse
    # de cerveau », et celle où une surcharge d'unité s'appliquerait au voisin
    # à la prochaine `daemon-reload`.
    lecture = {c for r in lecture
               for c in _eclater_autour_des_retranchees(r, retranchees)}
    ecriture = {c for r in ecriture
                for c in _eclater_autour_des_retranchees(r, retranchees)}
    fichiers = {c for c in fichiers
                if not any(c == r or c.startswith(r + "/") for r in retranchees)}
    portes = {c for c in g._PORTES_DE_DEV
              if not any(c == r or c.startswith(r + "/") for r in retranchees)}
    return sorted(lecture), sorted(ecriture), sorted(fichiers), sorted(portes)


def poser_depuis_le_garde() -> str:
    """Pose la barrière sur le périmètre que `garde_hermetique` déclare.

    C'est ici, et nulle part ailleurs, que le périmètre est repris — pour qu'il
    n'existe qu'UNE définition de ce que la suite a le droit de toucher.

    POURQUOI `/proc` EST ACCORDÉ EN ENTIER ICI ALORS QUE LE RIDEAU DE PYTHON LE
    DÉCOUPE PAR PROCESSUS. Une règle Landlock s'attache à un RÉPERTOIRE, c'est-
    à-dire à un inode : accorder « `/proc/self` » accorde le répertoire de NOTRE
    pid, et de personne d'autre — y compris pas de nos propres enfants, qui ont
    le leur. Mesuré, barrière posée avec « /proc/self » au lieu de « /proc » :
    notre `/proc/self/status` se lit, et un `python3 -c "open('/proc/self/
    status')"` fils rend `PermissionError [Errno 13]`. Mesuré aussi, barrière
    posée SANS `/proc` du tout : même notre propre `/proc/self/status` est
    refusé. Le grain « un processus, le sien » n'est pas exprimable en règles de
    chemin ; il l'est en Python, où l'on connaît son pid. Les deux couches ne
    disent donc pas la même chose, et c'est voulu : le noyau ferme le disque, le
    rideau ferme le répertoire du voisin.

    CE QUE LE RETRANCHEMENT COÛTE, ET POURQUOI IL SE PAIE. `_RETRANCHEES` passe
    devant tout le reste dans le rideau de Python ; il passe désormais devant
    tout le reste ici aussi, et cela se paie en RÈGLES : `/usr` et `/usr/lib`
    ne peuvent plus être accordés d'un bloc, ils sont éclatés en leurs enfants.
    Une barrière de cinquante règles n'est pas moins bonne qu'une de dix — elle
    est simplement écrite par un ordinateur plutôt que par une main.
    """
    lecture, ecriture, fichiers, portes = perimetre_depuis_le_garde()
    return poser_la_seconde_barriere(lecture, ecriture, fichiers, portes)
