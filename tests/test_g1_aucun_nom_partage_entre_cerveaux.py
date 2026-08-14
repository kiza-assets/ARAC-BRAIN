"""G1 — AUCUN NOM NE DOIT ÊTRE PARTAGÉ ENTRE DEUX CERVEAUX.

CE QUE CE GARDE EMPÊCHE, ET POURQUOI IL EXISTE
===============================================

Un incident réel, sur la machine de l'auteur. Une installation d'ESSAI du
framework, lancée à côté d'un cerveau de PRODUCTION, a détruit ce dernier.
Trois causes, toutes des défauts du produit — aucune n'était une faute
d'exploitation :

1. LES RÔLES. `arac_app`, `arac_agent`, `arac_readonly`, `arac_admin`,
   `arac_backup` étaient nommés en dur. Or un rôle PostgreSQL est GLOBAL AU
   CLUSTER, pas propre à une base : `arac_app` du cerveau A **est** `arac_app`
   du cerveau B. Le second bootstrap a fait `ALTER ROLE … PASSWORD` et écrasé
   les cinq secrets du premier. Sans erreur, sans trace, et sans effet visible
   avant le redémarrage suivant des services de production.

2. LES PORTS. Une unité d'essai a lié le 8000, celui de l'API de production.
   Celle-ci a redémarré 35 fois sur « [Errno 98] address already in use »
   pendant que `/healthz` répondait 200 — servi par l'usurpateur. Le
   diagnostic MENTAIT : la panne se présentait comme une santé.

3. LES DOSSIERS. `/var/backups/arac`, `/var/log/arac`, et le préfixe de dump
   `arac-*.dump` étaient communs. La rotation d'un cerveau supprimait les
   dumps de l'autre.

Le point commun des trois : un NOM que deux cerveaux se disputent sans le
savoir. Ce garde échoue si un tel nom réapparaît en dur au lieu d'être dérivé
de l'identité du cerveau (`config/brain.toml`).

CE QUE « EN DUR » VEUT DIRE ICI
================================

On ne balaie PAS les commentaires. Un commentaire qui raconte l'incident en
nommant `arac_app` est une leçon, et les leçons de ce dépôt sont sa valeur ;
un `GRANT … TO arac_app` est un défaut. La différence n'est pas de style,
elle est de nature : l'un s'exécute, l'autre s'enseigne.

On extrait donc, de chaque fichier, ce qui S'EXÉCUTE :
  · Python — l'arbre syntaxique, docstrings retirées (les commentaires
    n'y figurent déjà pas) ;
  · shell / TOML / env / Makefile — les lignes dont le premier caractère
    utile n'est ni `#` (commentaire) ni `--` (commentaire SQL, dans les
    documents en ligne).

Une chaîne de caractères Python EST du code exécuté : c'est précisément dans
`op.execute("GRANT … TO arac_app")` que le défaut vivait.

CE GARDE NE CHERCHE PLUS UN NOM DE PRODUIT — IL CHERCHE UNE NATURE
==================================================================

Il a été élargi trois fois, et trois fois de la même façon : en ajoutant ce
qui manquait. De quatre dossiers balayés à tout le dépôt ; d'une liste blanche
de suffixes à tous les fichiers lisibles ; de six motifs à huit ; puis de huit
noms à « des formes ». La troisième fois, il a écrit ici, en capitales, qu'il
décrivait désormais la FORME et qu'« un défaut d'une famille neuve est vu le
jour où il apparaît ».

C'ÉTAIT FAUX, ET ÇA A ÉTÉ MESURÉ. Trente-huit ressources partagées, couvrant
onze familles, ont été posées devant lui : il en a vu sept, dont six par
accident. Cinq de ses six motifs exigeaient, quelque part, la sous-chaîne
littérale « arac ». Il ne reconnaissait pas une RESSOURCE ; il reconnaissait un
NOM DE PRODUIT. Un compte système, une zone mémoire nginx, un port autre que
deux, un slot de réplication, une base en position d'argument : invisibles.

La question n'est donc plus « ce nom contient-il arac ? ». Elle est :

    ce littéral occupe-t-il la PLACE d'une ressource qui n'existe qu'en un
    seul exemplaire sur la machine — un compte, un rôle, une base, un objet
    global au cluster, un port, une unité, une étiquette launchd, un chemin,
    un espace de noms de démon partagé — et si oui, est-il DÉRIVÉ de
    l'identité du cerveau ?

`useradd cortex` est vu comme `useradd arac`. `/var/lib/cortex` est vu comme
`/var/lib/arac`. Le tri se fait par INVERSION, comme le garde de processus l'a
fait avant lui : on énumère ce que la DISTRIBUTION fournit, et tout le reste
est présumé nôtre, donc disputé. Une liste du légitime échoue à voix haute ;
une liste des fautes échoue en silence.

ET LE GARDE S'ÉPROUVE LUI-MÊME. Trente sondes inventent des ressources qu'il
n'a jamais rencontrées et exigent qu'il les voie ; quatorze autres exigent
qu'il se taise. Un motif qui ne correspond plus à rien et un motif qui n'existe
pas rendent le même vert : c'est ce test-là, et lui seul, qui les distingue.

CE QU'IL NE COUVRE PAS, IL LE DIT
==================================

`ZONES_NON_COUVERTES` nomme neuf zones aveugles, leur raison mécanique et, pour
sept d'entre elles, un exemple réel du dépôt qui reste à corriger. Un garde qui
ment sur sa couverture est pire qu'un garde absent : il donne confiance, et la
confiance est ce qui empêche de regarder.

LES DISPENSES, ET LES REMISES
=============================

Chaque dispense porte sa raison, et un second test échoue si une dispense ne
couvre plus aucune faute — une dispense morte est une porte laissée ouverte,
et personne ne le sait.

Une REMISE (`CONSTATS_REMIS`) n'est pas une dispense. Une dispense dit « ceci
est légitime ». Une remise dit « ceci est une faute, hors du périmètre de cette
manche, et voici son propriétaire ». Elle est imprimée en fin de session, pour
qu'un vert ne se lise jamais comme « il n'y a rien à faire ».
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# LA ZONE BALAYÉE — TOUT LE DÉPÔT
# ---------------------------------------------------------------------------
#
# CE GARDE A DÉJÀ ÉTÉ AVEUGLE, ET VOICI COMMENT.
#
# Il ne balayait que quatre dossiers (`bootstrap`, `ops`, `db/alembic/versions`,
# `deploy`) et n'acceptait qu'une LISTE BLANCHE de suffixes :
#
#     SUFFIXES = {".py", ".sh", ".toml", ".template", ".conf", ".example", ".sql", ""}
#
# Deux extensions manquaient à cette liste : `.modele` et `.exemple` — c'est-à-
# dire, très exactement, celles des gabarits de `deploy/`. Le dossier `deploy`
# était donc déclaré balayé et ne rendait qu'UN fichier sur huit. Le garde
# affichait 74 fichiers vus et se croyait complet ; `mac/`, `control_center/`,
# `app/`, `agents/`, `db/migrations/` et la documentation n'existaient pas
# pour lui. Le défaut avait été chassé du bootstrap ; il vivait tranquillement
# partout où le garde ne regardait pas.
#
# LA LEÇON N'EST PAS « J'AI OUBLIÉ DEUX SUFFIXES ».
# Elle est : UNE LISTE BLANCHE OUBLIE. C'est sa nature. Chaque nouveau type de
# fichier posé dans ce dépôt est invisible par défaut, et personne ne s'en
# aperçoit — l'absence de faute et l'absence de regard se ressemblent
# parfaitement dans un rapport vert.
#
# On INVERSE donc : le garde balaie TOUT le dépôt, et ne rejette que ce qu'il
# ne peut pas lire (binaires) ou ce qui n'est pas du dépôt (exemptions
# nommées ci-dessous). Un fichier d'un type inédit est balayé le jour où il
# apparaît, sans que personne n'ait à y penser.


@dataclass(frozen=True)
class Exemption:
    """Un chemin que le garde ne balaie pas, et la raison qui l'en dispense."""
    chemin: str
    raison: str
    #: Ce chemin n'existe QUE si une commande l'a fabriqué. `make test
    #: PY=python3` — le second chemin d'exécution que le `Makefile` documente
    #: lui-même, et le seul possible avant d'avoir construit l'environnement —
    #: rendait ROUGE sur un clone neuf : `.venv` est gitignoré, donc absent,
    #: donc « exemption morte » pour un contrôle qui exigeait son existence.
    #: Un garde qui exige la présence d'un dossier d'installation pour se
    #: déclarer hermétique perd la propriété qu'il vient d'acquérir.
    #: Ce qu'on exige à la place, pour ces zones-là : qu'elles soient nommées
    #: dans `.gitignore`. C'est ce qui prouve qu'elles appartiennent encore au
    #: dépôt sans dépendre de l'état de la machine — et une exemption pour
    #: `node_modules` échouerait toujours, ce qui était le but.
    engendree: bool = False
    #: `.git` est le seul chemin de cette liste dont l'ABSENCE soit normale et
    #: ne prouve rien : une archive téléchargée n'en a pas, et `git` ne
    #: s'ignore jamais lui-même — il n'est pas dans `.gitignore`, et il ne
    #: peut pas y être. Le contrôle d'exemption vivante le tenait pourtant
    #: pour mort, et rendait ROUGE, dans une copie sans `.git`, un garde qui
    #: n'a rien à voir avec git. C'est la même faute que celle des deux gardes
    #: documentaires, d'un cran plus discrète : supposer un environnement que
    #: le lecteur peut ne pas avoir.
    hors_git: bool = False


#: Ce qui n'est pas du code de ce dépôt. Chaque entrée porte sa raison, et
#: `test_chaque_exemption_de_zone_couvre_encore_quelque_chose` échoue si l'une
#: d'elles ne désigne plus rien : une exemption morte est un angle mort qui a
#: cessé de se justifier sans que personne ne le sache.
EXEMPTIONS_ZONE: tuple[Exemption, ...] = (
    Exemption(".git", "L'historique de git, pas le dépôt de travail. Son contenu "
                      "est immuable et n'est jamais exécuté ni lu par personne.",
              hors_git=True),
    Exemption(".venv", "Les dépendances tierces, installées par pip. Elles ne sont "
                       "pas notre code : on ne les corrige pas, on en change.",
              engendree=True),
    Exemption("__pycache__", "Du bytecode engendré, illisible et régénéré à chaque "
                             "import : il ne se corrige pas, il se supprime.",
              engendree=True),
    Exemption(".pytest_cache", "L'état de pytest entre deux passages ; engendré, "
                               "jamais lu par un humain, jamais exécuté.",
              engendree=True),
    Exemption("logs", "Des journaux d'exécution — la SORTIE du système, pas sa "
                      "source. Un nom de rôle y apparaît parce qu'il a tourné, "
                      "pas parce qu'il est figé quelque part.",
              engendree=True),
)
# NOTE — « node_modules » figurait ici à la première rédaction, par réflexe.
# Ce dépôt n'a pas une ligne de JavaScript, et
# `test_chaque_exemption_de_zone_couvre_encore_quelque_chose` l'a refusée dès
# le premier passage. C'est exactement son rôle : une permission de ne pas
# regarder se recopie sans qu'on y pense, et grossit jusqu'à ce que le garde
# ne balaie plus rien pendant que tout le monde le croit complet.

#: On ne balaie pas ce qu'on ne peut pas lire comme du texte. Ce n'est pas une
#: indulgence : un octet nul n'a jamais figé un nom de rôle.
SUFFIXES_BINAIRES = {
    ".pyc", ".pyo", ".so", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
    ".pdf", ".zip", ".gz", ".tar", ".dump", ".woff", ".woff2", ".ttf",
    ".db", ".sqlite", ".sqlite3", ".whl",
}


def _fichiers_balayes() -> list[Path]:
    """TOUT le dépôt, moins ce qui est nommément exempté et ce qui est binaire."""
    exemptes = {e.chemin for e in EXEMPTIONS_ZONE}
    vus: list[Path] = []
    for p in sorted(RACINE.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(RACINE)
        if any(part in exemptes for part in rel.parts):
            continue
        if p.suffix.lower() in SUFFIXES_BINAIRES:
            continue
        try:
            p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # illisible comme texte : rien à y figer
        vus.append(p)
    return vus


# ---------------------------------------------------------------------------
# EXTRAIRE CE QUI S'EXÉCUTE
# ---------------------------------------------------------------------------


_COMMENTAIRE = re.compile(r"^\s*(#|--|//)")
_ENCADRE = re.compile(r"^\s*(```|~~~)")


def _lignes_de_docstring(texte: str) -> set[int]:
    """Les numéros de ligne occupés par une chaîne écrite POUR ÊTRE LUE.

    Une docstring de module, de classe ou de fonction — mais aussi la
    docstring d'ATTRIBUT, cette chaîne nue posée juste après une affectation,
    que Sphinx et ce dépôt emploient abondamment :

        READONLY_DSN_ENV: str = "DATABASE_URL_READONLY"
        \"\"\"Nom de la variable portant le DSN read-only (rôle arac_readonly).\"\"\"

    Le garde n'en tenait pas compte et lisait cette prose comme du code : il
    accusait `control_center/config.py`, `cc_v1/metric.py` et `cc_v1/entities.py`
    de figer un nom de rôle, alors que les trois l'EXPLIQUENT. Un garde qui
    crie au loup sur une explication apprend à ses lecteurs à l'ignorer, et
    c'est précisément le jour où il a raison que plus personne ne l'écoute.

    On retient donc toute instruction-expression réduite à une chaîne : elle ne
    produit aucun effet, elle ne peut être là que pour être lue.
    """
    try:
        arbre = ast.parse(texte)
    except SyntaxError:  # pragma: no cover — un fichier illisible se voit ailleurs
        return set()
    pris: set[int] = set()
    for n in ast.walk(arbre):
        if (
            isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Constant)
            and isinstance(n.value.value, str)
        ):
            pris.update(range(n.lineno, (n.end_lineno or n.lineno) + 1))
    return pris


#: Une portion de texte en POLICE DE CODE, au fil d'une phrase ou d'une cellule
#: de tableau : `/var/log/arac`, `journalctl -u arac-backup`.
_SPAN = re.compile(r"`{1,2}([^`\n]+)`{1,2}")
#: Un bloc indenté de quatre espaces — l'autre façon d'écrire du code en
#: Markdown, que la clôture ``` n'attrape pas.
_INDENTE = re.compile(r"^(?: {4}|\t)\S")
#: Une ligne de tableau Markdown — donc une INSTRUCTION, voir plus bas.
_TABLEAU = re.compile(r"^\s*\|")
#: Ce qui distingue une COMMANDE d'un simple nom cité en police de code : elle
#: porte un argument. Un drapeau (`-u`, `--tout`) ou un chemin après un blanc.
_RX_COMMANDE = re.compile(r"\s(?:-{1,2}[A-Za-z]|[~/]\S|\S+/\S)")


def _RESSEMBLE_A_UNE_COMMANDE(span: str) -> bool:
    return bool(_RX_COMMANDE.search(span))


#: Ce qui reste d'une cellule quand on lui retire ses spans de code : si c'est
#: vide ou de la seule ponctuation de séparation, la cellule EST une valeur.
_LIANT = re.compile(r"^[\s·,;:/|*+()\[\]«»\"'—–-]*$")


def _cellules_de_code(ligne: str) -> list[str]:
    """Ce qu'une ligne de tableau Markdown fait EXÉCUTER, cellule par cellule.

    Une cellule entièrement en police de code est une VALEUR — c'est ce que le
    lecteur recopie. Une cellule de prose est une LEÇON, et ne rend que les
    commandes qu'elle porte, exactement comme une phrase au fil du texte.
    """
    sortie: list[str] = []
    for cellule in ligne.strip().strip("|").split("|"):
        spans = _SPAN.findall(cellule)
        if not spans:
            continue
        reste = _SPAN.sub(" ", cellule)
        if _LIANT.match(reste):
            sortie.extend(spans)          # la cellule est une valeur
        else:
            sortie.extend(s for s in spans if _RESSEMBLE_A_UNE_COMMANDE(s))
    return sortie


