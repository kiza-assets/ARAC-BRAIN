"""Ingest Watchdog v4 — diagnostic PAR SOURCE, autorité = `capture_manifests.run_ended_at`.

Refonte v4 (santé v2 bout-en-bout, 2026-07-06) — trois défauts mesurés de v3
corrigés :

  1. **Angle mort du "pending" naïf → fausses alertes CRITICAL.** v3 calculait
     l'âge du plus vieux message non curé SANS reproduire le prédicat réel du
     gate curateur (`agents/lib/curator_lib_v2.select_eligible_conversations`)
     — une conversation dont les seuls messages non curés sont VIDES (jamais
     éligible, anti-spawn-à-vide) vieillissait indéfiniment et déclenchait
     "AUCUNE curation depuis Nh" alors que la curation tournait normalement
     (rejoué 2026-07-04→06 : 11 alertes CRITICAL réelles, cf tests, toutes
     dues à des conversations `desktop_chat` 100% vides accumulées depuis le
     03/07 — le curseur RÉEL avançait, `curated_gap_h` restait borné). v4
     reproduit fidèlement ce prédicat (`_ACTIONABLE_BACKLOG_SQL` + `_gate_params`,
     mêmes env vars que le gate réel) et ne parle de famine QUE si du travail
     ACTIONNABLE attend ET qu'aucune curation n'a progressé depuis la cadence
     circadienne (3 créneaux/jour, cf `agents/cortex/cycle.py:resolve_slot`).
  2. **Point unique de défaillance : le heartbeat Mac.** v3 basait ses
     CRITICAL sur le signal `ingest_health.json` poussé par `arac-health.py` —
     si CE reporter mourait (bug, launchd, crash), le watchdog perdait toute
     visibilité même si l'ingestion réelle continuait. v4 fait du heartbeat
     un signal SECONDAIRE (contexte informatif dans le message Telegram
     uniquement) : l'AUTORITÉ de fraîcheur est `arac.capture_manifests.
     run_ended_at` (LE CAPTEUR A-T-IL TOURNÉ), agrégée PAR SOURCE via le
     registre `arac.ingest_sources` — une source `captured`
     dont le capteur n'a pas tourné alerte MÊME SI le reporter est mort.
     **Correctif finding 5/17/18/29 (revue adversariale)** : une v4 initiale
     basait cette fraîcheur sur `arac.raw_messages.received_at`, ce qui
     mesure l'ACTIVITÉ UTILISATEUR (a-t-il écrit un message ?), pas la SANTÉ
     DU CAPTEUR (le scanner a-t-il tourné ?) — toute pause d'usage
     (vacances, weekend) au-delà de 4× le seuil déclenchait un faux
     CRITICAL Telegram permanent. `received_at` reste disponible en
     CONTEXTE secondaire du message (`message_lag_minutes`), jamais comme
     déclencheur de niveau. Seules les sources `coverage_policy='captured'`
     sont évaluées — `uncovered`/`excluded` ont déjà un motif consigné au
     registre, rien à surveiller (une source encore PROSPECTIVE, pas
     armée, DOIT être seedée `uncovered` — jamais `captured` — sous peine
     de CRITICAL permanent pendant toute la fenêtre de déploiement où rien
     ne peut structurellement y arriver, cf migration `0020`).
  3. **Statut `processing` : vocabulaire mort depuis la v2.** Le curateur v2
     n'a ni ce statut ni de bail à récupérer (mono-instance par construction,
     cf `curator_lib_v2` docstring) — toute la mécanique v3 qui surveillait
     un run bloqué dans cet état était du code mort qui ne pouvait jamais
     s'activer (`oldest_processing_age_h` n'était jamais peuplé). Supprimée.
  4. **Faux-CRIT au bootstrap (répétition observée en production).** `lag_
     minutes is None` (AUCUN `capture_manifests` jamais enregistré pour la
     source) déclenchait CRITICAL fail-closed inconditionnel — correct pour
     un capteur qui a tourné puis s'est tu, mais FAUX pour une source tout
     juste seedée `captured` dont l'exportateur de manifestes n'est pas
     encore déployé (ex. `claude_code@mac` au cutover, avant l'Étape 5) : ce
     n'est pas une preuve de panne, c'est l'absence de preuve. `lag_minutes
     is None` se sépare maintenant en deux cas : (a) des messages RÉCENTS
     sont arrivés (`message_lag_minutes` sous ×`SOURCE_LAG_BOOTSTRAP_MSG_
     MULT` le seuil) → les données prouvent que la capture marche → OK ;
     (b) rien ne le prouve (pas de message récent non plus) → PENDING
     bootstrap, WARNING doux au plus, **jamais** CRITICAL. Un historique de
     manifestes qui s'est TARI (`lag_minutes` non-None mais au-delà du
     seuil) reste, lui, un vrai signal de panne — WARN/CRIT par âge, INCHANGÉ.

Le poste source pousse toujours un heartbeat (`POST /v1/heartbeat`, avec
VOTRE node_id, metadata={schema:"arac-mac-health/N"...}) — ce watchdog
(timer systemd ~15 min) l'affiche en contexte, mais ne s'appuie plus dessus
pour décider du niveau d'alerte :

  OK / silencieux : le capteur de toutes les sources captées a tourné
                    récemment (ou est hors-ligne de façon bénigne — machine
                    endormie), backlog actionnable nul ou en cours de
                    drainage (curation récente), aucun dead-letter non
                    acquitté. Un utilisateur inactif (0 message récent) mais
                    dont le capteur tourne normalement reste OK — l'absence
                    d'activité n'est jamais une panne. Une source SANS AUCUN
                    manifeste mais avec des messages récents (capture pas
                    encore instrumentée, mais données arrivant bel et bien)
                    reste aussi OK.
  WARNING         : le capteur d'une source captée n'a pas tourné depuis
                    ≥ 2× son seuil attendu (machine en ligne) ; backlog
                    actionnable qui stagne ≥ 16h (2 créneaux circadiens
                    manqués) ; quota Claude atteint ≥ 2× en 24h (dégradation
                    attendue, pas un bug) ; dead-letter récent non acquitté ;
                    source SANS AUCUN manifeste ET sans message récent —
                    PENDING bootstrap (absence de preuve, pas preuve de
                    panne — jamais escaladé en CRITICAL).
  CRITICAL        : le capteur d'une source captée A DÉJÀ tourné (un
                    historique de manifestes existe) mais est muet depuis
                    ≥ 4× son seuil (machine en ligne) — capteur démontrablement
                    mort ; backlog actionnable qui stagne ≥ 24h (3 créneaux
                    manqués = famine) ; dead-letter non acquitté depuis
                    ≥ 24h (retries épuisés, bug probable).

Anti-spam : INCHANGÉ vs v3 (front montant, rappels CRITICAL espacés de 6h,
quiet-hours pour les WARNING, un seul message de récupération).

Codes de sortie : 0=OK, 1=WARNING, 2=CRITICAL, 3=erreur interne.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import socket
import sys
import time
from datetime import datetime, timezone
from typing import Any

import arac_runtime

def mac_node_id() -> str:
    """L'identifiant du poste qui vous envoie vos conversations.

    AUCUN nom en dur : c'est VOTRE `node_id`, celui déclaré à l'entretien dans
    `config/brain.toml` (ou posé par `ARAC_NODE_ID`). Le cerveau refuse déjà
    toute conversation venant d'un nœud non déclaré ; le watchdog doit
    surveiller LE MÊME nœud, sinon il surveille une machine qui n'existe pas
    et reste éternellement vert.

    Repli : chaîne vide si l'entretien n'a pas eu lieu — aucune source ne
    portera ce node_id, donc aucune ne sera gatée sur la liveness du poste.
    Mieux vaut un watchdog qui n'affirme rien qu'un watchdog qui se trompe
    de machine.
    """
    try:
        return arac_runtime.node_id()
    except Exception:
        return ""
# Marqueur cockpit (info seulement — NE PROUVE PAS que le Mac est éveillé).
COCKPIT_MARKER_HOST, COCKPIT_MARKER_PORT = "127.0.0.1", 18100
# Tunnel reverse-shell : sa bannière SSH prouve la liveness Mac de bout en bout.
MAC_PROBE_HOST = os.environ.get("ARAC_MAC_PROBE_HOST", "127.0.0.1")
MAC_PROBE_PORT = int(os.environ.get("ARAC_MAC_PROBE_PORT", 2223))
STATE_FILE_DEFAULT = os.path.join(str(arac_runtime.var_dir()), "ingest_watchdog_state.json")

REMIND_INTERVAL_CRIT_S = 6 * 3600  # rappels : CRITICAL uniquement

# --- Fraîcheur PAR SOURCE (arac.ingest_sources) ---------------
# Multiplicateurs du seuil `expected_max_lag_minutes` déclaré par le registre.
SOURCE_LAG_WARN_MULT = float(os.environ.get("ARAC_SOURCE_LAG_WARN_MULT", 2))
SOURCE_LAG_CRIT_MULT = float(os.environ.get("ARAC_SOURCE_LAG_CRIT_MULT", 4))
# Bootstrap (AUCUN manifeste jamais enregistré, `lag_minutes is None`) : seuil
# généreux appliqué à `message_lag_minutes` pour décider si des messages
# récents suffisent à PROUVER que la capture fonctionne malgré l'absence de
# manifeste (capteur pas encore déployé, cf finding faux-CRIT cutover
# claude_code@mac — répétition observée). Défensif : plus large que le seuil
# CRIT normal, car ce n'est qu'un signal de secours, pas l'autorité.
SOURCE_LAG_BOOTSTRAP_MSG_MULT = float(os.environ.get("ARAC_SOURCE_LAG_BOOTSTRAP_MSG_MULT", 4))

# --- Backlog actionnable vs cadence circadienne (3 créneaux/j = ~8h) -------
# WARN à 2 créneaux manqués, CRIT à 3 (une journée entière sans progrès alors
# que du travail actionnable attend = famine, pas un ralentissement normal).
CURATION_FAMINE_WARN_H = float(os.environ.get("ARAC_CURATION_FAMINE_WARN_H", 16))
CURATION_FAMINE_CRIT_H = float(os.environ.get("ARAC_CURATION_FAMINE_CRIT_H", 24))

# --- famine PAR ÂGE — WARN diurne --------
# Preuve (registre) : 648 rapports OK d'affilée avec actionable_backlog=30 et
# oldest_actionable_age_h=863,7 — la métrique existait (affichage) mais AUCUN
# seuil ne l'armait : tant qu'UNE curation progressait quelque part
# (curated_gap_h ~5-8h), la queue qui diverge restait invisible 23,5h/24.
# Seuil 48h = ALIGNÉ sur STARVATION_HOURS de conservation-audit (même
# définition d'âge : ATTENTE received_at ci-dessous) — le watchdog
# rend VISIBLE en 15 min (WARN) ce que conservation-audit PAGE la nuit (CRIT).
# JAMAIS CRIT ici : conservation-audit STARVATION est l'unique autorité de
# PAGE famine. Le
# caractère DIURNE est porté par les quiet-hours existantes (les WARN ne
# partent jamais la nuit, cf `should_notify`).
ACTIONABLE_AGE_WARN_H = float(os.environ.get("ARAC_ACTIONABLE_AGE_WARN_H", 48))

# --- files de revue sans consommateur ----
# Preuve (registre) : digestion_review_queue 9 pending (depuis 07-08, dont 6
# sur la conv 38530a65), memory_review_queue 11, incoming_proposal_queue 5 —
# AUCUN consommateur, AUCUNE alerte = backlog silencieux structurel (interdit
# par la mission). Seuil sur l'ÂGE (72h), PAS sur la simple présence
# (anti-bruit, exigence explicite du registre) : une entrée de moins de 3
# jours est une latence de triage normale (l'audit nocturne + un passage
# humain), jamais un signal ; les files actuelles (9/11/5 lignes, pending
# depuis ≥6 jours) franchissent le seuil immédiatement — c'est voulu.
REVIEW_QUEUE_WARN_AGE_H = float(os.environ.get("ARAC_REVIEW_QUEUE_WARN_AGE_H", 72))

# --- Fix round-1 (finding « exclusion PERMANENTE d'une conversation
# vivante ») : dérive post-exclusion. Une conversation exclue-tracée (0023)
# sort du gate ET de tous ses miroirs — si du contenu NON VIDE continue
# d'arriver APRÈS `excluded_at`, il ne sera plus jamais digéré ni visible
# nulle part (aucun bulletin ne couvrait ce cas : EXCLUDED_WITH_REASON ne
# liste que les 100 % vides). Cette métrique compte ces conversations
# (`received_at > excluded_at AND btrim(content) <> ''`) — TOUJOURS mesurée
# et reportée (observabilité pure) ; l'armement WARN est FLAG-GATÉ défaut
# OFF (règle : changement de comportement = flag, armement au
# déploiement). Seuil d'ÂGE (72h, anti-bruit, même logique que les
# review-queues) : le triage attendu = ré-inclure
# (exclude_conversation.py --reinclude) ou requalifier l'exclusion.
EXCLUSION_DRIFT_WARN_ENABLED = os.environ.get(
    "ARAC_WATCHDOG_EXCLUSION_DRIFT_WARN", "").strip().lower() in ("1", "true", "yes", "on")
EXCLUSION_DRIFT_WARN_AGE_H = float(os.environ.get("ARAC_EXCLUSION_DRIFT_WARN_AGE_H", 72))

# --- Dead-man reconcile-audit (finding revue sceptique fix-round-1) ---------
# reconcile-audit est l'UNIQUE émetteur Telegram des codes RECONCILE_*
# et AUCUN dead-man ne le surveillait : unité tuée (ex. borne TimeoutStartSec)
# ou timer désarmé -> plus jamais de verdict reconcile délivré, EN SILENCE
# (risque_fix, suggérait lui-même ce dead-man). Seuil 30h =
# cadence quotidienne du timer (01:35Z, 24h) + 6h de marge de dérive —
# cohérent avec la fenêtre (26h) : si l'audit saute UNE seule nuit, la
# fenêtre 26h manque définitivement le trou, c'est exactement le cas que ce
# WARN rend visible. Le heartbeat est écrit par reconcile_audit.py en fin de
# run COMPLET uniquement (chemin partagé via env ARAC_RECONCILE_HEARTBEAT,
# posé par les deux units).
RECONCILE_DEADMAN_WARN_H = float(os.environ.get("ARAC_RECONCILE_DEADMAN_WARN_H", 30))
RECONCILE_HEARTBEAT_DEFAULT = os.path.join(str(arac_runtime.var_dir()), "reconcile_audit_heartbeat.json")


def read_reconcile_heartbeat(path: str | None = None, now: float | None = None) -> dict[str, Any]:
    """-> {"status": "ok"|"bootstrap"|"unreadable", "age_h": float|None, "path"}.

    « bootstrap » (fichier ABSENT = reconcile-audit n'a encore jamais rendu de
    verdict complet sur cette machine, ex. premier déploiement, ≤24h avant le
    premier run nocturne) n'arme JAMAIS un WARN — mission zéro faux positif.
    « unreadable » (présent mais corrompu/illisible) = panne de MESURE ->
    WARN fail-loud en aval (`derive_state`), jamais un silence."""
    p = (path or os.environ.get("ARAC_RECONCILE_HEARTBEAT", "").strip()
         or RECONCILE_HEARTBEAT_DEFAULT)
    if not os.path.exists(p):
        return {"status": "bootstrap", "age_h": None, "path": p}
    try:
        with open(p, encoding="utf-8") as f:
            epoch = float(json.load(f)["epoch"])
    except Exception as e:  # noqa: BLE001 — corrompu = panne de mesure, pas un silence
        return {"status": "unreadable", "age_h": None, "path": p,
                "error": f"{type(e).__name__}: {e}"}
    ref = now if now is not None else _now()
    return {"status": "ok", "age_h": max(0.0, (ref - epoch) / 3600.0), "path": p}

# --- Dead-letter (retry_count >= 5, non acquitté) — inchangé vs v3 ---------
FAILED_AGE_CRIT_H = float(os.environ.get("ARAC_FAILED_AGE_CRIT_H", 24))

# --- Quota Claude répété (run_receipts.stop_reason='spawn:quota') ----------
QUOTA_REPEAT_WINDOW_H = float(os.environ.get("ARAC_QUOTA_REPEAT_WINDOW_H", 24))
QUOTA_REPEAT_MIN_COUNT = int(os.environ.get("ARAC_QUOTA_REPEAT_MIN_COUNT", 2))

# --- Heures calmes : la nuit DE QUI ? ---------------------------------------
#
# On N'ENVOIE PAS les nouvelles alertes WARN pendant la nuit — un WARN n'est
# pas une urgence, et une alerte qui réveille pour rien enseigne à ignorer les
# alertes. Les CRIT sonnent TOUJOURS, y compris la nuit.
#
# La fenêtre était exprimée en UTC, avec 21:00->05:00 pour défaut. Ce n'est la
# nuit de personne en particulier : c'est la nuit de l'endroit d'où ce fichier
# a été écrit, transposée. À Tokyo, elle taisait les WARN de 06:00 à 14:00
# heure locale — la matinée de travail — et les faisait sonner toute la nuit.
# L'inverse exact de l'intention.
#
# Les heures sont donc LOCALES, et le fuseau est celui que le cerveau déclare
# déjà pour ses cycles (`ARAC_CYCLE_TZ`, repli UTC) : une seule source de
# « quelle heure est-il ici », partagée par le moteur, le cockpit et ce chien
# de garde. Deux définitions de la nuit dans un même système finiraient par
# diverger.
QUIET_START_LOCAL = int(os.environ.get("ARAC_WATCHDOG_QUIET_START", 23))
QUIET_END_LOCAL = int(os.environ.get("ARAC_WATCHDOG_QUIET_END", 7))


def _quiet_tz():
    """Le fuseau des heures calmes — celui des cycles, jamais un autre.

    Importé paresseusement : ce module est chargé par le cockpit et par des
    scripts d'exploitation, et il ne doit pas tirer le moteur entier au
    démarrage. Un import qui échoue retombe sur UTC, comme le moteur.
    """
    try:
        from agents.cortex.cycle import cycle_tz

        return cycle_tz()
    except Exception:  # noqa: BLE001 — un fuseau illisible n'est pas une panne
        return timezone.utc


def _in_quiet_hours(hour_local: int | None = None, start: int = QUIET_START_LOCAL,
                    end: int = QUIET_END_LOCAL) -> bool:
    """Vrai si l'heure LOCALE tombe dans la fenêtre calme [start, end).

    La fenêtre peut croiser minuit — c'est même le cas nominal. Sans argument,
    l'heure lue est l'heure courante dans le fuseau déclaré du cerveau.
    """
    if hour_local is None:
        hour_local = datetime.now(_quiet_tz()).hour
    if start == end:
        return False
    if start < end:
        return start <= hour_local < end
    return hour_local >= start or hour_local < end

OK, WARN, CRIT = "ok", "warning", "critical"
_RANK = {OK: 0, WARN: 1, CRIT: 2}
_EXIT = {OK: 0, WARN: 1, CRIT: 2}


def _worse(a: str, b: str) -> str:
    return a if _RANK[a] >= _RANK[b] else b


def _now() -> float:
    return time.time()


def tunnel_reachable(host: str = COCKPIT_MARKER_HOST, port: int = COCKPIT_MARKER_PORT,
                     timeout: float = 4.0) -> bool:
    """Le listener cockpit accepte-t-il une connexion ? (INFO — ne prouve pas Mac éveillé)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def mac_alive(host: str = MAC_PROBE_HOST, port: int = MAC_PROBE_PORT, timeout: float = 5.0) -> bool:
    """Liveness Mac FIABLE de bout en bout : lit la bannière SSH via le reverse-tunnel.

    Un listener de remote-forward accepte la connexion TCP locale même si le Mac
    (l'autre extrémité) est endormi ; mais la bannière "SSH-..." n'est émise que
    par le sshd du Mac. Pas de bannière ⇒ Mac injoignable (endormi/hors-ligne).
    Lecture seule, aucune authentification.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            s.settimeout(timeout)
            try:
                data = s.recv(64)
            except OSError:
                return False
            return data.startswith(b"SSH-")
    except OSError:
        return False


# Échecs de curation TERMINAUX et ACQUITTÉS (non-rejouables).
#
# Ils ne doivent PAS maintenir une alerte WARNING permanente : un échec terminal
# déjà connu n'est pas actionnable, et une alerte qui ne s'éteint jamais finit
# par ne plus être lue. Un NOUVEL échec (id absent de cette liste) déclenche
# toujours WARN + notification (front montant).
#
# VIDE PAR DÉFAUT : un identifiant de conversation n'existe que dans la base
# qui l'a reçue. Vous déclarez les vôtres, sans redémarrer ni migrer, via
#     ARAC_INGEST_ACK_FAILED_IDS="<uuid>,<uuid>"
# La même notion existe côté migration (`_TERMINAL_ACKED_IDS`, 0012) pour
# l'acquittement durable.
ACK_FAILED_IDS_DEFAULT: frozenset[str] = frozenset()


def _acked_failed_ids() -> set[str]:
    """IDs d'échecs de curation acquittés (terminaux, non-rejouables). Défaut + env CSV."""
    env = os.environ.get("ARAC_INGEST_ACK_FAILED_IDS", "")
    extra = {x.strip() for x in env.split(",") if x.strip()}
    return set(ACK_FAILED_IDS_DEFAULT) | extra


