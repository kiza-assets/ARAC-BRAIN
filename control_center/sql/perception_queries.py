"""Cockpit PERCEPTION — le SQL partagé entre les collecteurs et les pages.

Doctrine : OBSERVE FIRST. DO NOT CONTROL. + READ ONLY. + IMPORT-NOT-REWRITE.

Deux familles de constantes, TOUTES consommées à la fois par les collecteurs
(exécution) et par les routes (affichage `render_sql_block`) — le SQL montré
à l'écran EST l'objet exécuté, jamais une copie :

1. CONSTANTES AUTORITAIRES IMPORTÉES du code métier (identité d'objet,
   vérifiée par test — toute copie manuelle serait une fabrication) :
     - `SOURCE_REGISTRY_SQL`       ← app/perception/source_registry.py
       (l'autorité de retard est capture_manifests.run_ended_at ; la dégrader
        à max(raw_messages.received_at) confondrait « capteur en retard » et
        « message reçu tard », et fabriquerait un faux-positif permanent)
     - `ACTIONABLE_BACKLOG_SQL`    ← app/perception/ingest_watchdog.py
       (miroir fidèle du gate curateur v2 — retry/backoff/exclusion/3 seuils)
     - `ACTIONABLE_BACKLOG_DETAIL_SQL` ← app/perception/conservation_audit.py
       (projection par conversation, received_at + grâce healing)
     - `gate_params`               ← ingest_watchdog._gate_params (la FONCTION,
       pas une copie des seuils — quiet_hours/min_new_msgs/age_cap_hours)
     - `FULL_OMISSION_MARKER`      ← agents/lib/curator_lib_v2.py
     - `CHARS_PER_TOKEN`           ← agents/cortex/value_gate.py
     - `BudgetConfig`, `DEFAULT_KILL_SWITCH` ← agents/lib/spend_guard.py

2. Requêtes PROPRES au cockpit (agrégats d'affichage), définies UNE seule
   fois ici.
   `EXPLAINED_STATES_SQL` COMPOSE la constante importée
   `ACTIONABLE_BACKLOG_DETAIL_SQL` par concaténation (le prédicat
   d'éligibilité affiché/exécuté est l'objet importé lui-même).

Lecture seule stricte : uniquement des SELECT. Aucun identifiant n'est
construit depuis une entrée externe (placeholders psycopg partout).
"""

from __future__ import annotations

import os
import re as _re
import sys

# --- Imports AUTORITAIRES (identité d'objet, jamais de copie) --------------
#
# Le cockpit n'a pas le droit de RECOPIER une règle : il importe l'objet qui
# la porte. Une règle recopiée diverge, et deux écrans du même cockpit
# affichent alors deux vérités sur le même fait.
from app.perception import conservation_audit as _ca
from app.perception import ingest_watchdog as _iw
from app.perception import source_registry as _sr
from agents.lib import spend_guard as _sg
from agents.cortex import value_gate as _vg  # noqa: E402
from agents.lib import curator_lib_v2 as _cl  # noqa: E402

# Origine : app/perception/source_registry.py::_SOURCE_REGISTRY_SQL —
# l'autorité de fraîcheur est capture_manifests.run_ended_at.
SOURCE_REGISTRY_SQL = _sr._SOURCE_REGISTRY_SQL

# Origine : app/perception/source_registry.py::derive_source_status — LA
# fonction PURE de dérivation d'état (OK/MUTE/PENDING_BOOTSTRAP/DECLARED_*).
# Le cockpit ne compte JAMAIS la seule déclaration coverage_policy :
# le statut affiché est cette dérivation autoritaire, ligne à ligne.
derive_source_status = _sr.derive_source_status
STATUS_OK = _sr.STATUS_OK
STATUS_MUTE = _sr.STATUS_MUTE
STATUS_PENDING_BOOTSTRAP = _sr.STATUS_PENDING_BOOTSTRAP

# Origine : app/perception/ingest_watchdog.py::_ACTIONABLE_BACKLOG_SQL —
# agrégat du gate curateur v2 : un compte, et DEUX âges étiquetés (âge du
# contenu, âge de l'attente) — un seul des deux mentirait.
ACTIONABLE_BACKLOG_SQL = _iw._ACTIONABLE_BACKLOG_SQL