def _code_de_document(lignes: list[str]) -> list[tuple[int, str]]:
    """Ce qui S'EXÉCUTE dans un document : TOUT ce qui est en police de code.

    LA DOCUMENTATION EST DU CODE QUI S'EXÉCUTE DANS LES MAINS D'UN HUMAIN.
    Une commande fausse dans un runbook détruit aussi sûrement qu'un script :
    celui qui la lit la copie, la colle et l'exécute — avec les droits de root,
    et sans le filet d'un `--dry-run`. Un `sudo systemctl enable arac-api` posé
    dans un guide d'installation écrase l'unité du voisin exactement comme s'il
    était sorti d'un `.sh`.

    CE GARDE-CI N'A REGARDÉ QUE LES BLOCS ENCADRÉS, ET C'ÉTAIT UNE QUATRIÈME
    ÉNUMÉRATION — celle des FORMES de code qu'un document peut porter. Mesure :
    sur `docs/EXPLOITATION.md`, la règle « seul l'intérieur de ``` s'exécute »
    retenait 35 lignes sur 346. Ce qu'elle laissait passer :

      · six cellules de TABLEAUX DE RÉFÉRENCE publiant des dossiers communs
        comme valeurs par défaut — `| ARAC_LOG_DIR | /var/log/arac | … |`. Un
        tableau de configuration n'est pas de la prose : c'est ce que le
        lecteur recopie dans son `.env`, et l'environnement du processus
        l'emporte sur toute dérivation faite par le code ;
      · trois commandes de runbook écrites au fil du texte —
        `journalctl -u arac-curator-batch -n 100`, `python3 ~/.arac/arac-sync.py`.

    LA RÈGLE, CORRIGÉE, tient en une phrase : **ce qui est en police de code
    est ce que le lecteur copie**. On retient donc l'intérieur des blocs
    encadrés, les blocs indentés de quatre espaces, ET le contenu de chaque
    span `…` où qu'il soit — y compris dans une cellule de tableau. La prose
    nue, elle, ne s'exécute toujours pas : une phrase qui RACONTE l'incident en
    nommant `arac_app`… l'écrirait en police de code, justement. C'est pourquoi
    les dispenses existent, et pourquoi chacune porte sa raison.
    """
    retenues: list[tuple[int, str]] = []
    dedans = False
    for i, l in enumerate(lignes, start=1):
        if _ENCADRE.match(l):
            dedans = not dedans
            continue
        if dedans:
            if not _COMMENTAIRE.match(l):
                retenues.append((i, l))
            continue
        if _INDENTE.match(l) and not _COMMENTAIRE.match(l):
            retenues.append((i, l))
            continue
        if _TABLEAU.match(l):
            # UN TABLEAU DE RÉFÉRENCE EST UNE INSTRUCTION — MAIS PAS TOUTE
            # ENTIÈRE. Sa colonne « valeur par défaut » est ce que le lecteur
            # recopie dans son `.env`, et l'environnement du processus l'emporte
            # sur toute dérivation faite par le code : `ARAC_LOG_DIR=/var/log/arac`
            # posé à la main annule `${ARAC_LOG_DIR:-/var/log/arac/$ARAC_DB}`.
            #
            # Sa colonne « pourquoi », elle, est de la PROSE, et la prose de ce
            # dépôt est sa valeur. Retenir la ligne entière faisait accuser
            # `docs/CONFIGURATION.md:443` — la cellule qui explique, mot pour
            # mot, que « `/var/backups/arac` est commun à la machine, et deux
            # cerveaux qui y déposent leurs dumps se mêlent ». Le garde criait
            # au loup sur la phrase écrite pour l'en avertir.
            #
            # On applique donc à CHAQUE CELLULE la règle déjà écrite pour le
            # fil du texte : une cellule faite uniquement de police de code est
            # une valeur, on la retient ; une cellule de prose ne rend que ses
            # commandes.
            morceaux = [m for m in _cellules_de_code(l) if m]
            if morceaux:
                retenues.append((i, " ".join(morceaux)))
            continue
        commandes = [s for s in _SPAN.findall(l) if _RESSEMBLE_A_UNE_COMMANDE(s)]
        if commandes:
            # UNE COMMANDE AU FIL DU TEXTE S'EXÉCUTE COMME UNE AUTRE. Trois
            # d'entre elles nommaient des ressources communes hors de tout bloc
            # encadré — `journalctl -u arac-curator-batch -n 100`,
            # `python3 ~/.arac/arac-sync.py --tout`.
            #
            # On ne retient PAS le span d'un simple identifiant : `arac_app`
            # dans un glossaire, `8100` dans une phrase qui explique où vit le
            # cockpit, sont des LEÇONS. Un garde qui les accuse apprend à ses
            # lecteurs à l'ignorer — et c'est le jour où il a raison que plus
            # personne ne l'écoute.
            retenues.append((i, " ".join(commandes)))
    return retenues


def code_de(p: Path) -> list[tuple[int, str]]:
    """Les lignes de ce fichier qui S'EXÉCUTENT, numérotées.

    On retire les lignes de commentaire (`#`, `--` pour le SQL des documents
    en ligne, `//` pour le JavaScript) et, en Python, les chaînes écrites pour
    être lues. Une chaîne de caractères ordinaire, elle, RESTE : c'est dans
    `op.execute("GRANT … TO arac_app")` que le défaut vivait, et une chaîne SQL
    est du code au sens plein.

    Dans un document Markdown, ce qui s'exécute est le contenu des blocs
    encadrés — voir `_code_de_document`.
    """
    texte = p.read_text(encoding="utf-8", errors="replace")
    lignes = texte.splitlines()
    if p.suffix.lower() in {".md", ".markdown", ".rst"}:
        return _code_de_document(lignes)
    docs = _lignes_de_docstring(texte) if p.suffix == ".py" else set()
    return [
        (i, l)
        for i, l in enumerate(lignes, start=1)
        if i not in docs and not _COMMENTAIRE.match(l)
    ]


# ---------------------------------------------------------------------------
# LES MOTIFS — un nom qu'un second cerveau se disputerait
# ---------------------------------------------------------------------------


# LA QUATRIÈME ÉNUMÉRATION, ET POURQUOI ELLE A SURVÉCU À SA PROPRE CONDAMNATION
# =============================================================================
#
# La manche précédente a écrit ici, en capitales : « ON CESSE D'ÉNUMÉRER —
# C'EST LA TROISIÈME FOIS », puis « on décrit la FORME, pas les instances : un
# défaut d'une famille neuve est vu le jour où il apparaît ». C'était FAUX, et
# ça a été mesuré : trente-huit ressources partagées, couvrant onze familles,
# ont été posées devant le garde ; il en a vu SEPT — et six de ces sept
# uniquement parce qu'un chemin absolu traînait sur la même ligne.
#
# La raison est nette. Cinq des six motifs exigeaient, quelque part dans leur
# expression, la sous-chaîne littérale « arac ». Le garde ne reconnaissait donc
# pas une RESSOURCE : il reconnaissait un NOM DE PRODUIT. Un compte système, une
# zone mémoire nginx, un port autre que deux, un slot de réplication, une base
# en position d'argument — tout cela lui était invisible, et le restait quel que
# soit le dégât.
#
# UN GARDE QUI SE TROMPE EST RÉPARABLE. UN GARDE QUI MENT SUR SA PROPRE
# COUVERTURE NE L'EST PAS : il donne confiance, et la confiance est ce qui
# empêche de regarder.
#
# LE PRINCIPE, REFAIT — LA NATURE, PAS LE NOM
# ============================================
#
# La question n'est plus « ce nom contient-il arac ? ». Elle est :
#
#     ce littéral occupe-t-il la PLACE d'une ressource qui n'existe qu'en un
#     seul exemplaire sur la machine — et, si oui, est-il DÉRIVÉ de l'identité
#     du cerveau ?
#
# Deux portes d'entrée, et il suffit d'UNE :
#
#   · LA PLACE. Le littéral suit un geste de revendication ou occupe un champ
#     de déclaration : `useradd X`, `chown X`, `User=X`, `CREATE ROLE X`,
#     `createdb X`, `--port N`, `listen N`, `zone=X`, `WantedBy=X`,
#     `StateDirectory=X`, `pg_create_logical_replication_slot('X')`. Le NOM n'y
#     entre pour rien : `useradd cortex` est vu comme `useradd arac`.
#   · LE TERRITOIRE. Le littéral est un chemin absolu, ou sous le foyer, dans
#     un espace que toute la machine partage. Là non plus, aucun nom n'est
#     exigé : `/var/lib/cortex` est vu comme `/var/lib/arac`.
#
# CE QUE LA PORTE « LA PLACE » VOIT VRAIMENT — la ligne qui promettait trop
# ==========================================================================
#
# Cette ligne disait : « C'est cette porte qui voit les familles auxquelles
# personne n'a pensé. » C'était faux, et c'est MESURÉ. Vingt familles neuves
# de ressources partagées ont été posées devant le garde — `ip netns add`,
# `ip link add`, `dmsetup create`, `mkfs -L`, `zfs create`,
# `btrfs subvolume create`, `mount --bind`, `lvcreate -n`, `setcap`,
# `sysctl`, `update-alternatives`, `mkfifo`, `flock`, une socket UNIX
# abstraite, `at`, `avahi`, `docker network create`, `podman`, un vhost
# RabbitMQ. **Il en a raté quinze.** Les cinq « vues » ne l'ont été que parce
# qu'un chemin absolu traînait sur la même ligne — donc par LE TERRITOIRE,
# jamais parce que le verbe de revendication a été reconnu.
#
# La raison est mécanique, et elle est la même que celle de la troisième
# énumération : les MOTIFS décrivent des places prises dans un vocabulaire de
# verbes et de champs FERMÉ (`useradd`, `CREATE ROLE`, `--port`, `WantedBy=`…).
# Un geste de revendication écrit avec un AUTRE verbe n'occupe aucune place que
# le garde reconnaisse. « La place » n'est donc pas une porte ouverte sur
# l'inconnu : c'est une quatrième énumération, honnête sur ce qu'elle contient
# mais aveugle à ce qu'elle ne contient pas.
#
# CE QU'ELLE VOIT, POUR DE BON :
#   · les revendications écrites avec les verbes et les champs de `MOTIFS` —
#     comptes, rôles et bases PostgreSQL, unités systemd, ports, zones nginx,
#     slots de réplication. C'est le vocabulaire de CE produit, et c'est là
#     que vivent tous ses dégâts croisés connus ;
#   · le NOM n'y entre pour rien : un verbe connu suffit, quel que soit le
#     littéral qui le suit. C'est ce qui a été gagné, et c'est réel.
#
# CE QU'ELLE NE VOIT PAS :
#   · un verbe de revendication qui n'est pas dans `MOTIFS` — le noyau et le
#     stockage cœur-de-système en particulier (`ip netns`, `dmsetup`, `mkfs`,
#     `zfs`, `btrfs`, `mount --bind`, `lvcreate`, `setcap`) ;
#   · les démons TIERS, déjà déclarés dans `ZONES_NON_COUVERTES` (docker,
#     podman, rabbitmq) — cette zone-là était honnête, elle.
#
# POURQUOI CE N'EST PAS UN CHEMIN VIVANT, ET POURQUOI ON L'ÉCRIT QUAND MÊME.
# Le dépôt n'emploie aucun de ces outils, et sa propre doctrine dit qu'un motif
# pour une technologie absente « rend le même vert qu'un motif qui n'existe
# pas » : ajouter quinze motifs morts n'ajouterait aucune sécurité, seulement
# de la confiance. Ce qu'on corrige ici n'est donc pas la couverture, c'est la
# PHRASE — parce qu'un garde qui ment sur sa portée est pire qu'un garde
# absent : il donne confiance, et la confiance est ce qui empêche de regarder.
# Le jour où ce dépôt posera un `zfs create` ou un `ip netns add`, il faudra un
# motif ; d'ici là, cette limite est écrite, et `ZONES_NON_COUVERTES` la porte.
#
# L'INVERSION, QUI EST LE VRAI MÉCANISME
# =======================================
#
# Ce dépôt a déjà fait cette bascule une fois, pour le garde de processus : il
# n'énumère plus les commandes interdites, il énumère les outils LÉGITIMES et
# refuse tout le reste. La règle générale est là :
#
#     énumérer les FAUTES échoue en silence — ce qui manque à la liste est
#     invisible, et un motif qui ne correspond à rien rend le même vert qu'un
#     motif qui n'existe pas ;
#     énumérer le LÉGITIME échoue à voix haute — ce qui manque à la liste est
#     accusé à tort, et quelqu'un vient le lire.
#
# G1 applique désormais la même inversion, partout :
#   · `RACINES_DU_SYSTEME` / `FICHIERS_DU_SYSTEME` / `REPERTOIRES_DU_SYSTEME` —
#     ce que la distribution fournit et que nous ne revendiquons pas. Tout
#     autre chemin est présumé nôtre, donc disputé ;
#   · `COMPTES_DU_SYSTEME`, `UNITES_DU_SYSTEME` — même chose pour les comptes
#     et les démons partagés ;
#   · `TYPES_SQL_LOCAUX` — les types d'objets SQL qui vivent DANS une base.
#     Tout autre type (`CREATE PUBLICATION`, `CREATE EVENT TRIGGER`,
#     `CREATE TABLESPACE`, celui que PostgreSQL ajoutera l'an prochain) est
#     présumé global au cluster, donc disputé ;
#   · le vocabulaire d'identité de `est_derive` — voir ci-dessous.
#
# CE QUE « DÉRIVÉ » VEUT DIRE, ET CE QU'IL NE VEUT PLUS DIRE
# ==========================================================
#
# L'ancien prédicat était `re.compile(r"[\$@{<%]|__|\.\.\.|…|chemin/vers")` :
# tout littéral portant `$`, `@`, `{`, `<`, `%` ou un double soulignement
# N'IMPORTE OÙ était déclaré « calculé depuis l'identité du cerveau ». Il ne
# demandait pas si l'interpolation distinguait deux cerveaux ; il demandait
# s'il y avait de la ponctuation. Mesuré : `$HOME/.ssh/id_ed25519_arac` était
# classé comme le REMÈDE — alors que `$HOME` est l'identité d'un HUMAIN, et
# qu'un humain pilote plusieurs cerveaux : c'est le cas que tout ce travail
# existe pour rendre possible. Le même fichier écrit `~/.ssh/…` était vu ;
# écrit `$HOME/.ssh/…`, il ne l'était plus.
#
# Une dérivation est maintenant une SUBSTITUTION RECONNAISSABLE — `$VAR`,
# `${VAR}`, `{var}`, `@@JETON@@`, `__JETON__`, `<votre_base>` — dont le jeton
# n'est PAS déclaré étranger à l'identité d'un cerveau. La liste de ce qui n'est
# pas une identité (`$HOME`, `$USER`, `$PWD`, `%i`, …) est écrite une fois, et
# elle est courte parce qu'elle doit être lue.
#
# CE QUE CE PRÉDICAT NE SAIT PAS FAIRE — et le garde le dit lui-même, dans
# `ZONES_NON_COUVERTES` : il lit une LIGNE, pas un programme. `$U_API` est tenu
# pour dérivé sans que rien ne prouve d'où sort `U_API`. Suivre l'affectation
# demanderait une analyse de flot que ce garde ne fait pas. On préfère l'écrire
# que de laisser croire le contraire.

#: Les substitutions qui ne prouvent RIEN : elles nomment un humain, une
#: machine, un instant — jamais un cerveau. Un chemin qui ne porte que celles-là
#: reste accusable.
_PAS_UNE_IDENTITE = re.compile(
    r"\$\{?(?:HOME|USER|LOGNAME|PWD|OLDPWD|TMPDIR|TMP|UID|EUID|SUDO_USER|"
    r"SHELL|PATH|RANDOM|HOSTNAME|LANG|TERM|EDITOR)\b"
)

#: Une substitution, quelle qu'elle soit. `$1` en fait partie : un paramètre
#: positionnel est une valeur calculée par l'appelant, pas un nom écrit.
_MARQUE = re.compile(
    r"\$\{?[A-Za-z_][A-Za-z_0-9]*"      # $VAR  ${VAR}
    r"|\$\d+"                           # $1 — paramètre positionnel
    r"|\{[A-Za-z_]|\}"                 # {var} {R.app} — une accolade, ouverte ou
                                        # fermée, est la marque d'une f-string.
                                        # Le garde lit une LIGNE, pas un arbre :
                                        # `f"/var/log/arac/{base}"` lui arrive
                                        # parfois coupé à `/var/log/arac/{base`.
    r"|\$\("                            # $(…) — substitution de commande
    r"|@@[A-Z0-9_]+@@"                  # @@JETON@@ — gabarits de deploy/
    r"|__[A-Z0-9_]+__"                  # __JETON__ — gabarits SQL
)

#: Le trou que la documentation demande au lecteur de remplir AVEC LE NOM DE SON
#: CERVEAU. C'est le remède, écrit pour un humain au lieu d'un interpréteur.
#: `<le-dump>` n'en est pas : il nomme un fichier, pas un cerveau — et c'est
#: pourquoi `/var/backups/arac/<le-dump>.dump` reste accusé.
_TROU_D_IDENTITE = re.compile(
    r"<[^>]*(?:cerveau|base|brain|prefixe|prefix|votre)[^>]*>", re.IGNORECASE)

#: Un littéral qui n'est QUE le trou à remplir ne fige rien : il n'y a aucun
#: nom à disputer. `<unité>`, `${…}` seul.
_TOUT_UN_TROU = re.compile(r"^[\"'`]?(?:<[^>]+>|\$\{[^}]+\})[\"'`]?$")


def est_derive(litteral: str) -> bool:
    """Ce nom est-il calculé depuis l'identité du cerveau ? Alors il est le remède.

    Un seul endroit pose la question, pour tous les motifs — c'est ce qui évite
    qu'un motif neuf oublie de reconnaître le remède et crie au loup sur la
    solution. Mais il la pose maintenant sur la SUBSTITUTION, pas sur la
    ponctuation : `/var/backups/arac/<le-dump>.dump` porte des chevrons et reste
    accusé, parce que le répertoire — ce que deux cerveaux se disputent — n'est
    pas dérivé ; seul le nom du fichier l'est.
    """
    if _TOUT_UN_TROU.match(litteral) or _TROU_D_IDENTITE.search(litteral):
        return True
    if litteral.startswith("<"):
        return True          # un chevron ouvrant : le trou commence ici
    for m in _MARQUE.finditer(litteral):
        if not _PAS_UNE_IDENTITE.match(m.group(0)):
            return True
    return False