# ---------------------------------------------------------------------------
# Reproduction FIDÈLE du gate curateur v2 (agents/lib/curator_lib_v2) — même
# WHERE/HAVING, mêmes env vars de seuil. Ce watchdog est un script SYNC
# (psycopg sync, pas d'event loop) : il ne peut pas appeler la coroutine
# async `select_eligible_conversations`/`count_uncurated` directement, donc le
# SELECT est dupliqué ICI À L'IDENTIQUE plutôt que ré-inventé — toute
# évolution du gate dans curator_lib_v2 DOIT être répercutée ici (garde de
# non-régression : tests/test_ingest_watchdog.py::test_gate_params_match_*
# et ::test_actionable_backlog_predicate_mirrors_curator_gate).
# ---------------------------------------------------------------------------
_GATE_QUIET_HOURS = float(os.environ.get("ARAC_CURATOR_QUIET_HOURS", "2"))
_GATE_MIN_NEW_MSGS = max(1, int(os.environ.get("ARAC_CURATOR_MIN_NEW_MSGS", "3")))
_GATE_AGE_CAP_HOURS = float(os.environ.get("ARAC_CURATOR_AGE_CAP_HOURS", "24"))


def _gate_params() -> dict[str, Any]:
    """Mêmes clés/valeurs que `agents.lib.curator_lib_v2._gate_params()` (mêmes
    env vars, mêmes défauts) — zéro dérive de seuil entre le gate réel du
    curateur et cette reproduction en lecture seule pour le watchdog."""
    return {"quiet_hours": _GATE_QUIET_HOURS, "min_new_msgs": _GATE_MIN_NEW_MSGS,
            "age_cap_hours": _GATE_AGE_CAP_HOURS}


