"""Le garde qui rend la suite hermétique — et qui refuse de toucher un cerveau.

POURQUOI CE FICHIER EXISTE
==========================

Cinq documents du dépôt (``Makefile``, ``README.md``, ``GOAL.md``,
``docs/CONTRIBUER.md``, ``docs/FAQ.md``) promettent la même chose :

    « La suite est HERMÉTIQUE : ni base, ni réseau, ni clé d'API. Un test rouge
    doit vouloir dire *le code est cassé*, jamais *PostgreSQL n'est pas
    lancé*. »

C'était faux sur les deux moitiés, et les deux fautes ont la même forme : la
suite reconnaissait ce qu'elle voulait interdire par son NOM.

1. **Le réseau.** ``make test`` émettait de vrais GET HTTP vers
   ``http://127.0.0.1:8000`` — le repli codé en dur du collecteur du cockpit
   (``control_center/collectors/brain_api.py``). Sur la machine de l'auteur,
   c'est l'API de PRODUCTION. La preuve n'était pas théorique : le garde F1
   (« aucune trace de l'auteur à l'écran ») rendait la page ``/cc/brain``, la
   page allait chercher les données du cerveau RÉEL, et le HTML rendu par la
   suite de tests portait les scopes privés de l'auteur. Quatre tests rouges,
   dont la cause n'était pas dans le code : elle était dans le fait qu'un test
   parlait à un service vivant.

2. **La base.** Le garde anti-prod ne refusait qu'un seul nom de base : la
   chaîne littérale ``arac``, c'est-à-dire le cerveau de l'AUTEUR. Or le
   framework nomme la base d'après le cerveau — ``camille_brain``,
   ``nadia_brain``, celle de n'importe qui. **Le cerveau de tout autre
   utilisateur traversait le garde**, et la suite y exécutait alors une vraie
   migration Alembic 0006 UP/DOWN, plus un ``UPDATE arac.memory_atoms`` dont la
   clause ``WHERE`` vise explicitement les lignes NON-test.

LE PRINCIPE, CORRIGÉ
====================

La question n'est pas « *est-ce la base de l'auteur ?* » — on ne peut pas
énumérer les cerveaux du monde. La question est :

    **« cette base m'appartient-elle, à moi, test ? »**

Une base de test se RECONNAÎT : elle porte une marque, posée à la main, sur la
base elle-même (``COMMENT ON DATABASE``). Une marque n'est pas un nom : on ne
la porte pas par hasard, et un cerveau de production ne l'aura jamais — sauf à
ce que son propriétaire ait délibérément écrit sur SA base « mon contenu peut
être détruit à tout instant ». C'est très exactement le consentement qu'on
cherchait, et l'ancienne variable d'environnement ``ARAC_ALLOW_PROD_TEST_DB=1``
ne le portait pas : une variable de shell voyage, s'exporte dans un ``.env``,
survit à un ``source`` — la marque, elle, reste attachée à la base qu'elle
décrit.

Même principe pour le réseau : on n'énumère pas les adresses interdites, on
refuse TOUTE sortie TCP. *Fail-closed* : dans le doute, on refuse.

LE SOUS-PROCESSUS — LA PORTE QUI RESTAIT OUVERTE
=================================================

Cette docstring disait, jusqu'à cette manche : « les gardes sont posés DANS le
processus pytest ; un sous-processus lancé par un test n'en hérite pas ». C'était
exact, et c'était une porte, pas une limite. Mesuré, sur la suite VERTE, en
posant devant chaque binaire du ``PATH`` un mouchard qui note qui l'appelle :

  · ``sudo -u postgres psql -p 5432 -d postgres -tAc "SELECT … FROM pg_roles …"``
    — le cluster de PRODUCTION, dont les rôles sont GLOBAUX, interrogé quatre
    fois par ``bootstrap.sh --dry-run`` lancé par ``test_bootstrap_dry_run_
    enseigne`` ;
  · ``systemctl list-unit-files arac-*-api.service`` — l'inventaire des unités
    du VOISIN ; ``systemctl stop`` et ``systemctl reset-failed`` sur des unités
    transitoires posées sur l'hôte ;
  · ``ss -ltnH sport = :8000`` et ``:8100`` — les ports de production sondés ;
  · ``sudo -n -u aracagent test -x …`` — les comptes de service de production.

Aucun de ces appels ne venait du processus pytest : tous venaient d'un ``bash``
que le garde laissait passer — à raison, puisqu'il exécute les scripts du dépôt.
Le garde regardait ``args[0]``, lisait « bash », et n'avait plus rien à dire de
ce que ce bash ferait ensuite. La même porte s'ouvrait avec ``sudo psql``
(``args[0]`` vaut « sudo »), avec ``os.system`` (qui ne passe pas par
``subprocess``), et avec ``python -c "import psycopg …"``.

LE PRINCIPE, DEUX FOIS INVERSÉ
==============================

1. **On n'énumère plus ce qui est interdit.** Une liste de binaires interdits
   oublie par construction : elle ne connaît ni ``mysql``, ni ``redis-cli``, ni
   ``kubectl``, ni la commande qu'on inventera demain. On énumère ce que la
   suite a le DROIT de lancer — une vingtaine d'outils qui lisent et écrivent
   des FICHIERS — et on refuse tout le reste, y compris ce qui n'existe pas
   encore.

2. **La permission voyage avec les descendants.** Les trois seuls outils qui
   peuvent en lancer d'autres — ``bash``/``sh``, ``python``, ``git`` — la
   transmettent :

   · un répertoire de REFUS est placé en tête du ``PATH`` de tout descendant.
     Il porte un talon pour chaque nom du ``PATH`` de l'hôte qui n'est pas
     légitime. Un ``bash -c 'psql …'``, à n'importe quelle profondeur, trouve
     le talon avant ``/usr/bin/psql`` et se fait refuser. Le talon laisse
     passer une seule chose : un DOUBLE posé par le test lui-même (sous le
     dépôt, hors ``.venv``, ou sous le répertoire temporaire) — c'est ainsi
     que ``test_bootstrap_services_unites`` fournit son faux ``systemd-run`` ;
   · un ``sitecustomize.py`` est placé sur le ``PYTHONPATH`` des descendants :
     un ``python`` fils repose les trois gardes avant d'exécuter quoi que ce
     soit. ``python -c "import psycopg; psycopg.connect('…/arac')"`` est donc
     refusé dans le fils comme il l'est dans le père.

CE QUE CES DEUX PIÈCES NE VOYAIENT PAS — la quatrième, et ses limites
======================================================================

Le talon n'est consulté que lorsqu'un shell CHERCHE un programme. Mesuré, la
suite verte, depuis un test : ``bash -c "/usr/lib/postgresql/16/bin/psql …"``
démarre le vrai client PostgreSQL de cette machine — ``/usr/bin/psql`` n'y est
qu'un lien vers ``pg_wrapper`` — et ``bash -c "<venv>/bin/python -I -c 'import
psycopg …'"`` rend un interpréteur SANS aucun des trois gardes, qui joint
``127.0.0.1:5432``. Le garde n'avait vu que « bash », qui est légitime.

On lit donc le CORPS que reçoit un shell (``_controle_du_corps``), et on y
refuse cinq formes : un chemin absolu d'exécutable de l'hôte, une racine de
binaires, un ``PATH=`` qui rouvre un répertoire réel de l'hôte, ``env -i``, un
interpréteur déshabillé. On a aussi fermé deux portes que ``dir(os)`` ne donne
pas : ``pty.spawn`` (dont le refus tombait dans le FILS, après ``forkpty``) et
``_posixsubprocess.fork_exec`` (l'entrée C, qu'emprunte ``multiprocessing`` en
mode « spawn »).

CE QUE CELA NE VAUT PAS. Lire un corps de shell est un examen de TEXTE : un
chemin CALCULÉ à l'exécution ne s'y voit pas, ``P=/usr/b; ${P}in/psql`` non
plus, et ``ctypes.CDLL("libc.so.6").system(...)`` ne passe par aucune de nos
enveloppes. Ces limites sont ÉNUMÉRÉES, avec leur mécanique et leurs instances
vivantes, dans ``ZONES_NON_COUVERTES_DE_LA_PORTE``
(``tests/test_la_porte_du_sous_processus_est_fermee.py``), et imprimées en fin
de session. Un garde qui ment sur sa couverture est pire qu'un garde absent.

LE NOM JUGÉ N'ÉTAIT PAS LE PROGRAMME LANCÉ — six dissociations, mesurées
=========================================================================

Le contrôle jugeait ``commande[0]`` et en lisait le basename. Six mécanismes
séparent ce nom du programme qui s'exécute vraiment ; les six ont été reproduits
sur cette machine, la suite VERTE et ``TENTATIVES_MACHINE`` VIDE, avec
``hostname`` pour cible inoffensive :

  · ``executable=`` remplace le programme sans toucher ``argv[0]`` — en mot-clé
    ET en troisième argument POSITIONNEL de ``Popen`` ;
  · ``shell=True`` : la commande n'est plus un programme, c'est un CORPS de
    shell, et on n'en lisait que le premier mot ;
  · ``os.system`` — même faute ; ``os.popen`` n'était gardé par personne, son
    nom ne portant aucune des racines que ``dir(os)`` filtre ;
  · un LIEN SYMBOLIQUE sous le répertoire jetable, portant un nom légitime ;
  · ``cwd=`` avec un chemin relatif.

On juge désormais le programme qui s'exécute — ``executable`` s'il est donné,
sinon ``commande[0]`` résolu contre ``cwd`` et à travers les liens — et il
suffit qu'un seul des deux noms soit refusé pour que l'appel le soit.

LES EXÉCUTANTS — la liste blanche jugeait l'usage, pas le pouvoir
=================================================================

``OUTILS_LEGITIMES`` décrivait ``awk`` par « transforme du texte », ``find`` par
« parcourt une arborescence », ``tar`` par « archive des fichiers ». Les sept
exécutent un programme arbitraire (``system()``, ``-exec``, ``--to-command``,
``-c alias.x=!…``, le drapeau ``e`` d'un ``s///``), et le lecteur de corps ne
s'appliquait qu'aux SHELLS — au motif qu'« ailleurs, un chemin absolu est une
donnée ». C'est vrai de ``grep``. C'est faux de ces sept-là, et un ``pytest`` a
rendu quatre fois le compte d'atomes d'un cerveau de PRODUCTION. La question
n'est pas « est-ce un shell ? » mais **« cet outil peut-il exécuter ce qu'on lui
donne ? »** : voir ``EXECUTANTS``.

``PYTHONPATH`` — la seconde moitié de l'héritage, et elle était nue
===================================================================

``PATH`` était surveillé dans les corps de shell, ``PYTHONPATH`` pas du tout.
``bash -c "PYTHONPATH= python3 -c …"`` rend un fils SANS aucun des gardes —
mesuré : il rend ``socket.socket.connect`` d'origine. C'est ``python -I`` obtenu
sans écrire ``-I``. Les deux variables reçoivent maintenant la même règle :
allonger est permis, rebâtir ou vider ne l'est pas.

LE QUATRIÈME GARDE — la LECTURE, et pourquoi c'est un SECOND RIDEAU
====================================================================

Les trois premiers gardent la SORTIE. La LECTURE était déclarée nue, et c'était
la zone la plus coûteuse des sept : le jeton d'un cerveau voisin vit dans
``/etc/arac/<lui>/arac.env``, et qui le lit n'a plus besoin ni de ``psql``, ni
de ``sudo``, ni d'un chemin calculé — un GET suffit. ``open``, ``io.open``,
``os.open``, ``os.scandir`` et ``os.listdir`` sont donc enveloppés, avec le même
principe d'inversion : hors du dépôt, du répertoire jetable et de l'installation
Python, on n'ouvre pas et on ne liste pas. Le périmètre a été MESURÉ avant
d'être écrit, et la mesure est réécrite quand elle change : elle disait « ZÉRO
ouverture hors de lui » ; depuis que le ``/proc/<pid>/`` d'un tiers et les
périphériques de ``/dev`` en sont sortis, une session complète en refuse 241 —
toutes sous le ``/proc`` d'un autre processus, aucune n'étant un besoin. Le
relevé vit au-dessus de ``LECTURES_DECLAREES``.

Ce rideau ne ferme aucune des mailles restantes : il les rend SANS EFFET dans le
cas le plus simple. C'est ce qu'on demande d'une défense en profondeur, et ce
n'est pas ce qu'on demande d'une serrure.

Ce qui reste vrai : la preuve la plus forte se fait toujours de l'extérieur — un
espace de noms réseau vide (``unshare --net``), et surtout un COMPTE qui n'a pas
le droit d'atteindre un cerveau. Sous ``root``, ces gardes rendent les évasions
visibles et coûteuses ; ils ne les rendent pas impossibles.
"""

from __future__ import annotations

import os
import re
import shlex
import socket
import shutil
import tempfile
import threading
from pathlib import Path

MARQUE_DE_TEST = "arac:base-de-test-jetable"


#: Le geste qui marque une base — reproduit dans chaque message de refus, parce
#: qu'un refus qui ne dit pas quoi faire se contourne au lieu de se respecter.
#:
#: IL PORTE SON `-p`, ET CE N'EST PAS UNE COQUETTERIE. Ce geste dit à une base
#: « ton contenu peut être détruit à tout instant ». Sans `-p`, il s'adresse à
#: la grappe PAR DÉFAUT de la machine : on croit marquer sa base d'essai sur le
#: port 5461, on marque celle qui porte le même nom sur le 5432. Le port et le
#: nom viennent tous deux de la base REFUSÉE — on ne fait pas recopier un
#: gabarit à quelqu'un qui vient d'être arrêté par un refus.
def geste_de_marquage(base: str = "<base>", port: str = "<le port de VOTRE grappe>") -> str:
    return (
        f"psql -p {port} -d {base} -c \"COMMENT ON DATABASE {base} IS "
        f"'{MARQUE_DE_TEST} — son contenu peut être détruit à tout instant'\""
    )


class RefusHermetique(RuntimeError):
    """Levée quand la suite tente de sortir d'elle-même."""


# ============================================================================
# Le journal des refus — rendre visible ce qui était silencieux
# ============================================================================
#
# Le collecteur du cockpit avale toutes les exceptions (« résilience
# volontaire : aucune exception ne remonte au cockpit »). Un refus y serait
# donc invisible : la suite deviendrait hermétique sans que personne apprenne
# qu'elle ne l'était pas. On tient donc un journal, imprimé en fin de session.

TENTATIVES_RESEAU: list[str] = []
TENTATIVES_BASE: list[str] = []


def _journalise(journal: list[str], quoi: str) -> None:
    if quoi not in journal:
        journal.append(quoi)


# ============================================================================
# 1. LE RÉSEAU — aucune socket ne sort
# ============================================================================

_autorisation = threading.local()


def _sortie_autorisee() -> bool:
    """Vrai uniquement pendant qu'une connexion base DÉJÀ VALIDÉE s'ouvre."""
    return getattr(_autorisation, "actif", False)


class _fenetre_base:
    """Ouvre, le temps d'un ``connect`` validé, le droit d'ouvrir une socket."""

    def __enter__(self):
        self._ancien = getattr(_autorisation, "actif", False)
        _autorisation.actif = True
        return self

    def __exit__(self, *exc):
        _autorisation.actif = self._ancien
        return False


_connect_reel = socket.socket.connect
_connect_ex_reel = socket.socket.connect_ex


def _adresse_lisible(adresse) -> str:
    if isinstance(adresse, tuple) and len(adresse) >= 2:
        return f"{adresse[0]}:{adresse[1]}"
    return str(adresse)


def _refuse_la_sortie(self, adresse):
    """Refuse toute connexion TCP/UDP sortante, quelle que soit l'adresse.

    On ne discrimine pas par adresse : ``127.0.0.1:8000`` est le loopback, et
    c'est précisément là que vit l'API de production. « Local » ne veut pas
    dire « à moi ».

    Les sockets de famille ``AF_UNIX`` ne sont pas concernées : ce sont les
    tuyaux internes de l'interpréteur (et la socket locale de PostgreSQL, qui
    passe, elle, par le garde de base ci-dessous).
    """
    if self.family in (socket.AF_INET, socket.AF_INET6) and not _sortie_autorisee():
        ou = _adresse_lisible(adresse)
        _journalise(TENTATIVES_RESEAU, ou)
        raise RefusHermetique(
            f"REFUS hermétique : la suite de tests a tenté d'ouvrir une "
            f"connexion réseau vers {ou}.\n"
            "La suite est HERMÉTIQUE : ni base, ni réseau, ni clé d'API. Un "
            "test rouge doit vouloir dire « le code est cassé », jamais « le "
            "service n'est pas lancé » — et sur la machine de quelqu'un, "
            f"{ou} est peut-être son cerveau qui tourne.\n"
            "Le code testé doit être appelé avec un double (monkeypatch), pas "
            "avec un service vivant."
        )
    return _connect_reel(self, adresse)


def _refuse_la_sortie_ex(self, adresse):
    if self.family in (socket.AF_INET, socket.AF_INET6) and not _sortie_autorisee():
        _journalise(TENTATIVES_RESEAU, _adresse_lisible(adresse))
        # `connect_ex` a pour contrat de rendre un code d'erreur, pas de lever.
        # On rend « connexion refusée » : c'est la vérité de ce qui se passe.
        return 111
    return _connect_ex_reel(self, adresse)


# ============================================================================
# 2. LA BASE — « cette base m'appartient-elle, à moi, test ? »
# ============================================================================

#: On lit la marque ET le port de la grappe dans la MÊME interrogation.
#: Le port ne sert pas à décider : il sert à écrire le remède. Un remède qui
#: dit `psql -d <base>` sans `-p` s'adresse à la grappe PAR DÉFAUT de la
#: machine — pas à celle qu'on vient de refuser. Sur un poste à plusieurs
#: cerveaux, il fait donc poser « cette base est jetable » sur la base d'un
#: voisin, et c'est très exactement la permission de la détruire.
_REQUETE_MARQUE = (
    "SELECT coalesce(shobj_description(oid, 'pg_database'), ''), "
    "current_setting('port') "
    "FROM pg_database WHERE datname = current_database()"
)


def nom_de_base(dsn: str) -> str:
    """Nom de base d'un DSN postgres : segment après le dernier '/', sans query.

    Conservé pour les messages, jamais pour DÉCIDER : c'est le nom qui a menti.
    """
    return dsn.rsplit("/", 1)[-1].split("?")[0].strip()


def _refus(base: str, marque: str, var: str | None,
           port: str = "<le port de VOTRE grappe>") -> RefusHermetique:
    origine = f" (via {var})" if var else ""
    vue = f"« {marque} »" if marque else "aucun commentaire"
    return RefusHermetique(
        f"REFUS : la base « {base} »{origine} n'est pas une base de TEST.\n"
        "\n"
        "La suite écrit, supprime, et joue de vraies migrations Alembic "
        "(0006 fait un UPDATE dont le WHERE vise les lignes NON-test). Elle ne "
        "travaille donc que sur une base qui se DÉCLARE jetable.\n"
        "\n"
        f"Ce que porte cette base : {vue}.\n"
        f"Ce qu'il faut y lire : « {MARQUE_DE_TEST} ».\n"
        "\n"
        "Le nom de la base n'entre pas en jeu — c'est lui qui a menti : "
        "l'ancien garde ne refusait que la base littéralement nommée `arac`, "
        "et laissait donc passer `camille_brain`, `nadia_brain`, le cerveau de "
        "n'importe qui d'autre que l'auteur.\n"
        "\n"
        "Pour marquer une base que vous acceptez de voir détruite :\n"
        f"  {geste_de_marquage(base, port)}\n"
        "\n"
        f"Le « -p {port} » est celui de la grappe qu'on vient d'interroger : "
        "sans lui, ce geste marquerait « jetable » la base de même nom sur la "
        "grappe par défaut de la machine — celle du voisin.\n"
        "\n"
        "Ne la posez JAMAIS sur un cerveau vivant."
    )


def _marque_lue(commentaire: str) -> bool:
    return MARQUE_DE_TEST in (commentaire or "")


def verifie_la_marque_sync(conn, base: str, var: str | None = None) -> None:
    """Interroge la base OUVERTE : porte-t-elle la marque ? Sinon, refus."""
    with conn.cursor() as cur:
        cur.execute(_REQUETE_MARQUE)
        ligne = cur.fetchone()
    commentaire = (ligne[0] if ligne else "") or ""
    port = str(ligne[1]) if ligne and len(ligne) > 1 and ligne[1] else "<le port de VOTRE grappe>"
    if not _marque_lue(commentaire):
        raise _refus(base, commentaire, var, port)


async def verifie_la_marque_async(conn, base: str, var: str | None = None) -> None:
    async with conn.cursor() as cur:
        await cur.execute(_REQUETE_MARQUE)
        ligne = await cur.fetchone()
    commentaire = (ligne[0] if ligne else "") or ""
    port = str(ligne[1]) if ligne and len(ligne) > 1 and ligne[1] else "<le port de VOTRE grappe>"
    if not _marque_lue(commentaire):
        raise _refus(base, commentaire, var, port)