@dataclass(frozen=True)
class Motif:
    cle: str
    regex: str
    quoi: str        # ce que le nom désigne
    degat: str       # ce qu'un second cerveau détruirait en le réutilisant
    remede: str      # la forme dérivée qui aurait dû être écrite
    #: CE QUI A CHANGÉ ICI, ET POURQUOI C'ÉTAIT UNE RÉGRESSION.
    #: Le champ s'appelait `ligne_exclue` et il était appliqué à la LIGNE
    #: ENTIÈRE, alors que l'accusation porte sur un LITTÉRAL. Un seul mot,
    #: n'importe où sur la ligne, désarmait le motif pour tout ce qu'elle
    #: contenait. Neuf mots avaient ce pouvoir ; le pire était `postgres\b` sur
    #: le motif `base`, qui rendait le garde aveugle à
    #: `sudo -u postgres psql -d arac` — c'est-à-dire à la forme exacte que ce
    #: motif a été écrit pour attraper, et que son propre champ `degat` cite.
    #: L'exclusion porte maintenant sur le LITTÉRAL, et rien d'autre : un
    #: gabarit versionné (`arac-backup.service.modele`) est le nom d'un fichier
    #: du dépôt, pas celui d'une unité installée — et ça, ça se lit dans le
    #: littéral lui-même.
    exclusion_litterale: str = ""
    #: Ce qui PRÉCÈDE IMMÉDIATEMENT le littéral et prouve qu'il ne désigne pas
    #: cette ressource-là. `prompt[:8000]` n'est pas un port : le plafond de
    #: troncature se reconnaît aux deux caractères qui le précèdent, pas à un
    #: mot posé quelque part sur la ligne. Une exclusion de CONTEXTE est
    #: légitime ; une exclusion de LIGNE ne l'est pas, parce qu'elle éteint
    #: aussi ce qui n'a rien à voir.
    prefixe_refuse: str = ""
    #: Les groupes nommés qui portent le LITTÉRAL à juger. Vide = le motif
    #: entier. C'est ce littéral, et lui seul, qu'on interroge sur sa
    #: dérivation : `systemctl restart $PREFIXE_UNITE-api` ne doit pas être
    #: accusé parce que le mot « systemctl » n'est pas dérivé.
    groupes: tuple[str, ...] = ()
    rx: re.Pattern = field(init=False)
    rx_exclue: re.Pattern | None = field(init=False)
    rx_prefixe: re.Pattern | None = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "rx", re.compile(self.regex))
        object.__setattr__(
            self, "rx_exclue",
            re.compile(self.exclusion_litterale) if self.exclusion_litterale else None,
        )
        object.__setattr__(
            self, "rx_prefixe",
            re.compile("(?:" + self.prefixe_refuse + ")$") if self.prefixe_refuse else None,
        )


# ---------------------------------------------------------------------------
# CE QUE LA MACHINE FOURNIT — la liste du LÉGITIME, jamais celle des fautes
# ---------------------------------------------------------------------------
#
# Ces quatre listes sont des ÉNUMÉRATIONS, et c'est voulu. Elles n'énumèrent
# pas les fautes — elles énumèrent ce qui n'appartient à personne parce que la
# distribution le fournit. Le sens de l'échec s'inverse avec elles : un chemin
# système absent de la liste est ACCUSÉ À TORT, donc lu, discuté, ajouté. Une
# faute absente d'une liste de fautes, elle, n'est jamais lue.

#: Les racines où vivent les exécutables et les données de la distribution. On
#: y lit, on n'y revendique pas. `/usr/local/bin` y figure et c'est un COMPROMIS
#: assumé : voir `ZONES_NON_COUVERTES`.
RACINES_DU_SYSTEME = (
    "/usr/bin/", "/usr/sbin/", "/bin/", "/sbin/", "/usr/lib", "/usr/share/",
    "/usr/include/", "/proc/", "/sys/", "/dev/", "/lib/", "/lib64/",
    "/etc/apt/", "/etc/ssl/", "/etc/pki/", "/etc/default/", "/etc/security/",
    "/usr/local/bin/", "/usr/local/sbin/", "/opt/homebrew/bin/",
    "~/Library/Application", "~/Library/Containers", "~/Library/Caches",
    "~/Library/Preferences", "~/.cache/", "~/.local/bin/",
    # Le foyer de Claude Desktop / Claude Code : c'est la SOURCE des
    # conversations, posée par un autre éditeur. Les deux cerveaux la lisent, et
    # aucun ne peut la renommer — il n'y a rien à dériver là.
    "~/.claude/", "~/.claude.json",
)

#: Des fichiers que la distribution pose, que tout le monde lit, et que
#: personne ne se dispute : les nommer n'est pas les revendiquer.
FICHIERS_DU_SYSTEME = {
    "/etc/os-release", "/etc/lsb-release", "/etc/timezone", "/etc/localtime",
    "/etc/passwd", "/etc/group", "/etc/shadow", "/etc/gshadow", "/etc/hosts",
    "/etc/hostname", "/etc/fstab", "/etc/environment", "/etc/resolv.conf",
    "/etc/crontab", "/etc/sudoers", "/etc/nsswitch.conf", "/etc/machine-id",
    "/etc/shells", "/etc/login.defs", "/etc/profile", "/etc/bash.bashrc",
    "/etc/inputrc", "/etc/sysctl.conf",
    "~/.ssh/config", "~/.ssh/authorized_keys", "~/.ssh/known_hosts",
    "~/.bashrc", "~/.zshrc", "~/.profile", "~/.gitconfig",
}

#: Des RÉPERTOIRES partagés par nature. Le répertoire lui-même n'est disputé par
#: personne — ce qui est disputé, c'est le nom qu'on y DÉPOSE. `/etc/tmpfiles.d`
#: n'appartient à aucun cerveau ; `/etc/tmpfiles.d/arac-backup.conf`, si.
REPERTOIRES_DU_SYSTEME = {
    "/etc", "/var", "/run", "/opt", "/srv", "/tmp", "/home", "/root", "/usr",
    "/usr/local", "/etc/systemd", "/etc/systemd/system", "/etc/systemd/user",
    "/etc/cron.d", "/etc/cron.daily", "/etc/cron.hourly", "/etc/tmpfiles.d",
    "/etc/sudoers.d", "/etc/ssh", "/etc/ssh/sshd_config.d", "/etc/nginx",
    "/etc/nginx/conf.d", "/etc/nginx/sites-available", "/etc/nginx/sites-enabled",
    "/etc/letsencrypt", "/etc/letsencrypt/live", "/etc/postgresql",
    "/var/log", "/var/lib", "/var/backups", "/var/cache", "/var/run", "/var/tmp",
    "/var/log/nginx", "/var/lib/postgresql", "/var/www", "/var/www/html",
    "/opt/homebrew/bin", "/opt/homebrew/sbin",
    "/usr/local/lib", "/usr/local/share", "/usr/local/bin", "/usr/local/sbin",
    "/run/systemd", "/opt/homebrew",
    "~", "~/Library", "~/Library/LaunchAgents", "~/.ssh", "~/.config", "~/.local",
}

#: LES RACINES DE FAMILLE. Ces deux répertoires sont l'espace de noms du
#: PRODUIT : chaque cerveau reçoit le sien DESSOUS — `/etc/arac/<base>/arac.env`,
#: `~/.arac/<cerveau>/pont.conf`. Une racine de famille ne se dérive pas, et
#: c'est précisément ce qui la rend commune : il faut bien qu'elle soit écrite
#: quelque part, et il vaut mieux qu'elle le soit à un seul endroit, nommé.
#: CE QUI EST DESSOUS, EN REVANCHE, EST DISPUTÉ — `~/.arac/pont.conf` et
#: `/etc/arac/backup-recipients.txt` restent accusés, et doivent l'être.
#: La liste est courte, et elle doit le rester : chaque entrée est une porte
#: ouverte au niveau du dessous.
RACINES_DE_FAMILLE = {"~/.arac", "/etc/arac"}

#: Les comptes que la distribution crée. `root` n'est le cerveau de personne.
COMPTES_DU_SYSTEME = {
    "root", "nobody", "nogroup", "postgres", "www-data", "daemon", "bin", "sys",
    "adm", "sudo", "users", "staff", "wheel", "shadow", "tty", "utmp", "crontab",
    "syslog", "messagebus", "systemd-network", "systemd-journal", "systemd-resolve",
    "_postgres", "sshd", "mail", "nginx",
}

#: Les unités que la distribution pose. Deux cerveaux les partagent, et c'est
#: normal : on ne peut pas dériver `postgresql.service`. Ce qu'un cerveau fait
#: SUBIR à une unité partagée (un `systemctl restart postgresql` qui coupe la
#: base du voisin) est un vrai danger — il n'est pas de ceux que G1 sait voir,
#: et il est déclaré dans `ZONES_NON_COUVERTES`.
UNITES_DU_SYSTEME = re.compile(
    r"^(?:postgresql|nginx|ssh|sshd|cron|networking|network|network-online|"
    r"multi-user|basic|timers|sockets|paths|slices|swap|default|graphical|"
    r"rescue|emergency|shutdown|systemd-\w+|dbus|rsyslog|syslog|docker|redis|"
    r"redis-server|apache2|local-fs|remote-fs|system|user|machine|init|getty)"
    r"(?:[.@-]|$)"
)

#: Les types d'objets SQL qui vivent DANS une base — donc dans le cerveau, donc
#: sans conflit possible. Tout autre type est présumé GLOBAL AU CLUSTER : c'est
#: ainsi que `CREATE PUBLICATION`, `CREATE EVENT TRIGGER`, `CREATE TABLESPACE`,
#: et le type que PostgreSQL ajoutera l'an prochain, sont vus sans que personne
#: ne les ait écrits ici.
TYPES_SQL_LOCAUX = {
    "TABLE", "INDEX", "VIEW", "MATERIALIZED", "SCHEMA", "FUNCTION", "PROCEDURE",
    "TRIGGER", "TYPE", "SEQUENCE", "POLICY", "DOMAIN", "CONSTRAINT", "COLUMN",
    "AGGREGATE", "OPERATOR", "RULE", "CAST", "COLLATION", "STATISTICS",
    "EXTENSION", "TEMP", "TEMPORARY", "UNIQUE", "OR", "IF", "TEXT",
    # traités par leurs propres motifs, plus précis :
    "ROLE", "USER", "GROUP", "DATABASE",
}

#: Les verbes de `systemctl`. Ce qui les suit est une unité ; ce qui n'en est
#: pas un n'est pas une commande d'unité. Sans cette liste, le garde accusait
#: `then`, `2>` et `sous-commande`.
VERBES_SYSTEMCTL = {
    "start", "stop", "restart", "reload", "enable", "disable", "status",
    "is-active", "is-enabled", "is-failed", "mask", "unmask", "cat", "show",
    "edit", "kill", "try-restart", "reenable", "preset", "link", "revert",
    "isolate", "set-property", "reset-failed",
}
#: Cette liste entre DANS l'expression du motif : un verbe qui n'y figure pas
#: ne fait pas de la suite une unité, et surtout ne CONSOMME pas le texte —
#: `systemctl list-unit-files 'arac-*-api.service'` doit rester lisible par la
#: branche « forme », qui, elle, voit le nom d'unité.
_VERBES_SYSTEMCTL_RX = "|".join(sorted(VERBES_SYSTEMCTL, key=len, reverse=True))

#: Ceux qui ne prennent pas de nom d'unité en premier argument.
VERBES_SYSTEMCTL_SANS_UNITE = {
    "daemon-reload", "daemon-reexec", "list-units", "list-unit-files",
    "list-timers", "list-sockets", "list-dependencies", "show-environment",
    "poweroff", "reboot", "help",
}

#: Les mots du shell qui ne sont le nom de rien.
MOTS_DU_SHELL = {"then", "fi", "do", "done", "else", "elif", "esac", "in",
                 "&&", "||", ";;", "puis", "et", "ou"}


def _sans_foyer(chemin: str) -> str:
    """`$HOME/x` et `~/x` désignent le même endroit ; on n'en garde qu'une forme."""
    return re.sub(r"^\$\{?HOME\}?", "~", chemin)


def est_un_chemin_de_la_machine(chemin: str) -> bool:
    """Ce chemin désigne-t-il une ressource que deux cerveaux se disputeraient ?

    NON s'il est fourni par la distribution — on y lit, on n'y revendique rien.
    NON si c'est un répertoire partagé nu : ce qui se dispute est le nom qu'on
    y DÉPOSE, pas le répertoire. OUI dans tous les autres cas, quel que soit le
    nom : `/var/lib/cortex` est vu exactement comme `/var/lib/arac`.
    """
    c = _sans_foyer(chemin)
    if any(c.startswith(r) for r in RACINES_DU_SYSTEME):
        return False
    nu = c.rstrip("/")
    if nu in FICHIERS_DU_SYSTEME or nu in REPERTOIRES_DU_SYSTEME:
        return False
    if nu in RACINES_DE_FAMILLE:
        return False
    if c.startswith("~/"):
        # LE FOYER DE L'HUMAIN EST PARTAGÉ PAR SES DEUX CERVEAUX. C'est même le
        # cas que tout ce travail existe pour rendre possible : une personne,
        # plusieurs cerveaux. `~/.arac/pont.conf` et `~/.ssh/id_ed25519_arac`
        # sont donc disputés — tout ce qui n'est pas déjà déclaré fourni par le
        # système l'est.
        return True
    return bool(re.match(
        r"^/(?:etc|var|run|opt|srv|usr/local|tmp|home|root|private)\b", c
    ))


# ---------------------------------------------------------------------------
# LES MOTIFS — la PLACE d'une ressource, jamais son nom
# ---------------------------------------------------------------------------