# Origine : app/perception/conservation_audit.py::_ACTIONABLE_BACKLOG_DETAIL_SQL
# — même prédicat, projection PAR CONVERSATION (received_at + grâce healing).
ACTIONABLE_BACKLOG_DETAIL_SQL = _ca._ACTIONABLE_BACKLOG_DETAIL_SQL

# Origine : app/perception/ingest_watchdog.py::_gate_params — LA fonction
# (mêmes env vars/défauts que le gate réel du curateur v2).
gate_params = _iw._gate_params

# Origine : agents/lib/curator_lib_v2.py::_FULL_OMISSION_MARKER — marqueur
# parseable du streak d'omissions LLM dans conversations.last_curation_error.
FULL_OMISSION_MARKER = _cl._FULL_OMISSION_MARKER

# Origine : agents/cortex/value_gate.py::_CHARS_PER_TOKEN — l'estimateur
# chars→tokens du value-gate (jamais un ratio ré-inventé ici).
CHARS_PER_TOKEN = _vg._CHARS_PER_TOKEN

# Origine : agents/lib/spend_guard.py — plafonds réels (env-driven) +
# chemin canonique du kill-switch fichier.
BudgetConfig = _sg.BudgetConfig
DEFAULT_KILL_SWITCH = _sg.DEFAULT_KILL_SWITCH

# Grâce healing par défaut du bulletin (heures) pour le paramètre
# grace_hours d'ACTIONABLE_BACKLOG_DETAIL_SQL (cf conservation_audit).
STARVATION_GRACE_HOURS_DEFAULT = 24.0


def backlog_detail_params(grace_hours: float = STARVATION_GRACE_HOURS_DEFAULT) -> dict:
    """Paramètres complets d'`ACTIONABLE_BACKLOG_DETAIL_SQL` : les 3 seuils du
    gate viennent de `gate_params()` IMPORTÉ (jamais recopiés)."""
    return {**gate_params(), "grace_hours": grace_hours}


# ===========================================================================
# Requêtes propres au cockpit ; chaque constante porte le panneau qu'elle sert.
# ===========================================================================

# Q1 PERÇU — volume 24h.
INGEST_VOLUME_24H_SQL = (
    "SELECT COALESCE(SUM(inserted), 0) AS inserted_24h, COUNT(*) AS posts_24h "
    "FROM arac.ingest_receipts "
    "WHERE created_at > now() - interval '24 hours' "
    "  AND outcome IN ('accepted', 'duplicate_noop')"
)

# Q2 EN DIGESTION — runs ouverts (synthèse Q2.sql_runs_ouverts) [prod].
RUNS_OPEN_SQL = (
    "SELECT slot_key, status, progress, started_at FROM arac.run_receipts "
    "WHERE status IN ('started','spawning','disposing','dispose_interrupted') "
    "ORDER BY started_at DESC"
)

# Q2 — revue humaine pending par motif (synthèse Q2.sql_revue) [0028].
REVIEW_PENDING_SQL = (
    "SELECT drop_reason, count(*) FROM arac.digestion_review_queue "
    "WHERE status = 'pending' GROUP BY 1 ORDER BY 2 DESC"
)

# Q3 REJETÉ — étage 2 : refus ingest 7j par outcome (synthèse Q3) [0021].
REJECTED_INGEST_7D_SQL = (
    "SELECT outcome, count(*) FROM arac.ingest_receipts "
    "WHERE created_at > now() - interval '7 days' GROUP BY 1 ORDER BY 2 DESC"
)

# Q3 — étage 1 : amont scanner, motifs filtrés du DERNIER manifeste par
# source (messages_filtered jsonb motif→count) [0026].
CAPTURE_FILTERED_SQL = (
    "SELECT DISTINCT ON (node_id, source_type) node_id, source_type, "
    "  run_started_at, messages_filtered "
    "FROM arac.capture_manifests "
    "ORDER BY node_id, source_type, run_started_at DESC"
)

