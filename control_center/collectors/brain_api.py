"""brain_api.py — collecteur READ-ONLY du Control Center vers l'API Brain (`/v1/brain/*`).

Le cockpit consomme les endpoints read-only de l'API ARAC en loopback (jamais d'écriture,
jamais de POST/PUT/DELETE). Chaque fonction est RÉSILIENTE : en cas d'API down, de timeout
ou de réponse inattendue, elle retourne ``{"error": "unavailable"}`` au lieu de lever.

Sécurité :
  - LECTURE SEULE : uniquement des GET sur `/v1/brain/*`.
  - Les endpoints rédigent déjà la colonne ``value`` des atomes sensibles ; par défense en
    profondeur, ``_strip_value`` retire toute clé ``value`` résiduelle avant affichage cockpit.
  - Base de l'API : env ``ARAC_API_BASE``, posée par l'unité systemd du cockpit.
    AUCUN défaut : sans elle, le collecteur rend « indisponible » plutôt que
    d'interroger, au hasard, l'API d'un autre cerveau de la même machine.
  - JETON PORTEUR : l'API l'exige désormais de toute requête, boucle locale
    comprise (`app/auth.py`). L'unité du cockpit porte déjà
    ``EnvironmentFile=/etc/arac/<base>/arac.env`` — donc le jeton — et
    ``app/api_token.py`` va le chercher là. Sans lui, chaque page du cockpit
    afficherait « indisponible » sans dire pourquoi : c'est la panne la plus
    plausible de ce changement, et c'est pour elle que ``_get`` distingue
    maintenant un 401 d'une API muette.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from app.api_token import entetes_api

_UNAVAILABLE = "unavailable"
_TIMEOUT = 5.0


def _base() -> str:
    """URL de base de l'API de CE cerveau — jamais d'un autre.

    IL N'Y A PLUS DE DÉFAUT, ET C'EST LE CORRECTIF.

    Cette fonction retombait sur ``http://127.0.0.1:8000``. Sur une machine
    qui ne porte qu'un cerveau, ce défaut est juste. Sur une machine qui en
    porte deux, il désigne le PREMIER — et le cockpit du second affichait la
    taxonomie, la santé et la couverture du premier. Constaté sur pièces :
    la page ``/cc/brain`` du cockpit de « zoe-brain » montrait la taxonomie
    complète d'un tiers. Aucune erreur, aucun journal, aucun symptôme : juste
    un cerveau qui montre à quelqu'un la mémoire d'un autre.

    Un défaut plausible est ici plus dangereux qu'une panne, parce qu'il
    produit une page crédible. On préfère donc *fail-closed* : sans
    ``ARAC_API_BASE``, on ne devine pas, on ne répond rien, et l'appelant
    affiche « indisponible ». L'unité du cockpit engendrée par le bootstrap
    pose cette variable ; son absence signale une installation incomplète,
    ce qui est une information — contrairement à la mémoire du voisin.
    """
    return (os.environ.get("ARAC_API_BASE") or "").rstrip("/")


def _get(path: str) -> dict[str, Any]:
    """GET read-only loopback. Retourne le JSON (dict) ou ``{"error": ...}``. Ne lève jamais."""
    base = _base()
    if not base:
        # Sans adresse déclarée, on ne devine pas : deviner voudrait dire
        # interroger le cerveau du voisin et présenter sa mémoire comme la
        # nôtre. Une case vide est une information ; une case juste mais
        # remplie avec les souvenirs de quelqu'un d'autre n'en est pas une.
        return {"error": _UNAVAILABLE, "raison": "ARAC_API_BASE non déclarée"}
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.get(base + path, headers=entetes_api())
        if resp.status_code == 401:
            # Un 401 n'est PAS « l'API est en panne », et les confondre coûte
            # une soirée : l'API va très bien, c'est le cockpit qui parle sans
            # jeton. La cause est toujours la même — l'unité du cockpit a
            # perdu son `EnvironmentFile=` — et la case du tableau de bord est
            # le seul endroit où quelqu'un la lira.
            return {
                "error": _UNAVAILABLE,
                "status": 401,
                "raison": (
                    "l'API a refusé le jeton du cockpit. L'unité "
                    "<prefixe>-cockpit.service doit porter "
                    "EnvironmentFile=/etc/arac/<base>/arac.env, qui contient "
                    "ARAC_API_BEARER_TOKEN. L'API, elle, répond normalement."
                ),
            }
        if resp.status_code != 200:
            return {"error": _UNAVAILABLE, "status": resp.status_code}
        data = resp.json()
        return data if isinstance(data, dict) else {"error": _UNAVAILABLE}
    except Exception:  # noqa: BLE001 — résilience volontaire : aucune exception ne remonte au cockpit
        return {"error": _UNAVAILABLE}


def _strip_value(obj: Any) -> Any:
    """Défense en profondeur : retire récursivement toute clé ``value`` (jamais affichée)."""
    if isinstance(obj, dict):
        return {k: _strip_value(v) for k, v in obj.items() if k != "value"}
    if isinstance(obj, list):
        return [_strip_value(x) for x in obj]
    return obj


def brain_health() -> dict[str, Any]:
    """Rapport de santé consolidé du cerveau (score, sévérité, signaux, recommandations)."""
    return _strip_value(_get("/v1/brain/health"))


def current_state() -> dict[str, Any]:
    """Couverture state:current par feuille (coverage_pct, eligible_leaf_total, scopes)."""
    return _strip_value(_get("/v1/brain/current-state"))


def proposals() -> dict[str, Any]:
    """Propositions state:current (count + liste ; write_allowed=False côté API).

    L'endpoint ne supporte pas de paramètre `limit` ; la limitation d'affichage
    est faite côté cockpit (slice). On évite donc tout query string superflu.
    """
    return _strip_value(_get("/v1/brain/proposals"))


def memory_quality() -> dict[str, Any]:
    """Qualité mémoire = anti-drift (warnings) + sensitivity (taxonomie de risque)."""
    return {
        "anti_drift": _strip_value(_get("/v1/brain/anti-drift")),
        "sensitivity": _strip_value(_get("/v1/brain/sensitivity")),
    }
