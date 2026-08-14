"""ARAC — le jeton porteur : il est exigé, TOUJOURS, et voici pourquoi.

CE FICHIER DIT LA VÉRITÉ SUR L'AUTHENTIFICATION. Si la documentation dit autre
chose, c'est la documentation qui a tort — corrigez-la, pas ce fichier.

LA RÈGLE, EN UNE PHRASE
-----------------------
Le jeton porteur est exigé de TOUTE requête, sans exception d'origine — y
compris de celles qui arrivent de la machine elle-même, par 127.0.0.1. Seul
`/healthz` reste public (sonde de monitoring).

CE QUI A CHANGÉ, ET CE QUE ÇA A FERMÉ
-------------------------------------
Jusqu'ici, `ARAC_API_TRUST_LOOPBACK` valait `1` par défaut : une requête venue
de la boucle locale entrait sans présenter le moindre secret. Le raisonnement
était : « l'API n'écoute que sur 127.0.0.1, le seul chemin depuis le Mac est un
tunnel SSH, donc la frontière réelle est SSH ». Ce raisonnement suppose que
*atteindre* 127.0.0.1 exige d'avoir passé SSH. C'est faux dès qu'un second
compte a un shell sur la machine — et un second cerveau en amène au moins un.

Mesuré deux fois, par deux épreuves indépendantes, sur une machine à deux
cerveaux, depuis le compte `nobody`, sans un seul secret :

    GET  http://127.0.0.1:<port du voisin>/v1/dashboard/search  → 200, en clair
    POST http://127.0.0.1:<port du voisin>/v1/ingest/messages   → 202, écrit

Cette porte ne passe par aucun fichier : ni les comptes système distincts, ni
les coffres 0700, ni les rôles PostgreSQL, ni les grappes séparées ne la
ferment. Aucune permission ne la voit. C'était le dernier chemin par lequel un
cerveau lisait et corrompait la mémoire d'un autre.

POURQUOI INVERSER LE DÉFAUT PLUTÔT QUE FERMER « QUAND IL Y A UN VOISIN »
-----------------------------------------------------------------------
Le remède le plus tentant — « fermer dès qu'un second cerveau existe » — est
ASYMÉTRIQUE : le second cerveau se fermerait, le premier resterait ouvert, et
le fermer exigerait d'écrire dans le coffre du voisin, c'est-à-dire de violer
l'isolement qu'on prétend défendre. Inverser le défaut fait disparaître
l'asymétrie : un cerveau installé seul est fermé exactement comme un cerveau
installé à côté d'un autre, et l'ordre d'installation ne décide plus de rien.

Le coût pour l'utilisateur est NUL : le bootstrap engendre déjà le jeton
(`ARAC_API_BEARER_TOKEN`, recopié en `ARAC_NODE_TOKEN_<SLUG>`), et tout ce qui
appelle l'API pour s'en SERVIR le porte — le pont Mac, le pont sans-Mac, le
cycle, le cockpit, les agents, le harnais d'acceptation. Rien de plus n'est
demandé à personne. Voir `app/api_token.py`, qui est le seul endroit où un
appelant de ce dépôt va chercher son jeton.

UNE EXCEPTION, ET ELLE EST VOULUE : `bootstrap/checks/verify_install.sh`
frappe à cette porte SANS jeton. Il ne cherche pas à entrer, il vérifie
qu'elle refuse : il envoie un GET de recherche sans en-tête d'autorisation et
lit le code rendu. 401, la porte est fermée ; 200, elle est ouverte, et le
contrôle sort en échec. Il MESURE un état au lieu de lire une variable — le
fichier d'environnement peut dire « fermé » pendant que le service tourne
encore avec l'ancienne valeur, faute de redémarrage.

LE DESSERRAGE RESTE POSSIBLE — MAIS IL DOIT ÊTRE ÉCRIT, ET MOTIVÉ
-----------------------------------------------------------------
Quelqu'un peut avoir une raison de rouvrir la boucle locale (une sonde
tierce qu'on ne peut pas modifier, un banc de mesure). Il faut alors DEUX
variables, et pas une :

    ARAC_API_TRUST_LOOPBACK=1
    ARAC_API_TRUST_LOOPBACK_RAISON="2026-08-08 — sonde Prometheus héritée, ticket #412"

Sans la seconde, le desserrage n'est PAS appliqué : le jeton reste exigé, et
le refus le dit. Ce n'est pas une chicane administrative. Ce qui a permis à
cette porte de dormir deux manches entières, c'est précisément qu'elle était
un défaut IMPLICITE — une valeur que personne n'avait écrite, donc que
personne ne pouvait relire. Une exception qui porte sa date et son motif se
relit ; un défaut hérité, non.

`bootstrap/checks/verify_install.sh` n'accorde plus de ✓ rassurant à une
installation desserrée : il l'annonce, et il recopie le motif.

CE QUI PROTÈGE QUOI (les trois couches ne se remplacent pas)
------------------------------------------------------------
  1. le bind 127.0.0.1 + le tunnel SSH  → qui peut ATTEINDRE l'API
  2. le jeton porteur                   → quel POSTE parle — désormais partout
  3. ARAC_INGEST_ALLOWED_NODES          → quel node_id a le droit de DÉPOSER
     (fail-closed, toujours appliquée : un node_id non déclaré repart en 403,
     même avec un jeton valide — cf app/routers/ingest*.py)

Aucune ne remplace les autres : le jeton dit « je suis un poste connu », la
liste blanche dit « celui-là a le droit d'écrire », et le bind dit « on ne
m'atteint pas depuis l'Internet ».

L'AUTRE DÉFAUT, CORRIGÉ PLUS TÔT, ET QUI TIENT TOUJOURS
-------------------------------------------------------
La décision d'exemption reposait autrefois sur la PRÉSENCE de l'en-tête
`X-Forwarded-For`, un en-tête que le client écrit lui-même : il suffisait de
l'omettre pour être traité comme local. C'est l'adresse RÉELLE du pair TCP
(`request.client`) qui décide, et un en-tête de proxy ne peut plus
qu'AJOUTER de l'exigence, jamais en retirer. Cette règle reste en place ;
elle ne sert plus que sur les installations desserrées.

Source des tokens : variables d'env `ARAC_NODE_TOKEN_<SLUG>` chargées au startup,
lues depuis le fichier d'environnement du service (`/etc/arac/<votre-base>/arac.env`,
mode 0600, jamais versionné) via `EnvironmentFile=` de l'unité systemd.

Convention slug : node_id en majuscules, tirets → underscores. Ex :
  mon-portable        → ARAC_NODE_TOKEN_MON_PORTABLE
  claude-code-serveur → ARAC_NODE_TOKEN_CLAUDE_CODE_SERVEUR

Rotation : révoquez en retirant la variable et en redémarrant le service. Un
jeton retiré ferme le nœud correspondant à la requête suivante, sans purger
ce qu'il a déjà déposé.
"""

