"""Control Center v1 — exécution des métriques et résolution des preuves.

Ce module est un **transporteur**, pas un calculateur. Il ouvre une connexion
read-only, exécute le SQL déclaré dans le registre, et renvoie le résultat tel
quel. Il ne fait aucune arithmétique sur les données du cerveau : toute la
formule vit dans le SQL de la métrique (cf ``registry`` — deuxième invariant).

Résilience : aucune fonction publique ne lève sur une base injoignable ou une
requête en échec. Elle retourne un état ``unavailable`` porteur d'une raison —
jamais un zéro. C'est la règle I2 de la spécification : une donnée absente n'est
pas une donnée nulle, et l'interface doit pouvoir dire la différence.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.journal import raison, reduire, sha8
from control_center.cc_v1 import registry

__all__ = ["metric_value", "all_metrics", "evidence", "catalog"]

logger = logging.getLogger("arac.cc.v1")

_EVIDENCE_MAX_ROWS = 500


# ============================================================================
# Connexion — délègue au socle existant, fallback identique à db_metrics
# ============================================================================


def _connect_readonly():
    """Ouvre une connexion psycopg read-only via ``control_center.config``.

    Même contrat que ``control_center.collectors.db_metrics._connect_readonly``
    (rôle ``arac_readonly`` + ``default_transaction_read_only=on``). Lève si la
    connexion échoue ; les appelants publics capturent.
    """
    from control_center import config

    return config.db_connect_readonly()


# ============================================================================
# Sérialisation — rendre le résultat SQL transportable en JSON
# ============================================================================


def _jsonable(v: Any) -> Any:
    """Convertit une valeur psycopg en valeur JSON, sans perte de précision.

    Les ``Decimal`` deviennent ``float`` seulement s'ils ont une partie
    fractionnaire ; sinon ``int``. Cela évite d'afficher ``1712.0`` là où le
    cerveau compte 1712 objets.
    """
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc).isoformat()
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    return str(v)


def _state_for(m: registry.Metric, value: Any) -> str:
    """Évalue l'état sémantique d'une valeur contre les seuils de la métrique.

    Retourne ``ok`` / ``warn`` / ``critical``. Sans seuils déclarés, une valeur
    présente est ``ok`` : le registre n'invente jamais de seuil.
    """
    t = m.target
    if not t or not isinstance(value, (int, float)):
        return "ok"
    warn, crit, direction = t.get("warn"), t.get("critical"), t.get("direction", "down")
    if direction == "down":  # une valeur haute est mauvaise
        if crit is not None and value >= crit:
            return "critical"
        if warn is not None and value >= warn:
            return "warn"
    else:  # une valeur basse est mauvaise
        if crit is not None and value <= crit:
            return "critical"
        if warn is not None and value <= warn:
            return "warn"
    return "ok"


def _envelope(m: registry.Metric) -> dict[str, Any]:
    """Le descriptif d'une métrique, sans sa valeur — toujours servi, même en panne."""
    return {
        "key": m.key,
        "label": m.label,
        "unit": m.unit,
        "definition": m.definition,
        "formula": m.formula,
        "window": m.window,
        "domain": m.domain,
        "target": m.target,
        # Le chemin de preuve fait partie du contrat : il est servi avec la
        # valeur, pas déduit côté client.
        "evidence": {"kind": "metric", "ref": m.key, "href": f"/cc/v1/evidence/{m.key}",
                     "label": m.evidence_label},
    }


# ============================================================================
# API publique
# ============================================================================


def catalog() -> list[dict[str, Any]]:
    """Le registre sans exécution : utile pour documenter et pour tester."""
    return [_envelope(m) | {"sql": m.sql, "evidence_sql": m.evidence_sql} for m in registry.REGISTRY]