# DEUX âges ÉTIQUETÉS, plus jamais un seul
# chiffre non qualifié. `oldest` (COALESCE(msg_created_at, received_at)) = âge
# du CONTENU — c'est lui qui affichait 863,7h à cause du backfill self-capture
# de contenu juin, et il resterait à 800h+ même si ARAC drainait
# parfaitement. `oldest_wait` (received_at des messages non curés NON VIDES) =
# âge d'ATTENTE dans ARAC — la même définition que conservation-audit
# STARVATION (`_ACTIONABLE_BACKLOG_DETAIL_SQL`, correctif faux-CRIT) :
# c'est LUI qui arme le WARN (un contenu ancien tout juste ingéré est
# automatiquement « frais » en attente). Le prédicat de SÉLECTION (WHERE/
# HAVING) reste STRICTEMENT celui du gate curateur — seule la projection
# change (garde de non-régression : test_actionable_backlog_predicate_
# mirrors_curator_gate, inchangé).
_ACTIONABLE_BACKLOG_SQL = (
    "SELECT count(*), "
    "  round(EXTRACT(EPOCH FROM (now() - min(oldest))) / 3600.0, 1), "
    "  round(EXTRACT(EPOCH FROM (now() - min(oldest_wait))) / 3600.0, 1) "
    "FROM ( "
    "  SELECT c.id, "
    "    min(COALESCE(m.msg_created_at, m.received_at)) "
    "      FILTER (WHERE m.id > c.curated_through_message_id) AS oldest, "
    "    min(m.received_at) "
    "      FILTER (WHERE m.id > c.curated_through_message_id "
    "              AND btrim(m.content) <> '') AS oldest_wait "
    "  FROM arac.conversations c "
    "  JOIN arac.raw_messages m ON m.conversation_id = c.id "
    "  WHERE c.acked = false AND c.retry_count < 5 "
    # une conversation EXCLUE-TRACÉE (reçu d'exclusion
    # motivée, colonnes 0023) sort du gate curateur ET de ce miroir — sinon le
    # watchdog re-signalerait comme actionnables des conversations drainées
    # (faux STARVATION). Miroir synchrone du prédicat curator_lib_v2 (garde :
    # test_actionable_backlog_predicate_mirrors_curator_gate).
    "    AND c.exclusion_category IS NULL "
    "    AND (c.next_retry_at IS NULL OR c.next_retry_at <= now()) "
    "  GROUP BY c.id "
    "  HAVING count(*) FILTER (WHERE m.id > c.curated_through_message_id) >= 1 "
    "     AND count(*) FILTER (WHERE m.id > c.curated_through_message_id "
    "                          AND btrim(m.content) <> '') >= 1 "
    "     AND ( "
    "          (now() - max(COALESCE(m.msg_created_at, m.received_at)) "
    "                 >= interval '1 hour' * %(quiet_hours)s "
    "           AND count(*) FILTER (WHERE m.id > c.curated_through_message_id) "
    "                 >= %(min_new_msgs)s) "
    "          OR min(COALESCE(m.msg_created_at, m.received_at)) "
    "               FILTER (WHERE m.id > c.curated_through_message_id) "
    "               <= now() - interval '1 hour' * %(age_cap_hours)s "
    "     ) "
    ") sub"
)


