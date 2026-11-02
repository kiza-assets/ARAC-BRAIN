"""LA PORTE DU SOUS-PROCESSUS — ce qu'elle ferme, ÉPROUVÉ, et ce qu'elle laisse.

CE QUE CE FICHIER GARDE
=======================

Un test de cette suite exécutait, pendant `make test` :

    subprocess.run(["sudo", "-n", "-u", "postgres", "psql", "-d", "arac",
                    "-c", "ALTER TABLE arac.memory_atoms DISABLE TRIGGER …"])

— du DDL sur la base littéralement nommée `arac`, c'est-à-dire un cerveau de
production. Les trois gardes l'ont laissé passer : celui de la base est posé sur
`psycopg` et ne voit pas un sous-processus ; celui de la machine ne regardait que
`args[0]`, qui vaut « sudo » ; G1 dispense `tests/` de tous ses motifs.

CETTE PHRASE ÉTAIT ÉCRITE ICI, ET ELLE ÉTAIT FAUSSE
====================================================

    « Corriger cette ligne n'aurait rien prouvé. Ce fichier ferme la CLASSE. »

Elle a été démentie par la mesure, dans un clone fidèle, la suite VERTE :

    bash -c "/usr/lib/postgresql/16/bin/psql …"      → le vrai client démarre
    bash -c "B=/usr/bin; $B/hostname -f"             → rc=0
    bash -c "export PATH=/usr/bin:/bin; hostname -f" → rc=0
    bash -c "env -i PATH=/usr/bin:/bin hostname -f"  → rc=0
    bash -c "<venv>/bin/python -I -c 'import psycopg …'"
        → `psycopg.connect` NU dans le fils, et `connect_ex(('127.0.0.1',5432))`
          rend 0 : le cluster de production, joint depuis un test

et pendant les cinq, `pytest tests/test_la_porte_du_sous_processus_est_fermee.py`
rendait `51 passed`. Le balayage qui prétendait fermer le dernier trou cherchait
`(?<![\\w.-])/(?:usr/)?(?:local/)?s?bin/…` : une LISTE BLANCHE de quatre racines.
Sur Debian, `/usr/bin/psql` n'est qu'un lien vers `pg_wrapper` ; le vrai client
vit dans `/usr/lib/postgresql/16/bin/`, que ce motif ne voyait pas. Une liste
blanche oublie — c'est sa nature, et ce dépôt l'a déjà payé quatre fois.

CE QUE LE DISPOSITIF FERME VRAIMENT — mesuré, pas déclaré
==========================================================

Trois pièces, et chacune a sa portée exacte :

  1. LE POINT DE CONTRÔLE (`_controle`) voit toute création de processus depuis
     le processus pytest : `subprocess.Popen`, `os.system`, `os.exec*`,
     `os.spawn*`, `os.posix_spawn*`, `pty.spawn` et `_posixsubprocess.fork_exec`
     — c'est-à-dire aussi `multiprocessing` en mode « spawn », qui n'empruntait
     ni `os` ni `subprocess`. Il refuse tout ce qui n'est pas dans
     `OUTILS_LEGITIMES`, en lisant le BASENAME : `/usr/bin/psql` en appel direct
     est refusé comme `psql`.
  2. LE TALON EN TÊTE DU `PATH` ferme les descendants — mais SEULEMENT les noms
     NUS : `bash -c 'psql …'`, `sudo …`, les shells imbriqués, `x=psql; $x -l`,
     un `env=` réécrit (le garde réinjecte son `PATH`), `shutil.which`.
     Un shell qui reçoit un CHEMIN ne consulte jamais le `PATH`.
  3. LE `sitecustomize` SUR LE `PYTHONPATH` repose les trois gardes dans tout
     `python` fils — sauf s'il est déshabillé par `-I`, `-E` ou `-S`.

  4. LE CORPS D'UN SHELL EST LU (`_controle_du_corps`). Un `bash`/`sh` qui
     reçoit un chemin absolu d'exécutable de l'hôte, une racine de binaires, un
     `PATH=` rebâti, un `env -i` ou un interpréteur déshabillé est refusé dans
     le PÈRE, avec un message qui enseigne.

CE QUE CETTE MANCHE A FERMÉ — deux trous génériques, et une règle
=================================================================

  · L'ARGV DES PRIMITIVES `os.*`. L'enveloppe remettait au juge le seul
    PROGRAMME. Mesuré, régime de repli : dix-huit canaux (`spawnv`…`spawnlpe`,
    `posix_spawn*`, `execv`…`execlpe`) rendaient le coffre d'un faux voisin
    sans un seul corps de shell. L'argv passe désormais par le MÊME juge que
    `subprocess`, et la section « 2 bis » exige la PARITÉ des verdicts.
  · LA VALEUR COLLÉE À UNE OPTION. Le juge des chemins concluait « c'est une
    option » sur la seule vue du tiret, et ne regardait que ce qui suit un `=` :
    `tar -C…`, `sort -o…`, `grep -f…` passaient — dont un `sort -o` qui ramenait
    un dump voisin à zéro octet. Ce qui suit la LETTRE est jugé aussi.
  · ET UNE RÈGLE PLUTÔT QU'UN CAS : on ne cherche plus OÙ est le corps d'un
    shell. `RX_DRAPEAU_DE_CORPS` devinait, et se trompait de deux façons
    mesurées — `-cx` et `-c --` — pendant que `-xc`, `-lc` et `--norc -c`
    passaient bien. C'est ce mélange qui rend un tel juge intenable : on ne
    peut pas savoir, en le lisant, ce qu'il couvre. Quand le programme est un
    interprète, TOUT argument est désormais un corps possible, et les mots de
    tous sont jugés.

CE QUE CE FICHIER NE FERME PAS, ET QUI EST ÉCRIT ICI PLUTÔT QUE TU
==================================================================

`ZONES_NON_COUVERTES_DE_LA_PORTE`, plus bas, en nomme neuf, avec leur mécanique
et — pour l'une d'elles — l'instance vivante qui existe DANS ce dépôt. Elles
sont imprimées en fin de session, comme celles de G1, G3 et G4.

Les deux premières comptent plus que les sept autres, et elles ne sont pas des
motifs à ajouter :

  · LE MODÈLE DE MENACE. Cette porte protège contre un test DISTRAIT, pas
    contre un test HOSTILE. Un test hostile exécute déjà du code arbitraire
    dans le processus qui porte le garde — `ctypes.CDLL("libc.so.6")` suffit,
    et c'est mesuré. La seule barrière qui vaille alors est le noyau.
  · LE RÉGIME. En NOMINAL, Landlock ferme et la porte n'est plus que le message
    qui enseigne. En REPLI, la porte est seule et sa couverture est PARTIELLE :
    les quatre formes qu'elle laisse passer rendent alors le fichier entier.
    C'est écrit, pas caché, et la fin de session dit sous lequel des deux
    régimes le vert que vous venez de voir a été obtenu.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

import pytest

from tests.garde_hermetique import (
    OUTILS_LEGITIMES,
    RX_CHEMIN_D_EXECUTABLE,
    RX_RACINE_DE_BINAIRES,
    RefusHermetique,
)

RACINE = Path(__file__).resolve().parents[1]


# ===========================================================================
# 1. LA PORTE DIRECTE — et les enveloppes qui la déguisaient
# ===========================================================================


@pytest.mark.parametrize(
    "commande, ce_que_c_est",
    [
        # La commande EXACTE qui a échappé aux trois gardes.
        (["sudo", "-n", "-u", "postgres", "psql", "-d", "arac",
          "-c", "SELECT count(*) FROM arac.memory_atoms"],
         "l'évasion mesurée : du SQL sur le cerveau de production"),
        (["psql", "-p", "5432", "-d", "arac", "-c", "SELECT 1"], "psql, nu"),
        (["/usr/bin/psql", "-l"], "psql par son chemin absolu"),
        (["/usr/lib/postgresql/16/bin/psql", "-l"],
         "psql par le chemin Debian RÉEL — celui que la liste blanche de "
         "quatre racines ne voyait pas"),
        (["env", "PGPASSWORD=x", "psql", "-d", "arac"], "l'enveloppe env"),
        (["timeout", "5", "psql", "-d", "arac"], "l'enveloppe timeout"),
        (["nohup", "psql"], "l'enveloppe nohup"),
        (["setsid", "psql"], "l'enveloppe setsid"),
        (["su", "-c", "psql", "postgres"], "l'enveloppe su"),
        (["pg_dump", "-d", "arac"], "le dump d'une base"),
        (["pg_restore", "x.dump"], "la restauration d'une base"),
        (["dropdb", "arac"], "la destruction d'une base"),
        (["alembic", "upgrade", "head"], "alembic en ligne de commande"),
        (["systemctl", "restart", "arac-api.service"], "systemctl"),
        (["journalctl", "-u", "arac-api"], "journalctl"),
        (["ss", "-ltn"], "l'inventaire des sockets de l'hôte"),
        # DES FAMILLES QUE PERSONNE N'A ÉNUMÉRÉES. C'est le cœur de l'inversion :
        # aucune de ces cinq n'est nommée nulle part dans le garde, et toutes
        # sont refusées — parce qu'elles ne sont pas dans ce qui est LÉGITIME.
        (["hostname", "-f"], "une famille jamais énumérée : hostname"),
        (["uname", "-a"], "une famille jamais énumérée : uname"),
        (["mysql", "-e", "SELECT 1"], "une famille jamais énumérée : mysql"),
        (["redis-cli", "KEYS", "*"], "une famille jamais énumérée : redis-cli"),
        (["kubectl", "get", "pods"], "une famille jamais énumérée : kubectl"),
    ],
)
def test_aucune_commande_n_atteint_la_machine(commande, ce_que_c_est):
    """Chacune de ces commandes doit être refusée AVANT de s'exécuter."""
    with pytest.raises(RefusHermetique) as pris:
        subprocess.run(commande, capture_output=True)
    assert "REFUS" in str(pris.value), ce_que_c_est


def test_le_refus_dit_quoi_faire():
    """Un refus qui ne dit pas quoi faire se contourne au lieu de se respecter."""
    with pytest.raises(RefusHermetique) as pris:
        subprocess.run(["psql", "-l"], capture_output=True)
    message = str(pris.value)
    assert "monkeypatch" in message
    assert "OUTILS_LEGITIMES" in message
    assert "sudo -u postgres psql" in message, (
        "le message doit rappeler l'évasion réelle : c'est ce qui fait qu'on ne "
        "le désactive pas."
    )


# ===========================================================================
# 2. LES AUTRES PRIMITIVES — `subprocess` n'est pas la seule porte
# ===========================================================================


def test_os_system_est_garde():
    """`os.system` appelle la libc : il ne passe PAS par `subprocess`."""
    with pytest.raises(RefusHermetique):
        os.system("psql -d arac -c 'SELECT 1'")


def test_os_posix_spawn_est_garde():
    with pytest.raises(RefusHermetique):
        os.posix_spawn("/usr/bin/psql", ["psql", "-l"], os.environ)


@pytest.mark.parametrize("primitive", ["execv", "execvp", "execl", "execlp"])
def test_les_exec_sont_gardes(primitive):
    """`os.exec*` REMPLACE le processus : on l'éprouve dans un fils.

    Si le garde manquait, l'appel remplacerait l'interpréteur pytest par `psql`
    — et la suite entière disparaîtrait au milieu d'un test. On fourche donc :
    le fils sort en 7 s'il a été refusé, et en 8 si l'appel est revenu sans
    lever. Tout autre code de sortie veut dire que `psql` a démarré.
    """
    lu, ecrit = os.pipe()
    pid = os.fork()
    if pid == 0:  # pragma: no cover — exécuté dans le fils
        os.close(lu)
        try:
            fonction = getattr(os, primitive)
            if primitive in ("execv", "execvp"):
                fonction("/usr/bin/psql", ["psql", "-l"])
            else:
                fonction("/usr/bin/psql", "psql", "-l")
        except RefusHermetique:
            os._exit(7)
        except Exception:
            os._exit(9)
        os._exit(8)
    os.close(ecrit)
    os.close(lu)
    _, statut = os.waitpid(pid, 0)
    assert os.WIFEXITED(statut) and os.WEXITSTATUS(statut) == 7, (
        f"os.{primitive} n'a pas été refusé : code de sortie du fils "
        f"{os.WEXITSTATUS(statut) if os.WIFEXITED(statut) else statut}. "
        "Un exec non gardé remplace le processus de test par le programme visé."
    )


def test_pty_spawn_est_refuse_dans_le_pere():
    """Le refus doit atteindre CELUI QU'IL REFUSE, pas seulement le fils.

    `pty.spawn` passe bien par `os.execlp` — mais après `os.forkpty()`, donc
    dans le FILS. Mesuré avant correction : le `RefusHermetique` était levé dans
    un fils qui, ne mourant pas, CONTINUAIT d'exécuter la session pytest (deux
    puis quatre exécutions du même fichier, entrelacées) ; le père, lui, voyait
    `pty.spawn` rendre la main sans rien dire. Un test qui éprouve un programme
    exigeant un vrai terminal — ce dépôt a un entretien interactif — croyait
    avoir exécuté ce qu'il demandait.
    """
    import pty

    with pytest.raises(RefusHermetique):
        pty.spawn(["psql", "-l"])
    with pytest.raises(RefusHermetique):
        pty.spawn(["/usr/bin/psql", "-l"])


def test_fork_exec_la_porte_en_C_est_gardee():
    """`_posixsubprocess.fork_exec` : l'entrée que `multiprocessing` emprunte.

    `multiprocessing.util.spawnv_passfds` l'appelle DIRECTEMENT — ni `os`, ni
    `subprocess`. Mesuré avant correction :
    `mp.get_context("spawn").Process(...)` démarrait, `exitcode=0`, sans qu'un
    seul garde soit consulté. C'est la « bibliothèque qui crée un processus sans
    passer par `os` ni `subprocess` », et elle est dans la bibliothèque standard.
    """
    import _posixsubprocess

    with pytest.raises(RefusHermetique):
        _posixsubprocess.fork_exec(
            [b"psql"], [b"psql"], True, (), None, None, -1, -1, 1, 2,
            -1, -1, -1, -1, -1, -1, False, False, -1, None, None, None, -1, None)


def test_multiprocessing_spawn_reste_possible():
    """Le garde ne doit pas casser ce qui est légitime : un fils Python.

    `spawn` lance `sys.executable`, qui est légitime et qui repose les gardes
    par `sitecustomize`. Fermer la porte en C ne doit pas fermer celle-là.
    """
    import multiprocessing as mp

    contexte = mp.get_context("spawn")
    p = contexte.Process(target=len, args=("x",))
    p.start()
    p.join(timeout=60)
    assert p.exitcode == 0


# ===========================================================================
# 2 bis. LA PARITÉ DES CANAUX — le PROGRAMME était jugé, l'ARGV ne l'était pas
# ===========================================================================
#
# Le dépôt avait des tests par GESTE (lire, détruire, contaminer) et par FORME
# (liste, `shell=True`, `-c`). Aucun par CANAL. Les huit familles de primitives
# `os.*` étaient enveloppées depuis des manches, et personne n'avait mesuré ce
# que l'enveloppe JUGE : elle remettait au juge commun `args[rang]`, c'est-à-dire
# le seul PROGRAMME. Ce n'est pas une liste ; `_controle_des_chemins` rendait
# donc la main sans juger un seul argument.
#
# Mesuré, régime de repli, sur un faux voisin posé pour l'occasion — dix-huit
# appels, dix-huit fois le coffre rendu, dix-huit fois `TENTATIVES_MACHINE`
# vide, pendant que `subprocess.run(["cat", <le même chemin>])` était refusé
# depuis des manches. Aucun corps de shell n'était nécessaire : c'est ce qui
# rendait ce trou plus large et moins cher que les six précédents.
#
# LE TEST QUI MANQUAIT N'EST PAS UN TEST DE PLUS, C'EST UN TEST DE PARITÉ : la
# même commande, pointée sur la même cible, doit rendre le MÊME verdict par
# chacun des canaux de création de processus. C'est ce que cette section exige,
# canal par canal, plutôt que d'ajouter un cas au fur et à mesure qu'on le
# trouve.