# Q3 — étage 3 : conversations exclues par catégorie (motif par CHECK
# d'honnêteté, trigger non-contournable) [0023/0029].
EXCLUSIONS_BY_CATEGORY_SQL = (
    "SELECT exclusion_category, count(*) FROM arac.conversations "
    "WHERE acked GROUP BY 1 ORDER BY 2 DESC"
)

# Q3 — étage 4 : écartés en digestion par drop_reason [0028].
REVIEW_DROPS_SQL = (
    "SELECT drop_reason, count(*) FROM arac.digestion_review_queue "
    "GROUP BY 1 ORDER BY 2 DESC"
)

# Q3 — audit : actions conversation_* journalisées [prod].
AUDIT_CONVERSATION_ACTIONS_SQL = (
    "SELECT action, count(*) FROM arac.audit_log "
    "WHERE action LIKE 'conversation_%' GROUP BY 1 ORDER BY 2 DESC"
)

# Q4 APPRIS — atomes actifs par jour × kind (synthèse Q4.sql_atomes,
# borné 14 jours pour l'affichage — le drill donne les lignes).
ATOMS_BY_DAY_KIND_SQL = (
    "SELECT date_trunc('day', created_at)::date AS d, kind, count(*) "
    "FROM arac.memory_atoms WHERE status = 'active' "
    "  AND created_at > now() - interval '14 days' "
    "GROUP BY 1, 2 ORDER BY 1 DESC, 3 DESC"
)

# Q4 — ratio anti-fossilisation : created:superseded:confirmed côte à côte
# (une tuile ne comptant que 'created' masquerait la fossilisation — REFUSÉ).
ATOMS_LIFECYCLE_RATIO_SQL = (
    "SELECT (SELECT count(*) FROM arac.memory_atoms) AS atomes_total, "
    "  (SELECT count(*) FROM arac.memory_atoms WHERE status = 'active') AS actifs, "
    "  (SELECT count(*) FROM arac.memory_atoms WHERE status = 'superseded') AS supersedes, "
    "  COALESCE((SELECT sum(atoms_created) FROM arac.run_receipts), 0) AS run_created, "
    "  COALESCE((SELECT sum(atoms_superseded) FROM arac.run_receipts), 0) AS run_superseded, "
    "  COALESCE((SELECT sum(atoms_confirmed) FROM arac.run_receipts), 0) AS run_confirmed"
)

# Q4 — 5 derniers runs, colonnes apprentissage (synthèse Q4.sql_run).
RUNS_LEARNING_SQL = (
    "SELECT slot_key, atoms_created, atoms_superseded, atoms_confirmed, "
    "  coverage_covered, coverage_presented "
    "FROM arac.run_receipts ORDER BY started_at DESC LIMIT 5"
)

# Q5 POURQUOI — drill-down d'UN atome (synthèse Q5.sql_atome).
ATOM_DETAIL_SQL = (
    "SELECT id::text, kind, scope, key, rationale, source_ref::text, "
    "  confidence_score, status, created_at "
    "FROM arac.memory_atoms WHERE id = %(id)s"
)

# Q5 — l'incumbent et ses perdants (synthèse Q5.sql_perdants) [0028].
ATOM_LOSERS_SQL = (
    "SELECT drop_reason, proposed_atom::text, run_ref, created_at "
    "FROM arac.digestion_review_queue WHERE incumbent_atom_id = %(id)s"
)

# Q6 CONFIANCE — bandes 7j (synthèse Q6.sql_bandes) [0030]. GARDE GRAVÉE :
# raw_band ET final_band sont classées sur la distance FINALE post-modifiers ;
# on LIT les bandes telles quelles, on ne re-classe JAMAIS top1_distance_raw.
BANDS_7D_SQL = (
    "SELECT final_band, count(*), round(avg(top1_distance_final)::numeric, 4) "
    "FROM arac.context_receipts "
    "WHERE created_at > now() - interval '7 days' GROUP BY 1 ORDER BY 2 DESC"
)

# Q6 — abstentions receipt-grade (stop_reason='no_confident_context').
ABSTAIN_7D_SQL = (
    "SELECT count(*) FROM arac.context_receipts "
    "WHERE created_at > now() - interval '7 days' "
    "  AND stop_reason = 'no_confident_context'"
)