from __future__ import annotations

import ipaddress
import logging
import os

from fastapi import Request
from fastapi.responses import JSONResponse


_logger = logging.getLogger("arac.api")

_ENV_PREFIX = "ARAC_NODE_TOKEN_"
_MIN_TOKEN_LEN = 32  # openssl rand -hex 32 → 64 chars hex, mais on tolère ≥ 32

# Endpoints publics même derrière un reverse proxy (exemption Bearer)
_PUBLIC_PATHS = frozenset({"/healthz"})

# Le drapeau du desserrage. DÉFAUT : 0 — le jeton est exigé partout, y compris
# en boucle locale. Le rouvrir exige DEUX variables (cf docstring du module).
_TRUST_LOOPBACK_VAR = "ARAC_API_TRUST_LOOPBACK"
_TRUST_LOOPBACK_RAISON_VAR = "ARAC_API_TRUST_LOOPBACK_RAISON"

# Les seules écritures qui desserrent. Tout le reste — vide, absent, « yes »,
# une faute de frappe — laisse le jeton exigé. Le sens de la liste est
# INVERSÉ par rapport à la version d'avant, et c'est délibéré : quand la
# valeur par défaut était « ouvert », il fallait énumérer ce qui ferme, et une
# coquille laissait ouvert. Maintenant qu'elle est « fermé », on énumère ce
# qui ouvre, et une coquille laisse fermé. Une liste d'exceptions se trompe
# toujours du côté de sa valeur par défaut : autant que ce côté soit le bon.
_VALEURS_QUI_DESSERRENT = frozenset({"1", "true", "yes", "oui", "on"})

# Un seul de ces en-têtes suffit à dire « je viens d'un proxy » : dans ce cas
# le pair TCP est le proxy, pas l'appelant, et l'exemption ne s'applique pas.
# Ils ne peuvent qu'AJOUTER de l'exigence : un client qui les omet ne gagne
# rien, puisque son adresse réelle est vérifiée par ailleurs.
_PROXY_HEADERS = ("x-forwarded-for", "x-real-ip", "forwarded")


