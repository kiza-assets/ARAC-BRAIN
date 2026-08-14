"""Control Center v1 — le FLUX TEMPS RÉEL du cerveau (SSE, READ-ONLY strict).

╔══════════════════════════════════════════════════════════════════════════════╗
║ HONNÊTETÉ DU TRANSPORT — à lire avant tout le reste                          ║
╚══════════════════════════════════════════════════════════════════════════════╝

Le moteur ARAC **ne publie pas d'événements**. Il n'existe aujourd'hui aucun
``LISTEN``/``NOTIFY`` sur les cycles, aucun déclencheur applicatif, aucun bus.
Poser un trigger serait une écriture DDL — donc interdit ici, et de toute façon
hors du périmètre de ce module.

Ce que fait réellement ce module, sans le déguiser :

    Le SERVEUR suit la base (« db-tailing » par filigranes / high-water marks)
    dans UNE tâche de fond partagée, et POUSSE les nouveautés aux clients
    connectés en SSE.

Du point de vue du navigateur, il n'y a aucun sondage : les événements arrivent
seuls. Du point de vue de la vérité, il y a un suivi de table à 1 Hz, et l'API le
DIT — champ ``transport`` servi sur ``/cc/v1/stream/state`` et
``/cc/v1/stream/catalog`` :

    {"mode": "db-tailing", "interval_ms": 1000,
     "note": "le serveur suit la base ; le client ne sonde pas"}

Prétendre « le moteur publie » serait un mensonge d'architecture : le cockpit
afficherait un temps réel qu'il n'a pas. La latence réelle d'un événement est
donc bornée par l'intervalle de suivi, et chaque événement porte à la fois
``ts`` (l'instant du FAIT, lu dans la base) et ``observed_at`` (l'instant où le
suiveur l'a vu). L'écart est visible, donc opposable.

VOIE D'ÉVOLUTION — le jour où le moteur publiera
------------------------------------------------
Quand le moteur émettra ses propres événements, le remplacement est local et ne
touche ni les routes, ni l'enveloppe, ni le catalogue de messages :

  1. côté moteur : ``NOTIFY arac_events, '<json>'`` (ou une table de sortie
     ``arac.event_outbox`` alimentée par un trigger d'écriture) ;
     — ces deux gestes appartiennent au MOTEUR, pas au cockpit : le mot-clé
     correspondant n'apparaît nulle part dans ce fichier, pas même en prose,
     pour qu'un scanner de source ne puisse jamais confondre la documentation
     d'une évolution avec une écriture ;
  2. ici : remplacer ``_Tailer._poll_blocking`` par une connexion
     ``LISTEN arac_events`` + ``conn.notifies()`` ;
  3. passer ``transport.mode`` à ``"listen-notify"`` et ``interval_ms`` à ``0``.

Tout le reste — anneau de rattrapage, filtres, groupement de rafales, catalogue
de messages, contrat d'enveloppe — reste inchangé. Le suivi par filigranes est
donc un **substitut déclaré**, pas une impasse.

╔══════════════════════════════════════════════════════════════════════════════╗
║ RÈGLE CAPITALE — le serveur n'écrit JAMAIS de phrase                         ║
╚══════════════════════════════════════════════════════════════════════════════╝

Un événement transporte une ``message_key`` (clé de gabarit) et des
``message_args`` typés. Jamais une phrase construite. Les phrases sont composées
côté client à partir de ``MESSAGE_CATALOG``, servi par
``/cc/v1/stream/catalog``.

C'est ce qui rend **structurellement impossible** l'affichage d'un texte qui ne
dérive pas d'une donnée : il n'existe aucun chemin par lequel une chaîne libre
atteigne l'écran. Un gabarit sans argument ne s'affiche pas ; un argument sans
gabarit n'a pas de place où aller. ``catalog_gaps()`` vérifie cette bijection et
le smoke test la rejoue.

╔══════════════════════════════════════════════════════════════════════════════╗
║ PRINCIPE CARDINAL — toute l'arithmétique est en SQL                          ║
╚══════════════════════════════════════════════════════════════════════════════╝

Aucune ligne de Python de ce module ne calcule sur les données du cerveau :

  - les durées (``duration_ms``, ``duration_s``) sont produites par
    ``extract(epoch FROM …)`` ;
  - les minutes de silence d'un nœud par ``floor(extract(epoch …)/60)`` ;
  - l'état de silence (ok/warn/critical) par un ``CASE`` comparant
    ``last_heartbeat`` aux seuils **de la ligne** ;
  - le ``level`` d'un événement, quand il dépend de la donnée (bande de rappel,
    échec de curation, lot de capture en erreur), par un ``CASE`` SQL ;
  - l'état de repos (``idle``) par un ``count(*) = 0`` ;
  - l'horaire des cycles et le PROCHAIN cycle par ``generate_series`` +
    ``AT TIME ZONE %(tz)s`` — le fuseau étant celui que DÉCLARE le cerveau
    (``ARAC_CYCLE_TZ``, cf. ``config.cycle_tz``), donc juste au changement
    d'heure, sans qu'une seule date ni un seul fuseau soit écrit en dur.

Le seul comptage effectué en Python est ``measures.count`` d'un événement
agrégé : il compte des ÉVÉNEMENTS QUE CE MODULE VIENT DE PRODUIRE, pas des
lignes du cerveau. Le nombre d'objets du cerveau, lui, est toujours lu tel quel.

L'HORAIRE N'EST PAS UNE CONSTANTE — il est OBSERVÉ
--------------------------------------------------
Les créneaux circadiens ne sont écrits nulle part dans ce fichier. Ils sont
extraits de ``arac.run_receipts.slot_key`` (motif ``circadian_HHMM@AAAA-MM-JJ``)
par ``_SQL_SCHEDULE``. Le cockpit affirme donc l'horaire que les reçus PROUVENT,
pas celui qu'on lui a raconté ; si le moteur gagne ou perd un créneau, le
cockpit l'apprend sans qu'on touche au code.

╔══════════════════════════════════════════════════════════════════════════════╗
║ LE REPOS EST UNE INFORMATION                                                  ║
╚══════════════════════════════════════════════════════════════════════════════╝

Le cerveau ne travaille que quelques fois par jour. Entre deux cycles, ce module
**n'émet rien** : ni faux battement, ni événement de remplissage, ni activité
de synthèse. ``/cc/v1/stream/state`` répond ``idle: true`` et donne la date du
prochain cycle. Un flux vide devant un cerveau au repos est le comportement
CORRECT — et le seul honnête.

LECTURE SEULE : ce module n'exécute que des ``SELECT``. Toutes les requêtes sont
statiques et littérales ; les seules entrées externes sont des filigranes lus
dans la base et des entiers bornés, passés en **paramètres liés**. Garde lexicale
``_assert_read_only`` appliquée à l'import sur la totalité du SQL du module,
en plus du rôle ``arac_readonly`` et de ``default_transaction_read_only=on``.

Routes exposées :

  GET /cc/v1/stream           le flux SSE (heartbeat 15 s, rattrapage ``since``)
  GET /cc/v1/events           repli JSON, même enveloppe
  GET /cc/v1/stream/catalog   le catalogue fermé des types + les gabarits
  GET /cc/v1/stream/state     repos, prochain cycle, filigranes, transport
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import string
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from control_center import config
from control_center.cc_v1 import service

__all__ = [
    "register",
    "MESSAGE_CATALOG",
    "EVENT_CATALOG",
    "TRANSPORT",
    "STAGES",
    "LEVELS",
    "STATUSES",
    "SUBJECT_KINDS",
    "Tailer",
    "get_tailer",
    "catalog_gaps",
    "stream_catalog",
    "stream_state",
]

logger = logging.getLogger("arac.cc.v1.stream")

_PREFIX = "/cc/v1"


# ============================================================================
# Réglages du suiveur — bornes dures, jamais dépassées
# ============================================================================

TAIL_INTERVAL_MS = 1000
"""Cadence nominale du suivi. Le CLIENT ne sonde pas : c'est le serveur qui suit."""

RING_CAPACITY = 2000
"""Anneau mémoire de rattrapage. Borné : un cockpit ne doit pas grossir sans fin."""

REPLAY_MAX_EVENTS = 1000
"""Plafond dur d'un rattrapage ``since=``."""

REPLAY_MAX_AGE_HOURS = 24
"""Au-delà, un événement n'est plus rejoué : il appartient à l'histoire, pas au flux."""

HEARTBEAT_SECONDS = 15
"""Battement SSE (ligne de commentaire ``:``). Tient la connexion ouverte à travers
les proxies. Ce n'est PAS un événement : il ne porte aucune donnée du cerveau et
n'apparaît jamais dans l'anneau."""

BURST_THRESHOLD = 5
"""Au-delà de ce nombre d'événements du même type dans ``BURST_WINDOW_S``, on agrège."""

BURST_WINDOW_S = 2.0
"""Fenêtre de rafale, en secondes, mesurée sur les horodatages SOURCE."""

ROW_CAP = 200
"""Plafond de lignes lues par source et par passage. Une rafale n'écroule pas le suivi."""

STOP_GRACE_SECONDS = 30.0
"""Délai de grâce avant l'arrêt du suiveur quand plus personne n'écoute."""

POLL_KEEPALIVE_SECONDS = 60.0
"""Un appel à ``/cc/v1/events`` maintient le suiveur en vie ce temps-là : le repli
JSON doit être un vrai repli, pas un flux mort."""

BACKOFF_STEPS_S = (1.0, 2.0, 5.0, 15.0, 30.0)
"""Attente croissante quand la base est injoignable. Le suiveur ne meurt jamais."""

CLOSE_WAIT_SECONDS = 5.0
"""Temps accordé à un passage EN VOL avant de renoncer à fermer sa connexion.

Fermer une connexion psycopg pendant qu'un autre fil exécute une requête dessus
fait tomber le PROCESSUS (segmentation fault dans libpq), pas seulement la
requête. Ce délai borne l'attente ; passé lui, la connexion est laissée ouverte
— une connexion en trop est un incident, un processus mort en est un autre."""

IN_PROGRESS_WINDOW = "6 hours"
"""Fenêtre au-delà de laquelle un passage sans fin n'est plus considéré en cours."""


# ============================================================================
# Vocabulaire fermé de l'enveloppe
# ============================================================================

STAGES: tuple[str, ...] = (
    "capture", "import", "analyse", "atomes", "liens",
    "index", "benchmark", "rappel", "systeme",
)

LEVELS: tuple[str, ...] = ("info", "notable", "anomalie")

_LEVEL_RANK: dict[str, int] = {"info": 0, "notable": 1, "anomalie": 2}

STATUSES: tuple[str, ...] = ("in_progress", "success", "failed", "skipped", "unavailable")

SUBJECT_KINDS: tuple[str, ...] = (
    "conversation", "atome", "projet", "run", "noeud", "requete",
)

TRANSPORT: dict[str, Any] = {
    "mode": "db-tailing",
    "interval_ms": TAIL_INTERVAL_MS,
    "note": "le serveur suit la base ; le client ne sonde pas",
    "engine_publishes": False,
    "why": (
        "le moteur ARAC n'émet aujourd'hui aucun événement (pas de LISTEN/NOTIFY, "
        "pas de table de sortie). Poser un trigger serait une écriture."
    ),
    "consequence": (
        "la latence d'un événement est bornée par interval_ms ; chaque événement "
        "porte ts (l'instant du fait) ET observed_at (l'instant où le suiveur l'a vu)"
    ),
    "evolution": (
        "quand le moteur publiera : NOTIFY arac_events → remplacer le passage de "
        "suivi par conn.notifies(), passer mode à listen-notify et interval_ms à 0. "
        "Enveloppe, routes et catalogue de messages restent inchangés."
    ),
    "sse": {
        "event_name": "arac.event",
        "id_field": "event_id",
        "resume": "en-tête Last-Event-ID, ou paramètre ?since=",
        "heartbeat_seconds": HEARTBEAT_SECONDS,
        "heartbeat_is_not_an_event": True,
    },
}