MOTIFS: tuple[Motif, ...] = (
    Motif(
        cle="compte",
        # LA FAMILLE QUE PERSONNE N'AVAIT NOMMÉE, ET QUI EST LA CAUSE N° 1
        # TRANSPOSÉE D'UN ÉTAGE. Un compte système est global à la MACHINE
        # exactement comme un rôle PostgreSQL est global au CLUSTER. Deux
        # cerveaux qui tournent sous le même uid : chacun lit
        # `/proc/<pid>/environ` de l'autre — donc son `DATABASE_URL_ADMIN`,
        # mot de passe compris. Les empreintes SCRAM distinctes, le `CONNECT`
        # refusé entre bases et le coffre en 0700 tombent tous les trois
        # derrière une seule lecture.
        #
        # Aucun nom n'est exigé : `useradd cortex` est vu comme `useradd arac`.
        regex=r"\b(?:useradd|usermod|userdel|groupadd|groupmod|groupdel)\b"
              r"(?:\s+-{1,2}[\w-]+(?:[= ]\S+)?)*\s+[\"'`]?(?P<cree>[\w.$@{}<>-]+)"
              r"|\bchown\s+(?:-{1,2}\S+\s+)*[\"'`]?(?P<possede>[\w.$@{}<>-]+)(?::[\w.$@{}<>-]+)?\s"
              r"|\bchgrp\s+(?:-{1,2}\S+\s+)*[\"'`]?(?P<groupe>[\w.$@{}<>-]+)\s"
              r"|\b(?:runuser|setpriv)\b[^\n]{0,60}?(?:-u|--user|--reuid)[= ]\s*"
              r"[\"'`]?(?P<devient>[\w.$@{}<>-]+)"
              r"|(?:^|\s)(?:User|Group|SupplementaryGroups)=(?P<unite>[\w.$@{}<>%-]+)"
              r"|\binstall\b[^\n]{0,60}?\s-o\s*[\"'`]?(?P<installe>[\w.$@{}<>-]+)"
              # LA VALEUR PAR DÉFAUT D'UNE VARIABLE QUI DIT CE QU'ELLE PORTE.
              # `ARAC_SERVICE_USER="${ARAC_SERVICE_USER:-arac}"` ne met aucun
              # compte en position : c'est un repli. Mais le NOM de la variable
              # déclare la nature de la valeur, et c'est la seule chose qu'une
              # ligne isolée puisse dire. Sans cette branche, la cause n° 1 de
              # l'incident, transposée du cluster à l'hôte, reste invisible.
              r"|[A-Z_]*(?:USER|GROUP|COMPTE|ACCOUNT)[A-Z_]*="
              r"[\"'`]?\$\{[^:}]*:-(?P<repli>[\w.@-]+)\}",
        groupes=("cree", "possede", "groupe", "devient", "unite", "installe",
                 "repli"),
        quoi="un compte ou un groupe système",
        degat="un compte système est GLOBAL À LA MACHINE : le second cerveau "
              "adopte celui du premier sans un mot, leurs services tournent "
              "sous le même uid, et chacun lit /proc/<pid>/environ de l'autre — "
              "donc son DATABASE_URL_ADMIN. Toute la séparation obtenue en base "
              "tombe derrière une seule lecture",
        remede="dérivez-le comme tout le reste : arac-$ARAC_DB / aracagt-$ARAC_DB, "
               "et REFUSEZ un compte existant dont le foyer n'est pas le vôtre, "
               "au lieu de l'adopter",
    ),
    Motif(
        cle="role",
        # LA POSITION, ET NON LES CINQ NOMS. Le motif d'avant énumérait
        # `arac_(app|agent|readonly|admin|backup)` : un sixième rôle serait né
        # invisible. Ce qui fait qu'un identifiant EST un rôle n'est pas son
        # nom, c'est sa PLACE — après `CREATE ROLE`, après `GRANT … TO`, après
        # `OWNER TO`, après `-U`. Quel que soit son nom, un identifiant qui
        # occupe cette place doit être dérivé.
        #
        # Le second membre — les cinq noms de l'incident — a été RETIRÉ. Il ne
        # servait qu'à retrouver ces noms hors de leur place, c'est-à-dire dans
        # les leçons, et c'est très exactement ce qu'un garde ne doit pas
        # accuser.
        regex=r"(?:^|;)\s*(?:CREATE|ALTER|DROP|SET)\s+(?:ROLE|USER|GROUP)\s+"
              r"(?:IF\s+(?:NOT\s+)?EXISTS\s+)?[\"'`]?(?P<role>[A-Za-z_$@{][\w${}<>%@.-]*)"
              r"|\bGRANT\b[^;\n]{0,160}?\bTO\s+[\"'`]?(?P<a>[A-Za-z_$@{][\w${}<>%@.-]*)"
              r"|\bREVOKE\b[^;\n]{0,160}?\bFROM\s+[\"'`]?(?P<de>[A-Za-z_$@{][\w${}<>%@.-]*)"
              r"|OWNER\s+TO\s+[\"'`]?(?P<owner>[A-Za-z_$@{][\w${}<>%@.-]*)"
              r"|(?<!\w)-U\s+[\"'`]?(?P<u>[A-Za-z_$@{][\w${}<>%@.-]*)",
        groupes=("role", "a", "de", "owner", "u"),
        quoi="un identifiant de rôle PostgreSQL",
        degat="les rôles sont GLOBAUX au cluster : le second bootstrap "
              "réencode le mot de passe du premier, dont les services "
              "tombent au redémarrage suivant, sans rapport visible",
        remede="dérivez-le : $R_APP / $R_AGENT / … en shell, "
               "`roles_arac().app` dans une migration",
    ),
    Motif(
        cle="base",
        # LA BASE, NOMMÉE EN DUR DANS UN GESTE DE BASE. Le motif d'avant ne
        # connaissait que `-d`/`--dbname` : `createdb arac`, `dropdb arac`,
        # `CREATE DATABASE arac` — c'est-à-dire les gestes les PLUS destructeurs
        # du produit — lui échappaient tous. On y ajoute donc la position
        # POSITIONNELLE et les formes SQL.
        regex=r"(?:psql|pg_dump|pg_restore|pg_dumpall|createdb|dropdb|vacuumdb|"
              r"reindexdb|pg_isready|clusterdb)\b[^\n]{0,200}?\s(?:-d|--dbname)[= ]"
              r"\s*[\"'`]?(?P<d>[A-Za-z_$@{][\w${}<>%@.-]*)"
              r"|\b(?:createdb|dropdb)\b(?:\s+-{1,2}[\w-]+(?:[= ]\S+)?)*\s+"
              r"[\"'`]?(?P<positionnel>[A-Za-z_$@{][\w${}<>%@.-]*)"
              r"(?=\s*(?:$|[\"'`;&|)]|\\))"
              r"|(?:^|[;(]|\bTHEN\b)\s*(?:CREATE|DROP|ALTER)\s+DATABASE\s+"
              r"(?:IF\s+(?:NOT\s+)?EXISTS\s+)?[\"'`]?(?P<sql>[A-Za-z_$@{][\w${}<>%@.-]*)"
              r"|[\"'`](?:-d|--dbname)[\"'`]\s*,\s*[\"'`](?P<argv>[A-Za-z_$@{][\w${}<>%@.-]*)"
              r"|datname\s*=\s*'(?P<n>[\w${}<>%@-]+)'"
              r"|postgres(?:ql)?://[^\s\"'`]*/(?P<dsn>[\w${}<>%@-]+)",
        groupes=("d", "positionnel", "sql", "argv", "n", "dsn"),
        quoi="le nom d'une base de données, écrit en dur",
        degat="`arac` est le cerveau de l'auteur ; `camille_brain` celui de "
              "quelqu'un d'autre. Une base nommée en dur dans un geste "
              "d'administration écrit sur la mémoire d'un vivant — et un "
              "`dropdb` la détruit",
        remede="$ARAC_DB en shell, `nom_de_base(os.environ['DATABASE_URL_ADMIN'])` "
               "en Python — le nom vient du DSN de la session, jamais du code",
        # `postgres` n'est pas une base de quelqu'un : c'est la base de
        # maintenance du cluster. C'est le LITTÉRAL qui le dit, pas la ligne —
        # et `_PAS_DES_NOMS` le fait déjà. Rien d'autre à exclure ici : le
        # `|postgres\b` d'avant, appliqué à la ligne, aveuglait le motif sur
        # `sudo -u postgres psql -d arac`.
    ),
    Motif(
        cle="objet_global_sql",
        # LA FAMILLE OUVERTE. On n'énumère pas les objets globaux : on énumère
        # les types LOCAUX à une base, et tout ce qui n'y figure pas est présumé
        # global au cluster. `CREATE PUBLICATION`, `CREATE SUBSCRIPTION`,
        # `CREATE TABLESPACE`, `CREATE EVENT TRIGGER`, un slot de réplication —
        # et le type qu'on inventera — sont vus le jour où ils apparaissent,
        # sans que personne n'ait eu à y penser.
        regex=r"(?:^|[;(])\s*(?:CREATE|DROP)\s+(?:OR\s+REPLACE\s+)?"
              r"(?:IF\s+(?:NOT\s+)?EXISTS\s+)?"
              r"(?P<type>[A-Z][A-Z]{1,20}(?:\s+[A-Z]{2,20})?)\s+[\"'`]?"
              r"(?P<nom>[A-Za-z_$@{][\w${}<>%@.-]*)"
              r"|pg_create_\w*replication_slot\s*\(\s*'(?P<slot>[^']+)'",
        groupes=("nom", "slot"),
        quoi="un objet SQL global au cluster (publication, tablespace, "
             "event trigger, slot de réplication…)",
        degat="ces objets ne vivent pas dans la base : ils vivent dans le "
              "CLUSTER. Deux cerveaux qui posent le même nom se le disputent — "
              "le second `CREATE` échoue, ou pire, réussit et détourne le flux "
              "du premier",
        remede="faites porter le nom du cerveau à l'objet : "
               "arac_cdc_$ARAC_DB, et refusez plutôt que d'adopter",
    ),
    Motif(
        cle="port",
        # LA FORME D'UN PORT, ET NON DEUX NUMÉROS. Le motif d'avant était la
        # liste `(?:8000|8100)` — deux nombres, dans un fichier dont la
        # docstring proclamait « ON CESSE D'ÉNUMÉRER ». Le TROISIÈME nom global
        # de l'incident, le port du CLUSTER, n'avait aucun motif : `-p 5432`,
        # `PGPORT=5432`, `listen 8443`, `--port 8300` étaient tous invisibles.
        #
        # Un port est un entier EN POSITION DE PORT. On garde 8000, 8100 et 5432
        # en second membre : ce sont les trois noms de l'incident, et les
        # rencontrer hors position reste un signal.
        regex=r"(?<![\w.])(?:--[\w-]*port|-p)[= ]\s*[\"'`]?(?P<option>\d{2,5})(?![\w.])"
              r"|\bPGPORT[= ]\s*[\"'`]?(?P<pg>\d{2,5})"
              r"|\blisten\s+(?:[\d.]+:)?(?P<lie>\d{2,5})\b"
              r"|(?:127\.0\.0\.1|localhost|0\.0\.0\.0):(?P<adresse>\d{2,5})(?![\w.])"
              r"|(?<![\w.])(?P<incident>8000|8100|5432)(?![\w.])",
        groupes=("option", "pg", "lie", "adresse", "incident"),
        quoi="un numéro de port, ou le port du cluster PostgreSQL",
        degat="deux cerveaux qui figent le même numéro : le second lie le "
              "port du premier, qui redémarre en boucle pendant que "
              "/healthz répond 200 — servi par l'usurpateur. Et un port de "
              "cluster écrit en dur (ou donné par OMISSION) envoie un `dropdb` "
              "sur la base du voisin",
        remede="$ARAC_API_PORT / $ARAC_COCKPIT_PORT / $ARAC_DB_PORT, attribués "
               "et RÉSERVÉS après constat de disponibilité — et `-p` sur CHAQUE "
               "commande libpq",
        # 8000 n'est pas toujours un port : c'est aussi un PLAFOND DE CARACTÈRES.
        # Ce qui le prouve n'est pas un mot posé quelque part sur la ligne — le
        # motif serait éteint pour tout le reste — mais les DEUX CARACTÈRES qui
        # précèdent le nombre.
        prefixe_refuse=r"\[\s*:\s*|[\w.]*(?:_max|_MAX|MAX_CHARS|_LIMIT|_limit)\s*[:=]\s*"
                       r"|\bmax_\w*\s*[:=]\s*|\btimeout\w*\s*[:=]\s*|\d[\s,]*",
    ),
    Motif(
        cle="unite",
        # LA FORME D'UNE UNITÉ SYSTEMD, ET NON LE NOM DU PRODUIT. Le motif
        # d'avant exigeait la sous-chaîne `arac` DANS le nom de l'unité : une
        # unité partagée nommée autrement (`memory-brain.service`) naissait
        # invisible. On retire l'exigence, et on écarte à la place ce que la
        # DISTRIBUTION fournit — une liste du légitime, qui crie quand elle est
        # incomplète.
        regex=(
            # (a) LA FORME : un nom d'unité. `(?!\.\w)` refuse
            #     `arac-api.service.modele` — le nom d'un GABARIT versionné.
            r"(?P<nom>[\w@.+${}<>%*-]+"
            r"\.(?:service|timer|automount))(?![\w-])(?!\.\w)"
            # (b) LA POSITION : ce qui suit un verbe de systemctl, ou `-u` de
            #     journalctl, EST une unité — suffixe ou pas. C'est ainsi que
            #     `journalctl -u arac-backup` échappait à tout.
            r"|journalctl[^\n]{0,80}?\s(?:-u|--unit)[= ]\s*[\"'`]?"
            r"(?P<journal>[\w@.+${}<>%*-]+)"
            r"|systemctl\s+(?:--?[\w-]+(?:[= ]\S+)?\s+)*(?P<verbe>" + _VERBES_SYSTEMCTL_RX + r")"
            r"\s+(?:--?[\w-]+(?:[= ]\S+)?\s+)*[\"'`]?"
            r"(?P<arg>(?:[\w@.+${}%*-]|<[^>\s]{1,40}>)+)"
            # (c) LA DÉCLARATION : dans une unité, ce qui suit `Unit=`,
            #     `After=`, `WantedBy=`… est une unité, sans exception ; et ce
            #     qui suit `StateDirectory=` est un répertoire que systemd crée
            #     et détruit en notre nom.
            r"|(?:^|\s)(?:Unit|After|Before|Requires|Wants|BindsTo|PartOf|"
            r"WantedBy|RequiredBy|Conflicts)="
            r"(?P<decl>[\w@.+${}<>%*-]+)"
            r"|(?:^|\s)(?:StateDirectory|RuntimeDirectory|LogsDirectory|"
            r"CacheDirectory|ConfigurationDirectory)=(?P<repertoire>\S+)"
        ),
        groupes=("nom", "journal", "arg", "decl", "repertoire"),
        quoi="le nom d'une unité systemd, ou d'un répertoire d'état géré par systemd",
        degat="`systemctl enable` du second cerveau écrase l'unité du "
              "premier : un seul des deux tourne, et c'est le dernier installé. "
              "Et un cockpit qui interroge une unité qu'il n'a pas posée rend "
              "un verdict de santé sur celle du voisin",
        remede="$PREFIXE_UNITE-… en shell, $UNIT_PREFIX au rendu des gabarits ; "
               "et si le préfixe est inconnu, dire « je ne sais pas » plutôt "
               "que de nommer",
        # Un GABARIT versionné porte un nom de FICHIER, pas un nom d'unité :
        # `render.sh` le renomme au rendu. Ça se lit dans le littéral lui-même —
        # c'est pourquoi l'exclusion peut, ici, être honnête.
        exclusion_litterale=r"\.(?:modele|template|exemple|example|key|j2)$",
    ),
    Motif(
        cle="chemin_machine",
        # LA FORME D'UN CHEMIN DE LA MACHINE : absolu, ou sous le foyer — et
        # RIEN D'AUTRE. Le motif d'avant exigeait `arac` dans le chemin :
        # `/var/lib/cortex` naissait invisible. Le tri se fait maintenant sur la
        # NATURE (voir `est_un_chemin_de_la_machine`), pas sur le nom.
        # `(?<!:)` a été RETIRÉ du garde-fou : il faisait manquer
        # `bind = unix:/run/moteur.sock` — mesuré, à l'épreuve des familles
        # neuves. Un `postgres://hote/base` reste écarté parce que `//hote`
        # n'est sous aucune racine de la machine.
        regex=r"(?<![\w.@$~/})\]-])(?P<chemin>(?:~|\$HOME)?/[\w./@+${}<>%*-]+)",
        groupes=("chemin",),
        quoi="un chemin de la MACHINE",
        degat="deux cerveaux partagent un dossier : la rotation de l'un "
              "supprime les dumps de l'autre, le chien de garde de l'un se tait "
              "parce que l'autre a tourné, et le fichier de destinataires de "
              "l'un chiffre les sauvegardes de l'autre vers la mauvaise clé",
        remede="faites porter le nom de la base au chemin : "
               "$ARAC_ETC=/etc/arac/$ARAC_DB, $ARAC_LOG_DIR, $ARAC_BACKUP_DIR, "
               "~/.arac/<cerveau>/…",
        # Le dépôt lui-même n'est pas la machine : on le clone où l'on veut, et
        # son chemin est celui du test qui l'exécute. Ça se lit dans le littéral.
        exclusion_litterale=r"/tmp/pytest|/arac-oss|/arac_runtime|/site-packages"
                            r"|\.(?:modele|template|exemple)$",
    ),
    Motif(
        cle="espace_nomme",
        # LES ESPACES DE NOMS D'UN DÉMON PARTAGÉ. Une zone mémoire nginx est
        # globale à l'INSTANCE nginx : deux cerveaux qui posent chacun leur
        # copie font échouer le chargement de TOUTE la configuration
        # (« zone "arac_ingest" is already declared ») — donc coupent
        # l'ingestion du voisin, et tout autre site servi par le même nginx.
        # Aucune famille de ce genre n'avait de motif.
        regex=r"\b(?:zone|keys_zone)=(?P<zone>[\w${}<>%@.-]+)"
              r"|\bserver_name\s+(?P<hote>[\w${}<>%@.-]+)"
              r"|\bupstream\s+(?P<amont>[\w${}<>%@.-]+)"
              r"|\bproxy_cache_path\b[^\n]*?\bkeys_zone=(?P<cache>[\w.-]+)"
              r"|AF_UNIX[^\n]{0,80}?[\"']\\?0?(?P<socket>[\w-]{3,})",
        groupes=("zone", "hote", "amont", "cache", "socket"),
        quoi="un espace de noms global à un démon partagé (nginx, socket abstraite)",
        degat="une zone nginx, un bloc `upstream`, une socket abstraite sont "
              "uniques pour toute l'instance : le second cerveau qui pose le "
              "même nom fait échouer le chargement complet de la configuration "
              "— l'ingestion du voisin s'arrête, et tout autre site aussi. Un "
              "`server_name` partagé, lui, envoie les conversations d'un poste "
              "vers l'API de l'AUTRE cerveau",
        remede="@@BASE@@ dans les gabarits de deploy/ : zone=arac_ingest_@@BASE@@",
    ),
    Motif(
        cle="launchd",
        # UNE ÉTIQUETTE LAUNCHD EST UNIQUE PAR SESSION macOS. Deux cerveaux
        # pilotés depuis un même Mac : le second `launchctl bootstrap` remplace
        # l'agent du premier, sans erreur et sans journal.
        #
        # `(?<!/)` : une étiquette n'est pas un segment de chemin —
        # `~/Library/Containers/com.anthropic.claudefordesktop/` est le
        # conteneur d'un TIERS, pas une de nos étiquettes.
        regex=r"(?<![\w/.])(?P<etiquette>(?:com|org|net|io|dev)\."
              r"[\w.@${}<>%*-]*\.[\w.@${}<>%*-]+)",
        groupes=("etiquette",),
        quoi="l'étiquette d'un agent launchd sur le poste de travail",
        degat="une étiquette launchd est UNIQUE par session macOS. Deux "
              "cerveaux pilotés depuis un même Mac : le second "
              "`launchctl bootstrap` remplace l'agent du premier, dont la "
              "synchronisation cesse — sans erreur, sans journal, et sans que "
              "rien ne le signale avant qu'un mois de conversations manque",
        remede="com.arac.<cerveau>.pont.sync — l'étiquette porte le nom du "
               "cerveau, comme les unités systemd portent $PREFIXE_UNITE",
        exclusion_litterale=r"\.(?:modele|template|exemple|plist)$",
    ),
    Motif(
        cle="grappe",
        # LA GRAPPE POSTGRESQL. Une famille trouvée par l'épreuve, pas par la
        # réflexion : on pose `pg_createcluster 16 principal` devant le garde et
        # on constate qu'il voit le PORT et pas le NOM. Or un nom de grappe est
        # global à la machine au même titre qu'un compte : `pg_dropcluster 16
        # principal` détruit la grappe du voisin, avec toutes ses bases.
        regex=r"\b(?:pg_createcluster|pg_dropcluster|pg_ctlcluster|pg_upgradecluster)\b"
              r"(?:\s+-{1,2}[\w-]+(?:[= ]\S+)?)*"
              r"\s+(?:\d+(?:\.\d+)?|\$\{?\w+\}?)\s+"
              r"[\"'`]?(?P<grappe>[\w.${}<>%-]+)"
              r"|--cluster[= ]\s*[\"'`]?[\w.${}<>%-]+/(?P<via_option>[\w.${}<>%-]+)",
        groupes=("grappe", "via_option"),
        quoi="le nom d'une grappe (cluster) PostgreSQL",
        degat="une grappe est globale à la MACHINE : `pg_dropcluster 16 <nom>` "
              "détruit celle du voisin — toutes ses bases, tous ses rôles, d'un "
              "seul geste et sans confirmation",
        remede="nommez la grappe d'après le cerveau : "
               "`pg_createcluster 16 arac-$ARAC_DB --port <libre>`",
    ),
)