def raison_du_desserrage() -> str:
    """Le motif écrit du desserrage, ou la chaîne vide s'il n'y en a pas."""
    return os.environ.get(_TRUST_LOOPBACK_RAISON_VAR, "").strip()


def etat_du_desserrage() -> tuple[bool, str]:
    """(desserré ?, pourquoi cet état) — lu à CHAQUE requête, jamais mis en cache.

    Pas de cache : c'est un drapeau de posture, pas un secret coûteux à lire,
    et un exploitant qui le change doit voir l'effet au redémarrage du service
    sans dépendre d'un ordre d'import.

    Trois états, et le second est celui qui compte :

      · rien de posé            → jeton exigé. C'est le DÉFAUT, et il est fermé.
      · posé SANS motif écrit   → jeton exigé quand même, et on le DIT. Un
        desserrage muet est exactement ce qui a laissé cette porte ouverte
        pendant deux manches : personne ne pouvait relire une intention que
        personne n'avait écrite.
      · posé AVEC motif écrit   → desserré, et le motif voyage avec l'état
        pour que `verify_install.sh` et les journaux puissent le recopier.
    """
    brut = os.environ.get(_TRUST_LOOPBACK_VAR, "0").strip().lower()
    if brut not in _VALEURS_QUI_DESSERRENT:
        return False, "défaut fermé"
    motif = raison_du_desserrage()
    if not motif:
        return False, f"{_TRUST_LOOPBACK_VAR}={brut} posé sans {_TRUST_LOOPBACK_RAISON_VAR}"
    return True, motif


def loopback_de_confiance() -> bool:
    """La boucle locale est-elle desserrée ? (cf `etat_du_desserrage`)"""
    desserre, _ = etat_du_desserrage()
    return desserre


def _est_boucle_locale(hote: str | None) -> bool:
    """L'adresse du pair TCP est-elle une adresse de bouclage ?

    `hote` vient de `request.client.host` : c'est l'adresse vue par le noyau,
    que le client ne peut pas écrire lui-même. Tout ce qui n'est pas une
    adresse IP analysable (socket UNIX, client absent, faux client de test)
    est traité comme NON loopback : en cas de doute, on exige le jeton.
    """
    if not hote:
        return False
    try:
        adresse = ipaddress.ip_address(hote)
    except ValueError:
        return False
    # ::ffff:127.0.0.1 — un loopback IPv4 vu par une pile IPv6.
    if getattr(adresse, "ipv4_mapped", None) is not None:
        adresse = adresse.ipv4_mapped
    return adresse.is_loopback


def bearer_requis(
    *,
    path: str,
    hote_pair: str | None,
    entetes_proxy_presents: bool,
    confiance_loopback: bool,
) -> bool:
    """LA règle d'authentification, isolée pour être lisible et testable.

    Fonction pure : aucune I/O, aucun état. C'est elle que testent
    `tests/test_auth_bearer.py`, afin que la fermeture reste un fait vérifié
    et non un effet de bord qu'un remaniement ferait disparaître en silence.

    `confiance_loopback` est FAUX par défaut chez tous les appelants réels :
    il ne devient vrai que si l'exploitant a écrit son desserrage ET son
    motif (cf `etat_du_desserrage`).
    """
    if path in _PUBLIC_PATHS:
        return False
    if not confiance_loopback:
        return True
    if entetes_proxy_presents:
        return True
    return not _est_boucle_locale(hote_pair)


def _env_slug_to_node_id(slug: str) -> str:
    """Inverse de la convention slug.

    Hypothèse documentée : les node_id ARAC ne contiennent que [a-z0-9-]
    (convention Phase 1b.6, atomes `arac.nodes`). La conversion est donc
    sans perte : underscores → tirets, lowercase.
    """
    return slug.lower().replace("_", "-")


def load_tokens_from_env() -> dict[str, str]:
    """Scanne os.environ pour le préfixe ARAC_NODE_TOKEN_ et build {token: node_id}.

    Levée d'erreur si un token est trop court (< 32 chars) — signal qu'on a
    laissé un placeholder ou un token tronqué dans .env.

    Returns:
      Dict {token_string: node_id}. Vide si aucune variable d'env trouvée.
    """
    mapping: dict[str, str] = {}
    for key, value in os.environ.items():
        if not key.startswith(_ENV_PREFIX):
            continue
        slug = key[len(_ENV_PREFIX) :]
        if not slug:
            continue
        node_id = _env_slug_to_node_id(slug)
        token = value.strip()
        if not token:
            _logger.warning(
                "auth.token_empty",
                extra={"event": "config", "node_id": node_id},
            )
            continue
        if len(token) < _MIN_TOKEN_LEN:
            raise ValueError(
                f"Token for node '{node_id}' too short "
                f"({len(token)} chars, need ≥ {_MIN_TOKEN_LEN})"
            )
        if token in mapping and mapping[token] != node_id:
            raise ValueError(
                f"Duplicate token detected for nodes '{mapping[token]}' and '{node_id}'"
            )
        mapping[token] = node_id
    return mapping


