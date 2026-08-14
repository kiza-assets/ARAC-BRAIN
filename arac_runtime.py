"""Où vit ce cerveau, et à qui il appartient.

Ce module répond à deux questions que TOUT le reste du code se pose, et qu'il
ne doit jamais résoudre lui-même :

    1. « Où est installé ce cerveau ? »   →  :func:`home` et :func:`path`
    2. « De quel poste vient ce que je digère ? »  →  :func:`node_id`

POURQUOI CE MODULE EXISTE
-------------------------
Un cerveau écrit dans son dossier de logs, lit ses secrets, appelle son
interpréteur Python, dit à l'opérateur quelle commande taper quand une
migration manque. Tant que ces chemins sont écrits en dur, le code ne peut
vivre qu'à un seul endroit, sur une seule machine, pour une seule personne.

Le cerveau de référence a été écrit ainsi : le même chemin d'installation,
en dur, apparaissait dans plus de trois cents fichiers source. Le premier
travail du portage a été de le remplacer partout par un appel à ce module.
C'est, très concrètement, la différence entre un programme personnel et un
framework.

COMMENT LA RACINE EST RÉSOLUE
-----------------------------
Dans cet ordre, premier trouvé gagne :

1. la variable d'environnement ``ARAC_HOME`` — c'est ce que posent les unités
   systemd, les tâches planifiées et les scripts d'exploitation ;
2. à défaut, le dossier qui contient ce fichier, c'est-à-dire la racine du
   dépôt cloné.

Le second cas rend le dépôt utilisable immédiatement après un ``git clone``,
sans rien configurer : vous pouvez lancer les tests avant même d'avoir un
serveur. Le premier cas rend l'installation déplaçable : ``/opt/arac``,
``/srv/cerveau``, ``~/arac`` — le code s'en moque.

**Aucun chemin absolu n'est écrit ailleurs dans le dépôt.** Si vous en ajoutez
un, vous venez de refermer la porte que ce module ouvre.

COMMENT L'IDENTITÉ EST RÉSOLUE
------------------------------
``node_id`` est l'identifiant du poste depuis lequel les conversations
arrivent. Le cerveau REFUSE les conversations dont le nœud n'est pas déclaré —
c'est ce garde-fou qui l'empêche d'avaler n'importe quoi. Il vient de
``config/brain.toml``, écrit par l'entretien d'installation
(``bootstrap/wizard.py``), et peut être surchargé par ``ARAC_NODE_ID`` le
temps d'un test ou d'une migration.

Si ``config/brain.toml`` n'existe pas, l'erreur ne dit pas « fichier
introuvable » : elle renvoie à l'entretien. Un cerveau sans identité n'est pas
un bug de configuration, c'est une naissance qui n'a pas eu lieu.
"""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path

__all__ = [
    "home",
    "path",
    "config_dir",
    "logs_dir",
    "agent_logs_dir",
    "secrets_dir",
    "data_dir",
    "var_dir",
    "backups_dir",
    "python_bin",
    "alembic_bin",
    "brain",
    "node_id",
    "brain_name",
    "owner",
    "BrainNotBornError",
]


# ============================================================================
# La racine
# ============================================================================

#: Nom du fichier d'identité, relatif à la racine.
BRAIN_CONFIG_RELPATH = "config/brain.toml"

#: Ce que dit le code quand il ne trouve pas l'identité du cerveau. Ce message
#: est lu par quelqu'un qui vient d'installer : il doit désigner l'action
#: suivante, pas le symptôme.
_NO_BRAIN_MSG = (
    "Ce cerveau n'a pas encore d'identité : {p} est introuvable.\n"
    "\n"
    "Ce fichier n'est pas à écrire à la main — il naît de l'entretien "
    "d'installation, qui vous demande à qui appartient ce cerveau et depuis "
    "quel poste ses conversations arriveront :\n"
    "\n"
    "    python3 bootstrap/wizard.py\n"
    "\n"
    "Pour un test ou une migration ponctuelle, la variable d'environnement "
    "ARAC_NODE_ID court-circuite la lecture du fichier."
)