# ---------------------------------------------------------------------------
# LES DISPENSES
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Dispense:
    motif: str
    #: Un fichier, ou — s'il finit par « / » — un dossier entier. Le second
    #: n'est employé que pour `tests/`, et sa raison dit pourquoi.
    fichier: str
    #: La dispense ne couvre QUE les lignes portant ce marqueur. Un fichier
    #: entier dispensé serait un angle mort : une régression future s'y
    #: rangerait sans que personne ne la voie. `""` = tout le fichier, et
    #: n'est employé que pour le garde lui-même.
    marqueur: str
    raison: str


DISPENSES: tuple[Dispense, ...] = (
    Dispense(
        motif="*",
        fichier="tests/test_g1_aucun_nom_partage_entre_cerveaux.py",
        marqueur="",
        raison="Ce fichier EST le garde : il doit nommer les motifs interdits "
               "pour pouvoir les chercher. Se dispenser lui-même est la seule "
               "façon qu'il a d'exister. Même raisonnement, et même exception, "
               "que test_f1_aucune_trace_de_l_auteur.py, qui porte la liste des "
               "motifs nominatifs interdits pour la même raison.",
    ),
    Dispense(
        motif="role,base,port,unite,chemin_machine,compte,launchd",
        fichier="tests/",
        marqueur="",
        raison="UN TEST NOMME POUR AFFIRMER — ET CETTE PHRASE A ÉTÉ FAUSSE. "
               "C'est sa raison de fond qui la sauve, pas sa formulation "
               "d'origine, qui disait « il n'installe rien … aucune de ces "
               "lignes ne pose d'unité, ne lie de port ni ne crée de rôle ». "
               "tests/test_recall_fresh.py:56 lançait "
               "`sudo -n -u postgres psql -d arac -c 'ALTER TABLE … DISABLE "
               "TRIGGER …'` : du DDL sur un cerveau de PRODUCTION, pendant des "
               "mois, sous le couvert de cette dispense. Ce qui reste vrai est "
               "que la suite doit pouvoir NOMMER ce qu'elle interdit : "
               "test_g2 doit écrire « arac_app » pour prouver que le bootstrap "
               "ne le prend pas, et tests/acceptance/garde_isolement.sh porte "
               "GARDE_PORTS_INTERDITS=\"5432 8000 8100\" — la liste de ce "
               "qu'une installation d'essai n'a PAS le droit de toucher. "
               "CE QUI A CHANGÉ : la dispense n'est plus une affirmation, elle "
               "est GARDÉE. Trois gardes vérifient désormais que ce que "
               "`tests/` nomme, il ne l'exécute pas — et aucun n'est une "
               "énumération : (1) le garde de processus de "
               "tests/garde_hermetique.py n'autorise QUE les outils légitimes "
               "et refuse tout le reste, y compris `sudo`, `psql`, et ce qui "
               "n'existe pas encore ; (2) un PATH de refus suit les "
               "descendants, à n'importe quelle profondeur ; (3) "
               "tests/test_la_porte_du_sous_processus_est_fermee.py essaie "
               "ACTIVEMENT de sortir par chaque porte connue et exige un refus "
               "à chacune, puis balaie tests/ à la recherche de la seule forme "
               "qui reste — un chemin absolu vers un exécutable de l'hôte — et "
               "exige que chaque occurrence soit déclarée avec sa raison. "
               "L'ancienne rédaction renvoyait à garde_isolement.sh ; c'était "
               "insuffisant, et il faut le dire : ce garde-là n'est appelé que "
               "par le harnais d'acceptation, jamais par `make test`. "
               "ET ELLE NE DIT PLUS « * ». Elle nomme les sept motifs dont elle "
               "a besoin, un par un, et chacun doit encore couvrir une ligne "
               "réelle : la dispense la plus large du dépôt était la seule qui "
               "ne pouvait jamais être déclarée morte, parce qu'un `any` sur "
               "cent-vingt fichiers et tous les motifs est vrai pour toujours. "
               "Les deux motifs qui n'y figurent PAS — `espace_nomme` et "
               "`objet_global_sql` — ne sont donc pas silenciés dans `tests/` : "
               "une zone nginx ou un slot de réplication figés par un test "
               "feraient rougir la suite, comme il se doit.",
    ),
    Dispense(
        motif="port",
        fichier="bootstrap/lib/config.sh",
        marqueur="départ, pas attribution",
        raison="Un point de DÉPART doit bien être écrit quelque part, et il "
               "vaut mieux qu'il soit lisible et documenté qu'engendré par un "
               "calcul que personne ne peut prévoir. Ce que l'incident a montré "
               "n'est pas que le nombre 8000 existe : c'est qu'il était ATTRIBUÉ "
               "sans être constaté libre. Ces deux lignes ne sont pas une "
               "attribution — la valeur retenue sort de `premier_port_libre`, "
               "est annoncée si elle a bougé, puis écrite dans la configuration "
               "du cerveau, d'où les relances suivantes la relisent.",
    ),
    Dispense(
        motif="port",
        fichier="Makefile",
        marqueur="Ne touche NI la base",
        raison="Cette ligne d'aide NOMME les ports de production pour promettre "
               "de ne pas y toucher. C'est l'inverse exact d'un port figé : "
               "elle ne lie rien, elle n'attribue rien, elle DÉCLARE une "
               "limite à qui lit « make help » avant de lancer une cible qui "
               "écrit sur disque. Interdire ce nom-là reviendrait à rendre la "
               "promesse imprononçable.",
    ),
    Dispense(
        motif="port",
        fichier="deploy/nginx/ingest-tls.conf.exemple",
        marqueur="listen",
        raison="NGINX N'EST PAS UNE UNITÉ SYSTEMD. Deux serveurs virtuels du même "
               "nginx écoutent tous les deux le 443 et se distinguent par leur "
               "`server_name` : il n'y a là aucun port disputé, et exiger un port "
               "par cerveau ferait écrire une bêtise. Ce qui, dans ce fichier, se "
               "dispute VRAIMENT est ailleurs et reste accusé : la zone mémoire "
               "`zone=arac_ingest`, unique pour toute l'instance nginx — deux "
               "copies de ce fichier font échouer le chargement de la "
               "configuration entière, donc coupent aussi les sites des autres.",
    ),
    Dispense(
        motif="base",
        fichier="ops/restore_guard.sh",
        marqueur="injection est refusée",
        raison="Cette ligne est une PREUVE DE REFUS, pas un geste. Elle passe "
               "`x; DROP DATABASE arac\" --` à `arac_db_name_safe` et exige que le "
               "nom soit REJETÉ ; le motif `base` y voit un `DROP DATABASE arac` "
               "parce que c'est exactement ce que la chaîne contient, et c'est "
               "exactement pourquoi elle est là. Interdire ce nom-là rendrait la "
               "preuve imprononçable — comme la ligne du Makefile qui promet de "
               "ne pas toucher aux ports de production.",
    ),
    Dispense(
        motif="launchd",
        fichier="mac/arac-pont.sh",
        marqueur="modele",
        raison="Ces deux littéraux sont les noms des GABARITS versionnés — "
               "`mac/com.arac.pont.{sync,tunnel}.plist.modele` — dont la boucle "
               "lit le contenu. L'étiquette réellement posée est construite deux "
               "lignes plus bas et porte le cerveau : "
               "`etiquette=\"com.arac.$ARAC_CERVEAU.${modele#com.arac.}\"`. "
               "Confondre le nom d'un fichier du dépôt avec l'étiquette installée "
               "ferait renommer des fichiers pour rien — et, bien pire, ferait "
               "croire le problème résolu là où il ne l'est pas : la "
               "DOCUMENTATION, elle, publie encore les étiquettes communes, et "
               "elle est remise nommément à docs/.",
    ),
)

# ---------------------------------------------------------------------------
# LES CONSTATS REMIS — ce que le garde élargi a trouvé HORS de son périmètre
# ---------------------------------------------------------------------------
#
# POURQUOI CETTE LISTE EXISTE, ET CE QU'ELLE N'EST PAS.
#
# Le garde a changé de principe pendant cette manche : il ne cherche plus des
# NOMS, il cherche des FORMES. Il a donc trouvé, du premier coup, soixante-trois
# littéraux que les huit motifs énumérés ne voyaient pas — dont les deux
# constats que la manche précédente avait classés « bloquant » et « majeur »
# sans qu'aucun motif ne puisse les attraper :
#
#   · docs/SAUVEGARDE.md — `/etc/arac/backup-recipients.txt`, un fichier de
#     destinataires `age` COMMUN à la machine. Le second opérateur qui suit la
#     page écrase la clé publique du premier : les dumps du cerveau A partent
#     désormais chiffrés vers la clé de B. A ne peut plus déchiffrer ses
#     sauvegardes ; B peut déchiffrer toute la mémoire de A. Aucun motif ne
#     couvrait `/etc/arac` — le COFFRE — dans la version d'avant ;
#   · db/migrations/07_… — `arac_proposal_queue_writer`, `arac_memory_writer`,
#     `arac_review_writer` : TROIS rôles PostgreSQL figés, hors des cinq que le
#     motif énumérait. Un rôle est global au cluster. C'est très exactement
#     l'incident d'origine, dans une famille que personne n'avait listée.
#
# AUCUN de ces fichiers n'est dans le périmètre de cette manche (`tests/`,
# `ops/garde_isolement.sh`, `Makefile`). Les corriger à l'aveugle pendant que
# d'autres y travaillent produirait des conflits, pas des corrections.
#
# CE QUE CETTE LISTE FAIT :
#   1. elle rend le constat NOMINATIF — fichier, motif, littéral exact ;
#   2. elle laisse `make test` vert, donc utilisable par les autres ;
#   3. elle est IMPRIMÉE en fin de session (`pytest_terminal_summary`), pour
#      qu'un vert ne se lise jamais comme « il n'y a rien à faire » ;
#   4. elle ne couvre QUE les littéraux écrits ici. Un littéral neuf dans le
#      même fichier échoue — la remise n'est pas un blanc-seing sur le fichier.
#
# CE QU'ELLE N'EST PAS : une dispense. Une dispense dit « ceci est légitime ».
# Une remise dit « ceci est une faute, elle a un propriétaire, et voici son
# nom ». Le jour où elle est réparée, `test_les_constats_remis_sont_encore_la`
# le dit à voix haute au lieu d'échouer — parce qu'un agent qui vient de
# corriger un défaut ne doit pas trouver la suite rouge pour une écriture
# comptable.


@dataclass(frozen=True)
class Remis:
    fichier: str
    motif: str
    litteraux: tuple[str, ...]
    a_qui: str
    degat: str


