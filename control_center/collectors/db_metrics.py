"""Control Center — collecteurs de métriques DB (READ-ONLY strict).

Doctrine : OBSERVE FIRST. DO NOT CONTROL. + READ ONLY.

Chaque fonction publique ouvre sa propre connexion read-only (via
``control_center.config.db_connect_readonly()`` quand disponible, sinon un
fallback défensif local sur ``DATABASE_URL_READONLY``), exécute UNIQUEMENT des
SELECT, puis ferme la connexion. Aucun INSERT / UPDATE / DELETE / TRUNCATE /
DROP n'apparaît dans ce module — c'est une invariante vérifiée statiquement par
les tests (``inspect.getsource``).

Résilience : si la base est injoignable (DSN absent, serveur down, table
manquante, rôle insuffisant), la fonction NE LÈVE PAS — elle retourne un dict
``{"error": "unavailable"}`` (ou ``{"error": "unavailable", "total": 0, ...}``
pour les résumés à compteurs). Le cockpit affiche « n/a » plutôt que de crasher.

Connexion : ``autocommit=True`` + ``options="-c default_transaction_read_only=on"``
— double couche défensive (rôle ``arac_readonly`` + session read-only).
"""

from __future__ import annotations

import os
from typing import Any

# Le sentinel de status renvoyé quand une source DB est injoignable.
_UNAVAILABLE = "unavailable"


# ============================================================================
# Connexion read-only — délègue à config, fallback local défensif
# ============================================================================


def _connect_readonly():
    """Ouvre une connexion psycopg read-only.

    Préfère ``control_center.config.db_connect_readonly()`` (interface fournie
    par l'agent config en parallèle). Si la fonction n'existe pas encore (ou si
    le module config n'est pas importable), bascule sur un fallback local strict
    et équivalent : ``DATABASE_URL_READONLY`` + autocommit + session read-only.

    Lève une exception si la connexion échoue — c'est le rôle des fonctions
    publiques de capturer cette exception et de retourner ``{"error": ...}``.
    """
    try:
        from control_center import config  # import paresseux : config créé en //

        connect = getattr(config, "db_connect_readonly", None)
        if callable(connect):
            return connect()
    except Exception:
        # config absent / non importable / signature inattendue → fallback.
        pass

    import psycopg  # import local : pas de coût si config a déjà répondu.

    dsn = os.environ["DATABASE_URL_READONLY"]
    return psycopg.connect(
        dsn,
        autocommit=True,
        options="-c default_transaction_read_only=on",
    )


def _group_counts(cur, table: str, column: str) -> dict[str, int]:
    """Retourne ``{valeur_colonne: count}`` pour un GROUP BY sur ``column``.

    Le nom de table/colonne est codé en dur côté appelant (jamais issu d'une
    entrée externe) — pas de surface d'injection. SELECT pur.
    """
    cur.execute(
        f"SELECT {column} AS k, COUNT(*) AS n "  # noqa: S608 — identifiants internes constants
        f"FROM arac.{table} GROUP BY {column}"
    )
    return {str(row[0]): int(row[1]) for row in cur.fetchall()}


# ============================================================================
# API publique
# ============================================================================


def memory_atoms_summary() -> dict[str, Any]:
    """Résumé des atomes mémoire : total + ventilations by_kind / by_scope / by_status.

    Forme nominale ::

        {
            "total": int,
            "by_kind":   {<kind>:   int, ...},
            "by_scope":  {<scope>:  int, ...},
            "by_status": {<status>: int, ...},
        }

    Forme dégradée (DB injoignable) ::

        {"error": "unavailable", "total": 0,
         "by_kind": {}, "by_scope": {}, "by_status": {}}
    """
    try:
        conn = _connect_readonly()
        try:
            with conn.cursor() as cur:
                by_kind = _group_counts(cur, "memory_atoms", "kind")
                by_scope = _group_counts(cur, "memory_atoms", "scope")
                by_status = _group_counts(cur, "memory_atoms", "status")
                cur.execute("SELECT COUNT(*) FROM arac.memory_atoms")
                total = int(cur.fetchone()[0])
        finally:
            conn.close()
        return {
            "total": total,
            "by_kind": by_kind,
            "by_scope": by_scope,
            "by_status": by_status,
        }
    except Exception:
        return {
            "error": _UNAVAILABLE,
            "total": 0,
            "by_kind": {},
            "by_scope": {},
            "by_status": {},
        }