# ============================================================================
# Garde lecture seule — troisième couche, appliquée à l'import
# ============================================================================

FORBIDDEN_SQL: tuple[str, ...] = (
    "insert", "update", "delete", "truncate", "drop", "alter", "create",
    "grant", "revoke", "copy", "vacuum", "refresh", "call", "do",
)
"""Mots-clés interdits en position d'instruction, même contrat que ``registry`` et
``entities``. Une faute d'inattention est attrapée avant qu'une connexion s'ouvre."""

_WORD = re.compile(r"[a-z_]+")
_LITERAL = re.compile(r"'(?:[^']|'')*'")


def _assert_read_only(sql: str, where: str) -> None:
    """Lève ``ValueError`` si ``sql`` contient une instruction mutante.

    Les littéraux entre apostrophes sont retirés avant l'examen : un mot dans une
    chaîne est de la donnée, jamais une instruction.
    """
    body = _LITERAL.sub(" ", sql.lower())
    hit = set(_WORD.findall(body)) & set(FORBIDDEN_SQL)
    if hit:
        raise ValueError(f"{where}: instruction mutante interdite : {sorted(hit)}")


# ============================================================================
# LE SQL — un filigrane par source, une requête par source
# ============================================================================
#
# Filigranes entiers (``id``) : la comparaison stricte ``id > filigrane`` est
# exacte, un bigint ne connaît pas d'ex æquo.
#
# Filigranes temporels : ``created_at`` d'un lot d'atomes vaut l'horodatage de
# TRANSACTION — des dizaines d'atomes partagent la même microseconde (vérifié :
# max(created_at) = max(updated_at) sur memory_atoms). Un ``>`` strict perdrait
# les ex æquo, un ``>=`` les rejouerait en boucle. On lit donc en ``>=`` et on
# retient les identifiants déjà émis à l'horodatage de bord (cf ``_TsCursor``).

_SQL_WATERMARKS = """
SELECT
  (SELECT coalesce(max(created_at), now()) FROM arac.memory_atoms)          AS atom_created_ts,
  (SELECT coalesce(max(updated_at), now()) FROM arac.memory_atoms
     WHERE status = 'superseded')                                          AS atom_superseded_ts,
  (SELECT coalesce(max(id), 0)             FROM arac.run_receipts)         AS run_id,
  (SELECT coalesce(max(ended_at), now())   FROM arac.run_receipts)         AS run_ended_ts,
  (SELECT coalesce(max(id), 0)             FROM arac.context_receipts)     AS recall_id,
  (SELECT coalesce(max(id), 0)             FROM arac.ingest_receipts)      AS ingest_id,
  (SELECT coalesce(max(id), 0)             FROM arac.capture_manifests)    AS capture_id,
  (SELECT coalesce(max(curated_at), now()) FROM arac.conversations)        AS curation_ts,
  (SELECT coalesce(max(id), 0)             FROM arac.digestion_review_queue) AS dropped_id,
  (SELECT coalesce(max(id), 0)             FROM arac.audit_log
     WHERE success IS false)                                               AS audit_id,
  now()                                                                    AS server_now
"""

_SQL_ATOM_CREATED = """
SELECT a.id, a.kind, a.scope, a.key, a.status, a.confidence, a.confidence_score,
       a.node_id, a.session_id, a.created_at AS ts
FROM arac.memory_atoms a
WHERE a.created_at >= %(wm)s
  AND a.kind <> 'agent_message'
ORDER BY a.created_at ASC, a.id ASC
LIMIT %(cap)s
"""
# `agent_message` est du TRANSPORT, jamais du savoir : il ne compte pas comme un
# atome, donc il ne produit pas d'événement `atom.created`.

_SQL_ATOM_SUPERSEDED = """
SELECT a.id, a.kind, a.scope, a.key, a.superseded_by, a.node_id,
       a.updated_at AS ts
FROM arac.memory_atoms a
WHERE a.status = 'superseded'
  AND a.updated_at >= %(wm)s
ORDER BY a.updated_at ASC, a.id ASC
LIMIT %(cap)s
"""

_SQL_RUNS = """
SELECT r.id, r.slot_key, r.trigger, r.model, r.status, r.skip_reason, r.stop_reason,
       r.outcome, r.spawns, r.items, r.atoms_created, r.atoms_superseded,
       r.atoms_confirmed, r.atoms_quarantined, r.conflicts_409,
       r.messages_reported, r.coverage_presented, r.coverage_covered,
       r.started_at, r.ended_at,
       CASE WHEN r.ended_at IS NULL AND r.skip_reason IS NULL
            THEN 'in_progress' ELSE 'terminal' END                    AS lifecycle,
       round(extract(epoch FROM (r.ended_at - r.started_at)) * 1000)::bigint AS duration_ms,
       round(extract(epoch FROM (r.ended_at - r.started_at)))::bigint        AS duration_s,
       coalesce(r.ended_at, r.started_at)                             AS ts
FROM arac.run_receipts r
WHERE r.id > %(wm_id)s
   OR r.ended_at >= %(wm_ts)s
   OR r.id = ANY(%(open_ids)s::bigint[])
ORDER BY r.id ASC
LIMIT %(cap)s
"""
# `lifecycle` distingue un passage EN COURS d'un passage terminé, sans énumérer
# les statuts : un passage est en cours quand il n'a ni fin ni raison de saut.
# Règle vérifiée sur la totalité de l'historique (0 exception sur 138 passages) —
# les passages `skipped` n'ont jamais de `ended_at`, ils portent un `skip_reason`.

_SQL_RECALL = """
SELECT c.id, c.request_id, c.consumer, c.engine_version, c.calibration_version,
       c.scope_filter, c.kind_filter, c.k_requested, c.budget_k,
       c.raw_band, c.final_band, c.stop_reason, c.scope_prefix_gain,
       round(c.top1_distance_final::numeric, 4) AS top1_distance,
       round(c.top1_distance_raw::numeric, 4)   AS top1_distance_raw,
       round(c.shadow_latency_ms::numeric, 1)   AS latency_ms,
       coalesce(array_length(c.served_ids, 1), 0) AS served_count,
       CASE WHEN c.final_band IN ('high', 'medium') THEN 'notable'
            ELSE 'info' END                     AS level,
       c.created_at AS ts
FROM arac.context_receipts c
WHERE c.id > %(wm_id)s
ORDER BY c.id ASC
LIMIT %(cap)s
"""

_SQL_INGEST = """
SELECT i.id, i.request_id, i.node_id, i.source_type, i.conversation_uid, i.outcome,
       i.http_status, i.received, i.inserted, i.duplicates, i.hash_divergences,
       i.empty_messages, i.masked_messages, i.refusal_detail, i.origin_kind,
       CASE WHEN jsonb_typeof(i.scrub_hits) = 'array'
            THEN jsonb_array_length(i.scrub_hits) END AS scrub_hits_count,
       i.created_at AS ts
FROM arac.ingest_receipts i
WHERE i.id > %(wm_id)s
ORDER BY i.id ASC
LIMIT %(cap)s
"""

_SQL_CAPTURE = """
SELECT m.id, m.node_id, m.source_type, m.files_scanned, m.sessions,
       m.messages_read, m.messages_emitted, m.batches_ok, m.batches_failed,
       m.ack_mismatches, m.archive_bytes,
       pg_size_pretty(m.archive_bytes) AS archive_size,
       round(extract(epoch FROM (m.run_ended_at - m.run_started_at)) * 1000)::bigint
                                       AS duration_ms,
       CASE WHEN m.batches_failed > 0 OR m.ack_mismatches > 0 THEN 'anomalie'
            ELSE 'info' END            AS level,
       CASE WHEN m.batches_failed > 0 THEN 'failed' ELSE 'success' END AS status,
       m.created_at AS ts
FROM arac.capture_manifests m
WHERE m.id > %(wm_id)s
ORDER BY m.id ASC
LIMIT %(cap)s
"""

_SQL_CURATION = """
SELECT c.id, c.conversation_uid, c.title, c.source_type, c.node_id,
       c.atoms_generated, c.curated_through_message_id, c.retry_count,
       c.last_curation_error,
       CASE WHEN c.last_curation_error IS NOT NULL THEN 'anomalie'
            ELSE 'info' END AS level,
       CASE WHEN c.last_curation_error IS NOT NULL THEN 'failed'
            ELSE 'success' END AS status,
       c.curated_at AS ts
FROM arac.conversations c
WHERE c.curated_at >= %(wm)s
ORDER BY c.curated_at ASC, c.id ASC
LIMIT %(cap)s
"""

_SQL_DROPPED = """
SELECT q.id, q.run_ref, q.conversation_uid, q.drop_reason, q.scope, q.kind,
       q.status AS queue_status, q.incumbent_atom_id, q.created_at AS ts
FROM arac.digestion_review_queue q
WHERE q.id > %(wm_id)s
ORDER BY q.id ASC
LIMIT %(cap)s
"""

_SQL_AUDIT_FAILED = """
SELECT l.id, l.node_id, l.action, l.tool_name, l.target_atom_id,
       l.error_message, l.warning_code, l.latency_ms, l.tokens_used,
       l.created_at AS ts
FROM arac.audit_log l
WHERE l.success IS false
  AND l.id > %(wm_id)s
ORDER BY l.id ASC
LIMIT %(cap)s
"""

_SQL_NODES = """
SELECT n.node_id, n.role, n.account, n.owner, n.last_heartbeat,
       n.silent_warn_minutes, n.silent_critical_minutes, n.expected_cadence_minutes,
       floor(extract(epoch FROM (now() - n.last_heartbeat)) / 60)::bigint
                                        AS silent_minutes,
       CASE
         WHEN n.last_heartbeat IS NULL THEN 'unknown'
         WHEN n.silent_critical_minutes IS NOT NULL
              AND now() - n.last_heartbeat > make_interval(mins => n.silent_critical_minutes)
           THEN 'critical'
         WHEN n.silent_warn_minutes IS NOT NULL
              AND now() - n.last_heartbeat > make_interval(mins => n.silent_warn_minutes)
           THEN 'warn'
         ELSE 'ok'
       END                              AS silence_state,
       now() AS ts
FROM arac.nodes n
WHERE n.active
ORDER BY n.node_id ASC
LIMIT %(cap)s
"""
# Le seuil de silence appartient à la LIGNE (chaque nœud a sa cadence). On ne
# compare jamais un nœud à une constante inventée côté cockpit.

_SQL_OPEN_RUNS = """
SELECT r.id, r.status
FROM arac.run_receipts r
WHERE r.ended_at IS NULL AND r.skip_reason IS NULL
ORDER BY r.id DESC
LIMIT %(cap)s
"""

_SQL_IDLE = """
SELECT (SELECT count(*) FROM arac.run_receipts
          WHERE ended_at IS NULL AND skip_reason IS NULL
            AND started_at > now() - interval '""" + IN_PROGRESS_WINDOW + """') = 0
                                                        AS idle,
       (SELECT count(*) FROM arac.run_receipts
          WHERE ended_at IS NULL AND skip_reason IS NULL
            AND started_at > now() - interval '""" + IN_PROGRESS_WINDOW + """')
                                                        AS runs_in_progress,
       (SELECT max(started_at) FROM arac.run_receipts)  AS last_run_started_at,
       (SELECT max(ended_at)   FROM arac.run_receipts)  AS last_run_ended_at,
       (SELECT max(created_at) FROM arac.capture_manifests) AS last_capture_at,
       (SELECT max(created_at) FROM arac.ingest_receipts)   AS last_ingest_at,
       (SELECT max(created_at) FROM arac.memory_atoms)      AS last_atom_at,
       now() AS server_now
"""