CONSTATS_REMIS: tuple[Remis, ...] = (
    # ---- LE CLUSTER, NOMMÉ PAR OMISSION — la famille qu'aucun motif ne voyait
    # Le port du cluster est le TROISIÈME nom global de l'incident, et il
    # n'avait aucun motif : le motif `port` était la liste `(8000|8100)`. Une
    # commande libpq sans `-p` s'adresse au cluster PAR DÉFAUT — celui du
    # voisin, sur une machine qui suit §12 et pose un cluster par cerveau.
    Remis("bootstrap/lib/config.sh", "port", ('5432',), "bootstrap/",
          "`ARAC_DB_PORT=\"${ARAC_DB_PORT:-5432}\"` : le point de départ est le "
          "cluster de tout le monde. Un cerveau installé sans que la variable "
          "soit posée atterrit sur le cluster du voisin — et c'est là que "
          "vivent ses rôles, donc ses secrets"),
    Remis("bootstrap/lib/core.sh", "port", ('5432',), "bootstrap/",
          "le repli `-p \"${ARAC_DB_PORT:-5432}\"` de la fonction qui lance TOUT "
          "le SQL du bootstrap : si la variable manque, chaque migration part "
          "sur le cluster par défaut de la machine"),
    Remis("bootstrap/checks/verify_install.sh", "port", ('5432',), "bootstrap/",
          "le contrôle d'installation retombe lui aussi sur 5432 : il déclare "
          "alors sain — ou malade — un cerveau qui n'est pas celui qu'on "
          "vérifie. Un diagnostic qui interroge la mauvaise machine ment"),
    Remis("docs/INSTALLATION.md", "port", ('5432',), "docs/",
          "la page d'installation publie `ARAC_DB_PORT=5432` en exemple de base "
          "distante : le lecteur qui la recopie sur une machine à deux cerveaux "
          "vise le cluster du premier installé"),
    Remis("docs/PONT-MAC.md", "port", ('5432',), "docs/",
          "`ssh -N -L 5432:127.0.0.1:5432` : le tunnel d'essai fige le port du "
          "cluster des deux côtés. La ligne est là pour montrer un REFUS "
          "attendu, mais elle est copiable telle quelle"),

    # ---- LE RUNBOOK DE RESTAURATION — trois fautes sur quatre commandes -----
    Remis("bootstrap/README.md", "base", ('marc_brain_test',), "bootstrap/",
          "quatre commandes de restauration figent un nom de base dans un "
          "`createdb`, un `pg_restore`, un `psql` et un `dropdb` — et aucune ne "
          "porte `-p`. Sur une machine à un cluster par cerveau, elles créent et "
          "détruisent sur le cluster du voisin. C'est le seul geste du dépôt qui "
          "charge la mémoire de quelqu'un d'autre dans une base à soi"),
    Remis("bootstrap/README.md", "chemin_machine", ('/var/backups/arac/<le-dump>.dump',),
          "bootstrap/",
          "le dump est cherché à la RACINE COMMUNE des sauvegardes, alors que "
          "les dumps réels vivent en `/var/backups/arac/<base>/`. Le lecteur va "
          "donc chercher son dump là où se trouvent ceux des autres — et "
          "`verify_install.sh` le lui dit lui-même, à l'écran, quelques centaines "
          "de lignes plus loin"),

    # ---- LE COFFRE, LES RÔLES, LES UNITÉS — constats déjà remis, non corrigés
    Remis("db/migrations/07_roles_least_privilege_v1_6d.sql", "role",
          ('arac_memory_writer', 'arac_proposal_queue_writer'), "db/",
          "des rôles figés hors des cinq de l'incident. Un rôle est GLOBAL au "
          "cluster : le second cerveau installé retrouve ceux du premier, et "
          "leur donne des droits sur SA base — ou pire, les recrée"),
    Remis("db/migrations/07_roles_least_privilege_v1_6d_rollback.sql", "role",
          ('arac_memory_writer', 'arac_proposal_queue_writer'), "db/",
          "le rollback fige les mêmes noms : il révoquerait donc les droits du "
          "rôle du VOISIN"),
    Remis("db/migrations/proposals/2026-06-03-create-arac-review-writer-role.sql",
          "role", ('arac_review_writer',), "db/",
          "un rôle nommé en dur dans une proposition de migration : le jour où "
          "elle est appliquée, elle l'est sur le cluster entier"),
    Remis("db/migrations/proposals/2026-06-03-create-memory-review-queue.sql",
          "role", ('arac_review_writer',), "db/",
          "les GRANT de cette proposition visent un rôle figé : sur un cluster "
          "qui porte déjà le cerveau du voisin, ils lui ouvrent la file de "
          "revue de CE cerveau-ci"),
    Remis("bootstrap/checks/env_contract.toml", "unite",
          ('arac-curator-batch.service',), "bootstrap/ + control_center/",
          "le cockpit rend l'état de `arac-curator-batch.service` — un nom "
          "commun, qui n'est celui d'aucune unité posée par le bootstrap. Sur "
          "une machine neuve il rend un verdict sur une unité inexistante ; "
          "sur une machine à deux cerveaux, celui du voisin"),
    Remis("docs/EXPLOITATION.md", "unite", ('arac-backup', 'arac-curator-batch'),
          "docs/",
          "deux commandes de runbook, au fil du texte, interrogent le journal "
          "d'unités qui ne portent pas le nom du cerveau — celui du voisin, "
          "donc, ou rien du tout"),
    Remis("bootstrap/checks/verify_install.sh", "chemin_machine",
          ('/etc/arac/arac',), "bootstrap/",
          "la LEÇON qui explique le cerveau générique « arac » est écrite dans "
          "un message shell, donc dans ce qui s'exécute. À reformuler ou à "
          "dériver — le garde ne peut pas distinguer une leçon d'une valeur "
          "quand les deux sont dans la même chaîne"),

    # ---- LE COFFRE PARCOURU EN ENTIER ---------------------------------------
    Remis("deploy/ssh/rendre-pont.sh", "chemin_machine",
          ('/etc/arac/*/arac.env',), "deploy/",
          "le script parcourt le coffre de TOUS les cerveaux de la machine "
          "pour choisir le sien ; à vérifier qu'il refuse plutôt que de "
          "prendre le premier"),
    Remis("deploy/ssh/README.md", "chemin_machine", ('/etc/arac/*/arac.env',),
          "deploy/",
          "la page fait faire ce parcours du coffre commun à la main, sans dire "
          "ce qu'il faut faire quand il rend deux cerveaux"),
    Remis("ops/env.sh", "chemin_machine", ('/etc/arac/*/arac.env',),
          "ops/ (hors garde_isolement.sh)",
          "même parcours du coffre commun, dans la bibliothèque que tous les "
          "scripts d'exploitation sourcent"),

    # ---- LE COMPTE `pont` — une famille jamais nommée, vue par le motif neuf
    Remis("deploy/ssh/README.md", "chemin_machine",
          ('/home/pont/.ssh/authorized_keys',), "deploy/",
          "le compte du pont s'appelle `pont` pour toute la machine : deux "
          "cerveaux pilotés depuis deux Mac déposent leurs clés dans le MÊME "
          "`authorized_keys`, et chacune ouvre le tunnel de l'autre. Le compte "
          "lui-même n'est pas dérivé — c'est la famille « comptes système », "
          "celle que ce garde vient d'apprendre à voir"),

    # ---- LES DOSSIERS COMMUNS ------------------------------------------------
    Remis("ops/backup.sh", "chemin_machine",
          ('/tmp/units', '/tmp/units/*-backup-dirs.conf'), "ops/ (hors garde_isolement.sh)",
          "le message d'aide de la sauvegarde fait rendre les gabarits dans un "
          "répertoire commun : deux cerveaux rendus l'un après l'autre "
          "s'écrasent, et c'est le dernier rendu qui part dans /etc/tmpfiles.d"),
    Remis("docs/CONFIGURATION.md", "chemin_machine", ('/tmp/x',), "docs/",
          "le fichier de travail proposé pour éditer le coffre porte un nom "
          "commun : deux opérateurs qui suivent la page en même temps sur la "
          "même machine écrivent l'un sur l'autre, et ce qui y transite est le "
          "contenu d'un `arac.env` — donc des secrets"),
    Remis("docs/INSTALLATION.md", "chemin_machine",
          ('/opt/arac', '/tmp/arac-units'), "docs/",
          "la racine d'installation proposée est la même pour tous : deux "
          "cerveaux clonés en suivant la page se retrouvent au même endroit, et "
          "le répertoire de rendu des unités est commun"),
    Remis(".env.example", "chemin_machine", ('/opt/arac',), "racine du dépôt",
          "`ARAC_HOME=/opt/arac` dans le fichier canonique : c'est la valeur "
          "que tout le monde recopie"),
    Remis("control_center/security.py", "chemin_machine",
          ('/tmp/arac_cc', '/tmp/arac_cc/access.log',
           '/tmp/arac_cc/cc_auth_fail.log'), "control_center/",
          "hors `PrivateTmp`, deux cockpits mêlent leurs traces de "
          "consultation — c'est-à-dire QUI a lu QUELLE mémoire"),
    Remis("control_center/config.py", "chemin_machine", ('/tmp/arac_council',),
          "control_center/",
          "le répertoire des sessions du conseil est commun, et la variable "
          "que le message promet (`ARAC_COUNCIL_SESSIONS_DIR`) n'est lue nulle "
          "part : le levier annoncé n'existe pas"),
    Remis("control_center/collectors/reports_council.py", "chemin_machine",
          ('/tmp/arac_council/dryrun',), "control_center/",
          "le même répertoire commun, atteint par le collecteur : deux conseils "
          "mêlent leurs sessions de délibération"),
    Remis("deploy/nginx/ingest-tls.conf.exemple", "chemin_machine",
          ('/var/log/nginx/arac-ingest.access.log',
           '/var/log/nginx/arac-ingest.error.log'), "deploy/",
          "les journaux d'ingestion des deux cerveaux — donc les adresses "
          "clientes et les chemins — se mêlent dans un seul fichier"),
    Remis(".github/workflows/acceptance.yml", "chemin_machine",
          ('/var/backups/arac-acceptation', '/var/lib/arac-acceptation',
           '/var/log/arac-acceptation'), "CI",
          "le harnais d'intégration continue fige ses trois dossiers : deux "
          "exécutions concurrentes sur le même agent se marchent dessus"),

    # ---- LE POSTE DE TRAVAIL -------------------------------------------------
    Remis("mac/README.md", "chemin_machine", ('~/.arac/arac-sync.py',), "mac/",
          "le chemin réel est `~/.arac/<cerveau>/arac-sync.py` ; la page publie "
          "le script du foyer PARTAGÉ, dont le curseur de synchronisation fait "
          "marquer « déjà envoyées » des conversations qu'un cerveau n'a jamais "
          "reçues — la seule perte silencieuse et définitive du système"),
    Remis("docs/SAUVEGARDE.md", "chemin_machine", ('~/arac-backup.key',), "docs/",
          "la clé `age` de déchiffrement des sauvegardes porte un nom unique "
          "pour toute la session : deux cerveaux sauvegardés depuis le même "
          "poste partagent leur identité de déchiffrement, et le second "
          "`age-keygen -o` écrase la clé du premier — qui ne peut plus "
          "déchiffrer une seule de ses sauvegardes"),
    Remis("ops/restore_verify.sh", "chemin_machine", ('~/arac-backup.key',),
          "ops/ (hors garde_isolement.sh)",
          "la LEÇON qui explique qu'une clé commune est fautive est écrite dans "
          "un message shell, donc dans ce qui s'exécute — même cas que "
          "`/etc/arac/arac` dans verify_install.sh. À reformuler : le garde ne "
          "sait pas distinguer une leçon d'une valeur quand les deux sont dans "
          "la même chaîne"),
    Remis("docs/PONT-MAC.md", "chemin_machine", ('~/arac/config/brain.toml',),
          "docs/",
          "un chemin de clone commun : deux cerveaux pilotés depuis le même Mac "
          "se retrouvent au même endroit, et `brain.toml` — le fichier qui PORTE "
          "l'identité du cerveau — est celui qu'ils écrasent"),
    Remis("bootstrap/lib/services.sh", "unite",
          ('arac-*-api.service', 'arac-*-cockpit.service'), "bootstrap/",
          "le glob balaie les unités de TOUS les cerveaux de la machine : ce "
          "qu'on y lit appartient au voisin autant qu'à soi"),
    Remis("docs/COMMENT-IL-SE-SYNCHRONISE.md", "launchd",
          ('com.arac.pont.sync', 'com.arac.pont.tunnel'), "docs/",
          "une étiquette launchd est UNIQUE par session macOS : le second "
          "`launchctl bootstrap` remplace l'agent du premier, dont la "
          "synchronisation cesse sans une ligne de journal. Le SCRIPT, lui, "
          "dérive déjà l'étiquette — seule la documentation publie la commune"),
    Remis("mac/arac-pont.sh", "chemin_machine", ('$HOME/.ssh/id_ed25519_arac',),
          "mac/",
          "la clé COMMUNE du tunnel, que le script connaît sous ce nom pour "
          "migrer depuis elle. Tant qu'elle existe, deux cerveaux pilotés depuis "
          "le même Mac ouvrent leur tunnel avec la même identité — et le "
          "serveur ne peut plus distinguer lequel parle. Le garde ne la voyait "
          "PAS avant cette manche : `$HOME` suffisait à la faire passer pour "
          "dérivée"),
)


#: Ce que le balayage a effectivement rencontré. Sert à deux choses : imprimer
#: la liste en fin de session, et savoir quelle remise ne désigne plus rien.
REMIS_RENCONTRES: set[tuple[str, str, str]] = set()


def _remis(chemin: str, motif: str, litteral: str) -> Remis | None:
    for r in CONSTATS_REMIS:
        if r.fichier == chemin and r.motif == motif and litteral in r.litteraux:
            return r
    return None


def _concerne(d: Dispense, chemin: str) -> bool:
    """Cette dispense parle-t-elle de ce fichier ?"""
    if d.fichier.endswith("/"):
        return chemin.startswith(d.fichier)
    return chemin == d.fichier


def _dispensee(chemin: str, motif: str, ligne: str) -> bool:
    for d in DISPENSES:
        if not _concerne(d, chemin):
            continue
        if d.motif != "*" and motif not in d.motif.split(","):
            continue
        if not d.marqueur or d.marqueur in ligne:
            return True
    return False


def _fichiers_de(d: Dispense) -> list[Path]:
    """Les fichiers balayés que cette dispense couvre."""
    return [
        p for p in _fichiers_balayes()
        if _concerne(d, str(p.relative_to(RACINE)))
    ]


# ---------------------------------------------------------------------------
# LE GARDE
# ---------------------------------------------------------------------------


#: Ce qui occupe la place d'un nom sans en être un. `PUBLIC` est un mot-clé
#: SQL — le pseudo-rôle « tout le monde » — et `REVOKE … FROM PUBLIC` est
#: précisément le bon geste, pas la faute.
_PAS_DES_NOMS = {"PUBLIC", "CURRENT_USER", "SESSION_USER", "ALL", "NONE",
                 "POSTGRES", "TRUE", "FALSE", "NULL", "IF", "EXISTS", "NOT",
                 "ROLE", "USER", "GROUP", "SCHEMA", "DATABASE", "TABLE"}


#: Les langages où un identifiant s'écrit avec des points. `os.path`,
#: `e.target`, `socket.socket`, `k.slice` y sont indistinguables d'un nom
#: d'unité systemd — et le garde les accusait tous. LA RÈGLE QUI TRANCHE :
#: dans ces langages, une ressource de la MACHINE ne peut être nommée que dans
#: une CHAÎNE. Un identifiant nu est une variable, jamais un nom de ressource.
LANGAGES_A_POINTS = {".py", ".js", ".ts", ".jsx", ".tsx", ".mjs"}

_CHAINE = re.compile(r"\"\"\".*?\"\"\"|'''.*?'''|\"[^\"]*\"|'[^']*'")


def _dans_une_chaine(ligne: str, debut: int, fin: int) -> bool:
    return any(m.start() < debut and fin <= m.end() for m in _CHAINE.finditer(ligne))


def _est_une_ressource(motif: Motif, litteral: str, groupes: dict, groupe: str) -> bool:
    """Ce littéral désigne-t-il une ressource que deux cerveaux se disputeraient ?

    C'EST ICI QUE LE PRINCIPE VIT. On ne demande pas « ce nom porte-t-il le nom
    du produit ? » — on demande ce que la ressource EST. Et le tri se fait par
    INVERSION : ce que la distribution fournit est nommé ; tout le reste est
    présumé nôtre, donc disputé.
    """
    if litteral.upper() in _PAS_DES_NOMS or litteral.startswith("-"):
        return False
    if len(litteral) < 2:
        return False           # `$` de `"$(id -un)"` ne nomme rien
    if litteral in MOTS_DU_SHELL:
        return False
    if litteral.endswith("/") or litteral.endswith("/*"):
        # `~/.arac/` sans segment, `/home/*` : c'est la FAMILLE, pas une
        # instance que deux cerveaux se disputent.
        return False
    if motif.cle == "chemin_machine":
        return est_un_chemin_de_la_machine(litteral)
    if motif.cle == "compte":
        return litteral not in COMPTES_DU_SYSTEME
    if motif.cle == "unite":
        if UNITES_DU_SYSTEME.match(litteral):
            return False
        if litteral.isdigit():
            return False           # `2` de `2>/dev/null` n'est pas une unité
        if groupe == "arg":
            verbe = groupes.get("verbe") or ""
            if verbe not in VERBES_SYSTEMCTL or verbe in VERBES_SYSTEMCTL_SANS_UNITE:
                return False
            if litteral in VERBES_SYSTEMCTL:
                return False
        return True
    if motif.cle == "objet_global_sql":
        type_sql = (groupes.get("type") or "").strip().upper()
        # Un type peut faire plusieurs mots (`EVENT TRIGGER`, `UNIQUE INDEX`,
        # `MATERIALIZED VIEW`). C'est le PREMIER qui décide, et pas « l'un
        # d'eux » : `EVENT TRIGGER` contient le mot `TRIGGER`, qui est local,
        # alors qu'un event trigger s'applique à TOUT le DDL de la base. La
        # nuance a été trouvée par une sonde, pas par la relecture.
        if type_sql and type_sql.split()[0] in TYPES_SQL_LOCAUX:
            return False
        return True
    if motif.cle == "launchd":
        # `com.arac` est le préfixe de la FAMILLE ; c'est `com.arac.pont.sync`
        # qui est une étiquette. Moins de trois segments : rien à disputer.
        return litteral.count(".") >= 2
    return True


def _litteraux(motif: Motif, ligne: str, suffixe: str = "") -> list[str]:
    """Les littéraux NON DÉRIVÉS que ce motif reconnaît dans cette ligne.

    Un seul endroit pose les deux questions qui comptent — « est-ce une
    ressource de la machine ? » puis « ce nom est-il calculé ? » — pour tous les
    motifs. C'est ce qui empêche qu'un motif neuf oublie de reconnaître le
    remède et se mette à crier au loup sur la solution ; et un garde qui crie au
    loup apprend à ses lecteurs à l'ignorer.

    L'EXCLUSION PORTE SUR LE LITTÉRAL, PLUS SUR LA LIGNE. C'était la régression
    de la manche précédente : `ligne_exclue=r"…|postgres\\b"` désarmait le motif
    `base` sur `sudo -u postgres psql -d arac`, c'est-à-dire sur la forme exacte
    qu'il avait été écrit pour attraper.
    """
    a_points = suffixe.lower() in LANGAGES_A_POINTS
    trouves: list[str] = []
    for m in motif.rx.finditer(ligne):
        noms = motif.groupes or (0,)
        for g in noms:
            brut = m.group(g)
            if not brut:
                continue
            debut, fin = m.span(g)
            if a_points and not _dans_une_chaine(ligne, debut, fin):
                continue
            if motif.rx_prefixe is not None and motif.rx_prefixe.search(ligne[:debut]):
                continue
            c = brut.strip().strip("\"'`,;:.")
            if not c or est_derive(c):
                continue
            c = c.strip("{}").strip(".")
            if not c:
                continue
            if motif.rx_exclue is not None and motif.rx_exclue.search(c):
                continue
            if not _est_une_ressource(motif, c, m.groupdict(), g if isinstance(g, str) else ""):
                continue
            trouves.append(c)
    return trouves


def balayage() -> list[tuple[str, int, str, str]]:
    """Tout ce que le garde accuse, une bonne fois : (fichier, ligne, motif, littéral).

    Écrit une seule fois et employé par TOUS ceux qui parlent au nom du garde —
    le contrôle, la comptabilité des remises, et le bloc imprimé en fin de
    session. C'est ce qui empêche un rapport d'affirmer ce qu'il n'a pas mesuré,
    ce qui était le troisième défaut de la manche précédente.
    """
    trouves: list[tuple[str, int, str, str]] = []
    for p in _fichiers_balayes():
        rel = str(p.relative_to(RACINE))
        lignes = code_de(p)
        for motif in MOTIFS:
            for numero, ligne in lignes:
                if _dispensee(rel, motif.cle, ligne):
                    continue
                for litteral in _litteraux(motif, ligne, p.suffix):
                    trouves.append((rel, numero, motif.cle, litteral))
    return trouves


def constats_mesures() -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """Ce qui est ENCORE FIGÉ, et ce qui a été RÉPARÉ — mesurés, pas récités.

    Le bloc imprimé en fin de session parcourait `CONSTATS_REMIS` et proclamait
    « ces noms sont FIGÉS » sans avoir vérifié qu'ils y étaient encore : six des
    soixante-trois étaient réparés, dont le bloquant de la manche précédente.
    Un rapport ne doit jamais nommer ce qu'il n'a pas constaté — c'est la règle
    que ce dépôt s'impose partout ailleurs (« un 200 ne prouve rien tant qu'on
    ne sait pas QUI répond »).
    """
    rencontres = {
        (rel, cle, lit) for rel, _, cle, lit in balayage()
        if _remis(rel, cle, lit) is not None
    }
    declares = [
        (r.fichier, r.motif, lit) for r in CONSTATS_REMIS for lit in r.litteraux
    ]
    figes = [d for d in declares if d in rencontres]
    reparees = [d for d in declares if d not in rencontres]
    return figes, reparees


@pytest.mark.parametrize("motif", MOTIFS, ids=lambda m: m.cle)
def test_aucun_nom_partage_entre_cerveaux(motif: Motif) -> None:
    """Aucun nom disputable ne doit être figé dans ce qui s'exécute."""
    fautifs: list[str] = []
    for p in _fichiers_balayes():
        rel = str(p.relative_to(RACINE))
        for numero, ligne in code_de(p):
            if _dispensee(rel, motif.cle, ligne):
                continue
            for litteral in _litteraux(motif, ligne, p.suffix):
                remis = _remis(rel, motif.cle, litteral)
                if remis is not None:
                    REMIS_RENCONTRES.add((rel, motif.cle, litteral))
                    continue
                fautifs.append(f"{rel}:{numero} → {litteral!r}")

    assert not fautifs, (
        f"\n\nG1 rompu — motif « {motif.cle} » : {motif.quoi}.\n\n"
        f"  CE QU'UN SECOND CERVEAU DÉTRUIRAIT\n    {motif.degat}\n\n"
        f"  CE QU'IL FALLAIT ÉCRIRE\n    {motif.remede}\n\n"
        f"  OÙ ({len(fautifs)} occurrence(s))\n    "
        + "\n    ".join(fautifs[:40])
    )