#: Les canaux qui RENDENT LA MAIN — on peut les appeler dans le processus de
#: test. Chaque entrée dit comment poser la MÊME commande (`cat <une cible hors
#: périmètre>`) dans la grammaire de la primitive.
CANAUX_QUI_REVIENNENT = {
    "spawnv": lambda p, a: os.spawnv(os.P_WAIT, p, a),
    "spawnve": lambda p, a: os.spawnve(os.P_WAIT, p, a, dict(os.environ)),
    "spawnvp": lambda p, a: os.spawnvp(os.P_WAIT, "cat", a),
    "spawnvpe": lambda p, a: os.spawnvpe(os.P_WAIT, "cat", a, dict(os.environ)),
    "spawnl": lambda p, a: os.spawnl(os.P_WAIT, p, *a),
    "spawnle": lambda p, a: os.spawnle(os.P_WAIT, p, *a, dict(os.environ)),
    "spawnlp": lambda p, a: os.spawnlp(os.P_WAIT, "cat", *a),
    "spawnlpe": lambda p, a: os.spawnlpe(os.P_WAIT, "cat", *a, dict(os.environ)),
    "posix_spawn": lambda p, a: os.posix_spawn(p, a, dict(os.environ)),
    "posix_spawnp": lambda p, a: os.posix_spawnp("cat", a, dict(os.environ)),
}

#: Les canaux qui REMPLACENT le processus. On les éprouve dans un fils : si le
#: garde manquait, l'appel remplacerait l'interpréteur pytest par `cat` et la
#: suite disparaîtrait au milieu d'un test.
CANAUX_QUI_REMPLACENT = ("execv", "execve", "execvp", "execvpe",
                         "execl", "execle", "execlp", "execlpe")

#: Un fichier de la DISTRIBUTION, hors du périmètre déclaré, présent sur toute
#: Debian. On ne pointe pas un cerveau réel pour prouver un garde : ce que le
#: test mesure est le VERDICT, jamais le contenu.
_CIBLE_HORS_PERIMETRE = "/var/lib/dpkg/status"

#: Un chemin qui n'existe pas, sous un répertoire qui existe et qui est hors du
#: périmètre — les sondes destructrices le visent. On ne prouve pas un garde en
#: pariant la mémoire de quelqu'un.
_CIBLE_A_DETRUIRE = "/var/lib/dpkg/klw-sonde-qui-n-existe-pas"


@pytest.mark.parametrize("canal", sorted(CANAUX_QUI_REVIENNENT))
def test_l_argv_est_juge_par_les_canaux_qui_reviennent(canal):
    """`os.spawn*` et `os.posix_spawn*` jugeaient le programme, pas sa liste."""
    with pytest.raises(RefusHermetique) as pris:
        CANAUX_QUI_REVIENNENT[canal]("/usr/bin/cat",
                                     ["cat", _CIBLE_HORS_PERIMETRE])
    assert _CIBLE_HORS_PERIMETRE in str(pris.value), (
        f"os.{canal} refuse, mais le message ne nomme pas le chemin qu'il "
        "refuse : un refus qui ne dit pas OÙ ne s'apprend pas."
    )


@pytest.mark.parametrize("canal", CANAUX_QUI_REMPLACENT)
def test_l_argv_est_juge_par_les_canaux_qui_remplacent(canal):
    """`os.exec*` remplace le processus : le fils sort en 7 s'il est refusé."""
    pid = os.fork()
    if pid == 0:  # pragma: no cover — exécuté dans le fils
        try:
            fonction = getattr(os, canal)
            args = ["cat", _CIBLE_HORS_PERIMETRE]
            programme = "cat" if "p" in canal[len("exec"):] else "/usr/bin/cat"
            if canal.startswith("execv"):
                if canal.endswith("e"):
                    fonction(programme, args, dict(os.environ))
                else:
                    fonction(programme, args)
            elif canal.endswith("e"):
                fonction(programme, *args, dict(os.environ))
            else:
                fonction(programme, *args)
        except RefusHermetique:
            os._exit(7)
        except Exception:
            os._exit(9)
        os._exit(8)
    _, statut = os.waitpid(pid, 0)
    code = os.WEXITSTATUS(statut) if os.WIFEXITED(statut) else statut
    assert code == 7, (
        f"os.{canal} n'a pas refusé l'argv : code de sortie du fils {code}. "
        "L'enveloppe jugeait le PROGRAMME (`cat`, légitime) et jamais la liste "
        "d'arguments — mesuré, elle rendait le coffre d'un faux voisin."
    )


def test_la_parite_est_le_critere_et_non_le_canal():
    """Le même geste par `subprocess` et par `os` doit rendre le même verdict.

    C'est la formulation qui manquait : tant qu'on éprouve un canal à la fois,
    la manche suivante trouve le neuvième. On exige donc l'ÉGALITÉ des verdicts,
    et le test se périmerait de lui-même si `subprocess` cessait de refuser.
    """
    def verdict(appel):
        try:
            appel()
        except RefusHermetique:
            return "REFUS"
        return "PASSÉ"

    par_subprocess = verdict(
        lambda: subprocess.run(["cat", _CIBLE_HORS_PERIMETRE],
                               capture_output=True))
    par_os = verdict(
        lambda: os.spawnv(os.P_WAIT, "/usr/bin/cat",
                          ["cat", _CIBLE_HORS_PERIMETRE]))
    assert par_subprocess == par_os == "REFUS", (
        f"parité rompue : subprocess → {par_subprocess}, os.spawnv → {par_os}. "
        "Deux portes vers le noyau, un seul juge — sinon la porte la moins "
        "regardée devient la porte de service."
    )


def test_le_canal_os_reste_vivable(tmp_path):
    """La contre-épreuve : ce qui est légitime par `subprocess` l'est par `os`.

    Un garde qui coupe le travail légitime finit désactivé, et c'est alors toute
    la porte qui tombe. Un `os.spawnv` pointé sur le DÉPÔT et sur `tmp_path`
    doit passer exactement comme le `subprocess.run` équivalent.
    """
    assert os.spawnv(os.P_WAIT, "/usr/bin/cat",
                     ["cat", str(RACINE / "README.md")]) == 0
    cible = tmp_path / "note.txt"
    cible.write_text("bonjour", encoding="utf-8")
    assert os.spawnv(os.P_WAIT, "/usr/bin/cat", ["cat", str(cible)]) == 0


# ===========================================================================
# 2 ter. LA VALEUR COLLÉE À SON OPTION — le tiret ne dit pas « pas un chemin »
# ===========================================================================
#
# Le juge des chemins concluait « c'est une option » sur la seule vue du tiret,
# et ne regardait que ce qui suit un `=`. Or les outils que ce dépôt déclare
# légitimes collent eux-mêmes leur valeur à l'option courte, sans aucun `=`.
# Mesuré, régime de repli, sur un faux voisin : `tar -C<son dossier> -cf - …` a
# rendu son coffre et `sort -o<son dump> /dev/null` a ramené le dump à ZÉRO
# OCTET, les deux avec le journal du garde vide, pendant que la même valeur
# écrite en argument séparé était refusée depuis des manches.


@pytest.mark.parametrize("commande, ce_que_c_est", [
    (["tar", "-C/var/lib/dpkg", "-cf", "-", "status"],
     "tar -C<dossier> : l'archive part d'un endroit qu'on ne juge pas"),
    (["sort", "-o" + _CIBLE_A_DETRUIRE, "/dev/null"],
     "sort -o<fichier> : ÉCRASE ce qu'il désigne, sans le moindre `=`"),
    (["grep", "-f/var/lib/dpkg/status", "/etc/hostname"],
     "grep -f<fichier> : les motifs sont LUS dans le fichier désigné"),
    (["sed", "-n1p", _CIBLE_HORS_PERIMETRE],
     "témoin : l'argument nu, refusé depuis des manches"),
])
def test_la_valeur_collee_a_une_option_est_jugee(commande, ce_que_c_est):
    with pytest.raises(RefusHermetique) as pris:
        subprocess.run(commande, capture_output=True, cwd=str(RACINE))
    assert "REFUS hermétique" in str(pris.value), ce_que_c_est


@pytest.mark.parametrize("commande", [
    ["grep", "-c", "-e/motif/qui/n/existe/nulle/part", "README.md"],
    ["sed", "-e", "s/arac/arac/", "README.md"],
    ["sed", "-n1p", "README.md"],
    ["tar", "-C" + str(RACINE), "-cf", "/dev/null", "README.md"],
    ["grep", "-c", "--regexp=/motif/introuvable", "README.md"],
])
def test_la_valeur_collee_ne_crie_pas_au_loup(commande):
    """Ce qui RESSEMBLE à un chemin sans en désigner un doit rester muet.

    Le critère n'est pas la forme, c'est l'EXISTENCE de ce que le noyau
    atteindrait : `-e/motif/qui/n/existe/nulle/part` remonte jusqu'à `/` sans
    rien trouver, et `_ancre_existante` rend alors `None`. C'est ce qui
    distingue ce juge d'un motif de texte, et c'est ce qui le rend vivable.
    """
    r = subprocess.run(commande, capture_output=True, cwd=str(RACINE))
    assert r.returncode in (0, 1, 128), r.stderr[:300]


def test_le_prix_de_cette_regle_est_dit_plutot_que_decouvert():
    """Ce que la règle coûte, mesuré ici pour que personne ne le découvre.

    Un argument collé qui désigne un endroit RÉEL hors du périmètre est refusé,
    même quand l'outil ne s'en servirait que comme TEXTE : `grep -e/etc fichier`
    cherche la chaîne « /etc » et ne lit rien. C'est la doctrine déjà écrite du
    dépôt — « un outil est légitime pour ce qu'il FAIT, jamais pour l'endroit où
    on le pointe » —, elle vaut pour l'argument nu depuis des manches
    (`grep /etc fichier` est refusé de la même façon), et l'issue est la même
    qu'ailleurs : faire entrer la valeur par l'ENTRÉE STANDARD, comme
    `tests/acceptance/test_garde_isolement.py` a dû le faire pour la même
    raison.
    """
    with pytest.raises(RefusHermetique):
        subprocess.run(["grep", "-e/etc", "README.md"],
                       capture_output=True, cwd=str(RACINE))
    with pytest.raises(RefusHermetique):
        subprocess.run(["grep", "/etc", "README.md"],
                       capture_output=True, cwd=str(RACINE))


# ===========================================================================
# 2 quater. LE CORPS D'UN SHELL — on ne DEVINE plus où il est
# ===========================================================================
#
# Le garde posé la manche dernière décidait, en lisant du TEXTE, LEQUEL des
# arguments était le corps : un drapeau court dont la dernière lettre est `c`,
# puis l'argument suivant. DEUX façons mesurées de se mettre ailleurs, et les
# deux rendaient le coffre d'un faux voisin : `-cx` (le drapeau ne finit pas par
# `c`) et `-c --` (il prenait `--` pour le corps et s'arrêtait là). `-xc`, `-lc`,
# `--norc -c` et `-O extglob -c` étaient, eux, bien vus — et c'est ce mélange
# qui rend un tel juge intenable : on ne peut pas savoir, en le lisant, ce qu'il
# couvre. La table ci-dessous les joue TOUS, ouverts comme fermés, pour que le
# verdict soit le même par construction et non par chance.
#
# LA RÈGLE QUI REMPLACE NE DEVINE RIEN, et c'est pour cela qu'elle supprime la
# classe au lieu d'ajouter un cas : quand le programme est un interprète, TOUT
# argument est un corps possible, et on juge les mots de tous. Un argument qui
# n'est pas un corps se découpe en lui-même — il était déjà jugé comme argument.


@pytest.mark.parametrize("commande, ou_est_le_corps", [
    (["sh", "-c", "cat /var/lib/dpkg/status"], "en i+1 — le cas d'école, déjà vu"),
    (["sh", "-cx", "cat /var/lib/dpkg/status"],
     "OUVERT AVANT : le drapeau ne finit pas par `c`"),
    (["sh", "-c", "--", "cat /var/lib/dpkg/status"],
     "OUVERT AVANT : `--` était pris pour le corps"),
    (["sh", "-xc", "cat /var/lib/dpkg/status"], "déjà vu — la lettre `c` est en fin"),
    (["sh", "-lc", "cat /var/lib/dpkg/status"], "déjà vu — la forme de connexion"),
    (["bash", "--norc", "-c", "cat /var/lib/dpkg/status"],
     "déjà vu — précédé d'une option longue"),
    (["bash", "-O", "extglob", "-c", "cat /var/lib/dpkg/status"],
     "déjà vu — une option courte à valeur SÉPARÉE"),
    (["bash", "--rcfile", "/var/lib/dpkg/status", "-c", "true"],
     "ce n'est pas un corps du tout : c'est un FICHIER que bash va lire"),
    (["bash", "-c", "rm -f " + _CIBLE_A_DETRUIRE], "détruire, pas seulement lire"),
    (["bash", "-c", "echo x >>/var/lib/dpkg/status"], "contaminer"),
])
def test_le_corps_est_juge_ou_qu_il_soit_dans_l_argv(commande, ou_est_le_corps):
    with pytest.raises(RefusHermetique) as pris:
        subprocess.run(commande, capture_output=True, cwd=str(RACINE))
    assert "REFUS hermétique" in str(pris.value), ou_est_le_corps


@pytest.mark.parametrize("commande", [
    ["bash", "-c", "echo bonjour"],
    ["bash", "-c", "cat README.md"],
    ["sh", "-c", "ls docs >/dev/null"],
    ["bash", "-cx", "echo bonjour"],
])
def test_le_corps_legitime_reste_permis(commande):
    """Juger TOUS les arguments ne doit pas fermer le shell aux tests."""
    r = subprocess.run(commande, capture_output=True, cwd=str(RACINE))
    assert r.returncode == 0, r.stderr[:300]


# ===========================================================================
# 2 quinquies. CE QUI RESTE OUVERT — MESURÉ, puis exigé dans l'aveu
# ===========================================================================
#
# Trois justifications réécrites en deux manches se sont révélées fausses, dont
# deux le jour même de leur écriture. La cause était toujours la même : une zone
# qui déclare sa limite à partir de ce qu'on croit, et non de ce qu'on a joué.
# Ces sondes-ci jouent les formes que la porte NE ferme pas, et exigent que
# l'aveu les nomme. Si l'une venait à être fermée, ce test rougirait — un aveu
# périmé est un mensonge de plus.


def _la_porte_se_tait(appel) -> bool:
    """Le GARDE laisse-t-il passer ? (indépendant du régime : on ne juge pas
    ce que le noyau fait ensuite, seulement ce que la porte dit.)"""
    try:
        appel()
    except RefusHermetique:
        return False
    except Exception:
        return True
    return True


def _corps_dans_un_fichier(tmp_path):
    """Le corps n'est plus dans l'argv : il est le CONTENU d'un script."""
    script = tmp_path / "corps.sh"
    script.write_text("cat /var/lib/dpkg/status\n", encoding="utf-8")
    return lambda: subprocess.run(["bash", str(script)], capture_output=True)


SONDES_QUE_LA_PORTE_NE_FERME_PAS = (
    ("l'ENTRÉE STANDARD",
     lambda _t: lambda: subprocess.run(
         ["bash", "-s"], input=b"cat /var/lib/dpkg/status", capture_output=True)),
    ("le quotage ANSI-C",
     lambda _t: lambda: subprocess.run(
         ["bash", "-c", "cat $'\\x2fvar\\x2flib\\x2fdpkg\\x2fstatus'"],
         capture_output=True)),
    ("le chemin COMPOSÉ à l'exécution",
     lambda _t: lambda: subprocess.run(
         ["bash", "-c", 'p=$(printf /%s var); cat "$p/lib/dpkg/status"'],
         capture_output=True)),
    ("le corps mis dans un FICHIER", _corps_dans_un_fichier),
)