def collect_signals(dsn: str) -> dict[str, Any]:
    """LECTURE SEULE : heartbeat Mac (contexte), dead-letter, backlog
    actionnable (gate reproduit), fraîcheur par source, quota répété."""
    import psycopg  # type: ignore[import]
    sig: dict[str, Any] = {
        "health": None, "health_age_min": None,
        "sources": [],
        "backlog_failed": 0, "backlog_pending": 0,
        "oldest_failed_unacked_age_h": None, "curated_gap_h": None,
        "actionable_backlog": 0, "oldest_actionable_age_h": None,
        "oldest_actionable_wait_age_h": None,
        "quota_hits_24h": 0,
        "review_queues": [],
        "excluded_with_new_messages": 0,
        "excluded_new_messages_oldest_age_h": None,
    }
    with psycopg.connect(dsn, connect_timeout=8) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        with conn.cursor() as cur:
            # Heartbeat Mac : SECONDAIRE (contexte du message uniquement, cf
            # docstring module — l'autorité de fraîcheur est plus bas).
            cur.execute(
                "SELECT heartbeat_at, metadata FROM arac.nodes_heartbeat_history "
                "WHERE node_id = %s AND metadata ? 'schema' "
                "ORDER BY heartbeat_at DESC LIMIT 1",
                (mac_node_id(),),
            )
            row = cur.fetchone()
            if row:
                hb_at, meta = row
                sig["health"] = meta
                sig["health_age_min"] = (datetime.now(timezone.utc) - hb_at).total_seconds() / 60.0

            # Dead-letter v2 : retry épuisé (cap curator_lib), non acquitté.
            cur.execute(
                "SELECT id::text FROM arac.conversations "
                "WHERE retry_count >= 5 AND acked = false"
            )
            failed_ids = [r[0] for r in cur.fetchall()]
            acked = _acked_failed_ids()
            sig["backlog_failed"] = len(failed_ids)
            sig["backlog_failed_unacked"] = sum(1 for i in failed_ids if i not in acked)
            sig["backlog_failed_acked"] = sig["backlog_failed"] - sig["backlog_failed_unacked"]

            # pending v2 = arithmétique de curseur brute (info, PAS le
            # déclencheur d'alerte — cf `actionable_backlog` plus bas pour ça).
            cur.execute(
                "SELECT count(*) FROM ("
                "  SELECT c.id FROM arac.conversations c "
                "  JOIN arac.raw_messages m ON m.conversation_id = c.id "
                "  WHERE c.acked = false "
                "  GROUP BY c.id "
                "  HAVING count(*) FILTER (WHERE m.id > c.curated_through_message_id) >= 1"
                ") sub"
            )
            r = cur.fetchone()
            sig["backlog_pending"] = int(r[0] or 0) if r else 0

            cur.execute(
                "SELECT "
                "  max(round(EXTRACT(EPOCH FROM (now()-updated_at))/3600.0, 1)) "
                "    FILTER (WHERE retry_count >= 5 AND acked = false), "
                "  round(EXTRACT(EPOCH FROM (now()-max(curated_at)))/3600.0, 1) "
                "FROM arac.conversations"
            )
            fr = cur.fetchone()
            if fr:
                sig["oldest_failed_unacked_age_h"] = float(fr[0]) if fr[0] is not None else None
                sig["curated_gap_h"] = float(fr[1]) if fr[1] is not None else None

            # Backlog ACTIONNABLE : reproduction fidèle du gate curateur v2.
            # Deux âges étiquetés : contenu / attente, cf SQL.
            cur.execute(_ACTIONABLE_BACKLOG_SQL, _gate_params())
            fr = cur.fetchone()
            if fr:
                sig["actionable_backlog"] = int(fr[0] or 0)
                sig["oldest_actionable_age_h"] = float(fr[1]) if fr[1] is not None else None
                sig["oldest_actionable_wait_age_h"] = float(fr[2]) if fr[2] is not None else None

            # profondeur + âge du plus vieux pending des 3 review-queues
            # (producteurs actifs — pack oversized/omission/incoming — mais
            # AUCUN consommateur : sans cette métrique le backlog est
            # structurellement silencieux). Prédicat « pending » par table :
            # les vocabulaires de statut diffèrent (0028 / proposal v0.76 /
            # 0010). SAVEPOINT par file : une table absente (env partiel) ne
            # doit ni avorter la transaction ni faire taire les autres
            # métriques — l'entrée est alors marquée `error` (fail-loud en
            # aval, cf derive_state : illisible = WARN, jamais un silence).
            for queue, table, pending_pred in (
                ("digestion_review_queue", "arac.digestion_review_queue",
                 "status = 'pending'"),
                ("memory_review_queue", "arac.memory_review_queue",
                 "status = 'pending_human_review'"),
                ("incoming_proposal_queue", "arac.incoming_proposal_queue",
                 "status IN ('pending', 'needs_human')"),
            ):
                cur.execute("SAVEPOINT review_queue_probe")
                try:
                    cur.execute(
                        f"SELECT count(*), "  # noqa: S608 — identifiants constants ci-dessus, jamais d'entrée externe
                        f"  round(EXTRACT(EPOCH FROM (now() - min(created_at))) / 3600.0, 1) "
                        f"FROM {table} WHERE {pending_pred}"
                    )
                    n, age = cur.fetchone()
                    sig["review_queues"].append({
                        "queue": queue, "pending": int(n or 0),
                        "oldest_pending_age_h": float(age) if age is not None else None,
                    })
                except Exception as e:  # noqa: BLE001 — cf commentaire SAVEPOINT
                    cur.execute("ROLLBACK TO SAVEPOINT review_queue_probe")
                    sig["review_queues"].append({
                        "queue": queue, "pending": None,
                        "oldest_pending_age_h": None,
                        "error": f"{type(e).__name__}",
                    })
                else:
                    cur.execute("RELEASE SAVEPOINT review_queue_probe")

            # Fix round-1 : dérive post-exclusion (cf constantes
            # EXCLUSION_DRIFT_*) — conversations exclues-tracées (0023) qui
            # ont reçu du contenu NON VIDE APRÈS excluded_at : ce contenu ne
            # sera plus jamais digéré tant qu'un humain ne ré-inclut/ne
            # requalifie pas. `btrim` = même définition de « non vide » que
            # le gate. Toujours mesurée (le WARN, lui, est flag-gaté).
            cur.execute(
                "SELECT count(*), "
                "  round(EXTRACT(EPOCH FROM (now() - min(first_new))) / 3600.0, 1) "
                "FROM ( "
                "  SELECT c.id, min(m.received_at) AS first_new "
                "  FROM arac.conversations c "
                "  JOIN arac.raw_messages m ON m.conversation_id = c.id "
                "  WHERE c.exclusion_category IS NOT NULL "
                "    AND m.received_at > c.excluded_at "
                "    AND btrim(m.content) <> '' "
                "  GROUP BY c.id "
                ") sub"
            )
            r = cur.fetchone()
            if r:
                sig["excluded_with_new_messages"] = int(r[0] or 0)
                sig["excluded_new_messages_oldest_age_h"] = \
                    float(r[1]) if r[1] is not None else None

            # Fraîcheur PAR SOURCE (arac.ingest_sources) : seules
            # les sources `captured` sont évaluées (excluded/uncovered ont
            # déjà un motif consigné dans le registre, rien à surveiller).
            # AUTORITÉ = `capture_manifests.run_ended_at` (LE CAPTEUR A
            # TOURNÉ), jamais `raw_messages.received_at` (ACTIVITÉ
            # UTILISATEUR — signal SECONDAIRE seulement, `message_lag_minutes`,
            # cf docstring module point 2 / finding 5/17/18/29).
            cur.execute(
                "SELECT s.source_key, s.node_id, s.expected_max_lag_minutes, "
                "  round(EXTRACT(EPOCH FROM (now() - cap.last_run_ended))/60.0, 1) AS lag_minutes, "
                "  round(EXTRACT(EPOCH FROM (now() - msg.last_received))/60.0, 1) AS message_lag_minutes "
                "FROM arac.ingest_sources s "
                "LEFT JOIN ( "
                "  SELECT node_id, source_type, max(run_ended_at) AS last_run_ended "
                "  FROM arac.capture_manifests "
                "  WHERE run_ended_at IS NOT NULL "
                "  GROUP BY node_id, source_type "
                ") cap ON cap.node_id = s.node_id AND cap.source_type = s.source_type "
                # attribution par
                # `m.node_id` (le node qui a réellement ÉMIS le message),
                # PLUS JAMAIS `c.node_id` (le node CRÉATEUR de la
                # conversation). Preuve : le watchdog reportait pour
                # une source un message_lag_minutes=8187 alors que
                # max(raw_messages.received_at) du jour = 16:45Z — les
                # messages récents étaient appendés par un autre agent à
                # des conversations créées par un AUTRE node et attribués au
                # créateur. `message_lag_minutes` correspond désormais à
                # SELECT max(received_at) FROM arac.raw_messages filtré par
                # source (le test discriminant du registre). Signal
                # SECONDAIRE inchangé (jamais déclencheur de niveau, sauf
                # preuve positive bootstrap).
                "LEFT JOIN ( "
                "  SELECT m.node_id, c.source_type, max(m.received_at) AS last_received "
                "  FROM arac.raw_messages m "
                "  JOIN arac.conversations c ON c.id = m.conversation_id "
                "  GROUP BY m.node_id, c.source_type "
                ") msg ON msg.node_id = s.node_id AND msg.source_type = s.source_type "
                "WHERE s.coverage_policy = 'captured'"
            )
            sig["sources"] = [
                {"source_key": r[0], "node_id": r[1],
                 "expected_max_lag_minutes": (float(r[2]) if r[2] is not None else None),
                 "lag_minutes": (float(r[3]) if r[3] is not None else None),
                 "message_lag_minutes": (float(r[4]) if r[4] is not None else None)}
                for r in cur.fetchall()
            ]

            # Quota Claude répété : run_receipts.stop_reason
            # ='spawn:quota' (cf agents/cortex/cycle.py) — dégradation
            # ATTENDUE (pas un bug), mais mérite un WARN nommé si répétée.
            cur.execute(
                "SELECT count(*) FROM arac.run_receipts "
                "WHERE status = 'spawn_failed' AND stop_reason = 'spawn:quota' "
                "  AND started_at >= now() - interval '1 hour' * %(window_h)s",
                {"window_h": QUOTA_REPEAT_WINDOW_H},
            )
            r = cur.fetchone()
            sig["quota_hits_24h"] = int(r[0] or 0) if r else 0
    return sig


