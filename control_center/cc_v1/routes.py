"""Control Center v1 — routes HTTP du BFF (READ-ONLY strict, GET uniquement).

Paquet ADDITIF : ce module n'altère aucune route existante. Il s'enregistre sur
l'application via ``register()``, appelé une fois depuis
``control_center/app.py::_register_routes`` — qui reste la source unique de
vérité du routage CC.

Doctrine respectée à l'identique du socle :
  - ``@a.get`` uniquement (aucun verbe mutant) ;
  - garde de session (``_session_api``) sur chaque route ;
  - journal de lecture (``audit_read_log``) sur chaque accès.

Les handlers sont **synchrones** (``def``) : FastAPI les exécute dans un
threadpool, ce qui évite de bloquer la boucle d'événements pendant l'I/O
PostgreSQL.

Routes exposées :

  GET /cc/v1/catalog              le registre, sans exécution (documentation)
  GET /cc/v1/metrics              toutes les métriques, valeurs + chemins de preuve
  GET /cc/v1/metrics/{key}        une métrique
  GET /cc/v1/evidence/{key}       LA PREUVE : les lignes sources + le SQL rejouable
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, FastAPI, Query
from fastapi.responses import JSONResponse

from control_center.cc_v1 import registry, service

__all__ = ["register", "SUBMODULE_ERRORS"]

_PREFIX = "/cc/v1"

# Sous-modules optionnels du BFF, chargés dans cet ordre. Chacun expose
# ``register(a, session_api, audit_read_log)``.
#
# Le chargement est TOLÉRANT, pour la même raison que les familles de métriques :
# un module absent ou cassé ne doit pas vous priver de votre cockpit. Ce
# qui manque est journalisé dans ``SUBMODULE_ERRORS`` et exposé par l'API, pour
# que l'interface puisse DIRE ce qui est indisponible plutôt que de l'ignorer en
# silence — une absence tue plus sûrement qu'une erreur affichée.
_SUBMODULES: tuple[str, ...] = (
    "entities",   # navigation : conversations, atomes, scopes, projets
    "today",      # V2 — la journée du cerveau et sa synthèse narrative
    "scopes",     # V2 — les scopes comme objets de premier niveau
    "lifestory",  # V2 — histoire d'un atome, graphe d'un projet, chronologie
    "cascade",    # V3 — « le cerveau pense » : le trajet d'une conversation, étape par étape
    "replay",     # V3 — rejouer une journée du cerveau, image par image
    "listener",   # V3 — écoute LISTEN/NOTIFY, en repli sur le suivi de base
    "stream",     # flux temps réel (SSE)
    "ui",         # la page du cockpit et ses fichiers statiques  (EN DERNIER :
                  # elle sert des fichiers statiques et ne doit pas capter une
                  # route qu'un module métier déclarerait après elle)
)

SUBMODULE_ERRORS: dict[str, str] = {}
"""Sous-modules dont le chargement ou l'enregistrement a échoué : {nom: raison}."""


def _register_submodules(
    a: FastAPI,
    session_api: Callable[..., Any],
    audit_read_log: Callable[[str, str], Any],
) -> None:
    """Enregistre les sous-modules présents. Ne lève jamais."""
    import importlib

    for name in _SUBMODULES:
        try:
            mod = importlib.import_module(f"control_center.cc_v1.{name}")
        except ModuleNotFoundError:
            SUBMODULE_ERRORS[name] = "module absent"
            continue
        except Exception as exc:  # noqa: BLE001
            SUBMODULE_ERRORS[name] = f"import: {type(exc).__name__}: {exc}"
            continue

        fn = getattr(mod, "register", None)
        if not callable(fn):
            SUBMODULE_ERRORS[name] = "pas de fonction register()"
            continue
        try:
            fn(a, session_api=session_api, audit_read_log=audit_read_log)
        except Exception as exc:  # noqa: BLE001
            SUBMODULE_ERRORS[name] = f"register: {type(exc).__name__}: {exc}"