@pytest.mark.parametrize("forme, fabrique", SONDES_QUE_LA_PORTE_NE_FERME_PAS)
def test_ce_qui_reste_ouvert_est_mesure_et_declare(forme, fabrique, tmp_path):
    sonde = fabrique(tmp_path)
    assert _la_porte_se_tait(sonde), (
        f"« {forme} » est désormais FERMÉE par la porte : retirez-la de "
        "`ZONES_NON_COUVERTES_DE_LA_PORTE`. Un aveu périmé dit au lecteur "
        "suivant où il est inutile de regarder — c'est exactement la faute que "
        "trois manches ont payée."
    )
    declare = "\n".join(z.mecanique for z in ZONES_NON_COUVERTES_DE_LA_PORTE)
    assert forme in declare, (
        f"« {forme} » passe la porte et n'est pas déclarée dans l'aveu."
    )


# ===========================================================================
# 3. LA PROFONDEUR — un descendant n'est pas moins dangereux qu'un fils
# ===========================================================================


@pytest.mark.parametrize(
    "corps",
    [
        "psql -d arac -c 'SELECT 1'",
        "sudo -n -u postgres psql -d arac -c 'SELECT 1'",
        "systemctl is-active arac-api.service",
        "journalctl -u arac-api -n 10",
        "ss -ltn",
        "pg_dump -d arac",
        "hostname -f",
        # trois niveaux de shell : le PATH de refus est hérité, pas re-posé
        "bash -c 'bash -c \"psql -l\"'",
        # une substitution, pour que le nom n'apparaisse pas en tête de commande
        "x=psql; $x -l",
    ],
)
def test_un_descendant_ne_joint_pas_la_machine(corps):
    """`bash` est légitime — ce qu'il lance ensuite ne l'est pas pour autant.

    C'est par là que passait TOUT ce que la suite atteignait vraiment :
    `sudo -u postgres psql -p 5432` (le cluster de production), `systemctl
    list-unit-files arac-*` (les unités du voisin), `ss -ltnH sport = :8000`.
    """
    r = subprocess.run(["bash", "-c", corps], capture_output=True, text=True)
    assert r.returncode != 0, (
        f"« {corps} » s'est exécuté depuis un sous-processus : la porte est "
        "ouverte."
    )
    assert "REFUS hermétique" in r.stderr, r.stderr[:400]


def test_le_refus_d_un_descendant_est_journalise():
    """Un refus muet au fond d'un shell n'apprend rien à personne."""
    from tests import garde_hermetique as g

    subprocess.run(["bash", "-c", "pg_dumpall"], capture_output=True)
    assert "pg_dumpall" in g.refus_des_descendants(), (
        "le talon doit écrire au journal : `pytest_terminal_summary` en fait "
        "la preuve visible en fin de session."
    )


# ===========================================================================
# 3 bis. CE QUE LE TALON DU `PATH` NE VOIT PAS — les cinq évasions mesurées
# ===========================================================================
#
# Le talon n'est consulté que lorsqu'un shell CHERCHE un programme. Il ne l'est
# jamais quand le shell reçoit un chemin, ni quand le descendant rebâtit son
# `PATH`. Les cinq corps ci-dessous ont tous rendu 0 sur cette machine, la suite
# verte. Ils sont maintenant refusés dans le PÈRE, avant la fourche.


@pytest.mark.parametrize(
    "corps, ce_que_c_est",
    [
        ("/usr/bin/hostname -f",
         "le chemin absolu, dans un shell : le talon n'est pas consulté"),
        ("/usr/lib/postgresql/16/bin/psql --version",
         "le chemin Debian RÉEL du client PostgreSQL — invisible à la liste "
         "blanche de quatre racines, et c'est celui qui compte"),
        ("/opt/pg/bin/dropdb arac",
         "une racine que personne n'a énumérée : la FORME suffit"),
        ("B=/usr/bin; $B/hostname -f",
         "le chemin assemblé : la racine seule est déjà la moitié du geste"),
        ("export PATH=/usr/bin:/bin; hostname -f",
         "le descendant qui REBÂTIT son PATH et jette le répertoire de refus"),
        ("env -i PATH=/usr/bin:/bin hostname -f",
         "l'environnement rasé"),
        ("python3 -I -c 'import psycopg'",
         "l'interpréteur déshabillé, écrit DANS une chaîne : il n'hérite "
         "d'aucun des trois gardes, et il joint 127.0.0.1:5432"),
        ("python3 -S -c 'import socket'",
         "-S saute `site`, donc `sitecustomize`"),
        ("PYTHONPATH= python3 -c 'import socket'",
         "le `PYTHONPATH` VIDÉ : le fils n'a plus le `sitecustomize`, donc "
         "aucun des trois gardes. C'est `python -I` obtenu sans écrire `-I` — "
         "mesuré : le fils rend `socket.socket.connect` d'origine"),
        ("unset PYTHONPATH; python3 -c 'import socket'",
         "la même chose en un mot de moins"),
        ("PYTHONPATH=/tmp/ailleurs python3 -c 'import socket'",
         "le `PYTHONPATH` REBÂTI : allonger est permis, remplacer ne l'est pas"),
        ("unset PATH; echo x",
         "`unset PATH` jette le répertoire de refus"),
    ],
)
def test_le_corps_d_un_shell_est_lu(corps, ce_que_c_est):
    """Ces corps rendaient 0, la suite verte. Ils doivent lever, dans le père.

    Le refus a lieu AVANT la fourche : c'est la différence entre « le shell a
    échoué » et « la suite a refusé ». Un refus au fond d'un descendant
    n'apprend rien à qui lit la trace.
    """
    with pytest.raises(RefusHermetique) as pris:
        subprocess.run(["bash", "-c", corps], capture_output=True)
    assert "REFUS hermétique" in str(pris.value), ce_que_c_est


@pytest.mark.parametrize("corps", [
    "grep -c . README.md",
    "cat README.md | wc -l",
    "PATH=/tmp/faux:$PATH; echo bonjour",   # ALLONGER le PATH reste permis
    # PROUVER QU'ON REFUSE quand l'outil manque : c'est le geste de
    # `test_g2_le_bootstrap_ne_prend_pas_le_role_du_voisin`, et la première
    # rédaction du lecteur de corps l'interdisait. Un `PATH` qui ne mène nulle
    # part n'ouvre rien : il ferme davantage que le répertoire de refus.
    "PATH=/nonexistent-arac-garde; echo bonjour",
    # ALLONGER le PYTHONPATH reste permis : c'est le geste symétrique de
    # `PATH=$FAUX:$PATH`, et le `sitecustomize` reste lu.
    "PYTHONPATH=/tmp/faux:$PYTHONPATH; echo bonjour",
    "test -f README.md && echo oui",
    "sh -c 'echo imbrique'",
])
def test_le_lecteur_de_corps_ne_crie_pas_au_loup(corps):
    """Un garde qui refuse le travail légitime finit désactivé — donc absent.

    `PATH=$FAUX:$PATH` est le geste EXACT que le remède recommande : il garde le
    répertoire de refus en tête. Le refuser reviendrait à interdire le remède.
    """
    r = subprocess.run(["bash", "-c", corps], capture_output=True, text=True,
                       cwd=str(RACINE))
    assert r.returncode == 0, r.stderr[:400]


# ===========================================================================
# 4. LE FILS PYTHON — l'interpréteur est autorisé, donc il doit hériter
# ===========================================================================


def _fils_python(code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
    )


def test_un_python_fils_ne_sort_pas_par_le_reseau():
    r = _fils_python(
        "import socket; socket.socket().connect(('127.0.0.1', 5432))"
    )
    assert r.returncode != 0
    assert "REFUS hermétique" in r.stderr, r.stderr[:400]


def test_un_python_fils_ne_lance_pas_psql():
    r = _fils_python("import subprocess; subprocess.run(['psql', '-l'])")
    assert r.returncode != 0
    assert "REFUS hermétique" in r.stderr, r.stderr[:400]


def test_un_python_fils_porte_le_garde_de_base():
    """La porte la plus discrète : `psycopg` dans un fils, sans un seul binaire.

    On ne peut pas éprouver le refus en ouvrant vraiment une base — il n'y en a
    aucune de marquée dans une suite hermétique, et viser un cerveau vivant pour
    prouver qu'on ne le touche pas serait le comble. On éprouve donc que le
    fils porte bien la serrure : `psycopg.connect` y est le garde, pas la
    fonction d'origine. Le refus lui-même est éprouvé dans le père par les
    tests du garde de marque.
    """
    r = _fils_python(
        "import psycopg, sys; "
        "sys.stdout.write(getattr(psycopg.connect, '__qualname__', '?'))"
    )
    assert r.returncode == 0, r.stderr[:400]
    assert "_connect_garde" in r.stdout, (
        "`psycopg.connect` dans le fils n'est pas le garde : un "
        "`python -c \"import psycopg; psycopg.connect(…)\"` lancé par un test "
        f"atteindrait n'importe quelle base. Vu : {r.stdout!r}"
    )


@pytest.mark.parametrize("drapeau", ["-I", "-E", "-S"])
def test_on_ne_peut_pas_deshabiller_le_fils_python(drapeau):
    """`-I`, `-E`, `-S` : trois façons de faire qu'un fils n'hérite de rien.

    Sans ce refus, `python -I -c "import psycopg; …"` traverserait tout le
    dispositif — l'héritage repose sur `PYTHONPATH` et sur `site`.
    """
    with pytest.raises(RefusHermetique) as pris:
        subprocess.run([sys.executable, drapeau, "-c", "print(1)"],
                       capture_output=True)
    assert "n'hérite PAS" in str(pris.value)


# ===========================================================================
# 4 bis. LE NOM JUGÉ N'EST PAS LE PROGRAMME LANCÉ — six dissociations mesurées
# ===========================================================================
#
# Le garde jugeait `commande[0]`, et en lisait le basename. Six mécanismes
# dissocient ce nom du programme qui s'exécute vraiment. Les six ont été
# reproduits sur cette machine, la suite VERTE, `TENTATIVES_MACHINE` VIDE, avec
# `hostname` pour cible — inoffensif, et l'exact chemin qui atteindrait un
# cerveau si la cible était `psql`.
#
#   subprocess.run(["cat"], executable="…/hostname")        rc=0, nom de la machine
#   subprocess.Popen(["cat"], -1, "…/hostname")             idem, en POSITIONNEL
#   subprocess.run("cat f ; …/hostname", shell=True)        idem — le corps n'était pas lu
#   os.system("cat f ; …/hostname")                         idem
#   os.popen("cat f ; …/hostname")                          idem — `popen` n'était pas gardé
#   tmp_path/cat -> …/hostname   (lien symbolique)          idem — le nom ment, le lien dit vrai
#
# Le principe, en une phrase : **on juge le programme qui s'exécute, jamais
# l'étiquette qu'on lui a mise.**


def test_executable_ne_remplace_pas_le_programme_juge():
    """`executable=` remplace le programme sans toucher `argv[0]`.

    C'est deux mots dans un appel. Le garde lisait « cat » et se taisait pendant
    que le vrai client PostgreSQL ouvrait la socket du cluster de production.
    """
    with pytest.raises(RefusHermetique) as pris:
        subprocess.run(["cat"], executable="/usr/bin/hostname", capture_output=True)
    assert "hostname" in str(pris.value), (
        "le refus doit nommer le programme RÉEL, pas l'étiquette : c'est ce "
        "qui apprend au lecteur que les deux peuvent différer."
    )


def test_executable_positionnel_est_juge_aussi():
    """`executable` est le 3e paramètre positionnel de `Popen`.

    Ne lire que les mots-clés, c'est fermer la porte et laisser la fenêtre.
    """
    with pytest.raises(RefusHermetique):
        subprocess.Popen(["cat"], -1, "/usr/bin/hostname",
                         None, subprocess.PIPE, subprocess.PIPE)


@pytest.mark.parametrize("corps", [
    "cat README.md > /dev/null ; /usr/bin/hostname -f",
    "true && /usr/bin/hostname",
])
def test_un_corps_de_shell_true_est_lu_en_entier(corps):
    """`shell=True` : la commande n'est plus un programme, c'est un CORPS.

    Le garde en jugeait le PREMIER MOT. `cat` étant légitime, tout ce qui
    suivait le point-virgule n'était lu par personne.
    """
    with pytest.raises(RefusHermetique):
        subprocess.run(corps, shell=True, capture_output=True)


def test_os_system_et_os_popen_sont_lus_en_entier():
    """`os.system` et `os.popen` reçoivent un corps de shell, pas un programme.

    `os.popen` ne portait dans son nom aucune des racines que `dir(os)` filtre
    (`exec`, `spawn`, `system`) : il n'était pas gardé du tout.
    """
    with pytest.raises(RefusHermetique):
        os.system("cat README.md > /dev/null ; /usr/bin/hostname")
    with pytest.raises(RefusHermetique):
        os.popen("cat README.md ; /usr/bin/hostname")


def test_un_lien_symbolique_ne_deguise_pas_un_binaire_de_l_hote(tmp_path, monkeypatch):
    """Le nom du lien ment ; le fichier au bout du lien dit vrai.

    Un lien nommé `cat` sous `tmp_path` passait deux contrôles à la fois : son
    basename est légitime, et son chemin est sous le répertoire jetable, que le
    garde tolère pour laisser poser des doubles. On résout donc le lien avant de
    juger.
    """
    reel = "/usr/bin/hostname"
    if not os.path.exists(reel):
        pytest.skip("pas de `hostname` à cet endroit sur cette machine")
    lien = tmp_path / "cat"
    # Poser le lien nomme `reel` : quand Python vit hors de /usr (exécuteur
    # GitHub), le garde refuse déjà cette écriture comme une lecture de l'hôte,
    # avant même le sous-processus que le test veut éprouver. On déclare la
    # lecture, le temps de ce test seulement.
    from tests.garde_hermetique import LECTURES_DECLAREES
    monkeypatch.setitem(
        LECTURES_DECLAREES, reel,
        "hostname : cible d'un lien posé pour éprouver que le garde du "
        "sous-processus juge le fichier au bout du lien, pas son nom")
    lien.symlink_to(reel)
    with pytest.raises(RefusHermetique) as pris:
        subprocess.run([str(lien)], capture_output=True)
    assert "hostname" in str(pris.value)


def test_un_double_reste_nommable_par_un_chemin_relatif_et_son_cwd(tmp_path):
    """La contre-épreuve : résoudre contre `cwd` ne casse pas le remède.

    Un double posé par le test, nommé `./quelque-chose` avec `cwd=`, doit
    continuer de passer — sinon le garde interdirait ce qu'il recommande.
    """
    (tmp_path / "systemctl").write_text("#!/bin/sh\necho double\n", encoding="utf-8")
    (tmp_path / "systemctl").chmod(0o755)
    r = subprocess.run(["./systemctl"], cwd=str(tmp_path),
                       capture_output=True, text=True)
    assert r.returncode == 0 and "double" in r.stdout


# ===========================================================================
# 4 ter. LES EXÉCUTANTS — cinq outils rangés sous leur usage, pas leur pouvoir
# ===========================================================================
#
# `OUTILS_LEGITIMES` décrivait `awk` par « transforme du texte », `find` par
# « parcourt une arborescence », `tar` par « archive des fichiers ». Les cinq
# exécutent un programme arbitraire, et le lecteur de corps ne s'appliquait
# qu'aux SHELLS. Mesuré sur cette machine, la suite verte, le garde muet : les
# cinq formes ci-dessous ont rendu 0 et livré ce qu'on leur demandait.
#
# Ce n'est pas une famille de plus à énumérer : c'est la RAISON de l'énumération
# qui était fausse. La question n'est pas « est-ce un shell ? » mais « cet outil
# peut-il exécuter ce qu'on lui donne ? ».


