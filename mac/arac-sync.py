#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
arac-sync.py — le maillon qui fait sortir vos conversations de votre machine.

===========================================================================
CE QUE FAIT CE SCRIPT, EN UNE PHRASE
===========================================================================

Il lit les conversations que vos outils Claude ont écrites sur VOTRE disque,
repère celles qui sont nouvelles ou qui ont grandi depuis la dernière fois,
et les envoie à l'API de votre cerveau — par le tunnel SSH, jamais par
l'Internet ouvert.

Il n'invente rien, il ne supprime rien, il ne parle à personne d'autre qu'à
votre serveur. Il peut être interrompu à tout moment : la fois suivante il
reprend là où il s'était arrêté.

===========================================================================
OÙ SONT LES CONVERSATIONS — ET POURQUOI C'EST LA PARTIE FRAGILE
===========================================================================

Il y a trois endroits possibles sur un Mac. Deux sont exploitables, le
troisième ne l'est pas. Ce script traite les deux premiers et vous dit
honnêtement pourquoi il ignore le troisième.

1. CLAUDE CODE (le CLI) — `~/.claude/projects/<projet>/<session>.jsonl`
   C'est la source la plus solide : des fichiers texte, un objet JSON par
   ligne, écrits EN DIRECT au fil de la session, jamais réécrits en arrière.
   Un fichier = une session ; chaque ligne porte `sessionId`, `uuid`,
   `parentUuid`, `timestamp`, `type` (user/assistant) et `message.content`.
   Cette forme est observée, pas documentée par un contrat public : elle peut
   changer avec une mise à jour du CLI. Le script est écrit en lecteur
   tolérant — une ligne qu'il ne comprend pas est comptée et ignorée, jamais
   fatale. Si un jour le compteur « lignes incomprises » explose, c'est que
   le format a bougé : c'est votre signal d'alerte.

2. CLAUDE DESKTOP / claude.ai — l'EXPORT OFFICIEL `conversations.json`
   L'application de bureau ne garde PAS vos conversations dans un fichier
   lisible (voir le point 3). La seule voie officielle et stable est
   l'export de données : dans claude.ai → Paramètres → Confidentialité →
   « Exporter les données ». Vous recevez un lien par courriel, l'archive
   contient `conversations.json` : une liste de conversations, chacune avec
   `uuid`, `name`, `created_at`, `updated_at` et `chat_messages[]`, chaque
   message portant `uuid`, `parent_message_uuid`, `sender` (human/assistant),
   `created_at`, `content[]` (blocs de texte), `attachments[]`, `files[]`.
   C'est un instantané : il faut le redemander pour rattraper la suite. Ce
   n'est pas confortable, c'est honnête — et ça ne casse pas.