def _source_online(node_id: str | None, mac_online: bool) -> bool:
    """Liveness de la MACHINE hébergeant l'exportateur d'une source (pas du
    process lui-même) : les sources dont le node_id pointe le Mac sont
    gatées par `mac_online` (bannière SSH, cf `mac_alive`) ; toute autre
    source hébergée par le serveur lui-même (ce watchdog y tourne) est
    considérée en ligne par construction — si elle ne l'était pas, ce code
    ne s'exécuterait pas."""
    return mac_online if node_id == mac_node_id() else True


def evaluate_source_freshness(sources: list[dict[str, Any]], mac_online: bool) -> list[dict[str, Any]]:
    """Fonction PURE : évalue la fraîcheur PAR SOURCE captée (arac.ingest_sources).

    L'AUTORITÉ est `lag_minutes` — calculé côté DB depuis `arac.
    capture_manifests.run_ended_at` (LE CAPTEUR A-T-IL TOURNÉ), JAMAIS depuis
    `raw_messages.received_at` (qui mesure l'ACTIVITÉ UTILISATEUR, pas la
    santé du capteur — correctif finding 5/17/18/29, revue adversariale :
    une v4 initiale confondait les deux, ce qui déclenchait CRITICAL sur
    toute simple pause d'usage). `message_lag_minutes` (activité
    utilisateur) reste disponible en CONTEXTE informatif du message
    Telegram, jamais comme déclencheur de niveau ici — SAUF dans le cas
    bootstrap ci-dessous, où il sert de PREUVE POSITIVE de secours (pas
    d'autorité de niveau).

    `lag_minutes is None` = AUCUN manifeste jamais enregistré pour cette
    source. Ce n'est PAS, en soi, la preuve d'une panne — ça peut être un
    capteur pas encore déployé (bootstrap/cutover, correctif faux-CRIT
    répétition 2026-07-07, finding « claude_code@mac au cutover »). Deux cas :
      (a) des messages RÉCENTS sont arrivés (`message_lag_minutes` sous
          ×`SOURCE_LAG_BOOTSTRAP_MSG_MULT` le seuil déclaré) → les données
          prouvent que la capture marche malgré l'absence de manifeste → OK ;
      (b) rien ne le prouve → PENDING bootstrap, WARN doux (JAMAIS CRITICAL —
          absence de preuve ≠ preuve d'absence).
    Un historique de manifestes qui s'est TARI (`lag_minutes` non-None,
    au-delà du seuil ×WARN/×CRIT) reste, lui, un vrai signal de panne
    démontrable — INCHANGÉ, toujours CRITICAL à ×4.
    `expected_max_lag_minutes is None` (défensif — la contrainte
    `ingest_sources_honesty_check` l'exclut normalement pour une source
    `captured`) = WARN fail-closed plutôt qu'un silence.
    """
    out: list[dict[str, Any]] = []
    for src in sources:
        node_id = src.get("node_id")
        online = _source_online(node_id, mac_online)
        thr = src.get("expected_max_lag_minutes")
        lag = src.get("lag_minutes")
        msg_lag = src.get("message_lag_minutes")
        key = src.get("source_key", "?")
        level, reason = OK, None
        if not online:
            reason = f"source {key} : machine hors-ligne (bénin, non évalué)"
        elif thr is None:
            level, reason = WARN, f"source {key} : seuil de fraîcheur manquant au registre (fail-closed)"
        elif lag is None and msg_lag is not None and msg_lag <= thr * SOURCE_LAG_BOOTSTRAP_MSG_MULT:
            pass  # bootstrap PROUVÉ par des messages récents : OK, reason=None.
        elif lag is None:
            level, reason = WARN, (
                f"source {key} : PENDING bootstrap — aucun manifeste de capture jamais "
                f"enregistré ET aucun message récent pour compenser (captée, seuil "
                f"{thr:.0f} min ×{SOURCE_LAG_BOOTSTRAP_MSG_MULT:.0f}) — absence de preuve, "
                f"pas preuve de panne (capteur probablement pas encore déployé)")
        elif lag > thr * SOURCE_LAG_CRIT_MULT:
            level, reason = CRIT, (
                f"source {key} : capteur muet depuis {lag:.0f} min (aucun run terminé) "
                f"(seuil {thr:.0f} min ×{SOURCE_LAG_CRIT_MULT:.0f})")
        elif lag > thr * SOURCE_LAG_WARN_MULT:
            level, reason = WARN, (
                f"source {key} : capteur en retard — {lag:.0f} min depuis le dernier run terminé "
                f"(seuil {thr:.0f} min ×{SOURCE_LAG_WARN_MULT:.0f})")
        out.append({"source_key": key, "level": level, "reason": reason,
                    "online": online, "lag_minutes": lag, "expected_max_lag_minutes": thr,
                    "message_lag_minutes": msg_lag})
    return out