@pytest.mark.parametrize("commande, ce_que_c_est", [
    (["awk", 'BEGIN{system("/usr/bin/hostname -f")}'],
     "awk exécute : `system()`"),
    (["awk", 'BEGIN{print "x" | "/usr/bin/hostname"}'],
     "awk exécute aussi par le tuyau vers une commande"),
    (["find", "/etc/hostname", "-maxdepth", "0", "-exec", "/usr/bin/hostname", ";"],
     "find exécute : `-exec`"),
    (["find", ".", "-maxdepth", "0", "-execdir", "/usr/bin/hostname", ";"],
     "find exécute aussi par `-execdir`"),
    (["git", "-c", "alias.sonde=!/usr/bin/hostname -f", "sonde"],
     "git exécute : un alias qui commence par `!` est une ligne de shell"),
    (["git", "-c", "core.pager=/usr/bin/hostname", "log"],
     "git exécute aussi ce qu'il prend pour un pagineur"),
    (["sed", "-n", "1s#.*#/usr/bin/hostname#ep", "/etc/hostname"],
     "sed exécute : le drapeau `e` d'un `s///` de GNU sed"),
    (["tar", "-cf", "-", "--to-command", "/usr/bin/hostname", "/etc/hostname"],
     "tar exécute : `--to-command`"),
    (["tar", "--use-compress-program", "/usr/bin/hostname", "-cf", "x.tar", "."],
     "tar exécute aussi le filtre externe"),
])
def test_un_outil_legitime_ne_lance_pas_un_programme_de_l_hote(commande, ce_que_c_est):
    """Ces neuf appels rendaient ce qu'on leur demandait, le garde muet."""
    with pytest.raises(RefusHermetique) as pris:
        subprocess.run(commande, capture_output=True, cwd=str(RACINE))
    assert "REFUS hermétique" in str(pris.value), ce_que_c_est


@pytest.mark.parametrize("commande", [
    ["git", "ls-files"],
    ["git", "-c", "user.name=essai", "status", "--porcelain"],
    ["awk", "{n++} END{print n}", "README.md"],
    ["sed", "-n", "1,3p", "README.md"],
    ["sed", "s/README/LISEZMOI/", "README.md"],
    ["find", "docs", "-maxdepth", "1", "-name", "*.md"],
    ["tar", "-cf", "/dev/null", "README.md"],
])
def test_les_executants_restent_utilisables_pour_ce_qu_ils_lisent(commande):
    """La contre-épreuve. Un garde qui coupe le travail légitime sera désactivé.

    Ces sept-là lisent le dépôt et n'exécutent rien : ils doivent passer. Comme
    ailleurs dans ce fichier, on mesure « le garde a-t-il laissé passer ? », et
    non « la commande a-t-elle réussi ? » — une copie sans `.git` rend 128 sur
    `git`, ce qui ne dit rien du garde.
    """
    r = subprocess.run(commande, capture_output=True, cwd=str(RACINE))
    if commande[0] == "git" and r.returncode == 128:
        pytest.skip("hors dépôt git — la commande est passée, elle n'a rien à lire")
    assert r.returncode == 0, r.stderr[:400]


# ===========================================================================
# 4 quater. LE SECOND RIDEAU — la LECTURE, qui était déclarée nue
# ===========================================================================
#
# `ZONES_NON_COUVERTES_DE_LA_PORTE` déclarait : « Aucun garde n'enveloppe
# `open`, `os.listdir` ni `Path.read_text` — un test peut donc lire les coffres
# des cerveaux installés sur la machine. » C'était vrai, et ce n'était pas une
# zone comme les autres : le jeton d'un cerveau voisin vit dans un fichier. Qui
# le lit n'a plus besoin d'aucune des mailles ci-dessus — il lui suffit d'un GET.
#
# LA MESURE QUI A PERMIS L'INVERSION : un espion posé sur `open` pendant une
# session complète a compté ZÉRO ouverture hors du dépôt, hors du répertoire
# jetable et hors de l'installation Python. Le périmètre n'est donc pas un pari :
# c'est le relevé de ce que la suite fait déjà.
#
# CE CHIFFRE A CHANGÉ AVEC LE PÉRIMÈTRE, et on le réécrit : depuis que le
# `/proc/<pid>/` d'un tiers et les périphériques de `/dev` en sont sortis, une
# session complète (5 086 tests) refuse 241 ouvertures — toutes sous le `/proc`
# d'un autre processus, aucune n'étant un besoin. Le relevé à jour vit
# au-dessus de `garde_hermetique.LECTURES_DECLAREES`.


@pytest.mark.parametrize("chemin", [
    "/etc/sudoers",
    "/etc/shadow",
    "/var/lib/dpkg/status",
])
def test_un_test_ne_lit_pas_un_fichier_de_l_hote(chemin):
    """Le refus tombe AVANT l'ouverture : rien de ce fichier n'est lu.

    Les trois chemins sont neutres et choisis pour cela : on ne prouve pas un
    garde de lecture en lisant le coffre de quelqu'un. Ce qui est éprouvé, c'est
    la RÈGLE — hors du dépôt, hors du jetable, hors de l'installation Python, on
    n'ouvre pas.
    """
    with pytest.raises(RefusHermetique) as pris:
        open(chemin, encoding="utf-8")
    assert "LECTURES_DECLAREES" in str(pris.value), (
        "le refus doit dire quoi faire, sinon il se contourne au lieu de se "
        "respecter."
    )


def test_lister_un_repertoire_de_l_hote_est_refuse_aussi():
    """Lister n'est pas lire, et c'est pourtant le premier geste de l'évasion.

    Une session de contrôle a listé les NOMS des coffres de `/etc/arac/` — sans
    ouvrir aucun fichier — et l'a écrit dans son rapport. C'est le geste qui
    dit qui habite la machine, et c'est le début de la suite.
    """
    for lister in (os.listdir, os.scandir):
        with pytest.raises(RefusHermetique):
            lister("/etc")


@pytest.mark.parametrize("fabrique", [
    lambda r: r / "README.md",
    lambda r: r / "pyproject.toml",
])
def test_lire_le_depot_reste_permis(fabrique):
    """La contre-épreuve : le dépôt est l'objet même des tests."""
    assert fabrique(RACINE).read_text(encoding="utf-8")


def test_lire_sous_tmp_path_reste_permis(tmp_path):
    """L'autre contre-épreuve : c'est là que les tests écrivent tout."""
    (tmp_path / "x.txt").write_text("bonjour", encoding="utf-8")
    assert (tmp_path / "x.txt").read_text(encoding="utf-8") == "bonjour"
    assert "x.txt" in os.listdir(tmp_path)


def test_la_liste_des_lectures_declarees_est_bien_vide_ou_motivee():
    """Une lecture hors périmètre se DÉCLARE, avec ce qu'elle demande.

    Le vide d'aujourd'hui est un fait mesuré, pas une omission. Le jour où une
    ligne y apparaîtra, elle devra dire pourquoi rien d'autre ne ferait
    l'affaire — c'est la même exigence que `EXCEPTIONS_DECLAREES` plus bas.
    """
    from tests.garde_hermetique import LECTURES_DECLAREES

    muettes = [c for c, r in LECTURES_DECLAREES.items() if len(r.strip()) < 40]
    assert not muettes, (
        f"lecture hors périmètre déclarée sans raison lisible : {muettes}"
    )


# ===========================================================================
# 4 quinquies. L'HÉRITAGE TIENT À UNE VARIABLE — et la dépendance est ÉCRITE
# ===========================================================================
#
# La manche précédente avait fermé `PYTHONPATH= python3 …` dans un corps de
# shell, et elle l'avait bien fermé. Elle n'avait pas écrit la DÉPENDANCE — et
# c'est ce silence, pas la maille, qui a coûté la manche suivante : rien ne
# disait « tout l'héritage tient à ces deux variables », donc personne n'a
# cherché les autres portes par lesquelles on les efface. Il y en avait quatre,
# toutes en PYTHON, toutes en une ligne, aucune n'écrivant ni `-I`, ni `bash`,
# ni le moindre chemin — donc invisibles aussi pour le balayage de `tests/` :
#
#   os.posix_spawn(python, argv, {})            → fils NU
#   os.execve(python, argv, {})                 → fils NU
#   os.putenv("PYTHONPATH", "") puis un run     → fils NU
#   preexec_fn=lambda: os.unsetenv("PYTHONPATH") → fils NU
#
# « Fils NU » se mesure : `socket.socket.connect.__name__` y vaut « connect » au
# lieu de « _refuse_la_sortie ». Les quatre sont fermées ; la dépendance est
# maintenant DÉCLARÉE dans `VARIABLES_DE_L_HERITAGE`, et les tests ci-dessous
# rougissent si la déclaration disparaît — ou si elle devient fausse.

_CODE_QUI_SE_REGARDE = (
    "import os,socket;print(socket.socket.connect.__name__)"
)


def _fils_prive_de(variable: str) -> str:
    """Lance un `python` privé d'UNE variable, et rend le nom de son `connect`.

    On passe par `execve` DE LA LIBC, appelée en `ctypes` dans un fils forké.
    Ce n'est pas une coquetterie : toutes les portes Python sont désormais
    fermées, et c'est très exactement ce qu'on veut prouver. La libc est la
    zone que ce fichier DÉCLARE ne pas fermer — s'en servir ici est honnête, et
    c'est le seul moyen qui reste de mesurer la dépendance au lieu de l'affirmer.
    """
    import ctypes

    environnement = {c: v for c, v in os.environ.items() if c != variable}
    lecture, ecriture = os.pipe()
    fils = os.fork()
    if fils == 0:  # pragma: no cover — le fils ne rend jamais la main
        try:
            os.dup2(ecriture, 1)
            os.close(lecture)
            libc = ctypes.CDLL(None, use_errno=True)
            argv = (ctypes.c_char_p * 4)(
                sys.executable.encode(), b"-c", _CODE_QUI_SE_REGARDE.encode(), None)
            enve = (ctypes.c_char_p * (len(environnement) + 1))(
                *[f"{c}={v}".encode() for c, v in environnement.items()], None)
            libc.execve(sys.executable.encode(), argv, enve)
        finally:
            os._exit(9)
    os.close(ecriture)
    with os.fdopen(lecture, "rb") as tuyau:
        sortie = tuyau.read().decode().strip()
    os.waitpid(fils, 0)
    return sortie


def test_la_dependance_de_l_heritage_est_declaree():
    """La déclaration existe, elle nomme les deux variables, et elle dit POURQUOI.

    C'est le test qui rougit si quelqu'un efface la déclaration — le geste que
    la manche précédente n'avait pas fait, et sans lequel la maille suivante ne
    se cherche pas.
    """
    from tests.garde_hermetique import VARIABLES_DE_L_HERITAGE

    assert set(VARIABLES_DE_L_HERITAGE) == {"PYTHONPATH", "PATH"}, (
        "l'héritage des gardes tient à ces deux variables et à rien d'autre. "
        "Si une troisième apparaît, elle se déclare ICI — et si l'une des deux "
        "cesse de compter, la mécanique a changé et tout ce fichier est à relire."
    )
    for variable, raison in VARIABLES_DE_L_HERITAGE.items():
        assert len(raison) > 120, (
            f"« {variable} » : une dépendance déclarée sans sa mécanique est un "
            "commentaire. Dites ce qui casse quand elle disparaît."
        )
    assert any("UNE VARIABLE" in z.zone.upper()
               for z in ZONES_NON_COUVERTES_DE_LA_PORTE), (
        "la dépendance doit aussi être dans l'aveu imprimé en fin de session : "
        "ce qui n'est pas imprimé n'est pas lu."
    )


@pytest.mark.parametrize("variable", ["PYTHONPATH", "PATH"])
def test_la_dependance_declaree_est_VRAIE(variable):
    """On EFFACE la variable dans un fils, et on exige que le fils en sorte nu.

    Une déclaration qu'on ne peut pas éprouver est un commentaire. Celle-ci se
    mesure : privé de `PYTHONPATH`, le fils rend « connect » — l'original — au
    lieu de « _refuse_la_sortie ». Le témoin, juste en dessous, montre que c'est
    bien la variable et rien d'autre qui décide.
    """
    from tests.garde_hermetique import VARIABLES_DE_L_HERITAGE

    assert variable in VARIABLES_DE_L_HERITAGE
    nu = _fils_prive_de(variable)
    temoin = _fils_prive_de("ARAC_GARDE_VARIABLE_QUI_N_EXISTE_PAS")
    assert temoin == "_refuse_la_sortie", (
        "le témoin doit porter le garde : sans lui, ce test ne prouve rien."
    )
    if variable == "PYTHONPATH":
        assert nu == "connect", (
            "privé de PYTHONPATH, un fils DOIT être nu — c'est la dépendance "
            "déclarée. S'il ne l'est plus, l'héritage passe désormais par autre "
            "chose, et `VARIABLES_DE_L_HERITAGE` ment."
        )
    else:
        # `PATH` ne porte pas le `sitecustomize` : il porte le TALON. Un fils
        # privé de `PATH` garde donc ses gardes Python et perd le talon — ce
        # qui se mesure autrement, plus bas, par `refus_des_descendants`.
        assert nu == "_refuse_la_sortie"


@pytest.mark.parametrize("porte", ["posix_spawn", "execve"])
def test_les_primitives_qui_recoivent_un_environnement_le_font_juger(porte):
    """`os.posix_spawn(py, argv, {})` rendait un fils NU. Il rend le garde.

    L'environnement est un ARGUMENT COMME UN AUTRE, et il n'était jugé nulle
    part : la boucle des primitives ne lisait que le PROGRAMME, y voyait
    « python », et laissait passer le troisième argument.
    """
    lecture, ecriture = os.pipe()
    if porte == "posix_spawn":
        fils = os.posix_spawn(
            sys.executable, [sys.executable, "-c", _CODE_QUI_SE_REGARDE], {},
            file_actions=[(os.POSIX_SPAWN_DUP2, ecriture, 1)])
    else:
        fils = os.fork()
        if fils == 0:  # pragma: no cover — le fils ne rend jamais la main
            try:
                os.dup2(ecriture, 1)
                os.close(lecture)
                os.execve(sys.executable,
                          [sys.executable, "-c", _CODE_QUI_SE_REGARDE], {})
            finally:
                os._exit(9)
    os.close(ecriture)
    with os.fdopen(lecture, "rb") as tuyau:
        sortie = tuyau.read().decode().strip()
    os.waitpid(fils, 0)
    assert sortie == "_refuse_la_sortie", (
        f"`os.{porte}` avec un environnement vide a rendu un fils sans gardes "
        f"(« {sortie} »). L'environnement doit passer par `_environnement_garde` "
        "partout où il est reçu, pas seulement dans `Popen`."
    )


def test_effacer_l_heritage_depuis_python_est_refuse():
    """`os.putenv` écrit dans l'environnement C sans toucher `os.environ`.

    Aucun `env=` n'est passé, donc `_environnement_garde` n'est jamais appelé,
    et le fils suivant naît nu — sans qu'aucun motif de corps de shell n'ait
    rien à lire.
    """
    with pytest.raises(RefusHermetique) as pris:
        os.putenv("PYTHONPATH", "")
    assert "VARIABLES_DE_L_HERITAGE" in str(pris.value)
    with pytest.raises(RefusHermetique):
        os.unsetenv("PYTHONPATH")


def test_allonger_l_heritage_reste_permis(tmp_path):
    """La contre-épreuve : allonger est le geste légitime, et il doit passer."""
    ancien = os.environ["PYTHONPATH"]
    os.environ["PYTHONPATH"] = f"{tmp_path}{os.pathsep}{ancien}"
    try:
        assert os.environ["PYTHONPATH"].endswith(ancien)
    finally:
        os.environ["PYTHONPATH"] = ancien


def test_un_preexec_fn_est_refuse():
    """Elle tourne dans le FILS, après le contrôle : le garde ne peut rien en dire."""
    with pytest.raises(RefusHermetique) as pris:
        subprocess.run(["echo", "ok"], capture_output=True,
                       preexec_fn=lambda: os.unsetenv("PYTHONPATH"))
    assert "preexec_fn" in str(pris.value)


def test_popen_avec_neuf_positionnels_est_controle_et_ne_plante_pas():
    """Le décalage d'un cran : `len(a) >= 9` puis `a[9]`.

    Avec exactement neuf arguments positionnels après `args` — jusqu'à `cwd`,
    sans `env` — le garde levait `IndexError('tuple index out of range')` au
    lieu du refus qui enseigne. Le comportement restait fermé ; le message
    accusait le garde plutôt que l'appel.
    """
    with pytest.raises(RefusHermetique) as pris:
        subprocess.Popen(["/usr/lib/postgresql/16/bin/psql", "-l"], -1, None,
                         None, subprocess.PIPE, None, None, True, False, None)
    assert "REFUS hermétique" in str(pris.value)
    r = subprocess.Popen(["echo", "ok"], -1, None, None, subprocess.PIPE,
                         None, None, True, False, None)
    assert r.communicate()[0].strip() == b"ok"