def _dsn_du_connect(args, kwargs) -> str:
    if args:
        return str(args[0])
    return str(kwargs.get("conninfo") or "")


# ============================================================================
# 3. LA MACHINE — la suite lit le dépôt, pas l'hôte qui la fait tourner
# ============================================================================
#
# Mesuré à l'espion sur `subprocess` : la suite exécutait pour de vrai, sur la
# machine de qui la lance —
#
#   systemctl is-active arac-curator-batch.service   (l'unité de PRODUCTION)
#   systemctl is-enabled arac-curator-batch.timer
#   journalctl --since -7 days -g 'cortex\.alert_sent|…'   (le journal RÉEL)
#   ss -ltn        (les sockets réellement en écoute)
#   tmux ls        (les sessions réellement ouvertes)
#   df -h /opt
#
# — depuis `test_sobriety_collector` et depuis le rendu des pages du cockpit
# par le garde F1. C'est la MÊME faute que le GET vers 127.0.0.1:8000, par une
# autre porte : le résultat de la suite dépend de l'état de la machine, et le
# contenu du journal système de quelqu'un se retrouve dans un HTML que la suite
# relit ensuite ligne à ligne.
#
# LA PREMIÈRE RÉDACTION DE CE GARDE ÉTAIT UNE ÉNUMÉRATION — et c'est la
# troisième fois, dans ce dépôt, que le même défaut se présente sous une forme
# neuve : liste de dossiers balayés, puis liste de suffixes, puis liste de noms.
# `BINAIRES_DE_LA_MACHINE` contenait trente-deux noms. Il ignorait `sudo` (donc
# `sudo -u postgres psql`, l'appel exact qui a échappé à la manche précédente),
# `env`, `timeout`, `bash -c`, `mysql`, `redis-cli`, `kubectl`, `alembic`, et
# tout ce qui n'est pas encore inventé.
#
# ON INVERSE. On décrit ce que la suite a le DROIT de lancer — ce qui est court,
# stable, et se justifie ligne à ligne — et on refuse tout le reste. Un outil
# d'une famille inconnue est refusé LE JOUR OÙ IL APPARAÎT, sans que personne
# n'ait eu à y penser.

#: Les outils que la suite a le droit de lancer, chacun avec sa raison. Tout ce
#: qui n'est pas ici est refusé — c'est le sens de l'inversion. Cette liste a
#: été MESURÉE : elle est exactement l'ensemble des binaires que la suite verte
#: atteint (mouchard posé sur les 1 392 exécutables du PATH), moins ceux qui
#: interrogent l'hôte.
OUTILS_LEGITIMES: dict[str, str] = {
    # — ce qui lit le dépôt, qui est l'objet même des tests —
    "git": "l'historique et l'index du dépôt : F1 et « la doc dit vrai » "
           "demandent à git quels fichiers sont versionnés — ET EXÉCUTE, par "
           "`-c alias.x=!…`, `-c core.pager=`, `--exec-path` ; voir EXECUTANTS",
    "bash": "les scripts d'installation DU DÉPÔT (`bash -n`, `--dry-run`, "
            "sourcer une bibliothèque pour en exercer une fonction). Ses "
            "propres enfants sont couverts par le PATH de refus",
    "sh": "idem bash, pour les gabarits qui s'annoncent POSIX",
    # — l'interpréteur : le fils repose les gardes par sitecustomize —
    "python": "l'interpréteur du dépôt (`generate_scopes.py`, `audit_env.py`). "
              "Le fils hérite des trois gardes par `sitecustomize`",
    "python3": "idem python",
    # — lire, découper, compter des FICHIERS : rien de tout cela ne peut
    #   joindre un service, une base, un journal système ou une socket —
    "cat": "lit un fichier", "head": "lit le début d'un fichier",
    "tail": "lit la fin d'un fichier", "grep": "cherche dans des fichiers",
    "egrep": "grep", "fgrep": "grep",
    "sed": "transforme du texte — ET EXÉCUTE, par le drapeau `e` d'un `s///` ; "
           "voir EXECUTANTS",
    "awk": "transforme du texte — ET EXÉCUTE, par `system()` et par `| \"cmd\"` ; "
           "voir EXECUTANTS",
    "gawk": "awk — exécute aussi", "mawk": "awk — exécute aussi",
    "cut": "découpe des colonnes", "tr": "transpose des caractères",
    "sort": "trie", "uniq": "dédoublonne", "wc": "compte",
    "find": "parcourt une arborescence — ET EXÉCUTE, par `-exec`/`-execdir`/`-ok` ; voir EXECUTANTS", "stat": "lit les métadonnées d'un fichier",
    "dirname": "manipule une chaîne de chemin", "basename": "idem dirname",
    "readlink": "résout un lien", "realpath": "résout un chemin",
    "id": "dit qui est l'utilisateur COURANT — pas l'état d'un service",
    "date": "l'heure", "sleep": "attend", "seq": "compte", "expr": "calcule",
    "sha256sum": "empreinte d'un fichier", "sha1sum": "idem", "md5sum": "idem",
    "printf": "écrit", "echo": "écrit", "true": "rend 0", "false": "rend 1",
    "test": "interroge le système de fichiers", "[": "test",
    "mktemp": "crée un fichier jetable", "tee": "écrit",
    "diff": "compare deux fichiers", "cmp": "compare deux fichiers",
    "ls": "liste un répertoire", "cp": "copie un fichier",
    "mv": "déplace un fichier", "rm": "supprime un fichier",
    "mkdir": "crée un répertoire", "rmdir": "supprime un répertoire",
    "touch": "crée un fichier", "chmod": "change un mode",
    "ln": "crée un lien", "install": "copie avec un mode",
    "tar": "archive des fichiers — ET EXÉCUTE, par `--to-command` et `--use-compress-program` ; voir EXECUTANTS", "gzip": "compresse", "gunzip": "décompresse",
    # Les ENVELOPPES. Elles ne sont légitimes que pour un DESCENDANT : ce
    # qu'elles enveloppent repasse par le PATH de refus, donc rien ne leur
    # échappe. Depuis le processus de test, elles sont refusées (voir
    # `ENVELOPPES` ci-dessous) : le garde ne saurait pas dire ce qu'elles
    # lancent, et « je ne sais pas » ne vaut pas « c'est permis ».
    "xargs": "enveloppe — légitime pour un descendant seulement",
    "env": "enveloppe — légitime pour un descendant seulement",
    "timeout": "enveloppe — légitime pour un descendant seulement",
    "nice": "enveloppe — légitime pour un descendant seulement",
    "nohup": "enveloppe — légitime pour un descendant seulement",
    "setsid": "enveloppe — légitime pour un descendant seulement",
    "stdbuf": "enveloppe — légitime pour un descendant seulement",
    "getent": "lit /etc/passwd — l'existence d'un compte, pas l'état d'un service",
    "shellcheck": "analyse statique des scripts du dépôt",
}

#: La forme d'un interpréteur Python : `python`, `python3`, `python3.12`. On la
#: reconnaît par sa FORME et non par une liste de versions — une liste de
#: versions oublierait `python3.14` le jour de sa sortie.
_RX_PYTHON = re.compile(r"^python(?:\d+(?:\.\d+)?)?$")

#: Le dépôt : un programme qui en vient est l'objet du test, pas l'hôte.
RACINE_DEPOT = Path(__file__).resolve().parent.parent

TENTATIVES_MACHINE: list[str] = []

#: Ce que les DESCENDANTS se sont vu refuser. Le talon du PATH de refus y écrit
#: une ligne ; `pytest_terminal_summary` le lit. Sans ce fichier, un refus au
#: fond d'un `bash -c` serait parfaitement muet.
_JOURNAL_DESCENDANTS: list[Path] = []


def _tete(commande) -> str:
    """Le premier mot d'une commande, sous n'importe quelle forme d'appel."""
    try:
        if isinstance(commande, (list, tuple)):
            brut = commande[0]
        else:
            brut = str(commande).split()[0]
        return os.fsdecode(brut) if isinstance(brut, bytes) else str(brut)
    except Exception:
        return ""


def _vient_du_depot(chemin: str) -> bool:
    """Ce programme est-il un fichier DU DÉPÔT (hors dépendances tierces) ?

    `.venv/bin` est exclu, et pour la raison exacte qui l'exclut déjà de la zone
    balayée par G1 : ce n'est pas notre code. `alembic`, `uvicorn`, `pip` y
    vivent, et `alembic upgrade` sur une base est très précisément le geste que
    ce garde existe pour empêcher.
    """
    try:
        p = Path(chemin).resolve()
    except (OSError, ValueError):
        return False
    try:
        rel = p.relative_to(RACINE_DEPOT)
    except ValueError:
        return False
    return rel.parts[:1] != (".venv",)


def _resolu(chemin: str, cwd=None) -> str:
    """Le fichier RÉELLEMENT atteint : relatif résolu contre `cwd`, liens suivis.

    DEUX DISSOCIATIONS SE FERMENT ICI, et elles ont été mesurées.

    · `cwd=` — `subprocess.run(["./cat"], cwd=…)` ne nomme pas le même fichier
      selon le répertoire ; juger le nom sans le répertoire, c'est juger une
      étiquette.
    · le LIEN SYMBOLIQUE — un lien nommé `cat`, posé sous `tmp_path` et pointant
      sur le `hostname` de l'hôte, porte un nom légitime et exécute un binaire
      de la machine. Mesuré : rc=0, le nom d'hôte rendu, `TENTATIVES_MACHINE`
      vide. On suit donc le lien AVANT de juger, et c'est le nom du fichier RÉEL
      qui est soumis à `OUTILS_LEGITIMES`.
    """
    try:
        if not os.path.isabs(chemin) and cwd:
            chemin = os.path.join(os.fsdecode(cwd), chemin)
        return os.path.realpath(chemin)
    except (OSError, ValueError, TypeError):  # pragma: no cover — chemin illisible
        return chemin


def est_legitime(commande, executable=None, cwd=None) -> tuple[bool, str]:
    """La suite a-t-elle le droit de lancer ceci ? Rend (verdict, nom vu).

    ON JUGE LE PROGRAMME QUI S'EXÉCUTE, JAMAIS L'ÉTIQUETTE QU'ON LUI A MISE.
    `subprocess.Popen` accepte un mot-clé `executable=` qui REMPLACE le
    programme lancé sans toucher à `argv[0]` : mesuré sur cette machine,
    `subprocess.run(["cat", …], executable="/usr/lib/postgresql/16/bin/psql")`
    a démarré le vrai client PostgreSQL et ouvert la socket du cluster de
    production, pendant que le garde lisait « cat » et se taisait.

    Le verdict porte donc sur DEUX noms, et il suffit qu'un seul soit refusé :
    celui qu'on annonce (`commande[0]`) et celui qu'on exécute (`executable`,
    ou `commande[0]` résolu contre `cwd` et à travers les liens). Fail-closed :
    dans le doute, on refuse.
    """
    tete = _tete(commande)
    candidats = [c for c in (executable, tete) if c]
    if not candidats:
        return False, ""
    dernier_nom = ""
    for brut in candidats:
        cible = os.fsdecode(brut) if isinstance(brut, bytes) else str(brut)
        nom = os.path.basename(cible)
        if "/" in cible:
            reel = _resolu(cible, cwd)
            # Le nom du fichier RÉELLEMENT atteint prime : un lien nommé `cat`
            # qui pointe sur `hostname` est un `hostname`.
            nom = os.path.basename(reel) or nom
            if _vient_du_depot(reel) or _vient_du_depot(cible):
                continue
        dernier_nom = nom
        if nom in OUTILS_LEGITIMES or _RX_PYTHON.match(nom):
            continue
        return False, nom
    return True, dernier_nom or os.path.basename(str(candidats[-1]))


def _refus_de_processus(nom: str, commande) -> RefusHermetique:
    return RefusHermetique(
        f"REFUS hermétique : la suite de tests a tenté de lancer « {nom} ».\n"
        "\n"
        "La suite lit le DÉPÔT ; elle n'interroge pas l'hôte qui la fait "
        "tourner. Sur la machine de quelqu'un, une commande de ce genre rend "
        "l'état de SES services, SON journal système, SES sockets, SA base — et "
        "le résultat de la suite se met à dépendre de l'endroit où elle "
        "tourne.\n"
        "\n"
        "Le garde n'énumère plus ce qui est interdit : il énumère ce qui est "
        "LÉGITIME, et refuse tout le reste. Une liste d'interdits oublie par "
        "construction — celle d'avant ignorait `sudo`, donc laissait passer "
        "`sudo -u postgres psql -d arac`, qui exécutait du DDL sur un cerveau "
        "de production.\n"
        "\n"
        "Trois issues, dans l'ordre de préférence :\n"
        "  1. exercer le code appelant avec un DOUBLE (`monkeypatch` de "
        "`subprocess.run`), comme le font les tests de "
        "`control_center/collectors/system_metrics.py` ;\n"
        "  2. poser un faux binaire dans le `PATH` du sous-processus (un "
        "répertoire sous `tmp_path`), comme le fait "
        "`test_bootstrap_services_unites` pour `systemd-run` ;\n"
        "  3. si l'outil lit VRAIMENT des fichiers et rien d'autre, l'ajouter à "
        "`OUTILS_LEGITIMES` avec la raison qui le justifie.\n"
        "\n"
        f"Commande refusée : {str(commande)[:200]}"
    )


#: Les trois drapeaux qui feraient qu'un `python` fils N'HÉRITERAIT PAS des
#: gardes : `-E` ignore PYTHONPATH, `-I` l'ignore aussi et isole, `-S` saute
#: `site` — donc `sitecustomize`. Les refuser n'est pas de la méfiance : c'est
#: la seule façon que « le fils hérite » soit une propriété et non un espoir.
_LETTRES_SANS_HERITAGE = set("IES")

#: Ce qui lance AUTRE CHOSE sans le dire dans son nom. `sudo` n'est pas ici : il
#: n'est pas légitime du tout. Ces sept-là le sont pour un descendant — leur
#: contenu repasse par le PATH de refus — mais pas depuis le processus de test,
#: où le garde ne verrait que l'enveloppe. C'est très exactement l'erreur qui a
#: laissé passer `sudo -n -u postgres psql -d arac` : `args[0]` valait « sudo ».
ENVELOPPES = frozenset({
    "env", "timeout", "xargs", "nice", "ionice", "nohup", "setsid", "stdbuf",
    "flock", "chroot", "unbuffer", "script", "watch",
})


# ---------------------------------------------------------------------------
# 3 ter. CE QUE LE TALON DU PATH NE PEUT PAS VOIR — le corps d'un shell
# ---------------------------------------------------------------------------
#
# LE TALON NE MORD QUE LES NOMS NUS, ET C'EST MESURÉ. Le répertoire de refus est
# en tête du `PATH` : il est consulté quand un shell cherche `psql`. Il n'est
# JAMAIS consulté quand le shell reçoit un chemin — `bash` exécute
# `/usr/lib/postgresql/16/bin/psql` sans rien demander au `PATH`. Le garde, lui,
# n'a vu que `bash`, qui est légitime.
#
# Les six évasions mesurées sur cette machine, toutes depuis un test, toutes
# avec `pytest tests/test_la_porte_du_sous_processus_est_fermee.py` VERT :
#
#   bash -c "/usr/bin/hostname -f"                          → rc=0, le nom d'hôte
#   bash -c "/usr/lib/postgresql/16/bin/psql --version"     → rc=0, le vrai client
#   bash -c "B=/usr/bin; \$B/hostname -f"                    → rc=0
#   bash -c "export PATH=/usr/bin:/bin; hostname -f"        → rc=0
#   bash -c "env -i PATH=/usr/bin:/bin hostname -f"         → rc=0
#   bash -c "\$SYS_EXE -I -c 'import psycopg; …'"            → psycopg.connect NU,
#                                                             et connect_ex vers
#                                                             127.0.0.1:5432 → 0
#
# La dernière est la pire : un interpréteur déshabillé lancé depuis un shell
# n'a plus AUCUN des trois gardes, ni celui de la base, ni celui du réseau.
# Le père refusait déjà `python -I` — mais il ne voyait pas ce même `-I` écrit
# à l'intérieur d'une chaîne passée à `bash`.
#
# CE QU'ON FAIT, ET CE QUE ÇA VAUT. On lit le CORPS que reçoit un shell et on y
# cherche les CINQ formes ci-dessus. C'est un examen de TEXTE : un chemin
# CALCULÉ à l'exécution (`$(pg_config --bindir)/psql`) n'y sera jamais vu, et
# `P=/usr/b; ${P}in/psql` non plus. Ces deux-là sont déclarés dans
# `ZONES_NON_COUVERTES_DE_LA_PORTE`, et ils ne sont pas fermables depuis Python
# — seul un compte non privilégié ou un espace de noms les rend sans effet.
# On ferme donc ce qui se ferme, on le dit, et on n'appelle pas cela une classe.

#: Un chemin ABSOLU vers un exécutable : `/…/bin/<nom>` ou `/…/sbin/<nom>`, à
#: n'importe quelle profondeur. On cherche la FORME et non quatre racines :
#: `/usr/bin/psql` et `/usr/lib/postgresql/16/bin/psql` sont le même geste, et
#: sur Debian c'est le SECOND qui porte le vrai client — `/usr/bin/psql` n'y est
#: qu'un lien vers `pg_wrapper`. Une liste de racines aurait donc oublié le
#: chemin le plus courant de la machine sur laquelle elle tourne.
RX_CHEMIN_D_EXECUTABLE = re.compile(
    r"(?<![\w.+-])((?:/[\w.+-]+)*/s?bin)/([a-zA-Z][\w.+-]*)"
)

#: Une RACINE de binaires nommée toute seule (`/usr/bin`, `/usr/lib/postgresql/
#: 16/bin`). Elle n'exécute rien par elle-même — mais assemblée avec un nom
#: (`B=/usr/bin; $B/psql`) elle contourne le talon, et c'est la moitié du chemin
#: qu'aucun motif ne verra une fois la variable substituée.
RX_RACINE_DE_BINAIRES = re.compile(
    r"(?<![\w.+-])((?:/[\w.+-]+)*/s?bin)(?![\w.+-/])"
)

#: Toute affectation de `PATH` dans un corps de shell, avec sa VALEUR. On ne
#: refuse pas l'affectation : on regarde ce qu'elle ouvre.
#:
#: `PATH=$FAUX:$PATH` est le geste légitime d'un test qui pose un double — il
#: garde le répertoire de refus en tête. `PATH=/nonexistent cmd` est le geste
#: légitime de `test_g2`, qui prouve que le code REFUSE quand `ss` est absent :
#: un chemin qui ne mène nulle part n'ouvre rien, et refuser cela aurait été un
#: garde qui interdit de prouver qu'on refuse. `export PATH=/usr/bin:/bin`, lui,
#: jette le répertoire de refus ET rouvre les binaires de l'hôte : c'est la
#: seule des trois qui coûte quelque chose, et c'est la seule refusée.
RX_PATH_AFFECTE = re.compile(
    r"(?:^|[;&|(\s])(?:export\s+)?PATH=([^\s;&|]*)"
)

#: LA DÉPENDANCE, ÉCRITE — c'est le geste qui manquait à la manche précédente.
#:
#: Elle avait fermé `PYTHONPATH= python3 …` dans un corps de shell, et elle
#: l'avait bien fermé. Mais la DÉPENDANCE n'était écrite nulle part : rien, dans
#: ce fichier, ne disait « tout l'héritage des gardes tient à ces deux variables
#: et à rien d'autre ». Un garde dont une pièce dépend silencieusement d'une
#: autre casse le jour où l'autre change, et personne ne sait pourquoi. Quatre
#: portes PYTHON — `os.posix_spawn(py, argv, {})`, `os.execve(py, argv, {})`,
#: `os.putenv("PYTHONPATH", "")`, un `preexec_fn` qui appelle `os.unsetenv` —
#: rendaient un fils NU sans écrire ni `-I`, ni `bash`, ni le moindre chemin :
#: mesuré, `socket.socket.connect.__name__` y valait « connect ».
#:
#: Le dictionnaire ci-dessous EST la déclaration. Il est lu par
#: `_environnement_garde` (qui réinjecte), par les enveloppes de `os.putenv` et
#: `os.unsetenv` (qui refusent l'effacement), par le lecteur de corps de shell
#: (qui refuse la même chose écrite en shell), et par le test
#: `test_la_dependance_de_l_heritage_est_declaree_et_vraie`, qui EFFACE chaque
#: variable dans un fils et exige que le fils en sorte nu. Une déclaration qu'on
#: ne peut pas éprouver est un commentaire ; celle-ci se mesure.
VARIABLES_DE_L_HERITAGE: dict[str, str] = {
    "PYTHONPATH": (
        "porte le répertoire du `sitecustomize` qui repose les trois gardes "
        "dans TOUT `python` fils. Vidée ou rebâtie, le fils n'a NI garde de "
        "réseau, NI garde de base, NI garde de processus, NI rideau de "
        "lecture — c'est `python -I` obtenu sans écrire `-I`."
    ),
    "PATH": (
        "porte EN TÊTE le répertoire de refus, qui met un talon devant chaque "
        "nom de programme de l'hôte qui n'est pas légitime. Rebâti, un "
        "descendant retrouve `/usr/bin/psql` par son nom nu."
    ),
}