def test_chaque_exemption_de_zone_couvre_encore_quelque_chose() -> None:
    """Une exemption de zone qui ne désigne plus rien est un angle mort gratuit.

    Le garde balaie tout le dépôt SAUF ces chemins. Chacun doit donc exister —
    sinon on transporte, d'une manche à l'autre, la permission de ne pas
    regarder un dossier que plus personne n'a. C'est ainsi qu'une liste
    d'exclusions grossit jusqu'à ce que le garde ne balaie plus rien, et que
    tout le monde continue de croire qu'il balaie tout.
    """
    ignore = (RACINE / ".gitignore")
    lignes_ignore = (
        {l.strip().rstrip("/") for l in ignore.read_text(encoding="utf-8").splitlines()}
        if ignore.is_file() else set()
    )
    for e in EXEMPTIONS_ZONE:
        assert len(e.raison) > 60, f"{e.chemin} : raison trop courte"
        if e.engendree:
            # Une zone ENGENDRÉE n'existe qu'après une commande d'installation.
            # Exiger sa présence rendait `make test PY=python3` rouge sur un
            # clone neuf — le chemin d'exécution que le Makefile documente
            # lui-même, et le seul possible avant `make venv`. Ce qui prouve
            # qu'elle appartient encore au dépôt, sans dépendre de l'état de la
            # machine, c'est qu'elle soit nommée dans `.gitignore`.
            assert e.chemin.rstrip("/") in lignes_ignore, (
                f"exemption morte : « {e.chemin} » est déclarée engendrée mais "
                "ne figure pas dans `.gitignore`. Une zone que le dépôt "
                "n'ignore pas n'est pas engendrée par lui : c'est du code qu'on "
                "a cessé de regarder."
            )
            continue
        if e.hors_git and not (RACINE / ".git").is_dir():
            # Une copie sans `.git` — une archive téléchargée. L'absence de la
            # zone ne dit rien de l'exemption ; elle dit d'où vient la copie.
            continue
        trouve = (RACINE / e.chemin).exists() or any(
            e.chemin in p.parts for p in RACINE.rglob(e.chemin)
        )
        assert trouve, (
            f"exemption morte : « {e.chemin} » n'existe nulle part dans le "
            "dépôt. Retirez-la — une permission de ne pas regarder qui ne "
            "protège plus rien finit par en couvrir autre chose."
        )


def test_le_garde_voit_tout_le_depot() -> None:
    """Le garde doit voir les GABARITS, pas seulement les scripts.

    Ce test est né d'un aveuglement précis : la liste blanche de suffixes
    ignorait `.modele` et `.exemple`, c'est-à-dire l'extension de tous les
    gabarits de `deploy/`. Le dossier était déclaré balayé et rendait un
    fichier sur huit — le garde était vert et `deploy/ssh/authorized_keys.modele`
    figeait les ports 8000 et 8100 depuis toujours.

    On vérifie donc explicitement que les territoires longtemps invisibles le
    sont redevenus, et qu'aucun fichier de `deploy/` ne manque à l'appel.
    """
    vus = {str(p.relative_to(RACINE)) for p in _fichiers_balayes()}

    for dossier in ("mac", "deploy", "control_center", "db/migrations", "app"):
        if (RACINE / dossier).is_dir():
            assert any(v.startswith(dossier + "/") for v in vus), (
                f"« {dossier}/ » existe et n'est pas balayé : le garde est "
                "redevenu aveugle sur un territoire entier."
            )

    attendus = {
        str(p.relative_to(RACINE))
        for p in (RACINE / "deploy").rglob("*")
        if p.is_file() and p.suffix.lower() not in SUFFIXES_BINAIRES
    }
    assert attendus <= vus, (
        "des gabarits de deploy/ échappent au garde : "
        f"{sorted(attendus - vus)}. C'est l'aveuglement d'origine — une liste "
        "blanche de suffixes qui oublie précisément les extensions des "
        "gabarits."
    )


def test_chaque_dispense_sert_encore() -> None:
    """Une dispense qui ne couvre plus rien est une porte laissée ouverte.

    CE CONTRÔLE NE POUVAIT PAS TUER LA PLUS LARGE DES DISPENSES, ET C'ÉTAIT SON
    DÉFAUT. Pour une dispense « tout motif » sur un DOSSIER, il calculait
    `any(...)` sur cent-vingt fichiers et tous les motifs à la fois : vrai pour
    toujours dès qu'un seul test citait un seul nom, ce que la suite garantit
    par construction. La dispense qui silencie le plus de choses était la seule
    qu'on ne pouvait jamais déclarer morte.

    On exige maintenant que la dispense soit justifiée MOTIF PAR MOTIF. Une
    dispense qui silencie un motif sans qu'aucune ligne ne le porte est une
    permission gratuite, et elle doit être retirée de la liste — c'est pourquoi
    `tests/` ne dit plus « * » mais nomme les sept motifs dont il a besoin.
    """
    cles = {m.cle for m in MOTIFS}
    for d in DISPENSES:
        assert len(d.raison) > 80, f"{d.motif}/{d.fichier} : raison trop courte"
        cible = RACINE / d.fichier.rstrip("/")
        assert cible.is_file() or cible.is_dir(), f"dispense morte : {d.fichier}"
        fichiers = _fichiers_de(d)
        assert fichiers, (
            f"dispense morte : {d.fichier} ne couvre plus aucun fichier balayé."
        )
        vises = cles if d.motif == "*" else set(d.motif.split(","))
        assert vises <= cles, f"motif inconnu dans la dispense {d.fichier} : {vises - cles}"

        lignes = [
            ligne
            for p in fichiers
            for _, ligne in code_de(p)
            if not d.marqueur or d.marqueur in ligne
        ]
        for cle in sorted(vises):
            motif = next(m for m in MOTIFS if m.cle == cle)
            sert = any(_litteraux(motif, ligne) for ligne in lignes)
            assert sert, (
                f"dispense trop large : {d.fichier} silencie le motif "
                f"« {cle} », et aucune ligne couverte ne le porte plus. "
                "Retirez ce motif de la dispense — une permission de ne pas "
                "regarder qui ne protège rien finit toujours par couvrir "
                "autre chose. (La dispense qui disait « * » sur un dossier "
                "entier ne pouvait, elle, jamais être prise en défaut.)"
            )


def test_chaque_constat_remis_designe_un_fichier_vivant() -> None:
    """Une remise doit pointer un fichier qui existe, et nommer son destinataire.

    Ce contrôle-ci ÉCHOUE, contrairement au suivant : une remise qui désigne un
    fichier disparu ne remet plus rien à personne, et l'oublier reviendrait à
    transporter d'une manche à l'autre une permission de ne pas regarder.
    """
    for r in CONSTATS_REMIS:
        assert (RACINE / r.fichier).is_file(), (
            f"remise morte : {r.fichier} n'existe plus. Retirez-la, ou "
            "corrigez-la si le fichier a été renommé."
        )
        assert r.motif in {m.cle for m in MOTIFS}, r.motif
        assert r.litteraux, f"{r.fichier} : une remise sans littéral ne dit rien"
        assert len(r.degat) > 60, (
            f"{r.fichier} : le dégât est trop court. Une remise qui ne dit pas "
            "ce qui casse se recopie sans être lue."
        )
        assert r.a_qui, f"{r.fichier} : une remise sans destinataire est un oubli"


def test_les_constats_remis_sont_encore_la() -> None:
    """Un constat réparé doit se DIRE, pas faire rougir la suite de quelqu'un.

    C'est un choix, et il se défend. La doctrine de ce dépôt est qu'une
    dispense morte est une porte ouverte, et qu'elle doit donc échouer. Une
    remise n'est pas une dispense : elle décrit une faute qui appartient à un
    AUTRE périmètre, et que quelqu'un d'autre est en train de corriger. Faire
    échouer `make test` chez celui qui vient de réparer, pour une écriture
    comptable qui n'est pas la sienne, le pousserait à retirer la ligne sans la
    lire — ou à ne plus lancer la suite. On le dit à voix haute, à la place.
    """
    for rel, _, cle, litteral in balayage():
        if _remis(rel, cle, litteral) is not None:
            REMIS_RENCONTRES.add((rel, cle, litteral))

    reparees = [
        (r.fichier, r.motif, lit)
        for r in CONSTATS_REMIS
        for lit in r.litteraux
        if (r.fichier, r.motif, lit) not in REMIS_RENCONTRES
    ]
    if reparees:  # pragma: no cover — dépend de l'état du dépôt
        print(
            "\nCONSTATS REMIS QUI ONT ÉTÉ RÉPARÉS — retirez-les de "
            "CONSTATS_REMIS :\n  "
            + "\n  ".join(f"{f}: {m} → {l!r}" for f, m, l in reparees)
        )

# ---------------------------------------------------------------------------
# CE QUE LE GARDE NE COUVRE PAS — et pourquoi il le dit lui-même
# ---------------------------------------------------------------------------
#
# UN GARDE QUI MENT SUR SA COUVERTURE EST PIRE QU'UN GARDE ABSENT : il donne
# confiance, et la confiance est ce qui empêche de regarder. La manche
# précédente a écrit « on décrit la FORME, pas les instances : un défaut d'une
# famille neuve est vu le jour où il apparaît » — c'était faux, et personne
# n'est allé vérifier pendant deux manches.
#
# Ce bloc est la contrepartie du nouveau principe. Chaque entrée est une zone
# que le garde NE VOIT PAS, avec la raison mécanique, et — quand il y en a un —
# un exemple RÉEL du dépôt, mesuré, à corriger par quelqu'un d'autre. Il est
# imprimé en fin de session, à côté des remises.


@dataclass(frozen=True)
class ZoneAveugle:
    zone: str
    pourquoi: str
    exemple: str = ""     # fichier:ligne réel, quand il en existe un


ZONES_NON_COUVERTES: tuple[ZoneAveugle, ...] = (
    ZoneAveugle(
        "le FLOT des variables",
        "Le garde lit une LIGNE, pas un programme. `$U_API.service` est tenu "
        "pour dérivé sans que rien ne prouve d'où sort `U_API` ; si quelqu'un "
        "écrivait `U_API=arac-api`, le garde resterait vert. Voir d'où vient une "
        "valeur demanderait une analyse de flot, que ce garde ne fait pas. Ce "
        "qu'il refuse, en revanche, ce sont les substitutions qui ne PEUVENT PAS "
        "nommer un cerveau — `$HOME`, `$USER`, `%i` — et c'était la régression "
        "de la manche précédente.",
        "bootstrap/lib/config.sh",
    ),
    ZoneAveugle(
        "la PROSE, et les colonnes d'explication d'un tableau",
        "Un chemin cité au fil d'une phrase n'est pas retenu : la prose de ce "
        "dépôt est sa valeur, et `docs/CONFIGURATION.md:443` explique mot pour "
        "mot que « /var/backups/arac est commun à la machine ». Retenir la prose "
        "ferait accuser la phrase écrite pour nous avertir. Le prix est réel et "
        "il est payé : « copiée en `~/.arac/pont.conf` », dans une colonne "
        "d'explication, n'est PAS vue — et c'est un vrai foyer partagé.",
        "mac/README.md",
    ),
    ZoneAveugle(
        "les exécutables déposés dans /usr/local/bin",
        "`/usr/local/bin` est déclaré fourni par le système, sinon le garde "
        "accuserait `for chemin in /usr/local/bin/autossh` — un outil TIERS "
        "qu'on y cherche. Il ne sait pas distinguer chercher de déposer. "
        "Conséquence mesurée : `/usr/local/bin/arac-depot-sauvegardes`, un "
        "exécutable que la page de sauvegarde fait DÉPOSER sous un nom commun à "
        "la machine, échappe au garde. À corriger à la main, dans docs/.",
        "docs/SAUVEGARDE.md",
    ),
    ZoneAveugle(
        "les suffixes d'unité confusables : .target, .slice, .socket, .mount, .path",
        "En Python et en JavaScript, `e.target`, `k.slice`, `socket.socket` et "
        "`os.path` sont indistinguables d'un nom d'unité systemd. La forme nue "
        "ne retient donc que `.service`, `.timer` et `.automount` ; les autres "
        "ne sont vus qu'en POSITION (`systemctl enable x.target`, "
        "`WantedBy=x.target`). Un produit qui poserait sa propre `.target` sans "
        "jamais l'armer resterait invisible — mais une unité qu'on n'arme pas ne "
        "tourne pas.",
    ),
    ZoneAveugle(
        "un nom donné par OMISSION — COUVERT DEPUIS, PAR UN AUTRE GARDE",
        "`sudo -u postgres dropdb <votre_base>` sans `-p` s'adresse au cluster "
        "PAR DÉFAUT — donc à celui du voisin, sur une machine qui suit la "
        "recommandation d'un cluster par cerveau. Le nom du cluster n'est écrit "
        "NULLE PART : il est donné par son absence, et un garde qui interroge "
        "des littéraux ne peut pas voir une absence. CE GARDE-CI NE LA VOIT "
        "TOUJOURS PAS, et c'est pourquoi la zone reste écrite ici. Ce qui a "
        "changé : le contrôle d'une autre nature qu'elle appelait EXISTE — "
        "`tests/test_g3_toute_commande_imprimee_porte_son_port.py`. Et il ne "
        "porte pas le périmètre que cette zone lui donnait. « docs/, bootstrap/ "
        "ou ops/ » était une liste de RÉPERTOIRES, c'est-à-dire le même défaut "
        "de forme d'un cran au-dessus : le seul `dropdb` sans `-p` du dépôt "
        "vivait dans `db/alembic/versions/`, hors des trois, et il était "
        "IMPRIMÉ au moment d'une panne. G3 balaie donc le même corpus que G1 — "
        "tout ce que git transporte.",
        "db/alembic/versions/0001_baseline_phase1b.py",
    ),
    ZoneAveugle(
        "un VERBE de revendication hors du vocabulaire des motifs",
        "La porte « LA PLACE » ne reconnaît pas une revendication : elle "
        "reconnaît les verbes et les champs écrits dans MOTIFS — useradd, "
        "CREATE ROLE, createdb, --port, listen, zone=, WantedBy=, "
        "StateDirectory=, pg_create_logical_replication_slot. C'est une "
        "quatrième énumération, et elle oublie comme toutes les autres. "
        "MESURÉ sur vingt familles neuves : QUINZE sont invisibles, et les "
        "cinq vues ne l'ont été que par LE TERRITOIRE (un chemin absolu "
        "traînait sur la ligne), jamais parce que le verbe a été reconnu. "
        "Restent aveugles : ip netns, ip link, dmsetup, mkfs -L, zfs, btrfs, "
        "lvcreate, setcap, update-alternatives, mkfifo. Et `sysctl -w "
        "net.core.somaxconn` n'est vu QUE par coïncidence — le motif launchd "
        "cherche des étiquettes en DNS inversé ; écrit sans point, le même "
        "réglage redevient invisible. On ne compte pas les coups de chance. On "
        "n'ajoute pas quinze motifs pour des outils que ce dépôt n'emploie "
        "pas : sa propre doctrine dit qu'un motif pour une technologie absente "
        "rend le même vert qu'un motif qui n'existe pas. On écrit la limite, "
        "et `test_la_zone_du_vocabulaire_ferme_dit_encore_vrai` la MESURE à "
        "chaque passage.",
    ),
    ZoneAveugle(
        "ce qu'un cerveau fait SUBIR à un démon partagé",
        "`systemctl restart postgresql` coupe la base des DEUX cerveaux. C'est "
        "un vrai dégât croisé, et il n'a pas de remède nominatif : on ne dérive "
        "pas `postgresql`. G1 garde des NOMS ; celui-là demande un garde de "
        "GESTES, qui reste à écrire.",
        "bootstrap/lib/database.sh",
    ),
    ZoneAveugle(
        "les commentaires impératifs",
        "`code_de()` retire toute ligne qui commence par `#`, au nom de la règle "
        "« on n'accuse pas une leçon ». Mais « # GABARIT tmpfiles.d — à copier "
        "dans /etc/tmpfiles.d/arac-backup.conf » n'est pas une leçon : c'est une "
        "instruction, et elle nomme un fichier commun à toute la machine. "
        "Distinguer les deux demanderait de lire l'intention d'une phrase.",
        "ops/systemd/arac-backup-dirs.conf.template",
    ),
    ZoneAveugle(
        "les noms construits par concaténation",
        "En Python et en JavaScript, seules les CHAÎNES sont lues — un "
        "identifiant nu est une variable, jamais un nom de ressource, sinon "
        "`os.path` deviendrait une unité systemd. Un nom assemblé morceau par "
        "morceau (`\"arac-\" + role + \".service\"`) échappe donc à la forme, et "
        "n'est vu que si l'un des morceaux tombe en POSITION.",
    ),
    ZoneAveugle(
        "les objets nommés d'un démon TIERS",
        "Mesuré, en posant les lignes devant le garde : `docker network create "
        "memoire-net` et `docker run --name moteur-cycle` ne sont PAS vus. Un "
        "réseau et un conteneur portent des noms globaux au démon docker, "
        "exactement comme une zone l'est à nginx. Le garde ne les couvre pas, et "
        "il ne les couvrira pas tant que ce dépôt n'emploiera pas docker : "
        "écrire un motif pour une technologie absente, c'est fabriquer une "
        "règle que personne n'exerce — et un motif que personne n'exerce rend le "
        "même vert qu'un motif qui n'existe pas. Le jour où docker entre ici, "
        "cette ligne est la dette à payer.",
    ),
    ZoneAveugle(
        "écrire DANS un fichier de la distribution",
        "Mesuré : `echo \"127.0.0.1 cockpit.local\" | sudo tee -a /etc/hosts` "
        "n'est PAS vu. `/etc/hosts` est déclaré fourni par le système — sinon "
        "chaque `grep /etc/hosts` serait accusé — mais AJOUTER une ligne dedans "
        "est un geste qui porte sur toute la machine, et le second cerveau qui "
        "écrit le même alias emmène le trafic du premier. Le garde juge des "
        "NOMS ; celui-ci est un geste sur un nom qui ne nous appartient pas.",
    ),
    ZoneAveugle(
        "les racines de famille elles-mêmes",
        "`/etc/arac` et `~/.arac` ne sont pas accusées : ce sont les espaces de "
        "noms du produit, sous lesquels chaque cerveau reçoit le sien, et il faut "
        "bien qu'ils soient écrits quelque part. Le jour où l'un des deux "
        "deviendrait un FICHIER réellement partagé plutôt qu'un répertoire, le "
        "garde se tairait. La liste est volontairement courte — chaque entrée "
        "est une porte ouverte à l'étage du dessous.",
    ),
)