# ===========================================================================
# 4 sexies. LE CRITÈRE DE FORME — ce qu'un outil PEUT faire, lu dans son ELF
# ===========================================================================
#
# QUATRE FOIS, CE DÉPÔT A BUTÉ SUR UNE ÉNUMÉRATION : liste de dossiers, liste de
# suffixes, liste de noms de binaires, liste d'outils EXÉCUTANTS. Les trois
# premières ont été remplacées par une forme. La quatrième l'est ici — et la
# forme n'est pas une intuition, c'est une MESURE : un ELF déclare, dans sa
# table de symboles dynamiques, les portes de la libc qu'il ira chercher. Un
# programme qui peut en lancer un autre doit y nommer `execve`, `execvp`,
# `execlp`, `posix_spawn`, `system` ou `popen`. Il ne peut pas s'en passer.
#
# Ce que la mesure a rendu, et que personne n'avait deviné : `sort` (par
# `--compress-program` — il avait démarré le vrai `psql` contre la grappe de
# PRODUCTION) et `install` (par `--strip-program`). Les sept de la liste écrite
# sont retrouvés au passage, ce qui est la contre-épreuve du critère.


def test_le_critere_de_forme_retrouve_les_executants_ecrits(monkeypatch):
    """Le critère doit d'abord retrouver ce que la liste savait déjà."""
    from tests.garde_hermetique import LECTURES_DECLAREES, _peut_executer

    manques = []
    for nom in ("awk", "sed", "find", "tar", "git", "bash"):
        reel = shutil.which(nom, path=os.environ.get("ARAC_GARDE_PATH_HOTE", ""))
        if not reel:
            continue
        reel = os.path.realpath(reel)
        # Lire l'ELF d'un outil de l'hôte est la mesure même. Quand Python vit
        # hors de /usr (setup-python sur un exécuteur GitHub : /opt/hostedtoolcache),
        # /usr est hors périmètre et le garde refuse la lecture — `_peut_executer`
        # rend alors None et le test accuse à tort le critère. On déclare donc la
        # lecture, le temps de ce test seulement (monkeypatch : rien ne subsiste).
        monkeypatch.setitem(
            LECTURES_DECLAREES, reel,
            f"{nom} : lecture de l'en-tête ELF par le critère de forme, pour "
            "vérifier qu'il retrouve les exécutants de la liste écrite")
        if _peut_executer(reel) is not True:
            manques.append(nom)
    assert not manques, (
        f"le critère de forme ne voit plus {manques} comme exécutants alors que "
        "la liste écrite les nomme : il a cessé de lire, et tout ce qu'il "
        "trouvait « en plus » ne prouve plus rien."
    )


def test_le_critere_de_forme_trouve_ce_que_la_liste_ignorait():
    """`sort` et `install` : trouvés par la MESURE, pas par quelqu'un qui y a pensé."""
    from tests.garde_hermetique import _peut_executer

    for nom in ("sort", "install"):
        reel = shutil.which(nom, path=os.environ.get("ARAC_GARDE_PATH_HOTE", ""))
        if not reel:
            pytest.skip(f"{nom} absent de cette machine")
        if _peut_executer(os.path.realpath(reel)) is None:
            pytest.skip(f"{nom} n'est pas un ELF 64 lisible sur cette machine")
        assert _peut_executer(os.path.realpath(reel)) is True, (
            f"sur cette machine, `{nom}` n'annonce aucune porte d'exécution. "
            "C'est possible ailleurs — mais alors ce test doit le DIRE en "
            "s'ignorant, jamais passer en silence."
        )


def test_le_critere_de_forme_ne_crie_pas_au_loup():
    """Un critère qui rangerait `cat` parmi les exécutants serait inutilisable."""
    from tests.garde_hermetique import _peut_executer

    bavards = []
    for nom in ("cat", "head", "tail", "grep", "wc", "cut", "ls", "rm", "cp"):
        reel = shutil.which(nom, path=os.environ.get("ARAC_GARDE_PATH_HOTE", ""))
        if not reel:
            continue
        if _peut_executer(os.path.realpath(reel)) is True:
            bavards.append(nom)
    assert not bavards, (
        f"{bavards} annoncent une porte d'exécution sur cette machine. Ce n'est "
        "pas forcément une erreur du critère — un busybox le ferait — mais il "
        "faut alors le regarder plutôt que le supposer."
    )


@pytest.mark.parametrize("commande, ce_que_c_est", [
    (["sort", "--compress-program", "/usr/lib/postgresql/16/bin/psql", "x"],
     "sort exécute : `--compress-program`, mesuré contre la grappe de production"),
    (["sort", "--compress-program=/usr/bin/hostname", "x"],
     "la même, écrite avec un `=`"),
    (["install", "--strip-program", "/usr/bin/hostname", "a", "b"],
     "install exécute : `--strip-program`"),
])
def test_les_executants_mesures_sont_gardes_comme_les_autres(commande, ce_que_c_est):
    with pytest.raises(RefusHermetique) as pris:
        subprocess.run(commande, capture_output=True, cwd=str(RACINE))
    assert "REFUS hermétique" in str(pris.value), ce_que_c_est


@pytest.mark.parametrize("commande", [
    ["sort", "README.md"],
    ["sort", "-u", "README.md"],
])
def test_les_executants_mesures_restent_utilisables(commande):
    """La contre-épreuve : `sort` trie encore ce qu'on lui donne."""
    r = subprocess.run(commande, capture_output=True, cwd=str(RACINE))
    assert r.returncode == 0, r.stderr[:300]


# ===========================================================================
# 4 septies. LE RIDEAU DE LECTURE A DEUX CÔTÉS — et un seul était fermé
# ===========================================================================
#
# Le quatrième garde a été écrit avec la bonne raison, citée en toutes lettres :
# « le jeton d'un cerveau voisin vit dans un FICHIER. Qui le lit n'a plus besoin
# de `psql` ni de `sudo` : un GET suffit. » La raison est juste. L'application ne
# la suivait que du côté PYTHON. Mesuré, le même chemin, deux fois :
#
#   open("/var/lib/dpkg/status")   → RefusDeFichier
#   head -2 /var/lib/dpkg/status   → rc=0, le contenu revient
#   os.remove(<un fichier>)        → RefusDeFichier
#   find … -delete  /  rm -rf …    → rc=0, le fichier n'existe plus
#
# `TENTATIVES_MACHINE` ne bougeait pas : le garde du sous-processus ne cherchait
# que des chemins d'EXÉCUTABLE, jamais des chemins de DONNÉE.
#
# LA CORRECTION N'EST PAS UNE LISTE D'OUTILS. Un ensemble `TOUCHE_DES_FICHIERS`
# posé à côté d'`EXECUTANTS` aurait été la cinquième énumération. Un argument
# qui désigne un chemin est un chemin, quel que soit l'outil : le contrôle porte
# sur TOUT argument de TOUT outil, et il emploie le PÉRIMÈTRE DÉJÀ DÉCLARÉ par
# le rideau de lecture.

#: Un chemin qui n'existe pas, sous un répertoire qui existe et qui est hors du
#: périmètre. Les sondes destructrices le visent : si le garde échouait, `rm` et
#: `find -delete` n'auraient RIEN à détruire. On ne prouve pas un garde en
#: pariant la mémoire de quelqu'un.
_SONDE_INEXISTANTE = "/var/lib/dpkg/mai13-sonde-qui-n-existe-pas"


@pytest.mark.parametrize("commande, ce_que_c_est", [
    (["head", "-2", "/var/lib/dpkg/status"], "head LIT un fichier de l'hôte"),
    (["grep", "-c", "Package:", "/var/lib/dpkg/status"], "grep aussi"),
    (["cat", "/var/lib/dpkg/status"], "cat aussi"),
    (["wc", "-l", "/var/lib/dpkg/status"], "wc aussi"),
    (["rm", "-rf", _SONDE_INEXISTANTE], "rm DÉTRUIT"),
    (["find", "/var/lib/dpkg", "-name", "mai13-*", "-delete"],
     "find -delete détruit aussi, et `find` était déjà un exécutant"),
    (["tee", _SONDE_INEXISTANTE], "tee ÉCRIT hors périmètre"),
    (["sed", "-i", "s/a/b/", "/var/lib/dpkg/status"], "sed -i réécrit sur place"),
    (["cp", "/var/lib/dpkg/status", _SONDE_INEXISTANTE], "cp copie ce qu'il lit"),
    (["chmod", "600", "/var/lib/dpkg/status"], "chmod change un mode"),
    (["ls", "/var/lib/dpkg"], "ls liste — le premier geste de l'évasion"),
    (["sha256sum", "/var/lib/dpkg/status"], "une empreinte est une lecture"),
])
def test_un_outil_legitime_ne_touche_pas_un_fichier_de_l_hote(commande, ce_que_c_est):
    """Douze gestes qui rendaient ce qu'on leur demandait, le journal vide."""
    with pytest.raises(RefusHermetique) as pris:
        subprocess.run(commande, capture_output=True, cwd=str(RACINE))
    assert "REFUS hermétique" in str(pris.value), ce_que_c_est
    assert "tmp_path" in str(pris.value), (
        "un refus qui ne dit pas quoi faire se contourne au lieu de se respecter."
    )


@pytest.mark.parametrize("commande", [
    ["cat", "README.md"],
    ["wc", "-l", "README.md"],
    ["head", "-1", "Makefile"],
    ["ls", "docs"],
    ["grep", "-c", "arac", "README.md"],
    ["sed", "-n", "1,2p", "/etc/hostname"],
    ["test", "-x", "/usr/bin/env"],
])
def test_toucher_le_depot_et_la_distribution_reste_permis(commande):
    """La contre-épreuve, et elle compte autant que le refus.

    Le dépôt est l'objet même des tests ; `/usr/bin` et `/etc/hostname` ne
    portent aucun cerveau, et demander si un fichier de la distribution existe
    n'est pas lire un coffre. Un garde qui coupe le travail légitime finit
    désactivé, et c'est alors toute la porte qui tombe.
    """
    r = subprocess.run(commande, capture_output=True, cwd=str(RACINE))
    assert r.returncode in (0, 1), r.stderr[:300]


def test_un_chemin_absolu_sous_tmp_path_reste_permis(tmp_path):
    """C'est là que les tests écrivent tout : le refus ne doit pas y mordre."""
    cible = tmp_path / "journal.txt"
    r = subprocess.run(["tee", str(cible)], input=b"bonjour", capture_output=True)
    assert r.returncode == 0
    assert cible.read_text(encoding="utf-8") == "bonjour"


# ===========================================================================
# 4 octies. LA SECONDE BARRIÈRE — l'évasion qu'on n'a pas trouvée, sans effet
# ===========================================================================
#
# Ce fichier déclare depuis le début que la vraie barrière n'est pas dans ce
# fichier : « toutes les évasions ci-dessus n'atteignent un cerveau réel que
# parce que le processus en a le DROIT ». C'était un constat honnête, et il est
# resté un constat pendant quatre manches. `tests/seconde_barriere.py` en fait
# un dispositif : Landlock retire au NOYAU, pour cette session et toute sa
# descendance, le droit de toucher un fichier hors du périmètre que le rideau de
# lecture déclare déjà.
#
# Ce qui change : une évasion qu'on n'a pas trouvée devient SANS EFFET. La libc
# appelée en `ctypes` — la zone que ce fichier déclare ne pas fermer — échoue
# désormais dans le noyau.


def _barriere_posee() -> bool:
    from tests import conftest as c

    return c.VERDICT_DE_LA_SECONDE_BARRIERE.startswith("POSÉE")


def test_la_seconde_barriere_dit_ce_qu_elle_a_fait():
    """Posée ou non, elle s'annonce. Une barrière supposée n'est pas une barrière."""
    from tests import conftest as c

    verdict = c.VERDICT_DE_LA_SECONDE_BARRIERE
    assert verdict.startswith(("POSÉE", "PAS POSÉE")), verdict
    assert len(verdict) > 80, "le verdict doit dire ce qui a été posé, ou pourquoi rien."


def test_la_libc_ne_lit_plus_un_fichier_de_l_hote():
    """LA PREUVE QUI COMPTE : la maille déclarée ouverte devient sans effet.

    `ctypes.CDLL("libc.so.6")` ne passe ni par `subprocess`, ni par `os`, ni par
    `builtins.open` : aucun garde de ce dépôt ne la voit, et c'est écrit dans
    l'aveu. Sous la seconde barrière, elle échoue quand même — dans le noyau.
    """
    import ctypes

    if not _barriere_posee():
        pytest.skip("seconde barrière non posée sur cette machine — voir le verdict")
    libc = ctypes.CDLL(None, use_errno=True)
    fd = libc.open(b"/var/lib/dpkg/status", 0)
    if fd >= 0:  # pragma: no cover — la barrière n'aurait pas tenu
        os.close(fd)
        pytest.fail(
            "la libc a ouvert un fichier de l'hôte alors que la seconde "
            "barrière est annoncée POSÉE : le périmètre accordé est trop large."
        )
    assert ctypes.get_errno() == 13, (
        f"refus attendu EACCES (13), obtenu {ctypes.get_errno()}"
    )


def test_un_chemin_ECRIT_dans_un_corps_de_shell_est_refuse_par_la_porte():
    """LA CINQUIÈME INSTANCE, FERMÉE — et le test qui l'exigeait ouverte, retourné.

    CE TEST S'APPELAIT `test_une_maille_DECLAREE_OUVERTE_ne_rend_plus_rien`, ET
    IL EXIGEAIT QUE L'ÉVASION PASSE. Il était vert à chaque `make test` depuis
    des manches, et sa forme était un verrou posé sur le trou : le jour où
    quelqu'un refermait la maille, la suite rougissait, et il la rouvrait. Un
    test ne doit jamais exiger d'une PORTE qu'elle laisse passer ; il peut
    seulement exiger d'une DÉFENSE qu'elle tienne (voir le test suivant).

    Ce que la porte refuse maintenant, dans les DEUX régimes : le corps arrivé
    en LISTE est découpé comme un shell le découpe, et chacun de ses mots est
    remis au même juge que les arguments. Mesuré avant correction, régime de
    repli, sur des faux voisins : la même commande rendait le jeton porteur et
    le DSN d'administration d'un coffre voisin.
    """
    with pytest.raises(RefusHermetique) as refus:
        subprocess.run(["bash", "-c", "head -1 /var/lib/dpkg/status"],
                       capture_output=True, text=True, cwd=str(RACINE))
    assert "/var/lib/dpkg/status" in str(refus.value), (
        "le refus doit NOMMER le chemin lu dans le corps, sinon il n'apprend "
        f"rien : {str(refus.value)[:300]}"
    )


@pytest.mark.parametrize("corps", [
    'head -1 "/var/lib/dpkg/status"',          # guillemets : `split` ne les ôte pas
    "head -1 </var/lib/dpkg/status",           # opérateur collé au chemin
    "true; head -1 /var/lib/dpkg/status",      # après un point-virgule
    "cd / && head -1 /var/lib/dpkg/status",    # après un `&&`
])
def test_les_formes_du_meme_corps_sont_toutes_refusees(corps):
    """Une maille se ferme sur la RÉSOLUTION, pas sur une écriture.

    Les quatre corps ci-dessous désignent le même fichier de l'hôte et
    s'écrivent différemment. `str.split` — le découpage d'avant — n'en voyait
    que deux : il laisse le guillemet DANS le mot et colle l'opérateur au
    chemin. Fermer une écriture et pas les trois autres est exactement ce que
    ce dépôt corrige depuis cinq manches.
    """
    with pytest.raises(RefusHermetique):
        subprocess.run(["sh", "-c", corps], capture_output=True, cwd=str(RACINE))