def metric_value(key: str, conn: Any = None) -> dict[str, Any]:
    """Exécute UNE métrique et retourne son enveloppe complète.

    Ne lève jamais : un échec produit ``state='unavailable'`` avec sa raison.
    """
    # `key` désigne ici l'identifiant d'une MÉTRIQUE du registre (un littéral
    # de `cc_v1/registry.py`), et non la clé d'un atome. Le journal le nomme
    # donc `metric_id` : le garde du journal refuse `key`, et il a raison de
    # le refuser — c'est au code de dire ce qu'il écrit.
    metric_id = key
    try:
        m = registry.by_key(key)
    except KeyError:
        return {"key": key, "state": "unavailable", "value": None,
                "reason": "métrique inconnue du registre"}

    env = _envelope(m)
    own_conn = conn is None
    started = time.perf_counter()
    try:
        c = _connect_readonly() if own_conn else conn
        try:
            with c.cursor() as cur:
                cur.execute(m.sql)
                row = cur.fetchone()
                cols = [d.name for d in (cur.description or [])]
        finally:
            if own_conn:
                c.close()
    except Exception as exc:  # noqa: BLE001 — résilience volontaire (I2)
        logger.warning("cc_v1.metric_failed",
                       extra={"metric_id": metric_id, "error": type(exc).__name__})
        return env | {"value": None, "state": "unavailable",
                      "reason": f"source indisponible ({type(exc).__name__})",
                      "computed_at": _now(), "duration_ms": _ms(started)}

    if not row:
        return env | {"value": None, "state": "unavailable",
                      "reason": "la requête n'a retourné aucune ligne",
                      "computed_at": _now(), "duration_ms": _ms(started)}

    data = dict(zip(cols, row)) if cols else {}
    value = _jsonable(data.get("value"))
    return env | {
        "value": value,
        "detail": _jsonable(data.get("detail")),
        # Les seuils déclarés SONT évalués ici. Écrire "ok" en dur rendait
        # `_state_for` inatteignable et toute la couche d'alerte de l'interface
        # décorative : 22 métriques dépassaient leur propre seuil, dont 13 en
        # critique, pendant que l'API affirmait "ok" pour les 98.
        "state": _state_for(m, value) if value is not None else "unavailable",
        # Une indisponibilité doit être UTILE : la métrique peut déclarer sa
        # propre raison, son geste de déblocage et son substitut. Le message
        # générique n'est qu'un dernier recours.
        #
        # POURQUOI la requête peut PRIMER sur le texte déclaré : une raison
        # écrite dans le registre est une affirmation faite au moment où on l'a
        # écrite, et elle continue d'être servie quand le monde a changé —
        # « telle table n'existe pas » reste affiché le jour où la migration
        # passe. Une métrique dont l'indisponibilité dépend de l'état RÉEL de la
        # base peut donc projeter une colonne ``reason`` (et ``gesture``) : le
        # cockpit sert alors ce que la requête a CONSTATÉ, pas ce que le code
        # postulait. C'est la même doctrine que partout ici — chaque chose
        # affichée descend d'un SQL rejouable — appliquée au texte comme aux
        # chiffres. Le champ déclaré reste le repli.
        "reason": None if value is not None else (
            _jsonable(data.get("reason"))
            or m.unavailable_reason
            or "valeur nulle retournée par la source"),
        "gesture": None if value is not None else (
            _jsonable(data.get("gesture")) or m.unavailable_gesture),
        "substitute": None if value is not None else m.substitute,
        "computed_at": _now(),
        "duration_ms": _ms(started),
    }


def all_metrics(domain: str | None = None) -> dict[str, Any]:
    """Exécute tout le registre (ou un domaine) sur UNE connexion partagée."""
    metrics = registry.by_domain(domain) if domain else registry.REGISTRY
    started = time.perf_counter()
    items: list[dict[str, Any]] = []
    conn = None
    try:
        conn = _connect_readonly()
    except Exception as exc:  # noqa: BLE001
        logger.warning("cc_v1.db_unreachable", extra={"error": type(exc).__name__})

    try:
        for m in metrics:
            items.append(metric_value(m.key, conn=conn) if conn is not None else
                         _envelope(m) | {"value": None, "state": "unavailable",
                                         "reason": "base injoignable", "computed_at": _now()})
    finally:
        if conn is not None:
            conn.close()

    return {"items": items, "count": len(items), "domain": domain,
            "computed_at": _now(), "duration_ms": _ms(started)}


def evidence(key: str, limit: int = 200) -> dict[str, Any]:  # noqa: D401
    """Résout la preuve d'une métrique : les lignes sources qui produisent sa valeur.

    C'est l'assertion G4 du mandat : depuis n'importe quel chiffre, on atteint
    la donnée. Le SQL exécuté est renvoyé avec le résultat — on peut le rejouer
    à l'identique depuis un terminal, donc vérifier que l'interface ne ment pas.
    """
    try:
        m = registry.by_key(key)
    except KeyError:
        return {"key": key, "state": "unavailable", "rows": [],
                "reason": "métrique inconnue du registre"}

    # Même remarque que dans `metric_value` : identifiant de métrique, pas
    # clé d'atome.
    metric_id = key
    limit = max(1, min(int(limit), _EVIDENCE_MAX_ROWS))
    started = time.perf_counter()
    try:
        conn = _connect_readonly()
        try:
            with conn.cursor() as cur:
                cur.execute(m.evidence_sql)
                cols = [d.name for d in (cur.description or [])]
                raw = cur.fetchmany(limit)
                truncated = cur.fetchone() is not None
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("cc_v1.evidence_failed",
                       extra={"metric_id": metric_id, "error": type(exc).__name__})
        return {"key": key, "state": "unavailable", "rows": [], "columns": [],
                "reason": f"source indisponible ({type(exc).__name__})",
                "computed_at": _now()}

    return {
        "key": m.key,
        "label": m.label,
        "state": "ok",
        "evidence_label": m.evidence_label,
        "definition": m.definition,
        "formula": m.formula,
        # Le SQL est rendu au client : la preuve est rejouable, donc opposable.
        "sql": " ".join(m.evidence_sql.split()),
        "value_sql": " ".join(m.sql.split()),
        "columns": cols,
        "rows": [[_jsonable(v) for v in r] for r in raw],
        "row_count": len(raw),
        "truncated": truncated,
        "limit": limit,
        "computed_at": _now(),
        "duration_ms": _ms(started),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
