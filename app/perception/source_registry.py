#!/usr/bin/env python3
"""Registre des sources de perception — collecteur C-0.

Lit `arac.ingest_sources` (registre honnête des sources de
conversation que le cerveau ARAC DEVRAIT capter) et croise avec la dernière
preuve que LE CAPTEUR A TOURNÉ (`max(arac.capture_manifests.run_ended_at)`
par `(node_id, source_type)`) pour produire un rapport {source_key: {policy,
last_seen, lag_minutes, status, ...}}. C'est la brique de base du bulletin
de santé sensoriel (`app/perception/conservation_audit.py`, section
`sources`) : elle répond, source par source, à « le CAPTEUR de cette source
est-il en vie, muet, ou délibérément non captée ? » — jamais un silence, et
JAMAIS une question sur l'ACTIVITÉ de l'utilisateur.

Correctif faux-positif (bulletin nocturne 2026-07-07, mission
Perception V4) : une version antérieure basait `lag_minutes`/`MUTE` sur
`max(arac.raw_messages.received_at)` — ce qui mesure l'ACTIVITÉ UTILISATEUR
(a-t-il écrit un message récemment ?), pas la SANTÉ DU CAPTEUR (le scanner
a-t-il tourné ?). Conséquence mesurée en prod : `claude_code@mac` déclarée
« muette depuis 103 min (seuil 30 min) » alors que son dernier
`capture_manifest.run_ended_at` datait de 3 min — le capteur tournait
PARFAITEMENT, seul l'utilisateur était inactif (pas de nouvelle session).
Un utilisateur inactif n'est jamais une panne. C'est EXACTEMENT le correctif
déjà appliqué à `ingest_watchdog.evaluate_source_freshness` (mêmes seuils
`expected_max_lag_minutes`, même autorité `capture_manifests.run_ended_at`,
mêmes docstrings de doctrine) — ce module le reproduit fidèlement pour la
même raison : le SEUL déclencheur de fraîcheur/`MUTE` est désormais « le
capteur a-t-il tourné », jamais « l'utilisateur a-t-il écrit ».
`last_message_received`/`message_lag_minutes` (activité utilisateur) restent
disponibles en CONTEXTE SECONDAIRE informationnel dans le rapport — jamais
comme déclencheur de statut.

Vocabulaire de statut (4 familles, jamais un 5e implicite) :
  - `OK`                  : `coverage_policy='captured'`, capteur fraîchement
                             tourné (`lag_minutes <= expected_max_lag_minutes`,
                             mesuré sur `capture_manifests.run_ended_at`) —
                             quelle que soit l'activité utilisateur.
  - `MUTE`                : `coverage_policy='captured'` mais le capteur a
                             cessé de tourner ALORS QU'IL A DÉJÀ TOURNÉ au
                             moins une fois (`lag_minutes` dépasse le seuil
                             déclaré) — un vrai signal démontrable de panne
                             DU CAPTEUR (jamais un simple silence utilisateur).
                             Le champ `machine_active` (lu sur `arac.nodes.
                             active`) accompagne ce statut pour EXPLIQUER un
                             mutisme bénin (machine hors service par
                             construction) sans jamais le requalifier
                             silencieusement en `OK` : la « gate » de
                             liveness machine est un CONTEXTE pour l'humain,
                             pas un filtre qui efface le signal : jamais
                             de « conforme » silencieux).
  - `PENDING_BOOTSTRAP`   : `coverage_policy='captured'` mais AUCUN manifeste
                             de capture jamais enregistré (`lag_minutes is
                             None`) — absence de preuve, pas preuve de panne
                             (capteur probablement pas encore déployé, cf
                             cutover `claude_code@mac` avant l'exportateur de
                             manifestes — correctif faux-CRIT
                             répétition 2026-07-07). Distinct de `MUTE` :
                             ne DOIT jamais déclencher la même alerte dure
                             qu'un capteur démontrablement mort. INCHANGÉ par
                             ce correctif : même en présence de messages
                             récents, l'absence de manifeste reste
                             `PENDING_BOOTSTRAP` (pas d'échappatoire par
                             l'activité utilisateur ici — contrairement au
                             bootstrap du watchdog qui, lui, tolère une
                             preuve positive par message récent). Toujours
                             VISIBLE dans le rapport (jamais une ligne
                             muette), jamais requalifié en `OK`.
  - `DECLARED_EXCLUDED` / `DECLARED_UNCOVERED` : `coverage_policy` in
                             ('excluded', 'uncovered') — motif déjà consigné
                             au registre (`exclusion_reason`), rien à
                             alerter, mais toujours VISIBLE dans le rapport
                             (jamais une ligne muette).

Fonctions PURES (`derive_source_status`, `build_source_report`) testables
sans DB — `tests/test_source_registry.py`. Collecteur DB séparé
(`collect_source_registry`), lecture seule (`SET TRANSACTION READ ONLY`).
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

STATUS_OK = "OK"
STATUS_MUTE = "MUTE"
STATUS_PENDING_BOOTSTRAP = "PENDING_BOOTSTRAP"
STATUS_DECLARED_EXCLUDED = "DECLARED_EXCLUDED"
STATUS_DECLARED_UNCOVERED = "DECLARED_UNCOVERED"
STATUS_UNKNOWN_POLICY = "UNKNOWN_POLICY"  # défensif — la CHECK DB interdit ce cas en pratique.


# ---------------------------------------------------------------------------
# Fonctions PURES — dérivation du statut (testables sans DB)
# ---------------------------------------------------------------------------


def derive_source_status(
    coverage_policy: str,
    lag_minutes: float | None,
    expected_max_lag_minutes: float | None,
) -> str:
    """(policy, lag mesuré, seuil déclaré) -> statut. Fonction PURE.

    `coverage_policy='captured'` : `PENDING_BOOTSTRAP` si aucune donnée
    jamais reçue (`lag_minutes is None` — absence de preuve, pas preuve de
    panne, cf docstring module) ; `MUTE` si une donnée a déjà été reçue au
    moins une fois mais que le signal s'est taris (`lag_minutes >
    expected_max_lag_minutes` — vrai signal de panne démontrable), ou si le
    seuil est manquant (défensif fail-closed — la contrainte
    `ingest_sources_honesty_check` l'exclut normalement). Sinon `OK`.

    `coverage_policy='excluded'|'uncovered'` : `DECLARED_*` inconditionnel
    (le motif est déjà consigné au registre — jamais recalculé ici).
    """
    if coverage_policy == "excluded":
        return STATUS_DECLARED_EXCLUDED
    if coverage_policy == "uncovered":
        return STATUS_DECLARED_UNCOVERED
    if coverage_policy != "captured":
        return STATUS_UNKNOWN_POLICY
    if lag_minutes is None:
        return STATUS_PENDING_BOOTSTRAP
    if expected_max_lag_minutes is None:
        return STATUS_MUTE
    if lag_minutes > expected_max_lag_minutes:
        return STATUS_MUTE
    return STATUS_OK


def build_source_report(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """(rows bruts par source) -> {source_key: {policy, last_seen,
    lag_minutes, status, ...}}. Fonction PURE — `rows` est déjà la sortie
    normalisée du collecteur DB (ou une fixture de test), aucune requête ici.

    Chaque row attendu : `source_key`, `node_id`, `source_type`,
    `coverage_policy`, `expected_max_lag_minutes`, `exclusion_reason`,
    `machine_active`, `last_seen` (dernier `capture_manifests.run_ended_at`
    — AUTORITÉ), `lag_minutes` (dérivé de `last_seen`). `last_message_received`/
    `message_lag_minutes` (dernier `raw_messages.received_at` — ACTIVITÉ
    UTILISATEUR) sont optionnels, purement informationnels, JAMAIS utilisés
    par `derive_source_status`.
    """
    report: dict[str, dict[str, Any]] = {}
    for row in rows:
        policy = row["coverage_policy"]
        lag = row.get("lag_minutes")
        expected = row.get("expected_max_lag_minutes")
        status = derive_source_status(policy, lag, expected)
        report[row["source_key"]] = {
            "policy": policy,
            "last_seen": row.get("last_seen"),
            "lag_minutes": lag,
            "status": status,
            "node_id": row.get("node_id"),
            "source_type": row.get("source_type"),
            "expected_max_lag_minutes": expected,
            "exclusion_reason": row.get("exclusion_reason"),
            "machine_active": row.get("machine_active"),
            # Contexte SECONDAIRE (activité utilisateur) — jamais un déclencheur.
            "last_message_received": row.get("last_message_received"),
            "message_lag_minutes": row.get("message_lag_minutes"),
        }
    return report


# ---------------------------------------------------------------------------
# I/O — mesure DB (lecture seule)
# ---------------------------------------------------------------------------

# AUTORITÉ = `capture_manifests.run_ended_at` (LE CAPTEUR A TOURNÉ), JAMAIS
# `raw_messages.received_at` (ACTIVITÉ UTILISATEUR — cf docstring module,
# correctif faux-positif 2026-07-07). `raw_messages.received_at` reste
# joint pour `message_lag_minutes`, contexte SECONDAIRE informationnel
# uniquement (jamais utilisé par `derive_source_status`).
_SOURCE_REGISTRY_SQL = (
    "SELECT s.source_key, s.node_id, s.source_type, s.coverage_policy, "
    "  s.expected_max_lag_minutes, s.exclusion_reason, n.active, "
    "  cap.last_run_ended, "
    "  EXTRACT(EPOCH FROM (now() - cap.last_run_ended))/60.0 AS lag_minutes, "
    "  msg.last_received, "
    "  EXTRACT(EPOCH FROM (now() - msg.last_received))/60.0 AS message_lag_minutes "
    "FROM arac.ingest_sources s "
    "JOIN arac.nodes n ON n.node_id = s.node_id "
    "LEFT JOIN ( "
    "  SELECT node_id, source_type, max(run_ended_at) AS last_run_ended "
    "  FROM arac.capture_manifests "
    "  WHERE run_ended_at IS NOT NULL "
    "  GROUP BY node_id, source_type "
    ") cap ON cap.node_id = s.node_id AND cap.source_type = s.source_type "
    "LEFT JOIN ( "
    "  SELECT c.node_id, c.source_type, max(m.received_at) AS last_received "
    "  FROM arac.raw_messages m "
    "  JOIN arac.conversations c ON c.id = m.conversation_id "
    "  GROUP BY c.node_id, c.source_type "
    ") msg ON msg.node_id = s.node_id AND msg.source_type = s.source_type "
    "ORDER BY s.source_key"
)


def collect_source_registry(dsn: str) -> dict[str, dict[str, Any]]:
    """LECTURE SEULE (`SET TRANSACTION READ ONLY`) : construit le rapport
    complet {source_key: {...}} pour TOUTES les sources du registre
    (captured/excluded/uncovered — jamais un sous-ensemble silencieux)."""
    import psycopg

    rows: list[dict[str, Any]] = []
    with psycopg.connect(dsn, connect_timeout=10) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        with conn.cursor() as cur:
            cur.execute(_SOURCE_REGISTRY_SQL)
            for r in cur.fetchall():
                rows.append({
                    "source_key": r[0],
                    "node_id": r[1],
                    "source_type": r[2],
                    "coverage_policy": r[3],
                    "expected_max_lag_minutes": float(r[4]) if r[4] is not None else None,
                    "exclusion_reason": r[5],
                    "machine_active": bool(r[6]),
                    "last_seen": str(r[7]) if r[7] is not None else None,
                    "lag_minutes": float(r[8]) if r[8] is not None else None,
                    "last_message_received": str(r[9]) if r[9] is not None else None,
                    "message_lag_minutes": float(r[10]) if r[10] is not None else None,
                })
    return build_source_report(rows)


# ---------------------------------------------------------------------------
# CLI minimal (invocation manuelle / debug — pas un daemon, oneshot)
# ---------------------------------------------------------------------------


def main() -> int:  # pragma: no cover — CLI mince, DB réelle
    dsn = os.environ.get("DATABASE_URL_READONLY") or os.environ.get("DATABASE_URL_APP")
    if not dsn:
        print(
            json.dumps({"event": "source_registry.error",
                       "error": "DATABASE_URL_READONLY/APP manquant"}),
            file=sys.stderr,
        )
        return 2
    try:
        report = collect_source_registry(dsn)
    except Exception as e:  # noqa: BLE001 — fail-closed-et-crier (cf conservation_audit)
        print(
            json.dumps({"event": "source_registry.unavailable",
                       "error": f"{type(e).__name__}: {e}"}),
            file=sys.stderr,
        )
        return 1
    print(json.dumps({"event": "source_registry.report", "sources": report},
                     ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