def derive_state(sig: dict[str, Any], mac_online: bool, prev: dict[str, Any]) -> dict[str, Any]:
    """Fonction PURE (testable sans DB) : (sig, mac_online, prev) -> {level, reasons, ...}.

    `mac_online` = liveness Mac FIABLE (bannière SSH). `sig["health"]` (le
    heartbeat Mac) n'intervient PLUS dans le niveau — contexte du message
    seulement (cf docstring module, point 2).

    Retourne aussi `codes` : la liste STABLE des codes d'état actifs (sans
    aucun chiffre variable — un âge qui passe de 100h à 101h n'est PAS un
    changement d'état). C'est le support du pattern anti-accoutumance,
    appliqué uniformément : `main` notifie quand un code
    APPARAÎT (changement d'état) même à niveau global constant — un nouveau
    problème ne doit jamais être masqué par un WARN déjà en cours."""
    level = OK
    reasons: list[str] = []
    codes: list[str] = []

    # --- fraîcheur PAR SOURCE : l'AUTORITÉ (capture_manifests.run_ended_at) -
    source_states = evaluate_source_freshness(sig.get("sources", []), mac_online)
    for s in source_states:
        if s["level"] != OK:
            level = _worse(level, s["level"])
            reasons.append(s["reason"])
            codes.append(f"source:{s['source_key']}:{s['level']}")

    # --- backlog actionnable vs cadence circadienne (famine vs drainage) ---
    actionable = int(sig.get("actionable_backlog", 0) or 0)
    gap = sig.get("curated_gap_h")
    if actionable > 0:
        if gap is None or gap >= CURATION_FAMINE_CRIT_H:
            level = _worse(level, CRIT)
            gap_txt = "jamais" if gap is None else f"{gap:.1f}h"
            reasons.append(
                f"{actionable} conversation(s) actionnable(s) en attente, aucune curation "
                f"réussie depuis {gap_txt} (cadence circadienne 3/j ~{CURATION_FAMINE_CRIT_H:.0f}h "
                f"dépassée : famine)")
            codes.append("famine_gap:critical")
        elif gap >= CURATION_FAMINE_WARN_H:
            level = _worse(level, WARN)
            reasons.append(
                f"{actionable} conversation(s) actionnable(s), dernière curation il y a "
                f"{gap:.1f}h (retard vs cadence circadienne 3/j)")
            codes.append("famine_gap:warning")
        # sinon : drainage en cours (curseurs récemment avancés) — rien à signaler.

    # --- famine PAR ÂGE (la queue qui diverge malgré une curation qui
    #     progresse). Armée sur l'âge d'ATTENTE (received_at —
    #     mesurer sur l'âge CONTENU garderait un WARN éternel tant que la
    #     cohorte backfillée juin n'est pas drainée, 863,7h mesurées).
    #     WARN uniquement — l'autorité de PAGE CRIT famine est
    #     conservation-audit STARVATION.
    #     Pas de grâce healing ici (visibilité 15 min, pas une page) :
    #     received_at rend déjà « fraîche » toute matière nouvellement entrée.
    wait_age = sig.get("oldest_actionable_wait_age_h")
    if actionable > 0 and wait_age is not None and wait_age >= ACTIONABLE_AGE_WARN_H:
        level = _worse(level, WARN)
        content_age = sig.get("oldest_actionable_age_h")
        content_txt = f"{content_age:.0f}h" if content_age is not None else "?"
        reasons.append(
            f"famine par âge : {actionable} conversation(s) actionnable(s) dont la plus "
            f"ancienne ATTEND depuis {wait_age:.0f}h (seuil {ACTIONABLE_AGE_WARN_H:.0f}h, "
            f"âge d'attente received_at ; âge contenu={content_txt}) — la curation "
            f"progresse mais la queue diverge (autorité de PAGE : conservation-audit "
            f"STARVATION)")
        codes.append("famine_age:warning")

    # --- dead-letter (retries épuisés, non acquitté) — inchangé vs v3 -----
    failed_unacked = int(sig.get("backlog_failed_unacked", sig.get("backlog_failed", 0)) or 0)
    failed_acked = int(sig.get("backlog_failed_acked", 0) or 0)
    if failed_unacked > 0:
        level = _worse(level, WARN)
        suffix = f" ; {failed_acked} acquittée(s) ignorée(s)" if failed_acked else ""
        reasons.append(
            f"{failed_unacked} conversation(s) en 'failed' (retries épuisés) non acquittée(s){suffix}")
        codes.append("dead_letter:warning")
    elif failed_acked > 0:
        reasons.append(f"{failed_acked} conversation(s) 'failed' acquittée(s) (terminale, ignorée)")

    ofa = sig.get("oldest_failed_unacked_age_h")
    if ofa is not None and ofa >= FAILED_AGE_CRIT_H:
        level = _worse(level, CRIT)
        reasons.append(
            f"conversation 'failed' non acquittée depuis {ofa:.0f}h "
            f"(>{FAILED_AGE_CRIT_H:.0f}h : retries épuisés / bug réel probable — intervention requise)")
        codes.append("dead_letter_aged:critical")

    # --- quota Claude répété (dégradation ATTENDUE, pas un bug) ------------
    quota_hits = int(sig.get("quota_hits_24h", 0) or 0)
    if quota_hits >= QUOTA_REPEAT_MIN_COUNT:
        level = _worse(level, WARN)
        reasons.append(
            f"quota Claude atteint {quota_hits}× en {QUOTA_REPEAT_WINDOW_H:.0f}h (spawn:quota) — "
            f"cadence de curation dégradée, PAS un bug (reprise au prochain cycle)")
        codes.append("quota_repeated:warning")

    # --- review-queues (backlog silencieux structurel) --------------
    #     WARN sur l'ÂGE du plus vieux pending (>72h), jamais sur la simple
    #     présence (anti-bruit — cf justification du seuil, constantes).
    #     Une file ILLISIBLE (table absente/permission) = WARN fail-loud :
    #     ne jamais transformer une panne de mesure en silence.
    for q in sig.get("review_queues", []):
        qname = q.get("queue", "?")
        if q.get("error"):
            level = _worse(level, WARN)
            reasons.append(
                f"review-queue {qname} : ILLISIBLE ({q['error']}) — panne de mesure, "
                f"pas un backlog nul (fail-loud)")
            codes.append(f"review_queue_unreadable:{qname}:warning")
            continue
        age = q.get("oldest_pending_age_h")
        pending = int(q.get("pending") or 0)
        if pending > 0 and age is not None and age >= REVIEW_QUEUE_WARN_AGE_H:
            level = _worse(level, WARN)
            reasons.append(
                f"review-queue {qname} : {pending} entrée(s) pending, la plus vieille "
                f"depuis {age:.0f}h (> {REVIEW_QUEUE_WARN_AGE_H:.0f}h) — aucun "
                f"consommateur ne draine cette file, triage requis")
            codes.append(f"review_queue:{qname}:warning")

    # --- Fix round-1 : dérive post-exclusion (contenu VIVANT arrivé après
    #     excluded_at sur une conversation exclue-tracée — plus jamais digéré
    #     ni visible sans triage humain). Métrique TOUJOURS reportée ;
    #     l'armement WARN est flag-gaté défaut OFF (EXCLUSION_DRIFT_WARN_
    #     ENABLED, armement au déploiement) + seuil d'âge anti-bruit.
    drift_n = int(sig.get("excluded_with_new_messages", 0) or 0)
    drift_age = sig.get("excluded_new_messages_oldest_age_h")
    if (EXCLUSION_DRIFT_WARN_ENABLED and drift_n > 0
            and drift_age is not None and drift_age >= EXCLUSION_DRIFT_WARN_AGE_H):
        level = _worse(level, WARN)
        reasons.append(
            f"dérive post-exclusion : {drift_n} conversation(s) EXCLUE(S) ont reçu du "
            f"contenu non vide APRÈS leur exclusion (le plus ancien depuis "
            f"{drift_age:.0f}h > {EXCLUSION_DRIFT_WARN_AGE_H:.0f}h) — ce contenu ne sera "
            f"plus jamais digéré : ré-inclure (exclude_conversation.py --reinclude) ou "
            f"requalifier l'exclusion")
        codes.append("exclusion_drift:warning")

    # --- Dead-man reconcile-audit (fix-round-1, cf RECONCILE_DEADMAN_WARN_H) --
    #     WARN uniquement (le verdict reconcile lui-même reste porté par
    #     reconcile-audit, autorité unique — ici on surveille que
    #     l'AUDITEUR vit, pas ce qu'il conclut). « bootstrap » (jamais
    #     tourné) = contexte, jamais un WARN (zéro faux positif au premier
    #     déploiement, premier run nocturne ≤24h).
    hb = sig.get("reconcile_heartbeat") or {}
    if hb.get("status") == "unreadable":
        level = _worse(level, WARN)
        reasons.append(
            f"dead-man reconcile-audit : heartbeat ILLISIBLE ({hb.get('error')}) — "
            f"panne de mesure, pas une preuve de vie (fail-loud)")
        codes.append("reconcile_deadman_unreadable:warning")
    elif hb.get("status") == "ok" and hb.get("age_h") is not None \
            and hb["age_h"] >= RECONCILE_DEADMAN_WARN_H:
        level = _worse(level, WARN)
        reasons.append(
            f"dead-man reconcile-audit : dernier run complet il y a {hb['age_h']:.0f}h "
            f"(seuil {RECONCILE_DEADMAN_WARN_H:.0f}h = cadence quotidienne + marge) — "
            f"l'UNIQUE émetteur Telegram des codes RECONCILE_* ne rend plus de "
            f"verdict, et la fenêtre d'audit (26h) manque tout trou au-delà d'une "
            f"nuit sautée")
        codes.append("reconcile_deadman:warning")

    if level == OK and not reasons:
        reasons.append(
            "toutes les sources captées sont fraîches, backlog actionnable nul ou en cours "
            "de drainage — rien à signaler")

    return {"level": level, "reasons": reasons, "source_states": source_states,
            "codes": codes}


def _emoji(level: str) -> str:
    return {OK: "✅", WARN: "⚠️", CRIT: "🔴"}.get(level, "❓")