# Cache module-level : chargé une fois au premier appel, immuable ensuite.
# Le startup arac-api.service appelle get_tokens() via le lifespan pour
# forcer la validation au démarrage (évite de découvrir l'erreur sur la
# première requête authentifiée).
_tokens_cache: dict[str, str] | None = None


def get_tokens() -> dict[str, str]:
    """Retourne le mapping {token: node_id}. Cache module-level."""
    global _tokens_cache
    if _tokens_cache is None:
        _tokens_cache = load_tokens_from_env()
        _logger.info(
            "auth.tokens_loaded",
            extra={
                "event": "ready",
                "node_count": len(_tokens_cache),
                "node_ids": sorted(_tokens_cache.values()),
            },
        )
    return _tokens_cache


def chemin_du_coffre() -> str:
    """Le fichier d'environnement de CE cerveau, nommé aussi précisément que possible.

    Un message d'erreur qui dit « /etc/arac/<votre-base>/arac.env » oblige le
    lecteur à deviner ce qu'est sa base — sur une machine à deux cerveaux,
    deviner, c'est aller regarder dans le coffre du voisin. Le bootstrap écrit
    `ARAC_DB` dans ce même fichier : au moment où l'API répond, elle connaît
    donc son propre chemin. On ne retombe sur le gabarit que si elle tourne
    hors de son unité systemd.
    """
    depuis_env = os.environ.get("ARAC_ENV_FILE", "").strip()
    if depuis_env:
        return depuis_env
    base = os.environ.get("ARAC_DB", "").strip()
    if base:
        return f"/etc/arac/{base}/arac.env"
    return "/etc/arac/<votre-base>/arac.env"


def _geste_pour_trouver_le_jeton() -> str:
    """Le geste EXACT qui rend le jeton de ce cerveau — chemin réel compris."""
    return (
        f"sudo grep -E '^(ARAC_API_BEARER_TOKEN|ARAC_NODE_TOKEN_)' {chemin_du_coffre()}"
        "   puis :  curl -H \"Authorization: Bearer <jeton>\" …"
    )


def _pourquoi_le_jeton_est_exige(entetes_proxy: list[str], hote_pair: str | None) -> str:
    """La raison PARTICULIÈRE de ce refus-ci, pas la règle en général.

    Trois refus différents portent trois causes différentes, et confondre les
    trois coûte des heures : « je suis pourtant en local » n'a pas le même
    remède que « mon proxy ne transmet pas l'en-tête ».
    """
    desserre, etat = etat_du_desserrage()
    if not desserre and etat.startswith(_TRUST_LOOPBACK_VAR):
        return (
            f"le jeton est exigé de toute requête. Vous avez tenté un desserrage — {etat} — "
            f"mais il n'est PAS appliqué : un desserrage doit porter son motif écrit, "
            f"sans quoi personne ne peut le relire six mois plus tard"
        )
    if entetes_proxy:
        return (
            f"cette requête porte un en-tête de proxy ({', '.join(entetes_proxy)}) : "
            "elle vient du dehors, et le jeton y a toujours été exigé"
        )
    if not _est_boucle_locale(hote_pair):
        # Nommer l'adresse VUE PAR LE NOYAU est ce qui coupe court au
        # malentendu le plus fréquent : « je suis pourtant en local ». Non —
        # et voici sous quelle adresse l'API vous a vu arriver.
        return (
            f"votre adresse d'origine ({hote_pair or 'inconnue'}) n'est pas la boucle "
            "locale — le jeton y a toujours été exigé, et cette adresse est celle que "
            "voit le noyau, pas celle qu'un en-tête déclare"
        )
    return (
        "le jeton est exigé de TOUTE requête, y compris depuis 127.0.0.1. "
        "Ce n'est pas un durcissement optionnel : sans lui, n'importe quel compte "
        "local — un autre utilisateur, un script, le cerveau du voisin sur la même "
        "machine — lit votre mémoire et y écrit de faux souvenirs sans présenter "
        "un seul secret. Aucune permission de fichier ne ferme ce chemin-là, "
        "parce qu'il ne passe par aucun fichier"
    )