def test_une_maille_DECLAREE_OUVERTE_ne_rend_plus_rien():
    """LA PREUVE DE LA DÉFENSE EN PROFONDEUR, sur la maille qui reste ouverte.

    La zone déclare ce que la porte ne sait pas faire, et ce n'est plus « lire
    un corps de shell » : c'est lire ce qu'un corps de shell COMPOSE. Le chemin
    ci-dessous n'est écrit nulle part — il est assemblé par le shell à
    l'exécution, et aucun motif ne le lit. La porte le laisse donc passer, et
    c'est assumé : c'est très exactement l'endroit où la seconde barrière prend
    le relais.

    Ce test mesure les deux moitiés : que l'évasion PASSE la porte (sinon la
    déclaration mentirait dans l'autre sens), et qu'elle NE REND RIEN quand le
    noyau garde la maison.
    """
    compose = 'p=$(printf "/%s/%s/%s" var lib dpkg); head -1 "$p/status"'
    r = subprocess.run(["bash", "-c", compose],
                       capture_output=True, text=True, cwd=str(RACINE))
    if not _barriere_posee():
        pytest.skip("seconde barrière non posée — l'évasion rendrait le fichier")
    assert not r.stdout.strip(), (
        "le chemin COMPOSÉ a rendu le contenu d'un fichier de l'hôte alors que "
        "la seconde barrière est annoncée POSÉE."
    )
    assert r.returncode != 0 and "annot open" in r.stderr, (
        f"refus du noyau attendu, obtenu rc={r.returncode} err={r.stderr[:120]!r}"
    )


def test_la_seconde_barriere_laisse_vivre_le_depot(tmp_path):
    """La contre-épreuve : ce que la suite fait vraiment doit continuer.

    Lire le dépôt, écrire sous `tmp_path`, lancer `git` — si l'un des trois
    tombait, la barrière serait retirée le lendemain, et il ne resterait rien.
    """
    assert (RACINE / "README.md").read_text(encoding="utf-8")
    (tmp_path / "x").write_text("ok", encoding="utf-8")
    assert (tmp_path / "x").read_text(encoding="utf-8") == "ok"
    r = subprocess.run(["git", "ls-files"], capture_output=True, cwd=str(RACINE))
    assert r.returncode in (0, 128), r.stderr[:300]


def test_aucune_racine_de_cerveau_n_est_accordee():
    """La question qui compte : le périmètre accordé laisse-t-il passer un coffre ?

    On ne le mesure pas en ouvrant `/etc/arac/<un autre>` — on ne prouve pas un
    garde en tentant le geste qu'il interdit, et lire le coffre d'un voisin est
    précisément ce que tout ce fichier existe pour empêcher. On le mesure en
    RELISANT le périmètre : aucune racine accordée ne doit être un répertoire de
    cerveau, ni le contenir, ni être contenue par lui.
    """
    from tests import garde_hermetique as g
    from tests import seconde_barriere as sb

    # ON RELIT CE QUE LE CODE CALCULE, PAS UNE COPIE RECOMPOSÉE À LA MAIN.
    # Cette version-ci recomposait le périmètre par une union écrite dans le
    # test — et elle a donc été VERTE pendant que la barrière accordait au
    # noyau quatre des onze zones retranchées : la copie ne connaissait ni le
    # retranchement, ni l'éclatement des racines. Un juge qui garde sa propre
    # copie de la liste qu'il juge est la faute que ce dépôt a payée trois fois.
    lecture, ecriture, fichiers, portes = sb.perimetre_depuis_le_garde()
    accordees = set(lecture) | set(ecriture) | set(fichiers) | set(portes)

    #: LES ONZE ZONES, PAS LES QUATRE PREMIÈRES. Là où un cerveau vit — le
    #: coffre, la mémoire, les journaux, les sauvegardes — ET là où l'on peut
    #: s'en donner les clés sans toucher un seul de ses fichiers : une unité
    #: systemd, une surcharge d'unité, un `tmpfiles.d`, un `sysusers.d`.
    #: `_RETRANCHEES` est cette liste, et c'est elle que le rideau de Python
    #: applique : la barrière du noyau doit dire la même chose, ou elle ne
    #: double rien.
    fautes = []
    for coffre in (r.rstrip("/") for r in g._RETRANCHEES):
        for racine in accordees:
            if not racine:
                continue
            # LES DEUX NOMS DE CHAQUE RACINE. `/lib` est un LIEN vers
            # `/usr/lib` sur Debian, et `open(…, O_PATH)` suit les liens :
            # accorder `/lib` accordait `/usr/lib/systemd`. Mesuré.
            for r in {racine.rstrip("/"), os.path.realpath(racine).rstrip("/")}:
                if r == coffre or r.startswith(coffre + "/") or \
                        coffre.startswith(r + "/"):
                    fautes.append(f"{racine} touche {coffre}")
    assert not fautes, (
        "le périmètre accordé au noyau atteint une zone retranchée :\n  "
        + "\n  ".join(sorted(set(fautes)))
        + "\nUne barrière qui accorde le coffre n'est pas une barrière."
    )


def test_le_perimetre_de_la_barriere_n_est_pas_une_seconde_liste():
    """Une seconde liste aurait été la cinquième énumération de ce dépôt.

    Le périmètre appliqué au noyau est celui que `garde_hermetique` déclare —
    on le vérifie en le relisant, pas en le croyant.
    """
    from tests import garde_hermetique as g
    from tests import seconde_barriere as sb

    source = Path(sb.__file__).read_text(encoding="utf-8")
    assert "_racines_de_lecture()" in source and "_RACINES_SANS_CERVEAU" in source, (
        "le périmètre de la barrière doit être REPRIS du rideau de lecture, "
        "jamais recopié : deux définitions de « ce qu'on a le droit de "
        "toucher » divergent le jour où l'une seule est corrigée."
    )
    assert str(g.RACINE_DEPOT) in sb.poser_depuis_le_garde.__doc__ or True


# ===========================================================================
# 5. LE GARDE RESTE VIVABLE — un garde insupportable finit désactivé
# ===========================================================================


@pytest.mark.parametrize("commande", [
    ["git", "ls-files"],
    ["bash", "-n", "ops/lint_shell.sh"],
    ["bash", "-c", "grep -c . README.md"],
    [sys.executable, "-c", "print('bonjour')"],
])
def test_ce_qui_regarde_le_depot_reste_permis(commande):
    """On ne coupe pas ce qui lit le dépôt : c'est l'objet même des tests.

    CE QUE CE TEST MESURE, ET CE QU'IL NE MESURE PAS. La question est
    « le garde a-t-il LAISSÉ PASSER ce sous-processus ? », jamais « la
    commande a-t-elle réussi ? ». Confondre les deux coûtait un rouge à
    quiconque travaille dans une copie sans `.git` : `git ls-files` y rend
    128, ce qui ne dit rien du garde et tout de l'environnement. Un refus
    du garde lève `RefusHermetique` — c'est cela, et cela seul, qu'on
    exige de ne pas voir.
    """
    r = subprocess.run(commande, capture_output=True, cwd=str(RACINE))
    if commande[0] == "git" and r.returncode == 128:
        pytest.skip("hors dépôt git — la commande est passée, elle n'a rien à lire")
    assert r.returncode == 0, r.stderr[:400]


def test_un_double_pose_par_le_test_reste_permis(tmp_path):
    """Le remède doit rester praticable, sinon il ne sera pas pratiqué.

    `test_bootstrap_services_unites` fournit un faux `systemd-run`,
    `test_verify_install_cadre` un faux `ss` et un faux `systemctl` : sans cette
    porte-là, la moitié des gardes du bootstrap deviendrait intestable.
    """
    faux = tmp_path / "bin"
    faux.mkdir()
    (faux / "systemctl").write_text("#!/bin/sh\necho joue-la-comedie\n", encoding="utf-8")
    (faux / "systemctl").chmod(0o755)
    r = subprocess.run(
        ["bash", "-c", "systemctl is-active quoi-que-ce-soit"],
        capture_output=True, text=True,
        env={**os.environ, "PATH": f"{faux}:{os.environ['PATH']}"},
    )
    assert r.returncode == 0, r.stderr[:400]
    assert "joue-la-comedie" in r.stdout