_SQL_SCHEDULE = """
SELECT substring(r.slot_key from 'circadian_([0-9]{4})') AS slot,
       substring(substring(r.slot_key from 'circadian_([0-9]{4})') from 1 for 2)
         || ':' ||
       substring(substring(r.slot_key from 'circadian_([0-9]{4})') from 3 for 2)
                            AS local_time,
       count(*)             AS runs,
       max(r.started_at)    AS last_run_at
FROM arac.run_receipts r
WHERE r.slot_key ~ '^circadian_[0-9]{4}'
GROUP BY 1, 2
ORDER BY 1
"""
# L'horaire du cerveau n'est pas une constante de ce fichier : il est LU dans
# les reçus de passage. Le cockpit affirme ce que les receipts prouvent.

_SQL_NEXT_CYCLE = """
WITH slots AS (
  SELECT DISTINCT substring(slot_key from 'circadian_([0-9]{4})') AS hhmm
  FROM arac.run_receipts
  WHERE slot_key ~ '^circadian_[0-9]{4}'
),
days AS (
  SELECT generate_series((now() AT TIME ZONE %(tz)s)::date - 1,
                         (now() AT TIME ZONE %(tz)s)::date + 2,
                         interval '1 day')::date AS day
),
occurrences AS (
  SELECT s.hhmm,
         ((d.day + make_time(substring(s.hhmm from 1 for 2)::int,
                             substring(s.hhmm from 3 for 2)::int, 0))
            AT TIME ZONE %(tz)s) AS at_utc
  FROM slots s CROSS JOIN days d
)
SELECT hhmm                                                 AS slot,
       substring(hhmm from 1 for 2) || ':' || substring(hhmm from 3 for 2)
                                                            AS local_time,
       at_utc,
       round(extract(epoch FROM (at_utc - now())))::bigint  AS in_seconds
FROM occurrences
WHERE at_utc > now()
ORDER BY at_utc ASC
LIMIT 1
"""
# `AT TIME ZONE %(tz)s` applique la règle de décalage EN VIGUEUR à cette date-là :
# le prochain cycle reste juste la nuit du changement d'heure, sans qu'une seule
# date soit écrite en dur.
#
# POURQUOI le fuseau est un PARAMÈTRE LIÉ et non un littéral : les créneaux
# circadiens sont des heures LOCALES du serveur qui exécute les cycles. Un fuseau
# gravé ici serait celui de la machine où ce fichier a été écrit — et servirait à
# tous les autres cerveaux un « prochain cycle » décalé du décalage entre les deux
# fuseaux, sans jamais le dire. Il vient donc de `config.cycle_tz()`, la même
# source (`ARAC_CYCLE_TZ`) que celle qui arme les minuteries des cycles.

_ALL_SQL: dict[str, str] = {
    "watermarks": _SQL_WATERMARKS,
    "atom_created": _SQL_ATOM_CREATED,
    "atom_superseded": _SQL_ATOM_SUPERSEDED,
    "runs": _SQL_RUNS,
    "recall": _SQL_RECALL,
    "ingest": _SQL_INGEST,
    "capture": _SQL_CAPTURE,
    "curation": _SQL_CURATION,
    "dropped": _SQL_DROPPED,
    "audit_failed": _SQL_AUDIT_FAILED,
    "nodes": _SQL_NODES,
    "open_runs": _SQL_OPEN_RUNS,
    "idle": _SQL_IDLE,
    "schedule": _SQL_SCHEDULE,
    "next_cycle": _SQL_NEXT_CYCLE,
}

for _name, _sql in _ALL_SQL.items():
    _assert_read_only(_sql, f"stream.{_name}")


# ============================================================================
# LE CATALOGUE DES ÉVÉNEMENTS — fermé, servi, vérifiable
# ============================================================================
#
# Un type absent de ce catalogue ne peut pas être émis (``_build`` refuse), et un
# type présent sans gabarit fait échouer ``catalog_gaps()``. Le client n'a donc
# jamais à deviner ni à inventer : ce qu'il peut afficher est énuméré ici.

EVENT_CATALOG: tuple[dict[str, Any], ...] = (
    {"type": "atom.created", "stage": "atomes", "level": "info", "status": "success",
     "subject_kind": "atome", "source": "arac.memory_atoms",
     "watermark": "max(created_at)",
     "note": "les atomes de kind 'agent_message' sont du transport, pas du savoir : exclus",
     "args": ["kind", "scope"], "measures": ["confidence_score"]},

    {"type": "atom.superseded", "stage": "atomes", "level": "notable", "status": "success",
     "subject_kind": "atome", "source": "arac.memory_atoms",
     "watermark": "max(updated_at) où status = 'superseded'",
     "args": ["kind", "scope"], "measures": []},

    {"type": "atom.dropped", "stage": "atomes", "level": "anomalie", "status": "skipped",
     "subject_kind": "atome", "source": "arac.digestion_review_queue",
     "watermark": "max(id)",
     "args": ["drop_reason", "scope"], "measures": []},

    {"type": "cycle.started", "stage": "analyse", "level": "info", "status": "in_progress",
     "subject_kind": "run", "source": "arac.run_receipts",
     "watermark": "max(id)",
     "args": ["slot", "trigger"], "measures": ["items", "spawns"]},

    {"type": "cycle.finished", "stage": "analyse", "level": "notable", "status": "success",
     "subject_kind": "run", "source": "arac.run_receipts",
     "watermark": "max(ended_at)",
     "args": ["atoms_created", "duration_s"],
     "measures": ["atoms_created", "atoms_superseded", "atoms_confirmed",
                  "atoms_quarantined", "items", "duration_ms", "duration_s"]},

    {"type": "cycle.quarantined", "stage": "analyse", "level": "anomalie", "status": "failed",
     "subject_kind": "run", "source": "arac.run_receipts",
     "watermark": "max(ended_at)",
     "args": ["stop_reason"], "measures": ["atoms_quarantined", "items", "duration_s"]},

    {"type": "cycle.spawn_failed", "stage": "analyse", "level": "anomalie", "status": "failed",
     "subject_kind": "run", "source": "arac.run_receipts",
     "watermark": "max(ended_at)",
     "args": ["stop_reason"], "measures": ["spawns", "duration_s"]},

    {"type": "cycle.skipped", "stage": "analyse", "level": "info", "status": "skipped",
     "subject_kind": "run", "source": "arac.run_receipts",
     "watermark": "changement de statut (skip_reason renseigné, pas de ended_at)",
     "args": ["skip_reason"], "measures": ["items"]},

    {"type": "recall.served", "stage": "rappel", "level": "info", "status": "success",
     "subject_kind": "requete", "source": "arac.context_receipts",
     "watermark": "max(id)",
     "note": "level passe à 'notable' quand final_band vaut high ou medium (CASE SQL)",
     "args": ["band", "served_count", "stop_reason"],
     "measures": ["served_count", "k_requested", "budget_k", "top1_distance", "latency_ms"]},

    {"type": "ingest.accepted", "stage": "import", "level": "info", "status": "success",
     "subject_kind": "conversation", "source": "arac.ingest_receipts",
     "watermark": "max(id)",
     "args": ["inserted", "received"],
     "measures": ["received", "inserted", "duplicates", "hash_divergences",
                  "empty_messages", "masked_messages"]},

    {"type": "ingest.denied", "stage": "import", "level": "anomalie", "status": "failed",
     "subject_kind": "conversation", "source": "arac.ingest_receipts",
     "watermark": "max(id)",
     "args": ["outcome"], "measures": ["received", "http_status"]},

    {"type": "capture.detected", "stage": "capture", "level": "info", "status": "success",
     "subject_kind": "noeud", "source": "arac.capture_manifests",
     "watermark": "max(id)",
     "note": "level passe à 'anomalie' si batches_failed > 0 ou ack_mismatches > 0 (CASE SQL)",
     "args": ["node", "messages_emitted"],
     "measures": ["files_scanned", "sessions", "messages_read", "messages_emitted",
                  "batches_ok", "batches_failed", "ack_mismatches", "duration_ms"]},

    {"type": "curation.finished", "stage": "analyse", "level": "info", "status": "success",
     "subject_kind": "conversation", "source": "arac.conversations",
     "watermark": "max(curated_at)",
     "note": "level passe à 'anomalie' si last_curation_error est renseigné (CASE SQL)",
     "args": ["atoms_generated"],
     "measures": ["atoms_generated", "retry_count"]},

    {"type": "audit.failed", "stage": "systeme", "level": "anomalie", "status": "failed",
     "subject_kind": "noeud", "source": "arac.audit_log",
     "watermark": "max(id) où success = false",
     "args": ["action"], "measures": ["latency_ms", "tokens_used"]},

    {"type": "node.silent", "stage": "systeme", "level": "anomalie", "status": "failed",
     "subject_kind": "noeud", "source": "arac.nodes",
     "watermark": "last_heartbeat comparé à silent_warn_minutes / silent_critical_minutes",
     "note": "émis sur TRANSITION uniquement ; l'amorçage photographie l'état sans émettre",
     "args": ["node", "silent_minutes", "severity"],
     "measures": ["silent_minutes", "silent_warn_minutes", "silent_critical_minutes"]},

    {"type": "node.recovered", "stage": "systeme", "level": "notable", "status": "success",
     "subject_kind": "noeud", "source": "arac.nodes",
     "watermark": "last_heartbeat comparé aux seuils de la ligne",
     "note": "sans lui, une alarme de silence resterait affichée après le retour du nœud",
     "args": ["node"], "measures": ["silent_minutes"]},

    {"type": "systeme.tailing_started", "stage": "systeme", "level": "info", "status": "success",
     "subject_kind": None, "source": "le suiveur lui-même",
     "watermark": "—",
     "note": "fait vérifiable sur le SERVEUR, pas une activité du cerveau",
     "args": ["sources"], "measures": ["sources"]},

    {"type": "systeme.source_unavailable", "stage": "systeme", "level": "anomalie",
     "status": "unavailable", "subject_kind": None, "source": "le suiveur lui-même",
     "watermark": "—",
     "note": "émis sur TRANSITION vers la panne, jamais à chaque passage",
     "args": ["error"], "measures": ["attempts"]},

    {"type": "systeme.source_recovered", "stage": "systeme", "level": "notable",
     "status": "success", "subject_kind": None, "source": "le suiveur lui-même",
     "watermark": "—",
     "args": ["attempts"], "measures": ["attempts"]},

    {"type": "systeme.replay_truncated", "stage": "systeme", "level": "notable",
     "status": "unavailable", "subject_kind": None, "source": "l'anneau de rattrapage",
     "watermark": "—",
     "note": "le since demandé précède le plus ancien événement encore en mémoire",
     "args": ["since"], "measures": ["ring_size"]},
)

_BY_TYPE: dict[str, dict[str, Any]] = {e["type"]: e for e in EVENT_CATALOG}