def _compter(table: str) -> int | dict[str, Any]:
    """``COUNT(*)`` sur une table du schéma, ou ``{"error": "unavailable"}``.

    Le type composite est délibéré : il permet au cockpit de distinguer un 0
    RÉEL d'une indisponibilité. Voir ``render_tile`` / ``render_absence``.
    """
    try:
        conn = _connect_readonly()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM arac.{table}")
                return int(cur.fetchone()[0])
        finally:
            conn.close()
    except Exception:
        return {"error": _UNAVAILABLE}


def raw_conversations_count() -> int | dict[str, Any]:
    """Nombre de lignes dans ``arac.raw_conversations`` — TABLE GELÉE.

    ATTENTION AVANT DE S'EN SERVIR POUR UN CHIFFRE D'ACCUEIL.

    ``arac.raw_conversations`` est la file d'ingestion V1. Elle est GELÉE
    depuis la migration ``0017_freeze_raw_conversations`` : plus aucune ligne
    servie de ce dépôt n'y écrit (``app/routers/ingest.py`` : « raw_conversations
    est GELÉE » ; la route V1 rend 410 Gone). L'ingestion V2 écrit dans
    ``arac.conversations`` et ``arac.raw_messages`` (migration 0015).

    Conséquence : sur un cerveau installé après la bascule, ce compteur vaut 0
    le premier jour, et 0 au bout de six mois et de dix mille messages. Ce
    n'est pas un zéro, c'est une ABSENCE — et un zéro faux est pire qu'une
    absence, il se mesure. Cette fonction reste pour la LIGNÉE (les atomes
    d'avant la bascule y pointent par ``source_ref.curator_raw_id``) ; elle
    n'est plus la source d'une tuile du tableau de bord.
    """
    return _compter("raw_conversations")


def conversations_count() -> int | dict[str, Any]:
    """Nombre de conversations vivantes (``arac.conversations``, ingestion V2).

    C'est ce que le pont alimente réellement : ``POST /v1/ingest/messages``
    crée la conversation puis ses messages. Ce compteur bouge le jour même de
    la première synchronisation.
    """
    return _compter("conversations")


def raw_messages_count() -> int | dict[str, Any]:
    """Nombre de messages bruts absorbés (``arac.raw_messages``, ingestion V2).

    Même valeur que ``raw_messages_total`` de ``/cc/v1/metrics`` : le cockpit
    ne doit pas dire deux choses différentes d'une page à l'autre.
    """
    return _compter("raw_messages")


def ipq_summary() -> dict[str, Any]:
    """Résumé de la file IPQ (``arac.incoming_proposal_queue``) par status.

    Ventilation dynamique par valeur de ``status`` (GROUP BY) — couvre
    pending / approved / rejected et tout status présent en base sans le
    coder en dur (anti-fabulation : on lit ce qui existe).

    Forme nominale ::

        {"by_status": {<status>: int, ...}, "total": int}

    Forme dégradée ::

        {"error": "unavailable", "by_status": {}, "total": 0}
    """
    try:
        conn = _connect_readonly()
        try:
            with conn.cursor() as cur:
                by_status = _group_counts(cur, "incoming_proposal_queue", "status")
        finally:
            conn.close()
        return {"by_status": by_status, "total": sum(by_status.values())}
    except Exception:
        return {"error": _UNAVAILABLE, "by_status": {}, "total": 0}


def mrq_summary() -> dict[str, Any]:
    """Résumé de la file MRQ (``arac.memory_review_queue``) par status.

    Ventilation dynamique par valeur de ``status`` (GROUP BY) — couvre
    pending_human_review / reviewed / rejected / closed et tout status présent.

    Forme nominale ::

        {"by_status": {<status>: int, ...}, "total": int}

    Forme dégradée ::

        {"error": "unavailable", "by_status": {}, "total": 0}
    """
    try:
        conn = _connect_readonly()
        try:
            with conn.cursor() as cur:
                by_status = _group_counts(cur, "memory_review_queue", "status")
        finally:
            conn.close()
        return {"by_status": by_status, "total": sum(by_status.values())}
    except Exception:
        return {"error": _UNAVAILABLE, "by_status": {}, "total": 0}