def build_message(state: dict[str, Any], sig: dict[str, Any], mac_online: bool,
                  tunnel_marker: bool, recovery: bool) -> str:
    h = sig.get("health") or {}
    lines = []
    if recovery:
        lines += ["✅ ARAC ingestion — RÉCUPÉRATION", "", "L'incident est résolu, tout est revenu au vert."]
    else:
        lines += [f"{_emoji(state['level'])} ARAC ingestion — {state['level'].upper()}", ""]
        lines += ["Cause(s) :"] + [f"  • {r}" for r in state["reasons"]]

    lines.append("")
    lines.append("— Fraîcheur par source (autorité : capture_manifests.run_ended_at) —")
    for s in state.get("source_states", []):
        lag = s.get("lag_minutes")
        thr = s.get("expected_max_lag_minutes")
        msg_lag = s.get("message_lag_minutes")
        lag_txt = f"{lag:.0f} min" if lag is not None else "jamais tourné"
        thr_txt = f"{thr:.0f} min" if thr is not None else "?"
        msg_txt = f"{msg_lag:.0f} min" if msg_lag is not None else "jamais"
        online_txt = "en ligne" if s.get("online") else "hors-ligne (bénin)"
        lines.append(
            f"• {s['source_key']} : {_emoji(s['level'])} capteur lag={lag_txt} (seuil {thr_txt}) "
            f"[{online_txt}] — activité utilisateur (secondaire, non-alertant)={msg_txt}")

    lines.append("")
    lines.append("— Curation —")
    # les DEUX âges, étiquetés (contenu = COALESCE(msg_created_at,…),
    # attente = received_at) — plus jamais un seul chiffre non qualifié.
    lines.append(
        f"• backlog actionnable={sig.get('actionable_backlog')} "
        f"(âge contenu={sig.get('oldest_actionable_age_h')} h / "
        f"âge attente={sig.get('oldest_actionable_wait_age_h')} h ; "
        f"gap dernière curation={sig.get('curated_gap_h')} h)")
    lines.append(
        f"• dead-letter (failed non acquitté)={sig.get('backlog_failed_unacked', sig.get('backlog_failed'))} "
        f"; backlog brut (info)={sig.get('backlog_pending')}")
    if sig.get("quota_hits_24h"):
        lines.append(f"• quota Claude atteint {sig['quota_hits_24h']}× en {QUOTA_REPEAT_WINDOW_H:.0f}h")
    review_queues = sig.get("review_queues") or []
    if any((q.get("pending") or 0) > 0 or q.get("error") for q in review_queues):
        lines.append("")
        lines.append("— Files de revue —")
        for q in review_queues:
            if q.get("error"):
                lines.append(f"• {q.get('queue')} : ILLISIBLE ({q['error']})")
            elif (q.get("pending") or 0) > 0:
                age = q.get("oldest_pending_age_h")
                age_txt = f"{age:.0f} h" if age is not None else "?"
                lines.append(
                    f"• {q.get('queue')} : {q['pending']} pending, plus vieille={age_txt} "
                    f"(seuil {REVIEW_QUEUE_WARN_AGE_H:.0f} h)")

    lines.append("")
    lines.append("— Contexte (secondaire) —")
    lines.append(f"• Mac joignable (bannière SSH) : {'OUI' if mac_online else 'NON (endormi/hors-ligne)'}")
    lines.append(f"• marqueur cockpit 18100 : {'présent' if tunnel_marker else 'absent'} (info)")
    if h:
        lines.append(
            f"• heartbeat Mac : job chargé={h.get('ingest_job_loaded')} "
            f"disabled={h.get('ingest_job_disabled')} dernier exit={h.get('last_exit_code')} "
            f"échecs_consécutifs={h.get('consecutive_failures')}")
        age = sig.get("health_age_min")
        lines.append(f"• heartbeat Mac âge={age:.0f} min" if age is not None else "• heartbeat Mac âge=?")
    else:
        lines.append("• aucun heartbeat Mac reçu (secondaire — l'autorité reste capture_manifests.run_ended_at)")
    return "\n".join(lines)


def load_state(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(path: str, state: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def should_notify(prev: dict[str, Any], level: str, now: float,
                  backlog_grew: bool = False, quiet_hours: bool = False,
                  new_codes: bool = False) -> tuple[bool, bool]:
    """(notify, is_recovery). Politique anti-spam v3 + pattern V5 :
      • OK    : UN message de récup si on sortait d'un WARN/CRIT non encore récupéré.
      • toute aggravation de niveau (rang en hausse) notifie.
      • une AUGMENTATION du backlog 'failed' notifie (front montant), même à niveau égal.
      • `new_codes` (pattern anti-accoutumance V5 appliqué
        uniformément) : un NOUVEAU code d'état (cf `derive_state`, codes
        stables sans chiffre variable) notifie même à niveau égal — page sur
        CHANGEMENT d'état, jamais sur la répétition du même état.
      • rappels périodiques : CRITICAL UNIQUEMENT (6h — la re-page lente ;
        jamais de rappel WARNING, INCHANGÉ).
      • quiet-hours : on N'ENVOIE PAS les WARN la nuit (anti faux-positif). Les
        CRIT et les récup passent TOUJOURS.
    """
    prev_level = prev.get("level", OK)
    prev_notified_at = float(prev.get("last_notified_at", 0) or 0)
    notify, is_recovery = False, False
    if level == OK:
        if prev_level in (WARN, CRIT) and not prev.get("recovery_sent", False):
            notify, is_recovery = True, True
    elif _RANK[level] > _RANK.get(prev_level, 0):
        notify = True
    elif backlog_grew or new_codes:
        notify = True
    elif level == CRIT and now - prev_notified_at >= REMIND_INTERVAL_CRIT_S:
        notify = True
    if notify and quiet_hours and level == WARN and not is_recovery:
        return False, False
    return notify, is_recovery


# --- Pattern anti-accoutumance V5 (mission « zéro faux
# positif ») : page sur CHANGEMENT d'état + re-page périodique LENTE si
# l'état persiste. Helper PARTAGÉ (conservation_audit l'importe d'ici — même
# doctrine que send_telegram : une seule implémentation, jamais dupliquée).
# L'état durable vit dans un fichier state JSON (load_state/save_state
# ci-dessus, var/ du repo) — même mécanique que l'état anti-spam de ce
# watchdog, aucune table DB (l'alerting doit marcher même DB down).
REPAGE_SLOW_INTERVAL_S_DEFAULT = float(os.environ.get("ARAC_REPAGE_SLOW_INTERVAL_S", 24 * 3600))


def page_on_state_change(prev_entry: dict[str, Any] | None, *, fingerprint: str,
                         now: float,
                         repage_interval_s: float = REPAGE_SLOW_INTERVAL_S_DEFAULT,
                         ) -> tuple[bool, str, dict[str, Any]]:
    """(page, why, new_entry). Fonction PURE.

    `fingerprint` = représentation STABLE de l'état alertant (jamais un
    chiffre qui varie à chaque mesure — le caller la construit, par ex.
    ensemble d'uids + bucket d'âge par 24h). Page si :
      • premier franchissement (aucune page enregistrée) ;
      • le fingerprint a CHANGÉ depuis la dernière page (changement d'état) ;
      • l'état persiste inchangé depuis ≥ `repage_interval_s` depuis la
        dernière page (re-page périodique lente, défaut 24h — un vrai
        problème persistant mérite UN rappel par jour, pas un cri par run).
    Sinon : pas de page (l'état est connu, déjà pagé, inchangé).

    Le caller ne doit PERSISTER `new_entry` (fichier state) que si la page a
    réellement été ENVOYÉE (sent ok) — sinon garder l'ancienne entrée pour
    re-tenter au prochain run (même discipline que l'anti-spam du watchdog).
    """
    entry = dict(prev_entry or {})
    last_fp = entry.get("fingerprint")
    last_paged = entry.get("last_paged_at")
    if last_fp is None or last_paged is None:
        page, why = True, "premier franchissement"
    elif fingerprint != last_fp:
        page, why = True, "changement d'état depuis la dernière page"
    elif now - float(last_paged) >= repage_interval_s:
        page, why = True, (f"re-page périodique lente — état persistant depuis "
                           f"{(now - float(last_paged)) / 3600.0:.0f}h")
    else:
        page, why = False, "état inchangé depuis la dernière page (anti-accoutumance)"
    new_entry = {"fingerprint": fingerprint if page else last_fp,
                 "last_paged_at": now if page else last_paged,
                 "last_seen_at": now}
    return page, why, new_entry


# --- : retry borné du canal d'alerte ---
# Preuve (registre) : 14-07, `conservation.alert_sent ok=false detail='chat …:
# ReadTimeout'` — un CRIT STARVATION RÉEL perdu sur UN seul `client.post`
# (aucune tentative rejouée), et personne n'a été prévenu. Correctif : boucle de
# retry bornée (3 tentatives, backoff exponentiel 2/4 s + jitter, timeout 15 s
# CONSERVÉ) autour de CHAQUE post par chat_id, log JSON de chaque tentative
# échouée, échec FINAL = log ERROR structuré + compteur process. Ce helper est
# PARTAGÉ (conservation_audit, reconcile_audit, agents/cortex/cycle le chargent
# tous d'ici) — tous les émetteurs héritent du retry. Risque accepté (registre
#) : doublon possible si le timeout survient APRÈS réception côté
# Telegram — doublon << perte.
TELEGRAM_SEND_ATTEMPTS = max(1, int(os.environ.get("ARAC_TELEGRAM_SEND_ATTEMPTS", 3)))
TELEGRAM_RETRY_BASE_S = float(os.environ.get("ARAC_TELEGRAM_RETRY_BASE_S", 2.0))

# Finding revue sceptique fix-round-1 (conservation_audit.format_alert:366) :
# l'API Telegram sendMessage REFUSE tout text > 4096 chars avec HTTP 400 —
# classé DÉFINITIF par `_post_with_retry` (retryable = 429/5xx seulement,
# zéro retry) -> un CRIT trop verbeux (détail STARVATION ~630 chars +
# 10 violations verbeuses + header peut franchir 4096) serait perdu de façon
# PERMANENTE : le state conservé fait re-décider la même page trop
# longue chaque nuit -> boucle de perte du CRIT, visible seulement en
# journald. Tronquer ici (source unique d'envoi) protège TOUS
# les émetteurs (watchdog, conservation, reconcile, cortex). 3900 = marge
# sous 4096 pour le suffixe de troncature (le rapport COMPLET reste toujours
# loggé en JSON sur stderr par chaque émetteur — rien n'est perdu, seul le
# message Telegram est coupé).
TELEGRAM_HARD_LIMIT_CHARS = 4096
TELEGRAM_SAFE_CHARS = max(256, int(os.environ.get("ARAC_TELEGRAM_SAFE_CHARS", 3900)))


def _truncate_for_telegram(text: str) -> str:
    """Borne `text` sous la limite dure de l'API (4096) — voir constante."""
    if len(text) <= TELEGRAM_SAFE_CHARS:
        return text
    suffix = f"\n… [tronqué : {len(text)} chars, rapport complet en journald]"
    truncated = text[: TELEGRAM_SAFE_CHARS - len(suffix)] + suffix
    _send_log("telegram.text_truncated", original_chars=len(text),
              sent_chars=len(truncated))
    return truncated
# Compteur process des échecs FINALS (toutes tentatives épuisées) — exposé dans
# le log `telegram.send_failed` pour audit (le messager ne meurt plus en silence).
_send_failures_total = 0

# Injectable pour les tests (jamais de vrai sleep dans la suite hermétique).
_retry_sleep = time.sleep


def _send_log(event: str, **fields: Any) -> None:
    """Log JSON une-ligne sur stderr (convention journald du repo)."""
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), file=sys.stderr)