MESSAGE_CATALOG: dict[str, str] = {
    # --- atomes -------------------------------------------------------------
    "atom.created": "Atome créé — {kind} · {scope}",
    "atom.created.burst": "{count} atomes créés",
    "atom.superseded": "Atome remplacé — {kind} · {scope}",
    "atom.superseded.burst": "{count} atomes remplacés",
    "atom.dropped": "Atome rejeté — {drop_reason} · {scope}",
    "atom.dropped.burst": "{count} atomes rejetés",
    # --- analyse ------------------------------------------------------------
    "cycle.started": "Cycle démarré — {slot} · {trigger}",
    "cycle.started.burst": "{count} cycles démarrés",
    "cycle.finished": "Cycle terminé — {atoms_created} atomes en {duration_s} s",
    "cycle.finished.burst": "{count} cycles terminés",
    "cycle.quarantined": "Cycle mis en quarantaine — {stop_reason}",
    "cycle.quarantined.burst": "{count} cycles mis en quarantaine",
    "cycle.spawn_failed": "Échec de lancement du cycle — {stop_reason}",
    "cycle.spawn_failed.burst": "{count} échecs de lancement",
    "cycle.skipped": "Cycle sauté — {skip_reason}",
    "cycle.skipped.burst": "{count} cycles sautés",
    "curation.finished": "Conversation curée — {atoms_generated} atomes produits",
    "curation.finished.burst": "{count} conversations curées",
    # --- rappel -------------------------------------------------------------
    "recall.served": "Rappel servi — bande {band} · {served_count} atomes · arrêt {stop_reason}",
    "recall.served.burst": "{count} rappels servis",
    # --- import / capture ---------------------------------------------------
    "ingest.accepted": "Ingestion acceptée — {inserted} messages retenus sur {received}",
    "ingest.accepted.burst": "{count} ingestions acceptées",
    "ingest.denied": "Ingestion refusée — {outcome}",
    "ingest.denied.burst": "{count} ingestions refusées",
    "capture.detected": "Capture — {messages_emitted} messages émis par {node}",
    "capture.detected.burst": "{count} captures",
    # --- système ------------------------------------------------------------
    "audit.failed": "Appel d'audit en échec — {action}",
    "audit.failed.burst": "{count} appels d'audit en échec",
    "node.silent": "Nœud silencieux — {node}, {silent_minutes} min ({severity})",
    "node.silent.burst": "{count} nœuds silencieux",
    "node.recovered": "Nœud de nouveau vivant — {node}",
    "node.recovered.burst": "{count} nœuds de nouveau vivants",
    "systeme.tailing_started": "Suivi de la base démarré — {sources} sources sous filigrane",
    "systeme.source_unavailable": "Source indisponible — {error}",
    "systeme.source_recovered": "Source de nouveau disponible après {attempts} tentatives",
    "systeme.replay_truncated":
        "Rattrapage incomplet — les événements antérieurs à {since} ne sont plus en mémoire",
}
"""Gabarits FRANÇAIS à trous. Le serveur ne compose jamais de phrase : il envoie
une clé de ce dictionnaire et des arguments typés. Le client rend la phrase.

Corollaire structurel : une phrase qui ne dérive pas d'une donnée n'a aucun
chemin pour atteindre l'écran — il faudrait à la fois un gabarit ici et des
arguments produits par le SQL."""


def _placeholders(template: str) -> set[str]:
    """Les noms de trous d'un gabarit (``{kind}`` → ``kind``)."""
    return {f for _, f, _, _ in string.Formatter().parse(template) if f}


def catalog_gaps() -> dict[str, list[str]]:
    """Vérifie la bijection catalogue d'événements ↔ catalogue de messages.

    Retourne un dictionnaire de manquements, VIDE quand tout est cohérent :

      ``missing_template``   un type déclaré sans gabarit ;
      ``missing_burst``      un type sans gabarit de rafale ;
      ``orphan_template``    un gabarit sans type correspondant ;
      ``unfilled_args``      un gabarit dont un trou n'est promis par aucun ``args`` ;
      ``bad_stage``/``bad_level``/``bad_status``/``bad_subject_kind``
                             une valeur hors du vocabulaire fermé.

    C'est le test qui rend la règle capitale exécutable plutôt que déclarative.
    """
    gaps: dict[str, list[str]] = {
        "missing_template": [], "missing_burst": [], "orphan_template": [],
        "unfilled_args": [], "bad_stage": [], "bad_level": [],
        "bad_status": [], "bad_subject_kind": [],
    }
    for e in EVENT_CATALOG:
        t = e["type"]
        if e["stage"] not in STAGES:
            gaps["bad_stage"].append(t)
        if e["level"] not in LEVELS:
            gaps["bad_level"].append(t)
        if e["status"] not in STATUSES:
            gaps["bad_status"].append(t)
        if e["subject_kind"] is not None and e["subject_kind"] not in SUBJECT_KINDS:
            gaps["bad_subject_kind"].append(t)

        tpl = MESSAGE_CATALOG.get(t)
        if tpl is None:
            gaps["missing_template"].append(t)
        else:
            promised = set(e["args"]) | set(e.get("measures", []))
            missing = _placeholders(tpl) - promised
            if missing:
                gaps["unfilled_args"].append(f"{t}: {sorted(missing)}")

        # Les événements « une fois » du suiveur ne peuvent pas former de rafale.
        if not t.startswith("systeme.") and f"{t}.burst" not in MESSAGE_CATALOG:
            gaps["missing_burst"].append(t)

    known = {e["type"] for e in EVENT_CATALOG}
    for key in MESSAGE_CATALOG:
        base = key[: -len(".burst")] if key.endswith(".burst") else key
        if base not in known:
            gaps["orphan_template"].append(key)

    return {k: v for k, v in gaps.items() if v}


# ============================================================================
# Construction d'un événement — la seule porte d'entrée de l'enveloppe
# ============================================================================

_BOOT_MS = int(time.time() * 1000)
"""Millisecondes epoch au chargement du module. Préfixe des identifiants
d'événement : après un redémarrage, les identifiants restent strictement
supérieurs à ceux d'avant — donc l'ordre lexicographique reste un ordre
chronologique, même à travers un redémarrage."""


def _j(v: Any) -> Any:
    """Rend une valeur psycopg transportable en JSON (délègue au socle)."""
    return service._jsonable(v)


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


@dataclass
class _Raw:
    """Événement avant numérotation : tout est là sauf l'``event_id``."""

    type: str
    ts: datetime
    subject: dict[str, Any] | None = None
    measures: dict[str, Any] = field(default_factory=dict)
    args: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] | None = None
    level: str | None = None      # surcharge du catalogue (venue d'un CASE SQL)
    status: str | None = None     # idem
    count: int = 1                # > 1 après agrégation d'une rafale


def _mk(kind: str, ref: Any, source: str, href: str | None = None) -> dict[str, Any]:
    """Un pointeur de preuve : d'où vient CE fait, et où aller le vérifier.

    INVARIANT : ``source`` nomme la COLONNE qui contient ``ref``. On doit pouvoir
    écrire ``SELECT * FROM <table> WHERE <colonne> = <ref>`` et retomber sur la
    ligne qui a produit l'événement. Un ``source`` qui désigne une autre colonne
    que ``ref`` rendrait la preuve injouable — donc mensongère.
    """
    ev: dict[str, Any] = {"kind": kind, "ref": None if ref is None else str(ref),
                          "source": source}
    if href:
        ev["href"] = href
    return ev


def _subject(kind: str, ident: Any, label: Any) -> dict[str, Any]:
    return {"kind": kind, "id": None if ident is None else str(ident),
            "label": None if label is None else str(label)}


# ============================================================================
# Filigrane temporel tolérant aux ex æquo
# ============================================================================