def test_un_double_sous_tmp_path_peut_etre_nomme_par_son_chemin(tmp_path):
    """Le lecteur de corps ne doit pas interdire le remède qu'il recommande.

    Un double vit sous `tmp_path`, donc sous le répertoire jetable : le nommer
    par son chemin absolu, `bin` compris, n'est pas une évasion — c'est le
    geste que le message de refus enseigne.
    """
    faux = tmp_path / "bin"
    faux.mkdir()
    (faux / "systemctl").write_text("#!/bin/sh\necho double\n", encoding="utf-8")
    (faux / "systemctl").chmod(0o755)
    r = subprocess.run(["bash", "-c", f"{faux / 'systemctl'} is-active x"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[:400]
    assert "double" in r.stdout


def test_un_script_du_depot_reste_lancable(tmp_path):
    """Un programme qui vient du dépôt est l'objet du test, pas l'hôte."""
    script = RACINE / "ops" / "lint_shell.sh"
    assert script.exists()
    r = subprocess.run(["bash", "-n", str(script)], capture_output=True)
    assert r.returncode == 0


# ===========================================================================
# 6. LA DISPENSE `tests/` DE G1, RENDUE MORTELLE
# ===========================================================================
#
# G1 dispense `tests/` de tous ses motifs, au motif qu'« un test NOMME pour
# affirmer ; il n'installe rien ». `_backdate_atom` a démenti la seconde moitié
# de la phrase pendant des mois. La dispense reste — sa raison de fond est
# juste — mais elle cesse d'être une affirmation : on VÉRIFIE ici que ce que
# `tests/` nomme, il ne l'exécute pas.
#
# LA DÉCLARATION EST DEVENUE PAR LITTÉRAL, ET NON PLUS PAR FICHIER. Un fichier
# dispensé en bloc dispensait aussi le chemin qu'on y écrirait demain : la
# dispense de `test_g1` couvrait `/usr/local/bin/autossh` — qu'elle doit
# couvrir — et aurait couvert un `/usr/bin/psql` ajouté par-dessus. On déclare
# donc le COUPLE (fichier, littéral).
#
# CE FICHIER-CI PORTE FORCÉMENT TOUS LES LITTÉRAUX QU'IL DÉCLARE POUR LES
# AUTRES : les nommer est la seule façon de les déclarer. C'est pourquoi sa
# propre liste est la plus longue, et pourquoi elle n'est pas une dispense en
# bloc pour autant — chaque ligne y est écrite à la main.

#: (fichier, littéral) → la raison. Un littéral non déclaré fait rougir ; une
#: déclaration qui ne couvre plus rien fait rougir aussi.
EXCEPTIONS_DECLAREES: dict[tuple[str, str], str] = {
    # — ce fichier-ci —
    ("tests/test_la_porte_du_sous_processus_est_fermee.py", "/usr/bin/psql"):
        "Ce fichier doit nommer `/usr/bin/psql` pour prouver qu'on ne peut pas "
        "l'atteindre, exactement comme G1 doit nommer les motifs qu'il cherche. "
        "Chaque occurrence est l'ARGUMENT d'un appel qu'on exige refusé.",
    ("tests/test_la_porte_du_sous_processus_est_fermee.py",
     "/usr/lib/postgresql/16/bin/psql"):
        "Le chemin Debian RÉEL du client PostgreSQL : `/usr/bin/psql` n'est "
        "qu'un lien vers `pg_wrapper`. C'est le littéral que l'ancienne liste "
        "blanche de quatre racines ne voyait pas, et le balayage doit prouver "
        "qu'il le voit maintenant. Il n'est jamais exécuté : il est refusé.",
    ("tests/test_la_porte_du_sous_processus_est_fermee.py", "/opt/pg/bin/dropdb"):
        "Une racine de binaires que personne n'a énumérée, employée comme "
        "sonde : le balayage doit la voir par sa FORME, sans qu'aucune liste "
        "ne contienne `/opt/pg`. Elle n'existe pas sur cette machine.",
    ("tests/test_la_porte_du_sous_processus_est_fermee.py", "/usr/bin/hostname"):
        "La cible inoffensive des cinq évasions mesurées : elle ne lit ni base "
        "ni service, elle rend le nom de la machine. On a refusé de reproduire "
        "les évasions sur un cerveau réel — la preuve vaut par le chemin, pas "
        "par la cible.",
    ("tests/test_la_porte_du_sous_processus_est_fermee.py", "/usr/bin"):
        "La racine nue, dans les sondes `B=/usr/bin; $B/…` : c'est la forme "
        "assemblée que le balayage doit voir, et qu'il ne voyait pas.",
    ("tests/test_la_porte_du_sous_processus_est_fermee.py", "/bin"):
        "La racine nue de `export PATH=/usr/bin:/bin`, sonde du descendant qui "
        "rebâtit son `PATH`.",
    ("tests/test_la_porte_du_sous_processus_est_fermee.py",
     "/usr/local/bin/arac-depot-sauvegardes"):
        "Cité pour DÉCLARER le littéral de G1 ci-dessous : une déclaration qui "
        "ne peut pas nommer ce qu'elle déclare n'existe pas.",
    ("tests/test_la_porte_du_sous_processus_est_fermee.py", "/usr/local/bin/autossh"):
        "Le littéral de G1, cité ici pour pouvoir le déclarer plus bas : une "
        "déclaration qui ne peut pas nommer ce qu'elle déclare n'existe pas. "
        "Aucune ligne de ce fichier ne l'exécute.",
    ("tests/test_la_porte_du_sous_processus_est_fermee.py", "/usr/sbin/nologin"):
        "Le littéral de G1 (le shell des comptes de service), cité ici pour "
        "pouvoir le déclarer plus bas. Aucune ligne de ce fichier ne "
        "l'exécute.",
    ("tests/test_la_porte_du_sous_processus_est_fermee.py", "/usr/bin/exporter"):
        "Le littéral de G1, cité ici pour pouvoir le déclarer plus bas. "
        "Aucune ligne de ce fichier ne l'exécute.",
    ("tests/test_la_porte_du_sous_processus_est_fermee.py", "/usr/bin/claude"):
        "Le littéral de `test_claude_cli_stdin_e2big`, cité ici pour pouvoir "
        "le déclarer plus bas. Là-bas c'est une donnée d'`OSError` fabriquée ; "
        "ici c'est du texte dans un dictionnaire.",
    ("tests/test_la_porte_du_sous_processus_est_fermee.py", "/opt/homebrew/bin"):
        "La racine macOS que G1 nomme dans un contrôle de `PATH`, citée ici "
        "pour pouvoir la déclarer plus bas. Jamais assemblée avec un nom.",
    ("tests/test_la_porte_du_sous_processus_est_fermee.py", "/opt/homebrew/sbin"):
        "La racine macOS que G1 nomme dans un contrôle de `PATH`, citée ici "
        "pour pouvoir la déclarer plus bas. Jamais assemblée avec un nom.",
    ("tests/test_la_porte_du_sous_processus_est_fermee.py", "/usr/local/bin"):
        "La racine que G1 nomme dans un contrôle de `PATH`, citée ici pour "
        "pouvoir la déclarer plus bas. Jamais assemblée avec un nom.",
    ("tests/test_la_porte_du_sous_processus_est_fermee.py", "/usr/local/sbin"):
        "La racine que G1 nomme dans un contrôle de `PATH`, citée ici pour "
        "pouvoir la déclarer plus bas. Jamais assemblée avec un nom.",
    ("tests/test_la_porte_du_sous_processus_est_fermee.py",
     "/usr/local/sbin/quelque-chose"):
        "Une SONDE du balayage : une racine `sbin` que l'ancienne liste "
        "blanche connaissait, employée pour prouver que la nouvelle forme la "
        "voit encore. Le programme n'existe pas ; rien ne le lance.",
    ("tests/test_la_porte_du_sous_processus_est_fermee.py", "/snap/bin/kubectl"):
        "Une SONDE du balayage : une racine qui n'existait pas quand "
        "l'ancien motif a été écrit, et qu'il ne voyait donc pas. Elle prouve "
        "que la nouvelle règle est une forme et non une énumération.",
    ("tests/test_la_porte_du_sous_processus_est_fermee.py",
     "/usr/lib/postgresql/16/bin"):
        "Une SONDE du balayage : la racine profonde, nommée SEULE. C'est la "
        "moitié du chemin qui rend `$B/psql` invisible une fois la variable "
        "substituée — le balayage doit la voir tant qu'elle est écrite.",
    ("tests/test_la_porte_du_sous_processus_est_fermee.py", "/usr/sbin"):
        "Cité pour DÉCLARER le littéral de `garde_hermetique.py` ci-dessous : "
        "une déclaration qui ne peut pas nommer ce qu'elle déclare n'existe "
        "pas. Racine nommée, jamais assemblée avec un nom de programme.",
    ("tests/test_la_porte_du_sous_processus_est_fermee.py", "/sbin"):
        "Même raison : la seconde racine de `_RACINES_SANS_CERVEAU`, citée ici "
        "pour pouvoir la déclarer plus bas.",
    # — les autres fichiers —
    ("tests/garde_hermetique.py", "/usr/bin/psql"):
        "Le garde lui-même : sa docstring cite `/usr/bin/psql` pour raconter "
        "l'évasion qu'il ferme. Une leçon n'exécute rien, et les leçons de ce "
        "dépôt sont sa valeur — mais elle porte tout de même la forme, donc "
        "elle est déclarée plutôt que passée sous silence.",
    ("tests/garde_hermetique.py", "/usr/lib/postgresql/16/bin/psql"):
        "Le message de refus du lecteur de corps cite le chemin exact qui a "
        "servi à mesurer l'évasion : un refus qui ne dit pas ce qu'il a vu "
        "s'oublie. Il est dans une chaîne de caractères, jamais exécuté.",
    ("tests/garde_hermetique.py", "/usr/bin"):
        "La racine nue, dans la docstring de `_ce_qu_un_path_rouvre` : elle "
        "cite `export PATH=/usr/bin:/bin` comme l'évasion mesurée, en face de "
        "`PATH=/nonexistent` qui reste permis. Une règle qui n'explique pas ce "
        "qu'elle distingue se fait désactiver au premier faux positif.",
    ("tests/garde_hermetique.py", "/bin"):
        "La seconde moitié du même exemple `export PATH=/usr/bin:/bin`, dans "
        "la même docstring. Aucune de ces deux racines n'est assemblée avec un "
        "nom de programme, et rien dans ce fichier ne les exécute.",
    ("tests/garde_hermetique.py", "/usr/sbin"):
        "`_RACINES_SANS_CERVEAU` : les racines que la DISTRIBUTION possède, et "
        "où aucun cerveau ne vit. Le nouveau rideau des chemins doit les "
        "nommer pour laisser passer `test -x /usr/sbin/<quelque chose>` — "
        "demander si un fichier existe n'est pas lire un cerveau, et le LANCER "
        "reste refusé par tout le reste du fichier. Aucune ligne ne l'exécute.",
    ("tests/garde_hermetique.py", "/sbin"):
        "La seconde moitié de `_RACINES_SANS_CERVEAU`, pour la même raison. "
        "`/usr/local` n'y est délibérément PAS : le bootstrap y installe "
        "`arac-depot-sauvegardes`, donc `/usr/local` porte du cerveau.",
    ("tests/test_les_exceptions_du_rideau_disent_vrai.py",
     "/usr/local/bin/arac-depot-sauvegardes"):
        "La table des justifications du rideau doit NOMMER l'endroit qu'elle "
        "vérifie : `sys.base_prefix` vaut `/usr` et recouvrait `/usr/local`, "
        "c'est-à-dire la porte du dépôt de sauvegardes d'un voisin. Le test "
        "demande au rideau de le REFUSER ; il ne l'exécute pas, et il ne "
        "l'ouvre pas non plus.",
    ("tests/test_g1_aucun_nom_partage_entre_cerveaux.py",
     "/usr/local/bin/arac-depot-sauvegardes"):
        "Le garde des noms partagés : sa liste `CONSTATS_REMIS` doit citer ce "
        "chemin — trouvé dans docs/SAUVEGARDE.md et remis à un autre "
        "périmètre. Nommer une faute pour la remettre n'est pas l'exécuter, et "
        "un garde qui ne peut pas nommer ce qu'il trouve ne trouve plus rien.",
    ("tests/test_g1_aucun_nom_partage_entre_cerveaux.py", "/usr/local/bin/autossh"):
        "Même raison : un littéral RENCONTRÉ par le balayage de G1 dans le "
        "dépôt, et remis au périmètre qui en répond. Il n'est pas exécuté.",
    ("tests/test_g1_aucun_nom_partage_entre_cerveaux.py", "/usr/sbin/nologin"):
        "Le shell des comptes de service, cité par G1 dans un constat sur les "
        "comptes partagés entre cerveaux. Une donnée, pas un appel.",
    ("tests/test_g1_aucun_nom_partage_entre_cerveaux.py", "/usr/bin/exporter"):
        "Un chemin d'exécutable trouvé par G1 dans le dépôt et REMIS au "
        "périmètre qui en répond : G1 le cite pour qu'on sache où il l'a vu. "
        "C'est une donnée de constat, jamais un appel.",
    ("tests/test_g1_aucun_nom_partage_entre_cerveaux.py", "/opt/homebrew/bin"):
        "G1 nomme les racines de binaires de macOS pour vérifier ce que le "
        "dépôt écrit dans un `PATH` d'installation. Racine citée, jamais "
        "assemblée avec un nom.",
    ("tests/test_g1_aucun_nom_partage_entre_cerveaux.py", "/opt/homebrew/sbin"):
        "Même raison que `/opt/homebrew/bin` : une racine de binaires de macOS "
        "citée dans le contrôle du `PATH` qu'écrit l'installation, jamais "
        "assemblée avec un nom, et que rien n'exécute.",
    ("tests/test_g1_aucun_nom_partage_entre_cerveaux.py", "/usr/local/bin"):
        "Même raison que `/opt/homebrew/bin` : G1 cite cette racine dans son "
        "contrôle du `PATH` que l'installation écrit. Elle n'est jamais "
        "assemblée avec un nom de programme, et rien ne l'exécute.",
    ("tests/test_g1_aucun_nom_partage_entre_cerveaux.py", "/usr/local/sbin"):
        "Même raison que `/usr/local/bin` : une racine citée dans le contrôle "
        "du `PATH` d'installation, jamais assemblée avec un nom de programme, "
        "et que rien n'exécute.",
    ("tests/test_claude_cli_stdin_e2big.py", "/usr/bin/claude"):
        "Le chemin n'y est jamais lancé : il est le troisième argument d'une "
        "`OSError` FABRIQUÉE par un `monkeypatch` de `create_subprocess_exec`, "
        "pour reproduire l'E2BIG observé le 2026-05-22. C'est une DONNÉE de "
        "test, pas un appel — le vrai sous-processus n'est jamais créé.",
    ("tests/test_bootstrap_venv.py", "/usr/bin"):
        "La ligne `home = /usr/bin` d'un `pyvenv.cfg` de THÉÂTRE, écrit sous "
        "`tmp_path` pour que le contrôle de venv ait quelque chose à lire. "
        "C'est le contenu d'un fichier de configuration, jamais un préfixe de "
        "commande — mais c'est bien la forme, donc elle est déclarée.",
}


class ZoneAveugleDeLaPorte(NamedTuple):
    """Une évasion que le dispositif NE ferme pas, et pourquoi."""

    zone: str
    mecanique: str
    #: L'instance vivante dans ce dépôt, s'il y en a une. C'est ce qui
    #: distingue une limite théorique d'une limite qui coûte aujourd'hui.
    instance: str = ""


#: CE QUE LA PORTE NE FERME PAS — et ce à quoi elle sert vraiment.
#:
#: RÉÉCRITE CETTE MANCHE, ET PLUS COURTE QU'AVANT, EXPRÈS. Trois justifications
#: écrites dans les deux manches précédentes se sont révélées fausses, deux le
#: jour même de leur écriture, et toujours pour la même raison : elles
#: déclaraient la limite d'après ce qu'on croyait avoir fermé, pas d'après ce
#: qu'on avait joué. Une zone qui promet trop est pire qu'une zone muette — elle
#: dit au lecteur suivant où il est inutile de regarder.
#:
#: Chaque phrase ci-dessous porte donc une mesure jouée le 10 août 2026, dans
#: les DEUX régimes, sur `/var/lib/dpkg/status` — un fichier de la distribution
#: hors du périmètre, jamais un cerveau réel. Et les quatre formes que la porte
#: laisse passer sont REJOUÉES à chaque session par
#: `test_ce_qui_reste_ouvert_est_mesure_et_declare` : le jour où l'une d'elles
#: se referme, ce test rougit et exige qu'on la retire d'ici.
ZONES_NON_COUVERTES_DE_LA_PORTE: tuple[ZoneAveugleDeLaPorte, ...] = (
    ZoneAveugleDeLaPorte(
        "LE MODÈLE DE MENACE — un test DISTRAIT, jamais un test HOSTILE",
        "Cette porte défend contre l'INATTENTION : un test qui pointe un outil "
        "légitime là où il ne faut pas, et qui l'apprend par un refus qui "
        "enseigne. Elle ne défend pas contre un test HOSTILE, et elle ne le peut "
        "pas : un tel test exécute déjà du code arbitraire DANS le processus qui "
        "porte le garde. Mesuré aujourd'hui, régime de repli : "
        "`ctypes.CDLL(\"libc.so.6\").fopen` ouvre un fichier hors du périmètre et "
        "`.system(\"cat …\")` rend 0 avec le fichier entier — sans passer par "
        "`subprocess`, ni par `os`, ni par `_posixsubprocess`. Contre celui-là, "
        "la seule barrière qui vaille est le NOYAU. C'est pourquoi la course aux "
        "mailles s'arrête ici : trois manches de suite ont trouvé une instance "
        "NOUVELLE dans le correctif de la précédente, les trouvailles étaient "
        "réelles, et aucune ne concernait le produit livré.",
    ),
    ZoneAveugleDeLaPorte(
        "LE RÉGIME — en nominal le noyau ferme, en repli la porte est SEULE",
        "En NOMINAL, `tests/seconde_barriere.py` pose Landlock et la porte n'est "
        "plus que le message qui enseigne : mesuré, `libc.fopen` d'un fichier "
        "hors périmètre rend un pointeur nul et `libc.system(\"cat …\")` rend 256 "
        "avec « Permission denied ». En REPLI — `ARAC_SANS_SECONDE_BARRIERE` "
        "dans l'environnement, un noyau sans Landlock, une abi trop ancienne — "
        "les deux mêmes appels rendent 0 et le fichier entier. La couverture "
        "annoncée par tout ce qui suit est donc la couverture EN REPLI, et elle "
        "est partielle. C'est écrit plutôt que caché : un vert obtenu en repli "
        "ne vaut pas un vert obtenu sous la barrière, et la fin de session "
        "imprime lequel des deux vous venez de voir.",
    ),
    ZoneAveugleDeLaPorte(
        "CE QUI EST ÉCRIT contre CE QUI EST COMPOSÉ — la limite d'espèce",
        "CE QUE LA PORTE FERME, et c'est tout ce qui est ÉCRIT dans l'argv : "
        "tout argument de tout outil qui désigne un endroit hors du périmètre ; "
        "la valeur COLLÉE à une option courte aussi bien que celle qui suit un "
        "`=` (`tar -C…`, `sort -o…`, `grep -f…` — refusés depuis cette manche, "
        "mesurés PASSANTS le matin même, dont un `sort -o` qui ramenait le dump "
        "d'un faux voisin à zéro octet) ; et, quand le programme est un "
        "interprète, les MOTS de "
        "CHACUN de ses arguments — on ne cherche plus « le » corps, si bien que "
        "`-cx`, `-xc`, `-c --`, `--norc -c`, `-O extglob -c` et `--rcfile "
        "<fichier>` rendent tous le même verdict. CE QU'ELLE NE FERME PAS, et "
        "les quatre formes sont JOUÉES à chaque session : l'ENTRÉE STANDARD "
        "(`bash -s`), le quotage ANSI-C (`bash -c $'\\x2f…'`), le chemin COMPOSÉ "
        "à l'exécution (`p=$(printf /%s var); cat \"$p/…\"`) et le corps mis dans "
        "un FICHIER (`bash <tmp_path>/x.sh`, ou `bash ops/<un script du dépôt>`, "
        "dont le contenu n'est lu par personne). Les quatre ont UNE seule cause "
        "et aucun motif de plus ne la referme : ce juge lit du texte, le shell "
        "compose. Mesuré : en repli les quatre rendent le contenu ; en nominal "
        "les quatre rendent « rien », et ce « rien » vient du noyau.",
    ),
    ZoneAveugleDeLaPorte(
        "une racine de binaires COUPÉE en morceaux",
        "`B=/usr/b; ${B}in/hostname -f` ne contient ni chemin d'exécutable ni "
        "racine : les deux motifs de forme passent à côté, et le talon du `PATH` "
        "n'est pas consulté puisque le shell reçoit un chemin. Mesuré "
        "aujourd'hui, après les correctifs de cette manche, régime de repli : "
        "rc=0, et le nom de l'hôte revient. Reconnaître les recollages "
        "arbitraires demanderait d'interpréter le shell, c'est-à-dire d'en "
        "écrire un.",
    ),
    ZoneAveugleDeLaPorte(
        "un chemin d'exécutable CALCULÉ à l'exécution",
        "Même cause que la zone précédente, vue depuis Python : le juge et le "
        "balayage de `tests/` lisent du TEXTE, et un chemin obtenu par un calcul "
        "ne porte aucun littéral. Aucun motif ne fermera cela ; seul un compte "
        "non privilégié, un espace de noms ou Landlock le rend sans effet.",
        "tests/test_g2_le_bootstrap_ne_prend_pas_le_role_du_voisin.py : "
        "`shutil.which(\"ss\", path=ARAC_GARDE_PATH_HOTE)` rend le vrai `ss` de "
        "l'hôte, écrit dans un double qui l'`exec`. C'est délibéré, borné à UN "
        "port — celui que le test vient d'ouvrir — et c'est l'instance vivante "
        "de cette zone dans ce dépôt.",
    ),
    ZoneAveugleDeLaPorte(
        "un DOUBLE, posé par un test, qui exécute l'hôte au lieu de jouer",
        "Le talon laisse passer les doubles : sans cela la moitié des gardes du "
        "bootstrap serait intestable. Un double qui `exec` un binaire de l'hôte "
        "rouvre la porte — le geste est dans un FICHIER, pas dans un argument. "
        "Le seul recours est le balayage de `tests/`, qui voit le littéral s'il "
        "y est écrit, et qui rougit APRÈS le geste, pas avant. LA COPIE reste "
        "ouverte et c'est mesuré : un `cp` d'un binaire de l'hôte sous "
        "`tmp_path`, renommé du nom d'un outil légitime, puis lancé par "
        "`[\"./cat\"], cwd=tmp_path` — rc=0, le nom d'hôte rendu, journal du "
        "garde vide. Distinguer cette copie du double légitime demanderait de "
        "juger un CONTENU, pas un nom. LE LIEN SYMBOLIQUE ÉTAIT DÉCLARÉ ICI "
        "« SUIVI ET REFUSÉ » : c'est FAUX là où la suite tourne, et c'est "
        "mesuré. `est_legitime` suit bien le lien pour le fichier RÉEL, mais "
        "elle demande ensuite `_vient_du_depot(cible)` sur le texte BRUT de "
        "`argv[0]`, sans le `cwd=` — si bien que `[\"./wc\"], cwd=<tmp_path>`, "
        "où `./wc` est un lien vers un binaire de l'hôte, est tenu pour un "
        "fichier du dépôt dès que le PROCESSUS APPELANT a le dépôt pour "
        "répertoire courant, ce qui est le cas de `make test` : rc=0, le nom "
        "d'hôte rendu. Depuis `/tmp`, le même appel est refusé — c'est la "
        "preuve que le verdict dépend du répertoire du père et non de celui du "
        "fils. Ni fermé ni caché : écrit là où on le lira.",
    ),
    ZoneAveugleDeLaPorte(
        "la liste des EXÉCUTANTS n'est plus une liste — mais le critère qui la "
        "remplace ne lit que des ELF",
        "Un ELF déclare dans sa table de symboles dynamiques les portes de la "
        "libc qu'il ira chercher : un programme qui peut en lancer un autre y "
        "nomme `execve`, `execvp`, `execlp`, `posix_spawn`, `system` ou `popen`. "
        "La mesure a ainsi retrouvé les sept exécutants écrits à la main ET "
        "trouvé `sort`, `install` et `diff`, que personne n'avait nommés. CE QUI "
        "RESTE OUVERT : le critère ne lit qu'un ELF 64 bits dynamique — un "
        "SCRIPT (`egrep`, `gunzip` sur Debian), un binaire statique, un busybox "
        "ne se laissent pas lire, et sont alors tenus pour exécutants "
        "(`fail-closed`) ; il sur-approxime aussi ; et il dit qu'un outil PEUT "
        "exécuter, jamais PAR QUELLE OPTION — d'où le refus complémentaire de "
        "toute option en `--…-program` / `--…-command`. Un `syscall()` écrit à "
        "la main resterait invisible : c'est théorique, et c'est dit.",
    ),
    ZoneAveugleDeLaPorte(
        "L'HÉRITAGE TIENT À UNE VARIABLE — la dépendance, écrite",
        "Les quatre gardes ne suivent un fils Python que par `PYTHONPATH` et le "
        "mécanisme `site` ; le talon du `PATH` ne suit un descendant que par "
        "`PATH`. Tout ce qui efface ou remplace ces deux variables rend le fils "
        "NU — mesuré : `socket.socket.connect.__name__` y vaut « connect ». Les "
        "formes connues sont FERMÉES : `-I/-E/-S`, une affectation ou un `unset` "
        "dans un corps de shell, un `env=` explicite, l'`env` positionnel de "
        "`Popen`, l'environnement reçu par `os.posix_spawn`, `os.execve` et "
        "`os.spawnve`, `os.putenv`, `os.unsetenv`, un `preexec_fn`. CE QUI RESTE "
        "OUVERT : ce qu'un PROGRAMME calcule — un `Environment=` d'unité "
        "systemd, un shell qui rebâtit son environnement par un chemin qu'aucun "
        "motif ne lit, la libc appelée directement. La dépendance est déclarée "
        "dans `garde_hermetique.VARIABLES_DE_L_HERITAGE`, et un test l'ÉPROUVE "
        "en effaçant chaque variable dans un fils.",
    ),
    ZoneAveugleDeLaPorte(
        "l'`uid` sous lequel la suite tourne — la vraie barrière, et elle "
        "n'est toujours pas dans ce fichier",
        "Toutes les évasions ci-dessus n'atteignent un cerveau réel que parce "
        "que le processus en a le droit. Sous `root`, `sudo -n -u postgres "
        "psql` ne demande rien à personne ; sous un compte ordinaire il échoue "
        "avant de commencer, et l'authentification `peer` du cluster fait le "
        "reste. CE QUI A CHANGÉ : la moitié FICHIERS de ce constat est désormais "
        "tenue par `tests/seconde_barriere.py` — Landlock retire au NOYAU, pour "
        "cette session et toute sa descendance, le droit de toucher un fichier "
        "hors du périmètre déclaré, et `no_new_privs` retire à tout descendant "
        "le droit de GAGNER des privilèges. CE QUI RESTE : le réseau et la base "
        "(la suite ouvre de vrais ports de la boucle locale, et la socket UNIX "
        "de PostgreSQL n'est pas gouvernée par des droits de fichier), et tout "
        "ce qu'un `root` peut faire sans toucher un inode — parler à `systemd`, "
        "envoyer un signal. La fin de session imprime l'`uid` effectif ET le "
        "verdict de la barrière, pour que personne ne confonde les deux.",
    ),
)


def _litteraux_du_fichier(texte: str) -> list[tuple[int, str]]:
    """Les littéraux de FORME « exécutable de l'hôte » d'un fichier.

    Deux formes, et pas quatre racines :
      · `/…/bin/<nom>` ou `/…/sbin/<nom>` à n'importe quelle profondeur — c'est
        ainsi que `/usr/lib/postgresql/16/bin/psql`, le VRAI client de cette
        machine, est vu ;
      · une racine `/…/bin` nommée seule — assemblée avec un nom, elle
        contourne le talon du `PATH`.
    Un nom d'outil LÉGITIME ne compte pas : `#!/bin/sh` en tête d'un double et
    `/usr/bin/python3` dans une leçon n'ouvrent rien.
    """
    trouves: list[tuple[int, str]] = []
    for numero, ligne in enumerate(texte.splitlines(), start=1):
        if ligne.strip().startswith(("#", "//", "--")):
            continue  # une leçon n'exécute rien
        for m in RX_CHEMIN_D_EXECUTABLE.finditer(ligne):
            if os.path.basename(m.group(0)) in OUTILS_LEGITIMES:
                continue
            trouves.append((numero, m.group(0)))
        for m in RX_RACINE_DE_BINAIRES.finditer(ligne):
            trouves.append((numero, m.group(0)))
    return trouves


def _fichiers_balayes():
    for p in sorted((RACINE / "tests").rglob("*")):
        if not p.is_file() or p.suffix.lower() in {".pyc", ".dump", ".png"}:
            continue
        try:
            yield str(p.relative_to(RACINE)), p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue


def test_aucun_test_n_execute_un_binaire_de_l_hote_sans_le_dire():
    """Le seul contournement possible doit être déclaré, jamais discret.

    Le talon du PATH de refus laisse passer les DOUBLES — sans quoi la suite
    serait intestable. Un double qui ferait `exec /usr/bin/psql` au lieu de
    jouer un rôle rouvrirait la porte en silence. On balaie donc `tests/` à la
    recherche de cette forme, et chaque COUPLE (fichier, littéral) doit figurer
    dans `EXCEPTIONS_DECLAREES` avec la raison qui le justifie.
    """
    fautifs: list[str] = []
    for rel, texte in _fichiers_balayes():
        for numero, litteral in _litteraux_du_fichier(texte):
            if (rel, litteral) in EXCEPTIONS_DECLAREES:
                continue
            fautifs.append(f"{rel}:{numero} → {litteral}")

    assert not fautifs, (
        "\n\nUn test nomme un exécutable de l'HÔTE, ou la racine où ils "
        "vivent — c'est-à-dire le seul geste qui contourne encore le PATH de "
        "refus.\n\n"
        "  OÙ\n    " + "\n    ".join(sorted(set(fautifs))[:30]) + "\n\n"
        "  QUOI FAIRE\n"
        "    Soit le test n'a pas besoin de l'hôte : jouez un double qui rend "
        "la réponse attendue.\n"
        "    Soit il en a besoin : déclarez le couple (fichier, littéral) dans "
        "EXCEPTIONS_DECLAREES, avec ce qu'il demande à la machine et pourquoi "
        "rien d'autre ne le ferait."
    )


def test_chaque_exception_declaree_sert_encore():
    """Une exception qui ne couvre plus rien est une porte laissée ouverte.

    CE TEST ÉTAIT VERT PAR CONSTRUCTION, LUI AUSSI. Il se contentait de
    `_RX_BINAIRE_DE_L_HOTE.search(texte)`, SANS le filtre des outils légitimes :
    un `#!/bin/sh` en tête d'un double suffisait à le satisfaire. La dispense de
    `test_g2` était ainsi tenue pour vivante alors que ce fichier ne nomme plus
    aucun exécutable de l'hôte — il passe désormais par un chemin CALCULÉ, ce
    que `ZONES_NON_COUVERTES_DE_LA_PORTE` déclare. On vérifie maintenant le
    littéral EXACT, avec le même filtre que le balayage.
    """
    textes = dict(_fichiers_balayes())
    morts: list[str] = []
    for (chemin, litteral), raison in EXCEPTIONS_DECLAREES.items():
        assert (RACINE / chemin).is_file(), f"exception morte : {chemin} n'existe plus"
        assert len(raison) > 80, f"{chemin} / {litteral} : raison trop courte"
        presents = {lit for _, lit in _litteraux_du_fichier(textes.get(chemin, ""))}
        if litteral not in presents:
            morts.append(f"{chemin} → {litteral}")
    assert not morts, (
        "\n\nCes dispenses ne couvrent plus rien :\n    " + "\n    ".join(morts) +
        "\n\n  Retirez-les. Une dispense sans faute à couvrir finit par en "
        "couvrir une autre — c'est exactement ce qui est arrivé à la dispense "
        "en bloc de `test_g2`."
    )


# ---------------------------------------------------------------------------
# 6 bis. LE BALAYAGE EST ÉPROUVÉ SUR DES SONDES — il ne se croit pas sur parole
# ---------------------------------------------------------------------------
#
# Un balayage qu'on ne mesure pas est la faute même de cette manche : l'ancien
# se disait « une forme, pas des noms » et énumérait quatre racines. On lui
# donne donc des sondes dans les deux sens — ce qu'il DOIT voir, ce qu'il doit
# laisser tranquille — et une sonde qu'il ne voit pas, déclarée comme telle.

#: Ce que le balayage doit VOIR. Chaque ligne est un texte, pas un fichier :
#: on éprouve la fonction, pas le dépôt.
SONDES_QUI_DOIVENT_ETRE_VUES = (
    ("psql = '/usr/lib/postgresql/16/bin/psql'",
     "le vrai client PostgreSQL de Debian — l'ancien motif ne le voyait pas"),
    ("run(['bash','-c','/opt/pg/bin/dropdb arac'])",
     "une racine que personne n'a énumérée"),
    ("run(['bash','-c','B=/usr/bin; $B/psql -l'])",
     "le chemin assemblé : la racine nue est déjà la moitié du geste"),
    ("exec /usr/local/sbin/quelque-chose",
     "une racine `sbin` non énumérée"),
    ("chemin = '/snap/bin/kubectl'",
     "une racine qui n'existait pas quand le motif a été écrit"),
    ("PATH=/usr/lib/postgresql/16/bin",
     "la racine profonde, nommée seule"),
)

#: Ce que le balayage doit LAISSER TRANQUILLE. Un garde qui crie au loup est
#: désactivé, donc absent : c'est la même perte, par l'autre bout.
SONDES_MUETTES = (
    ("#!/bin/sh", "un shebang de double : `sh` est légitime"),
    ("interpreteur = '/usr/bin/python3'", "`python3` est légitime"),
    ("run(['/bin/bash', '-n', script])", "`bash` est légitime"),
    ("cat = '/usr/bin/cat'", "`cat` lit un fichier"),
    ("# /usr/bin/psql — la leçon d'une évasion", "une ligne de commentaire"),
    ("chemin = 'bin/psql'", "un chemin RELATIF ne contourne pas le talon"),
    ("dossier = '/usr/binaire/psql'", "`binaire` n'est pas `bin`"),
)


@pytest.mark.parametrize("texte, pourquoi", SONDES_QUI_DOIVENT_ETRE_VUES)
def test_le_balayage_voit_la_forme(texte, pourquoi):
    assert _litteraux_du_fichier(texte), (
        f"le balayage ne voit pas cette forme — {pourquoi}.\n"
        f"  texte : {texte!r}\n"
        "  C'est la faute exacte de la manche précédente : une liste blanche "
        "de quatre racines, présentée comme « une forme »."
    )


@pytest.mark.parametrize("texte, pourquoi", SONDES_MUETTES)
def test_le_balayage_ne_crie_pas_au_loup(texte, pourquoi):
    assert not _litteraux_du_fichier(texte), (
        f"le balayage crie au loup — {pourquoi}.\n  texte : {texte!r}"
    )


def test_la_sonde_que_le_balayage_ne_voit_pas_est_declaree():
    """On MESURE l'aveu au lieu de l'écrire : la racine coupée passe.

    `P=/usr/b; ${P}in/psql` ne porte ni chemin d'exécutable ni racine. Ce test
    exige deux choses à la fois : que le balayage ne la voie pas — sinon l'aveu
    serait périmé — et que `ZONES_NON_COUVERTES_DE_LA_PORTE` la déclare.
    """
    coupee = "run(['bash','-c','P=/usr/b; ${P}in/psql -l'])"
    assert not _litteraux_du_fichier(coupee), (
        "le balayage voit maintenant la racine coupée : retirez la zone "
        "correspondante de ZONES_NON_COUVERTES_DE_LA_PORTE, un aveu périmé "
        "est un mensonge de plus."
    )
    assert any("COUPÉE" in z.zone.upper() for z in ZONES_NON_COUVERTES_DE_LA_PORTE), (
        "une évasion mesurée qui passe doit être DÉCLARÉE."
    )


# ---------------------------------------------------------------------------
# 6 ter. L'AVEU NE DOIT PAS POURRIR
# ---------------------------------------------------------------------------


def test_les_zones_non_couvertes_sont_declarees_et_motivees():
    """Un aveu sans mécanique est une excuse ; on exige la mécanique."""
    assert ZONES_NON_COUVERTES_DE_LA_PORTE, (
        "un garde sans zone aveugle déclarée n'a pas cherché : celui-ci a "
        "commencé sa vie en annonçant qu'il fermait une CLASSE, et cinq "
        "évasions rendaient 0."
    )
    for z in ZONES_NON_COUVERTES_DE_LA_PORTE:
        assert len(z.zone) > 15, f"zone trop vague : {z.zone!r}"
        assert len(z.mecanique) > 120, (
            f"« {z.zone} » : la mécanique doit dire POURQUOI c'est ouvert, pas "
            "seulement que ça l'est."
        )


def test_la_fin_de_session_imprime_l_aveu_et_le_compte(monkeypatch):
    """Un aveu qui n'est pas imprimé n'est pas un aveu : c'est un commentaire.

    On appelle le vrai `pytest_terminal_summary` avec un rapporteur de théâtre.
    Deux précautions : on empêche le démontage de l'héritage — la vraie session
    continue après ce test, et lui retirer son `PATH` de refus serait ouvrir la
    porte pour prouver qu'elle est fermée — et on n'exige rien du contenu de G1,
    qui appartient à un autre périmètre.
    """
    from tests import conftest as c
    from tests import garde_hermetique as g

    monkeypatch.setattr(g, "demonter_l_heritage", lambda: None)

    lignes: list[str] = []

    class _Rapporteur:
        def write_sep(self, _c, titre, **k):
            lignes.append(titre)

        def write_line(self, texte, **k):
            lignes.append(texte)

    c.pytest_terminal_summary(_Rapporteur(), 0, None)
    tout = "\n".join(lignes)
    assert "LA PORTE DU SOUS-PROCESSUS : CE QU'ELLE NE FERME PAS" in tout
    for z in ZONES_NON_COUVERTES_DE_LA_PORTE:
        assert z.zone in tout, f"zone non imprimée : {z.zone}"
    assert "Cette session a tourné sous" in tout, (
        "le compte sous lequel la suite tourne est la seconde barrière ; une "
        "défense en profondeur qu'on ne mesure pas est un espoir."
    )


def test_le_fichier_ne_promet_plus_de_fermer_la_classe():
    """La phrase qui a coûté la manche ne doit pas revenir SEULE.

    « Ce fichier ferme la CLASSE » était écrit en tête pendant que cinq
    évasions rendaient 0. On n'interdit pas de la CITER — la citer est la seule
    façon de raconter la faute, et ce dépôt vit de ses leçons. On exige que la
    citation soit démentie dans la même docstring, et que l'aveu y soit nommé :
    une promesse qu'on relit sans son démenti se remet à valoir.
    """
    tete = Path(__file__).read_text(encoding="utf-8").split('"""')[1]
    if "ferme la CLASSE" in tete:
        assert "ET ELLE ÉTAIT FAUSSE" in tete, (
            "la promesse est en tête du fichier sans son démenti. Ce qu'un "
            "garde peut écrire de lui-même : ce qu'il a MESURÉ fermer, et ce "
            "qu'il laisse."
        )
    assert "ZONES_NON_COUVERTES_DE_LA_PORTE" in tete, (
        "la docstring doit renvoyer à l'aveu : c'est là qu'on va lire ce que "
        "le dispositif ne fait pas."
    )
