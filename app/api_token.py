"""ARAC — le jeton, vu du côté de CELUI QUI APPELLE l'API.

`app/auth.py` dit quand le jeton est EXIGÉ. Ce fichier-ci dit où le trouver
quand on est le pont, le cycle, le cockpit, un agent, ou n'importe quel
programme de ce dépôt qui parle à l'API. C'est le pendant exact de l'autre, et
les deux doivent se lire ensemble.

POURQUOI CE FICHIER EXISTE — un seul endroit, pas onze
------------------------------------------------------
Le jour où le jeton est devenu exigé partout, onze appelants de ce dépôt
appelaient l'API sans en porter aucun : `agents/lib/bus.py`,
`agents/lib/heartbeat.py`, `agents/lib/llm_auditor.py`,
`agents/cortex/atoms_client.py`, les quatre `agents/*/main.py`,
`control_center/collectors/brain_api.py`, et deux scripts de vérification.
Onze fois « lire une variable, construire un en-tête », c'est onze occasions
d'oublier, et surtout onze endroits à retrouver le jour d'une rotation. Il n'y
a donc qu'UNE fonction, ici, et tout le monde l'appelle.

OÙ EST LE JETON, ET DANS QUEL ORDRE ON LE CHERCHE
-------------------------------------------------
Toutes les unités systemd engendrées par le bootstrap portent
`EnvironmentFile=/etc/arac/<base>/arac.env` — l'API, le cockpit, le cycle, les
sauvegardes. Le jeton est donc DÉJÀ dans l'environnement de tout appelant
légitime, sous deux noms :

  1. `ARAC_API_BEARER_TOKEN`  — le nom que le bootstrap engendre et que la
     documentation du pont Mac fait recopier. C'est le nom CANONIQUE côté
     client, et on le regarde en premier.
  2. `ARAC_NODE_TOKEN_<SLUG>` — le nom sous lequel l'API le RECONNAÎT (elle
     balaie ce préfixe pour bâtir sa table « jeton → poste »). Le bootstrap
     recopie le premier vers le second ; ils portent la même valeur.

On accepte les deux, dans cet ordre, puis — et seulement si un seul poste est
déclaré — l'unique `ARAC_NODE_TOKEN_*` trouvé. Cette dernière porte est étroite
VOLONTAIREMENT : s'il y en a plusieurs, choisir « au hasard » reviendrait à
signer avec l'identité d'un autre poste, et le refus de l'API (403 sur la
liste blanche) serait alors incompréhensible. Mieux vaut ne rien envoyer et
recevoir un 401 qui explique.

Le slug de `ARAC_NODE_ID` est essayé avant l'unicité : sur un cerveau où
plusieurs postes sont déclarés, c'est lui qui désigne le bon.

CE QU'ON NE FAIT PAS, ET POURQUOI
---------------------------------
· On ne LIT PAS `/etc/arac/<base>/arac.env` nous-mêmes. Ce fichier est en 0600
  root : un agent qui tourne sous son propre compte ne peut pas l'ouvrir, et
  c'est très bien ainsi. C'est systemd qui l'injecte, avant d'abandonner ses
  privilèges. Un client qui irait le lire lui-même exigerait des droits qu'on
  a passé des manches entières à lui retirer.
· On ne LÈVE PAS quand le jeton manque. Un cockpit qui refuse de démarrer
  parce qu'une variable manque est plus difficile à diagnostiquer qu'un
  cockpit qui affiche « indisponible » ; et l'API, elle, rend un 401 qui
  enseigne. On journalise une fois, en clair, et on laisse l'appel partir.
· On ne journalise JAMAIS la valeur, ni un préfixe de la valeur. Un jeton dans
  un journal est un jeton public : les journaux se copient, se collent dans un
  rapport de bogue, et survivent à la rotation.
"""

from __future__ import annotations

import logging
import os

_logger = logging.getLogger("arac.api_token")

_VAR_CANONIQUE = "ARAC_API_BEARER_TOKEN"
_PREFIXE_NODE = "ARAC_NODE_TOKEN_"

# Un seul avertissement par processus : un cycle qui boucle noierait le journal.
_absence_deja_dite = False


def _slug(node_id: str) -> str:
    """node_id → suffixe de variable. L'inverse de `app.auth._env_slug_to_node_id`.

    MAJUSCULES, tirets ET points remplacés par des soulignés — la même
    conversion que celle que `bootstrap/checks/verify_install.sh` applique
    (`tr 'a-z.-' 'A-Z__'`). Les trois doivent rester d'accord : c'est ce qui
    fait qu'un jeton posé par le bootstrap est trouvé par le client et reconnu
    par l'API.
    """
    return node_id.strip().upper().replace("-", "_").replace(".", "_")


def jeton_api() -> str | None:
    """Le jeton de CE cerveau, ou None s'il n'est pas dans l'environnement.

    Ne lève jamais. Ne lit aucun fichier. Ne journalise aucune valeur.
    """
    valeur = os.environ.get(_VAR_CANONIQUE, "").strip()
    if valeur:
        return valeur

    node_id = os.environ.get("ARAC_NODE_ID", "").strip()
    if node_id:
        # L'unité du cycle pose `ARAC_NODE_ID=<poste>-cycle` : le poste du
        # cycle n'a pas de jeton à lui, mais le cerveau en a un. On essaie
        # donc le nom exact, puis le nom sans le suffixe d'unité.
        candidats = [node_id]
        for suffixe in ("-cycle", "-agent", "-cockpit"):
            if node_id.endswith(suffixe):
                candidats.append(node_id[: -len(suffixe)])
        for candidat in candidats:
            valeur = os.environ.get(_PREFIXE_NODE + _slug(candidat), "").strip()
            if valeur:
                return valeur

    # Dernier recours : un seul poste déclaré, donc aucune ambiguïté possible.
    trouves = [
        v.strip()
        for k, v in os.environ.items()
        if k.startswith(_PREFIXE_NODE) and v.strip()
    ]
    if len(set(trouves)) == 1:
        return trouves[0]
    return None


def entetes_api(supplementaires: dict[str, str] | None = None) -> dict[str, str]:
    """Les en-têtes à poser sur tout appel à l'API de ce cerveau.

    C'est la SEULE fonction que les appelants doivent connaître :

        from app.api_token import entetes_api
        client.post(url, json=payload, headers=entetes_api())

    Rend un dictionnaire vide (plus les `supplementaires`) si aucun jeton n'est
    disponible — l'API répondra alors 401 avec un corps qui explique où le
    trouver, ce qui est plus utile qu'une exception ici.
    """
    entetes: dict[str, str] = dict(supplementaires or {})
    jeton = jeton_api()
    if jeton:
        entetes["Authorization"] = f"Bearer {jeton}"
    else:
        _avertir_une_fois()
    return entetes


def _avertir_une_fois() -> None:
    global _absence_deja_dite
    if _absence_deja_dite:
        return
    _absence_deja_dite = True
    _logger.warning(
        "api_token.absent",
        extra={
            "event": "config_missing",
            "cherche": [_VAR_CANONIQUE, _PREFIXE_NODE + "<POSTE>"],
            "effet": "les appels à l'API partiront sans jeton et seront refusés en 401",
            "geste": (
                "l'unité systemd de ce programme doit porter "
                "EnvironmentFile=/etc/arac/<base>/arac.env ; "
                "hors systemd, exportez ARAC_API_BEARER_TOKEN avant de lancer"
            ),
        },
    )


def _reinitialiser_avertissement() -> None:
    """Réservé aux tests : rend le « une seule fois » observable plusieurs fois."""
    global _absence_deja_dite
    _absence_deja_dite = False