def register(
    a: FastAPI,
    session_api: Callable[..., Any],
    audit_read_log: Callable[[str, str], Any],
) -> None:
    """Enregistre les routes ``/cc/v1/*`` sur l'application fournie.

    Args:
        a: l'instance FastAPI du Control Center.
        session_api: la dépendance de session en mode API (401 JSON si absente).
        audit_read_log: le journal de lecture du socle (chemin, principal).
    """

    @a.get(f"{_PREFIX}/catalog")
    def cc_v1_catalog(principal: dict = Depends(session_api)) -> JSONResponse:
        """Le registre des métriques, SANS exécution.

        Sert à documenter et à vérifier : chaque entrée porte sa définition, sa
        formule, le SQL de sa valeur et le SQL de sa preuve. Aucune connexion à
        la base n'est ouverte — cette route répond même si la base est éteinte.
        """
        audit_read_log(f"{_PREFIX}/catalog", principal.get("sub", "?"))
        return JSONResponse({
            "count": len(registry.REGISTRY),
            "domains": sorted({m.domain for m in registry.REGISTRY}),
            "items": service.catalog(),
        })

    @a.get(f"{_PREFIX}/metrics")
    def cc_v1_metrics(
        principal: dict = Depends(session_api),
        domain: str | None = Query(default=None, max_length=64),
    ) -> JSONResponse:
        """Toutes les métriques (ou celles d'un domaine), valeurs comprises.

        Chaque entrée porte sa valeur, son état, sa fenêtre, sa définition, sa
        formule ET son chemin de preuve. Le client n'a rien à calculer ni à
        déduire — pas même une URL.
        """
        audit_read_log(f"{_PREFIX}/metrics", principal.get("sub", "?"))
        return JSONResponse(service.all_metrics(domain=domain))

    @a.get(f"{_PREFIX}/metrics/{{key}}")
    def cc_v1_metric(key: str, principal: dict = Depends(session_api)) -> JSONResponse:
        """Une métrique et sa valeur courante.

        Une clé inconnue ne lève pas : elle retourne ``state='unavailable'``
        avec sa raison, comme toute source indisponible.
        """
        audit_read_log(f"{_PREFIX}/metrics/{key}", principal.get("sub", "?"))
        return JSONResponse(service.metric_value(key))

    @a.get(f"{_PREFIX}/evidence/{{key}}")
    def cc_v1_evidence(
        key: str,
        principal: dict = Depends(session_api),
        limit: int = Query(default=200, ge=1, le=500),
    ) -> JSONResponse:
        """LA PREUVE d'une métrique : les lignes sources qui produisent sa valeur.

        C'est l'assertion G4 du mandat : depuis n'importe quel chiffre affiché,
        on atteint la donnée. La réponse inclut le SQL exécuté — la preuve est
        donc **rejouable à l'identique depuis un terminal**, donc opposable.
        Un cockpit qui ne peut pas être contredit ne mérite pas d'être cru.
        """
        audit_read_log(f"{_PREFIX}/evidence/{key}", principal.get("sub", "?"))
        return JSONResponse(service.evidence(key, limit=limit))

    @a.get(f"{_PREFIX}/status")
    def cc_v1_status(principal: dict = Depends(session_api)) -> JSONResponse:
        """Ce que le cockpit sait de LUI-MÊME : ce qui est chargé, ce qui manque.

        Sert l'honnêteté du produit : l'interface doit pouvoir afficher ses
        propres organes manquants plutôt que de les taire. Un module absent est
        une information, pas un détail d'implémentation.
        """
        audit_read_log(f"{_PREFIX}/status", principal.get("sub", "?"))
        # Import LOCAL et gardé : `entities` est un sous-module optionnel, et
        # `/status` est justement la route qui doit répondre quand un sous-module
        # manque. L'importer en tête ferait tomber la page qui sert à diagnostiquer
        # sa propre absence.
        try:
            from control_center.cc_v1 import entities as _entities

            links_dep = _entities.links_dependency()
        except Exception:  # noqa: BLE001 — /status répond toujours
            links_dep = {
                "state": "unavailable",
                "reason": ("l'état de arac.atom_links n'a pas pu être constaté : "
                           "le module de navigation n'est pas chargé"),
                "gesture": "voir submodules.errors ci-dessus",
            }
        return JSONResponse({
            "metrics": {
                "count": len(registry.REGISTRY),
                "core": len(registry.CORE),
                "families": [f for f in registry.FAMILY_MODULES],
                "load_errors": registry.LOAD_ERRORS,
                "domains": sorted({m.domain for m in registry.REGISTRY}),
            },
            "submodules": {
                "expected": list(_SUBMODULES),
                "errors": SUBMODULE_ERRORS,
                "loaded": [s for s in _SUBMODULES if s not in SUBMODULE_ERRORS],
            },
            # POURQUOI cette dépendance est SONDÉE et non déclarée : `/status`
            # est la page qu'on lit quand quelque chose ne va pas. Y écrire
            # « migration non appliquée » en dur, c'est répondre à la question
            # « qu'est-ce qui manque ? » sans avoir regardé — et envoyer relancer
            # une migration déjà passée. `links_dependency()` interroge le
            # catalogue et rend la phrase correspondant à ce qu'il a trouvé.
            "dependencies": {
                "atom_links": dict(
                    links_dep,
                    impact=["maillon 5 « Reliée »", "constante V5 Connectivité",
                            "vues « les plus reliés » et « orphelins »"],
                    substitute="voisinage sémantique + vue « jamais rappelés »",
                ),
            },
        })

    # Sous-modules optionnels : navigation, temps réel, interface.
    _register_submodules(a, session_api, audit_read_log)