# Q6 — distribution confidence_score par kind (synthèse Q6.sql_confiance_atomes).
CONFIDENCE_BUCKETS_SQL = (
    "SELECT kind, width_bucket(confidence_score, 0, 100, 10) AS bucket, count(*) "
    "FROM arac.memory_atoms WHERE status = 'active' "
    "GROUP BY 1, 2 ORDER BY 1, 2"
)

# Q7 COÛT — ledger 14j (synthèse Q7.sql_ledger) [run_receipts = write-ahead].
LEDGER_14D_SQL = (
    "SELECT utc_day, sum(est_input_tokens) AS est_input_tokens, "
    "  sum(spawns) AS spawns, sum(items) AS items, "
    "  count(*) FILTER (WHERE status = 'skipped') AS skipped "
    "FROM arac.run_receipts GROUP BY 1 ORDER BY 1 DESC LIMIT 14"
)

# Q7 — frein DB (synthèse Q7.sql_frein_db) — 1 des 3 freins fail-closed.
BRAKE_DB_SQL = "SELECT value FROM arac.arac_config WHERE key = 'paid_ai_enabled'"

# Q8 PREUVES — chaîne bout-en-bout d'UNE conversation (synthèse Q8.sql_chaine).
CHAIN_SQL = (
    "SELECT c.conversation_uid, c.source_type, c.node_id, c.acked, "
    "  c.exclusion_category, c.retry_count, c.curated_through_message_id, "
    "  (SELECT count(*) FROM arac.raw_messages m "
    "     WHERE m.conversation_id = c.id) AS msgs, "
    "  (SELECT count(*) FROM arac.ingest_receipts ir "
    "     WHERE ir.conversation_uid = c.conversation_uid) AS posts, "
    "  (SELECT count(*) FROM arac.digestion_review_queue q "
    "     WHERE q.conversation_uid = c.conversation_uid) AS dropped "
    "FROM arac.conversations c WHERE c.conversation_uid = %(uid)s"
)

# ===========================================================================
# Panneaux STABILISATION (audit V5)
# ===========================================================================