3. LE STOCKAGE INTERNE DE L'APPLICATION DE BUREAU — ignoré, volontairement.
   `~/Library/Application Support/Claude/` contient un cache d'application
   (bases LevelDB/IndexedDB d'un binaire Electron), pas un journal de
   conversations. Format binaire, non documenté, susceptible de changer à
   chaque mise à jour, et la lecture d'une base LevelDB pendant que
   l'application l'a ouverte est une bonne façon de la corrompre. Ce
   framework n'y touche pas. C'est ICI que se branchera un jour un
   connecteur officiel ou une extension MCP locale : le jour où cette source
   existera, elle s'ajoutera à côté des deux autres sans rien changer au
   reste de la chaîne (voir la classe `Source` plus bas — le contrat tient
   en deux méthodes).

   `--inventaire` va regarder ces trois emplacements et vous dire ce qui
   existe RÉELLEMENT sur VOTRE machine : nombre de fichiers, extensions,
   taille. Métadonnées seulement, aucun contenu affiché, aucun envoi.

===========================================================================
CE QUE LE SCRIPT ENVOIE, ET CE QU'IL N'ENVOIE JAMAIS
===========================================================================

Envoyé : pour chaque message, un identifiant, l'identifiant du parent, le
rôle (user/assistant), le TEXTE, et l'horodatage. Plus le titre de la
conversation quand la source en donne un.

Jamais envoyé : les blocs d'outillage (tool_use / tool_result / thinking)
qui n'ont pas de champ texte, les fichiers de votre disque, et tout ce qui
ressemble à un secret — clés d'API, jetons, mots de passe, clés privées,
URL de connexion à une base : ces motifs sont remplacés par un marqueur
`[REDACTED:...]` AVANT l'envoi (voir `masquer_secrets`). Ce filtre est un
filet, pas une garantie : il attrape les formes connues.

Au PREMIER lancement, le script refuse d'envoyer quoi que ce soit. Il vous
montre d'abord ce qu'il a trouvé — combien de conversations, lesquelles,
depuis quand — et vous rend la main. Ces fichiers contiennent une vie ;
vous devez voir ce qui part avant que ça parte.

===========================================================================
IDEMPOTENCE, REPRISE, ET POURQUOI RENVOYER N'EST PAS GRAVE
===========================================================================

Le serveur déduplique lui-même : chaque message porte une clé naturelle
(son uuid, ou l'empreinte de son contenu s'il n'en a pas), et une seconde
insertion du même message est comptée « doublon » sans rien écrire. Renvoyer
tout l'historique (`--tout`) est donc sans danger — c'est le filet de
rattrapage quand vous doutez d'un trou.

L'état local (`etat-pont.json`) n'est donc qu'une OPTIMISATION : il évite de
relire et de renvoyer du connu. Il retient, par conversation, combien de
messages ont été ACQUITTÉS par le serveur et l'empreinte de ce préfixe. Si
le préfixe a changé (conversation réécrite), le script recommence cette
conversation depuis le début. Si le script est tué au milieu d'une
conversation de 4 000 messages, la reprise repart au message acquitté
suivant, pas au premier.

« ACQUITTÉ » a un sens précis : le serveur répond `received` / `inserted` /
`duplicates`. Un 2xx ne suffit PAS. On exige `received == ce qu'on a envoyé`
ET `received == inserted + duplicates`. Toute autre réponse fait échouer le
lot sans avancer le curseur — mieux vaut un renvoi inutile qu'un trou
silencieux dans la mémoire.

===========================================================================
LA LEÇON QUE CE SCRIPT PORTE — la provenance
===========================================================================

Sur le cerveau de référence, 76 % de la provenance a été perdue : un
changement de format de la référence de source a coupé le lien entre un
atome et la conversation qui l'a produit. Le savoir restait, mais plus
personne ne pouvait dire d'où il venait.

D'où la règle appliquée ici sans exception : `conversation_uid` est
l'identifiant NATIF de la source (le `sessionId` de Claude Code, l'`uuid` de
l'export), jamais un identifiant recalculé, jamais un chemin de fichier.
Un chemin déménage ; un uuid, non. Ne changez pas cette règle après la
première synchronisation : vous couperiez le fil.

===========================================================================
CONFIGURATION
===========================================================================

Tout vient de `~/.arac/<cerveau>/pont.conf` (voir `pont.conf.example`),
surchargeable par variable d'environnement, elle-même surchargeable par option
de ligne de commande. Aucun chemin n'est écrit en dur ailleurs que dans les
valeurs par défaut, toutes relatives à `$HOME` ET au nom du cerveau.

UN FOYER PAR CERVEAU. Un même poste pilote souvent deux cerveaux (le
personnel et celui d'un projet). Leurs jetons, leurs journaux et surtout leur
CURSEUR de synchronisation ne se partagent pas : un curseur commun ferait
marquer « déjà envoyées » des conversations que l'autre cerveau n'a jamais
reçues, et elles ne repartiraient plus jamais. Voir `--cerveau`.

===========================================================================
CODES DE SORTIE (launchd et les scripts appelants s'en servent)
===========================================================================

  0  tout est passé, ou il n'y avait rien à envoyer
  2  configuration invalide (il manque le node_id, le jeton, l'URL…)
  3  aucune source de conversations trouvée
  4  le serveur a refusé l'authentification ou le poste (401/403)
  5  le serveur est injoignable — tunnel fermé, 9 fois sur 10
  6  synchronisation partielle : au moins un succès ET un échec
  7  tout ce qui a été tenté a échoué
 10  annonce : rien n'a été envoyé, une confirmation est attendue

Dépendances : aucune. Python 3.9+ de la bibliothèque standard, tel qu'il
est livré avec macOS (`/usr/bin/python3`, fourni par les Command Line Tools)
ou avec n'importe quel Linux.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid as uuidlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

VERSION = "1.0"

# ---------------------------------------------------------------------------
# Limites — elles doivent rester SOUS les plafonds du serveur, jamais dessus.
# Le serveur refuse un lot de plus de 2000 messages (400) et un message de
# plus de 512 Ko. On se garde de la marge : un lot rejeté bloque toute une
# conversation, et une conversation bloquée ne se débloque pas toute seule.
# ---------------------------------------------------------------------------
MAX_MESSAGES_PAR_LOT = 2000
MAX_OCTETS_PAR_MESSAGE = 500 * 1024        # < 512 Ko, cap serveur
MAX_OCTETS_PAR_LOT = 5 * 1024 * 1024       # < 10 Mo, cap serveur
DELAIS_REESSAI_S = (1, 4, 16)              # trois tentatives, recul exponentiel
DELAI_HTTP_S = 30

MARQUEUR_TRONCATURE = (
    "\n[ARAC : contenu tronqué par la synchronisation (message trop long) — "
    "l'original est resté sur votre machine]"
)

ROLES_VALIDES = ("user", "assistant")

# Les deux types de source déclarés au serveur. Ils décident de la façon dont
# la conversation sera relue plus tard ; ne les renommez pas après coup.
TYPE_CLAUDE_CODE = "claude_code"
TYPE_DESKTOP = "desktop_chat"


# ===========================================================================
# 1. MASQUAGE DES SECRETS — avant l'envoi, toujours
# ===========================================================================
#
# Ces motifs attrapent les formes connues. Ils ne remplacent pas votre
# vigilance : si vous collez un secret d'un format exotique dans une
# conversation, il partira. La bonne habitude reste de ne pas coller de
# secrets dans une conversation.

_MOTIFS_SECRETS = (
    (re.compile(r"sk-[A-Za-z0-9_\-]{20,}"), "[REDACTED:cle-api]"),
    (re.compile(r"(?i)\bgh[pousr]_[A-Za-z0-9]{20,}"), "[REDACTED:jeton-github]"),
    (re.compile(r"(AKIA|ASIA)[A-Z0-9]{16}"), "[REDACTED:cle-aws]"),
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
        ),
        "[REDACTED:cle-privee]",
    ),
    (
        re.compile(r"eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}"),
        "[REDACTED:jwt]",
    ),
    (re.compile(r"(?i)password\s*[=:]\s*\S+"), "password=[REDACTED]"),
    (re.compile(r"(?i)bearer\s+[a-zA-Z0-9\-._~+/]{20,}"), "bearer [REDACTED]"),
    (re.compile(r"(?i)postgres(?:ql)?://[^@\s]+@"), "postgresql://[REDACTED]@"),
    (re.compile(r"(?i)token\s*[=:]\s*[A-Za-z0-9_\-]{20,}"), "token=[REDACTED]"),
)


def masquer_secrets(texte: str) -> str:
    """Remplace les motifs de secrets connus par un marqueur nommé.

    Nommé, jamais muet : un `[REDACTED:cle-api]` dans un souvenir vous dira
    plus tard qu'il y avait là quelque chose, et quoi. Un trou silencieux,
    non."""
    if not isinstance(texte, str) or not texte:
        return texte
    sortie = texte
    for motif, remplacement in _MOTIFS_SECRETS:
        sortie = motif.sub(remplacement, sortie)
    return sortie


# ===========================================================================
# 2. CONFIGURATION — fichier, puis environnement, puis ligne de commande
# ===========================================================================

CLES_CONNUES = (
    "ARAC_CERVEAU",
    "ARAC_NODE_ID",
    "ARAC_INGEST_URL",
    "ARAC_TOKEN_FILE",
    "ARAC_CLAUDE_CODE_DIR",
    "ARAC_DESKTOP_EXPORT",
    "ARAC_STATE_FILE",
    "ARAC_LOG_FILE",
    "ARAC_MAX_CONVERSATIONS",
    "ARAC_SERVEUR_SSH",
    "ARAC_PORT_API",
    "ARAC_PORT_COCKPIT",
)

# ---------------------------------------------------------------------------
# UN FOYER PAR CERVEAU — et pourquoi le contraire perdait des conversations
# ---------------------------------------------------------------------------
#
# Tous ces chemins vivaient directement sous ~/.arac, et l'URL retombait sur
# 127.0.0.1:8000. Le serveur, lui, sait depuis longtemps qu'on installe deux
# cerveaux sur une machine : ses bases, ses rôles, ses unités, ses journaux et
# ses secrets portent tous le nom du cerveau. Le POSTE ne le savait pas — alors
# qu'un même Mac pilote très naturellement deux cerveaux (le sien et celui d'un
# projet, le personnel et le professionnel).
#
# Le plus coûteux des noms partagés n'est ni le jeton ni le journal : c'est
# ARAC_STATE_FILE, LE CURSEUR. Il retient, par conversation, combien de
# messages le serveur a ACQUITTÉS. Partagé entre deux cerveaux, le pont du
# second y marque « déjà envoyées » des conversations que le premier n'a
# jamais reçues — et il ne les renverra plus JAMAIS. C'est la seule perte
# silencieuse et définitive de tout le système : pas d'erreur, pas de 403,
# pas de ligne de journal. Simplement des souvenirs qui n'existent pas.
#
# Le nom du cerveau est donc requis, et tout en découle.

DEFAUTS_FIXES = {
    "ARAC_NODE_ID": "",
    "ARAC_CLAUDE_CODE_DIR": "$HOME/.claude/projects",
    "ARAC_MAX_CONVERSATIONS": "0",
    "ARAC_SERVEUR_SSH": "",
    # AUCUN DÉFAUT POUR CES TROIS-LÀ, ET C'EST VOULU.
    #
    # « 8000 » et « http://127.0.0.1:8000/… » étaient des défauts PLAUSIBLES,
    # ce qui est exactement ce qui les rendait dangereux : sur une machine à
    # deux cerveaux, ils désignent le premier, et le pont du second y déposait
    # les conversations privées de son propriétaire. Jeton valide, poste
    # déclaré, HTTP 200 — une fuite qui se présente comme un succès.
    #
    # Vide = le pont refuse de partir et dit quoi écrire. Un refus bruyant
    # vaut infiniment mieux qu'un envoi réussi vers la mauvaise mémoire.
    "ARAC_INGEST_URL": "",
    "ARAC_PORT_API": "",
    "ARAC_PORT_COCKPIT": "",
}

#: Ce qui vit DANS le foyer du cerveau. `{f}` est ce foyer — par défaut
#: `$HOME/.arac/<cerveau>`, et le dossier du fichier nommé quand on en nomme
#: un. Le gabarit ne colle plus le nom lui-même : un nom vide produisait
#: `$HOME/.arac//etat-pont.json`, c'est-à-dire le curseur COMMUN, celui dont
#: le partage marquait « déjà envoyées » des conversations qu'un cerveau
#: n'avait jamais reçues.
DEFAUTS_PAR_CERVEAU = {
    "ARAC_TOKEN_FILE": "{f}/jeton_ingest",
    "ARAC_DESKTOP_EXPORT": "{f}/export-desktop/conversations.json",
    "ARAC_STATE_FILE": "{f}/etat-pont.json",
    "ARAC_LOG_FILE": "{f}/journal/arac-pont.log",
}

FOYER_ARAC = "$HOME/.arac"


def assainir_cerveau(nom: str) -> str:
    """Le nom du cerveau, réduit à ce qui fait un nom de dossier sûr.

    Même règle que le bootstrap côté serveur (`tr -c 'a-zA-Z0-9' '_'`, puis
    minuscules) : deux règles vaudraient deux vérités, et le poste doit
    pouvoir nommer son dossier comme le serveur nomme sa base.
    """
    return "".join(
        c if (c.isascii() and c.isalnum()) else "_" for c in nom
    ).strip("_").lower()


def cerveaux_connus() -> list[str]:
    """Les cerveaux déjà configurés sur ce poste (un dossier chacun)."""
    foyer = Path(_developper(FOYER_ARAC))
    if not foyer.is_dir():
        return []
    return sorted(
        d.name for d in foyer.iterdir()
        if d.is_dir() and (d / "pont.conf").is_file()
    )


class CerveauIndetermine(RuntimeError):
    """On ne sait pas de quel cerveau ce pont est le pont — et on ne devine pas."""


def resoudre_cerveau(demande: str | None = None) -> str:
    """Quel cerveau ce passage sert-il ?

    Dans l'ordre : ce qu'on demande (`--cerveau`), puis l'environnement
    (`ARAC_CERVEAU`, que l'unité systemd du pont pose), puis — seulement s'il
    n'y en a qu'UN de configuré — celui-là.

    Deux cerveaux configurés et rien pour trancher : on REFUSE en les nommant.
    Deviner reviendrait à choisir dans quelle mémoire déposer des
    conversations privées, ce qu'aucun défaut n'a le droit de faire.
    """
    if demande:
        return assainir_cerveau(demande)
    env = (os.environ.get("ARAC_CERVEAU") or "").strip()
    if env:
        return assainir_cerveau(env)
    connus = cerveaux_connus()
    if len(connus) == 1:
        return connus[0]
    if not connus:
        raise CerveauIndetermine(
            "Aucun cerveau n'est configuré sur ce poste.\n"
            f"     Attendu : {FOYER_ARAC}/<cerveau>/pont.conf\n"
            "     Créez-le :  mac/arac-pont.sh installer"
        )
    raise CerveauIndetermine(
        "Ce poste pilote plusieurs cerveaux ; lequel ?\n"
        "       " + "  ".join(connus) + "\n"
        "     Précisez :  --cerveau <nom>   (ou ARAC_CERVEAU=<nom>)\n"
        "     Sans cela, le pont devrait choisir DANS QUELLE MÉMOIRE déposer\n"
        "     vos conversations. Il refuse de choisir à votre place."
    )


def chemin_conf_de(cerveau: str) -> str:
    """Le fichier de configuration de CE cerveau."""
    return f"{FOYER_ARAC}/{cerveau}/pont.conf"


def foyer_de(cerveau: str) -> str:
    """Le dossier de CE cerveau sur ce poste."""
    return f"{FOYER_ARAC}/{cerveau}"


def _cerveau_du_chemin(chemin: Path) -> str:
    """Le cerveau que désigne l'emplacement d'un `pont.conf`, s'il en désigne un.

    Convention du foyer : `~/.arac/<cerveau>/pont.conf`. Un fichier posé
    ailleurs — le cas d'un essai, d'un service sans Mac, de `make acceptance` —
    ne désigne aucun cerveau, et on ne lui en invente pas : c'est le fichier
    qui fait foi, pas un nom déduit d'un dossier quelconque.
    """
    parent = chemin.parent
    if parent.parent == Path(_developper(FOYER_ARAC)):
        return assainir_cerveau(parent.name)
    return ""


def defauts_pour(cerveau: str, foyer: str | None = None) -> dict[str, str]:
    """Les valeurs par défaut, une fois le foyer de ce cerveau connu.

    `foyer` l'emporte sur `cerveau` : quand un fichier de configuration a été
    nommé explicitement, l'état, le jeton et le journal vivent À CÔTÉ de lui.
    C'est la seule règle qui ne produise jamais de chemin commun, y compris
    quand aucun nom de cerveau n'a pu être déterminé.
    """
    valeurs = dict(DEFAUTS_FIXES)
    racine = foyer if foyer else foyer_de(cerveau)
    for cle, gabarit in DEFAUTS_PAR_CERVEAU.items():
        valeurs[cle] = gabarit.format(f=racine)
    return valeurs


def _developper(valeur: str) -> str:
    """`$HOME`, `${HOME}` et `~` deviennent le vrai foyer de l'utilisateur.

    C'est ce qui permet au fichier de configuration d'être lisible à la fois
    par ce script et par `arac-pont.sh` (qui le `source`), sans qu'aucun
    chemin absolu d'aucun utilisateur n'apparaisse jamais dans le dépôt."""
    return os.path.expanduser(os.path.expandvars(valeur))


def lire_conf(chemin: Path) -> dict[str, str]:
    """Lit un fichier `CLE=valeur`. Compatible avec `source` en bash.

    Tolérant : ligne vide, commentaire, `export CLE=valeur`, guillemets
    simples ou doubles autour de la valeur. Une clé inconnue est ignorée
    en silence (elle peut servir à `arac-pont.sh`), une ligne illisible
    aussi — ce fichier ne doit jamais faire planter la synchronisation."""
    conf: dict[str, str] = {}
    if not chemin.is_file():
        return conf
    for ligne in chemin.read_text(encoding="utf-8", errors="replace").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#"):
            continue
        if ligne.startswith("export "):
            ligne = ligne[len("export "):].strip()
        if "=" not in ligne:
            continue
        cle, _, valeur = ligne.partition("=")
        cle = cle.strip()
        valeur = valeur.strip()
        if len(valeur) >= 2 and valeur[0] == valeur[-1] and valeur[0] in "\"'":
            valeur = valeur[1:-1]
        if cle:
            conf[cle] = valeur
    return conf


class Config:
    """La configuration résolue, avec la trace de d'où vient chaque valeur.

    On garde l'origine parce qu'un pont qui ne marche pas est presque
    toujours un pont mal configuré, et que « d'où vient cette valeur ? » est
    la première question du diagnostic."""

    def __init__(self, chemin_conf: Path | None = None, cerveau: str | None = None):
        # UN CHEMIN DONNÉ EXPLICITEMENT FAIT AUTORITÉ.
        #
        # `resoudre_cerveau()` était appelé INCONDITIONNELLEMENT, y compris
        # avec `--conf <fichier>`. Or dans ce cas le cerveau ne sert plus qu'à
        # calculer l'emplacement du fichier — celui-là même qu'on vient de
        # nommer — et des valeurs par défaut que le fichier fournit. Le refus
        # se déclenchait donc pour une question qui n'était plus posée :
        #
        #   · sur un poste sans aucun cerveau — un clone neuf — code 2 ;
        #   · sur un poste qui en pilote deux — la situation que ce dépôt
        #     revendique comme acquise — code 2 aussi.
        #
        # `make acceptance` était dans le premier cas : ses étapes 5 et 6
        # rendaient ÉCHEC sans que rien de F5 ni de F6 ait été mesuré.
        #
        # Le refus de deviner reste ENTIER là où il protège : quand personne
        # n'a nommé de fichier, choisir un cerveau, c'est choisir dans quelle
        # mémoire déposer des conversations privées, et on refuse toujours.
        if chemin_conf is not None:
            self.chemin_conf = Path(_developper(str(chemin_conf)))
            # Le nom reste utile — il nourrit les défauts par cerveau et
            # s'affiche dans les diagnostics. Il se lit dans l'ordre : ce
            # qu'on demande, l'environnement, puis le dossier qui PORTE le
            # fichier nommé (`~/.arac/<cerveau>/pont.conf`), qui est la
            # convention de ce foyer. À défaut, on n'invente pas de nom : le
            # fichier fait foi à lui seul.
            self.cerveau = (
                assainir_cerveau(cerveau) if cerveau
                else assainir_cerveau(os.environ.get("ARAC_CERVEAU") or "")
                or _cerveau_du_chemin(self.chemin_conf)
            )
            # L'état, le jeton et le journal vivent à côté du fichier nommé —
            # jamais dans un foyer commun, même quand le cerveau reste anonyme.
            self.foyer = str(self.chemin_conf.parent)
        else:
            self.cerveau = resoudre_cerveau(cerveau)
            self.chemin_conf = Path(_developper(chemin_conf_de(self.cerveau)))
            self.foyer = foyer_de(self.cerveau)
        fichier = lire_conf(self.chemin_conf)
        defauts = defauts_pour(self.cerveau, self.foyer)
        self.valeurs: dict[str, str] = {}
        self.origines: dict[str, str] = {}
        for cle in CLES_CONNUES:
            if cle == "ARAC_CERVEAU":
                self.valeurs[cle] = self.cerveau
                self.origines[cle] = "résolu"
                continue
            if os.environ.get(cle):
                self.valeurs[cle] = os.environ[cle]
                self.origines[cle] = "environnement"
            elif fichier.get(cle):
                self.valeurs[cle] = fichier[cle]
                self.origines[cle] = str(self.chemin_conf)
            else:
                self.valeurs[cle] = defauts[cle]
                self.origines[cle] = "défaut"

        # L'URL peut se déduire du port, qui est la valeur que l'utilisateur
        # connaît (elle est dans l'arac.env de son serveur). L'un OU l'autre
        # suffit donc ; aucun des deux, et `problemes()` le dira en clair.
        if not self.valeurs["ARAC_INGEST_URL"] and self.valeurs["ARAC_PORT_API"]:
            port = self.valeurs["ARAC_PORT_API"].strip()
            self.valeurs["ARAC_INGEST_URL"] = (
                f"http://127.0.0.1:{port}/v1/ingest/messages"
            )
            self.origines["ARAC_INGEST_URL"] = "dérivée de ARAC_PORT_API"

    def texte(self, cle: str) -> str:
        return self.valeurs[cle]

    def chemin(self, cle: str) -> Path:
        return Path(_developper(self.valeurs[cle]))

    def entier(self, cle: str) -> int:
        try:
            return int(self.valeurs[cle])
        except (TypeError, ValueError):
            try:
                return int(defauts_pour(self.cerveau, self.foyer)[cle])
            except (TypeError, ValueError, KeyError):
                return 0

    def problemes(self) -> list[str]:
        """Ce qui empêche une synchronisation de fonctionner, en clair."""
        maux: list[str] = []
        if not self.texte("ARAC_NODE_ID").strip():
            maux.append(
                "ARAC_NODE_ID est vide. C'est le nom que votre cerveau donne à ce "
                "poste ; il doit être EXACTEMENT celui de `source.node_id` dans le "
                "config/brain.toml du serveur, sinon le serveur refusera tout "
                "(403). C'est la panne n°1 du pont."
            )
        jeton = self.chemin("ARAC_TOKEN_FILE")
        if not jeton.is_file():
            maux.append(
                f"Le jeton d'ingestion est introuvable : {jeton}\n"
                "     Il se lit sur le serveur (root uniquement) :\n"
                "       sudo grep '^ARAC_API_BEARER_TOKEN=' /etc/arac/<votre-base>/arac.env\n"
                "     et se dépose ici en 0600. Il ne doit jamais entrer dans un dépôt git."
            )
        elif jeton.stat().st_mode & 0o077:
            maux.append(
                f"Le jeton {jeton} est lisible par d'autres comptes de cette "
                "machine. Corrigez : chmod 600 " + str(jeton)
            )
        url = self.texte("ARAC_INGEST_URL")
        if not url.strip():
            maux.append(
                "ARAC_INGEST_URL est vide, et ARAC_PORT_API aussi : le pont ne "
                "sait pas VERS QUEL CERVEAU envoyer.\n"
                "     Il n'y a volontairement plus de défaut. L'ancien était une "
                "valeur plausible,\n"
                "     et c'est ce qui le rendait dangereux : sur une machine qui "
                "porte deux cerveaux,\n"
                "     elle désigne le PREMIER, et vos conversations privées "
                "atterrissaient dans la\n"
                "     mémoire du voisin — avec un jeton valide et un HTTP 200.\n"
                "     Le port de VOTRE cerveau se lit sur son serveur :\n"
                "       sudo grep '^ARAC_API_PORT=' /etc/arac/<votre-base>/arac.env\n"
                f"     puis, dans {self.chemin_conf} :  ARAC_PORT_API=<ce numéro>"
            )
        elif not url.startswith(("http://127.0.0.1", "http://localhost", "https://")):
            maux.append(
                f"ARAC_INGEST_URL = {url}\n"
                "     Une URL en http:// vers autre chose que la boucle locale fait "
                "voyager vos conversations en clair. Passez par le tunnel "
                "(http://127.0.0.1:<port>) ou par https://."
            )
        return maux


# ===========================================================================
# 3. JOURNAL — une ligne humaine à l'écran, une ligne JSON dans le fichier
# ===========================================================================

class Journal:
    """Deux destinataires, deux formats.

    L'écran s'adresse à vous : phrases, français, ordre chronologique.
    Le fichier s'adresse à la machine et à votre futur diagnostic : une
    ligne JSON par événement, parsable par `jq`, jamais tronquée.

    Rien de ce qui est écrit ici ne quitte votre machine."""

    def __init__(self, chemin: Path, bavard: bool = False):
        self.chemin = chemin
        self.bavard = bavard
        try:
            chemin.parent.mkdir(parents=True, exist_ok=True)
            self._fichier = chemin.open("a", encoding="utf-8")
        except OSError:
            self._fichier = None  # jamais bloquant : on continue sans journal

    # `/` : le nom de l'événement est POSITIONNEL. Sans cela, un champ
    # nommé `nom=` (il y en a) entrerait en collision avec le paramètre.
    def evenement(self, nom: str, /, **champs: Any) -> None:
        if self._fichier is None:
            return
        enregistrement = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "evenement": nom,
        }
        enregistrement.update(champs)
        try:
            self._fichier.write(json.dumps(enregistrement, ensure_ascii=False) + "\n")
            self._fichier.flush()
        except OSError:
            pass

    def dire(self, texte: str = "") -> None:
        print(texte, flush=True)

    def detail(self, texte: str) -> None:
        if self.bavard:
            print("   · " + texte, flush=True)

    def fermer(self) -> None:
        if self._fichier is not None:
            try:
                self._fichier.close()
            except OSError:
                pass


def notifier_macos(titre: str, message: str) -> None:
    """Une notification macOS, au mieux, jamais bloquante.

    Sous launchd, personne ne lit la sortie standard. Quand une
    synchronisation échoue, c'est la seule façon de vous prévenir sans
    exiger que vous surveilliez un fichier."""
    osascript = "/usr/bin/osascript"
    if not os.path.isfile(osascript):
        return
    try:
        script = 'display notification {} with title {}'.format(
            json.dumps(message), json.dumps(titre)
        )
        subprocess.run([osascript, "-e", script], timeout=10,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


# ===========================================================================
# 4. LES SOURCES — deux méthodes, c'est tout le contrat
# ===========================================================================
#
# Une source sait faire deux choses : dire ce qu'elle contient
# (`inventaire`), et rendre les messages d'une conversation (`messages`).
# Rien d'autre. Un futur connecteur officiel, ou une extension MCP locale,
# s'ajoute en implémentant ces deux méthodes — aucune autre ligne de ce
# fichier ne change, et le reste de la chaîne (tunnel, ingestion, cycle,
# cockpit) ignore jusqu'à son existence.


class Conversation:
    """Ce qu'on sait d'une conversation AVANT de la lire en entier."""

    def __init__(self, uid: str, titre: str | None, source_type: str,
                 nb_messages: int, derniere_activite: str | None,
                 provenance: str):
        self.uid = uid
        self.titre = titre
        self.source_type = source_type
        self.nb_messages = nb_messages
        self.derniere_activite = derniere_activite
        self.provenance = provenance  # d'où elle vient sur le disque

    @property
    def cle_etat(self) -> str:
        return f"{self.source_type}:{self.uid}"


class Source:
    nom = "source"
    description = ""

    def disponible(self) -> tuple[bool, str]:
        raise NotImplementedError

    def inventaire(self) -> list[Conversation]:
        raise NotImplementedError

    def messages(self, conv: Conversation) -> tuple[list[dict], dict[str, int]]:
        raise NotImplementedError


def _texte_des_blocs(blocs: Any) -> str:
    """Concatène les blocs `{"text": ...}` d'un `content[]`.

    Les blocs `thinking`, `tool_use` et `tool_result` n'ont pas de champ
    `text` : ils sont écartés naturellement. C'est voulu — le cerveau doit
    apprendre de ce qui a été DIT, pas du câblage interne d'un outil."""
    if not isinstance(blocs, list):
        return ""
    morceaux = [b["text"] for b in blocs
                if isinstance(b, dict) and isinstance(b.get("text"), str) and b.get("text")]
    return "\n".join(morceaux)


def tronquer(contenu: str, max_octets: int = MAX_OCTETS_PAR_MESSAGE) -> str:
    """Tronque un message trop long, avec un marqueur visible.

    Sans cela, UN message pathologique fait rejeter son lot entier et bloque
    sa conversation pour toujours. Mieux vaut un message tronqué et ingéré
    qu'une conversation invisible."""
    brut = contenu.encode("utf-8")
    if len(brut) <= max_octets:
        return contenu
    coupe = brut[:max_octets].decode("utf-8", errors="ignore")
    return coupe + MARQUEUR_TRONCATURE


class SourceClaudeCode(Source):
    """`~/.claude/projects/**/*.jsonl` — les sessions du CLI Claude Code.

    Un fichier par session, une ligne JSON par événement, écrit en direct.
    On regroupe par `sessionId` et non par fichier : c'est le `sessionId`
    qui est l'identité durable d'une conversation, un fichier peut être
    déplacé ou renommé quand un projet change de dossier."""

    nom = "claude-code"
    description = "sessions du CLI Claude Code (fichiers .jsonl)"

    def __init__(self, racine: Path):
        self.racine = racine
        self._cache: dict[str, list[dict]] | None = None
        # Compteur public : c'est le signal d'alerte « le format a changé ».
        self.lignes_incomprises = 0
        self.fichiers_lus = 0

    def disponible(self) -> tuple[bool, str]:
        if not self.racine.exists():
            return False, f"{self.racine} n'existe pas (Claude Code n'a jamais tourné ici ?)"
        if not any(self.racine.rglob("*.jsonl")):
            return False, f"{self.racine} existe mais ne contient aucun .jsonl"
        return True, str(self.racine)

    def _charger(self) -> dict[str, list[dict]]:
        if self._cache is not None:
            return self._cache
        groupes: dict[str, list[dict]] = {}
        if self.racine.exists():
            for fichier in sorted(self.racine.rglob("*.jsonl")):
                self.fichiers_lus += 1
                try:
                    brut = fichier.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for ligne in brut.splitlines():
                    ligne = ligne.strip()
                    if not ligne:
                        continue
                    try:
                        objet = json.loads(ligne)
                    except (json.JSONDecodeError, ValueError):
                        self.lignes_incomprises += 1
                        continue
                    if not isinstance(objet, dict):
                        self.lignes_incomprises += 1
                        continue
                    sid = objet.get("sessionId")
                    if not sid:
                        continue
                    objet["_fichier"] = str(fichier)
                    groupes.setdefault(str(sid), []).append(objet)
        self._cache = groupes
        return groupes

    @staticmethod
    def _role(ligne: dict) -> str | None:
        t = ligne.get("type")
        if t in ROLES_VALIDES:
            return t
        msg = ligne.get("message")
        if isinstance(msg, dict) and msg.get("role") in ROLES_VALIDES:
            return str(msg["role"])
        return None

    @staticmethod
    def _contenu(message: Any) -> str:
        if not isinstance(message, dict):
            return ""
        contenu = message.get("content")
        if isinstance(contenu, str):
            return contenu.strip()
        if isinstance(contenu, list):
            return _texte_des_blocs(contenu).strip()
        return ""

    def inventaire(self) -> list[Conversation]:
        sorties: list[Conversation] = []
        for sid, lignes in self._charger().items():
            utiles = [l for l in lignes if self._role(l) is not None]
            if not utiles:
                continue
            horodatages = [l.get("timestamp") for l in lignes
                           if isinstance(l.get("timestamp"), str)]
            cwd = next((l.get("cwd") for l in lignes if l.get("cwd")), None)
            titre = Path(str(cwd)).name if cwd else None
            sorties.append(Conversation(
                uid=sid,
                titre=titre,
                source_type=TYPE_CLAUDE_CODE,
                nb_messages=len(utiles),
                derniere_activite=max(horodatages) if horodatages else None,
                provenance=str(Path(lignes[0].get("_fichier", "?")).name),
            ))
        sorties.sort(key=lambda c: c.derniere_activite or "", reverse=True)
        return sorties

    def messages(self, conv: Conversation) -> tuple[list[dict], dict[str, int]]:
        stats = {"lues": 0, "ignorees_controle": 0, "ignorees_vides": 0, "tronquees": 0}
        sortie: list[dict] = []
        for ligne in self._charger().get(conv.uid, []):
            stats["lues"] += 1
            role = self._role(ligne)
            if role is None:
                stats["ignorees_controle"] += 1
                continue
            message_uuid = ligne.get("uuid")
            contenu = self._contenu(ligne.get("message"))
            tronque = tronquer(contenu)
            if tronque != contenu:
                stats["tronquees"] += 1
            if not message_uuid and not tronque:
                stats["ignorees_vides"] += 1
                continue
            sortie.append({
                "message_uuid": message_uuid,
                "parent_uuid": ligne.get("parentUuid"),
                "role": role,
                "content": masquer_secrets(tronque),
                "created_at": ligne.get("timestamp"),
            })
        return sortie, stats


class SourceExportDesktop(Source):
    """L'export officiel de claude.ai : `conversations.json`.

    Un instantané, pas un flux. On le relit en entier à chaque passage ;
    l'état local et la déduplication serveur font que seul le nouveau
    voyage réellement."""

    nom = "export-desktop"
    description = "export officiel de claude.ai (conversations.json)"

    def __init__(self, fichier: Path):
        self.fichier = fichier
        self._cache: dict[str, dict] | None = None

    def disponible(self) -> tuple[bool, str]:
        if not self.fichier.is_file():
            return False, (
                f"{self.fichier} absent — demandez l'export dans claude.ai : "
                "Paramètres → Confidentialité → Exporter les données"
            )
        return True, str(self.fichier)

    def _charger(self) -> dict[str, dict]:
        if self._cache is not None:
            return self._cache
        conversations: dict[str, dict] = {}
        if self.fichier.is_file():
            try:
                donnees = json.loads(self.fichier.read_text(encoding="utf-8", errors="replace"))
            except (OSError, json.JSONDecodeError, ValueError):
                donnees = []
            if isinstance(donnees, dict):
                # Certains exports enveloppent la liste. On accepte les deux.
                donnees = donnees.get("conversations") or []
            if isinstance(donnees, list):
                for conv in donnees:
                    if isinstance(conv, dict) and conv.get("uuid"):
                        conversations[str(conv["uuid"])] = conv
        self._cache = conversations
        return conversations

    @staticmethod
    def _role(m: dict) -> str:
        return "user" if m.get("sender") == "human" else "assistant"

    @staticmethod
    def _contenu(m: dict) -> str:
        """Texte du message, puis les marqueurs de pièces jointes.

        Une pièce jointe dont le contenu a été extrait par claude.ai est
        recopiée ; une pièce jointe sans contenu extrait laisse un marqueur
        nommé. Jamais un trou muet : plus tard, quand un souvenir vous
        paraîtra incomplet, ce marqueur vous dira pourquoi."""
        if not isinstance(m, dict):
            return ""
        base = (_texte_des_blocs(m.get("content")) or (m.get("text") or "")).strip()
        morceaux = [base]
        for piece in m.get("attachments") or []:
            if not isinstance(piece, dict):
                piece = {}
            nom = piece.get("file_name") or "sans-nom"
            type_ = piece.get("file_type") or "inconnu"
            marqueur = f"\n[ARAC pièce jointe : {nom} ({type_})]"
            extrait = piece.get("extracted_content")
            if isinstance(extrait, str) and extrait:
                morceaux.append(marqueur + "\n" + extrait)
            elif extrait:
                morceaux.append(marqueur + "\n" + str(extrait))
            else:
                morceaux.append(marqueur)
        for fic in m.get("files") or []:
            if not isinstance(fic, dict):
                fic = {}
            morceaux.append(
                f"\n[ARAC fichier joint sans contenu extrait : {fic.get('file_uuid') or 'inconnu'}]"
            )
        return "".join(morceaux).strip()

    def inventaire(self) -> list[Conversation]:
        sorties: list[Conversation] = []
        for uid, conv in self._charger().items():
            messages = conv.get("chat_messages") or []
            if not isinstance(messages, list) or not messages:
                continue
            sorties.append(Conversation(
                uid=uid,
                titre=conv.get("name") or None,
                source_type=TYPE_DESKTOP,
                nb_messages=len(messages),
                derniere_activite=conv.get("updated_at") or conv.get("created_at"),
                provenance=self.fichier.name,
            ))
        sorties.sort(key=lambda c: c.derniere_activite or "", reverse=True)
        return sorties

    def messages(self, conv: Conversation) -> tuple[list[dict], dict[str, int]]:
        stats = {"lues": 0, "ignorees_controle": 0, "ignorees_vides": 0, "tronquees": 0}
        brut = self._charger().get(conv.uid, {})
        sortie: list[dict] = []
        for m in brut.get("chat_messages") or []:
            stats["lues"] += 1
            if not isinstance(m, dict):
                stats["ignorees_vides"] += 1
                continue
            message_uuid = m.get("uuid")
            contenu = self._contenu(m)
            tronque = tronquer(contenu)
            if tronque != contenu:
                stats["tronquees"] += 1
            if not message_uuid and not tronque:
                stats["ignorees_vides"] += 1
                continue
            sortie.append({
                "message_uuid": message_uuid,
                "parent_uuid": m.get("parent_message_uuid"),
                "role": self._role(m),
                "content": masquer_secrets(tronque),
                "created_at": m.get("created_at"),
            })
        return sortie, stats


# ===========================================================================
# 5. L'ÉTAT LOCAL — une optimisation, jamais une source de vérité
# ===========================================================================

class Etat:
    """Ce que le pont retient d'un passage à l'autre.

    Écrit de façon ATOMIQUE (fichier temporaire puis `os.replace`) après
    CHAQUE lot acquitté : si la machine s'endort, se ferme ou perd le
    réseau au milieu d'une grosse conversation, ce qui est acquitté est
    acquitté, et la reprise repart exactement là."""

    VERSION = 1

    def __init__(self, chemin: Path):
        self.chemin = chemin
        self.donnees: dict[str, Any] = {
            "version": self.VERSION,
            "node_id": "",
            "premiere_synchro": None,
            "derniere_synchro": None,
            "conversations": {},
        }
        if chemin.is_file():
            try:
                charge = json.loads(chemin.read_text(encoding="utf-8"))
                if isinstance(charge, dict):
                    self.donnees.update(charge)
            except (OSError, json.JSONDecodeError, ValueError):
                # État illisible : on repart de zéro. Le serveur déduplique,
                # donc le pire qui arrive est un renvoi complet.
                pass
        self.donnees.setdefault("conversations", {})

    @property
    def vierge(self) -> bool:
        return not self.donnees.get("premiere_synchro")

    def entree(self, cle: str) -> dict[str, Any]:
        e = self.donnees["conversations"].get(cle)
        return e if isinstance(e, dict) else {}

    def poser(self, cle: str, acquittes: int, empreinte_prefixe: str,
              complete: bool) -> None:
        self.donnees["conversations"][cle] = {
            "messages_acquittes": acquittes,
            "empreinte_prefixe": empreinte_prefixe,
            "complete": complete,
            "maj": datetime.now(timezone.utc).isoformat(),
        }

    def sauver(self) -> None:
        self.donnees["derniere_synchro"] = datetime.now(timezone.utc).isoformat()
        try:
            self.chemin.parent.mkdir(parents=True, exist_ok=True)
            temporaire = self.chemin.with_suffix(self.chemin.suffix + ".tmp")
            temporaire.write_text(
                json.dumps(self.donnees, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporaire, self.chemin)
            os.chmod(self.chemin, 0o600)
        except OSError as err:
            print(f"   ! l'état n'a pas pu être écrit ({err}) — la prochaine "
                  f"synchronisation renverra ce qui vient de partir (sans dommage : "
                  f"le serveur déduplique).", file=sys.stderr)


def empreinte(messages: Iterable[dict]) -> str:
    """Empreinte stable d'une suite de messages.

    Sur l'uuid quand il existe, sur le contenu sinon — exactement la même
    règle que la clé de déduplication du serveur, pour que les deux côtés
    parlent de la même chose."""
    h = hashlib.sha256()
    for m in messages:
        cle = m.get("message_uuid") or ""
        h.update(str(cle).encode("utf-8"))
        h.update(b"\x1f")
        h.update(hashlib.sha256((m.get("content") or "").encode("utf-8")).digest())
        h.update(b"\x1e")
    return h.hexdigest()


# ===========================================================================
# 6. L'ENVOI — découpe, compression, acquittement vérifié
# ===========================================================================

def decouper(messages: list[dict]) -> list[list[dict]]:
    """Découpe en lots qui tiennent SOUS les plafonds du serveur.

    Deux plafonds, pas un : le nombre de messages ET la taille JSON. Une
    conversation de 300 messages dont un seul fait 400 Ko déborde la taille
    bien avant le nombre."""
    if not messages:
        return []
    lots: list[list[dict]] = []
    courant: list[dict] = []
    octets = 0
    for m in messages:
        taille = len(json.dumps(m, ensure_ascii=False).encode("utf-8"))
        if courant and (len(courant) >= MAX_MESSAGES_PAR_LOT
                        or octets + taille > MAX_OCTETS_PAR_LOT):
            lots.append(courant)
            courant, octets = [], 0
        courant.append(m)
        octets += taille
    if courant:
        lots.append(courant)
    return lots


def verifier_acquittement(corps: str, envoyes: int) -> tuple[bool, str | None]:
    """Un 2xx ne suffit pas. Le corps de la réponse doit compter juste.

    Le serveur répond `received` / `inserted` / `duplicates`. On exige :
      · `received == envoyés`            (rien n'a été perdu en route)
      · `received == inserted + duplicates` (rien n'a disparu à l'écriture)

    Tout le reste — corps absent, tronqué par un proxy, JSON invalide,
    champs non entiers — est un ÉCHEC. C'est délibéré : un 2xx sans preuve
    chiffrée n'est pas un succès, et un renvoi idempotent coûte infiniment
    moins cher qu'un trou invisible dans une mémoire."""
    try:
        analyse = json.loads(corps) if corps else None
    except (json.JSONDecodeError, TypeError, ValueError):
        analyse = None
    if not isinstance(analyse, dict):
        return False, "acquittement illisible (réponse vide, tronquée ou non JSON)"
    recus = analyse.get("received")
    inseres = analyse.get("inserted")
    doublons = analyse.get("duplicates")
    for valeur in (recus, inseres, doublons):
        if not isinstance(valeur, int) or isinstance(valeur, bool):
            return False, "acquittement illisible (compteurs absents ou non entiers)"
    if recus != envoyes:
        return False, f"le serveur dit avoir reçu {recus} messages, on en a envoyé {envoyes}"
    if recus != inseres + doublons:
        return False, (f"comptes incohérents côté serveur : reçus={recus}, "
                       f"insérés={inseres}, doublons={doublons}")
    return True, None


class ErreurPermanente(Exception):
    """Réessayer ne servirait à rien : c'est la configuration qui cloche."""

    def __init__(self, message: str, categorie: str):
        super().__init__(message)
        self.categorie = categorie  # "auth" | "refus" | "contrat"


class ErreurTemporaire(Exception):
    """Le serveur ou le réseau a hoqueté. On réessaie, puis on abandonne
    ce lot en laissant l'état intact."""

    def __init__(self, message: str, categorie: str = "reseau"):
        super().__init__(message)
        self.categorie = categorie


def contexte_ssl() -> ssl.SSLContext:
    """Contexte TLS pour un envoi en https://.

    Sous launchd l'environnement est minimal et les variables de certificats
    du shell n'existent pas. On tente `certifi` s'il est là, sinon le magasin
    du système. On ne désactive JAMAIS la vérification."""
    try:
        import certifi  # type: ignore
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def envoyer_lot(lot: dict, jeton: str, node_id: str, url: str,
                origine: str, reconciliation: bool,
                journal: Journal) -> tuple[int, int]:
    """Envoie UN lot, vérifie l'acquittement, rend (insérés, doublons).

    Le corps part en JSON gzippé : une conversation compresse entre 5 et 10
    fois, ce qui compte quand on remonte un historique par un tunnel.

    Lève `ErreurPermanente` ou `ErreurTemporaire` — jamais un succès vague."""
    messages = lot["messages"]
    corps = gzip.compress(json.dumps(lot, ensure_ascii=False).encode("utf-8"))
    identifiant_requete = str(uuidlib.uuid4())

    entetes = {
        "Content-Type": "application/json",
        "Content-Encoding": "gzip",
        "Authorization": f"Bearer {jeton}",
        "X-ARAC-Node-Id": node_id,
        "X-ARAC-Request-Id": identifiant_requete,
        "X-ARAC-Origin-Kind": origine,
        "User-Agent": f"arac-pont/{VERSION}",
    }
    if reconciliation:
        entetes["X-ARAC-Reconcile"] = "1"

    derniere: Exception | None = None
    for tentative, delai in enumerate((0,) + DELAIS_REESSAI_S):
        if delai:
            time.sleep(delai)
        requete = urllib.request.Request(url, data=corps, headers=entetes, method="POST")
        try:
            contexte = contexte_ssl() if url.startswith("https://") else None
            with urllib.request.urlopen(requete, timeout=DELAI_HTTP_S,
                                        context=contexte) as reponse:
                brut = reponse.read().decode("utf-8", errors="replace")
            ok, raison = verifier_acquittement(brut, len(messages))
            if not ok:
                journal.evenement("acquittement_refuse", raison=raison,
                                  requete=identifiant_requete)
                raise ErreurTemporaire(f"acquittement refusé : {raison}", "acquittement")
            analyse = json.loads(brut)
            return int(analyse["inserted"]), int(analyse["duplicates"])

        except urllib.error.HTTPError as err:
            detail = ""
            try:
                detail = err.read().decode("utf-8", errors="replace")[:400]
            except Exception:
                pass
            journal.evenement("http_erreur", code=err.code, detail=detail,
                              requete=identifiant_requete)
            if err.code in (401, 403):
                raise ErreurPermanente(
                    f"HTTP {err.code} — le serveur refuse ce poste ou ce jeton. {detail}",
                    "auth") from err
            if err.code in (400, 413, 422):
                raise ErreurPermanente(
                    f"HTTP {err.code} — le serveur a refusé le contenu du lot. {detail}",
                    "contrat") from err
            if err.code == 429 or 500 <= err.code < 600:
                derniere = ErreurTemporaire(f"HTTP {err.code} — {detail}", "serveur")
                continue
            raise ErreurPermanente(f"HTTP {err.code} — {detail}", "refus") from err

        except urllib.error.URLError as err:
            journal.evenement("reseau_erreur", raison=str(err.reason),
                              requete=identifiant_requete)
            derniere = ErreurTemporaire(f"serveur injoignable : {err.reason}", "reseau")
            continue
        except (TimeoutError, OSError) as err:
            journal.evenement("reseau_erreur", raison=str(err),
                              requete=identifiant_requete)
            derniere = ErreurTemporaire(f"serveur injoignable : {err}", "reseau")
            continue

    raise derniere if derniere else ErreurTemporaire("échec inexpliqué", "reseau")


# ===========================================================================
# 7. AFFICHAGE — l'annonce, puis le rapport
# ===========================================================================

def _abreger(texte: str | None, largeur: int) -> str:
    t = (texte or "—").replace("\n", " ").strip()
    return t if len(t) <= largeur else t[: largeur - 1] + "…"


def _date_courte(iso: str | None) -> str:
    if not iso:
        return "—"
    return str(iso)[:16].replace("T", " ")


def annoncer(journal: Journal, a_faire: list[tuple[Conversation, int, int]],
             limite_affichage: int = 25) -> None:
    """Montrer AVANT d'envoyer. C'est la règle, et elle n'a pas d'exception.

    Ces conversations contiennent une vie. Vous devez voir ce qui part."""
    total_messages = sum(reste for _, _, reste in a_faire)
    journal.dire()
    journal.dire("  CE QUI VA PARTIR DE CETTE MACHINE")
    journal.dire("  " + "─" * 68)
    journal.dire()
    journal.dire(f"  {len(a_faire)} conversation(s), {total_messages} message(s) au total.")
    journal.dire()
    if a_faire:
        journal.dire("   messages  dernière activité   source        conversation")
        journal.dire("   " + "─" * 66)
    for conv, deja, reste in a_faire[:limite_affichage]:
        marque = f"{reste:>9}"
        if deja:
            marque = f"{reste:>6} +{deja}"
        journal.dire("  {} {:<18} {:<13} {}".format(
            marque,
            _date_courte(conv.derniere_activite),
            conv.source_type,
            _abreger(conv.titre or conv.uid, 30),
        ))
    if len(a_faire) > limite_affichage:
        journal.dire(f"   … et {len(a_faire) - limite_affichage} autres.")
    journal.dire()
    journal.dire("  « +N » = N messages déjà acquittés par le serveur, qui ne repartiront pas.")
    journal.dire()


def rapport(journal: Journal, compteurs: dict[str, Any]) -> None:
    journal.dire()
    journal.dire("  RAPPORT")
    journal.dire("  " + "─" * 68)
    journal.dire(f"  trouvées sur le disque    {compteurs['trouvees']}")
    journal.dire(f"  déjà connues, ignorées    {compteurs['ignorees']}")
    journal.dire(f"  tentées                   {compteurs['tentees']}")
    journal.dire(f"  acceptées entièrement     {compteurs['reussies']}")
    journal.dire(f"  en échec                  {compteurs['echouees']}")
    journal.dire()
    journal.dire(f"  messages envoyés          {compteurs['messages_envoyes']}")
    journal.dire(f"  messages insérés          {compteurs['inseres']}")
    journal.dire(f"  messages déjà connus      {compteurs['doublons']}  (déduplication serveur)")
    if compteurs["tronques"]:
        journal.dire(f"  messages tronqués         {compteurs['tronques']}  (trop longs pour un envoi)")
    if compteurs["lignes_incomprises"]:
        journal.dire()
        journal.dire(f"  ! {compteurs['lignes_incomprises']} ligne(s) de journal illisible(s) ont été ignorées.")
        journal.dire("    Quelques-unes : normal. Beaucoup, d'un coup : le format de la")
        journal.dire("    source a probablement changé — relancez avec --inventaire.")
    if compteurs["echecs"]:
        journal.dire()
        journal.dire("  POURQUOI CE QUI A ÉCHOUÉ A ÉCHOUÉ")
        for titre, raison in compteurs["echecs"][:15]:
            journal.dire(f"   · {_abreger(titre, 34):<34} {raison}")
        if len(compteurs["echecs"]) > 15:
            journal.dire(f"   … et {len(compteurs['echecs']) - 15} autres, dans {compteurs['journal']}")
    journal.dire()


# ===========================================================================
# 8. INVENTAIRE — où sont vos conversations, sur VOTRE machine
# ===========================================================================

# LES EMPLACEMENTS QU'ON VA REGARDER — ET CELUI QUI N'EXISTAIT JAMAIS
#
# Chaque entrée porte : le LIBELLÉ générique qu'on affiche, la clé de
# configuration qui donne le chemin RÉEL quand le pont en connaît un, et le
# commentaire.
#
# La deuxième ligne — l'export claude.ai — était écrite
# « $HOME/.arac/<cerveau>/export-desktop » et développée par `_developper()`,
# qui remplace `$HOME`, `${HOME}` et `~`, mais pas `<cerveau>`. Le chemin
# TESTÉ contenait donc littéralement un chevron : il n'existe jamais, et la
# commande répondait « → absent » même quand l'export était là et qu'il venait
# d'être envoyé avec succès. Vingt-cinq lignes plus bas, le même écran
# imprimait « [✓] export-desktop … /conversations.json ». La première des trois
# commandes du pont criait au loup sur la source la plus fragile.
#
# La valeur juste était déjà calculée à quelques lignes de là : c'est
# `config.chemin('ARAC_DESKTOP_EXPORT')`. On la lit, au lieu de la deviner.
CANDIDATS_MAC = (
    ("$HOME/.claude/projects", "ARAC_CLAUDE_CODE_DIR",
     "Claude Code (CLI) — LISIBLE, c'est la source principale"),
    ("$HOME/.arac/<cerveau>/export-desktop", "ARAC_DESKTOP_EXPORT",
     "l'export officiel claude.ai que vous y déposez — LISIBLE"),
    ("$HOME/Library/Application Support/Claude", None,
     "cache interne de l'application de bureau — NON LISIBLE, voir plus bas"),
    ("$HOME/Library/Containers/com.anthropic.claudefordesktop/Data", None,
     "variante « sandbox » du même cache — NON LISIBLE"),
)


def _resoudre_candidat(brut: str, cle: str | None, config: Config) -> Path | None:
    """Le chemin RÉEL d'un candidat, ou None si on n'a pas su le résoudre.

    Rendre None n'est pas la même chose que rendre un chemin absent : un
    chemin qu'on n'a pas su résoudre ne dit RIEN de ce que la machine
    contient. C'est la règle qu'`ops/install_check.sh` applique déjà côté
    serveur — quand un contrôle ne peut pas mesurer, il ne tranche pas.
    """
    if cle == "ARAC_DESKTOP_EXPORT":
        # La configuration nomme le FICHIER (conversations.json) ; le candidat
        # décrit le DOSSIER où on le dépose.
        try:
            return config.chemin(cle).parent
        except (KeyError, TypeError, ValueError):
            return None
    if cle:
        try:
            return config.chemin(cle)
        except (KeyError, TypeError, ValueError):
            return None
    developpe = _developper(brut)
    if "<" in developpe or ">" in developpe:
        return None
    return Path(developpe)


def _inventaire_config_dir_deplace(journal: Journal, config: Config) -> None:
    """Claude Code peut ranger ses journaux AILLEURS que dans ~/.claude.

    Le CLI lit la variable d'environnement `CLAUDE_CONFIG_DIR` : quand elle est
    posée, ses transcriptions vivent dans `$CLAUDE_CONFIG_DIR/projects` et
    `~/.claude/projects` reste vide — ou pire, garde un vieil historique qui
    donne au pont l'air de fonctionner pendant qu'il n'envoie plus rien de
    récent. C'est très exactement la panne que la docstring de cette commande
    promet de détecter : « relancez-la le jour où le pont se tait ».

    On ne DÉPLACE rien tout seul : la source du pont reste ce que sa
    configuration dit. On le SIGNALE, avec le geste, et seulement quand la
    variable est réellement posée — annoncer une divergence qui n'existe pas
    serait le même défaut à l'envers.
    """
    ailleurs = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    if not ailleurs:
        return
    attendu = Path(_developper(ailleurs)) / "projects"
    try:
        configure = config.chemin("ARAC_CLAUDE_CODE_DIR")
    except (KeyError, TypeError, ValueError):
        return
    if attendu == configure:
        return
    journal.dire("  CLAUDE_CONFIG_DIR EST POSÉE — ET LE PONT NE REGARDE PAS LÀ")
    journal.dire("  " + "─" * 68)
    journal.dire(f"  Claude Code écrit ses transcriptions dans   {attendu}")
    journal.dire(f"  Le pont est configuré pour lire             {configure}")
    etat = "existe" if attendu.exists() else "n'existe pas (encore)"
    journal.dire(f"  Le premier {etat}.")
    journal.dire("  Tant que les deux diffèrent, le pont peut envoyer sans erreur")
    journal.dire("  des conversations périmées — ou plus rien du tout, en silence.")
    journal.dire("  Le geste, dans votre pont.conf :")
    journal.dire(f"      ARAC_CLAUDE_CODE_DIR={attendu}")
    journal.dire()


def inventaire(journal: Journal, config: Config) -> int:
    """Regarde, compte, n'ouvre aucun contenu, n'envoie rien.

    À lancer en premier, et à relancer le jour où le pont se tait : c'est
    la seule façon de savoir si le format d'une source a bougé sous vos
    pieds."""
    journal.dire()
    journal.dire("  CE QUE CETTE MACHINE CONTIENT")
    journal.dire("  " + "─" * 68)
    journal.dire()
    journal.dire("  Métadonnées seulement : nombre de fichiers, extensions, taille.")
    journal.dire("  Aucun contenu n'est lu, affiché ni envoyé.")
    journal.dire()

    for brut, cle, commentaire in CANDIDATS_MAC:
        chemin = _resoudre_candidat(brut, cle, config)
        journal.dire(f"  {brut}")
        journal.dire(f"     {commentaire}")
        if chemin is None:
            journal.dire("     → NON RÉSOLU : ce chemin porte un gabarit que rien n'a remplacé.")
            journal.dire("       Ce n'est pas « absent » : c'est « je n'ai pas su regarder ».")
            journal.dire()
            continue
        if str(chemin) != brut:
            journal.dire(f"     regardé ici : {chemin}")
        if not chemin.exists():
            journal.dire("     → absent")
            journal.dire()
            continue
        fichiers = 0
        octets = 0
        extensions: dict[str, int] = {}
        try:
            for f in chemin.rglob("*"):
                if f.is_file():
                    fichiers += 1
                    try:
                        octets += f.stat().st_size
                    except OSError:
                        pass
                    extensions[f.suffix or "(sans)"] = extensions.get(f.suffix or "(sans)", 0) + 1
        except (OSError, PermissionError) as err:
            journal.dire(f"     → illisible : {err}")
            journal.dire()
            continue
        principales = sorted(extensions.items(), key=lambda kv: -kv[1])[:6]
        journal.dire(f"     → {fichiers} fichier(s), {octets / 1_000_000:.1f} Mo")
        if principales:
            journal.dire("       extensions : "
                         + ", ".join(f"{e} ×{n}" for e, n in principales))
        journal.dire()

    _inventaire_config_dir_deplace(journal, config)

    journal.dire("  POURQUOI LE CACHE DE L'APPLICATION DE BUREAU N'EST PAS UNE SOURCE")
    journal.dire("  " + "─" * 68)
    journal.dire("  C'est une base LevelDB/IndexedDB d'application Electron : binaire,")
    journal.dire("  non documentée, réécrite à chaque mise à jour de l'application, et")
    journal.dire("  ouverte en écriture tant que l'application tourne — la lire pendant")
    journal.dire("  ce temps est un bon moyen de la corrompre. Ce framework n'y touche")
    journal.dire("  pas, et vous conseille de ne pas y toucher non plus.")
    journal.dire()
    journal.dire("  Les deux voies réelles restent :")
    journal.dire("   1. Claude Code (CLI) — automatique, en direct, aucun geste.")
    journal.dire("   2. L'export officiel claude.ai — manuel, complet, stable.")
    journal.dire("      claude.ai → Paramètres → Confidentialité → Exporter les données,")
    journal.dire("      puis dézippez conversations.json dans :")
    journal.dire(f"      {config.chemin('ARAC_DESKTOP_EXPORT').parent}")
    journal.dire()

    journal.dire("  CE QUE LE PONT EST CONFIGURÉ POUR LIRE")
    journal.dire("  " + "─" * 68)
    for source in construire_sources(config):
        ok, detail = source.disponible()
        journal.dire(f"  [{'✓' if ok else '×'}] {source.nom:<16} {detail}")
    journal.dire()
    return 0


# ===========================================================================
# 9. LA SYNCHRONISATION
# ===========================================================================

def construire_sources(config: Config) -> list[Source]:
    return [
        SourceClaudeCode(config.chemin("ARAC_CLAUDE_CODE_DIR")),
        SourceExportDesktop(config.chemin("ARAC_DESKTOP_EXPORT")),
    ]


ORIGINE = {
    TYPE_CLAUDE_CODE: "jsonl_export",
    TYPE_DESKTOP: "desktop_export",
}


def synchroniser(journal: Journal, config: Config, args) -> int:
    maux = config.problemes()
    if maux and not args.annonce:
        journal.dire()
        journal.dire("  LE PONT N'EST PAS PRÊT")
        journal.dire("  " + "─" * 68)
        for m in maux:
            journal.dire(f"   × {m}")
        journal.dire()
        journal.dire(f"  Configuration lue dans : {config.chemin_conf}")
        journal.dire()
        return 2

    sources = construire_sources(config)
    vivantes: list[Source] = []
    for source in sources:
        ok, detail = source.disponible()
        journal.evenement("source", nom=source.nom, disponible=ok, detail=detail)
        if ok:
            vivantes.append(source)
        else:
            journal.detail(f"source {source.nom} indisponible : {detail}")

    if not vivantes:
        journal.dire()
        journal.dire("  AUCUNE SOURCE DE CONVERSATIONS SUR CETTE MACHINE")
        journal.dire("  " + "─" * 68)
        for source in sources:
            journal.dire(f"   × {source.nom:<16} {source.disponible()[1]}")
        journal.dire()
        journal.dire("  Lancez `arac-sync.py --inventaire` : il vous dira ce qui existe")
        journal.dire("  réellement ici, et où déposer un export si besoin.")
        journal.dire()
        return 3

    etat = Etat(config.chemin("ARAC_STATE_FILE"))
    if etat.donnees.get("node_id") and etat.donnees["node_id"] != config.texte("ARAC_NODE_ID"):
        journal.dire()
        journal.dire("  ! L'identifiant de ce poste a changé depuis la dernière synchronisation :")
        journal.dire(f"    avant « {etat.donnees['node_id'] } », maintenant « {config.texte('ARAC_NODE_ID')} ».")
        journal.dire("    Le serveur range les conversations par poste : changer ce nom")
        journal.dire("    crée un SECOND poste, il ne renomme pas le premier.")
        journal.dire()
    etat.donnees["node_id"] = config.texte("ARAC_NODE_ID")

    # --- Quoi envoyer ------------------------------------------------------
    a_faire: list[tuple[Source, Conversation, list[dict], int]] = []
    compteurs: dict[str, Any] = {
        "trouvees": 0, "ignorees": 0, "tentees": 0, "reussies": 0, "echouees": 0,
        "messages_envoyes": 0, "inseres": 0, "doublons": 0, "tronques": 0,
        "lignes_incomprises": 0, "echecs": [],
        "journal": str(config.chemin("ARAC_LOG_FILE")),
    }

    for source in vivantes:
        for conv in source.inventaire():
            compteurs["trouvees"] += 1
            if args.conversation and conv.uid != args.conversation:
                continue
            messages, stats = source.messages(conv)
            compteurs["tronques"] += stats.get("tronquees", 0)
            if not messages:
                compteurs["ignorees"] += 1
                continue
            entree = etat.entree(conv.cle_etat)
            deja = 0
            if not args.tout and entree:
                acquittes = int(entree.get("messages_acquittes", 0))
                if 0 < acquittes <= len(messages):
                    if entree.get("empreinte_prefixe") == empreinte(messages[:acquittes]):
                        deja = acquittes
                    # sinon : le préfixe a changé, on renvoie tout depuis zéro.
            if deja >= len(messages):
                compteurs["ignorees"] += 1
                continue
            a_faire.append((source, conv, messages, deja))

    for source in vivantes:
        if isinstance(source, SourceClaudeCode):
            compteurs["lignes_incomprises"] += source.lignes_incomprises

    resume = [(conv, deja, len(messages) - deja) for _, conv, messages, deja in a_faire]

    if not a_faire:
        journal.dire()
        journal.dire(f"  Rien de nouveau. {compteurs['trouvees']} conversation(s) sur "
                     f"le disque, toutes déjà connues du serveur.")
        journal.dire()
        etat.sauver()
        journal.evenement("rien_a_faire", trouvees=compteurs["trouvees"])
        return 0

    # --- L'annonce : montrer avant d'envoyer -------------------------------
    doit_annoncer = args.annonce or (etat.vierge and not args.jenvoie)
    if doit_annoncer:
        annoncer(journal, resume)
        if args.annonce:
            journal.dire("  Rien n'a été envoyé (mode annonce).")
            journal.dire()
            return 10
        journal.dire("  " + "─" * 68)
        journal.dire("  C'est la PREMIÈRE synchronisation de ce poste. Rien n'est parti.")
        journal.dire()
        journal.dire("  Regardez la liste ci-dessus. Ce sont vos conversations : elles")
        journal.dire("  vont quitter cette machine pour votre serveur, par le tunnel SSH.")
        journal.dire("  Si quelque chose ne doit pas partir, retirez-le du disque ou")
        journal.dire("  restreignez ARAC_CLAUDE_CODE_DIR maintenant — après, ce sera au")
        journal.dire("  serveur qu'il faudra le demander.")
        journal.dire()
        journal.dire("  Quand vous êtes prêt :")
        journal.dire("      arac-sync.py --jenvoie")
        journal.dire()
        journal.evenement("annonce", conversations=len(a_faire),
                          messages=sum(r for _, _, r in resume))
        return 10

    limite = config.entier("ARAC_MAX_CONVERSATIONS")
    if args.limite:
        limite = args.limite
    if limite > 0 and len(a_faire) > limite:
        journal.dire(f"  ({len(a_faire)} conversations à envoyer, plafond réglé à "
                     f"{limite} pour ce passage — le reste suivra au prochain.)")
        a_faire = a_faire[:limite]

    jeton = config.chemin("ARAC_TOKEN_FILE").read_text(encoding="utf-8").strip()
    node_id = config.texte("ARAC_NODE_ID")
    url = args.vers or config.texte("ARAC_INGEST_URL")

    journal.dire()
    journal.dire(f"  Envoi de {len(a_faire)} conversation(s) vers {url}")
    journal.dire(f"  poste déclaré : « {node_id} »")
    journal.dire()

    debut = time.time()
    for source, conv, messages, deja in a_faire:
        restants = messages[deja:]
        titre = conv.titre or conv.uid
        compteurs["tentees"] += 1
        journal.evenement("conversation_debut", uid=conv.uid,
                          source=conv.source_type, messages=len(restants),
                          deja_acquittes=deja)

        acquittes = deja
        echec: str | None = None
        for lot_messages in decouper(restants):
            lot = {
                "source_type": conv.source_type,
                "conversation_uid": conv.uid,
                "messages": lot_messages,
            }
            if conv.titre:
                lot["title"] = conv.titre
            try:
                inseres, doublons = envoyer_lot(
                    lot, jeton, node_id, url,
                    ORIGINE.get(conv.source_type, "jsonl_export"),
                    args.tout, journal,
                )
            except ErreurPermanente as err:
                echec = str(err)
                if err.categorie == "auth":
                    # Inutile de continuer : tout échouera pareil.
                    journal.dire(f"   × {_abreger(titre, 40)} — {echec}")
                    compteurs["echouees"] += 1
                    compteurs["echecs"].append((titre, echec))
                    etat.sauver()
                    return conclure(journal, compteurs, 4, debut, config)
                break
            except ErreurTemporaire as err:
                echec = str(err)
                break

            acquittes += len(lot_messages)
            compteurs["messages_envoyes"] += len(lot_messages)
            compteurs["inseres"] += inseres
            compteurs["doublons"] += doublons
            etat.poser(conv.cle_etat, acquittes,
                       empreinte(messages[:acquittes]),
                       complete=(acquittes >= len(messages)))
            etat.sauver()   # après CHAQUE lot : c'est ce qui rend la reprise exacte

        if echec:
            compteurs["echouees"] += 1
            compteurs["echecs"].append((titre, echec))
            journal.dire(f"   × {_abreger(titre, 40)} — {echec}")
            journal.evenement("conversation_echec", uid=conv.uid, raison=echec,
                              acquittes=acquittes)
        else:
            compteurs["reussies"] += 1
            journal.dire(f"   ✓ {_abreger(titre, 40)} — {len(restants)} message(s)")
            journal.evenement("conversation_ok", uid=conv.uid, messages=len(restants))

    if etat.vierge:
        etat.donnees["premiere_synchro"] = datetime.now(timezone.utc).isoformat()
    etat.sauver()

    if compteurs["echouees"] == 0:
        code = 0
    elif compteurs["reussies"] == 0:
        code = 7
    else:
        code = 6
    return conclure(journal, compteurs, code, debut, config)


def conclure(journal: Journal, compteurs: dict[str, Any], code: int,
             debut: float, config: Config) -> int:
    rapport(journal, compteurs)
    journal.dire(f"  ({time.time() - debut:.1f} s — journal détaillé : "
                 f"{config.chemin('ARAC_LOG_FILE')})")
    journal.dire()
    journal.evenement("fin", code=code, **{k: v for k, v in compteurs.items()
                                           if k != "echecs"})
    if code == 4:
        # Le code HTTP dit LEQUEL des deux refus s'est produit, et les gestes
        # ne sont pas les mêmes. Les confondre envoie chercher un node_id
        # quand c'est un jeton qui manque — et l'inverse. La règle tient en
        # une ligne : jeton absent ou inconnu -> 401 ; jeton valide mais poste
        # non déclaré -> 403.
        journal.dire("  Le serveur a refusé. Le code HTTP ci-dessus dit lequel des deux :")
        journal.dire()
        journal.dire("  401 — le JETON est absent ou inconnu (le lieu d'où vous appelez")
        journal.dire("        n'y est pour rien : il est exigé de toute requête) :")
        journal.dire("   1. ARAC_TOKEN_FILE absent de pont.conf, ou fichier introuvable ;")
        journal.dire("   2. un saut de ligne parasite dans le fichier de jeton ;")
        journal.dire("   3. rotation côté serveur non répercutée ici.")
        journal.dire()
        journal.dire("  403 — le jeton est bon, mais ce POSTE n'est pas déclaré :")
        journal.dire("   1. ARAC_NODE_ID ne correspond pas à `source.node_id` du serveur ;")
        journal.dire("   2. le poste n'est pas dans ARAC_INGEST_ALLOWED_NODES côté serveur.")
        journal.dire()
        notifier_macos("ARAC — pont refusé",
                       "Le serveur refuse ce poste. Voir le journal du pont.")
    elif code in (5, 7):
        notifier_macos("ARAC — synchronisation en échec",
                       "Aucune conversation n'a pu être envoyée.")
    elif code == 6:
        notifier_macos("ARAC — synchronisation partielle",
                       f"{compteurs['echouees']} conversation(s) en échec.")
    return code


# ===========================================================================
# 10. POINT D'ENTRÉE
# ===========================================================================

def analyser_arguments(argv: list[str]):
    p = argparse.ArgumentParser(
        prog="arac-sync.py",
        description="Envoie les conversations locales vers l'API de votre cerveau.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Les trois commandes qui comptent :

  arac-sync.py --inventaire     où sont vos conversations, sur cette machine
  arac-sync.py --annonce        ce qui partirait, sans rien envoyer
  arac-sync.py --jenvoie        envoie (obligatoire au premier lancement)

Ensuite, `arac-sync.py` tout court suffit : c'est ce que fait launchd.

Codes de sortie : 0 ok · 2 config · 3 pas de source · 4 refus serveur ·
5 réseau · 6 partiel · 7 tout en échec · 10 annonce (rien envoyé).
""",
    )
    p.add_argument("--cerveau", metavar="NOM", default=None,
                   help="de quel cerveau ce pont est le pont (défaut : le seul "
                        "configuré ; refuse de deviner s'il y en a plusieurs)")
    p.add_argument("--conf", type=Path, default=None,
                   help="fichier de configuration "
                        "(défaut : ~/.arac/<cerveau>/pont.conf)")
    p.add_argument("--inventaire", action="store_true",
                   help="montre où sont les conversations sur cette machine, n'envoie rien")
    p.add_argument("--annonce", action="store_true",
                   help="montre ce qui partirait, n'envoie rien")
    p.add_argument("--jenvoie", action="store_true",
                   help="confirme l'envoi (exigé au premier lancement)")
    p.add_argument("--tout", action="store_true",
                   help="ignore l'état local et renvoie TOUT (le serveur déduplique)")
    p.add_argument("--conversation", metavar="UID", default=None,
                   help="ne traite qu'une conversation, par son identifiant natif")
    p.add_argument("--limite", type=int, default=0, metavar="N",
                   help="au plus N conversations pour ce passage")
    p.add_argument("--vers", metavar="URL", default=None,
                   help="URL d'ingestion (surcharge la configuration)")
    p.add_argument("--bavard", action="store_true", help="plus de détails à l'écran")
    p.add_argument("--version", action="version", version=f"arac-sync {VERSION}")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = analyser_arguments(argv if argv is not None else sys.argv[1:])
    try:
        config = Config(args.conf, cerveau=args.cerveau)
    except CerveauIndetermine as e:
        # Code 2 = configuration. On ne part pas : choisir à la place de
        # l'utilisateur reviendrait à choisir dans quelle mémoire déposer ses
        # conversations privées.
        print(f"\n  × {e}\n", file=sys.stderr)
        return 2
    journal = Journal(config.chemin("ARAC_LOG_FILE"), bavard=args.bavard)
    journal.evenement("depart", version=VERSION,
                      mode=("inventaire" if args.inventaire
                            else "annonce" if args.annonce else "synchronisation"))
    try:
        if args.inventaire:
            return inventaire(journal, config)
        return synchroniser(journal, config, args)
    except KeyboardInterrupt:
        journal.dire()
        journal.dire("  Interrompu. Ce qui a été acquitté est acquitté : la prochaine")
        journal.dire("  synchronisation reprendra exactement là.")
        journal.evenement("interrompu")
        return 130
    finally:
        journal.fermer()


if __name__ == "__main__":
    sys.exit(main())