def home() -> Path:
    """La racine d'installation de ce cerveau.

    ``ARAC_HOME`` si elle est posée, sinon le dépôt qui contient ce fichier.
    Le chemin est résolu (liens symboliques suivis) pour que deux appels
    depuis deux répertoires courants différents donnent la même réponse.
    """
    env = os.environ.get("ARAC_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parent


def path(*parts: str) -> Path:
    """Un chemin sous la racine. ``path("logs", "agents")`` et rien d'autre.

    C'est la seule façon correcte de désigner un fichier de l'installation.
    Toute chaîne commençant par ``/`` ailleurs dans le code est une régression.
    """
    return home().joinpath(*parts)


def config_dir() -> Path:
    """``config/`` — l'identité et la taxonomie. Écrit par le bootstrap."""
    return path("config")


def logs_dir() -> Path:
    """``logs/`` — ce que le cerveau raconte de lui-même."""
    return Path(os.environ.get("ARAC_LOGS_DIR") or path("logs"))


def agent_logs_dir() -> Path:
    """``logs/agents/`` — une ligne JSONL par mission, prompt et réponse inclus.

    C'est le journal qui permet de rejouer une décision d'agent six mois plus
    tard. Le cerveau de référence y doit l'essentiel de ce qu'il sait de ses
    propres erreurs.
    """
    return Path(os.environ.get("ARAC_MISSIONS_DIR") or logs_dir() / "agents")


def secrets_dir() -> Path:
    """``secrets/`` — jetons de nœuds, mots de passe de rôles. Mode 0700.

    Rien de ce dossier n'est versionné. Le dépôt ne contient aucun secret :
    s'il en contenait un, ce ne serait plus un framework mais une fuite.
    """
    return Path(os.environ.get("ARAC_SECRETS_DIR") or path("secrets"))


def data_dir() -> Path:
    """``data/`` — l'espace de travail des agents (HOME, caches, dépôts)."""
    return Path(os.environ.get("ARAC_DATA_DIR") or path("data"))


def var_dir() -> Path:
    """``var/`` — l'état vivant : verrous, curseurs, marqueurs de cycle."""
    return Path(os.environ.get("ARAC_VAR_DIR") or path("var"))


def backups_dir() -> Path:
    """Où atterrissent les dumps. Hors de la racine par défaut : une sauvegarde
    qui vit dans le dossier qu'elle sauvegarde ne sauvegarde rien.

    LE DÉFAUT PORTE LE NOM DE LA BASE, ET CE N'EST PAS DU RANGEMENT.

    Il valait « /var/backups/arac » — le même dossier pour tous les cerveaux
    d'une machine. Or la rotation des sauvegardes SUPPRIME les dumps de plus
    de N jours dans ce dossier : c'est le seul geste destructeur de toute
    l'installation. Deux cerveaux partageant ce chemin, la rotation de l'un
    efface les sauvegardes de l'autre — et on ne l'apprend qu'en cherchant à
    restaurer, c'est-à-dire le seul jour où c'était important.
    """
    declare = os.environ.get("ARAC_BACKUP_DIR")
    if declare:
        return Path(declare)
    nom = db_nom()
    if not nom:
        # Même doctrine que `node_id()` : deviner, ici, c'est ouvrir la porte.
        # Un cerveau sans nom n'a pas de dossier de sauvegarde à lui ; rendre
        # la racine commune reviendrait à désigner l'endroit exact où la
        # rotation d'un autre cerveau viendra supprimer ces dumps.
        raise BrainNotBornError(
            "Aucun nom de cerveau (ni ARAC_BACKUP_DIR, ni ARAC_DB, ni "
            "config/brain.toml) : impossible de nommer un dossier de "
            "sauvegarde qui n'appartienne qu'à lui. La rotation SUPPRIME "
            "dans ce dossier — c'est le seul geste destructeur du produit, "
            "et il ne doit jamais viser un chemin partagé."
        )
    return Path(f"/var/backups/arac/{nom}")


def python_bin() -> str:
    """L'interpréteur de l'installation — celui qui a les dépendances.

    Utilisé dans les messages destinés à l'opérateur (« tapez ceci ») et par
    les agents qui lancent un sous-processus. Par défaut l'environnement
    virtuel du dépôt ; ``ARAC_PYTHON`` pour un autre.
    """
    return os.environ.get("ARAC_PYTHON") or str(path(".venv", "bin", "python"))


def alembic_bin() -> str:
    """La commande de migration de l'installation, pour les mêmes raisons."""
    return os.environ.get("ARAC_ALEMBIC") or str(path(".venv", "bin", "alembic"))


# ============================================================================
# L'identité
# ============================================================================


class BrainNotBornError(RuntimeError):
    """``config/brain.toml`` est absent : l'entretien n'a pas eu lieu."""


@lru_cache(maxsize=1)
def _read_brain_config(marker: tuple[str, float]) -> dict:
    """Lecture mémoïsée. ``marker`` porte le chemin et la date de modification :
    le cache s'invalide tout seul si le fichier change (le bootstrap le
    réécrit), sans qu'aucun appelant ait à y penser."""
    return tomllib.loads(Path(marker[0]).read_text(encoding="utf-8"))


def brain() -> dict:
    """Le contenu de ``config/brain.toml``, tel quel.

    Lève :class:`BrainNotBornError` s'il n'existe pas, avec le message qui
    renvoie à l'entretien.
    """
    p = Path(os.environ.get("ARAC_BRAIN_CONFIG") or path(BRAIN_CONFIG_RELPATH))
    try:
        stat = p.stat()
    except OSError:
        raise BrainNotBornError(_NO_BRAIN_MSG.format(p=p)) from None
    return _read_brain_config((str(p), stat.st_mtime))


def node_id() -> str:
    """L'identifiant du poste source déclaré à l'installation.

    Le cerveau rejette toute conversation venant d'un nœud non déclaré. Cette
    valeur n'a donc pas de défaut : deviner, ici, c'est ouvrir la porte.
    """
    env = os.environ.get("ARAC_NODE_ID")
    if env:
        return env
    cfg = brain()
    value = (cfg.get("source") or {}).get("node_id")
    if not value:
        raise BrainNotBornError(
            "config/brain.toml ne déclare pas [source].node_id — le cerveau "
            "ne saurait pas d'où viennent ses conversations, donc il les "
            "refuserait toutes. Relancez : python3 bootstrap/wizard.py"
        )
    return str(value)


def brain_name() -> str:
    """Le nom de ce cerveau. Sert aux libellés, jamais à une décision."""
    env = os.environ.get("ARAC_BRAIN_NAME")
    if env:
        return env
    return str((brain().get("brain") or {}).get("name") or "arac")


def db_nom() -> str:
    """Le nom ASSAINI de ce cerveau — celui que portent ses dossiers propres.

    C'est la clé qui distingue deux cerveaux sur une même machine :
    ``/var/log/arac/<db_nom>``, ``/var/backups/arac/<db_nom>``,
    ``arac-<db_nom>-api.service``. Le bootstrap la calcule à l'étape 2
    (``bootstrap/lib/config.sh``) et l'écrit dans ARAC_DB, qui fait autorité :
    deux calculs vaudraient deux vérités, et c'est précisément cette
    divergence-là qui faisait écrire le cockpit à côté de ses droits.

    Sans ARAC_DB, on reproduit la règle du bootstrap —
    ``tr -c 'a-zA-Z0-9' '_' | sed 's/_*$//'`` puis minuscules — plutôt que
    d'en inventer une seconde. Rend `""` si le cerveau n'est pas encore né :
    cette fonction sert à choisir un chemin, elle ne doit jamais lever.
    """
    env = os.environ.get("ARAC_DB")
    if env:
        return env.strip()
    try:
        nom = brain_name()
    except Exception:  # noqa: BLE001 — pas de cerveau déclaré : pas de nom, pas d'erreur
        return ""
    assaini = "".join(
        c if (c.isascii() and c.isalnum()) else "_" for c in nom
    ).rstrip("_").lower()
    return assaini


def owner() -> str:
    """À qui appartient ce cerveau. Affichage seulement."""
    env = os.environ.get("ARAC_BRAIN_OWNER")
    if env:
        return env
    return str((brain().get("brain") or {}).get("owner") or "")