# S1 — ÉTATS DE CONVERSATION EXPLICABLES. Le prédicat d'éligibilité
# (WITH actionable) est la constante IMPORTÉE `ACTIONABLE_BACKLOG_DETAIL_SQL`
# concaténée telle quelle (composition, pas ré-écriture) ; les seuils
# affichés dans les raisons gate[...] sont les paramètres de `gate_params()`.
# Raisons mécaniques nommées (jamais un silence) :
#   exclue-tracée[cat]     : reçu d'exclusion motivée (0023/0029)
#   acquittée[msgs post-ack]: acked sans exclusion mais messages non curés
#   dead-letter[retry>=5]  : retry épuisé (cap curator_lib), hors gate
#   drainage-par-tranche   : éligible ET curseur déjà avancé (tranches)
#   jamais-atteinte        : éligible ET jamais présentée (curseur à 0)
#   omise-LLM[streak=N]    : marqueur full_omission_streak — le modèle a
#                            rendu zéro atome N fois d'affilée sur cette
#                            conversation
#   backoff[next_retry_at] : re-présentation différée (next_retry_at futur)
#   jamais-éligible[vides] : aucun nouveau message non vide (anti-spawn-à-vide)
#   gate[min_new_msgs]     : moins de %(min_new_msgs)s nouveaux messages
#   gate[quiet-hours]      : conversation encore active (< quiet_hours)
#   inclassée              : divergence classification↔gate — fail-loud.
EXPLAINED_STATES_SQL = (
    "WITH actionable AS ( "
    + ACTIONABLE_BACKLOG_DETAIL_SQL
    + " ), pend AS ( "
    "  SELECT c.id, c.conversation_uid, c.source_type, c.acked, c.retry_count, "
    "    c.exclusion_category, c.next_retry_at, c.curated_through_message_id, "
    "    c.curated_at, c.last_curation_error, "
    "    count(*) FILTER (WHERE m.id > c.curated_through_message_id) AS new_msgs, "
    "    count(*) FILTER (WHERE m.id > c.curated_through_message_id "
    "                     AND btrim(m.content) <> '') AS new_nonempty, "
    "    round(EXTRACT(EPOCH FROM (now() - max(COALESCE(m.msg_created_at, "
    "      m.received_at)))) / 3600.0, 1) AS last_activity_age_h "
    "  FROM arac.conversations c "
    "  JOIN arac.raw_messages m ON m.conversation_id = c.id "
    "  GROUP BY c.id "
    "  HAVING count(*) FILTER (WHERE m.id > c.curated_through_message_id) >= 1 "
    ") "
    "SELECT p.conversation_uid, p.source_type, p.new_msgs, p.new_nonempty, "
    "  p.retry_count, p.last_activity_age_h, "
    "  CASE "
    "    WHEN p.exclusion_category IS NOT NULL "
    "      THEN 'exclue-tracée[' || p.exclusion_category || ']' "
    "    WHEN p.acked THEN 'acquittée[messages post-ack]' "
    "    WHEN p.retry_count >= 5 "
    "      THEN 'dead-letter[retry=' || p.retry_count::text || ']' "
    "    WHEN a.conversation_uid IS NOT NULL "
    "         AND (p.curated_at IS NOT NULL OR p.curated_through_message_id > 0) "
    "      THEN 'drainage-par-tranche[curseur=' "
    "           || p.curated_through_message_id::text || ']' "
    "    WHEN a.conversation_uid IS NOT NULL THEN 'jamais-atteinte' "
    "    WHEN p.last_curation_error LIKE %(omission_like)s "
    "      THEN 'omise-LLM[streak=' || COALESCE(substring(p.last_curation_error "
    "           from %(omission_regex)s), '?') || ']' "
    "    WHEN p.next_retry_at IS NOT NULL AND p.next_retry_at > now() "
    "      THEN 'backoff[next_retry_at=' "
    "           || to_char(p.next_retry_at AT TIME ZONE 'UTC', "
    "                      'YYYY-MM-DD HH24:MI') || 'Z]' "
    "    WHEN p.new_nonempty = 0 THEN 'jamais-éligible[nouveaux msgs vides]' "
    "    WHEN p.new_msgs < %(min_new_msgs)s "
    "      THEN 'gate[min_new_msgs ' || p.new_msgs::text || '<' "
    "           || (%(min_new_msgs)s)::text || ']' "
    "    WHEN p.last_activity_age_h < %(quiet_hours)s "
    "      THEN 'gate[quiet-hours ' || p.last_activity_age_h::text || 'h<' "
    "           || (%(quiet_hours)s)::text || 'h]' "
    "    ELSE 'inclassée[divergence — investiguer]' "
    "  END AS raison "
    "FROM pend p "
    "LEFT JOIN actionable a ON a.conversation_uid = p.conversation_uid "
    "ORDER BY p.acked, p.new_nonempty DESC, p.conversation_uid "
    "LIMIT 200"
)


# Tables requises par EXPLAINED_STATES_SQL — DÉRIVÉES de la constante composée
# elle-même (la CTE importée référence notamment raw_message_revisions, 0022) :
# jamais une liste maintenue à la main qui pourrait diverger du bulletin.
EXPLAINED_STATES_TABLES = tuple(sorted(set(
    _re.findall(r"\barac\.([a-z_]+)", EXPLAINED_STATES_SQL))))


def explained_states_params(
    grace_hours: float = STARVATION_GRACE_HOURS_DEFAULT,
) -> dict:
    """Paramètres d'`EXPLAINED_STATES_SQL` : seuils du gate via `gate_params()`
    importé + marqueur d'omission via `FULL_OMISSION_MARKER` importé."""
    return {
        **backlog_detail_params(grace_hours),
        "omission_like": FULL_OMISSION_MARKER + "%",
        "omission_regex": FULL_OMISSION_MARKER + r"(\d+)",
    }


# S2 — INFLOW vs CAPACITÉ. kt/j entrés par source (7j) — l'estimateur
# chars→tokens est CHARS_PER_TOKEN importé du value-gate, passé en paramètre.
INFLOW_7D_BY_SOURCE_SQL = (
    "SELECT c.node_id, c.source_type, "
    "  count(*) AS msgs_7j, "
    "  round((sum(length(m.content)) / %(chars_per_token)s / 1000.0)::numeric, 1) "
    "    AS ktok_7j, "
    "  round((sum(length(m.content)) / %(chars_per_token)s / 1000.0 / 7.0)::numeric, 1) "
    "    AS ktok_par_jour "
    "FROM arac.raw_messages m "
    "JOIN arac.conversations c ON c.id = m.conversation_id "
    "WHERE m.received_at >= now() - interval '7 days' "
    "GROUP BY 1, 2 ORDER BY 4 DESC"
)