@dataclass
class _TsCursor:
    """Filigrane ``(horodatage, identifiants déjà émis à cet horodatage)``.

    Nécessaire parce que ``created_at`` vaut l'horodatage de TRANSACTION :
    tout un lot d'atomes partage la même microseconde. Un ``>`` strict perdrait
    les ex æquo (donc des atomes jamais annoncés) ; un ``>=`` nu les rejouerait
    à chaque passage (donc un flux qui radote). On lit en ``>=``, et on écarte ce
    qu'on a déjà émis à l'horodatage de bord.
    """

    ts: datetime | None = None
    seen: set = field(default_factory=set)
    ts_field: str = "ts"
    id_field: str = "id"

    def bootstrap(self, ts: datetime | None) -> None:
        self.ts = ts
        self.seen = set()

    def fresh(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Les lignes réellement nouvelles, ex æquo de bord exclus."""
        out = []
        for r in rows:
            rts = r.get(self.ts_field)
            if rts is None:
                continue
            if self.ts is None:
                out.append(r)
            elif rts > self.ts:
                out.append(r)
            elif rts == self.ts and r.get(self.id_field) not in self.seen:
                out.append(r)
            # rts < self.ts : déjà passé, on ne rejoue pas.
        return out

    def advance(self, rows: list[dict[str, Any]]) -> None:
        """Déplace le filigrane sur le dernier horodatage vu."""
        stamped = [r for r in rows if r.get(self.ts_field) is not None]
        if not stamped:
            return
        top = max(r[self.ts_field] for r in stamped)
        at_top = {r[self.id_field] for r in stamped if r[self.ts_field] == top}
        if self.ts is None or top > self.ts:
            self.ts, self.seen = top, at_top
        elif top == self.ts:
            self.seen |= at_top


# ============================================================================
# LE SUIVEUR — une tâche, une connexion, tous les clients
# ============================================================================


@dataclass
class _Subscriber:
    """Un client SSE branché sur le flux."""

    queue: asyncio.Queue
    stages: frozenset[str] | None
    min_level: int
    connected_at: datetime = field(default_factory=_now_dt)
    delivered: int = 0
    dropped: int = 0

    def wants(self, ev: dict[str, Any]) -> bool:
        if self.stages is not None and ev["stage"] not in self.stages:
            return False
        return _LEVEL_RANK.get(ev["level"], 0) >= self.min_level


class Tailer:
    """Suit la base par filigranes et pousse les nouveautés aux abonnés.

    UN SEUL suiveur pour tous les clients : une connexion PostgreSQL, pas une
    par onglet ouvert. Démarré paresseusement à la première connexion SSE,
    arrêté quand plus personne n'écoute (après ``STOP_GRACE_SECONDS``).

    Amorçage : au premier passage, les filigranes sont PHOTOGRAPHIÉS sans rien
    émettre. Ouvrir le cockpit ne déverse pas 125 000 événements d'histoire ;
    on n'annonce que ce qui arrive APRÈS.
    """

    def __init__(self) -> None:
        self._ring: deque[dict[str, Any]] = deque(maxlen=RING_CAPACITY)
        self._seq = 0
        self._subs: dict[int, _Subscriber] = {}
        self._sub_seq = 0
        self._task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        # Sérialise l'accès à la connexion PostgreSQL. ``asyncio.to_thread`` ne
        # peut pas INTERROMPRE un thread : quand une boucle d'événements meurt
        # pendant un passage (arrêt applicatif, rechargement, client de test), le
        # thread en cours SURVIT à l'annulation de la coroutine. Sans ce verrou,
        # le passage suivant — lancé depuis une nouvelle boucle — entrerait dans
        # libpq en même temps que le précédent, sur la même connexion : le
        # processus meurt en segmentation fault, pas en exception.
        self._poll_lock = threading.Lock()

        self._conn: Any = None
        self._bootstrapped = False
        self._failures = 0
        self._degraded = False
        self._last_error: str | None = None

        self._wm: dict[str, Any] = {}
        self._atoms_created = _TsCursor(ts_field="ts")
        self._atoms_superseded = _TsCursor(ts_field="ts")
        # Le filigrane des fins de passage porte sur ``ended_at``, PAS sur le ``ts``
        # de la ligne (qui vaut coalesce(ended_at, started_at)) : un passage encore
        # ouvert ne doit jamais faire avancer le filigrane des fins.
        self._runs_ended = _TsCursor(ts_field="ended_at")
        self._curation = _TsCursor(ts_field="ts")
        self._run_id = 0
        self._recall_id = 0
        self._ingest_id = 0
        self._capture_id = 0
        self._dropped_id = 0
        self._audit_id = 0
        self._open_runs: dict[int, str] = {}
        self._node_state: dict[str, str] = {}

        self._passes = 0
        self._events_emitted = 0
        self._started_at: datetime | None = None
        self._last_pass_at: datetime | None = None
        self._last_event_at: datetime | None = None
        self._last_poll_request: float = 0.0

    # -- état ---------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def bootstrapped(self) -> bool:
        return self._bootstrapped

    def watermarks(self) -> dict[str, Any]:
        """Les filigranes courants, tels que le suiveur les tient."""
        if not self._bootstrapped:
            return {"state": "unavailable",
                    "reason": "le suiveur n'a pas encore photographié la base"}
        return {
            "state": "ok",
            "memory_atoms": {"created_at": _iso(self._atoms_created.ts),
                             "superseded_at": _iso(self._atoms_superseded.ts),
                             "ties_held": len(self._atoms_created.seen)},
            "run_receipts": {"id": self._run_id, "ended_at": _iso(self._runs_ended.ts),
                             "open": sorted(self._open_runs)},
            "context_receipts": {"id": self._recall_id},
            "ingest_receipts": {"id": self._ingest_id},
            "capture_manifests": {"id": self._capture_id},
            "conversations": {"curated_at": _iso(self._curation.ts)},
            "digestion_review_queue": {"id": self._dropped_id},
            "audit_log": {"id_failed": self._audit_id},
            "nodes": {"watched": len(self._node_state),
                      "silent": sorted(n for n, s in self._node_state.items()
                                       if s in ("warn", "critical"))},
        }

    def stats(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "bootstrapped": self._bootstrapped,
            "started_at": _iso(self._started_at),
            "passes": self._passes,
            "events_emitted": self._events_emitted,
            "ring_size": len(self._ring),
            "ring_capacity": RING_CAPACITY,
            "last_pass_at": _iso(self._last_pass_at),
            "last_event_at": _iso(self._last_event_at),
            "clients_connected": len(self._subs),
            "degraded": self._degraded,
            "consecutive_failures": self._failures,
            "last_error": self._last_error,
            "clients": [
                {"connected_at": _iso(s.connected_at), "delivered": s.delivered,
                 "dropped": s.dropped,
                 "stages": sorted(s.stages) if s.stages else None,
                 "min_level": LEVELS[s.min_level]}
                for s in self._subs.values()
            ],
        }

    # -- cycle de vie -------------------------------------------------------

    async def ensure_started(self) -> None:
        """Démarre la tâche de fond si besoin. Idempotent, sûr en concurrence."""
        loop = asyncio.get_running_loop()
        if self._task is not None and not self._task.done() and self._loop is loop:
            return
        # Une boucle d'événements différente (ou morte) invalide la tâche : le
        # cockpit peut être monté plusieurs fois dans un même processus (tests,
        # rechargement). On congédie l'ancienne AVANT d'en créer une neuve, sans
        # quoi deux boucles de suivi coexisteraient sur la même connexion.
        old = self._task
        if old is not None and not old.done():
            try:
                old.cancel()
            except Exception:  # noqa: BLE001 — l'ancienne boucle peut déjà être close
                pass
        self._task = loop.create_task(self._run(), name="cc_v1_stream_tailer")
        self._loop = loop
        self._started_at = _now_dt()

    def note_poll(self) -> None:
        """Un appel au repli JSON compte comme une écoute (garde le suiveur en vie)."""
        self._last_poll_request = time.monotonic()

    def _has_listeners(self) -> bool:
        if self._subs:
            return True
        return (time.monotonic() - self._last_poll_request) < POLL_KEEPALIVE_SECONDS

    async def _run(self) -> None:
        """La boucle de suivi. Ne meurt ni sur une panne de base, ni sur une requête."""
        idle_since: float | None = None
        try:
            while True:
                try:
                    raw = await asyncio.to_thread(self._poll_blocking)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 — résilience volontaire
                    raw = self._on_failure(exc)
                self.emit(raw)

                if self._has_listeners():
                    idle_since = None
                else:
                    idle_since = idle_since or time.monotonic()
                    if (time.monotonic() - idle_since) > STOP_GRACE_SECONDS:
                        logger.info("cc_v1.stream.tailer_stopped_no_listener")
                        return

                await asyncio.sleep(self._interval_s())
        except asyncio.CancelledError:
            raise
        finally:
            self._close_conn()

    def _interval_s(self) -> float:
        if not self._failures:
            return TAIL_INTERVAL_MS / 1000.0
        return BACKOFF_STEPS_S[min(self._failures - 1, len(BACKOFF_STEPS_S) - 1)]

    async def stop(self) -> None:
        """Arrête la tâche de fond et libère la connexion."""
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._close_conn()

    def _close_conn(self) -> None:
        """Ferme la connexion de suivi — JAMAIS sous un passage EN VOL.

        CE QUI ÉTAIT FAUX : ``_run`` lance le passage par
        ``await asyncio.to_thread(self._poll_blocking)``. Une annulation (arrêt
        du service, fin de la boucle, ``stop()``) fait ressortir l'``await``
        IMMÉDIATEMENT, mais le fil de travail, lui, continue sa requête. Le
        ``finally`` fermait alors la connexion psycopg pendant que ce fil était
        dans ``cur.execute()`` : libpq libère une structure qu'un autre fil
        utilise, et le PROCESSUS tombe en segmentation fault — reproduit deux
        fois sur six exécutions de ``scripts/ops/cc_v1_stream_smoke.py``, pile
        dans ``_tail_atoms_created`` (``Fatal Python error: Segmentation
        fault``). Ce n'est pas une requête perdue : c'est le serveur qui meurt.

        CE QUE CETTE VERSION GARANTIT : la fermeture prend le MÊME verrou que le
        passage (``_poll_lock``, tenu pendant toute la requête). Elle attend donc
        la fin du passage en vol, au plus ``CLOSE_WAIT_SECONDS``. Au-delà, elle
        RENONCE et garde la référence : une connexion en lecture seule laissée
        ouverte se ferme à la sortie du processus (et ``_connect`` la réutilise
        si le suiveur repart), tandis qu'une fermeture forcée tue tout le monde.
        """
        pris = self._poll_lock.acquire(timeout=CLOSE_WAIT_SECONDS)
        try:
            if not pris:
                # On ne met PAS `_conn` à None : perdre la dernière référence
                # ferait fermer la connexion par le ramasse-miettes, au même
                # endroit et avec le même effet.
                logger.warning("cc_v1.stream.close_deferred_poll_in_flight")
                return
            conn, self._conn = self._conn, None
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001 — fermer ne doit jamais masquer l'erreur utile
                    pass
        finally:
            if pris:
                self._poll_lock.release()

    # -- panne / reprise ----------------------------------------------------

    def _on_failure(self, exc: Exception) -> list[_Raw]:
        """Une panne de source se DIT une fois, puis se tait jusqu'à la reprise."""
        self._close_conn()
        self._failures += 1
        self._last_error = f"{type(exc).__name__}: {exc}"
        logger.warning("cc_v1.stream.source_unavailable",
                       extra={"error": type(exc).__name__, "failures": self._failures})
        if self._degraded:
            return []  # déjà annoncé : on ne matraque pas le client
        self._degraded = True
        return [_Raw(type="systeme.source_unavailable", ts=_now_dt(),
                     args={"error": type(exc).__name__},
                     measures={"attempts": self._failures},
                     evidence=_mk("tailer", None, "control_center.cc_v1.stream"))]

    # -- LE PASSAGE (bloquant, exécuté dans un thread) ----------------------

    def _connect(self) -> Any:
        if self._conn is None or getattr(self._conn, "closed", False):
            self._conn = service._connect_readonly()
        return self._conn

    def _rows(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Exécute une lecture et rend des lignes brutes (valeurs Python natives).

        Les horodatages restent des ``datetime`` : ils servent de filigranes, et
        les convertir trop tôt casserait les comparaisons.
        """
        conn = self._connect()
        with conn.cursor() as cur:
            cur.execute(sql, params or {})
            cols = [d.name for d in (cur.description or [])]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def _poll_blocking(self) -> list[_Raw]:
        """UN passage de suivi. Synchrone : appelé via ``asyncio.to_thread``.

        Au premier appel, photographie les filigranes et n'émet qu'un événement
        de service (``systeme.tailing_started``) — jamais d'historique.

        Sérialisé par ``_poll_lock`` : deux passages ne touchent JAMAIS la
        connexion en même temps, quelle que soit la boucle qui les a lancés.
        """
        with self._poll_lock:
            return self._poll_locked()

    def _poll_locked(self) -> list[_Raw]:
        if not self._bootstrapped:
            return self._bootstrap_blocking()

        raw: list[_Raw] = []
        raw += self._tail_atoms_created()
        raw += self._tail_atoms_superseded()
        raw += self._tail_runs()
        raw += self._tail_recall()
        raw += self._tail_ingest()
        raw += self._tail_capture()
        raw += self._tail_curation()
        raw += self._tail_dropped()
        raw += self._tail_audit()
        raw += self._tail_nodes()

        self._passes += 1
        self._last_pass_at = _now_dt()

        if self._degraded:
            attempts, self._failures = self._failures, 0
            self._degraded = False
            self._last_error = None
            raw.append(_Raw(type="systeme.source_recovered", ts=_now_dt(),
                            args={"attempts": attempts},
                            measures={"attempts": attempts},
                            evidence=_mk("tailer", None, "control_center.cc_v1.stream")))
        self._failures = 0
        return raw

    def _bootstrap_blocking(self) -> list[_Raw]:
        """AMORÇAGE — on note où on en est, on n'émet pas le passé."""
        wm = self._rows(_SQL_WATERMARKS)[0]
        self._wm = wm
        self._atoms_created.bootstrap(wm["atom_created_ts"])
        self._atoms_superseded.bootstrap(wm["atom_superseded_ts"])
        self._runs_ended.bootstrap(wm["run_ended_ts"])
        self._curation.bootstrap(wm["curation_ts"])
        self._run_id = int(wm["run_id"] or 0)
        self._recall_id = int(wm["recall_id"] or 0)
        self._ingest_id = int(wm["ingest_id"] or 0)
        self._capture_id = int(wm["capture_id"] or 0)
        self._dropped_id = int(wm["dropped_id"] or 0)
        self._audit_id = int(wm["audit_id"] or 0)

        self._open_runs = {int(r["id"]): r["status"]
                           for r in self._rows(_SQL_OPEN_RUNS, {"cap": ROW_CAP})}
        self._node_state = {r["node_id"]: r["silence_state"]
                            for r in self._rows(_SQL_NODES, {"cap": ROW_CAP})}

        # Les ex æquo de bord sont déjà émis (ils sont l'HISTOIRE, pas la nouveauté) :
        # on les marque comme vus pour ne pas les rejouer au premier passage utile.
        self._atoms_created.seen = {
            r["id"] for r in self._rows(_SQL_ATOM_CREATED,
                                        {"wm": self._atoms_created.ts, "cap": ROW_CAP})}
        self._atoms_superseded.seen = {
            r["id"] for r in self._rows(_SQL_ATOM_SUPERSEDED,
                                        {"wm": self._atoms_superseded.ts, "cap": ROW_CAP})}
        self._curation.seen = {
            r["id"] for r in self._rows(_SQL_CURATION,
                                        {"wm": self._curation.ts, "cap": ROW_CAP})}
        self._runs_ended.seen = {
            r["id"] for r in self._rows(_SQL_RUNS,
                                        {"wm_id": self._run_id, "wm_ts": self._runs_ended.ts,
                                         "open_ids": [], "cap": ROW_CAP})
            if r.get("ended_at") == self._runs_ended.ts}

        self._bootstrapped = True
        self._passes += 1
        self._last_pass_at = _now_dt()
        self._failures = 0
        self._degraded = False
        logger.info("cc_v1.stream.bootstrapped", extra={"run_id": self._run_id})

        return [_Raw(type="systeme.tailing_started", ts=_now_dt(),
                     args={"sources": len(_SOURCE_TABLES)},
                     measures={"sources": len(_SOURCE_TABLES)},
                     evidence=_mk("tailer", None,
                                  "control_center.cc_v1.stream — tables suivies : "
                                  + ", ".join(_SOURCE_TABLES)))]

    # -- les dix sources ----------------------------------------------------

    def _tail_atoms_created(self) -> list[_Raw]:
        rows = self._rows(_SQL_ATOM_CREATED, {"wm": self._atoms_created.ts, "cap": ROW_CAP})
        fresh = self._atoms_created.fresh(rows)
        self._atoms_created.advance(rows)
        return [
            _Raw(type="atom.created", ts=r["ts"],
                 subject=_subject("atome", r["id"], r["key"]),
                 args={"kind": r["kind"], "scope": r["scope"]},
                 measures={"confidence_score": _j(r["confidence_score"])},
                 evidence=_mk("atome", r["id"], "arac.memory_atoms.id",
                              f"{_PREFIX}/atoms/{r['id']}"))
            for r in fresh
        ]

    def _tail_atoms_superseded(self) -> list[_Raw]:
        rows = self._rows(_SQL_ATOM_SUPERSEDED,
                          {"wm": self._atoms_superseded.ts, "cap": ROW_CAP})
        fresh = self._atoms_superseded.fresh(rows)
        self._atoms_superseded.advance(rows)
        return [
            _Raw(type="atom.superseded", ts=r["ts"],
                 subject=_subject("atome", r["id"], r["key"]),
                 args={"kind": r["kind"], "scope": r["scope"]},
                 measures={"superseded_by": _j(r["superseded_by"])},
                 evidence=_mk("atome", r["id"], "arac.memory_atoms.id",
                              f"{_PREFIX}/atoms/{r['id']}"))
            for r in fresh
        ]

    def _tail_runs(self) -> list[_Raw]:
        """Cycles : naissance (nouvel ``id``) et fin (``ended_at`` ou changement de statut)."""
        rows = self._rows(_SQL_RUNS, {"wm_id": self._run_id, "wm_ts": self._runs_ended.ts,
                                      "open_ids": sorted(self._open_runs), "cap": ROW_CAP})
        out: list[_Raw] = []
        seen_ended = self._runs_ended.fresh(rows)
        ended_ids = {r["id"] for r in seen_ended if r.get("ended_at") is not None}

        for r in rows:
            rid = int(r["id"])
            is_new = rid > self._run_id
            was_open = rid in self._open_runs
            in_progress = r["lifecycle"] == "in_progress"

            # Naissance : une ligne neuve ENCORE en cours. Une ligne neuve déjà
            # terminée (cas du passage sauté, inséré tel quel) n'a jamais « démarré »
            # du point de vue de l'observateur : on n'invente pas un début qu'on
            # n'a pas vu.
            if is_new and in_progress:
                out.append(_Raw(
                    type="cycle.started", ts=r["started_at"] or r["ts"],
                    subject=_subject("run", rid, r["slot_key"]),
                    args={"slot": r["slot_key"], "trigger": r["trigger"]},
                    measures={"items": _j(r["items"]), "spawns": _j(r["spawns"])},
                    evidence=_mk("run", rid, "arac.run_receipts.id")))

            # Fin : soit un `ended_at` neuf, soit un statut qui a changé sous nos
            # yeux, soit une ligne neuve déjà terminée à sa découverte.
            terminal_now = not in_progress
            status_moved = was_open and self._open_runs.get(rid) != r["status"]
            if terminal_now and (rid in ended_ids or status_moved or is_new):
                out.append(self._run_terminal(r, rid))

        self._runs_ended.advance(rows)
        if rows:
            self._run_id = max(self._run_id, max(int(r["id"]) for r in rows))

        # Tous les passages précédemment ouverts sont relus à chaque passage
        # (``id = ANY(open_ids)``) : l'ensemble ouvert se reconstruit donc sans
        # perte — on retire ceux qui viennent de se fermer, on ajoute les neufs.
        closed = {int(r["id"]) for r in rows if r["lifecycle"] != "in_progress"}
        self._open_runs = {k: v for k, v in self._open_runs.items() if k not in closed}
        self._open_runs.update({int(r["id"]): r["status"]
                                for r in rows if r["lifecycle"] == "in_progress"})
        return out

    def _run_terminal(self, r: dict[str, Any], rid: int) -> _Raw:
        """Traduit le statut d'un passage terminé en événement du catalogue."""
        etype = _RUN_STATUS_EVENT.get(r["status"], "cycle.finished")
        measures = {
            "items": _j(r["items"]), "spawns": _j(r["spawns"]),
            "atoms_created": _j(r["atoms_created"]),
            "atoms_superseded": _j(r["atoms_superseded"]),
            "atoms_confirmed": _j(r["atoms_confirmed"]),
            "atoms_quarantined": _j(r["atoms_quarantined"]),
            "conflicts_409": _j(r["conflicts_409"]),
            "messages_reported": _j(r["messages_reported"]),
            "duration_ms": _j(r["duration_ms"]), "duration_s": _j(r["duration_s"]),
            "raw_status": r["status"],
        }
        args = {
            "slot": r["slot_key"], "trigger": r["trigger"],
            "atoms_created": _j(r["atoms_created"]),
            "duration_s": _j(r["duration_s"]),
            "stop_reason": r["stop_reason"] or r["outcome"],
            "skip_reason": r["skip_reason"],
        }
        return _Raw(type=etype, ts=r["ts"],
                    subject=_subject("run", rid, r["slot_key"]),
                    args=args, measures=measures,
                    evidence=_mk("run", rid, "arac.run_receipts.id"))

    def _tail_recall(self) -> list[_Raw]:
        rows = self._rows(_SQL_RECALL, {"wm_id": self._recall_id, "cap": ROW_CAP})
        if rows:
            self._recall_id = max(int(r["id"]) for r in rows)
        return [
            _Raw(type="recall.served", ts=r["ts"], level=r["level"],
                 subject=_subject("requete", r["request_id"], r["consumer"]),
                 args={"band": r["final_band"], "served_count": _j(r["served_count"]),
                       "stop_reason": r["stop_reason"]},
                 measures={"served_count": _j(r["served_count"]),
                           "k_requested": _j(r["k_requested"]),
                           "budget_k": _j(r["budget_k"]),
                           "top1_distance": _j(r["top1_distance"]),
                           "top1_distance_raw": _j(r["top1_distance_raw"]),
                           "latency_ms": _j(r["latency_ms"]),
                           "raw_band": r["raw_band"],
                           "scope_prefix_gain": _j(r["scope_prefix_gain"])},
                 evidence=_mk("requete", r["id"], "arac.context_receipts.id"))
            for r in rows
        ]

    def _tail_ingest(self) -> list[_Raw]:
        rows = self._rows(_SQL_INGEST, {"wm_id": self._ingest_id, "cap": ROW_CAP})
        if rows:
            self._ingest_id = max(int(r["id"]) for r in rows)
        out: list[_Raw] = []
        for r in rows:
            accepted = r["outcome"] == "accepted"
            out.append(_Raw(
                type="ingest.accepted" if accepted else "ingest.denied", ts=r["ts"],
                subject=_subject("conversation", r["conversation_uid"], r["source_type"]),
                args={"inserted": _j(r["inserted"]), "received": _j(r["received"]),
                      "outcome": r["outcome"], "node": r["node_id"]},
                measures={"received": _j(r["received"]), "inserted": _j(r["inserted"]),
                          "duplicates": _j(r["duplicates"]),
                          "hash_divergences": _j(r["hash_divergences"]),
                          "empty_messages": _j(r["empty_messages"]),
                          "masked_messages": _j(r["masked_messages"]),
                          "scrub_hits": _j(r["scrub_hits_count"]),
                          "http_status": _j(r["http_status"])},
                evidence=_mk("conversation", r["id"], "arac.ingest_receipts.id",
                             f"{_PREFIX}/conversations/{r['conversation_uid']}"
                             if r["conversation_uid"] else None)))
        return out

    def _tail_capture(self) -> list[_Raw]:
        rows = self._rows(_SQL_CAPTURE, {"wm_id": self._capture_id, "cap": ROW_CAP})
        if rows:
            self._capture_id = max(int(r["id"]) for r in rows)
        return [
            _Raw(type="capture.detected", ts=r["ts"], level=r["level"], status=r["status"],
                 subject=_subject("noeud", r["node_id"], r["source_type"]),
                 args={"node": r["node_id"], "messages_emitted": _j(r["messages_emitted"])},
                 measures={"files_scanned": _j(r["files_scanned"]),
                           "sessions": _j(r["sessions"]),
                           "messages_read": _j(r["messages_read"]),
                           "messages_emitted": _j(r["messages_emitted"]),
                           "batches_ok": _j(r["batches_ok"]),
                           "batches_failed": _j(r["batches_failed"]),
                           "ack_mismatches": _j(r["ack_mismatches"]),
                           "archive_bytes": _j(r["archive_bytes"]),
                           "archive_size": r["archive_size"],
                           "duration_ms": _j(r["duration_ms"])},
                 evidence=_mk("noeud", r["id"], "arac.capture_manifests.id"))
            for r in rows
        ]

    def _tail_curation(self) -> list[_Raw]:
        rows = self._rows(_SQL_CURATION, {"wm": self._curation.ts, "cap": ROW_CAP})
        fresh = self._curation.fresh(rows)
        self._curation.advance(rows)
        return [
            _Raw(type="curation.finished", ts=r["ts"], level=r["level"], status=r["status"],
                 subject=_subject("conversation", r["conversation_uid"], r["title"]),
                 args={"atoms_generated": _j(r["atoms_generated"]),
                       "source": r["source_type"]},
                 measures={"atoms_generated": _j(r["atoms_generated"]),
                           "retry_count": _j(r["retry_count"]),
                           "curated_through_message_id": _j(r["curated_through_message_id"]),
                           "error": r["last_curation_error"]},
                 evidence=_mk("conversation", r["conversation_uid"],
                              "arac.conversations.conversation_uid",
                              f"{_PREFIX}/conversations/{r['conversation_uid']}"))
            for r in fresh
        ]

    def _tail_dropped(self) -> list[_Raw]:
        rows = self._rows(_SQL_DROPPED, {"wm_id": self._dropped_id, "cap": ROW_CAP})
        if rows:
            self._dropped_id = max(int(r["id"]) for r in rows)
        return [
            _Raw(type="atom.dropped", ts=r["ts"],
                 subject=_subject("conversation", r["conversation_uid"], r["kind"]),
                 args={"drop_reason": r["drop_reason"], "scope": r["scope"],
                       "kind": r["kind"]},
                 measures={"queue_status": r["queue_status"], "run_ref": r["run_ref"]},
                 evidence=_mk("atome", r["id"], "arac.digestion_review_queue.id"))
            for r in rows
        ]

    def _tail_audit(self) -> list[_Raw]:
        rows = self._rows(_SQL_AUDIT_FAILED, {"wm_id": self._audit_id, "cap": ROW_CAP})
        if rows:
            self._audit_id = max(int(r["id"]) for r in rows)
        return [
            _Raw(type="audit.failed", ts=r["ts"],
                 subject=_subject("noeud", r["node_id"], r["tool_name"]),
                 args={"action": r["action"], "node": r["node_id"]},
                 measures={"latency_ms": _j(r["latency_ms"]),
                           "tokens_used": _j(r["tokens_used"]),
                           "warning_code": r["warning_code"],
                           "error": r["error_message"]},
                 evidence=_mk("noeud", r["id"], "arac.audit_log.id"))
            for r in rows
        ]

    def _tail_nodes(self) -> list[_Raw]:
        """Silence des nœuds — émis sur TRANSITION, jamais en continu.

        Sans cette règle, dix-neuf nœuds muets depuis des semaines produiraient
        dix-neuf événements par seconde : un flux qui hurle en permanence
        n'informe plus de rien.
        """
        rows = self._rows(_SQL_NODES, {"cap": ROW_CAP})
        out: list[_Raw] = []
        for r in rows:
            node, now_state = r["node_id"], r["silence_state"]
            was = self._node_state.get(node)
            self._node_state[node] = now_state
            if was is None or was == now_state:
                continue
            silent = now_state in ("warn", "critical")
            if silent:
                out.append(_Raw(
                    type="node.silent", ts=_now_dt(),
                    level="anomalie" if now_state == "critical" else "notable",
                    subject=_subject("noeud", node, r["role"]),
                    args={"node": node, "silent_minutes": _j(r["silent_minutes"]),
                          "severity": now_state},
                    measures={"silent_minutes": _j(r["silent_minutes"]),
                              "silent_warn_minutes": _j(r["silent_warn_minutes"]),
                              "silent_critical_minutes": _j(r["silent_critical_minutes"]),
                              "last_heartbeat": _iso(r["last_heartbeat"])},
                    evidence=_mk("noeud", node, "arac.nodes.node_id")))
            elif now_state == "ok" and was in ("warn", "critical"):
                out.append(_Raw(
                    type="node.recovered", ts=_now_dt(),
                    subject=_subject("noeud", node, r["role"]),
                    args={"node": node},
                    measures={"silent_minutes": _j(r["silent_minutes"]),
                              "last_heartbeat": _iso(r["last_heartbeat"])},
                    evidence=_mk("noeud", node, "arac.nodes.node_id")))
        return out

    # -- ÉMISSION : rafales, numérotation, anneau, diffusion ----------------

    def emit(self, raw: Iterable[_Raw]) -> list[dict[str, Any]]:
        """Agrège les rafales, numérote, archive et diffuse. Retourne les enveloppes."""
        raw = list(raw)
        if not raw:
            return []
        with self._lock:
            events = [self._envelope(r) for r in _collapse_bursts(raw)]
            for ev in events:
                self._ring.append(ev)
            self._events_emitted += len(events)
            if events:
                self._last_event_at = _now_dt()
        self._fanout(events)
        return events

    def one(self, r: _Raw) -> dict[str, Any]:
        """Numérote un événement pour UN client, sans l'archiver ni le diffuser.

        Sert aux faits propres à une connexion (rattrapage tronqué) : les
        annoncer à tout le monde serait faux, les taire serait pire.
        """
        with self._lock:
            return self._envelope(r)

    def _envelope(self, r: _Raw) -> dict[str, Any]:
        """Le contrat d'enveloppe. Aucune phrase, jamais."""
        spec = _BY_TYPE.get(r.type)
        if spec is None:  # verrou : un type hors catalogue ne sort pas d'ici
            raise KeyError(f"type d'événement hors catalogue : {r.type!r}")
        self._seq += 1
        aggregated = r.count > 1
        key = f"{r.type}.burst" if aggregated else r.type
        subject = None if aggregated else r.subject
        return {
            "event_id": f"{_BOOT_MS:013d}-{self._seq:09d}",
            "ts": _iso(r.ts),
            "observed_at": _iso(_now_dt()),
            "stage": spec["stage"],
            "type": r.type,
            "level": r.level or spec["level"],
            "status": r.status or spec["status"],
            "subject": subject,
            "measures": r.measures,
            "message_key": key,
            "message_args": r.args,
            "evidence": r.evidence,
            "aggregated": aggregated,
        }

    def _fanout(self, events: list[dict[str, Any]]) -> None:
        """Pousse vers les abonnés. Un abonné lent est marqué, jamais attendu."""
        for sub in list(self._subs.values()):
            for ev in events:
                if not sub.wants(ev):
                    continue
                try:
                    sub.queue.put_nowait(ev)
                except asyncio.QueueFull:
                    # Un client lent n'est jamais attendu : on compte ce qu'il
                    # rate (visible dans /stream/state) et il se rattrape par
                    # ``since=``. Bloquer ici gèlerait le suiveur pour tous.
                    sub.dropped += 1
                except Exception:  # noqa: BLE001 — suiveur piloté hors serveur (script)
                    sub.dropped += 1
                    break

    # -- abonnement ---------------------------------------------------------

    def subscribe(self, stages: frozenset[str] | None, min_level: int) -> tuple[int, _Subscriber]:
        self._sub_seq += 1
        sub = _Subscriber(queue=asyncio.Queue(maxsize=512), stages=stages, min_level=min_level)
        self._subs[self._sub_seq] = sub
        return self._sub_seq, sub

    def unsubscribe(self, sid: int) -> None:
        self._subs.pop(sid, None)

    # -- rattrapage ---------------------------------------------------------

    def replay(self, since: str | None, stages: frozenset[str] | None,
               min_level: int, limit: int = REPLAY_MAX_EVENTS) -> tuple[list[dict], bool]:
        """Les événements postérieurs à ``since``, fenêtre bornée.

        Bornes : ``REPLAY_MAX_EVENTS`` et ``REPLAY_MAX_AGE_HOURS``. Un
        rattrapage n'est pas une archive — l'histoire se lit dans les preuves des
        métriques, pas dans le flux.

        Retourne ``(événements, tronqué)`` : ``tronqué`` dit qu'un trou existe
        entre ``since`` et le plus ancien événement encore en mémoire. On ne le
        déduit pas d'une intuition : il est vrai dès que l'anneau a débordé, ou
        dès que ``since`` porte le préfixe d'un AUTRE démarrage du processus —
        auquel cas tout ce qui s'est passé entre les deux est perdu, et le
        client doit le savoir plutôt que de croire son historique complet.
        """
        floor_ts = _now_dt() - timedelta(hours=REPLAY_MAX_AGE_HOURS)
        with self._lock:
            snapshot = list(self._ring)
            overflowed = self._events_emitted > RING_CAPACITY
        out: list[dict[str, Any]] = []
        for ev in snapshot:
            if since and ev["event_id"] <= since:
                continue
            obs = ev.get("observed_at")
            if obs and datetime.fromisoformat(obs) < floor_ts:
                continue
            if stages is not None and ev["stage"] not in stages:
                continue
            if _LEVEL_RANK.get(ev["level"], 0) < min_level:
                continue
            out.append(ev)

        truncated = False
        if since:
            other_boot = not since.startswith(f"{_BOOT_MS:013d}-")
            lost_to_ring = overflowed and (not snapshot or since < snapshot[0]["event_id"])
            truncated = bool(other_boot or lost_to_ring)
        if len(out) > limit:
            out = out[-limit:]
            truncated = True
        return out, truncated

    def oldest_event_id(self) -> str | None:
        with self._lock:
            return self._ring[0]["event_id"] if self._ring else None

    def ring_size(self) -> int:
        with self._lock:
            return len(self._ring)

    # -- lectures ponctuelles (hors boucle) ---------------------------------

    def snapshot_blocking(self) -> dict[str, Any]:
        """Repos, dernier passage, horaire observé et prochain cycle — tout en SQL.

        Ouvre sa PROPRE connexion, courte : la connexion du suiveur appartient à
        la boucle de suivi, et une route HTTP ne doit pas s'interposer dedans.
        Cette route dit donc la vérité même quand le suiveur ne tourne pas.
        """
        conn = service._connect_readonly()
        try:
            def rows(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    cols = [d.name for d in (cur.description or [])]
                    return [dict(zip(cols, r)) for r in cur.fetchall()]

            tz = config.cycle_tz()
            idle = rows(_SQL_IDLE)[0]
            slots = rows(_SQL_SCHEDULE)
            # Le fuseau voyage en paramètre lié : c'est une DONNÉE de configuration,
            # jamais un fragment de SQL — la garde `_assert_read_only` ne le voit
            # donc jamais, et aucune valeur d'environnement ne peut construire du SQL.
            nxt = rows(_SQL_NEXT_CYCLE, {"tz": tz})
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001 — fermer ne masque jamais l'erreur utile
                pass
        return {"idle": idle, "slots": slots, "next": nxt[0] if nxt else None,
                "tz": tz}


_RUN_STATUS_EVENT: dict[str, str] = {
    "done": "cycle.finished",
    "quarantined": "cycle.quarantined",
    "spawn_failed": "cycle.spawn_failed",
    "skipped": "cycle.skipped",
}
"""Statut de passage → type d'événement. Un statut inconnu retombe sur
``cycle.finished`` en conservant le statut brut dans ``measures.raw_status`` :
le cockpit ne cache pas un statut qu'il ne sait pas nommer."""

_SOURCE_TABLES: tuple[str, ...] = (
    "arac.memory_atoms", "arac.run_receipts", "arac.context_receipts",
    "arac.ingest_receipts", "arac.capture_manifests", "arac.conversations",
    "arac.digestion_review_queue", "arac.audit_log", "arac.nodes",
)


# ============================================================================
# Groupement des rafales
# ============================================================================


def _collapse_bursts(raw: list[_Raw]) -> list[_Raw]:
    """Plus de ``BURST_THRESHOLD`` événements d'un même type en moins de
    ``BURST_WINDOW_S`` → un seul événement agrégé portant ``measures.count``.

    Le comptage porte sur des événements que ce module vient de produire, pas sur
    des lignes du cerveau : c'est la seule arithmétique tolérée ici, et elle est
    explicitement demandée par le contrat.

    L'agrégat perd son ``subject`` (il n'en a plus un seul) mais conserve la
    plage temporelle et la liste des valeurs distinctes des arguments — assez
    pour que le client dise « 40 atomes créés · gotcha, decision » sans rien
    inventer.
    """
    by_type: dict[str, list[_Raw]] = {}
    for r in raw:
        by_type.setdefault(r.type, []).append(r)

    out: list[_Raw] = []
    for etype, group in by_type.items():
        group.sort(key=lambda r: r.ts)
        i = 0
        while i < len(group):
            # Fenêtre glissante : on étend tant qu'on reste à moins de
            # BURST_WINDOW_S du PREMIER événement de la fenêtre.
            j = i
            while (j + 1 < len(group)
                   and (group[j + 1].ts - group[i].ts).total_seconds() <= BURST_WINDOW_S):
                j += 1
            window = group[i:j + 1]
            if len(window) > BURST_THRESHOLD:
                out.append(_aggregate(etype, window))
            else:
                out.extend(window)
            i = j + 1

    out.sort(key=lambda r: r.ts)
    return out


def _aggregate(etype: str, window: list[_Raw]) -> _Raw:
    """Un événement pour toute une rafale."""
    n = len(window)
    distinct: dict[str, list[Any]] = {}
    for r in window:
        for k, v in r.args.items():
            if v is None:
                continue
            vals = distinct.setdefault(k, [])
            if v not in vals and len(vals) < 8:
                vals.append(v)
    return _Raw(
        type=etype,
        ts=window[-1].ts,
        subject=None,
        args={"count": n, **{k: ", ".join(str(x) for x in v) for k, v in distinct.items()}},
        measures={"count": n,
                  "first_ts": _iso(window[0].ts), "last_ts": _iso(window[-1].ts),
                  "distinct": {k: v for k, v in distinct.items()}},
        evidence=_mk("rafale", etype,
                     "agrégat produit par le suiveur — détail dans measures.distinct"),
        level=window[0].level,
        status=window[0].status,
        count=n,
    )


# ============================================================================
# Le suiveur partagé
# ============================================================================

_TAILER: Tailer | None = None
_TAILER_LOCK = threading.Lock()


def get_tailer() -> Tailer:
    """Le suiveur unique du processus : une tâche, une connexion, tous les clients."""
    global _TAILER
    with _TAILER_LOCK:
        if _TAILER is None:
            _TAILER = Tailer()
        return _TAILER


# ============================================================================
# Analyse des paramètres de requête
# ============================================================================


def _parse_stages(raw: str | None) -> frozenset[str] | None:
    """``?stages=analyse,atomes`` → ensemble validé. Vide ou inconnu = pas de filtre."""
    if not raw or not raw.strip():
        return None
    wanted = {s.strip() for s in raw.split(",") if s.strip()}
    keep = wanted & set(STAGES)
    return frozenset(keep) if keep else None


def _parse_level(raw: str | None) -> int:
    """``?level=notable`` → seuil MINIMAL de gravité (info < notable < anomalie)."""
    return _LEVEL_RANK.get((raw or "").strip().lower(), 0)


# ============================================================================
# Charges utiles des routes
# ============================================================================


def stream_catalog() -> dict[str, Any]:
    """Ce que le client a le droit d'afficher — et rien d'autre."""
    return {
        "events": [dict(e) for e in EVENT_CATALOG],
        "message_catalog": dict(MESSAGE_CATALOG),
        "vocabulary": {
            "stages": list(STAGES),
            "levels": list(LEVELS),
            "level_order": ["info", "notable", "anomalie"],
            "statuses": list(STATUSES),
            "subject_kinds": list(SUBJECT_KINDS),
        },
        "envelope": {
            "event_id": "identifiant monotone, ordonnable lexicographiquement "
                        "(<ms d'amorçage du processus>-<séquence>)",
            "ts": "ISO-8601 UTC — l'instant du FAIT, lu dans la base",
            "observed_at": "ISO-8601 UTC — l'instant où le suiveur l'a vu",
            "stage": "|".join(STAGES),
            "type": "un type du catalogue ci-dessus",
            "level": "|".join(LEVELS),
            "status": "|".join(STATUSES),
            "subject": "{kind, id, label} ou null (toujours null sur un agrégat)",
            "measures": "compteurs et durées typés, produits par le SQL",
            "message_key": "CLÉ de MESSAGE_CATALOG — jamais une phrase",
            "message_args": "arguments typés à injecter dans le gabarit",
            "evidence": "{kind, ref, source, href?} ou null",
            "aggregated": "true quand l'événement résume une rafale (measures.count)",
        },
        "rules": {
            "no_server_side_prose":
                "le serveur n'envoie jamais de phrase : message_key + message_args. "
                "Une phrase qui ne dérive pas d'une donnée n'a aucun chemin vers l'écran.",
            "burst":
                f"plus de {BURST_THRESHOLD} événements du même type en moins de "
                f"{BURST_WINDOW_S} s → un agrégat unique portant measures.count",
            "bootstrap":
                "à l'amorçage, les filigranes sont photographiés sans émettre "
                "l'historique : seuls les faits POSTÉRIEURS sont annoncés",
            "idle":
                "au repos, le flux n'émet rien. Pas de faux battement, pas de "
                "remplissage. Le repos est une information, pas un vide à combler.",
            "replay":
                f"rattrapage borné à {REPLAY_MAX_EVENTS} événements ou "
                f"{REPLAY_MAX_AGE_HOURS} h (anneau de {RING_CAPACITY})",
            "arithmetic":
                "toutes les durées, ratios, minutes de silence et niveaux dérivés "
                "sont calculés en SQL ; ni Python ni JavaScript ne calculent",
        },
        "transport": dict(TRANSPORT),
        "sources": list(_SOURCE_TABLES),
        "gaps": catalog_gaps(),
    }


def stream_state() -> dict[str, Any]:
    """Repos, prochain cycle, filigranes, transport, clients connectés.

    Répond que le suiveur tourne ou non : les filigranes et l'état de repos sont
    relus dans la base à la demande, pour que cette route dise la vérité même
    quand personne n'est connecté.
    """
    t = get_tailer()
    stats = t.stats()
    payload: dict[str, Any] = {
        "transport": dict(TRANSPORT),
        "tailer": stats,
        "watermarks": t.watermarks(),
        "clients_connected": stats["clients_connected"],
        "computed_at": _iso(_now_dt()),
    }

    try:
        snap = t.snapshot_blocking()
    except Exception as exc:  # noqa: BLE001 — une absence se dit, elle ne se déguise pas
        logger.warning("cc_v1.stream.state_unavailable", extra={"error": type(exc).__name__})
        payload |= {
            "idle": None,
            "state": "unavailable",
            "reason": f"source indisponible ({type(exc).__name__})",
            "next_cycle_at": None,
            "last_event_at": _iso(t._last_event_at),
        }
        return payload

    idle, slots, nxt = snap["idle"], snap["slots"], snap["next"]
    # Le fuseau SERVI est celui qui a réellement produit `next_cycle` : il vient
    # de l'instantané, pas d'une seconde lecture qui pourrait différer.
    tz = snap.get("tz") or config.cycle_tz()
    payload |= {
        "state": "ok",
        "idle": idle["idle"],
        "idle_rule": (
            "aucun passage en cours (ended_at IS NULL AND skip_reason IS NULL) "
            f"démarré dans les dernières {IN_PROGRESS_WINDOW} — count(*) = 0 en SQL"
        ),
        "runs_in_progress": _j(idle["runs_in_progress"]),
        "server_now": _iso(idle["server_now"]),
        "last_event_at": _iso(t._last_event_at),
        "last_activity": {
            "run_started_at": _iso(idle["last_run_started_at"]),
            "run_ended_at": _iso(idle["last_run_ended_at"]),
            "capture_at": _iso(idle["last_capture_at"]),
            "ingest_at": _iso(idle["last_ingest_at"]),
            "atom_at": _iso(idle["last_atom_at"]),
        },
        "next_cycle_at": _iso(nxt["at_utc"]) if nxt else None,
        "next_cycle": {
            "slot": nxt["slot"] if nxt else None,
            "local_time": nxt["local_time"] if nxt else None,
            "at_utc": _iso(nxt["at_utc"]) if nxt else None,
            "in_seconds": _j(nxt["in_seconds"]) if nxt else None,
            "state": "ok" if nxt else "unavailable",
            "reason": None if nxt else "aucun créneau circadien dans les reçus de passage",
        },
        "schedule": {
            "timezone": tz,
            "source": "arac.run_receipts.slot_key (motif circadian_HHMM@AAAA-MM-JJ)",
            "note": ("l'horaire n'est pas configuré dans le cockpit : il est OBSERVÉ "
                     "dans les reçus. Le cockpit affirme ce que les receipts prouvent."),
            "slots": [{"slot": s["slot"], "local_time": s["local_time"],
                       "runs": _j(s["runs"]), "last_run_at": _iso(s["last_run_at"])}
                      for s in slots],
        },
    }
    return payload


# ============================================================================
# Le générateur SSE
# ============================================================================


def _sse(ev: dict[str, Any]) -> str:
    """Une trame SSE : identifiant reprenable, nom d'événement unique, charge JSON."""
    body = json.dumps(ev, ensure_ascii=False, separators=(",", ":"))
    return f"id: {ev['event_id']}\nevent: arac.event\ndata: {body}\n\n"


def _sse_comment(text: str) -> str:
    """Un commentaire SSE : tient la connexion, ne porte AUCUNE donnée du cerveau."""
    return f": {text}\n\n"


async def _event_stream(request: Request, since: str | None,
                        stages: frozenset[str] | None, min_level: int):
    """Le flux d'un client : rattrapage borné, puis poussée, puis battement.

    Se termine proprement à la déconnexion : l'abonné est retiré dans le
    ``finally``, et le suiveur s'arrête tout seul quand plus personne n'écoute.
    """
    t = get_tailer()
    sid, sub = t.subscribe(stages, min_level)
    try:
        await t.ensure_started()

        yield _sse_comment(f"arac cc/v1 stream · transport={TRANSPORT['mode']} "
                           f"· interval_ms={TRANSPORT['interval_ms']}")
        yield f"retry: {TAIL_INTERVAL_MS * 3}\n\n"

        backlog, truncated = t.replay(since, stages, min_level)
        if truncated:
            # Un trou de rattrapage est un FAIT : il se dit, il ne se cache pas.
            # Il ne concerne QUE ce client : il n'entre ni dans l'anneau ni dans
            # le flux des autres.
            yield _sse(t.one(_Raw(
                type="systeme.replay_truncated", ts=_now_dt(),
                args={"since": since},
                measures={"ring_size": t.ring_size(),
                          "oldest_available": t.oldest_event_id()},
                evidence=_mk("anneau", since, "control_center.cc_v1.stream"))))
        for ev in backlog:
            sub.delivered += 1
            yield _sse(ev)

        while True:
            if await request.is_disconnected():
                return
            try:
                ev = await asyncio.wait_for(sub.queue.get(), timeout=HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                # Le cerveau est peut-être au repos. On ne fabrique pas d'activité :
                # un commentaire SSE tient la connexion sans porter de donnée.
                yield _sse_comment(f"hb {_iso(_now_dt())}")
                continue
            sub.delivered += 1
            yield _sse(ev)
    except asyncio.CancelledError:  # déconnexion côté serveur
        raise
    except GeneratorExit:            # déconnexion côté client
        raise
    finally:
        t.unsubscribe(sid)


# ============================================================================
# Enregistrement des routes
# ============================================================================


def register(
    a: FastAPI,
    session_api: Callable[..., Any],
    audit_read_log: Callable[[str, str], Any],
) -> None:
    """Enregistre les routes du flux temps réel sur l'application fournie.

    Doctrine identique au socle : ``@a.get`` uniquement, garde de session sur
    chaque route, journal de lecture sur chaque accès.

    Args:
        a: l'instance FastAPI du Control Center.
        session_api: la dépendance de session en mode API (401 JSON si absente).
        audit_read_log: le journal de lecture du socle (chemin, principal).
    """

    @a.get(f"{_PREFIX}/stream")
    async def cc_v1_stream(  # noqa: D401
        request: Request,
        principal: dict = Depends(session_api),
        since: str | None = Query(default=None, max_length=64),
        stages: str | None = Query(default=None, max_length=200),
        level: str | None = Query(default=None, max_length=16),
    ) -> StreamingResponse:
        """LE FLUX : le serveur pousse, le client n'interroge jamais.

        Le suiveur démarre à la première connexion et s'arrête quand la dernière
        se ferme — un seul suiveur, une seule connexion base, quel que soit le
        nombre d'onglets ouverts.

        Reprise : ``?since=<event_id>`` ou l'en-tête standard ``Last-Event-ID``.
        Filtres : ``?stages=analyse,atomes`` et ``?level=notable`` (seuil minimal).
        """
        audit_read_log(f"{_PREFIX}/stream", principal.get("sub", "?"))
        resume = since or request.headers.get("last-event-id")
        gen = _event_stream(request, resume, _parse_stages(stages), _parse_level(level))
        return StreamingResponse(
            gen,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-store, no-transform",
                "Connection": "keep-alive",
                # Neutralise la mise en tampon d'un proxy : sans cela, le flux
                # arriverait par paquets et cesserait d'être un temps réel.
                "X-Accel-Buffering": "no",
            },
        )

    @a.get(f"{_PREFIX}/events")
    async def cc_v1_events(
        principal: dict = Depends(session_api),
        since: str | None = Query(default=None, max_length=64),
        limit: int = Query(default=200, ge=1, le=REPLAY_MAX_EVENTS),
        stages: str | None = Query(default=None, max_length=200),
        level: str | None = Query(default=None, max_length=16),
    ) -> JSONResponse:
        """REPLI JSON — même enveloppe, pour un client sans SSE.

        Appeler cette route maintient le suiveur en vie : le repli est un vrai
        repli, pas la lecture d'un flux mort.
        """
        audit_read_log(f"{_PREFIX}/events", principal.get("sub", "?"))
        t = get_tailer()
        t.note_poll()
        await t.ensure_started()
        items, truncated = t.replay(since, _parse_stages(stages), _parse_level(level),
                                    limit=limit)
        return JSONResponse({
            "items": items,
            "count": len(items),
            "since": since,
            "next_since": items[-1]["event_id"] if items else since,
            "truncated": truncated,
            "oldest_available": t.oldest_event_id(),
            "transport": dict(TRANSPORT),
            "tailer": {"running": t.running, "bootstrapped": t.bootstrapped},
            "note": ("un flux vide devant un cerveau au repos est le comportement "
                     "correct : ce module n'invente jamais d'activité"),
            "computed_at": _iso(_now_dt()),
        })

    @a.get(f"{_PREFIX}/stream/catalog")
    def cc_v1_stream_catalog(principal: dict = Depends(session_api)) -> JSONResponse:
        """Le catalogue FERMÉ des événements et les gabarits de messages.

        Le client ne compose une phrase qu'à partir d'ici. Aucune base n'est
        interrogée : cette route répond même si PostgreSQL est éteint.
        """
        audit_read_log(f"{_PREFIX}/stream/catalog", principal.get("sub", "?"))
        return JSONResponse(stream_catalog())

    @a.get(f"{_PREFIX}/stream/state")
    def cc_v1_stream_state(principal: dict = Depends(session_api)) -> JSONResponse:
        """L'état du flux : repos, prochain cycle, filigranes, clients connectés.

        Le repos est une information : ``idle: true`` avec la date du prochain
        cycle vaut mieux qu'un flux qu'on ferait semblant d'animer.
        """
        audit_read_log(f"{_PREFIX}/stream/state", principal.get("sub", "?"))
        return JSONResponse(stream_state())