#: Les variables de service que le talon et le `sitecustomize` relisent. Elles
#: ne PORTENT pas l'héritage, elles le RENSEIGNENT : sans elles le talon ne sait
#: plus reconnaître un double légitime, et le `sitecustomize` ne trouve plus le
#: dépôt. On les réinjecte partout où l'on réinjecte les deux premières.
VARIABLES_DU_GARDE: tuple[str, ...] = (
    "ARAC_GARDE_PATH_HOTE", "ARAC_GARDE_DEPOT", "ARAC_GARDE_JETABLE",
    "ARAC_GARDE_REFUS", "ARAC_GARDE_REFUSDIR",
)

#: `PYTHONPATH` EST LA SECONDE MOITIÉ DE L'HÉRITAGE, ET ELLE ÉTAIT NUE.
#:
#: Le dispositif tient sur deux variables : `PATH` (le talon de refus) et
#: `PYTHONPATH` (le `sitecustomize` qui repose les trois gardes dans tout
#: `python` fils). La première était surveillée dans les corps de shell, la
#: seconde pas du tout. Mesuré sur cette machine, la suite verte :
#:
#:   bash -c "PYTHONPATH= python3 -c 'import socket; …'"      → GARDE absent
#:   bash -c "unset PYTHONPATH; python3 -c 'import socket; …'" → GARDE absent
#:   bash -c "python3 -c 'import socket; …'"   (témoin)        → GARDE présent
#:
#: — le fils rend `socket.socket.connect.__name__` == « connect » au lieu de
#: « _refuse_la_sortie » : ni garde de réseau, ni garde de base, ni garde de
#: processus. C'est `python -I` obtenu sans écrire `-I`.
#:
#: On applique donc à `PYTHONPATH` la règle exacte de `PATH` : ALLONGER est
#: permis (`PYTHONPATH=$X:$PYTHONPATH`), REBÂTIR ou VIDER ne l'est pas.
RX_PYTHONPATH_AFFECTE = re.compile(
    r"(?:^|[;&|(\s])(?:export\s+)?PYTHONPATH=([^\s;&|]*)"
)

#: `unset PATH` et `unset PYTHONPATH` — la même chose en un mot de moins.
RX_UNSET_DE_L_HERITAGE = re.compile(
    r"(?:^|[;&|(\s])unset\s+(?:-\w+\s+)*((?:\w+\s+)*(?:PATH|PYTHONPATH))\b"
)

#: `env -i` : l'environnement rasé, donc le `PATH` de refus et les variables du
#: garde avec lui.
RX_ENV_RASE = re.compile(r"(?:^|[;&|(\s])env\s+(?:-\w+\s+)*-\w*i")

#: Un interpréteur DÉSHABILLÉ écrit à l'intérieur d'une chaîne : `python -I`,
#: `python3.12 -SE`, `/…/.venv/bin/python -E`. Le père refuse déjà la forme
#: `[sys.executable, "-I", …]` ; celle-ci passait par `bash`.
RX_PYTHON_DESHABILLE = re.compile(
    r"python[\d.]*[\"']?\s+-[A-Za-z]*[IES]\b"
)

#: Ce qui, recevant du TEXTE, l'exécute. `python` n'y est pas : son fils repose
#: les trois gardes par `sitecustomize`, et les refuse donc lui-même — sauf s'il
#: est déshabillé, ce que la forme ci-dessus attrape ici comme ailleurs.
SHELLS = frozenset({"bash", "sh", "dash", "ksh", "zsh"})

#: LES EXÉCUTANTS — la maille qui a rendu 1 936 atomes de production à un
#: simple `pytest`, quatre fois, le garde muet.
#:
#: `OUTILS_LEGITIMES` rangeait ces sept-là sous leur USAGE COURANT (« awk :
#: transforme du texte », « find : parcourt une arborescence », « tar : archive
#: des fichiers ») et non sous leur POUVOIR. Les sept exécutent un programme
#: arbitraire :
#:
#:   awk 'BEGIN{system("…")}'          ·  sed 's///e'  (drapeau `e` de GNU sed)
#:   find … -exec … \;                  ·  tar --to-command '…'
#:   git -c alias.x='!…' x
#:
#: La docstring de `_controle_du_corps` portait la phrase qui a causé l'oubli :
#: « ailleurs, un chemin absolu est une donnée (`grep /usr/bin/psql fichier` ne
#: lance rien) ». Elle est vraie de `grep` et de `cat`. Elle est FAUSSE de ces
#: sept-là. La question n'est donc pas « est-ce un shell ? » mais **« cet outil
#: peut-il exécuter ce qu'on lui donne ? »** — et sept outils que tout le monde
#: range parmi les lecteurs de fichiers le peuvent.
#:
#: Ils restent légitimes (la suite s'en sert : `git ls-files`, `awk` sur un
#: fichier du dépôt), mais ils reçoivent le MÊME traitement que les shells :
#: leur corps est lu, et une directive d'exécution y est refusée.
EXECUTANTS = frozenset({"awk", "gawk", "mawk", "sed", "find", "tar", "git",
                        # — trouvés par le CRITÈRE DE FORME ci-dessous, pas par
                        #   quelqu'un qui y a pensé —
                        "sort", "install", "diff"})

# ---------------------------------------------------------------------------
# LE CRITÈRE DE FORME — ce qu'un outil PEUT faire, lu dans le binaire lui-même
# ---------------------------------------------------------------------------
#
# C'EST LA QUATRIÈME FOIS QUE CE DÉPÔT BUTE SUR UNE ÉNUMÉRATION : liste de
# dossiers, liste de suffixes, liste de noms de binaires, et maintenant liste
# d'outils EXÉCUTANTS. Les trois premières ont été remplacées par une forme. La
# quatrième l'est ici, et pas par une intuition : par une MESURE.
#
# Un exécutable ELF déclare, dans sa table de symboles DYNAMIQUES, les fonctions
# de la libc qu'il ira chercher. Un programme qui peut lancer un autre programme
# doit y nommer une des portes de la famille `exec` (`execve`, `execvp`,
# `execlp`, `posix_spawn`, `system`, `popen`, …). Il ne peut pas s'en passer :
# c'est le seul chemin vers `execve(2)` qui ne soit pas un appel système écrit à
# la main. La question « cet outil peut-il exécuter ce qu'on lui donne ? » a donc
# une réponse MÉCANIQUE, lisible sans lancer l'outil et sans lui faire confiance.
#
# CE QUE LA MESURE A RENDU SUR CETTE MACHINE (2026-08-09, coreutils 9.4) :
#
#   sort     execlp fork      ← `--compress-program` : l'évasion de la manche
#   install  execlp fork      ← `--strip-program` : PERSONNE ne l'avait nommée
#   diff     execv  fork      ← `-l` passe la sortie à `pr`
#   find     execvp fork  ·  tar execl/execlp/execv/execvp  ·  git execl/execve
#   awk      execl/execvp/system/popen  ·  sed popen
#   cat head tail grep wc cut tr uniq stat cmp ls cp mv rm touch chmod ln tee
#   mktemp gzip dirname basename readlink realpath id date sleep seq sha*sum
#   printf echo true false test getent            → AUCUN symbole d'exécution
#
# Les sept de la liste écrite sont retrouvés — et trois de plus, dont les deux
# qui coûtaient. Le critère ne les a pas devinés : il les a LUS.
#
# CE QUE LE CRITÈRE NE VAUT PAS, et c'est déclaré dans
# `ZONES_NON_COUVERTES_DE_LA_PORTE` :
#   · il sur-approxime — `diff` n'exécute que `pr`, pas ce qu'on lui donne. On
#     préfère refuser un outil de trop que d'en oublier un : *fail-closed* ;
#   · il ne lit qu'un ELF dynamique. Un SCRIPT (`egrep`, `gunzip` sur Debian),
#     un binaire statique, un busybox : on ne sait pas → on le traite comme un
#     exécutant. « Je ne sais pas » ne vaut pas « c'est permis » ;
#   · il dit qu'un outil PEUT exécuter, jamais PAR QUELLE OPTION. C'est pourquoi
#     le refus porte sur la forme de l'option (`--…-program`, `--…-command`) ET
#     sur tout chemin absolu d'exécutable trouvé dans les arguments.

#: Les portes de la libc par lesquelles un programme en lance un autre. C'est
#: une liste, et c'en est une bonne : elle énumère une interface FIGÉE depuis
#: 1988 (POSIX.1), pas les outils d'une distribution qui bouge tous les six
#: mois. La différence entre une énumération qui tient et une qui pourrit est là.
_SYMBOLES_D_EXECUTION = frozenset({
    "execv", "execve", "execvp", "execvpe", "execl", "execle", "execlp",
    "execlpe", "fexecve", "posix_spawn", "posix_spawnp", "system",
    "__libc_system", "popen", "forkpty",
})