# S2 — consommation mesurée 7j (reçus write-ahead, jamais une estimation UI).
CONSUMED_7D_SQL = (
    "SELECT utc_day, sum(est_input_tokens) AS est_input_tokens, "
    "  sum(spawns) AS spawns, sum(items) AS items "
    "FROM arac.run_receipts "
    "WHERE started_at >= now() - interval '7 days' "
    "GROUP BY 1 ORDER BY 1 DESC"
)

# ===========================================================================
# Drill-to-receipt — requêtes de LIGNES BRUTES (ids/sha, pas de PII opérateur
# dans les libellés ; le contenu affiché à l'écran reste du contenu, assumé
# sur tunnel trusted read-only — cf synthèse navigation_preuve).
# ===========================================================================

DRILL_INGEST_SOURCES_SQL = SOURCE_REGISTRY_SQL  # même objet importé

DRILL_INGEST_RECEIPTS_SQL = (
    "SELECT id::text, created_at, node_id, source_type, conversation_uid, "
    "  outcome, http_status, received, inserted, duplicates, refusal_detail "
    "FROM arac.ingest_receipts "
    "WHERE created_at > now() - interval '1 hour' * %(window_hours)s "
    "ORDER BY created_at DESC LIMIT 200"
)

DRILL_CAPTURE_MANIFESTS_SQL = (
    "SELECT id::text, node_id, source_type, run_started_at, run_ended_at, "
    "  files_scanned, sessions, messages_read, messages_emitted, "
    "  messages_filtered, batches_ok, batches_failed, ack_mismatches "
    "FROM arac.capture_manifests ORDER BY run_started_at DESC LIMIT 100"
)

DRILL_CONVERSATIONS_EXCLUDED_SQL = (
    "SELECT conversation_uid, source_type, exclusion_category, "
    "  exclusion_reason, excluded_at, excluded_by "
    "FROM arac.conversations WHERE exclusion_category IS NOT NULL "
    "ORDER BY excluded_at DESC NULLS LAST LIMIT 200"
)

DRILL_RUN_RECEIPTS_SQL = (
    "SELECT id::text, slot_key, trigger, status, skip_reason, stop_reason, "
    "  spawns, items, est_input_tokens, atoms_created, atoms_superseded, "
    "  atoms_confirmed, coverage_presented, coverage_covered, "
    "  coverage_omitted, utc_day, started_at, ended_at "
    "FROM arac.run_receipts ORDER BY started_at DESC LIMIT 100"
)

DRILL_REVIEW_QUEUE_SQL = (
    "SELECT id::text, run_ref, conversation_uid, drop_reason, scope, kind, "
    "  status, incumbent_atom_id::text, created_at "
    "FROM arac.digestion_review_queue ORDER BY created_at DESC LIMIT 200"
)

DRILL_MEMORY_ATOMS_SQL = (
    "SELECT id::text, kind, scope, key, status, confidence_score, "
    "  rationale IS NOT NULL AS a_rationale, created_at "
    "FROM arac.memory_atoms ORDER BY created_at DESC LIMIT 200"
)

DRILL_CONTEXT_RECEIPTS_SQL = (
    "SELECT id::text, created_at, consumer, engine_version, "
    "  calibration_version, query_sha256, raw_band, final_band, "
    "  top1_distance_raw, top1_distance_final, stop_reason, "
    "  shadow_latency_ms, shadow_error "
    "FROM arac.context_receipts ORDER BY created_at DESC LIMIT 200"
)

DRILL_AUDIT_LOG_SQL = (
    "SELECT id::text, created_at, node_id, action, success, warning_code "
    "FROM arac.audit_log WHERE action LIKE 'conversation_%' "
    "ORDER BY created_at DESC LIMIT 200"
)