async def bearer_middleware(request: Request, call_next):
    """Middleware FastAPI — applique `bearer_requis` (cf docstring du module).

    Ordre de décision :
      1. Chemin public (/healthz) → libre.
      2. Boucle locale NON desserrée (le défaut) → Bearer exigé, sans exception.
      3. En-tête de proxy présent → la requête vient du dehors → Bearer exigé.
      4. Desserrage écrit ET motivé + pair TCP sur la boucle locale → libre.
      5. Tout le reste → Bearer exigé.
         5a. Pas d'en-tête Authorization Bearer → 401 + log auth.missing_bearer.
         5b. Token inconnu → 401 + log auth.invalid_bearer.
         5c. Token valide → request.state.auth_node_id = node_id, pass.
    """
    path = request.url.path
    hote_pair = request.client.host if request.client else None
    entetes_proxy = [h for h in _PROXY_HEADERS if request.headers.get(h)]
    forwarded_for = request.headers.get("X-Forwarded-For")

    if not bearer_requis(
        path=path,
        hote_pair=hote_pair,
        entetes_proxy_presents=bool(entetes_proxy),
        confiance_loopback=loopback_de_confiance(),
    ):
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        _logger.info(
            "auth.missing_bearer",
            extra={
                "event": "denied",
                "path": path,
                "client_host": hote_pair,
                "proxy_headers": entetes_proxy,
                "x_forwarded_for": forwarded_for,
            },
        )
        # Un refus qui n'explique pas se paie en heures de recherche. Celui-ci
        # dit les quatre choses qu'on cherche à ce moment-là : CE QUI manque,
        # POURQUOI c'est exigé ici, OÙ se trouve le jeton, et — parce que ce
        # refus est nouveau et va donc surprendre — ce qui a changé.
        return JSONResponse(
            status_code=401,
            content={
                "detail": "Jeton porteur requis : en-tête `Authorization: Bearer <jeton>` absent.",
                "pourquoi": _pourquoi_le_jeton_est_exige(entetes_proxy, hote_pair),
                "ou_est_le_jeton": chemin_du_coffre(),
                "geste": _geste_pour_trouver_le_jeton(),
                "si_vous_ecrivez_un_appelant": (
                    "n'allez pas relire ce fichier vous-même : `app/api_token.py` "
                    "le fait déjà, de la même façon pour le pont, le cycle, le "
                    "cockpit et les agents — `from app.api_token import entetes_api`"
                ),
                "desserrer": (
                    "si vous avez une raison de rouvrir la boucle locale, il en "
                    f"faut DEUX lignes : {_TRUST_LOOPBACK_VAR}=1 et "
                    f"{_TRUST_LOOPBACK_RAISON_VAR}=\"<date> — <votre motif>\". "
                    "Sans la seconde, le desserrage n'est pas appliqué : une "
                    "exception qu'on ne peut pas relire est celle qu'on oublie"
                ),
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth_header[len("Bearer ") :].strip()
    tokens = get_tokens()
    node_id = tokens.get(token)
    if not node_id:
        _logger.info(
            "auth.invalid_bearer",
            extra={
                "event": "denied",
                "path": path,
                "client_host": hote_pair,
                "x_forwarded_for": forwarded_for,
                "token_prefix": token[:8] + "..." if len(token) >= 8 else "***",
            },
        )
        return JSONResponse(
            status_code=401,
            content={
                "detail": "Jeton porteur inconnu.",
                "pourquoi": (
                    "aucune variable ARAC_NODE_TOKEN_<NODE_ID> de l'environnement "
                    "de l'API ne porte cette valeur "
                    f"({len(tokens)} poste(s) déclaré(s))"
                ),
                "ou_est_le_jeton": chemin_du_coffre(),
                "geste": (
                    "vérifiez le nom de la variable : node_id en MAJUSCULES, "
                    "tirets et points remplacés par des soulignés, "
                    f"dans {chemin_du_coffre()} — puis redémarrez le service de l'API. "
                    "Un jeton copié depuis le coffre d'un AUTRE cerveau de cette "
                    "machine donne exactement ce refus-ci : les tables sont disjointes"
                ),
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Token valide — attache node_id sur request.state pour usage downstream
    # (futurs handlers peuvent lire request.state.auth_node_id pour audit_log,
    # filtrage par node, etc.).
    request.state.auth_node_id = node_id
    return await call_next(request)