def _post_with_retry(client: Any, httpx_mod: Any, api: str, cid: str, text: str) -> tuple[bool, str]:
    """UN chat_id : jusqu'à `TELEGRAM_SEND_ATTEMPTS` posts, backoff exponentiel
    + jitter entre les tentatives. Retryable = erreur réseau (httpx.HTTPError,
    ReadTimeout compris — le cas mesuré) ou HTTP 429/5xx ; un 4xx autre
    (chat inconnu, message invalide) est définitif — inutile de rejouer."""
    global _send_failures_total
    last_err, attempt = "?", 0
    for attempt in range(1, TELEGRAM_SEND_ATTEMPTS + 1):
        try:
            r = client.post(api, json={"chat_id": cid, "text": text, "disable_web_page_preview": True})
            if r.status_code == 200:
                if attempt > 1:
                    _send_log("telegram.send_recovered", chat=cid, attempt=attempt)
                return True, "ok"
            last_err = f"HTTP {r.status_code}"
            retryable = r.status_code == 429 or r.status_code >= 500
        except httpx_mod.HTTPError as e:
            last_err = type(e).__name__
            retryable = True
        _send_log("telegram.send_attempt_failed", chat=cid, attempt=attempt,
                  max_attempts=TELEGRAM_SEND_ATTEMPTS, detail=last_err)
        if not retryable or attempt >= TELEGRAM_SEND_ATTEMPTS:
            break
        # Backoff exponentiel 2/4 s (base×2^n) + jitter uniforme [0, base) —
        # désynchronise les émetteurs concurrents (watchdog 15 min + audits
        # nocturnes partagent ce helper).
        _retry_sleep(TELEGRAM_RETRY_BASE_S * (2 ** (attempt - 1))
                     + random.uniform(0, TELEGRAM_RETRY_BASE_S))
    _send_failures_total += 1
    _send_log("telegram.send_failed", level="ERROR", chat=cid, attempts=attempt,
              detail=last_err, send_failures_total=_send_failures_total)
    return False, last_err


def _quiet_httpx_logs() -> None:
    """httpx logge en INFO l'URL complète `.../bot<jeton>/sendMessage` : on
    relève le seuil pour que le jeton ne soit plus écrit dans les journaux."""
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def send_telegram(text: str) -> tuple[bool, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_ids_raw = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
    if not token or not chat_ids_raw:
        return False, "TELEGRAM_BOT_TOKEN / TELEGRAM_ALLOWED_CHAT_IDS manquant(s)"
    try:
        import httpx
    except ImportError:
        return False, "httpx indisponible"
    api = f"https://api.telegram.org/bot{token}/sendMessage"
    # Borne 4096 de l'API : un text trop long = HTTP 400 définitif (jamais
    # rejoué) -> perte permanente du message, cf `_truncate_for_telegram`.
    text = _truncate_for_telegram(text)
    ok_all, errs = True, []
    # timeout=15 CONSERVÉ : le fix est le retry, pas un timeout plus long.
    _quiet_httpx_logs()
    with httpx.Client(timeout=15) as client:
        for cid in [c.strip() for c in chat_ids_raw.split(",") if c.strip()]:
            ok, detail = _post_with_retry(client, httpx, api, cid, text)
            if not ok:
                ok_all = False; errs.append(f"chat {cid}: {detail}")
    return ok_all, ("ok" if ok_all else "; ".join(errs))


def main() -> int:
    p = argparse.ArgumentParser(description="Watchdog d'ingestion ARAC v4 (fraîcheur par source, autorité DB).")
    p.add_argument("--state-file", default=os.environ.get("ARAC_INGEST_WATCHDOG_STATE", STATE_FILE_DEFAULT))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--test-telegram", action="store_true")
    args = p.parse_args()

    if args.test_telegram:
        ok, detail = send_telegram("🧪 ARAC ingest-watchdog v4 — message de TEST.")
        print(json.dumps({"test_telegram": ok, "detail": detail}, ensure_ascii=False))
        return 0 if ok else 3

    dsn = os.environ.get("DATABASE_URL_READONLY") or os.environ.get("DATABASE_URL")
    if not dsn:
        print("[watchdog] DATABASE_URL_READONLY/DATABASE_URL absent.", file=sys.stderr)
        return 3
    try:
        sig = collect_signals(dsn)
    except Exception as exc:  # noqa: BLE001
        print(f"[watchdog] Erreur collecte : {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3

    mac_online = mac_alive()
    tunnel_marker = tunnel_reachable()
    # Dead-man reconcile-audit (fix-round-1) : signal FICHIER (heartbeat),
    # pas DB — injecté dans `sig` pour garder `derive_state` PURE/testable.
    sig["reconcile_heartbeat"] = read_reconcile_heartbeat()
    prev = load_state(args.state_file)
    state = derive_state(sig, mac_online, prev)
    level = state["level"]
    now = _now()

    # Le front montant de notification se base sur les échecs NON acquittés (assault §7) :
    # un échec terminal acquitté ne doit ni alerter ni compter comme "backlog en hausse".
    backlog_failed = int(sig.get("backlog_failed_unacked", sig.get("backlog_failed", 0)) or 0)
    notified_backlog = int(prev.get("notified_backlog_failed", 0) or 0)
    backlog_grew = backlog_failed > notified_backlog

    # Pattern V5 : un code d'état qui APPARAÎT
    # (ex. une review-queue franchit 72h pendant qu'un WARN source court
    # déjà) notifie — changement d'état, même à niveau égal. Un code qui
    # disparaît ne re-notifie pas (l'amélioration partielle n'est pas une
    # alerte ; la récup complète l'est, via is_recovery).
    codes = state.get("codes", [])
    new_codes = bool(set(codes) - set(prev.get("notified_codes") or []))

    quiet = _in_quiet_hours()
    notify, is_recovery = should_notify(prev, level, now, backlog_grew=backlog_grew,
                                        quiet_hours=quiet, new_codes=new_codes)
    msg = build_message(state, sig, mac_online, tunnel_marker, is_recovery)

    report = {"level": level, "reasons": state["reasons"], "codes": codes,
              "mac_online": mac_online,
              "tunnel_marker": tunnel_marker, "backlog_failed": backlog_failed,
              "backlog_grew": backlog_grew, "health_age_min": sig.get("health_age_min"),
              "quiet_hours": quiet, "notify": notify, "is_recovery": is_recovery,
              "actionable_backlog": sig.get("actionable_backlog"),
              "oldest_actionable_age_h": sig.get("oldest_actionable_age_h"),
              "oldest_actionable_wait_age_h": sig.get("oldest_actionable_wait_age_h"),
              "oldest_failed_unacked_age_h": sig.get("oldest_failed_unacked_age_h"),
              "curated_gap_h": sig.get("curated_gap_h"),
              "quota_hits_24h": sig.get("quota_hits_24h"),
              "review_queues": sig.get("review_queues"),
              "excluded_with_new_messages": sig.get("excluded_with_new_messages"),
              "excluded_new_messages_oldest_age_h":
                  sig.get("excluded_new_messages_oldest_age_h"),
              "reconcile_heartbeat": sig.get("reconcile_heartbeat"),
              "source_states": state.get("source_states")}

    if args.dry_run:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        print("---- message ----"); print(msg)
        return _EXIT[level]

    sent_ok, sent_detail = True, "non-envoyé"
    if notify:
        sent_ok, sent_detail = send_telegram(msg)

    new_state = dict(prev)
    new_state.update({"level": level, "last_eval_at": now,
                      "health_age_min": sig.get("health_age_min"),
                      "notified_backlog_failed": notified_backlog})
    if notify and sent_ok:
        new_state["last_notified_at"] = now
        new_state["recovery_sent"] = is_recovery
        new_state["notified_backlog_failed"] = backlog_failed
        new_state["notified_codes"] = codes
    if level != OK:
        new_state["recovery_sent"] = False
    else:
        new_state["notified_backlog_failed"] = 0
        new_state["notified_codes"] = []
    save_state(args.state_file, new_state)

    report["sent"] = bool(notify and sent_ok); report["sent_detail"] = sent_detail
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return _EXIT[level]


if __name__ == "__main__":
    sys.exit(main())