def _symboles_dynamiques(chemin: str) -> frozenset[str] | None:
    """Les symboles dynamiques d'un ELF 64 bits, ou ``None`` si on ne sait pas.

    Écrit à la main, en une trentaine de lignes, plutôt que par `nm` ou
    `readelf` : ces deux-là ne sont pas installés sur cette machine, et un garde
    qui dépend d'un paquet optionnel se tait le jour où il manque. Ce lecteur
    n'ouvre le fichier qu'en lecture, une fois, et ne le lance jamais.
    """
    import struct

    try:
        with open(chemin, "rb") as f:
            data = f.read()
    except OSError:
        return None
    if len(data) < 0x40 or data[:4] != b"\x7fELF" or data[4] != 2:
        return None  # pas un ELF 64 bits : un script, un binaire d'une autre
        #              classe, ou autre chose. On ne sait pas.
    try:
        (e_shoff,) = struct.unpack_from("<Q", data, 0x28)
        (e_shentsize,) = struct.unpack_from("<H", data, 0x3A)
        (e_shnum,) = struct.unpack_from("<H", data, 0x3C)
        if not e_shoff or not e_shnum:
            return None
        sections = []
        for i in range(e_shnum):
            sections.append(struct.unpack_from("<IIQQQQIIQQ", data,
                                               e_shoff + i * e_shentsize))
        noms: set[str] = set()
        vu_une_table = False
        for s in sections:
            if s[1] != 11:  # SHT_DYNSYM
                continue
            vu_une_table = True
            strtab = sections[s[6]]
            brut = data[strtab[4]:strtab[4] + strtab[5]]
            entree = s[9] or 24
            for i in range(s[5] // entree):
                (st_name,) = struct.unpack_from("<I", data, s[4] + i * entree)
                fin = brut.find(b"\0", st_name)
                if fin > st_name:
                    noms.add(brut[st_name:fin].decode("latin1"))
        return frozenset(noms) if vu_une_table else None
    except (struct.error, IndexError, ValueError):  # pragma: no cover
        return None


def _peut_executer(chemin: str) -> bool | None:
    """Cet outil peut-il lancer un programme ? ``None`` = on ne sait pas."""
    symboles = _symboles_dynamiques(chemin)
    if symboles is None:
        return None
    return bool(symboles & _SYMBOLES_D_EXECUTION)


#: Ce que la MESURE a rendu sur CETTE machine, remplie par `_mesurer_les_
#: pouvoirs()` au moment où le garde balaie déjà le `PATH` de l'hôte pour y
#: poser ses talons. Sur une autre distribution, un autre `sort` : le garde
#: mesure là où il tourne au lieu de réciter ce qu'on a vu ailleurs.
EXECUTANTS_MESURES: dict[str, str] = {}


def _mesurer_les_pouvoirs() -> None:
    """Range chaque outil légitime selon ce qu'il PEUT faire, pas son nom."""
    chemins = os.environ.get("ARAC_GARDE_PATH_HOTE") or os.environ.get("PATH", "")
    for nom in OUTILS_LEGITIMES:
        if nom in EXECUTANTS or nom in SHELLS or _RX_PYTHON.match(nom):
            continue  # déjà déclarés exécutants, ou jugés autrement
        reel = shutil.which(nom, path=chemins)
        if not reel:
            continue
        try:
            reel = os.path.realpath(reel)
        except OSError:  # pragma: no cover
            continue
        verdict = _peut_executer(reel)
        if verdict is True:
            EXECUTANTS_MESURES[nom] = f"{reel} : symbole d'exécution dans l'ELF"
        elif verdict is None:
            EXECUTANTS_MESURES[nom] = (
                f"{reel} : ni ELF 64 lisible ni table dynamique — on ne sait "
                "pas, donc on refuse (fail-closed)")


def est_un_executant(nom: str) -> bool:
    """La question de fond : cet outil peut-il exécuter ce qu'on lui donne ?"""
    return nom in EXECUTANTS or nom in EXECUTANTS_MESURES

#: Les directives par lesquelles un exécutant lance un programme, y compris
#: quand le programme y est nommé NU. Le talon du `PATH` mord déjà les noms nus
#: (mesuré : `awk 'BEGIN{system("hostname -f")}'` est refusé par le talon) ;
#: refuser la directive elle-même déplace le refus dans le PÈRE, où il enseigne,
#: et ferme la forme où le nom est calculé par l'outil lui-même.
RX_DIRECTIVES_D_EXECUTION: dict[str, re.Pattern] = {
    # awk : `system("…")`, `print … | "cmd"`, `"cmd" | getline`, `|&`
    "awk": re.compile(r"\bsystem\s*\(|\|\s*&?\s*\"|\bgetline\s*<\s*\"\s*\|"),
    # sed : le drapeau `e` d'un `s///`, et la commande `e` seule
    "sed": re.compile(r"s(.)(?:\\.|(?!\1).)*\1(?:\\.|(?!\1).)*\1[gpiImMw\d]*e"
                      r"|(?:^|[;\n{])\s*e(?:\s|$)"),
    # find : les quatre formes qui exécutent
    "find": re.compile(r"^-(?:exec|execdir|ok|okdir)$"),
    # tar : le filtre externe, sous ses quatre noms
    "tar": re.compile(r"^(?:--to-command|--use-compress-program|--rsh-command"
                      r"|--rmt-command|--checkpoint-action)(?:=|$)|^-I$"),
    # git : la configuration qui nomme un programme, et le chemin d'exécution
    "git": re.compile(r"^--exec-path(?:=|$)|^--(?:upload|receive)-pack(?:=|$)"
                      r"|^(?:core\.(?:pager|editor|sshCommand|fsmonitor|askPass)"
                      r"|sequence\.editor|diff\.external|gpg\.program"
                      r"|alias\.[\w.-]+|filter\.[\w.-]+\.(?:clean|smudge|process)"
                      r"|protocol\.ext\.allow|http\.proxy|remote\.[\w.-]+\.url)="),
    # sort : le filtre de débordement — mesuré, il a démarré le vrai `psql`
    # contre la socket de la grappe de PRODUCTION
    "sort": re.compile(r"^--compress-program(?:=|$)"),
    # install : le programme d'allègement
    "install": re.compile(r"^--strip-program(?:=|$)"),
}
RX_DIRECTIVES_D_EXECUTION["gawk"] = RX_DIRECTIVES_D_EXECUTION["awk"]
RX_DIRECTIVES_D_EXECUTION["mawk"] = RX_DIRECTIVES_D_EXECUTION["awk"]

#: LA DIRECTIVE, RECONNUE PAR SA FORME — le pendant du critère de forme.
#:
#: `RX_DIRECTIVES_D_EXECUTION` est une table par outil : elle sait ce qu'on lui
#: a appris. Le critère de forme, lui, découvre des exécutants dont personne n'a
#: écrit la table — et un exécutant sans directive connue ne serait gardé que
#: par le balayage des chemins absolus. Or les options qui nomment un programme
#: se ressemblent toutes, parce qu'elles décrivent la même chose : `--compress-
#: program`, `--use-compress-program`, `--strip-program`, `--to-command`,
#: `--rsh-command`, `--diff-program`, `--exec-path`, `--pager`, `--editor`.
#: On refuse donc la FORME de l'option chez tout exécutant, connu ou mesuré.
RX_DIRECTIVE_DE_FORME = re.compile(
    r"^--[\w-]*(?:program|command|cmd|exec|editor|pager|filter|shell)(?:=|$)"
)


def _chemin_tolere(chemin: str) -> bool:
    """Un chemin d'exécutable que la suite a le droit de nommer.

    Deux seulement : un programme DU DÉPÔT (l'objet même des tests) et un double
    posé sous le répertoire temporaire (le remède que le talon laisse déjà
    passer). `.venv` est exclu par `_vient_du_depot` — `alembic upgrade` y vit.
    """
    if _vient_du_depot(chemin):
        return True
    jetable = os.environ.get("ARAC_GARDE_JETABLE") or tempfile.gettempdir()
    if not jetable:
        return False
    # LE TEXTE ET LA RÉSOLUTION, comme partout ailleurs depuis cette manche.
    # `PATH=/tmp/faux` où `/tmp/faux` est un lien vers `/usr/bin` s'écrit sous
    # le jetable et rouvre les binaires de l'hôte à tout descendant. Le noyau
    # suit le lien ; ce jugement-ci le suit aussi.
    prefixes = {jetable.rstrip("/") + "/"}
    try:
        prefixes.add(os.path.realpath(jetable).rstrip("/") + "/")
    except (OSError, ValueError):  # pragma: no cover — jetable illisible
        pass
    if not any(chemin.startswith(p) for p in prefixes):
        return False
    try:
        reel = os.path.realpath(chemin)
    except (OSError, ValueError):  # pragma: no cover — chemin illisible
        return True
    return any(reel.startswith(p) for p in prefixes) or reel == chemin


def _ce_qu_un_path_rouvre(valeur: str) -> str:
    """Ce qu'une affectation de `PATH` remet à portée d'un descendant.

    Rend le premier répertoire de l'hôte que cette valeur rouvre, ou « » si elle
    n'ouvre rien. Trois cas, mesurés sur la suite :
      · la valeur contient `$PATH` — le répertoire de refus reste en tête, rien
        n'est rouvert ;
      · la valeur ne désigne que des répertoires qui n'existent pas
        (`PATH=/nonexistent`, employé par `test_g2` pour prouver qu'on REFUSE
        quand l'outil manque) — rien n'est rouvert ;
      · la valeur désigne un répertoire RÉEL hors du dépôt et hors du jetable —
        c'est `export PATH=/usr/bin:/bin`, l'évasion mesurée.
    """
    if "$PATH" in valeur or "${PATH}" in valeur:
        return ""
    for morceau in valeur.split(":"):
        morceau = morceau.strip("\"'")
        if not morceau.startswith("/") or "$" in morceau:
            continue
        if _chemin_tolere(morceau):
            continue
        try:
            if os.path.isdir(morceau):
                return morceau
        except OSError:  # pragma: no cover — chemin illisible
            continue
    return ""


# ---------------------------------------------------------------------------
# LE QUATRIÈME RIDEAU, DE L'AUTRE CÔTÉ DE LA PORTE
# ---------------------------------------------------------------------------
#
# LE RIDEAU DE LECTURE A ÉTÉ ÉCRIT AVEC LA BONNE RAISON, ET ELLE EST CITÉE EN
# TOUTES LETTRES : « le jeton d'un cerveau voisin vit dans un FICHIER. Qui le
# lit n'a plus besoin de `psql` ni de `sudo` : un GET suffit. » La raison est
# juste. L'application ne la suivait que d'un côté : `open`, `os.open`,
# `os.scandir`, `os.remove` étaient enveloppés — et `head`, `grep`, `cat`,
# `find -delete`, `rm -rf`, `sed -i`, `tee` recevaient un CHEMIN sans que
# personne ne le regarde. Mesuré sur ce banc, le même chemin, deux fois :
#
#   open("/var/lib/dpkg/status")           → RefusDeFichier
#   head -2 /var/lib/dpkg/status           → rc=0, le contenu revient
#   os.remove(".../temoin.txt")            → RefusDeFichier
#   find ... -delete   /   rm -rf ...      → rc=0, le fichier n'existe plus
#
# `TENTATIVES_MACHINE` n'a pas bougé : le garde du sous-processus n'a rien vu du
# tout, parce qu'il ne cherchait que des chemins d'EXÉCUTABLE — jamais des
# chemins de DONNÉE. C'est la faute de forme que ce dépôt condamne, appliquée
# non plus au pouvoir d'exécuter mais au pouvoir de LIRE et d'EFFACER.
#
# CE N'EST PAS UNE LISTE D'OUTILS. La correction évidente aurait été d'écrire un
# ensemble `TOUCHE_DES_FICHIERS` à côté d'`EXECUTANTS` — et c'eût été la
# cinquième énumération. Un argument qui désigne un chemin est un chemin, quel
# que soit l'outil qui le reçoit : le contrôle porte donc sur TOUT argument de
# TOUT outil légitime, et il emploie le PÉRIMÈTRE DÉJÀ DÉCLARÉ du rideau de
# lecture (`_lecture_toleree`). Une seule définition de « ce que la suite a le
# droit de toucher », deux endroits qui l'appliquent.

#: Ce que la DISTRIBUTION possède, et où aucun cerveau ne vit. Nommer
#: `/usr/bin/systemd-run` pour demander s'il existe n'est pas lire un cerveau ;
#: le LANCER reste refusé par tout le reste de ce fichier. `/usr/local` n'y est
#: PAS : le bootstrap y installe `arac-depot-sauvegardes`, donc il porte du
#: cerveau.
_RACINES_SANS_CERVEAU: tuple[str, ...] = (
    "/usr/bin", "/usr/sbin", "/usr/include", "/usr/src",
    "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/libx32",
    "/etc/alternatives",
)


def _donnee_toleree(chemin: str) -> bool:
    """Ce chemin peut-il être remis à un sous-processus comme DONNÉE ?

    Les racines sans cerveau sont jugées, elles aussi, sur le chemin QUE LE
    NOYAU ATTEINT et non sur celui qu'on écrit : `cat /usr/bin/<un lien posé
    par un test vers /etc/arac/<voisin>/arac.env>` s'écrit comme `/usr/bin`
    et ouvre le coffre. Même critère qu'en lecture, et pour la même raison.
    """
    if _lecture_toleree(chemin):
        return True
    try:
        absolu = os.path.abspath(chemin)
    except (OSError, ValueError):  # pragma: no cover — chemin illisible
        return False
    reel = _ce_que_le_noyau_atteint(chemin)
    for vu in ((absolu,) if reel == absolu else (absolu, reel)):
        if not any(vu == racine or vu.startswith(racine + "/")
                   for racine in _RACINES_SANS_CERVEAU):
            return False
    return True


def _ancre_existante(chemin: str) -> str | None:
    """Le premier ancêtre qui EXISTE — ou ``None`` s'il n'y a que la racine.

    Un chemin qui n'existe pas ne se lit pas : on ne juge donc pas le chemin,
    on juge l'endroit où il tomberait. `tee /var/log/arac/<voisin>/journal`
    n'existe pas encore ; `/var/log/arac` existe, et c'est là que vivent les
    journaux des cerveaux RÉELS. Quand l'ancre remonte jusqu'à `/`, rien
    n'existe sur ce chemin : `PATH=/nonexistent` et `sed -n '/^motif/p'` ne
    touchent personne, et les refuser aurait été un garde qui crie au loup.
    """
    try:
        if os.path.lexists(chemin):
            return chemin
    except (OSError, ValueError):  # pragma: no cover — chemin illisible
        return None
    parent = os.path.dirname(chemin.rstrip("/")) or "/"
    while parent != "/":
        try:
            if os.path.lexists(parent):
                return parent
        except (OSError, ValueError):  # pragma: no cover
            return None
        parent = os.path.dirname(parent) or "/"
    return None


def _repertoire_effectif(cwd=None) -> str:
    """Le répertoire contre lequel le NOYAU va résoudre les chemins relatifs.

    `cwd=None` ne veut pas dire « pas de répertoire » : c'est celui du
    processus, que `os.chdir` déplace et qu'aucun garde n'enveloppe. Le
    troisième terme de la résolution du noyau est donc, lui aussi, une donnée
    à juger — et c'est le seul qui restait sans juge.
    """
    if cwd is None:
        try:
            return os.getcwd()
        except OSError:  # pragma: no cover — répertoire courant supprimé
            return "/"
    vu = os.fsdecode(cwd) if isinstance(cwd, bytes) else str(cwd)
    return vu or "/"


def _chemins_d_un_argument(arg: str, cwd=None):
    """Ce qui, dans un argument, désigne un endroit du disque.

    NE JUGE PAS UN CHEMIN SUR SON TEXTE QUAND LE NOYAU JUGE SUR SA RÉSOLUTION.
    Cette phrase est celle du correctif des liens magiques `/proc/self` ; elle
    n'avait pas été appliquée jusqu'au bout, et ce qui restait dehors était le
    cas le plus banal de tous : LE MOT NU.

    L'écriture d'avant ne retenait un chemin relatif que s'il était ÉCRIT comme
    tel (`./x`, `../x`), au motif que « sans cela, tout mot serait un chemin
    possible et le garde crierait au loup ». Le noyau, lui, résout CHAQUE
    relatif contre le répertoire courant, quel que soit son aspect. Mesuré en
    régime de repli, `cwd` posé sur le dossier d'un voisin : `cat arac.env`
    rendait son coffre, `tee arac.env` le réécrivait, `rm adieu.dump`
    détruisait son dump — et le témoin disait tout, puisque `cat ./arac.env`,
    LE MÊME FICHIER, était refusé.

    LA RÉPONSE À « CRIER AU LOUP » N'EST PAS UNE EXCEPTION, C'EST UN MEILLEUR
    CRITÈRE : on retient le mot nu quand il EXISTE là où le noyau irait le
    chercher. `grep motif` ne désigne rien et ne réveille personne ; `grep
    motif arac.env`, depuis le dossier d'un voisin, désigne un fichier réel.
    L'existence est mesurée, jamais devinée — et par `realpath`, jamais par
    `normpath` : c'est ce qui fait du critère une RÉSOLUTION et non un texte.
    """
    if arg.startswith("/"):
        yield arg
        return
    if arg.startswith("-"):
        # Une option, pas un chemin — sauf sa VALEUR, et une option porte sa
        # valeur de DEUX façons, pas d'une seule.
        #
        # LE TIRET NE DIT PAS « CE N'EST PAS UN CHEMIN », ET C'EST MESURÉ. Cette
        # branche ne regardait que ce qui suit un `=` (`--file=x`, `-o=/etc/…`).
        # Or les outils que ce dépôt déclare légitimes COLLENT leur valeur à
        # l'option courte, sans aucun `=` : régime de repli, faux voisin,
        # `tar -C/etc/arac/<x> -cf - arac.env` a rendu le coffre et
        # `sort -o/var/backups/arac/<x>/adieu.dump /dev/null` a ramené le dump à
        # zéro octet — les deux avec le journal du garde VIDE, pendant que la
        # même valeur écrite en argument séparé était refusée.
        #
        # On juge donc aussi ce qui suit la LETTRE. On ne compte pas les lettres
        # d'option — chaque outil a sa grammaire, et compter serait deviner
        # comme le faisait le drapeau de corps : on prend le premier endroit de
        # l'argument où commence une forme de chemin. Ce qui n'existe pas ne
        # réveille personne (`_ancre_existante` rend `None` dès que la remontée
        # atteint `/`), si bien que `-e s/a/b/` reste muet.
        if "=" in arg:
            valeur = arg.split("=", 1)[1]
            if valeur.startswith("/"):
                yield valeur
            elif valeur:
                candidat = _ce_que_le_noyau_atteint(
                    os.path.join(_repertoire_effectif(cwd), valeur))
                if os.path.lexists(candidat):
                    yield candidat
        for rang in range(1, len(arg)):
            reste = arg[rang:]
            if reste.startswith(("./", "../")):
                yield _ce_que_le_noyau_atteint(
                    os.path.join(_repertoire_effectif(cwd), reste))
                break
            if reste.startswith("/"):
                yield reste
                break
        return
    if arg.startswith(("./", "../")):
        yield _ce_que_le_noyau_atteint(
            os.path.join(_repertoire_effectif(cwd), arg))
        return
    if arg:
        candidat = _ce_que_le_noyau_atteint(
            os.path.join(_repertoire_effectif(cwd), arg))
        if os.path.lexists(candidat):
            yield candidat


def _controle_du_repertoire(nom: str, commande, cwd=None) -> None:
    """Le répertoire courant est une donnée, et il se juge comme telle.

    `ls`, sans un seul argument, listait le dossier d'un voisin : il n'y avait
    rien à juger dans la commande, et personne ne regardait l'endroit d'où elle
    partait. C'est le même trou que le mot nu, vu par l'autre bout — et il se
    ferme au même endroit, avec le même critère.
    """
    vu = _ce_que_le_noyau_atteint(_repertoire_effectif(cwd))
    if _donnee_toleree(vu):
        return
    _journalise(TENTATIVES_MACHINE, f"{nom} … cwd {vu[:60]}")
    raise RefusDeFichier(
        f"REFUS hermétique (répertoire de travail) : « {nom} » est lancé "
        f"depuis « {vu} ».\n"
        "\n"
        "LE NOYAU RÉSOUT CHAQUE CHEMIN RELATIF CONTRE CE RÉPERTOIRE — y "
        "compris ceux qui n'apparaissent nulle part dans la commande. "
        "Mesuré, rideau seul : `ls` SANS UN SEUL ARGUMENT listait le dossier "
        "d'un voisin, et `cat arac.env` rendait son coffre, pendant que `cat "
        "./arac.env` — le même fichier — était refusé.\n"
        "\n"
        "Ce répertoire vient soit du `cwd=` passé à `Popen`, soit d'un "
        "`os.chdir` (`monkeypatch.chdir`) que rien n'enveloppe.\n"
        "\n"
        "Deux issues : partez de `tmp_path`, ou partez du dépôt.\n"
        f"\nCommande refusée : {str(commande)[:200]}"
    )


#: IL N'Y A PLUS DE DRAPEAU DE CORPS, ET C'EST LE POINT DE CETTE MANCHE.
#: `RX_DRAPEAU_DE_CORPS = re.compile(r"^-[A-Za-z]*c$")` vivait ici : il
#: cherchait « la » place du corps en lisant la FORME du drapeau qui l'annonce.
#: Un juge qui DEVINE se trompe, et celui-ci se trompait de DEUX façons
#: mesurées — `sh -cx CORPS` (le drapeau ne finit pas par `c`) et
#: `sh -c -- CORPS` (il prenait `--` pour le corps et s'arrêtait là). Les deux
#: rendaient le coffre d'un faux voisin, le journal du garde vide, pendant que
#: `-c`, `-xc`, `-lc`, `--norc -c` et `-O extglob -c` étaient, eux, bien vus :
#: c'est ce mélange qui rend un tel juge intenable — on ne peut pas savoir, en
#: le lisant, ce qu'il couvre. La règle qui le remplace ne devine rien : voir
#: `_corps_recus_par_un_shell` — TOUT argument d'un interprète est un corps
#: possible, et on juge les mots de tous. Elle supprime la classe au lieu
#: d'ajouter un cas ; ce qu'elle ne couvre toujours pas — le corps qui n'est pas
#: ÉCRIT dans l'argv (entrée standard, fichier, composition) — est mesuré et
#: déclaré dans `ZONES_NON_COUVERTES_DE_LA_PORTE`.

#: Ce qui, dans un corps de shell, sépare des mots sans en être un : les
#: opérateurs. `>>/etc/arac/<voisin>/arac.env` est UN mot pour `str.split` et
#: DEUX pour le shell — et c'est le second qui désigne un fichier.
_PONCTUATION_DE_SHELL = "();<>|&"


def _mots_du_corps(corps: str) -> list[str]:
    """Le corps d'un shell, découpé comme le shell le découpe.

    POURQUOI PAS `str.split`, ET POURQUOI CE N'EST PAS « ÉCRIRE UN SHELL ».
    La branche `shell=True` découpait son corps avec `corps.split()`. Ce
    découpage-là laisse les guillemets DANS le mot (`cat "/etc/arac/…"` rend un
    mot qui commence par un guillemet, donc pas par `/`) et colle l'opérateur
    au chemin (`>>/etc/arac/…`). Les deux formes échappaient au juge, et elles
    ne demandent pas d'écrire un analyseur : `shlex` est dans la bibliothèque
    standard, il retire les guillemets et — avec `punctuation_chars` — détache
    les opérateurs. C'est une ligne, pas un shell.

    CE QUE CE DÉCOUPAGE NE PRÉTEND PAS ÊTRE. Il ne substitue rien : `$VAR`,
    `$(…)` et les accolades restent du texte. Un chemin COMPOSÉ à l'exécution
    n'est donc pas vu — c'est écrit dans `ZONES_NON_COUVERTES_DE_LA_PORTE`, et
    c'est là que la seconde barrière prend le relais. Ce qu'on ferme ici est ce
    qui est ÉCRIT : le mot que le noyau recevra tel quel.
    """
    try:
        lecteur = shlex.shlex(corps, posix=True, punctuation_chars=True)
        lecteur.whitespace_split = True
        mots = list(lecteur)
    except ValueError:
        # Un corps aux guillemets impairs — souvent un gabarit. On ne renonce
        # pas à le juger : on retombe sur un découpage grossier, débarrassé des
        # opérateurs. Renoncer serait faire du texte mal formé une porte.
        mots = [m.strip(_PONCTUATION_DE_SHELL) for m in corps.split()]
    return [m for m in mots if m.strip(_PONCTUATION_DE_SHELL)]


def _corps_recus_par_un_shell(nom: str, arguments: list[str]) -> list[str]:
    """TOUT ce qu'un interprète reçoit est un corps possible — on ne devine plus.

    `subprocess.run(["sh", "-c", "cat /etc/arac/<voisin>/arac.env"])` remet au
    juge des chemins UN SEUL argument : la phrase entière. `_chemins_d_un_
    argument` la traite alors en MOT NU, la cherche telle quelle sur le disque,
    ne la trouve nulle part — et conclut « ce n'est pas un chemin ». Le coffre
    part. La MÊME phrase écrite `shell=True` était refusée depuis deux manches.

    LA RÉDACTION D'AVANT CHERCHAIT « LE » CORPS, ET ON A TROUVÉ OÙ SE METTRE.
    Elle repérait le drapeau qui annonce le corps (`^-[A-Za-z]*c$`) puis prenait
    l'argument SUIVANT. Mesuré, régime de repli, faux voisin :
    `["sh", "-cx", "cat /etc/arac/<x>/arac.env"]` rendait le coffre — le drapeau
    ne finit pas par `c` — et `["sh", "-c", "--", "cat …"]` aussi, puisque le
    juge prenait `--` pour le corps et s'arrêtait là. `-c`, `-xc`, `-lc`,
    `--norc -c` et `-O extglob -c` étaient, eux, bien vus : c'est ce mélange qui
    rend un tel juge intenable, car on ne peut pas savoir en le lisant ce qu'il
    couvre. Une seule cause : il répondait « à quoi cet argument ressemble-t-il ?
    » là où la question est « qu'est-ce que le noyau ira ouvrir ? ».

    LA RÈGLE GÉNÉRALE QUI SUPPRIME LA CLASSE. On ne cherche plus OÙ est le
    corps : quand le programme est un interprète, on traite CHAQUE argument
    comme un corps possible et on juge les mots de tous. C'est correct par
    construction — un argument qui n'est pas un corps se découpe en lui-même, et
    il était déjà jugé comme argument — et cela ne demande de connaître ni la
    grammaire des drapeaux de `bash`, ni celle de `dash`, ni celle qu'une
    version future ajoutera.

    CE QUE CELA NE FERME PAS, et c'est mesuré : le corps qui n'est pas ÉCRIT
    dans l'argv. `bash -s` le lit sur l'entrée standard, `bash x.sh` dans un
    fichier, `cat "$P/…"` le compose à l'exécution — aucun mot à découper dans
    les trois cas. C'est la limite de tout juge de texte, elle est déclarée dans
    `ZONES_NON_COUVERTES_DE_LA_PORTE`, et c'est là que le noyau prend le relais.
    """
    if nom not in SHELLS:
        return []
    return list(arguments)


def _arguments_a_juger(nom: str, commande) -> list[str]:
    """Tout ce que ce processus va remettre au noyau comme un chemin possible.

    Les arguments de la commande, ET les mots du corps qu'un shell reçoit : le
    noyau ne fait pas la différence entre les deux, et c'est le noyau qui ouvre.
    """
    arguments = [os.fsdecode(b) if isinstance(b, bytes) else str(b)
                 for b in commande[1:]]
    mots = list(arguments)
    for corps in _corps_recus_par_un_shell(nom, arguments):
        mots.extend(_mots_du_corps(corps))
    return mots


def _controle_des_chemins(nom: str, commande, cwd=None) -> None:
    """Aucun argument ne désigne un endroit que la suite n'a pas le droit de lire.

    S'applique à TOUS les outils légitimes, sans exception et sans liste : le
    pouvoir de lire un fichier n'appartient pas à une famille d'outils, il
    appartient à tout ce qui reçoit un chemin — et, depuis cette manche, à tout
    ce qu'un shell reçoit comme CORPS (voir `_corps_recus_par_un_shell`).
    """
    _controle_du_repertoire(nom, commande, cwd=cwd)
    if not isinstance(commande, (list, tuple)):
        return
    for arg in _arguments_a_juger(nom, commande):
        for candidat in _chemins_d_un_argument(arg, cwd):
            ancre = _ancre_existante(candidat)
            if ancre is None or _donnee_toleree(ancre):
                continue
            _journalise(TENTATIVES_MACHINE, f"{nom} … {candidat[:60]}")
            raise RefusDeFichier(
                f"REFUS hermétique (fichier de l'hôte) : « {nom} » reçoit le "
                f"chemin « {candidat} ».\n"
                "\n"
                "LE RIDEAU DE LECTURE A DEUX CÔTÉS, et c'est le second. "
                "`open()` refusait déjà ce chemin depuis Python ; `head` le "
                "rendait, `rm -rf` l'effaçait, `tee` y écrivait — mesuré, le "
                "journal du garde vide. Un outil est légitime pour ce qu'il "
                "FAIT, jamais pour l'endroit où on le pointe : sur une machine "
                "qui porte des cerveaux, `/etc/arac/<un autre>/arac.env` "
                "contient le JETON de ce cerveau, et `/var/backups/arac/<un "
                "autre>` toute sa mémoire.\n"
                "\n"
                "Trois issues, dans l'ordre de préférence :\n"
                "  1. le fichier n'a pas besoin d'être RÉEL : écrivez-le sous "
                "`tmp_path` et pointez l'outil là ;\n"
                "  2. le fichier vient du dépôt : donnez son chemin depuis la "
                "racine du dépôt, il passe sans un mot ;\n"
                "  3. il faut vraiment toucher ce fichier de la machine : "
                "déclarez-le dans `LECTURES_DECLAREES`, avec ce qu'il apporte.\n"
                f"\nCommande refusée : {str(commande)[:200]}"
            )


def _refus_de_corps(motif: str, vu: str, commande) -> RefusHermetique:
    return RefusHermetique(
        f"REFUS hermétique : {motif} — « {vu} ».\n"
        "\n"
        "Le répertoire de refus en tête du `PATH` n'arrête que les noms NUS : un "
        "shell qui reçoit un CHEMIN ne consulte jamais le `PATH`, et un shell "
        "qui rebâtit son `PATH` jette le répertoire de refus. Mesuré sur cette "
        "machine : `bash -c \"/usr/lib/postgresql/16/bin/psql …\"` démarre le "
        "vrai client PostgreSQL et atteint le cluster de production, pendant que "
        "le garde ne voit que « bash ».\n"
        "\n"
        "Trois issues, dans l'ordre de préférence :\n"
        "  1. nommez le programme SANS chemin — le talon fera son travail, et "
        "le refus sera lisible ;\n"
        "  2. posez un DOUBLE sous `tmp_path` et mettez-le en tête du `PATH` "
        "avec `PATH=$FAUX:$PATH` (qui garde le répertoire de refus) ;\n"
        "  3. si le programme vient du DÉPÔT, donnez son chemin depuis la racine "
        "du dépôt : il est reconnu et laissé passer.\n"
        "\n"
        f"Commande refusée : {str(commande)[:300]}"
    )


def _controle_du_corps(nom: str, commande) -> None:
    """Lit ce que va exécuter un outil QUI PEUT EXÉCUTER, et y cherche les formes.

    LA QUESTION N'EST PAS « EST-CE UN SHELL ? » mais « cet outil peut-il
    exécuter ce qu'on lui donne ? ». La rédaction précédente disait : « n'est
    appliqué qu'aux SHELLS : ailleurs, un chemin absolu est une donnée
    (`grep /usr/bin/psql fichier` ne lance rien) ». C'est vrai de `grep` et de
    `cat` ; c'est FAUX de `awk`, `sed`, `find`, `tar` et `git`, qui reçoivent du
    texte et en exécutent une partie. Cette phrase est la cause exacte d'une
    évasion mesurée : `awk 'BEGIN{system("/usr/…/psql -p 5432 -d arac …")}'`
    a rendu le compte d'atomes du cerveau de PRODUCTION à un simple `pytest`.

    On l'applique donc à `SHELLS | EXECUTANTS`, et on refuse en plus la
    DIRECTIVE d'exécution elle-même (`system(`, `-exec`, `--to-command`,
    `-c alias.x=!…`, le drapeau `e` d'un `s///`) — pour que le refus tombe dans
    le père, où il enseigne, plutôt qu'au fond d'un descendant.

    L'ENSEMBLE DES EXÉCUTANTS N'EST PLUS UNE LISTE ÉCRITE. `est_un_executant`
    ajoute à la liste ce que la MESURE a trouvé sur cette machine : un outil
    dont l'ELF nomme une porte de la famille `exec` peut lancer un programme,
    qu'on y ait pensé ou non. C'est ainsi que `sort --compress-program` et
    `install --strip-program` sont fermés, sans que personne n'ait eu à les
    deviner. Ce que cela ne vaut toujours pas est déclaré dans
    `ZONES_NON_COUVERTES_DE_LA_PORTE`.
    """
    if nom not in SHELLS and not est_un_executant(nom):
        return
    if not isinstance(commande, (list, tuple)):
        return
    directive = RX_DIRECTIVES_D_EXECUTION.get(nom)
    for brut in commande[1:]:
        arg = os.fsdecode(brut) if isinstance(brut, bytes) else str(brut)
        if nom not in SHELLS and RX_DIRECTIVE_DE_FORME.match(arg):
            _journalise(TENTATIVES_MACHINE, f"{nom} … {arg[:40]}")
            raise _refus_de_corps(
                f"« {nom} » reçoit une option qui NOMME UN PROGRAMME : cet "
                "outil peut exécuter (mesuré dans son ELF), et une option dont "
                "le nom finit par `-program`, `-command`, `-exec`, `-pager` ou "
                "`-shell` désigne toujours la même chose — le programme qu'il "
                "ira lancer (mesuré : `sort --compress-program` a démarré le "
                "vrai `psql` contre la grappe de PRODUCTION)",
                arg[:80], commande)
        if directive and directive.search(arg):
            _journalise(TENTATIVES_MACHINE, f"{nom} … {arg[:40]}")
            raise _refus_de_corps(
                f"« {nom} » reçoit une DIRECTIVE D'EXÉCUTION : cet outil est "
                "légitime pour ce qu'il LIT, pas pour ce qu'il LANCE (mesuré : "
                "`awk 'BEGIN{system(…)}'` a lu le cerveau de production depuis "
                "un test, le garde muet)",
                arg[:80], commande)
    for brut in commande[1:]:
        arg = os.fsdecode(brut) if isinstance(brut, bytes) else str(brut)
        for m in RX_CHEMIN_D_EXECUTABLE.finditer(arg):
            chemin, base = m.group(0), m.group(2)
            if base in OUTILS_LEGITIMES or _RX_PYTHON.match(base):
                continue
            if _chemin_tolere(chemin):
                continue
            _journalise(TENTATIVES_MACHINE, f"{nom} -c … {chemin}")
            raise _refus_de_corps(
                "un shell reçoit le CHEMIN ABSOLU d'un exécutable de l'hôte",
                chemin, commande)
        for m in RX_RACINE_DE_BINAIRES.finditer(arg):
            if _chemin_tolere(m.group(0)):
                continue
            _journalise(TENTATIVES_MACHINE, f"{nom} -c … {m.group(0)}/…")
            raise _refus_de_corps(
                "un shell reçoit une RACINE de binaires de l'hôte, qu'il suffit "
                "d'assembler avec un nom pour contourner le talon du `PATH`",
                m.group(0), commande)
        for m in RX_PATH_AFFECTE.finditer(arg):
            ouvert = _ce_qu_un_path_rouvre(m.group(1))
            if not ouvert:
                continue
            _journalise(TENTATIVES_MACHINE, f"{nom} -c … PATH={ouvert}")
            raise _refus_de_corps(
                "un descendant REBÂTIT son `PATH` au lieu de l'allonger : il "
                "jette le répertoire de refus et rouvre un répertoire de "
                "binaires de l'hôte (écrivez `PATH=$FAUX:$PATH`)",
                f"PATH=…{ouvert}…", commande)
        for m in RX_PYTHONPATH_AFFECTE.finditer(arg):
            valeur = m.group(1)
            if "$PYTHONPATH" in valeur or "${PYTHONPATH}" in valeur:
                continue  # ALLONGER est le geste légitime, comme pour `PATH`
            _journalise(TENTATIVES_MACHINE, f"{nom} … PYTHONPATH={valeur[:20]}")
            raise _refus_de_corps(
                "un descendant REBÂTIT ou VIDE son `PYTHONPATH` : le "
                "`sitecustomize` qui repose les trois gardes dans tout `python` "
                "fils n'est alors plus lu, et ce fils n'a NI garde de réseau, NI "
                "garde de base, NI garde de processus (mesuré : il rend "
                "`socket.socket.connect` d'origine). C'est `python -I` obtenu "
                "sans écrire `-I` — écrivez `PYTHONPATH=$X:$PYTHONPATH`",
                f"PYTHONPATH={valeur[:40]}", commande)
        m = RX_UNSET_DE_L_HERITAGE.search(arg)
        if m:
            _journalise(TENTATIVES_MACHINE, f"{nom} … unset {m.group(1)}")
            raise _refus_de_corps(
                "un descendant EFFACE la variable qui porte l'héritage du garde "
                "(`unset PATH` jette le répertoire de refus, `unset PYTHONPATH` "
                "jette le `sitecustomize`)",
                f"unset {m.group(1)}", commande)
        if RX_ENV_RASE.search(arg):
            _journalise(TENTATIVES_MACHINE, f"{nom} -c … env -i")
            raise _refus_de_corps(
                "`env -i` rase l'environnement, donc le `PATH` de refus et les "
                "variables du garde",
                "env -i", commande)
        m = RX_PYTHON_DESHABILLE.search(arg)
        if m:
            _journalise(TENTATIVES_MACHINE, f"{nom} -c … python -I/-E/-S")
            raise _refus_de_corps(
                "un interpréteur Python DÉSHABILLÉ (`-I`, `-E`, `-S`) est lancé "
                "depuis un shell : il n'hérite ni du garde de la base, ni de "
                "celui du réseau, ni de celui des processus — mesuré, il ouvre "
                "un socket vers 127.0.0.1:5432",
                m.group(0).strip(), commande)


def _corps_de_shell(commande) -> str:
    """Le texte qu'un `shell=True` (ou `os.system`) remet à `/bin/sh -c`."""
    if isinstance(commande, (list, tuple)):
        premier = commande[0] if commande else ""
        return os.fsdecode(premier) if isinstance(premier, bytes) else str(premier)
    return os.fsdecode(commande) if isinstance(commande, bytes) else str(commande)


def _controle(commande, executable=None, cwd=None, shell=False):
    """Le point de passage unique de TOUTE création de processus.

    Trois choses lui sont passées en plus de la commande, et chacune ferme une
    dissociation MESURÉE entre le nom jugé et le programme lancé :

    · `executable=` — le mot-clé de `Popen` qui remplace le programme sans
      toucher `argv[0]` (`["cat"], executable="/usr/…/psql"` a démarré le vrai
      client PostgreSQL, `TENTATIVES_MACHINE` vide) ;
    · `cwd=` — un `./cat` ne désigne pas le même fichier selon le répertoire ;
    · `shell=True` — la commande n'est plus un programme, c'est un CORPS de
      shell. Le garde lisait son premier mot : un corps de la forme
      « cat un-fichier ; <chemin absolu d'un binaire de l'hôte> » passait, parce
      que `cat` est légitime. Un corps de shell doit être LU comme un corps de
      shell, du premier caractère au dernier.
    """
    if shell:
        corps = _corps_de_shell(commande)
        # Le premier mot reste jugé — il donne le refus le plus lisible — mais
        # ce n'est plus lui qui décide : tout le corps est lu.
        ok, nom = est_legitime([corps.split()[0]] if corps.split() else [])
        if not ok:
            _journalise(TENTATIVES_MACHINE, nom or corps[:60])
            raise _refus_de_processus(nom, commande)
        _controle_du_corps("sh", ["-c", corps])
        # LE CORPS D'UN SHELL EST FAIT D'ARGUMENTS, ET ILS DÉSIGNENT DES
        # FICHIERS. Cette branche retournait avant tout contrôle de chemin :
        # `subprocess.run("cat arac.env", shell=True, cwd=<voisin>)` rendait
        # son coffre là où la même commande en liste était refusée.
        #
        # UN SEUL JUGE POUR LES DEUX ÉCRITURES, ET C'EST LE POINT. Ce corps-ci
        # était découpé ICI et nulle part ailleurs — si bien que le même corps
        # arrivé en LISTE (`["sh", "-c", …]`) n'était découpé par personne. On
        # remet donc la forme `shell=True` dans la forme LISTE et on appelle le
        # juge commun : deux écritures, un seul critère, et plus de moitié qui
        # progresse sans l'autre.
        _controle_des_chemins("sh", ["sh", "-c", corps], cwd=cwd)
        return
    ok, nom = est_legitime(commande, executable=executable, cwd=cwd)
    if not ok:
        _journalise(TENTATIVES_MACHINE, nom or str(commande)[:60])
        raise _refus_de_processus(nom, commande)
    if nom in ENVELOPPES:
        _journalise(TENTATIVES_MACHINE, nom)
        raise RefusHermetique(
            f"REFUS hermétique : « {nom} » est une ENVELOPPE.\n"
            "Le garde ne peut pas dire ce qu'elle lance, et « je ne sais pas » "
            "ne vaut pas « c'est permis ». C'est l'erreur exacte qui a laissé "
            "passer `sudo -n -u postgres psql -d arac` pendant des mois : le "
            "garde lisait `args[0]`, y voyait « sudo », et concluait.\n"
            "Nommez directement le programme que vous voulez lancer.\n"
            f"Commande refusée : {str(commande)[:200]}"
        )
    if _RX_PYTHON.match(nom) and isinstance(commande, (list, tuple)):
        for brut in commande[1:]:
            arg = os.fsdecode(brut) if isinstance(brut, bytes) else str(brut)
            if not arg.startswith("-") or arg.startswith("--"):
                break
            if set(arg[1:]) & _LETTRES_SANS_HERITAGE:
                _journalise(TENTATIVES_MACHINE, f"python {arg}")
                raise RefusHermetique(
                    f"REFUS hermétique : « python {arg} » — un interpréteur "
                    "lancé ainsi n'hérite PAS des gardes.\n"
                    "`-E` et `-I` ignorent PYTHONPATH, `-S` saute `site` : dans "
                    "les trois cas le `sitecustomize` qui repose les gardes dans "
                    "le fils n'est jamais lu, et ce fils peut ouvrir une "
                    "connexion vers n'importe quelle base.\n"
                    "Lancez l'interpréteur sans ces drapeaux, ou exercez le code "
                    "avec un double.\n"
                    f"Commande refusée : {str(commande)[:200]}"
                )
    _controle_du_corps(nom, commande)
    _controle_des_chemins(nom, commande, cwd=cwd)


# ---------------------------------------------------------------------------
# 3 bis. LA PERMISSION VOYAGE — le PATH de refus et le sitecustomize
# ---------------------------------------------------------------------------


_TALON = """#!/bin/sh
# Posé par tests/garde_hermetique.py — NE PAS MODIFIER, ce fichier est engendré.
#
# La suite de tests est hermétique : elle lit le dépôt, elle n'interroge pas
# l'hôte. Ce talon porte le nom d'un programme de la machine qui n'est pas dans
# la liste des outils légitimes ; il est en tête du PATH de tout descendant de
# la suite, à n'importe quelle profondeur.
nom=${0##*/}

# Un DOUBLE posé par le test lui-même reste permis : il ne touche pas l'hôte,
# c'est le remède, pas la faute. On le cherche dans le PATH DE CET APPELANT,
# amputé du répertoire de refus — et surtout pas dans un PATH figé à
# l'installation du garde : le test qui pose un double le pose PENDANT la
# session, en tête de SON propre PATH.
sans_refus=""
ancien_ifs=$IFS
IFS=:
for repertoire in $PATH; do
    [ "$repertoire" = "${ARAC_GARDE_REFUSDIR:-}" ] && continue
    sans_refus="${sans_refus:+$sans_refus:}$repertoire"
done
IFS=$ancien_ifs
reel=$(PATH="$sans_refus" command -v "$nom" 2>/dev/null) || reel=""
case "$reel" in
    "${ARAC_GARDE_DEPOT:-/dev/null/jamais}"/.venv/*) ;;
    "${ARAC_GARDE_DEPOT:-/dev/null/jamais}"/*) exec "$reel" "$@" ;;
    "${ARAC_GARDE_JETABLE:-/dev/null/jamais}"/*) exec "$reel" "$@" ;;
esac

[ -n "${ARAC_GARDE_REFUS:-}" ] && printf '%s\\n' "$nom" >> "$ARAC_GARDE_REFUS"
cat >&2 <<FIN
REFUS hermétique (sous-processus) : « $nom ».

La suite de tests lit le dépôt ; elle n'interroge pas l'hôte. Cet appel vient
d'un descendant de la suite (un script lancé par un test), et il a été refusé
avant d'atteindre la machine.

Ce qui aurait pu arriver sans ce refus, et qui arrivait pour de vrai :
« sudo -u postgres psql -p 5432 » interrogeait le cluster de PRODUCTION pendant
un simple « make test », et « systemctl » l'inventaire des unités du voisin.

Le remède : posez un DOUBLE de « $nom » dans un répertoire du PATH de ce
sous-processus (sous tmp_path), comme le fait test_bootstrap_services_unites
pour systemd-run. Le talon laisse passer les doubles.
FIN
exit 127
"""

_SITECUSTOMIZE = '''"""Posé par tests/garde_hermetique.py — les gardes suivent le fils.

`python` est l'un des trois outils autorisés à lancer d'autres programmes. Sans
ce fichier, `python -c "import psycopg; psycopg.connect(…)"` lancé par un test
atteindrait une base sans que le moindre garde le voie : le fils est un
processus neuf, et les gardes du père sont des monkeypatchs de sa mémoire.
"""
import os
import sys

_racine = os.environ.get("ARAC_GARDE_DEPOT")
if _racine and _racine not in sys.path:
    sys.path.insert(0, _racine)
try:
    from tests.garde_hermetique import installer_les_gardes
except Exception:  # le dépôt n'est pas là : ce fils ne peut rien exécuter de lui
    pass
else:
    installer_les_gardes()
'''


def _construire_le_path_de_refus() -> Path:
    """Un talon de refus pour chaque nom du PATH qui n'est pas légitime.

    C'EST L'INVERSION, RENDUE EXÉCUTABLE. On ne pose pas un talon devant les
    noms qu'on redoute — on en pose un devant TOUS ceux qu'on n'a pas
    explicitement autorisés. `mysql`, `kubectl`, `redis-cli`, `pg_dumpall`, et
    le binaire que quelqu'un installera demain sont couverts sans qu'une seule
    ligne ne les nomme.
    """
    dossier = Path(tempfile.mkdtemp(prefix="arac-garde-refus-"))
    refuseur = dossier / ".refuser.sh"
    refuseur.write_text(_TALON, encoding="utf-8")
    refuseur.chmod(0o755)

    poses: set[str] = set()
    for repertoire in os.environ.get("PATH", "").split(os.pathsep):
        if not repertoire:
            continue
        try:
            entrees = os.scandir(repertoire)
        except OSError:
            continue
        with entrees:
            for e in entrees:
                nom = e.name
                if nom in poses or nom in OUTILS_LEGITIMES or _RX_PYTHON.match(nom):
                    continue
                try:
                    if not (e.is_file() and os.access(e.path, os.X_OK)):
                        continue
                except OSError:
                    continue
                try:
                    (dossier / nom).symlink_to(refuseur)
                except OSError:
                    continue
                poses.add(nom)
    return dossier


#: Le préfixe du répertoire qui porte le `sitecustomize`. Nommé une fois, et
#: relu partout : c'est à cette marque que le garde reconnaît SON héritage dans
#: un `PYTHONPATH`, aussi bien pour refuser qu'on l'efface que pour le démonter.
PREFIXE_DU_SITECUSTOMIZE = "arac-garde-python-"


def _construire_le_sitecustomize() -> Path:
    dossier = Path(tempfile.mkdtemp(prefix=PREFIXE_DU_SITECUSTOMIZE))
    (dossier / "sitecustomize.py").write_text(_SITECUSTOMIZE, encoding="utf-8")
    return dossier


def _poser_l_heritage() -> None:
    """Rend la permission héréditaire, par l'environnement du processus.

    On modifie `os.environ` — donc l'environnement que TOUT enfant hérite, quel
    que soit le mécanisme (`Popen`, `os.system`, `os.posix_spawn`, un fils de
    fils). Un test qui passe un `env=` explicite est rattrapé séparément, dans
    l'enveloppe de `Popen`.
    """
    if os.environ.get("ARAC_GARDE_PATH_HOTE"):
        return  # déjà posé — y compris hérité d'un père déjà gardé
    journal = Path(tempfile.mkdtemp(prefix="arac-garde-journal-")) / "refus.txt"
    journal.touch()
    _JOURNAL_DESCENDANTS.append(journal)

    os.environ["ARAC_GARDE_PATH_HOTE"] = os.environ.get("PATH", "")
    os.environ["ARAC_GARDE_DEPOT"] = str(RACINE_DEPOT)
    os.environ["ARAC_GARDE_JETABLE"] = tempfile.gettempdir()
    os.environ["ARAC_GARDE_REFUS"] = str(journal)
    refus = str(_construire_le_path_de_refus())
    os.environ["ARAC_GARDE_REFUSDIR"] = refus
    os.environ["PATH"] = refus + os.pathsep + os.environ.get("PATH", "")
    garde_py = _construire_le_sitecustomize()
    ancien = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = (
        str(garde_py) + (os.pathsep + ancien if ancien else "")
    )
    # QUI CRÉE DÉMONTE. `pytest_terminal_summary` démonte la session
    # principale, mais un descendant qui n'a pas hérité des variables (un
    # `env -i`, un shell qui reconstruit son environnement) repose l'héritage
    # pour lui-même et créerait alors trois répertoires que personne ne
    # ramasse. Mesuré : cinquante et un `/tmp/arac-garde-journal-*` en une
    # après-midi. Une suite qui laisse des restes n'est pas hermétique.
    import atexit

    atexit.register(demonter_l_heritage)


def _environnement_garde(env):
    """Réinjecte l'héritage dans un environnement explicite. Fail-closed.

    Appelée partout où un environnement est REÇU — le mot-clé `env=` de `Popen`,
    son onzième paramètre positionnel, et le rang que chaque primitive `os.*` de
    la famille `exec`/`spawn` réserve à l'environnement. La rédaction
    précédente ne l'appelait que dans `Popen`, et la docstring de
    `_poser_l_heritage` l'écrivait comme une certitude : « un test qui passe un
    `env=` explicite est rattrapé séparément, dans l'enveloppe de `Popen` ».
    Vraie de `Popen`, fausse de `os.posix_spawn`, `os.execve` et `os.spawnve`,
    qui prennent tous un environnement et n'en recevaient aucun contrôle.
    """
    if env is None:
        return None
    try:
        neuf = dict(env)
    except (TypeError, ValueError):  # pragma: no cover — pas un mapping
        return env
    for cle in VARIABLES_DU_GARDE + ("PYTHONPATH",):
        neuf[cle] = os.environ.get(cle, "")
    refus = os.environ["ARAC_GARDE_REFUSDIR"]
    chemin = neuf.get("PATH", os.environ.get("ARAC_GARDE_PATH_HOTE", ""))
    if chemin.split(os.pathsep)[:1] != [refus]:
        neuf["PATH"] = refus + os.pathsep + chemin
    return neuf


def _rang_de_l_environnement(nom: str, rang_du_programme: int) -> int | None:
    """Où une primitive `os.*` reçoit son environnement — lu dans son NOM.

    La famille POSIX porte ses pouvoirs dans ses lettres, et cette convention
    ne bouge plus depuis 1988 : ``v`` un vecteur d'argv, ``l`` les arguments à
    plat, ``p`` la recherche dans le `PATH`, ``e`` **et un environnement** —
    toujours le dernier paramètre. Lire le nom plutôt que tenir une table, c'est
    couvrir `execve`, `execvpe`, `execle`, `execlpe`, `spawnve`, `spawnvpe`,
    `spawnle`, `spawnlpe` et ce que CPython ajoutera demain sous la même règle.

    Rend ``-1`` quand l'environnement est le DERNIER argument (formes ``l``),
    l'indice sinon, ``None`` quand la primitive n'en prend pas.
    """
    if nom.startswith("posix_spawn"):
        return rang_du_programme + 2  # (chemin, argv, env, …)
    for racine in ("exec", "spawn"):
        if nom.startswith(racine):
            lettres = nom[len(racine):]
            if not lettres.endswith("e"):
                return None
            return -1 if lettres.startswith("l") else rang_du_programme + 2
    return None


def _commande_d_une_primitive(nom: str, rang: int, rang_env: int | None,
                              args: tuple) -> list:
    """La commande COMPLÈTE qu'une primitive `os.*` remet au noyau.

    LE PROGRAMME ÉTAIT JUGÉ, LA LISTE D'ARGUMENTS NE L'ÉTAIT PAS. L'enveloppe
    des primitives passait `args[rang]` — le seul PROGRAMME — au juge commun.
    Comme ce n'est pas une liste, `_controle_des_chemins` rendait la main sans
    juger un seul argument, et `_controle_du_corps` avec. Mesuré, régime de
    repli, faux voisin, sans un seul corps de shell : `os.spawnv`, `os.spawnve`,
    `os.spawnlp`, `os.posix_spawn`, et `os.execv`/`execve`/`execl`/`execlp`/
    `execvp` après un `fork` ont TOUS rendu le coffre — neuf canaux, neuf fois
    le journal du garde vide, pendant que `subprocess.run(["cat", <le même
    chemin>])` était refusé depuis des manches. C'est le trou le plus large de
    la famille, et le moins cher : il ne demande même pas de shell.

    LE NOM DE LA PRIMITIVE DIT OÙ EST L'ARGV, comme il disait déjà où est
    l'environnement (cf. `_rang_de_l_environnement`) — POSIX.1 ne bouge plus
    depuis 1988 : ``v`` un VECTEUR à la place suivante, ``l`` les arguments À
    PLAT jusqu'à la fin, ``e`` un environnement en dernier qui n'en fait pas
    partie. On lit le nom plutôt que de tenir une table : `execv`, `execve`,
    `execvp`, `execvpe`, `execl`, `execle`, `execlp`, `execlpe`, les huit
    `spawn*` de même, `posix_spawn` et `posix_spawnp`.

    Rend la commande dans la FORME que le juge de `subprocess` reçoit —
    programme en tête, arguments ensuite. `argv[0]` est écarté : c'est
    l'ÉTIQUETTE du programme, pas un chemin qu'on ouvre, et le programme, lui,
    est jugé comme tête de la commande.
    """
    programme = args[rang]
    if nom.startswith("posix_spawn"):
        lettres = "v"
    elif nom.startswith("exec"):
        lettres = nom[len("exec"):]
    elif nom.startswith("spawn"):
        lettres = nom[len("spawn"):]
    else:  # `system`, `popen` : un CORPS, pas un programme et son argv
        return programme
    if lettres.startswith("v"):
        vecteur = args[rang + 1] if len(args) > rang + 1 else ()
        argv = list(vecteur) if isinstance(vecteur, (list, tuple)) else []
    else:
        argv = list(args[rang + 1:])
        if rang_env == -1 and argv:
            argv = argv[:-1]  # les formes `l…e` portent l'environnement en fin
    return [programme, *argv[1:]]


def _refuse_l_effacement_de_l_heritage(nom_var: str, valeur: str | None) -> None:
    """Refuse d'effacer, depuis PYTHON, ce dont l'héritage du garde dépend.

    `os.putenv` écrit dans l'environnement C sans passer par `os.environ` : le
    fils suivant naît nu et rien, dans l'appel, ne le montre. `os.unsetenv` de
    même. On applique ici la règle EXACTE déjà défendue pour les corps de shell
    — allonger est permis, rebâtir ou vider ne l'est pas — parce qu'une règle
    qui change selon la porte par laquelle on entre n'est pas une règle.
    """
    if nom_var not in VARIABLES_DE_L_HERITAGE:
        return
    refusdir = os.environ.get("ARAC_GARDE_REFUSDIR", "")
    if valeur is not None:
        morceaux = valeur.split(os.pathsep)
        if nom_var == "PATH":
            if refusdir in morceaux or not _ce_qu_un_path_rouvre(valeur):
                return
        # ON CHERCHE LA MARQUE, PAS LA PLACE. La première rédaction comparait
        # au PREMIER morceau du `PYTHONPATH` courant : allonger par la tête
        # (`PYTHONPATH=<le mien>:$PYTHONPATH`, le geste que ce garde
        # RECOMMANDE) déplaçait la marque, et le rétablissement de la valeur
        # d'origine se faisait alors refuser. Un garde qui interdit le geste
        # qu'il prescrit finit désactivé.
        elif any(PREFIXE_DU_SITECUSTOMIZE in m for m in morceaux):
            return
    _journalise(TENTATIVES_MACHINE,
                f"{'unsetenv' if valeur is None else 'putenv'} {nom_var}")
    raise RefusHermetique(
        f"REFUS hermétique : ce geste EFFACE « {nom_var} », dont l'héritage du "
        "garde dépend.\n"
        "\n"
        f"{VARIABLES_DE_L_HERITAGE[nom_var]}\n"
        "\n"
        "La dépendance n'est pas une opinion : elle est écrite dans "
        "`VARIABLES_DE_L_HERITAGE`, et un test l'ÉPROUVE en effaçant chaque "
        "variable dans un fils pour vérifier que ce fils en sort nu. Mesuré : "
        "`os.putenv(\"PYTHONPATH\", \"\")` puis un `subprocess.run` rend un "
        "interpréteur sans garde de réseau, sans garde de base, sans garde de "
        "processus et sans rideau de lecture.\n"
        "\n"
        "Le geste permis est d'ALLONGER : `PYTHONPATH=<le vôtre>:$PYTHONPATH`, "
        "`PATH=<le vôtre>:$PATH`. Depuis Python, passez plutôt par `env=` : il "
        "est LU et corrigé par le garde."
    )


def refus_des_descendants() -> list[str]:
    """Ce que le PATH de refus a arrêté au fond des sous-processus."""
    vus: list[str] = []
    for journal in _JOURNAL_DESCENDANTS:
        try:
            for ligne in journal.read_text(encoding="utf-8").splitlines():
                if ligne.strip() and ligne.strip() not in vus:
                    vus.append(ligne.strip())
        except OSError:
            continue
    return vus


def demonter_l_heritage() -> None:
    """Efface les TROIS répertoires engendrés. Appelé en fin de session.

    Les trois, et pas deux : la première rédaction oubliait le journal des
    refus, et cinquante et un `/tmp/arac-garde-journal-*` s'étaient accumulés
    en une après-midi. Une suite qui laisse des restes derrière elle n'est pas
    hermétique — c'est la mesure même que `make acceptance` applique à
    l'installation, et elle vaut d'abord pour les tests.
    """
    for chemin in os.environ.get("PATH", "").split(os.pathsep)[:1]:
        if "arac-garde-refus-" in chemin:
            shutil.rmtree(chemin, ignore_errors=True)
    for chemin in os.environ.get("PYTHONPATH", "").split(os.pathsep)[:1]:
        if PREFIXE_DU_SITECUSTOMIZE in chemin:
            shutil.rmtree(chemin, ignore_errors=True)
    for journal in _JOURNAL_DESCENDANTS:
        shutil.rmtree(journal.parent, ignore_errors=True)
    _JOURNAL_DESCENDANTS.clear()


def installer_les_gardes() -> None:
    """Pose les trois gardes. Idempotent : un second appel ne fait rien."""
    import subprocess

    if getattr(installer_les_gardes, "_pose", False):
        return
    installer_les_gardes._pose = True  # type: ignore[attr-defined]

    socket.socket.connect = _refuse_la_sortie  # type: ignore[method-assign]
    socket.socket.connect_ex = _refuse_la_sortie_ex  # type: ignore[method-assign]

    _poser_l_heritage()
    # LA MESURE DES POUVOIRS a lieu ici, et pas ailleurs : elle lit les binaires
    # du `PATH` de l'hôte, exactement comme la construction du répertoire de
    # refus qui vient de l'être — donc AVANT que le rideau de lecture n'existe,
    # et une seule fois par session.
    _mesurer_les_pouvoirs()
    # APRÈS `_poser_l_heritage`, et pas avant : la construction du répertoire de
    # refus balaie les répertoires du `PATH` de l'hôte (`/usr/bin`, `/usr/sbin`)
    # pour y poser un talon devant chaque nom. C'est la seule lecture hors
    # périmètre du dispositif, elle est faite par le garde lui-même, et elle a
    # lieu avant que le garde de lecture n'existe.
    _installer_le_garde_de_lecture()

    _popen_reel = subprocess.Popen.__init__

    def _popen_garde(self, args, *a, **k):
        # LES RANGS POSITIONNELS DE `Popen`, ET POURQUOI ON LES LIT.
        # `Popen(args, bufsize, executable, stdin, stdout, stderr, preexec_fn,
        #  close_fds, shell, cwd, env, …)`. Ne lire que les mots-clés, c'est
        # laisser passer `Popen(["cat"], -1, "/usr/bin/psql")` — mesuré : le
        # vrai client PostgreSQL démarre, le garde ne voit que « cat ».
        executable = k.get("executable", a[1] if len(a) >= 2 else None)
        shell = k.get("shell", a[7] if len(a) >= 8 else False)
        cwd = k.get("cwd", a[8] if len(a) >= 9 else None)
        _controle(args, executable=executable, cwd=cwd, shell=shell)
        # `preexec_fn` TOURNE DANS LE FILS, APRÈS le contrôle. Un
        # `preexec_fn=lambda: os.unsetenv("PYTHONPATH")` rend donc un fils NU
        # sans qu'aucun motif de ce fichier n'ait rien à lire — mesuré : le fils
        # rend `socket.socket.connect` d'origine, le journal du garde vide.
        preexec = k.get("preexec_fn", a[5] if len(a) >= 6 else None)
        if preexec is not None:
            _journalise(TENTATIVES_MACHINE, "preexec_fn")
            raise RefusHermetique(
                "REFUS hermétique : `preexec_fn` — cette fonction tourne dans "
                "le FILS, après le contrôle ; le garde ne peut pas dire ce "
                "qu'elle fait.\n"
                "Mesuré : `preexec_fn=lambda: os.unsetenv(\"PYTHONPATH\")` rend "
                "un fils sans AUCUN des gardes, et rien dans l'appel ne le "
                "montre. Ce que l'héritage du garde exige est écrit dans "
                "`VARIABLES_DE_L_HERITAGE`.\n"
                "Le remède : faites ce réglage dans `env=`, qui est LU et "
                "corrigé par le garde.\n"
                f"Commande refusée : {str(args)[:200]}"
            )
        if "env" in k:
            k["env"] = _environnement_garde(k["env"])
        elif len(a) >= 10:
            # `env` est le ONZIÈME paramètre de `Popen` — donc l'indice 9 de
            # `a`, qui NE PORTE PAS `args` (capturé à part dans la signature).
            # La rédaction précédente lisait `len(a) >= 9` puis `a[9]` : avec
            # exactement neuf positionnels — jusqu'à `cwd`, sans `env` — elle
            # levait `IndexError('tuple index out of range')` au lieu du refus
            # qui enseigne, et accusait le garde plutôt que l'appel.
            a = a[:9] + (_environnement_garde(a[9]),) + a[10:]
        return _popen_reel(self, args, *a, **k)

    subprocess.Popen.__init__ = _popen_garde  # type: ignore[method-assign]

    # LES AUTRES PORTES. `subprocess` n'est pas le seul chemin vers un
    # processus : `os.system` appelle la libc directement, `os.posix_spawn` et
    # `os.exec*` aussi. Un test qui les emploie ne voyait AUCUN garde. On les
    # fait toutes passer par le même point de contrôle — et on ne les énumère
    # pas à la main : on prend, dans `os`, tout ce qui porte le nom d'une
    # primitive de création de processus.
    # `os.popen` s'ajoute à la main : il ne porte dans son nom aucune des
    # racines ci-dessus, et il lance pourtant un `/bin/sh -c`. Il était ouvert.
    _PRIMITIVES = tuple(
        n for n in dir(os)
        if (n in ("system", "popen") or n.startswith(("exec", "spawn", "posix_spawn")))
        and callable(getattr(os, n, None))
    )
    for nom_primitive in _PRIMITIVES:
        reel = getattr(os, nom_primitive, None)
        if not callable(reel):
            continue
        # `os.spawn*` prend le MODE en premier argument, le programme en second.
        # Se tromper de position rendrait le garde bavard au lieu d'exact.
        rang = 1 if nom_primitive.startswith("spawn") else 0
        # `os.system` et `os.popen` ne reçoivent PAS un programme : ils
        # reçoivent un CORPS de shell. Le juger sur son premier mot laissait
        # passer `os.system("cat /etc/x; /bin/hostname")` — mesuré, rc=0.
        par_le_shell = nom_primitive in ("system", "popen")
        # L'ENVIRONNEMENT EST UN ARGUMENT COMME UN AUTRE, ET IL N'ÉTAIT JUGÉ
        # NULLE PART. Cette boucle ne lisait que le PROGRAMME : elle voyait
        # « python », le déclarait légitime, et laissait passer le TROISIÈME
        # argument — qui est l'environnement. Mesuré : `os.posix_spawn(py,
        # argv, {})` et `os.execve(py, argv, {})` rendent un fils SANS aucun
        # des quatre gardes, sans écrire ni `-I`, ni `bash`, ni un chemin.
        #
        # On ne range pas les rangs à la main : la FAMILLE `exec`/`spawn` porte
        # ses pouvoirs dans son NOM depuis POSIX.1 — `v` = un vecteur d'argv,
        # `l` = les arguments à plat, `p` = cherché dans le `PATH`, `e` = ET UN
        # ENVIRONNEMENT, toujours en dernier. Le nom dit donc où il est.
        rang_env = _rang_de_l_environnement(nom_primitive, rang)

        def _enveloppe(*args, _reel=reel, _rang=rang, _sh=par_le_shell,
                       _renv=rang_env, _nom=nom_primitive, **kwargs):
            if len(args) > _rang:
                # L'ARGV AUSSI, ET PAR LE MÊME JUGE. On ne remet plus le seul
                # programme : `_commande_d_une_primitive` rend la commande
                # entière, dans la forme que `subprocess` remet déjà, pour que
                # les huit canaux de création de processus rendent le MÊME
                # verdict sur la MÊME commande.
                _controle(_commande_d_une_primitive(_nom, _rang, _renv, args),
                          shell=_sh)
            if _renv is not None:
                indice = len(args) - 1 if _renv == -1 else _renv
                if indice > _rang and len(args) > indice:
                    args = (args[:indice] + (_environnement_garde(args[indice]),)
                            + args[indice + 1:])
            if "env" in kwargs:
                kwargs["env"] = _environnement_garde(kwargs["env"])
            return _reel(*args, **kwargs)

        _enveloppe.__name__ = nom_primitive
        setattr(os, nom_primitive, _enveloppe)

    # CE QUI EFFACE L'HÉRITAGE DEPUIS PYTHON, refusé comme on le refuse déjà
    # depuis un shell. `os.putenv` écrit dans l'environnement C sans toucher
    # `os.environ` : aucun `env=` n'est passé, `_environnement_garde` n'est
    # jamais appelé, et le fils suivant naît nu. Mesuré, la suite verte.
    _putenv_reel = os.putenv
    _unsetenv_reel = os.unsetenv

    def _putenv_garde(cle, valeur):
        nom_var = os.fsdecode(cle) if isinstance(cle, bytes) else str(cle)
        val = os.fsdecode(valeur) if isinstance(valeur, bytes) else str(valeur)
        _refuse_l_effacement_de_l_heritage(nom_var, val)
        return _putenv_reel(cle, valeur)

    def _unsetenv_garde(cle):
        nom_var = os.fsdecode(cle) if isinstance(cle, bytes) else str(cle)
        _refuse_l_effacement_de_l_heritage(nom_var, None)
        return _unsetenv_reel(cle)

    os.putenv = _putenv_garde  # type: ignore[assignment]
    os.unsetenv = _unsetenv_garde  # type: ignore[assignment]

    # DEUX PORTES QUE `dir(os)` NE DONNE PAS, et qui étaient ouvertes.
    #
    # 1. `pty.spawn`. Il passe bien par `os.execlp` — mais APRÈS `os.forkpty()`,
    #    donc dans le FILS. Mesuré : le refus était levé dans un fils qui, ne
    #    mourant pas, continuait d'exécuter la session pytest ; le père, lui,
    #    voyait `pty.spawn` rendre la main sans rien dire. Un test qui éprouve
    #    l'entretien interactif — ce dépôt en a un — croyait avoir exécuté ce
    #    qu'il demandait. On contrôle donc AVANT la fourche, dans le père.
    # 2. `_posixsubprocess.fork_exec`. C'est l'entrée C sous `subprocess`, et
    #    `multiprocessing.util.spawnv_passfds` l'appelle DIRECTEMENT : la
    #    méthode de démarrage « spawn » créait donc un processus sans passer ni
    #    par `subprocess.Popen`, ni par une primitive de `os`. Mesuré :
    #    `mp.get_context("spawn").Process(...)` démarrait, exitcode 0.
    try:
        import pty
    except Exception:  # pragma: no cover — pas de pty sur cette plateforme
        pass
    else:
        _pty_reel = pty.spawn

        def _pty_garde(argv, *a, **k):
            _controle(argv if isinstance(argv, (list, tuple)) else [argv])
            return _pty_reel(argv, *a, **k)

        pty.spawn = _pty_garde  # type: ignore[assignment]

    try:
        import _posixsubprocess
    except Exception:  # pragma: no cover — implémentation sans ce module
        pass
    else:
        _fork_exec_reel = _posixsubprocess.fork_exec

        def _fork_exec_garde(*args, **kwargs):
            if args:
                _controle(args[0])
            return _fork_exec_reel(*args, **kwargs)

        _posixsubprocess.fork_exec = _fork_exec_garde  # type: ignore[assignment]

    try:
        import psycopg
    except Exception:
        # Un fils qui n'a pas psycopg ne peut pas ouvrir de connexion : les deux
        # autres gardes suffisent. Ne PAS échouer ici — un `sitecustomize` qui
        # tue l'interpréteur casserait des sous-processus légitimes.
        return

    _sync_reel = psycopg.Connection.connect
    _async_reel = psycopg.AsyncConnection.connect

    def _connect_garde(*args, **kwargs):
        dsn = _dsn_du_connect(args, kwargs)
        base = nom_de_base(dsn)
        with _fenetre_base():
            conn = _sync_reel(*args, **kwargs)
        try:
            verifie_la_marque_sync(conn, base)
        except RefusHermetique:
            _journalise(TENTATIVES_BASE, base)
            with _fenetre_base():
                conn.close()
            raise
        except BaseException:
            with _fenetre_base():
                conn.close()
            raise
        return conn

    async def _connect_garde_async(*args, **kwargs):
        dsn = _dsn_du_connect(args, kwargs)
        base = nom_de_base(dsn)
        with _fenetre_base():
            conn = await _async_reel(*args, **kwargs)
        try:
            await verifie_la_marque_async(conn, base)
        except RefusHermetique:
            _journalise(TENTATIVES_BASE, base)
            with _fenetre_base():
                await conn.close()
            raise
        except BaseException:
            with _fenetre_base():
                await conn.close()
            raise
        return conn

    psycopg.Connection.connect = _connect_garde  # type: ignore[method-assign]
    psycopg.AsyncConnection.connect = _connect_garde_async  # type: ignore[method-assign]
    # `psycopg.connect` est une méthode DÉJÀ LIÉE, capturée à l'import du
    # paquet (`connect = Connection.connect` dans `psycopg/__init__.py`).
    # Remplacer la classmethod ne la change donc pas : il faut la réécrire.
    # Les tests qui écrivent `psycopg.connect(dsn)` — 0006, 0007, 0008, bus —
    # sont précisément ceux qui touchaient la base sans passer par les
    # fixtures, donc sans passer par le garde d'avant.
    psycopg.connect = _connect_garde  # type: ignore[assignment]


# ============================================================================
# 4. LA LECTURE — le second rideau, et la zone qui était déclarée nue
# ============================================================================
#
# POURQUOI CE QUATRIÈME GARDE EXISTE, ET POURQUOI IL EST UN *SECOND* RIDEAU
# ========================================================================
# Les trois premiers gardent la SORTIE : une socket, une connexion de base, un
# processus. `ZONES_NON_COUVERTES_DE_LA_PORTE` déclarait, en toutes lettres, que
# la LECTURE de fichiers n'était gardée par personne : « un test peut donc lire
# les coffres des cerveaux installés sur la machine ». Ce n'était pas une
# hypothèse — une session de contrôle a listé les noms de `/etc/arac/` pour
# mesurer la zone, et l'a écrit.
#
# Or la lecture n'est pas une zone parmi d'autres : c'est la PREMIÈRE MOITIÉ de
# l'évasion la plus simple qui reste. Le jeton d'un cerveau voisin vit dans
# `/etc/arac/<lui>/arac.env`. Qui peut le lire n'a plus besoin de `psql`, ni de
# `sudo`, ni d'un chemin calculé : il lui suffit d'un GET. Fermer la lecture ne
# rend pas les autres mailles impossibles — elle les rend SANS EFFET, et c'est
# très exactement ce qu'on demande d'une défense en profondeur.
#
# CE QU'IL VAUT, ET CE QU'IL NE VAUT PAS
# ======================================
# Il ne remplace pas la vraie seconde barrière — l'`uid`, ou un espace de noms.
# Sous `root`, un test qui appelle la libc directement lit ce qu'il veut. Ce
# garde-ci couvre les lectures PYTHON, c'est-à-dire celles qu'un test écrit.
#
# LA MESURE QUI AUTORISE L'INVERSION. On n'énumère pas les fichiers interdits —
# `/etc/arac`, `/var/backups/arac`, `/opt/<cerveau>/.env` : une liste oublierait
# le cerveau installé ailleurs, et c'est la faute que ce dépôt a corrigée cinq
# fois. On énumère ce que la suite a le DROIT de lire, et le droit se mesure :
# un espion posé sur `open` pendant une session complète a compté ZÉRO ouverture
# hors du dépôt, hors du répertoire jetable et hors de l'installation Python. La
# liste ci-dessous n'est donc pas un pari : c'est le relevé de ce que la suite
# fait déjà.
#
# CETTE MESURE A CHANGÉ, ET ON LA RÉÉCRIT PLUTÔT QUE DE LA LAISSER VIEILLIR.
# Elle disait « ZÉRO » et donnait un compte de tests (4 950). Le périmètre s'est
# depuis RESSERRÉ — le `/proc/<pid>/` d'un autre processus et les périphériques
# de `/dev` en sont sortis — et le zéro avec lui. Relevé sur une session
# complète (5 086 tests, dépôt principal) : **241 ouvertures refusées**, toutes
# sous `/proc/<pid>/` d'un tiers, dont **235 `cmdline`** venant d'un seul
# endroit — `control_center/collectors/sobriety.py::_claude_running`, qui
# balaie `/proc` pour compter les `claude` en cours. Ce n'est pas une lecture à
# déclarer : ce code attrape déjà `OSError` et continue, son test reste vert, et
# le compte qu'il rend est celui d'une machine où il ne voit rien — ce qui est
# exactement ce qu'une suite hermétique doit lui montrer.
#
# Un chiffre daté vaut mieux qu'un chiffre faux : ce relevé est de la session
# qui a fermé le trou de `/proc`, et il se refait en lisant la section
# « hermétisme : LECTURES de l'hôte refusées » imprimée en fin de session.

TENTATIVES_LECTURE: list[str] = []

#: Les lectures HORS PÉRIMÈTRE qu'un test déclare avoir besoin de faire, avec
#: sa raison. Vide — et ce vide n'est pas l'absence de refus (il y en a 241 par
#: session, voir ci-dessus) : c'est l'absence de BESOIN. Chacun de ces refus
#: tombe dans du code qui a son chemin d'indisponibilité et le prend. Le jour où
#: une lecture sera vraiment nécessaire, elle s'écrira ici, avec ce qu'elle
#: demande à la machine — sauf le `/proc` d'un tiers, que `_lecture_toleree`
#: refuse AVANT de regarder ce dictionnaire, et délibérément.
LECTURES_DECLAREES: dict[str, str] = {}

#: `/proc/<pid>/` D'UN AUTRE PROCESSUS — LE COFFRE, EN CLAIR, SANS LE COFFRE.
#:
#: CE QUI ÉTAIT ÉCRIT ICI, ET QUI ÉTAIT FAUX. Cette racine portait pour raison :
#: « `/proc` et `/sys` ne portent le cerveau de personne ». `/proc` porte le
#: cerveau de TOUT service arac de la machine. L'unité systemd d'un cerveau
#: porte `EnvironmentFile=/etc/arac/<lui>/arac.env` : le noyau recopie ce coffre
#: dans l'environnement du service, et `/proc/<son pid>/environ` en est la copie
#: VERBATIM — jeton porteur et DSN avec mot de passe, en clair, sans avoir à
#: ouvrir `/etc/arac`. Le rideau fermait la porte du coffre et laissait la
#: fenêtre ouverte sur son contenu. Une épreuve a lu par là, il y a plusieurs
#: manches, le DSN d'administration d'un voisin.
#:
#: ET LA PHRASE FAUSSE COÛTAIT PLUS CHER QUE LE TROU. Le trou seul, on le
#: retrouve en relisant. Le trou AVEC sa justification écrite, personne ne le
#: rouvre : la ligne a déjà l'air examinée. C'est la classe de défaut que ce
#: dépôt condamne partout ailleurs (la preuve verte par construction), et elle
#: vivait ici, sur le fichier le plus sensible de la machine.
#:
#: LE GRAIN, ET POURQUOI CELUI-LÀ. On ne ferme pas `/proc` — la machinerie
#: Python et le code testé y lisent pour de vrai (`/proc/loadavg` dans
#: `control_center/collectors/system_metrics.py`, `/proc/net/tcp` dans le même,
#: `os.listdir('/proc')` dans `collectors/sobriety.py`). On ferme LE RÉPERTOIRE
#: D'UN AUTRE PROCESSUS, en entier : `environ` n'est pas le seul — `cmdline`
#: porte le DSN de tout `psql "postgresql://arac_admin:<mdp>@…"` en cours.
#: `/proc/self`, `/proc/thread-self`, `/proc/<notre propre pid>` et tout ce qui
#: n'est pas un répertoire de processus passent ce refus-ci — mesuré : la suite
#: lit `/proc/self/status` et `/proc/meminfo` sans un mot.
#:
#: ET CE REFUS-CI NE SUFFIT PAS — LA PHRASE QUI DISAIT LE CONTRAIRE ÉTAIT FAUSSE.
#: Elle ajoutait, dans la même parenthèse : « `fd/`, `root/` et `cwd/` rouvrent
#: tout le disque par un lien ». C'est vrai, et le lecteur en concluait que ces
#: trois-là étaient fermés. Ils ne l'étaient QUE POUR UN AUTRE PID. Or
#: `/proc/self/root/…` et `/proc/self/cwd/…` sont les liens magiques de NOTRE
#: PROPRE processus : aucun chiffre à comparer, rien qui sorte de `/proc` après
#: `abspath` — et le noyau, lui, les réécrit vers `/` et vers le répertoire
#: courant, c'est-à-dire vers TOUT LE DISQUE. Mesuré, rideau seul : le coffre
#: d'un faux voisin lu, écrasé, son dump détruit, `/etc/shadow` lu, par `open`,
#: par `pathlib` et par `cat` en sous-processus. Un refus qui compte les pids ne
#: pouvait pas voir cela : `self` n'est un autre pid pour personne.
#:
#: LE CRITÈRE QUI NE S'ÉNUMÈRE PAS, et c'est la leçon de dix manches : NE JUGE
#: PAS UN CHEMIN SUR SON TEXTE QUAND LE NOYAU JUGE SUR SA RÉSOLUTION. Ce n'est
#: pas une exception de plus (`self`, `thread-self`, `<notre pid>`, `root`,
#: `cwd`, `fd`, et demain le lien magique qu'on n'a pas listé) : `_lecture_
#: toleree` soumet désormais au MÊME périmètre le chemin normalisé ET le chemin
#: que `realpath` atteint. Un chemin n'est toléré que si les DEUX le sont.
#: `/proc/self/root/etc/arac/<voisin>/arac.env` se résout en
#: `/etc/arac/<voisin>/arac.env`, qui n'a jamais été toléré : il tombe, sans
#: qu'aucun préfixe de `/proc` ait eu à être nommé.
#:
#: CE QUE LA SECONDE BARRIÈRE FERME, ET CE QU'ELLE NE FERME PAS — mesuré, parce
#: que c'est ce qui décide si ce garde-ci est un doublon ou la seule maille.
#: Landlock posé, `/proc/<un autre>/environ` est REFUSÉ par le noyau (EACCES) :
#: un processus restreint ne peut plus tracer un processus qui ne l'est pas.
#: Mais `/proc/<un autre>/cmdline` et `/proc/<un autre>/status` se lisent
#: TOUJOURS — la restriction ptrace ne les couvre pas. Le rideau Python n'est
#: donc pas un doublon, même en régime nominal, et il est la SEULE maille en
#: régime de repli (noyau sans Landlock, `ARAC_SANS_SECONDE_BARRIERE=1`), que ce
#: dépôt documente comme supporté.
_PID_DANS_PROC = re.compile(r"/proc/(\d+)(?:/|$)")


def _proc_d_un_autre(absolu: str) -> bool:
    """Ce chemin tombe-t-il dans le `/proc/<pid>/` d'un AUTRE processus ?

    On juge sur le chemin normalisé ET sur sa résolution réelle : sans la
    seconde, `/proc/self/root/proc/<voisin>/environ` passerait — `/proc/self`
    ne porte pas de chiffre, et `abspath` ne suit pas les liens. Mesuré.
    """
    if absolu != "/proc" and not absolu.startswith("/proc/"):
        return False
    candidats = [absolu]
    try:
        candidats.append(os.path.realpath(absolu))
    except (OSError, ValueError):  # pragma: no cover — chemin illisible
        pass
    for candidat in candidats:
        trouve = _PID_DANS_PROC.match(candidat)
        if trouve and int(trouve.group(1)) != os.getpid():
            return True
    return False


#: Ce que la machinerie doit pouvoir lire pour que Python existe. Ce n'est pas
#: la même chose qu'une permission accordée à la suite, et chaque entrée porte
#: désormais une raison qu'on peut vérifier :
#:
#: · `/proc` — IL PORTE UN CERVEAU PAR SERVICE, et la phrase qui disait le
#:   contraire a tenu ce trou ouvert deux manches. Il est ici pour ses
#:   pseudo-fichiers globaux (`loadavg`, `meminfo`, `net/tcp`, que le code testé
#:   lit vraiment) ; le répertoire de chaque AUTRE processus en est retranché
#:   par `_proc_d_un_autre`, avant toute racine et avant toute déclaration.
#: · `/sys` — mesuré : ZÉRO ouverture Python sur une session complète (5 052
#:   tests). Il n'est donc pas là pour la suite, mais pour la machinerie NATIVE,
#:   qui n'emprunte pas ce rideau (les bibliothèques de calcul y lisent la
#:   topologie des processeurs). Il ne porte aucun coffre : rien de ce que le
#:   produit installe n'écrit dans `/sys`, et le noyau n'y recopie aucun
#:   environnement. Le retirer ne gagnerait rien de mesurable et pourrait
#:   changer un régime sans qu'on sache pourquoi — c'est dit, plutôt que tu.
#: · `/usr/share`, `/usr/lib`, `/usr/local/lib`, l'installation Python — le code
#:   de la distribution. Un cerveau n'y vit pas : le produit installe sous
#:   `/etc/arac`, `/var/lib/arac`, `/var/log/arac` et `/var/backups/arac`, tous
#:   REFUSÉS ici, et `tests/test_les_exceptions_du_rideau_disent_vrai.py` le
#:   vérifie racine par racine plutôt que de le croire.
#: · `/etc/ssl/certs`, `/etc/ca-certificates`, `/etc/alternatives` — les
#:   autorités de certification, lues à l'import de `ssl`. Ce sont des
#:   certificats PUBLICS.
#:
#:   ET CETTE RAISON-LÀ A ÉTÉ FAUSSE JUSQU'À CETTE MANCHE, sous une forme qui
#:   mérite d'être écrite en entier parce qu'elle est la troisième du même
#:   genre dans ce fichier. La racine accordée était `/etc/ssl` TOUT ENTIER, et
#:   sa raison finissait par : « la clé privée d'un serveur ne vit pas là ».
#:   Sur Debian et Ubuntu, la clé privée d'un serveur vit très exactement là :
#:   `/etc/ssl/private/`. Mesuré sur cette machine, rideau seul :
#:   `open("/etc/ssl/private/ssl-cert-snakeoil.key")` rendait `-----BEGIN
#:   PRIVATE KEY-----`. La phrase ne décrivait pas le droit qu'elle accordait —
#:   c'est la faute de `/dev` (« `/dev/null` s'écrit » pour justifier `/dev/sda`)
#:   commise une fois de plus, un répertoire plus loin.
#:
#:   LE GRAIN EST DONC CELUI DE LA RAISON : `certs`, et rien d'autre. Ce que la
#:   machinerie demande vraiment est mesurable —
#:   `ssl.get_default_verify_paths()` rend `/usr/lib/ssl/cert.pem` et
#:   `/usr/lib/ssl/certs`, qui sont des liens vers `/etc/ssl/certs`. Ils passent
#:   toujours, parce que le rideau juge désormais aussi la RÉSOLUTION : le lien
#:   et sa cible sont dans le périmètre. `/etc/ssl/openssl.cnf` n'y est pas, et
#:   c'est délibéré — aucune ouverture mesurée sur une session complète.
#: · `/dev` N'EST PLUS UNE RACINE — voir `_PORTES_DE_DEV` ci-dessus : la raison
#:   écrite (« `/dev/null` s'écrit ») nommait deux fichiers pour un répertoire
#:   qui, sous `root`, contient `/dev/sda` et `/dev/mem`.
#:
#: ET LA RACINE QUI N'A JAMAIS EU DE RAISON ÉCRITE — parce qu'elle n'est écrite
#: nulle part. `sys.prefix`, `sys.base_prefix` et `sysconfig.get_paths()` sont
#: ajoutés à la liste pour que Python trouve sa propre installation. Sur une
#: machine ordinaire, `sys.base_prefix` vaut **`/usr`** : la liste ci-dessus
#: nomme soigneusement `/usr/share`, `/usr/lib` et `/usr/local/lib` avec une
#: raison chacune, et une quatrième ligne — invisible, calculée — accorde le
#: parent des trois, en entier. Les trois raisons écrites ne décrivaient donc
#: pas le droit accordé ; elles en décrivaient un tiers.
#:
#: CE QUE ÇA OUVRAIT, MESURÉ EN RÉGIME DE REPLI (rideau seul) : `os.mkdir`
#: RÉUSSIT sous `/usr/local/bin/`, sous `/usr/bin/` et sous
#: `/usr/lib/systemd/system/`. Or `_RACINES_SANS_CERVEAU`, dix lignes plus
#: haut, écrit noir sur blanc : « `/usr/local` n'y est PAS : le bootstrap y
#: installe `arac-depot-sauvegardes`, donc il porte du cerveau ». Le rideau de
#: lecture disait le contraire de la doctrine que le rideau des données
#: énonce — et il le disait par omission, ce qui est la seule façon dont une
#: exception peut vivre sans être relue.
#:
#: `_RETRANCHEES` — LES ENDROITS QU'AUCUNE RACINE NE PEUT RECOUVRIR. Plutôt que
#: de rogner `sys.base_prefix` (qui vaudra autre chose ailleurs, et qui casse
#: alors sans qu'on sache pourquoi), on RETRANCHE, de toute racine quelle
#: qu'elle soit, les endroits où le PRODUIT dépose quelque chose. La liste ne
#: vient pas de l'hôte : elle vient de ce que `bootstrap/` installe. Le jour où
#: une racine nouvelle recouvrira l'un d'eux — par un `sys.path` exotique, par
#: un `sysconfig` de distribution, par une ligne ajoutée sans discussion — elle
#: ne le recouvrira pas.
def _racines_de_lecture() -> tuple[str, ...]:
    import sys as _sys
    import sysconfig as _sysconfig

    racines = {str(RACINE_DEPOT), tempfile.gettempdir(), "/proc", "/sys",
               "/usr/share", "/usr/lib", "/usr/local/lib", "/etc/ssl/certs",
               "/etc/ca-certificates", "/etc/alternatives"}
    for cle in ("stdlib", "purelib", "platlib", "data"):
        try:
            racines.add(_sysconfig.get_paths()[cle])
        except Exception:  # pragma: no cover — installation exotique
            continue
    racines.update({_sys.prefix, _sys.base_prefix})
    racines.update(c for c in _sys.path if c.startswith("/"))
    jetable = os.environ.get("ARAC_GARDE_JETABLE")
    if jetable:
        racines.add(jetable)
    # CHAQUE RACINE SOUS SES DEUX NOMS. Le rideau juge désormais aussi la
    # RÉSOLUTION d'un chemin (voir `_lecture_toleree`) ; une racine qui est
    # elle-même un lien — `/tmp` → `/private/tmp` sur macOS, un dépôt cloné
    # sous un chemin lié — se verrait alors refuser ses propres fichiers.
    # C'est le même endroit sous deux noms, pas un droit de plus.
    for racine in tuple(racines):
        try:
            racines.add(os.path.realpath(racine))
        except (OSError, ValueError):  # pragma: no cover — racine illisible
            continue
    return tuple(sorted(r.rstrip("/") or "/" for r in racines if r))


_RACINES_DE_LECTURE: tuple[str, ...] = ()

#: Les fichiers de la machine que la bibliothèque standard ouvre pour des
#: raisons qui ne concernent personne — l'heure, l'encodage, le nom d'hôte. Ils
#: sont nommés un par un : un fichier n'est pas un répertoire, et `/etc/passwd`
#: ne devient pas `/etc/arac/<voisin>/arac.env` par distraction.
_FICHIERS_DE_LA_MACHINERIE = frozenset({
    "/etc/localtime", "/etc/timezone", "/etc/os-release", "/etc/hosts",
    "/etc/resolv.conf", "/etc/nsswitch.conf", "/etc/passwd", "/etc/group",
    "/etc/mime.types", "/etc/hostname", "/etc/machine-id",
})

#: `/dev` — L'EXCEPTION DONT LA RAISON ÉTAIT PLUS ÉTROITE QUE LE DROIT.
#:
#: `/dev` figurait comme RACINE, en lecture ici et en ÉCRITURE COMPLÈTE dans la
#: seconde barrière, avec pour toute raison : « `/dev/null` s'écrit,
#: `/dev/urandom` se lit ». Les deux moitiés de la phrase sont vraies ; ce
#: qu'elles justifient ne l'est pas. Sous `root` — et cette suite tourne sous
#: `root` — la même racine ouvrait `/dev/sda` et `/dev/mem` : les disques bruts
#: de la machine et sa mémoire vive, c'est-à-dire TOUS les coffres à la fois,
#: chiffrés ou non, et de quoi les écraser. Une justification qui nomme deux
#: pseudo-fichiers pour accorder un répertoire entier n'est pas une petite
#: imprécision : c'est la forme exacte du défaut que ce fichier condamne.
#:
#: LA MESURE QUI DÉCIDE DE LA LISTE. Espion posé sur toutes les portes de
#: lecture pendant une session complète (5 052 tests) : la suite ouvre UN seul
#: chemin sous `/dev`, et c'est `/dev/null`. Le reste de cette liste est ce que
#: la machinerie et les sous-processus demandent — `/dev/zero` (`head -c 7000
#: /dev/zero` dans `test_le_juge_ne_tire_pas_au_sort`), les deux sources
#: d'aléa, le terminal, et les portes du pseudo-terminal (`pty.openpty`, que
#: `test_la_porte_du_sous_processus_est_fermee` et ce fichier-ci utilisent :
#: elles s'ouvrent DANS la libc et ne passent jamais par ce rideau, mais la
#: barrière du noyau, elle, les voit).
#:
#: Ce qui n'y est pas, et volontairement : `/dev/shm` — un tmpfs partagé par
#: toute la machine, où rien du produit n'écrit — et tous les périphériques
#: bloc et caractère.
_PORTES_DE_DEV = frozenset({
    "/dev/null", "/dev/zero", "/dev/full", "/dev/random", "/dev/urandom",
    "/dev/tty", "/dev/ptmx", "/dev/console",
    "/dev/stdin", "/dev/stdout", "/dev/stderr",
})

#: Les répertoires de `/dev` où un chemin se compose à l'exécution : le numéro
#: d'un pseudo-terminal et le numéro d'un descripteur ne se nomment pas
#: d'avance. Ils ne portent rien de durable — un terminal meurt avec sa session.
_RACINES_DE_DEV = ("/dev/pts", "/dev/fd")


def _ce_que_le_noyau_atteint(chemin: str) -> str:
    """Le chemin que le NOYAU ouvrira réellement — liens magiques compris.

    `os.path.abspath` est du calcul de TEXTE : il replie les `..` sans jamais
    demander au disque, et il ne suit aucun lien. `os.path.realpath` demande.
    C'est toute la différence entre les deux jugements, et c'est celle qui a
    tenu ce trou ouvert : `/proc/self/root/etc/shadow` reste, pour `abspath`,
    un chemin de `/proc`, et devient `/etc/shadow` pour le noyau.

    ON LUI DONNE LE CHEMIN BRUT, JAMAIS SON `abspath` — et cette ligne-là est
    tout le sujet. `abspath("/proc/self/cwd/../x")` rend `/proc/self/x` : le
    `..` est replié AVANT le lien, et le détour a disparu du texte qu'on
    s'apprêtait à résoudre. `realpath` du chemin brut résout `cwd` d'abord,
    puis remonte depuis LÀ — c'est ce que fait le noyau, et il rend `<parent du
    répertoire courant>/x`. Mesuré : la première écriture rendait ce détour
    « toléré », la seconde le refuse.

    On ne lève pas : un chemin illisible se juge sur son texte, et un texte
    hors périmètre est déjà refusé — *fail-closed*.
    """
    try:
        return os.path.realpath(chemin)
    except (OSError, ValueError):  # pragma: no cover — chemin illisible
        try:
            return os.path.abspath(chemin)
        except (OSError, ValueError):  # pragma: no cover
            return chemin


#: LES ENDROITS QU'AUCUNE RACINE NE RECOUVRE, quelle que soit la racine.
#:
#: Ils viennent de ce que le PRODUIT installe, jamais de ce qui existe sur
#: cette machine : `bootstrap/lib/services.sh` pose le coffre, les journaux,
#: les sauvegardes, l'état et le foyer du compte de service ; `docs/
#: SAUVEGARDE.md` pose `/usr/local/bin/arac-depot-sauvegardes`, la porte
#: restreinte du dépôt de sauvegardes d'un voisin ; les unités vivent dans
#: `/etc/systemd/system`. Aucun n'a de raison d'être lu par une suite de tests,
#: et aucun ne doit pouvoir rentrer par la porte de derrière d'une racine
#: calculée.
#:
#: LE CRITÈRE A CHANGÉ, ET C'EST LA CORRECTION. « Là où le produit ÉCRIT »
#: était plus étroit que le danger, et la liste le prouvait elle-même : la
#: raison écrite au-dessus citait TROIS endroits mesurés où `os.mkdir`
#: réussissait — `/usr/local/bin/`, `/usr/bin/` et `/usr/lib/systemd/system/`
#: — et n'en fermait que deux. Le troisième est resté ouvert une manche de
#: plus, sous une phrase qui avait l'air relue.
#:
#: Le bon critère n'est pas « où le produit écrit », c'est « CE QUE LE SYSTÈME
#: LIT POUR FAIRE VIVRE UN CERVEAU ». Le produit écrit dans UN répertoire
#: d'unités ; systemd les cherche dans DOUZE (`systemd-analyze unit-paths`).
#: Écrire ailleurs dans cette recherche ne modifie pas le fichier du voisin —
#: c'est pire, ça ajoute une surcharge qui s'applique à SON unité au prochain
#: `daemon-reload`, sans que son fichier à lui ait bougé d'un octet.
#:
#: Des douze, une seule est sous une racine accordée — `/usr/lib/systemd`, que
#: `sys.base_prefix` (`/usr`) recouvre. `/usr/local/lib/systemd/system` est
#: déjà couvert par `/usr/local` ; les `/etc/…` et les `/run/…` ne sont sous
#: aucune racine et sont refusés depuis toujours. Deux familles voisines
#: entrent par la même porte et pour la même raison — le répertoire n'est pas
#: celui où le produit dépose, c'est celui où le SYSTÈME va chercher :
#:
#:   · `/usr/lib/tmpfiles.d` — le produit dépose `/etc/tmpfiles.d/
#:     arac-backup.conf` ; `systemd-tmpfiles` lit AUSSI `/usr/lib/tmpfiles.d`,
#:     et une ligne `R!` y efface un répertoire entier au démarrage. C'est-à-
#:     dire, écrite depuis une suite de tests, la mémoire SAUVEGARDÉE d'un
#:     voisin — celle qu'on garde précisément pour le jour où le reste a brûlé.
#:   · `/usr/lib/sysusers.d` — le bootstrap crée `arac_<base>` et
#:     `aracagent_<base>`, les comptes sous lesquels tournent les services d'un
#:     cerveau ; `systemd-sysusers` lit ce répertoire et crée ou complète des
#:     comptes au démarrage. Un compte est ce qui porte les droits d'un
#:     cerveau : le fabriquer ailleurs revient à s'en donner les clés.
#:
#: MESURÉ, RÉGIME DE REPLI, avant correction, sur des noms à moi retirés
#: aussitôt : `os.mkdir('/usr/lib/systemd/system/arac-<voisin>-api.service.d')`
#: réussissait et la surcharge s'y écrivait ; `/usr/lib/tmpfiles.d/` s'écrivait
#: aussi. `_lecture_toleree` rendait `True` pour les deux.
_RETRANCHEES: tuple[str, ...] = (
    "/etc/arac", "/var/lib/arac", "/var/log/arac", "/var/backups/arac",
    "/etc/systemd/system", "/usr/local", "/root/.pgpass", "/etc/ssl/private",
    "/usr/lib/systemd", "/usr/lib/tmpfiles.d", "/usr/lib/sysusers.d",
)


def _retranche(absolu: str) -> bool:
    """Cet endroit est-il hors d'atteinte de TOUTE racine ?"""
    return any(absolu == r or absolu.startswith(r + "/")
               for r in _RETRANCHEES)


def _sous_le_perimetre(absolu: str) -> bool:
    """Ce chemin-ci — pris pour ce qu'il DIT — est-il dans le périmètre ?

    N'appeler que par `_lecture_toleree`, qui la pose deux fois : sur le texte
    et sur la résolution. Seule, elle juge une étiquette.
    """
    # AVANT LES RACINES, ET AVANT LES DÉCLARATIONS. Une racine calculée
    # (`sys.base_prefix` vaut `/usr`) recouvrait `/usr/local`, que le rideau
    # des données déclare pourtant porteur de cerveau. Le retranchement passe
    # donc devant tout le reste — comme `_proc_d_un_autre`, et pour la même
    # raison : ce qui protège un voisin ne se lève pas par une ligne ajoutée
    # dans un dictionnaire.
    if _retranche(absolu):
        return False
    if absolu in _FICHIERS_DE_LA_MACHINERIE or absolu in LECTURES_DECLAREES:
        return True
    if absolu in _PORTES_DE_DEV:
        return True
    for racine_dev in _RACINES_DE_DEV:
        if absolu == racine_dev or absolu.startswith(racine_dev + "/"):
            return True
    for racine in _RACINES_DE_LECTURE:
        if absolu == racine or absolu.startswith(racine + "/"):
            return True
    return False


def _lecture_toleree(chemin: str) -> bool:
    """Ce chemin est-il dans ce que la suite a le droit de lire ?

    DEUX JUGEMENTS, ET IL FAUT LES DEUX. Le chemin tel qu'il est ÉCRIT (une
    fois normalisé) et le chemin que le NOYAU atteint. Un seul des deux hors
    périmètre suffit à refuser.

    · le texte seul laissait passer `/proc/self/root/<n'importe quoi>` et
      `/proc/self/cwd/../../<n'importe quoi>` — les liens magiques de NOTRE
      PROPRE processus, qui ne portent aucun chiffre à comparer et qui
      rouvrent tout le disque. Mesuré, rideau seul : coffre d'un voisin lu et
      écrasé, dump détruit, `/etc/shadow` lu ;
    · la résolution seule laisserait passer l'inverse — un lien posé DANS le
      périmètre et pointant dehors serait jugé sur sa cible, ce qui est bien,
      mais un chemin hors périmètre qui n'existe pas encore (`realpath` le
      rend inchangé) doit rester refusé sur son texte.

    Le critère ne s'énumère pas : il ne connaît ni `self`, ni `thread-self`,
    ni `root/`, ni `cwd/`, ni `fd/`. Il connaît une seule chose — le noyau ne
    juge pas sur du texte, donc nous non plus.
    """
    if not chemin:
        return True
    try:
        absolu = os.path.abspath(chemin)
    except (OSError, ValueError):  # pragma: no cover — chemin illisible
        return False
    reel = _ce_que_le_noyau_atteint(chemin)
    vus = (absolu,) if reel == absolu else (absolu, reel)
    # AVANT TOUT LE RESTE, ET CE N'EST PAS UN DÉTAIL D'ORDRE. Ce refus-ci passe
    # devant `LECTURES_DECLAREES` : c'est le seul du fichier qu'une déclaration
    # ne peut pas lever. Une déclaration existe pour les fichiers qu'un test a
    # de bonnes raisons de lire ; il n'y a aucune bonne raison, dans une suite
    # hermétique, de lire le `/proc/<pid>/` d'un processus qui n'est pas soi. Le
    # jour où il y en aurait une, elle vaut un changement de code discuté, pas
    # une ligne ajoutée dans un dictionnaire — c'est exactement par une ligne
    # ajoutée sans discussion que ce trou-ci avait été ouvert.
    for vu in vus:
        if _proc_d_un_autre(vu):
            return False
    return all(_sous_le_perimetre(vu) for vu in vus)


class RefusDeFichier(RefusHermetique, PermissionError):
    """Un refus de toucher un fichier de l'hôte — ET un ``PermissionError``.

    POURQUOI DEUX ANCÊTRES, ET CE QUE ÇA COÛTE. Le refus doit dire la vérité au
    code testé dans le langage que ce code parle déjà. `control_center/
    security.py` écrit son journal d'accès dans `/var/log/arac/<cerveau>/` « si
    c'est possible », et retombe sur `/tmp` sinon — sa fonction
    `_ensure_log_file` attrape `OSError` et rend `False`. Un refus qui serait
    seulement un `RuntimeError` traverserait ce `except` et ferait ROUGIR une
    suite dont le code n'a rien de cassé : « le journal n'est pas accessible »
    n'est pas « le code est faux ».

    C'est le choix déjà fait pour `connect_ex`, et pour la même raison : « a
    pour contrat de rendre un code d'erreur, pas de lever ». Le code testé
    retombe sur son chemin d'indisponibilité, l'hôte n'est pas touché, et le
    refus n'est pas muet pour autant — il est journalisé dans
    `TENTATIVES_LECTURE` et imprimé en fin de session.

    CE QUE ÇA COÛTE, DIT PLUTÔT QUE TU : un test qui avale `OSError` avalera ce
    refus. La propriété de sécurité tient (rien n'est touché) ; la visibilité
    passe alors par la fin de session, pas par un rouge.
    """


def _refus_de_lecture(chemin: str) -> RefusHermetique:
    try:
        absolu = os.path.abspath(chemin)
    except (OSError, ValueError):  # pragma: no cover — chemin illisible
        absolu = chemin
    reel = _ce_que_le_noyau_atteint(chemin)
    if reel != absolu and not _sous_le_perimetre(reel):
        # LE LIEN MAGIQUE, NOMMÉ PAR CE QU'IL ATTEINT. Sans cette phrase, le
        # refus dirait « /proc/self/root/etc/arac/… n'est pas dans le
        # périmètre » alors que `/proc` l'est : le lecteur croirait à un
        # caprice et irait chercher une autre porte. On lui montre donc la
        # réécriture du noyau, qui est toute l'explication.
        return RefusDeFichier(
            f"REFUS hermétique (lecture) : « {chemin} ».\n"
            "\n"
            f"CE CHEMIN N'EST PAS CELUI QUI S'OUVRE. Le noyau le réécrit en "
            f"« {reel} », qui est hors du périmètre de la suite.\n"
            "\n"
            "`/proc/<pid>/root`, `/proc/<pid>/cwd` et `/proc/<pid>/fd/<n>` ne "
            "sont pas des fichiers : ce sont des LIENS MAGIQUES. `/proc/self/"
            "root/etc/arac/<un voisin>/arac.env` s'écrit comme un chemin de "
            "`/proc` — `abspath` ne suit pas les liens — et ouvre le coffre de "
            "ce voisin : son JETON PORTEUR et son DSN avec mot de passe. La "
            "même écriture ouvre `/etc/shadow`, écrase une sauvegarde, efface "
            "un dump. Et `self` n'est le `/proc` d'un autre processus pour "
            "personne : compter les pids ne pouvait pas voir cela.\n"
            "\n"
            "Le rideau juge donc DEUX chemins — celui que vous écrivez et "
            "celui que le noyau atteint —, et il faut que les deux soient dans "
            "le périmètre. Il n'y a aucun préfixe à apprendre : donnez le "
            "chemin direct, il sera jugé exactement pareil.\n"
            "\n"
            "Trois issues, dans l'ordre de préférence :\n"
            "  1. le fichier n'a pas besoin d'être RÉEL : écrivez-le sous "
            "`tmp_path` et lisez-le là ;\n"
            "  2. le fichier vient du dépôt : donnez son chemin depuis la "
            "racine du dépôt, il est lu sans un mot ;\n"
            "  3. il faut vraiment lire ce fichier de la machine : déclarez-le "
            "dans `LECTURES_DECLAREES` — sous son chemin RÉEL, pas sous un "
            "détour."
        )
    if _proc_d_un_autre(absolu):
        return RefusDeFichier(
            f"REFUS hermétique (lecture) : « {chemin} ».\n"
            "\n"
            "C'est le `/proc/<pid>/` d'un AUTRE processus, et ce n'est pas un "
            "pseudo-fichier anodin : sur une machine qui porte des cerveaux, "
            "`/proc/<pid>/environ` d'un service arac est la copie VERBATIM de "
            "son coffre — l'unité porte `EnvironmentFile=/etc/arac/<lui>/"
            "arac.env`, donc le JETON PORTEUR et le DSN avec son mot de passe, "
            "en clair, sans avoir à ouvrir `/etc/arac`. `cmdline` porte le DSN "
            "de tout `psql` en cours ; `fd/`, `root/` et `cwd/` rouvrent le "
            "disque entier par un lien.\n"
            "\n"
            "Ce refus-ci ne se lève pas par `LECTURES_DECLAREES` : une suite "
            "hermétique n'a aucune raison de lire le `/proc` d'un tiers.\n"
            "\n"
            "Ce qui reste ouvert, et qui suffit : `/proc/self/…`, "
            "`/proc/thread-self/…`, votre propre pid, et tous les "
            "pseudo-fichiers globaux (`/proc/loadavg`, `/proc/meminfo`, "
            "`/proc/net/tcp`). Un code qui inspecte les processus de la machine "
            "se teste sur une arborescence FACTICE — c'est ce que fait déjà "
            "`tests/test_control_center_collectors.py`."
        )
    return RefusDeFichier(
        f"REFUS hermétique (lecture) : « {chemin} ».\n"
        "\n"
        "La suite lit le DÉPÔT, le répertoire jetable et son installation "
        "Python. Elle ne lit pas l'hôte — et ce n'est pas une pudeur : sur une "
        "machine qui porte des cerveaux, `/etc/arac/<un autre>/arac.env` "
        "contient le JETON de ce cerveau. Qui le lit n'a plus besoin de `psql` "
        "ni de `sudo` : un GET suffit. Fermer la lecture rend les évasions que "
        "les autres gardes ne ferment pas SANS EFFET.\n"
        "\n"
        "Trois issues, dans l'ordre de préférence :\n"
        "  1. le fichier n'a pas besoin d'être RÉEL : écrivez-le sous "
        "`tmp_path` et lisez-le là ;\n"
        "  2. le fichier vient du dépôt : donnez son chemin depuis la racine "
        "du dépôt, il est lu sans un mot ;\n"
        "  3. il faut vraiment lire ce fichier de la machine : déclarez-le "
        "dans `LECTURES_DECLAREES`, avec ce qu'il apporte et pourquoi rien "
        "d'autre ne le ferait. Une lecture déclarée est une lecture qu'on "
        "relit ; une lecture tue est une lecture qu'on découvre après."
    )


def _installer_le_garde_de_lecture() -> None:
    """Enveloppe les portes de lecture ÉCRITES EN PYTHON.

    Ce que cela ne couvre pas, et qui est dit plutôt que tu : la libc appelée
    directement (`ctypes`), et tout ce qu'une extension C ouvre pour son propre
    compte. Un garde en espace utilisateur ne se substitue pas à un `uid`.
    """
    global _RACINES_DE_LECTURE
    import builtins
    import io

    _RACINES_DE_LECTURE = _racines_de_lecture()

    _open_reel = builtins.open
    _os_open_reel = os.open
    _scandir_reel = os.scandir
    _listdir_reel = os.listdir

    def _garde_open(fichier, *a, **k):
        try:
            chemin = os.fsdecode(fichier) if isinstance(
                fichier, (str, bytes, os.PathLike)) else ""
        except (TypeError, ValueError):
            chemin = ""
        if chemin and not _lecture_toleree(chemin):
            _journalise(TENTATIVES_LECTURE, chemin)
            raise _refus_de_lecture(chemin)
        return _open_reel(fichier, *a, **k)

    def _garde_os_open(chemin, *a, **k):
        try:
            vu = os.fsdecode(chemin)
        except (TypeError, ValueError):  # pragma: no cover
            vu = ""
        if vu and not _lecture_toleree(vu):
            _journalise(TENTATIVES_LECTURE, vu)
            raise _refus_de_lecture(vu)
        return _os_open_reel(chemin, *a, **k)

    def _garde_scandir(chemin="."):
        try:
            vu = os.fsdecode(chemin)
        except (TypeError, ValueError):  # pragma: no cover
            vu = ""
        if vu and not _lecture_toleree(vu):
            _journalise(TENTATIVES_LECTURE, vu + "/ (liste)")
            raise _refus_de_lecture(vu)
        return _scandir_reel(chemin)

    def _garde_listdir(chemin="."):
        try:
            vu = os.fsdecode(chemin)
        except (TypeError, ValueError):  # pragma: no cover
            vu = ""
        if vu and not _lecture_toleree(vu):
            _journalise(TENTATIVES_LECTURE, vu + "/ (liste)")
            raise _refus_de_lecture(vu)
        return _listdir_reel(chemin)

    builtins.open = _garde_open
    io.open = _garde_open
    os.open = _garde_os_open
    os.scandir = _garde_scandir
    os.listdir = _garde_listdir

    # ÉCRIRE EST PIRE QUE LIRE, ET C'ÉTAIT LA MOITIÉ OUBLIÉE. Mesuré sur un
    # clone neuf : `make test` créait `/var/log/arac/<cerveau de test>/` et y
    # écrivait 292 kio de journal d'accès — dans la racine où vivent les
    # journaux des cerveaux RÉELS de la machine, à côté d'eux, sous la même
    # convention de nommage. `open` ne suffisait pas : `Path.mkdir` passe par
    # `os.mkdir`, et le dossier était créé avant que le fichier ne le soit.
    for nom_primitive in ("mkdir", "rmdir", "remove", "unlink", "chmod",
                          "truncate", "mkfifo"):
        reel = getattr(os, nom_primitive, None)
        if not callable(reel):
            continue

        def _garde_ecriture(chemin, *a, _reel=reel, **k):
            try:
                vu = os.fsdecode(chemin)
            except (TypeError, ValueError):  # pragma: no cover — fd, pas chemin
                vu = ""
            if vu and not _lecture_toleree(vu):
                _journalise(TENTATIVES_LECTURE, vu + " (écriture)")
                raise _refus_de_lecture(vu)
            return _reel(chemin, *a, **k)

        _garde_ecriture.__name__ = nom_primitive
        setattr(os, nom_primitive, _garde_ecriture)

    for nom_primitive in ("rename", "replace", "symlink", "link"):
        reel = getattr(os, nom_primitive, None)
        if not callable(reel):
            continue

        def _garde_deux_chemins(src, dst, *a, _reel=reel, **k):
            for brut in (src, dst):
                try:
                    vu = os.fsdecode(brut)
                except (TypeError, ValueError):  # pragma: no cover
                    continue
                if vu and not _lecture_toleree(vu):
                    _journalise(TENTATIVES_LECTURE, vu + " (écriture)")
                    raise _refus_de_lecture(vu)
            return _reel(src, dst, *a, **k)

        _garde_deux_chemins.__name__ = nom_primitive
        setattr(os, nom_primitive, _garde_deux_chemins)


# ============================================================================
# 3. Le contrôle d'entrée de session
# ============================================================================


def controle_des_dsn_de_session(variables=("DATABASE_URL_APP", "DATABASE_URL_ADMIN",
                                           "DATABASE_URL_APP_TEST",
                                           "DATABASE_URL_ADMIN_TEST",
                                           "DATABASE_URL_READONLY")) -> list[str]:
    """Refuse la session AVANT le moindre test si un DSN vise une base non marquée.

    Retourne la liste des refus (vide = rien à signaler). On se contente d'un
    constat quand la base est INJOIGNABLE : une base de test éteinte doit
    donner des tests IGNORÉS, pas une session avortée — c'est la promesse
    « un test rouge veut dire que le code est cassé ». Le garde de connexion,
    lui, reste souverain : rien ne s'ouvre sans la marque.
    """
    import psycopg

    refus: list[str] = []
    for var in variables:
        dsn = os.environ.get(var)
        if not dsn:
            continue
        try:
            conn = psycopg.connect(dsn, connect_timeout=3)
        except RefusHermetique as exc:
            refus.append(f"{var} → {exc}")
        except Exception:
            # Injoignable, identifiants absents, pilote manquant : on ne peut
            # rien affirmer, donc on n'affirme rien ici. Le garde de connexion
            # refusera au premier usage réel.
            continue
        else:
            conn.close()
    return refus