# ---------------------------------------------------------------------------
# LE GARDE ÉPROUVÉ COMME L'ÉPREUVE L'A ÉPROUVÉ
# ---------------------------------------------------------------------------
#
# CE TEST EST LA LEÇON DE LA MANCHE, RENDUE MÉCANIQUE.
#
# Le garde d'avant affirmait voir les familles neuves. Personne ne le lui a
# demandé pendant deux manches, et quand on le lui a demandé — trente-huit
# ressources partagées, onze familles — il en a vu SEPT.
#
# Un garde qui ne s'éprouve pas lui-même finit toujours par mentir : un motif
# qui ne correspond plus à rien et un motif qui n'existe pas rendent le même
# vert. On pose donc devant lui des ressources qu'il n'a JAMAIS rencontrées, on
# exige qu'il les voie, et on exige qu'il se taise sur celles qui n'en sont pas.
# Chaque sonde porte la famille qu'elle invente : si un jour l'une d'elles cesse
# d'être vue, c'est ce test-ci qui rougit, et il dit laquelle.

#: (ligne posée devant le garde, motif qui doit la voir, famille inventée)
SONDES_VUES: tuple[tuple[str, str, str], ...] = (
    ('useradd --system --shell /usr/sbin/nologin cortex-daemon',
     "compte", "un compte système dont le nom ne porte PAS celui du produit"),
    ('groupadd --system memoire',
     "compte", "un groupe système"),
    ('chown neurone:neurone "$dossier"',
     "compte", "un propriétaire de fichier"),
    ('User=aracagent',
     "compte", "le compte d'une unité systemd"),
    ('ARAC_SERVICE_USER="${ARAC_SERVICE_USER:-arac}"',
     "compte", "LE BLOQUANT DE LA MANCHE : le compte système figé en valeur par "
               "défaut — la cause n° 1 de l'incident, transposée du cluster à "
               "l'hôte, et qu'aucun motif ne voyait"),
    ('subprocess.run(["sudo", "-u", "postgres", "psql", "-d", "arac"])',
     "base", "une base nommée dans un argv de sous-processus — la forme même "
             "par laquelle du DDL a tourné des mois sur la production"),
    ('systemctl enable --now memory-brain.service',
     "unite", "une unité systemd dont le nom ne porte PAS celui du produit"),
    ('StateDirectory=cortex/data',
     "unite", "un répertoire d'état créé et détruit par systemd"),
    ('limit_req_zone $binary_remote_addr zone=ingest_bl:10m rate=30r/m;',
     "espace_nomme", "une zone mémoire nginx — globale à toute l'instance"),
    ('upstream memoire_api { server 127.0.0.1:8300; }',
     "espace_nomme", "un bloc upstream nginx"),
    ("SELECT pg_create_logical_replication_slot('cdc_flux', 'pgoutput');",
     "objet_global_sql", "un slot de réplication — global au cluster"),
    ('CREATE PUBLICATION flux_memoire FOR ALL TABLES;',
     "objet_global_sql", "une publication logique"),
    ('CREATE EVENT TRIGGER audit_ddl ON ddl_command_end EXECUTE FUNCTION f();',
     "objet_global_sql", "un event trigger — global à la base, invisible d'avant"),
    ("CREATE TABLESPACE vecteurs LOCATION '/srv/vect';",
     "objet_global_sql", "un tablespace — global au cluster"),
    ('sudo -u postgres dropdb marc_brain',
     "base", "une base en position POSITIONNELLE — le geste le plus destructeur"),
    ('CREATE DATABASE colline;',
     "base", "une base créée par DDL"),
    ('sudo -u postgres psql -d arac -c "SELECT 1"',
     "base", "LA RÉGRESSION MESURÉE : le mot « postgres » désarmait la ligne"),
    ('uvicorn app:api --port 8300',
     "port", "un port autre que les deux de l'incident"),
    ('PGPORT=5460 pg_dump -Fc -f /srv/x.dump',
     "port", "le port du cluster par variable d'environnement"),
    ('psql -p 5432 -d colline -c "SELECT 1"',
     "port", "le port du cluster de production, en position d'option"),
    ('install -d -m 0700 /var/lib/cortex/etat',
     "chemin_machine", "un chemin de la machine sans le nom du produit"),
    ('sudo cp cycle.conf /etc/cron.d/cycle-nuit',
     "chemin_machine", "un fichier déposé dans un répertoire du système"),
    ('sudo cp u.conf /etc/tmpfiles.d/memoire-backup.conf',
     "chemin_machine", "une entrée tmpfiles.d"),
    ('sudo install -m 0644 p.conf /etc/ssh/sshd_config.d/99-pont.conf',
     "chemin_machine", "un fragment de configuration sshd"),
    ('cle="$HOME/.ssh/id_ed25519_arac"',
     "chemin_machine", "LA RÉGRESSION MESURÉE : $HOME passait pour une dérivation"),
    ('ARAC_BACKUP_DIR=/var/backups/arac/%i',
     "chemin_machine", "LA RÉGRESSION MESURÉE : %i passait pour une dérivation"),
    ('sudo -u postgres pg_restore -d b /var/backups/arac/<le-dump>.dump',
     "chemin_machine", "LA RÉGRESSION MESURÉE : le chevron du NOM DE FICHIER "
                       "faisait passer le RÉPERTOIRE commun pour dérivé"),
    ('launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.exemple.pont.sync.plist',
     "chemin_machine", "un agent launchd posé dans le foyer de l'utilisateur"),
    ('<key>Label</key><string>com.exemple.pont.sync</string>',
     "launchd", "une étiquette launchd sans le nom du produit"),
    ('GRANT SELECT ON arac.memory_atoms TO arac_review_writer;',
     "role", "un rôle hors des cinq de l'incident"),
    ('CREATE ROLE cortex_writer NOLOGIN;',
     "role", "un rôle dont le nom ne porte pas celui du produit"),
    ('sudo pg_createcluster 16 principal --port 5433 --start',
     "grappe", "LE NOM D'UNE GRAPPE POSTGRESQL — famille trouvée en posant "
               "cette ligne devant le garde, qui voyait le port et pas le nom"),
    ('sudo pg_dropcluster 16 principal --stop',
     "grappe", "la destruction d'une grappe — toutes les bases du voisin"),
    ('/usr/bin/exporter --metrics-port 9187',
     "port", "un port sous un drapeau qui n'est pas `--port`"),
    ('bind = unix:/run/moteur.sock',
     "chemin_machine", "une socket d'écoute unix, précédée de « unix: »"),
    ('server_name memoire.exemple.fr;',
     "espace_nomme", "un nom d'hôte virtuel nginx — deux cerveaux qui le "
                     "partagent envoient l'ingestion de l'un chez l'autre"),
)

#: Ce sur quoi le garde doit SE TAIRE. Un garde qui crie au loup apprend à ses
#: lecteurs à l'ignorer — et c'est le jour où il a raison que plus personne ne
#: l'écoute.
SONDES_MUETTES: tuple[tuple[str, str], ...] = (
    ('ARAC_ETC="/etc/arac/$ARAC_DB"', "le remède, écrit"),
    ('systemctl restart postgresql', "un démon fourni par la distribution"),
    ('if [[ -r /etc/os-release ]]; then', "un fichier de la distribution"),
    ('prompt = texte[:8000]', "un plafond de troncature, pas un port"),
    ('PAYLOAD_MAX_CHARS = 8000', "un plafond nommé"),
    ('sudo -u postgres psql -d "$ARAC_DB" -c "SELECT 1"', "le remède, écrit"),
    ('REVOKE CONNECT ON DATABASE "$ARAC_DB" FROM PUBLIC;',
     "PUBLIC est un mot-clé SQL, pas un rôle"),
    ('journalctl -u <unité> -n 40 --no-pager', "un trou à remplir, rien de figé"),
    ('chown root:root "/etc/arac/$ARAC_DB"', "un compte du système, un chemin dérivé"),
    ('cp x /usr/share/doc/lisez-moi', "une racine fournie par la distribution"),
    ('etiquette="com.arac.$ARAC_CERVEAU.pont.sync"', "le remède, écrit"),
    ('for m in registry.REGISTRY: print(m.target)',
     "un accès d'attribut Python, pas une unité systemd"),
    ('if (ev.target && ev.target.closest) return;',
     "un accès d'attribut JavaScript, pas une unité systemd"),
    ('lock_path = os.path.join(runtime_dir, "cortex.lock")',
     "os.path n'est pas une unité systemd"),
)


def test_le_garde_voit_les_familles_qu_il_ne_connait_pas() -> None:
    """Des ressources partagées INVENTÉES, posées devant le garde.

    C'est le seul test qui compte, et c'est celui que la manche précédente
    n'avait pas : elle affirmait la propriété au lieu de l'exercer.
    """
    aveugles: list[str] = []
    for ligne, cle, famille in SONDES_VUES:
        motif = next(m for m in MOTIFS if m.cle == cle)
        # `.sh` : une sonde est écrite comme une ligne de script, pas de Python.
        if not _litteraux(motif, ligne, ".sh"):
            aveugles.append(f"[{cle}] {famille}\n        {ligne}")
    assert not aveugles, (
        "\n\nG1 EST AVEUGLE À DES RESSOURCES PARTAGÉES QU'IL PRÉTEND VOIR.\n\n"
        "  Chacune de ces lignes pose, sur la machine, un nom qu'un second\n"
        "  cerveau se disputerait. Le garde ne le voit pas.\n\n    "
        + "\n    ".join(aveugles)
    )


#: LES FAMILLES QUE « LA PLACE » NE VOIT PAS — et qui le disent elles-mêmes.
#:
#: Chacune de ces lignes revendique, sur la machine, un nom qu'un second
#: cerveau se disputerait. Aucune n'emploie un verbe du vocabulaire de
#: `MOTIFS`, et aucune ne porte de chemin absolu : ni la PLACE ni le
#: TERRITOIRE ne les attrape. Elles sont ici pour que l'affirmation « ce
#: garde est aveugle à ces familles » soit MESURÉE, pas seulement écrite —
#: c'est la règle que ce fichier s'impose partout ailleurs.
#:
#: Le dépôt n'emploie aucun de ces outils : ajouter quinze motifs morts
#: n'ajouterait aucune sécurité, seulement de la confiance. Le jour où il en
#: emploiera un, ce test le dira à voix haute.
FAMILLES_HORS_VOCABULAIRE = (
    ("ip netns add pont", "un espace de noms réseau, global à la machine"),
    ("ip link add veth0 type veth peer name veth1", "une interface réseau"),
    ("dmsetup create memoire", "une cible device-mapper"),
    ("mkfs.ext4 -L memoire /dev/sdb1", "une étiquette de système de fichiers"),
    ("zfs create tank/memoire", "un jeu de données ZFS"),
    ("btrfs subvolume create memoire", "un sous-volume btrfs"),
    ("lvcreate -n memoire -L 10G vg0", "un volume logique LVM"),
    ("setcap cap_net_bind_service=+ep bin/serveur", "une capacité posée sur un binaire"),
    ("update-alternatives --install bin/python python bin/python3 1",
     "une alternative, globale à la machine"),
    ("mkfifo tube-de-travail", "un tube nommé, dans un espace partagé"),
    # `sysctl -w net.core.somaxconn=1024` N'EST PAS DANS CETTE LISTE, et la
    # raison mérite d'être écrite : le garde le VOIT — mais par accident. Le
    # motif `launchd` cherche les étiquettes en DNS inversé (`net.core.…`
    # ressemble à `com.arac.…`), pas un réglage de noyau. Une famille vue par
    # coïncidence n'est pas une famille couverte : le jour où le réglage
    # s'écrit `sysctl -w somaxconn=1024`, elle redevient invisible. On ne
    # compte pas les coups de chance dans une couverture.
)


def test_la_zone_du_vocabulaire_ferme_dit_encore_vrai() -> None:
    """L'aveu de G1 est-il toujours exact — ni exagéré, ni périmé ?

    La ligne « c'est cette porte qui voit les familles auxquelles personne
    n'a pensé » promettait plus qu'elle ne tenait : sur vingt familles
    neuves, le garde en ratait quinze. La phrase a été corrigée et la limite
    écrite dans `ZONES_NON_COUVERTES`. Ce test empêche l'aveu de pourrir dans
    les DEUX sens : s'il devient faux parce qu'un motif a été ajouté, il le
    dit — une zone aveugle qui ne l'est plus est une excuse qui traîne.
    """
    desormais_vues: list[str] = []
    for ligne, famille in FAMILLES_HORS_VOCABULAIRE:
        for motif in MOTIFS:
            trouves = _litteraux(motif, ligne, ".sh")
            if trouves:
                desormais_vues.append(f"[{motif.cle}] {trouves} — {famille}\n        {ligne}")
    assert not desormais_vues, (
        "\n\nBONNE NOUVELLE, ET ELLE DEMANDE UN GESTE.\n\n"
        "  G1 déclare, dans ZONES_NON_COUVERTES, être aveugle aux verbes de\n"
        "  revendication hors de son vocabulaire. Ce n'est plus vrai pour les\n"
        "  lignes ci-dessous : un motif les attrape désormais.\n\n"
        "  Retirez-les de FAMILLES_HORS_VOCABULAIRE et corrigez la zone. Une\n"
        "  limite déclarée qui n'existe plus est une excuse qui traîne, et\n"
        "  elle finit par couvrir autre chose.\n\n    "
        + "\n    ".join(desormais_vues)
    )


def test_le_garde_se_tait_sur_ce_qui_n_est_pas_une_ressource() -> None:
    """Un garde qui crie au loup apprend à ses lecteurs à l'ignorer."""
    cris: list[str] = []
    for ligne, pourquoi in SONDES_MUETTES:
        suffixe = ".py" if ("os.path" in ligne or "registry" in ligne) else (
            ".js" if "ev.target" in ligne else ".sh")
        for motif in MOTIFS:
            trouves = _litteraux(motif, ligne, suffixe)
            if trouves:
                cris.append(f"[{motif.cle}] {trouves} — {pourquoi}\n        {ligne}")
    assert not cris, (
        "\n\nG1 CRIE AU LOUP.\n\n  Ces lignes ne figent aucune ressource "
        "partagée, et le garde les accuse.\n  Un garde qui accuse une leçon "
        "apprend à ses lecteurs à l'ignorer — et\n  c'est le jour où il a raison "
        "que plus personne ne l'écoute.\n\n    " + "\n    ".join(cris)
    )


def test_chaque_sonde_couvre_une_famille_distincte() -> None:
    """Les sondes doivent couvrir TOUS les motifs — sinon l'épreuve est partielle."""
    couverts = {cle for _, cle, _ in SONDES_VUES}
    manquants = {m.cle for m in MOTIFS} - couverts
    assert not manquants, (
        f"aucune sonde n'éprouve le motif « {sorted(manquants)} ». Un motif que "
        "personne n'exerce est un motif dont personne ne sait s'il vit encore."
    )


def test_le_garde_declare_ce_qu_il_ne_couvre_pas() -> None:
    """Une zone aveugle doit porter sa raison, et son exemple doit exister.

    Ce contrôle n'est pas décoratif : il empêche qu'un aveu se périme en
    silence. Une zone dont l'exemple a disparu du dépôt est un aveu qu'on
    transporte sans le relire.
    """
    assert ZONES_NON_COUVERTES, (
        "Aucune zone déclarée non couverte. Un garde qui prétend tout voir a "
        "cessé de se regarder — c'est très exactement la faute de la manche "
        "précédente."
    )
    for z in ZONES_NON_COUVERTES:
        assert len(z.pourquoi) > 120, f"{z.zone} : la raison est trop courte"
        if z.exemple:
            assert (RACINE / z.exemple).exists(), (
                f"aveu périmé : « {z.zone} » cite {z.exemple}, qui n'existe "
                "plus. Corrigez l'exemple ou retirez la zone."
            )
