#!/usr/bin/env python3
"""Conservation-audit v2 — le bulletin de santé sensoriel nocturne.

Refonte en REGISTRE DE SECTIONS (V3 §3.2 [5]).
La v1 ne couvrait que la digestion (STARVATION/DEAD_LETTER/
PAID_AI_OFF_WITH_BACKLOG). Le chantier « Perception V4 » a fait naître
plusieurs organes de preuve séparés (registre des sources, manifestes de
capture, reconcile-audit, canari mémoire, review-queue) — cette refonte les
AGRÈGE en un seul rapport sectionné, plutôt que de laisser chacun crier dans
son coin sans vue d'ensemble :

    sources         : `app/perception/source_registry.py` — fraîcheur/
                       déclaration par source (OK/MUTE/PENDING_BOOTSTRAP/
                       DECLARED_*). PENDING_BOOTSTRAP (aucune donnée jamais
                       reçue) n'est jamais une violation — absence de preuve,
                       pas preuve de panne (correctif faux-CRIT
                       répétition 2026-07-07).
    capture         : `arac.capture_manifests` — invariant comptable
                       (messages_read == messages_emitted + rejets réels),
                       fraîcheur du dernier manifeste par source captée.
                       (prepurge : cf note BREAK ci-dessous — gap documenté.)
    ingest          : la preuve zéro-perte par source (le rapprochement
                       capture↔ingestion) + échantillon de `raw_messages` récents
                       sans `ingest_receipts` couvrant (trou de preuve) —
                       plancher `received_at >= min(ingest_receipts.
                       created_at)` : un message reçu AVANT l'existence même
                       des reçus ne peut pas en avoir un, ce n'est pas un trou
                       de preuve (correctif faux-WARN du déploiement
                       2026-07-07).
    digestion       : STARVATION (sur backlog ACTIONNABLE, pas juste non-vide ;
                       âge mesuré sur `received_at` — entrée dans ARAC — PAS
                       `msg_created_at`, et GRÂCE aux conversations tout juste
                       (ré)alimentées : `raw_message_revisions reason=healing`
                       récente exclut du décompte de famine — correctif
                       faux-CRIT du déploiement 2026-07-07, cf
                       `derive_digestion_violations`/`_ACTIONABLE_BACKLOG_
                       DETAIL_SQL`), DEAD_LETTER, PAID_AI_OFF_WITH_BACKLOG
                       (3 violations historiques, préservées) +
                       conversations 100% vides sans motif d'exclusion
                       (EMPTY_WITHOUT_REASON) + messages_truncated>0 (viole
                       INV-7, `agents/cortex/pack.py`) + coverage_omitted
                       répété + messages surdimensionnés bloquants + créneaux
                       circadiens « brûlés » RÉCENTS uniquement (spawn_failed/
                       dispose_interrupted hors quota, fenêtre glissante —
                       jamais un artefact vieux d'une semaine rapporté à
                       l'infini) + quota Claude répété + RECEIPT_ATOM_MISMATCH
                       (invariant `agents/cortex/review_queue.py`).
    memoire         : le canari de rappel (une question dont on connaît la
                       réponse, reposée chaque nuit) + les embeddings NULL.
                       ATTENTION : ce dépôt ne livre PAS encore le module
                       qui la calcule — la section rend donc une erreur
                       déclarée, jamais un OK silencieux.
    backups         : `not_yet_wired` EXPLICITE — les vérifications vivent
                       dans les scripts shell d'`ops/`, et aucun collecteur
                       Python ne les agrège encore ici. Le dire est le
                       minimum : une section absente qui rendrait « OK »
                       serait un mensonge sur le filet de sécurité.

Chaque section : `status` (OK/WARN/CRIT, ou `not_yet_wired`) + `violations`
typées (`code`/`severity`/`detail`) + `counters`. Le niveau GLOBAL est le pire
des statuts actifs (`not_yet_wired` n'escalade jamais rien — c'est un aveu de
gap, pas un signal).

BREAK (fail-closed-ET-CRIER, DEUX régimes de panne distincts) :
  1. DB totalement injoignable -> une sonde de connectivité PRÉALABLE
     (`_db_reachable`) échoue -> alerte Telegram + exit 1 IMMÉDIAT, aucune
     section n'est même tentée (c'est le régime « DB down » historique,
     inchangé depuis l'origine).
  2. Un COLLECTEUR PARTICULIER lève APRÈS que la DB s'est révélée joignable
     (bug de code, import cassé, requête invalide sur une table absente...)
     -> SEULE cette section passe `CRIT`/`COLLECTOR_ERROR`, les autres
     sections continuent normalement, une alerte part quand même. Jamais un
     crash qui rend l'audit muet — c'est l'organe de preuve, il ne peut pas
     mourir en silence.

Reclassement des conversations 100% vides (ex-desktop_chat
« no_content=OK silencieux ») : `exclusion_reason` posé -> `EXCLUDED_WITH_
REASON` (consigné, PAS une violation) ; absent -> `EMPTY_WITHOUT_REASON`
(WARN). Tant que les 6 conversations `desktop_chat` vides connues n'ont pas
reçu d'exclusion (`scripts/ops/exclude_conversation.py`, GO opérateur requis),
cet audit CRIE WARN à leur sujet — comportement VOULU, pas un bug de ce WP.

Gap PROSPECTIF documenté (capture/prepurge) : l'âge du plus vieux fichier
source non purgé (garde-fou `claude_code_selfcapture.derive_prepurge_level`)
est un état LOCAL au scanner (exit code du run côté Mac), jamais transmis au
serveur — aucune colonne dédiée sur `arac.capture_manifests` à ce jour. Ce
conservation-audit, lecture-seule côté serveur, ne peut donc PAS le vérifier
tant qu'un champ dédié n'aura pas été ajouté au manifeste : signalé
explicitement dans la section `capture` (`prepurge.status=not_yet_wired`),
jamais fabulé.

Lecture seule partout (DSN readonly, `SET TRANSACTION READ ONLY`). Oneshot
systemd + timer nocturne 03:30 Paris.

Défense en profondeur — pager (Telegram) UNIQUEMENT sur CRIT (correctif du
2026-07-07, bulletin nocturne 01:30 UTC pendant les quiet-hours) :
`WARN`/`OK` sont TOUJOURS calculés et LOGGÉS (le rapport JSON complet part
sur stderr -> journald, inspectable, alimente le cockpit — INCHANGÉ, cf plus
bas dans `main()`), mais ne déclenchent plus d'envoi Telegram. Un bulletin
nocturne doit alerter sur les vrais problèmes (`CRIT`), pas réveiller sur un
`WARN`. `should_page` (fonction PURE, cf plus bas) porte cette décision — le
watchdog 15-min (`app/perception/ingest_watchdog.py`) garde SA PROPRE
logique quiet-hours pour l'alerting réactif, non touchée ici.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

import arac_runtime

STARVATION_HOURS_DEFAULT = 48.0
# --- cadence de page STARVATION ---------
# Preuve (registre) : 5 CRIT nocturnes IDENTIQUES (doyenne 54h→78h→102h→126h
# →150h, +24h/nuit) sans attribution ni delta -> accoutumance : le lecteur
# apprend à ignorer l'alerte, y compris la vraie. Politique : page au 1er
# franchissement ; re-page si l'état S'AGGRAVE (nouvelle conversation affamée,
# OU doyenne qui franchit un bucket de 24h = « +≥24h », 1 créneau circadien
# perdu — delta conservateur du registre) ; sinon la violation est DIGÉRÉE en
# WARN (toujours calculée, loggée, visible cockpit — `should_page` ne page
# que CRIT). Re-page périodique LENTE si état strictement inchangé : 72h = 3
# passes nocturnes — le défaut générique du helper (24h, pensé pour les
# émetteurs 15 min) équivaudrait ICI à la cadence même de l'audit quotidien,
# donc re-crierait chaque nuit exactement comme avant.
STARVATION_REPAGE_HOURS_DEFAULT = 72.0
# Fenêtre « le cortex a-t-il tourné récemment » pour l'attribution de cause
# STARVATION : 26h = cadence quotidienne complète (3 créneaux
# circadiens) + marge de dérive du timer — même raisonnement que la fenêtre
# reconcile.
STARVATION_CAUSE_RUN_WINDOW_HOURS_DEFAULT = 26.0
# --- Drain-aware STARVATION (mission drain phase 2, 2026-07-16) -------------
# Contexte mesuré (drain-diagnostic) : le backlog ancien est en RÉSORPTION
# PLANIFIÉE (~×5 de débit, stock 86% = sessions-géantes) — la doyenne reste
# vieille PENDANT que le drain progresse. L'alerte STARVATION actuelle re-page
# sans distinguer « drain qui progresse » de « drain qui stalle ». Sous flag
# maître `ARAC_STARVATION_DRAIN_AWARE` (défaut OFF = bit-identique) : le
# backlog actionnable est aussi mesuré en kt (kilotokens ~ chars/4/1000, même
# unité que drain-diagnostic.json), persisté dans l'état ; si le delta
# entre deux audits ≤ -SEUIL (env `ARAC_DRAIN_PROGRESS_KT_MIN`, défaut 60 kt/j
# PRO-RATÉ par l'intervalle réel entre audits), la violation est apaisée en
# WARN « drain en cours : -X kt, ETA ~N j » (ETA = backlog/débit, affiché
# borné ≤30 j) ; si le drain STALLE, CRIT comme aujourd'hui (cause dominante
# conservée). Premier audit sans mesure antérieure = comportement actuel
# (aucune fabrication).
DRAIN_PROGRESS_KT_MIN_DEFAULT = 60.0  # kt/jour
DRAIN_ETA_DISPLAY_CAP_DAYS = 30.0
CAPTURE_FRESHNESS_HOURS_DEFAULT = 48.0
RECONCILE_WINDOW_HOURS_DEFAULT = 48.0
RECEIPT_SAMPLE_WINDOW_HOURS_DEFAULT = 24.0
RECEIPT_SAMPLE_LIMIT_DEFAULT = 50
RUN_WINDOW_DAYS_DEFAULT = 7.0
COVERAGE_OMITTED_MIN_DEFAULT = 2
# Aucun défaut : « 8000 » désigne le PREMIER cerveau de la machine.
# L'unité systemd engendrée par le bootstrap pose ARAC_API_URL ; sans
# elle, on ne devine pas — deviner, c'est parler à la mémoire du voisin.
API_BASE_URL_DEFAULT = ""
# Fenêtre de "créneau brûlé" RÉCENT (déploiement 2026-07-07, correctif
# faux-WARN de rodage) : un slot brûlé plus vieux que ça est un artefact
# historique déjà connu, pas un signal actionnable — ne doit pas être
# rapporté indéfiniment sur toute `run_window_days` (défaut 7j).
BURNED_SLOT_RECENT_HOURS_DEFAULT = 48.0

_STATUS_RANK = {"OK": 0, "WARN": 1, "CRIT": 2}


def _env_float(name: str, default: float) -> float:
    try:
        v = float(os.environ.get(name, ""))
        return v if v > 0 else default
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        v = int(os.environ.get(name, ""))
        return v if v > 0 else default
    except ValueError:
        return default


def _starvation_hours() -> float:
    return _env_float("ARAC_CONSERVATION_STARVATION_HOURS", STARVATION_HOURS_DEFAULT)


def _starvation_grace_hours() -> float:
    """Fenêtre de grâce STARVATION — défaut = `starvation_hours` courant
    (dynamique, PAS `STARVATION_HOURS_DEFAULT` figé), surchargeable
    indépendamment via `ARAC_CONSERVATION_STARVATION_GRACE_HOURS`."""
    return _env_float("ARAC_CONSERVATION_STARVATION_GRACE_HOURS", _starvation_hours())


def _burned_slot_recent_hours() -> float:
    return _env_float("ARAC_CONSERVATION_BURNED_SLOT_RECENT_HOURS", BURNED_SLOT_RECENT_HOURS_DEFAULT)


def _starvation_repage_hours() -> float:
    return _env_float("ARAC_CONSERVATION_STARVATION_REPAGE_H", STARVATION_REPAGE_HOURS_DEFAULT)


def _starvation_drain_aware() -> bool:
    """Flag maître drain-aware — env PUR, défaut OFF (= comportement
    bit-identique à l'existant, y compris le fichier state)."""
    return os.environ.get("ARAC_STARVATION_DRAIN_AWARE", "").strip().lower() in (
        "1", "true", "yes", "on")


def _drain_progress_kt_min() -> float:
    """Seuil de progression du drain (kt/JOUR — pro-raté par l'intervalle
    réel entre audits dans `assess_drain_progress`)."""
    return _env_float("ARAC_DRAIN_PROGRESS_KT_MIN", DRAIN_PROGRESS_KT_MIN_DEFAULT)


# État durable anti-accoutumance : fichier state JSON sous var/ du
# repo — même mécanique que `ingest_watchdog` (load_state/save_state PARTAGÉS,
# importés de là — jamais une table DB : l'alerting doit décider même DB
# indisponible, et l'audit est lecture-seule côté DB par doctrine).
CONSERVATION_STATE_FILE_DEFAULT = os.path.join(str(arac_runtime.var_dir()), "conservation_audit_state.json")


def _state_file() -> str:
    return os.environ.get("ARAC_CONSERVATION_STATE", CONSERVATION_STATE_FILE_DEFAULT)


def _capture_freshness_hours() -> float:
    return _env_float("ARAC_CONSERVATION_CAPTURE_FRESHNESS_HOURS", CAPTURE_FRESHNESS_HOURS_DEFAULT)


def _reconcile_window_hours() -> float:
    return _env_float("ARAC_RECONCILE_AUDIT_WINDOW_HOURS", RECONCILE_WINDOW_HOURS_DEFAULT)


def _receipt_sample_window_hours() -> float:
    return _env_float("ARAC_CONSERVATION_RECEIPT_SAMPLE_WINDOW_HOURS", RECEIPT_SAMPLE_WINDOW_HOURS_DEFAULT)


def _receipt_sample_limit() -> int:
    return _env_int("ARAC_CONSERVATION_RECEIPT_SAMPLE_LIMIT", RECEIPT_SAMPLE_LIMIT_DEFAULT)


def _run_window_days() -> float:
    return _env_float("ARAC_CONSERVATION_RUN_WINDOW_DAYS", RUN_WINDOW_DAYS_DEFAULT)


def _coverage_omitted_min() -> int:
    return _env_int("ARAC_CONSERVATION_COVERAGE_OMITTED_MIN", COVERAGE_OMITTED_MIN_DEFAULT)


def _api_base_url() -> str:
    return os.environ.get("ARAC_API_BASE_URL", API_BASE_URL_DEFAULT)


# ---------------------------------------------------------------------------
# Fonctions PURES — statut de section, agrégation, alerte (testables sans DB)
# ---------------------------------------------------------------------------


def section_status_from_violations(violations: list[dict[str, Any]]) -> str:
    """(violations d'une section) -> OK/WARN/CRIT. Fonction PURE."""
    if any(v.get("severity") == "CRIT" for v in violations):
        return "CRIT"
    if violations:
        return "WARN"
    return "OK"


def build_section(
    violations: list[dict[str, Any]],
    *,
    counters: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble une section {status, violations, counters, ...extra}. PURE."""
    sec: dict[str, Any] = {
        "status": section_status_from_violations(violations),
        "violations": violations,
        "counters": counters or {},
    }
    if extra:
        sec.update(extra)
    return sec


def run_section_safely(name: str, builder) -> dict[str, Any]:
    """Exécute `builder()` (un des collecteurs `_section_*`) et convertit
    TOUTE exception en section `CRIT`/`COLLECTOR_ERROR` — BREAK : un
    collecteur cassé (import cassé, requête invalide sur une table
    absente...) ne doit JAMAIS faire taire tout l'audit, seule SA section
    est marquée en échec, les autres continuent normalement. `builder` est
    INJECTABLE (zéro argument) — testable directement avec un fake qui
    lève, aucune DB requise."""
    try:
        return builder()
    except Exception as e:  # noqa: BLE001 — cf docstring
        return {
            "status": "CRIT",
            "violations": [{
                "code": "COLLECTOR_ERROR",
                "severity": "CRIT",
                "detail": (
                    f"section {name} : collecteur en échec "
                    f"({type(e).__name__}: {e}) — les autres sections "
                    f"restent évaluées normalement"
                ),
            }],
            "counters": {},
        }


def build_backups_section() -> dict[str, Any]:
    """Section `backups` — hook `not_yet_wired` EXPLICITE : les contrôles
    réels vivent dans les scripts shell d'`ops/`, nommés ici pour que le
    rapport reste complet même sur une section non câblée."""
    return {
        "status": "not_yet_wired",
        "violations": [],
        "counters": {},
        "reason": (
            "les vérifications de sauvegarde (fraîcheur du dump, contrôle de "
            "la table des matières, rejeu de restauration, copie hors site) "
            "vivent dans des scripts shell autonomes ; aucun collecteur "
            "Python ne les agrège encore ici : ops/backup.sh, "
            "ops/backup_toc_check.sh, ops/backup_offsite.sh, "
            "ops/restore_verify.sh, ops/restore_guard.sh"
        ),
    }


def build_report(sections: dict[str, dict[str, Any]], *, generated_at: str) -> dict[str, Any]:
    """Assemble le rapport complet {level, violations, sections}. PURE.

    Le niveau global est le pire des statuts OK/WARN/CRIT parmi les
    sections ; un statut `not_yet_wired` (ou tout autre statut non
    OK/WARN/CRIT) n'escalade JAMAIS le niveau global — c'est un aveu de
    gap documenté, pas un signal d'alerte.
    """
    all_violations: list[dict[str, Any]] = []
    for name, sec in sections.items():
        for v in sec.get("violations", []):
            all_violations.append({**v, "section": name})

    level = "OK"
    for sec in sections.values():
        status = sec.get("status", "OK")
        if status in _STATUS_RANK and _STATUS_RANK[status] > _STATUS_RANK[level]:
            level = status

    return {
        "event": "conservation.audit",
        "generated_at": generated_at,
        "level": level,
        "violations_count": len(all_violations),
        "violations": all_violations,
        "sections": sections,
    }


def should_page(level: str) -> bool:
    """(niveau du rapport) -> faut-il PAGER (Telegram) ? Fonction PURE.

    Défense en profondeur pour le bulletin nocturne (cf docstring module) :
    UNIQUEMENT `CRIT` page. `WARN` et `OK` sont toujours calculés/loggés
    (rapport JSON complet sur stderr, cf `main()`) mais ne réveillent
    JAMAIS personne — un WARN nocturne mérite d'être VU au matin, pas de
    sonner à 01:30 UTC en pleines quiet-hours."""
    return level == "CRIT"


_ALERT_DETAIL_CAP = 10


def format_alert(report: dict[str, Any]) -> str:
    """Message Telegram lisible depuis le rapport sectionné. PURE.

    Un rapport à 0 violation produit un message de bulletin lisible (« tout
    va bien »), jamais une chaîne vide ou un crash — cf BREAK docstring
    module."""
    count = report.get("violations_count", 0)
    if count == 0:
        return f"✅ ARAC conservation-audit v2 : 0 violation — niveau {report.get('level', 'OK')}"
    lines = [f"🧠⚠️ ARAC conservation-audit v2 : {count} violation(s) — niveau {report.get('level')}"]
    violations = report.get("violations", [])
    for v in violations[:_ALERT_DETAIL_CAP]:
        lines.append(f"• [{v.get('section', '?')}/{v.get('code', '?')}] {v.get('detail', '')}")
    if count > _ALERT_DETAIL_CAP:
        lines.append(f"… +{count - _ALERT_DETAIL_CAP} autres")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Fonctions PURES — dérivation par section (testables sans DB, cf tests)
# ---------------------------------------------------------------------------


def derive_sources_violations(source_report: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """(rapport `source_registry.build_source_report`) -> violations `SOURCE_
    MUTE` (WARN, capteur démontrablement mort — une donnée a déjà été reçue
    puis s'est tarie). `DECLARED_EXCLUDED`/`DECLARED_UNCOVERED`/`OK`/
    `PENDING_BOOTSTRAP` ne sont JAMAIS des violations (motif déjà consigné
    au registre, fraîcheur normale, ou absence de preuve — pas preuve de
    panne, cf `source_registry` docstring) — mais restent visibles dans
    `counters`/`extra` de la section."""
    v: list[dict[str, Any]] = []
    for key, info in source_report.items():
        if info.get("status") == "MUTE":
            lag = info.get("lag_minutes")
            lag_txt = f"{lag:.0f} min" if lag is not None else "jamais"
            thr = info.get("expected_max_lag_minutes")
            thr_txt = f"{thr:.0f} min" if thr is not None else "?"
            v.append({
                "code": "SOURCE_MUTE",
                "severity": "WARN",
                "detail": (
                    f"source {key} : muette depuis {lag_txt} (seuil {thr_txt}, "
                    f"machine_active={info.get('machine_active')})"
                ),
            })
    return v


def derive_capture_violations(
    manifests: list[dict[str, Any]],
    *,
    freshness_hours: float,
    check_invariant,
) -> list[dict[str, Any]]:
    """(liste par source captée `{source_key, has_manifest, manifest?,
    age_hours?}`) -> violations `MANIFEST_MISSING`/`MANIFEST_STALE`/
    `MANIFEST_INVARIANT_BROKEN`. `check_invariant` est INJECTABLE (fonction
    PURE `jsonl_capture_lib.check_manifest_invariant` en production, un fake
    en test) — cette fonction reste PURE, aucun import ici."""
    v: list[dict[str, Any]] = []
    for m in manifests:
        key = m["source_key"]
        if not m.get("has_manifest"):
            v.append({
                "code": "MANIFEST_MISSING",
                "severity": "WARN",
                "detail": (
                    f"source {key} : PENDING bootstrap — aucun manifeste de capture "
                    f"jamais posté (capture non démarrée, ou self-capture serveur pas "
                    f"encore livré — cf WP-A). Absence de preuve, pas preuve de panne "
                    f"(jamais CRIT pour ce seul motif)"
                ),
            })
            continue
        age_h = m.get("age_hours")
        if age_h is None or age_h > freshness_hours:
            age_txt = f"{age_h:.0f}" if age_h is not None else "?"
            v.append({
                "code": "MANIFEST_STALE",
                "severity": "WARN",
                "detail": (
                    f"source {key} : dernier manifeste il y a {age_txt} h "
                    f"(> {freshness_hours:.0f} h)"
                ),
            })
        manifest = m.get("manifest") or {}
        if not check_invariant(manifest):
            v.append({
                "code": "MANIFEST_INVARIANT_BROKEN",
                "severity": "CRIT",
                "detail": (
                    f"source {key} : messages_read != messages_emitted + rejets "
                    f"réels (dernier manifeste {manifest.get('run_started_at')}) "
                    f"— comptes de capture incohérents"
                ),
            })
    return v


def build_capture_prepurge_hook() -> dict[str, Any]:
    """Sous-item `not_yet_wired` EXPLICITE de la section capture — cf note
    BREAK du docstring module. N'entre JAMAIS dans les violations (ce n'est
    pas un signal, c'est un gap documenté)."""
    return {
        "status": "not_yet_wired",
        "reason": (
            "l'âge du plus vieux fichier source non purgé (garde-fou "
            "claude_code_selfcapture.derive_prepurge_level / EXIT_PREPURGE_WARN) "
            "est un état LOCAL au scanner (exit code du run côté Mac), jamais "
            "transmis au serveur — aucune colonne dédiée sur "
            "arac.capture_manifests à ce jour. Ce conservation-audit, "
            "lecture-seule côté serveur, ne peut donc PAS vérifier ce signal "
            "tant qu'un champ dédié n'a pas été ajouté au manifeste."
        ),
    }


def derive_receipt_coverage_violations(uncovered_sample: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """(échantillon de raw_messages récents sans ingest_receipts couvrant)
    -> violations `RECEIPT_COVERAGE_GAP` (WARN — trou de PREUVE, pas
    forcément une perte réelle, cf `reconcile_audit` pour la preuve
    exhaustive par source)."""
    v: list[dict[str, Any]] = []
    for u in uncovered_sample:
        v.append({
            "code": "RECEIPT_COVERAGE_GAP",
            "severity": "WARN",
            "detail": (
                f"message {u['message_id']} ({u['source_type']}@{u['node_id']}, "
                f"reçu {u['received_at']}) sans ingest_receipts couvrant (±1h) — "
                f"trou de preuve, pas forcément une perte (échantillon)"
            ),
        })
    return v


def derive_empty_conversation_violations(
    empties: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(conversations 100% vides — aucun message non-vide, quel que soit le
    curseur) -> (violations, consignées). point 3 : `exclusion_reason`
    posé -> consignée (`EXCLUDED_WITH_REASON`, pas une violation) ; absent ->
    violation `EMPTY_WITHOUT_REASON` (WARN) — fini le « no_content=OK
    silencieux »."""
    violations: list[dict[str, Any]] = []
    consigned: list[dict[str, Any]] = []
    for c in empties:
        uid, source_type = c.get("conversation_uid"), c.get("source_type")
        if c.get("exclusion_reason"):
            consigned.append({
                "code": "EXCLUDED_WITH_REASON",
                "conversation_uid": uid,
                "source_type": source_type,
                "exclusion_reason": c["exclusion_reason"],
            })
        else:
            violations.append({
                "code": "EMPTY_WITHOUT_REASON",
                "severity": "WARN",
                "detail": (
                    f"conversation {uid} ({source_type}) : 100% vide (aucun "
                    f"message non-vide) SANS exclusion_reason — exclure via "
                    f"scripts/ops/exclude_conversation.py ou expliquer pourquoi "
                    f"elle reste en attente"
                ),
            })
    return violations, consigned


# ---------------------------------------------------------------------------
# — STARVATION actionnable : attribution de cause + page-sur-changement
# ---------------------------------------------------------------------------


def derive_starvation_cause(
    sig: dict[str, Any],
    *,
    quota_repeat_min: int,
    run_recent_hours: float = STARVATION_CAUSE_RUN_WINDOW_HOURS_DEFAULT,
) -> tuple[str, str]:
    """(code, texte) — LA cause mécanique DOMINANTE de la famine, MESURÉE au
    moment de l'émission (exigence architecte) : jamais un libellé
    générique. Fonction PURE (tout vient de `sig`). Branches, par ordre de
    priorité mécanique (la plus en AMONT du pipeline gagne — inutile de
    parler d'ordonnancement de pack si aucun spawn n'est même possible) :

      ia-desarmee   : paid_ai_enabled=false — aucun spawn possible, quelle
                      que soit la file (le frein n°2 de la doctrine coût).
      quota         : quota Claude épuisé de façon répétée sur la fenêtre —
                      le budget meurt avant la file.
      aucun-cycle   : AUCUN run cortex (quel que soit son statut) depuis
                      `run_recent_hours` — timer/cortex en panne, la famine
                      est un symptôme, pas la maladie.
      cycles-brules : des runs récents existent mais AUCUN 'done' — les
                      créneaux brûlent (spawn_failed/quarantined/
                      dispose_interrupted) sans rien digérer.
      retry-parked  : ≥50% des conversations affamées portent retry_count>0
                      — elles SONT re-présentées puis omises/échouées cycle
                      après cycle (backoff), pas un manque de
                      cycles.
      budget-pack   : des cycles réussissent ET les affamées n'ont pas
                      d'échec propre -> le débit du pack (budget borné, tri
                      oldest-first, tête de file monopolisée) est simplement
                      inférieur à l'inflow — la cause par
                      défaut MESURÉE (cycles 'done' comptés), pas une
                      supposition.

    Note périmètre : gate-quiet-hours / min_new_msgs / files-vides (les
    autres causes canoniques d'un PENDING inexpliqué) ne peuvent PAS être la
    cause d'une famine ACTIONNABLE — une conversation actionnable a par
    définition déjà PASSÉ le gate ; ces causes-là appartiennent au panneau
    cockpit « états de conversation » (P2), pas à cette alerte."""
    if sig.get("paid_ai_enabled") is False:
        return ("ia-desarmee",
                "IA payante DÉSARMÉE (arac_config.paid_ai_enabled=false) — aucun "
                "spawn possible tant que non ré-armée (RUNBOOK-SOBER-BRAIN §3)")
    quota_hits = int(sig.get("quota_hits_window") or 0)
    if quota_hits >= quota_repeat_min:
        return ("quota",
                f"quota Claude épuisé {quota_hits}× sur la fenêtre — le budget "
                f"meurt avant la file (reprise auto, mais la file diverge)")
    runs = sig.get("run_receipts_window", [])
    recent = [r for r in runs
              if r.get("age_hours") is not None and r["age_hours"] <= run_recent_hours]
    if not recent:
        return ("aucun-cycle",
                f"AUCUN run cortex depuis {run_recent_hours:.0f}h (timer ou cortex "
                f"en panne — la famine est le symptôme, pas la maladie)")
    done = [r for r in recent if r.get("status") == "done"]
    if not done:
        statuses = ", ".join(sorted({str(r.get("status")) for r in recent}))
        return ("cycles-brules",
                f"{len(recent)} run(s) cortex sur {run_recent_hours:.0f}h, 0 'done' "
                f"(statuts : {statuses}) — les créneaux brûlent sans digérer")
    starving = [r for r in sig.get("actionable_backlog_detail", [])
                if not r.get("healed_recently")]
    with_retry = [r for r in starving if int(r.get("retry_count") or 0) > 0]
    if starving and len(with_retry) * 2 >= len(starving):
        return ("retry-parked",
                f"{len(with_retry)}/{len(starving)} conversation(s) affamée(s) en "
                f"échec/omission répété (retry_count>0, backoff —) : "
                f"re-présentées puis non digérées, pas un manque de cycles")
    return ("budget-pack",
            f"{len(done)} cycle(s) 'done' sur {run_recent_hours:.0f}h ET la file ne "
            f"draine pas — débit du pack (budget borné, tri oldest-first : tête de "
            f"file monopolisée) < inflow")


def derive_starvation_page(
    prev_entry: dict[str, Any] | None,
    *,
    uids: list[str],
    oldest_age_h: float | None,
    now_epoch: float,
    repage_hours: float = STARVATION_REPAGE_HOURS_DEFAULT,
) -> tuple[bool, str, dict[str, Any]]:
    """(page, why, new_entry) — décision de page STARVATION. PURE.

    S'appuie sur le helper PARTAGÉ `ingest_watchdog.page_on_state_change`
    (pattern anti-accoutumance V5) avec un fingerprint MONOTONE-aggravation,
    conforme au registre (« re-pager seulement si la doyenne croît de ≥24h OU
    si de nouvelles convs entrent ») :
      • uids   : UNION avec les uids déjà pagés — une conversation qui DRAINE
                 (disparaît) ne change pas le fingerprint (une amélioration
                 partielle n'est pas une alerte) ; une NOUVELLE conversation
                 affamée le change (aggravation -> page).
      • bucket : floor(doyenne/24h), MAX historique — la doyenne qui grimpe
                 d'un bucket (+≥24h = 1 créneau circadien perdu) page ; une
                 doyenne qui baisse (drainage partiel) ne page pas.
    `oldest_age_h is None` (jamais mesuré, fail-closed en amont) -> bucket -1
    (état distinct, page au premier passage). L'entrée retournée porte aussi
    `last_seen_oldest_h` (delta « vs veille » du message, mis à jour à CHAQUE
    run, pagé ou non)."""
    from app.perception import ingest_watchdog as iw  # helper partagé (scripts/ingest, sys.path posé en tête de module)

    prev = dict(prev_entry or {})
    known_uids = set(prev.get("uids") or [])
    merged_uids = sorted(known_uids | set(uids))
    bucket_now = -1 if oldest_age_h is None else int(oldest_age_h // 24.0)
    prev_bucket = prev.get("bucket")
    bucket = bucket_now if prev_bucket is None else max(bucket_now, int(prev_bucket))
    fingerprint = f"b{bucket}|{','.join(merged_uids)}"

    page, why, entry = iw.page_on_state_change(
        prev, fingerprint=fingerprint, now=now_epoch,
        repage_interval_s=repage_hours * 3600.0)
    # Motif HUMAIN précis pour les deux aggravations directionnelles (le
    # helper générique ne connaît que « fingerprint a changé »).
    if page and prev.get("fingerprint") is not None:
        news = sorted(set(uids) - known_uids)
        if news:
            shown = ", ".join(u[:8] for u in news[:3])
            more = "…" if len(news) > 3 else ""
            why = f"{len(news)} NOUVELLE(S) conversation(s) affamée(s) ({shown}{more})"
        elif prev_bucket is not None and bucket > int(prev_bucket):
            why = f"doyenne +≥24h (bucket {int(prev_bucket)}j -> {bucket}j) — 1+ créneau circadien perdu"
    entry.update({"uids": merged_uids, "bucket": bucket,
                  "last_seen_oldest_h": oldest_age_h,
                  "paged_this_run": page})
    return page, why, entry


def assess_drain_progress(
    prev_entry: dict[str, Any] | None,
    *,
    backlog_kt: float | None,
    now_epoch: float,
    progress_kt_min_per_day: float = DRAIN_PROGRESS_KT_MIN_DEFAULT,
) -> dict[str, Any] | None:
    """(mesure de progression du drain) — fonction PURE, drain-aware.

    Compare le backlog actionnable en kt (chars/4/1000, unité de
    drain-diagnostic.json) à la mesure PERSISTÉE du dernier audit
    (`backlog_kt`/`backlog_kt_at` dans l'entrée d'état). Retourne None
    (= aucune conclusion, comportement actuel inchangé — jamais de
    fabrication) si : pas de mesure courante, pas de mesure antérieure, ou
    intervalle non positif (horloge/état incohérent, fail-closed).

    Sinon : `progressing` = delta ≤ -(seuil kt/jour PRO-RATÉ par
    l'intervalle réel entre audits) ; `eta_days` = backlog / débit mesuré
    (kt/jour) quand le backlog décroît."""
    prev = prev_entry or {}
    prev_kt, prev_at = prev.get("backlog_kt"), prev.get("backlog_kt_at")
    if backlog_kt is None or prev_kt is None or prev_at is None:
        return None
    interval_days = (now_epoch - float(prev_at)) / 86400.0
    if interval_days <= 0:
        return None
    delta_kt = float(backlog_kt) - float(prev_kt)
    threshold_kt = progress_kt_min_per_day * interval_days
    progressing = delta_kt <= -threshold_kt
    rate_kt_day = (-delta_kt / interval_days) if delta_kt < 0 else 0.0
    eta_days = (float(backlog_kt) / rate_kt_day) if rate_kt_day > 0 else None
    return {"delta_kt": delta_kt, "interval_days": interval_days,
            "threshold_kt": threshold_kt, "progressing": progressing,
            "rate_kt_per_day": rate_kt_day, "eta_days": eta_days}


def format_drain_eta(eta_days: float | None, *, cap_days: float = DRAIN_ETA_DISPLAY_CAP_DAYS) -> str:
    """Affichage de l'ETA de drain, borné ≤`cap_days` (« ~30+ j » au-delà,
    jamais un chiffre astronomique anxiogène). PURE."""
    if eta_days is None:
        return "?"
    if eta_days > cap_days:
        return f"~{cap_days:.0f}+ j"
    return f"~{eta_days:.0f} j"


def mark_reconcile_informational(violations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """autorité de PAGE unique = le
    reconcile-audit dédié (`scripts/ops/reconcile_audit.py`, timer 01:35Z).
    La section ingest de CE conservation-audit reproduit la même vérification
    5 min plus tôt (01:30) — le même événement était ÉMIS DEUX FOIS. Fonction
    PURE : les violations RECONCILE_* restent calculées/visibles (rapport,
    cockpit) mais leur sévérité est PLAFONNÉE à WARN (non-paging, cf
    `should_page` : seul CRIT page) et marquée informationnelle — ce
    conservation-audit ne peut structurellement plus pager pour un code
    RECONCILE_*. Les autres codes (RECEIPT_COVERAGE_GAP…) sont INTOUCHÉS.
    Aucun créneau sans émetteur : reconcile-audit continue de pager, lui."""
    out: list[dict[str, Any]] = []
    for v in violations:
        if str(v.get("code", "")).startswith("RECONCILE_"):
            v = {**v,
                 "severity": "WARN" if v.get("severity") == "CRIT" else v.get("severity", "WARN"),
                 "paging_authority": "reconcile-audit",
                 "detail": (f"{v.get('detail', '')} [informationnel — émetteur de "
                            f"page : reconcile-audit]")}
        out.append(v)
    return out


def derive_digestion_violations(
    sig: dict[str, Any],
    *,
    starvation_hours: float,
    coverage_omitted_min: int,
    quota_repeat_min: int,
    burned_slot_recent_hours: float,
    check_receipt_atom_invariant,
    starvation_prev: dict[str, Any] | None = None,
    now_epoch: float | None = None,
    starvation_repage_hours: float = STARVATION_REPAGE_HOURS_DEFAULT,
    drain_aware: bool = False,
    drain_progress_kt_min: float = DRAIN_PROGRESS_KT_MIN_DEFAULT,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Assemble TOUTES les violations de la section digestion. Fonction
    PURE : `sig` est déjà collecté, `check_receipt_atom_invariant` est
    INJECTABLE (`agents.cortex.review_queue.check_receipt_atom_invariant`
    en production, un fake en test).

    `drain_aware=False` (défaut, flag `ARAC_STARVATION_DRAIN_AWARE`) =
    comportement STRICTEMENT identique à l'existant (aucune clé kt ajoutée
    à l'état, aucune mention drain dans les messages).

    Retourne `(violations, consigned)` — `consigned` porte les conversations
    100% vides déjà exclues (`EXCLUDED_WITH_REASON`, informationnel)."""
    v: list[dict[str, Any]] = []

    # --- STARVATION (historique, réassise sur le backlog ACTIONNABLE
    #     — pas juste « non vide » : exclut désormais aussi les conversations
    #     en backoff (next_retry_at futur), cf docstring module).
    #
    #     Correctif faux-CRIT du déploiement 2026-07-07 : `oldest_
    #     actionable_age_h` est désormais mesuré côté collecteur sur
    #     `received_at` (entrée dans ARAC), PAS `msg_created_at` (date du
    #     CONTENU, qui peut être un healing/backfill d'avril tout juste
    #     restauré) — ET le collecteur a DÉJÀ retiré du calcul les
    #     conversations graciées (`raw_message_revisions reason='healing'`
    #     récente) via `actionable_ungraced_count`. `actionable_backlog`
    #     (total, y compris graciées) reste utilisé pour PAID_AI_OFF_WITH_
    #     BACKLOG ci-dessous — désarmer l'IA avec DE LA MATIÈRE qui attend
    #     reste un vrai signal même si cette matière est fraîche. `ungraced`
    #     retombe sur `actionable` si absent de `sig` (compat ascendante :
    #     un appelant qui ne connaît pas encore la grâce se comporte comme
    #     avant, rien n'est jamais gracié par défaut).
    actionable = int(sig.get("actionable_backlog") or 0)
    oldest = sig.get("oldest_actionable_age_h")
    ungraced = int(sig.get("actionable_ungraced_count", actionable) or 0)
    if actionable > 0 and ungraced > 0 and (oldest is None or oldest >= starvation_hours):
        age_txt = f"{oldest:.0f}" if oldest is not None else "jamais mesuré"

        # --- enrichissement (attribution + delta) + cadence de page.
        # Le CRIT nocturne répété à l'identique 5 nuits (mêmes comptes, +24h)
        # sans top-offenders ni cause = accoutumance garantie. Désormais :
        # top-3 doyennes (uid8 — jamais de PII, ce sont des uuid de convs),
        # breakdown par source, delta doyenne vs veille, et LA cause
        # mécanique dominante mesurée (cf derive_starvation_cause).
        starving = [r for r in sig.get("actionable_backlog_detail", [])
                    if not r.get("healed_recently")]
        parts: list[str] = []
        if starving:
            ranked = sorted(starving, key=lambda r: (r.get("age_h") is None, -(r.get("age_h") or 0)))
            top = ", ".join(
                f"{str(r.get('conversation_uid') or '?')[:8]}={r['age_h']:.0f}h"
                if r.get("age_h") is not None
                else f"{str(r.get('conversation_uid') or '?')[:8]}=?h"
                for r in ranked[:3])
            parts.append(f"top-3 : {top}")
            by_src: dict[str, int] = {}
            for r in starving:
                by_src[str(r.get("source_type") or "?")] = by_src.get(str(r.get("source_type") or "?"), 0) + 1
            parts.append("par source : " + ", ".join(
                f"{k}={n}" for k, n in sorted(by_src.items(), key=lambda kv: -kv[1])))
        prev_seen = (starvation_prev or {}).get("last_seen_oldest_h")
        if oldest is not None and prev_seen is not None:
            parts.append(f"Δ doyenne vs veille : {oldest - float(prev_seen):+.0f}h")
        cause_code, cause_txt = derive_starvation_cause(sig, quota_repeat_min=quota_repeat_min)
        parts.append(f"cause dominante [{cause_code}] : {cause_txt}")

        now_e = time.time() if now_epoch is None else now_epoch
        page, page_why, state_entry = derive_starvation_page(
            starvation_prev,
            uids=[str(r.get("conversation_uid") or "?") for r in starving],
            oldest_age_h=oldest, now_epoch=now_e,
            repage_hours=starvation_repage_hours)

        # --- Drain-aware (flag maître, défaut OFF = bit-identique) ----------
        # Un backlog ANCIEN dont le drain PROGRESSE (delta kt ≤ -seuil
        # pro-raté) n'est pas une panique : WARN explicite avec ETA, jamais
        # de page — et l'entrée d'état reste « non pagée » (fingerprint/
        # last_paged_at antérieurs conservés) pour qu'un STALL ultérieur
        # re-déclenche le page normalement. Un drain qui STALLE = CRIT comme
        # aujourd'hui (cause dominante conservée), le stall est nommé.
        backlog_kt = sig.get("actionable_backlog_kt")
        drain = (assess_drain_progress(
            starvation_prev, backlog_kt=backlog_kt, now_epoch=now_e,
            progress_kt_min_per_day=drain_progress_kt_min)
            if drain_aware else None)
        if drain is not None and drain["progressing"]:
            parts.append(
                f"drain en cours : {drain['delta_kt']:.0f} kt depuis le dernier "
                f"audit ({drain['interval_days']:.1f} j), "
                f"ETA {format_drain_eta(drain['eta_days'])}")
            page = False
            prev_d = dict(starvation_prev or {})
            state_entry["fingerprint"] = prev_d.get("fingerprint")
            state_entry["last_paged_at"] = prev_d.get("last_paged_at")
            state_entry["paged_this_run"] = False
            cadence_txt = ("digest WARN (non-paging) : drain en cours "
                           "(drain-aware, progression ≥ seuil)")
        else:
            if drain is not None:
                parts.append(
                    f"drain STALLE : {drain['delta_kt']:+.0f} kt depuis le "
                    f"dernier audit ({drain['interval_days']:.1f} j, progrès "
                    f"requis ≥{drain['threshold_kt']:.0f} kt)")
            cadence_txt = (f"page : {page_why}" if page
                           else f"digest WARN (non-paging) : {page_why}")
        if drain_aware and backlog_kt is not None:
            # Mesure persistée À CHAQUE audit (pagé ou non) — c'est elle qui
            # rend le delta du prochain audit calculable. Jamais écrite
            # flag OFF (bit-identique, y compris le fichier state).
            state_entry["backlog_kt"] = float(backlog_kt)
            state_entry["backlog_kt_at"] = now_e

        v.append({
            "code": "STARVATION",
            # CRIT (page) uniquement sur changement d'état / re-page
            # lente ; état strictement inchangé -> WARN (digéré : calculé,
            # loggé, visible cockpit — `should_page` ne page que CRIT).
            "severity": "CRIT" if page else "WARN",
            "detail": (
                f"{ungraced} conversation(s) ACTIONNABLE(S) non graciée(s) en "
                f"attente (sur {actionable} au total), la plus ancienne depuis "
                f"{age_txt} h (> {starvation_hours:.0f} h, mesuré sur "
                f"received_at) — backlog réellement éligible au gate curateur, "
                f"pas du contenu vide ou tout juste (ré)alimenté qui traîne — "
                + " ; ".join(parts) + f" — {cadence_txt}"
            ),
            "starvation_state": state_entry,
        })

    # --- DEAD_LETTER (historique, inchangé) --------------------------
    for dl in sig.get("dead_letters", []):
        v.append({
            "code": "DEAD_LETTER",
            "severity": "CRIT",
            "detail": (
                f"conversation {dl['conversation_uid']} : retry épuisé "
                f"({dl['retry_count']}), dernière erreur : "
                f"{dl['last_error'] or 'n/a'} — acquitter (acked) ou corriger"
            ),
        })

    # --- PAID_AI_OFF_WITH_BACKLOG (historique, inchangé) -------------
    if actionable > 0 and sig.get("paid_ai_enabled") is False:
        v.append({
            "code": "PAID_AI_OFF_WITH_BACKLOG",
            "severity": "CRIT",
            "detail": (
                "de la matière ACTIONNABLE attend ET l'IA payante est "
                "DÉSARMÉE (arac_config.paid_ai_enabled=false) — décrochage "
                "silencieux probable : armer (RUNBOOK-SOBER-BRAIN §3) ou "
                "acquitter"
            ),
        })

    # --- conversations 100% vides ---------------------------
    empty_v, consigned = derive_empty_conversation_violations(sig.get("empty_conversations", []))
    v.extend(empty_v)

    runs = sig.get("run_receipts_window", [])

    # --- messages_truncated>0 (viole INV-7, agents/cortex/pack.py) ---------
    for r in runs:
        if int(r.get("messages_truncated") or 0) > 0:
            v.append({
                "code": "MESSAGES_TRUNCATED",
                "severity": "CRIT",
                "detail": (
                    f"run {r['slot_key']} : {r['messages_truncated']} message(s) "
                    f"tronqué(s) avant présentation — viole l'invariant INV-7 "
                    f"(jamais de troncature de contexte, cf agents/cortex/pack.py)"
                ),
            })

    # --- coverage_omitted répété ("fuite de perception", 0027 docstring) ---
    omitted_runs = [r for r in runs if int(r.get("coverage_omitted") or 0) > 0]
    if len(omitted_runs) >= coverage_omitted_min:
        v.append({
            "code": "COVERAGE_OMITTED",
            "severity": "WARN",
            "detail": (
                f"{len(omitted_runs)} run(s) avec coverage_omitted>0 sur la "
                f"fenêtre (seuil {coverage_omitted_min}) — fuite de perception "
                f"répétée (cf arac.digestion_review_queue, "
                f"drop_reason=coverage_omitted)"
            ),
        })

    # --- messages surdimensionnés bloquants --------------------------------
    oversized_runs = [r for r in runs if r.get("oversized_messages")]
    if oversized_runs:
        total = sum(len(r["oversized_messages"]) for r in oversized_runs)
        v.append({
            "code": "OVERSIZED_BLOCKING",
            "severity": "WARN",
            "detail": (
                f"{total} message(s) surdimensionné(s) bloquant(s) sur "
                f"{len(oversized_runs)} run(s) — curseur(s) gelé(s), voir "
                f"arac.digestion_review_queue (drop_reason=oversized_message)"
            ),
        })

    # --- créneaux circadiens "brûlés" (hors quota, cf check séparé) --------
    # Correctif faux-WARN du déploiement 2026-07-07 : ne compter que les
    # slots brûlés RÉCENTS (`age_hours <= burned_slot_recent_hours`, calculé
    # côté collecteur sur `started_at`) — un artefact vieux d'une semaine
    # (ex. `manual@2026-07-03T17:38`) ne doit pas être rapporté à l'infini
    # sur toute la fenêtre `run_window_days`. `age_hours` absent (collecteur
    # historique/test qui ne le fournit pas) -> fail-closed, traité comme
    # récent (jamais un silence).
    burned = [r for r in runs
              if r.get("status") in ("spawn_failed", "dispose_interrupted")
              and r.get("stop_reason") != "spawn:quota"
              and (r.get("age_hours") is None or r["age_hours"] <= burned_slot_recent_hours)]
    if burned:
        keys = ", ".join(r["slot_key"] for r in burned[:5])
        suffix = "…" if len(burned) > 5 else ""
        v.append({
            "code": "BURNED_SLOT",
            "severity": "WARN",
            "detail": (
                f"{len(burned)} créneau(x) circadien(s) consommé(s) sans "
                f"résultat exploitable ({keys}{suffix})"
            ),
        })

    # --- quota Claude répété (dégradation ATTENDUE, pas un bug) ------------
    quota_hits = int(sig.get("quota_hits_window") or 0)
    if quota_hits >= quota_repeat_min:
        v.append({
            "code": "QUOTA_REPEATED",
            "severity": "WARN",
            "detail": (
                f"quota Claude atteint {quota_hits}x sur la fenêtre "
                f"(seuil {quota_repeat_min}) — dégradation attendue, pas un "
                f"bug (reprise au prochain créneau)"
            ),
        })

    # --- RECEIPT_ATOM_MISMATCH (invariant review_queue, runs 'done') -------
    atoms_by_run = sig.get("atoms_in_db_by_run", {})
    for r in runs:
        if r.get("status") != "done":
            continue
        atoms_created = int(r.get("atoms_created") or 0)
        atoms_superseded = int(r.get("atoms_superseded") or 0)
        atoms_in_db = int(atoms_by_run.get(r["slot_key"], 0))
        ok, ecart = check_receipt_atom_invariant(
            atoms_in_db=atoms_in_db, atoms_created=atoms_created,
            atoms_superseded=atoms_superseded)
        if not ok:
            v.append({
                "code": "RECEIPT_ATOM_MISMATCH",
                "severity": "CRIT",
                "detail": (
                    f"run {r['slot_key']} : écart {ecart:+d} entre le reçu "
                    f"(created={atoms_created}+superseded={atoms_superseded}) "
                    f"et memory_atoms réel ({atoms_in_db}) — invariant "
                    f"receipts<->atomes rompu (cf agents/cortex/review_queue)"
                ),
            })

    return v, consigned


# ---------------------------------------------------------------------------
# I/O — collecteurs par section (lecture seule, imports PARESSEUX)
# ---------------------------------------------------------------------------


_EMPTY_CONVERSATIONS_SQL = (
    "SELECT c.conversation_uid, c.source_type, c.exclusion_reason "
    "FROM arac.conversations c "
    "LEFT JOIN arac.raw_messages m ON m.conversation_id = c.id "
    "GROUP BY c.id, c.conversation_uid, c.source_type, c.exclusion_reason "
    "HAVING count(*) FILTER (WHERE btrim(m.content) <> '') = 0"
)

_RUN_RECEIPTS_WINDOW_SQL = (
    "SELECT slot_key, status, stop_reason, messages_truncated, coverage_omitted, "
    "  oversized_messages, atoms_created, atoms_superseded, "
    "  round(EXTRACT(EPOCH FROM (now() - started_at)) / 3600.0, 1) AS age_hours "
    "FROM arac.run_receipts "
    "WHERE started_at >= now() - interval '1 day' * %(window_days)s "
    "ORDER BY started_at DESC"
)

# Détail PAR CONVERSATION du backlog ACTIONNABLE (déploiement
# 2026-07-07, correctif faux-CRIT STARVATION) : reproduit le MÊME prédicat
# d'éligibilité que `ingest_watchdog._ACTIONABLE_BACKLOG_SQL` (réutilise ses
# `_gate_params()` — mêmes seuils env que le gate curateur réel, aucune
# divergence de seuil introduite ici) mais projette PAR CONVERSATION plutôt
# que l'agrégat seul, pour deux raisons que l'agrégat ne peut pas fournir :
#   1. l'âge est mesuré sur `received_at` (entrée dans ARAC), PAS
#      `COALESCE(msg_created_at, received_at)` — un healing/backfill restaure
#      un CONTENU ancien (msg_created_at d'avril) sans changer `received_at`
#      (append-only, healing ne touche jamais cette colonne, cf
#      `scripts/ops/heal_empty_messages.py`) ; mesurer sur received_at rend
#      automatiquement "fraîche" toute conversation dont les messages
#      viennent d'ENTRER dans ARAC (self-capture backfill), sans code de
#      grâce dédié — la conversation ne peut PAS pousser l'âge max au-delà du
#      seuil de famine si elle vient d'arriver.
#   2. `healed_recently` (EXISTS sur `raw_message_revisions reason='healing'`
#      dans la fenêtre de grâce) identifie les conversations dont le contenu
#      restauré a un `received_at` ANCIEN malgré tout (la row existait déjà,
#      vide, avant le healing) — CES conversations doivent être exclues
#      explicitement du calcul de l'âge max (`actionable_ungraced_count`),
#      received_at seul ne suffit pas à les détecter comme fraîches.
# Duplication du WHERE/HAVING assumée et documentée (même doctrine que le
# commentaire "Reproduction FIDÈLE" d'`ingest_watchdog.py`) — nécessaire car
# ce conservation-audit a besoin d'une projection différente (par
# conversation) que l'agrégat `count+min` d'`ingest_watchdog`, jamais pour
# ré-inventer le SEUIL d'éligibilité (`_gate_params()` reste l'unique source
# des 3 seuils).
_ACTIONABLE_BACKLOG_DETAIL_SQL = (
    # + source_type (breakdown par source du message STARVATION) et
    # + retry_count (cause `retry-parked` — conversations re-présentées puis
    # omises/échouées, cf derive_starvation_cause). Projection seule : le
    # prédicat d'éligibilité (WHERE/HAVING) reste STRICTEMENT le gate.
    "SELECT c.id::text AS conversation_id, c.conversation_uid, c.source_type, "
    "  c.retry_count, "
    "  round(EXTRACT(EPOCH FROM (now() - min(m.received_at) FILTER ( "
    "    WHERE m.id > c.curated_through_message_id AND btrim(m.content) <> '' "
    "  ))) / 3600.0, 1) AS oldest_received_age_h, "
    "  EXISTS ( "
    "    SELECT 1 FROM arac.raw_message_revisions rev "
    "    WHERE rev.conversation_id = c.id AND rev.reason = 'healing' "
    "      AND rev.created_at >= now() - interval '1 hour' * %(grace_hours)s "
    "  ) AS healed_recently, "
    # Drain-aware (2026-07-16) : volume PENDING en kt (chars/4/1000 — même
    # unité que drain-diagnostic.json et value_gate._CHARS_PER_TOKEN=4).
    # Projection PURE (aucun impact sur le prédicat WHERE/HAVING — le miroir
    # gate curateur / watchdog reste strictement synchrone) ; sert la mesure
    # de progression du drain (delta kt entre deux audits).
    "  round((sum(length(m.content)) FILTER (WHERE m.id > c.curated_through_message_id "
    "    AND btrim(m.content) <> '') / 4000.0)::numeric, 1) AS pending_kt "
    "FROM arac.conversations c "
    "JOIN arac.raw_messages m ON m.conversation_id = c.id "
    "WHERE c.acked = false AND c.retry_count < 5 "
    # même prédicat d'exclusion que le gate curateur et le
    # miroir watchdog — une conversation exclue-tracée (drain pas 2 / futur
    # enforce value-gate) ne doit plus jamais compter dans STARVATION.
    "  AND c.exclusion_category IS NULL "
    "  AND (c.next_retry_at IS NULL OR c.next_retry_at <= now()) "
    "GROUP BY c.id, c.conversation_uid, c.source_type, c.retry_count "
    "HAVING count(*) FILTER (WHERE m.id > c.curated_through_message_id) >= 1 "
    "   AND count(*) FILTER (WHERE m.id > c.curated_through_message_id "
    "                        AND btrim(m.content) <> '') >= 1 "
    "   AND ( "
    "        (now() - max(COALESCE(m.msg_created_at, m.received_at)) "
    "               >= interval '1 hour' * %(quiet_hours)s "
    "         AND count(*) FILTER (WHERE m.id > c.curated_through_message_id) "
    "               >= %(min_new_msgs)s) "
    "        OR min(COALESCE(m.msg_created_at, m.received_at)) "
    "             FILTER (WHERE m.id > c.curated_through_message_id) "
    "             <= now() - interval '1 hour' * %(age_cap_hours)s "
    "   )"
)


def _db_reachable(dsn: str) -> tuple[bool, str | None]:
    """Sonde de connectivité DB minimale — isole « DB down » (régime 1,
    exit 1) de « un collecteur particulier plante » (régime 2, section
    CRIT localisée) — cf BREAK docstring module."""
    try:
        import psycopg
        with psycopg.connect(dsn, connect_timeout=10) as conn:
            conn.execute("SET TRANSACTION READ ONLY")
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True, None
    except Exception as e:  # noqa: BLE001 — fail-closed-ET-CRIER
        return False, f"{type(e).__name__}: {e}"


def _section_sources(dsn: str) -> dict[str, Any]:
    from app.perception import source_registry as sr

    report = sr.collect_source_registry(dsn)
    violations = derive_sources_violations(report)
    return build_section(
        violations,
        counters={"sources_total": len(report),
                  "mute": sum(1 for x in report.values() if x["status"] == "MUTE"),
                  "pending_bootstrap": sum(1 for x in report.values()
                                           if x["status"] == "PENDING_BOOTSTRAP")},
        extra={"registry": report},
    )


def _collect_capture(dsn: str) -> list[dict[str, Any]]:
    import psycopg

    manifests: list[dict[str, Any]] = []
    with psycopg.connect(dsn, connect_timeout=10) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        with conn.cursor() as cur:
            cur.execute(
                "SELECT source_key, node_id, source_type FROM arac.ingest_sources "
                "WHERE coverage_policy = 'captured'"
            )
            sources = [{"source_key": r[0], "node_id": r[1], "source_type": r[2]}
                      for r in cur.fetchall()]
            for src in sources:
                cur.execute(
                    "SELECT run_started_at, files_scanned, sessions, messages_read, "
                    "  messages_emitted, messages_filtered, batches_ok, batches_failed, "
                    "  ack_mismatches "
                    "FROM arac.capture_manifests "
                    "WHERE node_id = %(node_id)s AND source_type = %(source_type)s "
                    "ORDER BY run_started_at DESC LIMIT 1",
                    {"node_id": src["node_id"], "source_type": src["source_type"]},
                )
                row = cur.fetchone()
                if row is None:
                    manifests.append({**src, "has_manifest": False})
                    continue
                run_started_at = row[0]
                age_h = ((datetime.now(timezone.utc) - run_started_at).total_seconds() / 3600.0
                        if run_started_at else None)
                manifests.append({
                    **src, "has_manifest": True, "age_hours": age_h,
                    "manifest": {
                        "run_started_at": str(run_started_at) if run_started_at else None,
                        "messages_read": row[3], "messages_emitted": row[4],
                        "messages_filtered": row[5] or {},
                    },
                })
    return manifests


def _section_capture(dsn: str, *, freshness_hours: float) -> dict[str, Any]:
    # La bibliothèque de capture vit côté poste source (le scanner qui lit
    # les conversations locales) ; ce dépôt ne la livre pas. Son absence est
    # rendue par `run_section_safely` comme une section EN ERREUR, jamais
    # comme un OK.
    import jsonl_capture_lib as jcl

    manifests = _collect_capture(dsn)
    violations = derive_capture_violations(
        manifests, freshness_hours=freshness_hours,
        check_invariant=jcl.check_manifest_invariant)
    return build_section(
        violations,
        counters={"sources_checked": len(manifests)},
        extra={"manifests": manifests, "prepurge": build_capture_prepurge_hook()},
    )


_UNCOVERED_SAMPLE_SQL = (
    "SELECT m.id::text, m.received_at, c.node_id, c.source_type "
    "FROM arac.raw_messages m JOIN arac.conversations c ON c.id = m.conversation_id "
    "WHERE m.received_at >= now() - interval '1 hour' * %(window_hours)s "
    # Plancher « ère des reçus » (déploiement 2026-07-07, correctif
    # faux-WARN) : un message reçu AVANT le premier `ingest_receipts` jamais
    # posté ne peut structurellement PAS avoir de reçu — ce n'est pas un trou
    # de preuve, juste un message antérieur à l'existence du mécanisme. Si
    # `arac.ingest_receipts` est vide, la sous-requête vaut NULL et la
    # comparaison filtre TOUTES les lignes -> aucun gap, sans cas spécial.
    "  AND m.received_at >= (SELECT min(created_at) FROM arac.ingest_receipts) "
    "  AND NOT EXISTS ( "
    "    SELECT 1 FROM arac.ingest_receipts r "
    "    WHERE r.node_id = c.node_id AND r.source_type = c.source_type "
    "      AND r.outcome = 'accepted' "
    "      AND r.created_at BETWEEN m.received_at - interval '1 hour' "
    "                           AND m.received_at + interval '1 hour' "
    "  ) "
    "ORDER BY m.received_at DESC LIMIT %(sample_limit)s"
)


def _collect_uncovered_sample(dsn: str, *, window_hours: float, sample_limit: int) -> list[dict[str, Any]]:
    import psycopg

    with psycopg.connect(dsn, connect_timeout=10) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        with conn.cursor() as cur:
            cur.execute(_UNCOVERED_SAMPLE_SQL,
                       {"window_hours": window_hours, "sample_limit": sample_limit})
            return [
                {"message_id": r[0], "received_at": str(r[1]), "node_id": r[2], "source_type": r[3]}
                for r in cur.fetchall()
            ]


def _section_ingest(
    dsn: str, *, reconcile_window_hours: float, sample_window_hours: float, sample_limit: int,
) -> dict[str, Any]:
    import reconcile_audit as ra  # scripts/ops/reconcile_audit.py

    reconcile_sig = ra.collect_reconcile(dsn, window_hours=reconcile_window_hours)
    uncovered_sample = _collect_uncovered_sample(
        dsn, window_hours=sample_window_hours, sample_limit=sample_limit)

    # la partie reconcile devient INFORMATIONNELLE ici (plafonnée WARN,
    # marquée) — l'unique émetteur de PAGE reconcile est reconcile-audit.
    violations = mark_reconcile_informational(
        ra.derive_violations(reconcile_sig, window_hours=reconcile_window_hours))
    violations += derive_receipt_coverage_violations(uncovered_sample)
    return build_section(
        violations,
        counters={"sources_checked": len(reconcile_sig.get("sources", [])),
                  "sample_checked": len(uncovered_sample)},
        extra={"reconcile": reconcile_sig, "uncovered_sample": uncovered_sample},
    )


def _collect_digestion(dsn: str, *, window_days: float, starvation_grace_hours: float) -> dict[str, Any]:
    from app.perception import ingest_watchdog as iw  # réutilisé, jamais dupliqué
    import psycopg

    # Backlog ACTIONNABLE — le COMPTE total et le quota répété viennent
    # d'ingest_watchdog (DRY, gate curateur réel reproduit UNE seule fois).
    # L'ÂGE (`oldest_actionable_age_h`) est en revanche recalculé CI-DESSOUS
    # via `_ACTIONABLE_BACKLOG_DETAIL_SQL` (received_at + grâce healing,
    # cf docstring de cette requête) — `iw_sig["oldest_actionable_age_h"]`
    # (basé sur msg_created_at, sans grâce) n'est PLUS utilisé ici.
    iw_sig = iw.collect_signals(dsn)
    sig: dict[str, Any] = {
        "actionable_backlog": iw_sig.get("actionable_backlog", 0),
        "quota_hits_window": iw_sig.get("quota_hits_24h", 0),
    }

    with psycopg.connect(dsn, connect_timeout=10) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        with conn.cursor() as cur:
            cur.execute(
                "SELECT conversation_uid, retry_count, left(coalesce(last_curation_error,''),160) "
                "FROM arac.conversations WHERE retry_count >= 5 AND acked = false"
            )
            sig["dead_letters"] = [
                {"conversation_uid": r[0], "retry_count": int(r[1]), "last_error": r[2]}
                for r in cur.fetchall()
            ]

            cur.execute(
                _ACTIONABLE_BACKLOG_DETAIL_SQL,
                {**iw._gate_params(), "grace_hours": starvation_grace_hours},
            )
            detail_rows = [
                {"conversation_uid": r[1],
                 "source_type": r[2],
                 "retry_count": int(r[3] or 0),
                 "age_h": (float(r[4]) if r[4] is not None else None),
                 "healed_recently": bool(r[5]),
                 "pending_kt": (float(r[6]) if r[6] is not None else None)}
                for r in cur.fetchall()
            ]
            ungraced = [r for r in detail_rows if not r["healed_recently"]]
            # Drain-aware : backlog actionnable NON gracié en kt (même
            # population que la famine). Détail vide -> None (pas de mesure,
            # jamais un 0 fabriqué).
            sig["actionable_backlog_kt"] = (
                round(sum(r["pending_kt"] or 0.0 for r in ungraced), 1)
                if detail_rows else None)
            if detail_rows:
                # Détail obtenu : on fait CONFIANCE au partitionnement
                # healed/ungraced (même prédicat que le gate réel, cf
                # docstring _ACTIONABLE_BACKLOG_DETAIL_SQL).
                sig["actionable_ungraced_count"] = len(ungraced)
                ungraced_ages = [r["age_h"] for r in ungraced if r["age_h"] is not None]
                sig["oldest_actionable_age_h"] = max(ungraced_ages) if ungraced_ages else None
            else:
                # Détail VIDE alors qu'`actionable_backlog` (iw) peut être >0
                # -> divergence entre les deux requêtes (bug/course), jamais
                # interprété comme « tout est gracié » : fail-closed, on
                # retombe sur le compte total (rien n'est gracié par défaut).
                sig["actionable_ungraced_count"] = sig["actionable_backlog"]
                sig["oldest_actionable_age_h"] = None
            sig["actionable_backlog_detail"] = detail_rows

            try:
                cur.execute("SELECT value FROM arac.arac_config WHERE key = 'paid_ai_enabled'")
                row = cur.fetchone()
                sig["paid_ai_enabled"] = bool(row[0]) if row is not None else False
            except Exception:  # noqa: BLE001 — table absente : posture inconnue
                sig["paid_ai_enabled"] = None

            cur.execute(_EMPTY_CONVERSATIONS_SQL)
            sig["empty_conversations"] = [
                {"conversation_uid": r[0], "source_type": r[1], "exclusion_reason": r[2]}
                for r in cur.fetchall()
            ]

            cur.execute(_RUN_RECEIPTS_WINDOW_SQL, {"window_days": window_days})
            runs = [
                {"slot_key": r[0], "status": r[1], "stop_reason": r[2],
                 "messages_truncated": r[3], "coverage_omitted": r[4],
                 "oversized_messages": r[5], "atoms_created": r[6],
                 "atoms_superseded": r[7],
                 "age_hours": (float(r[8]) if r[8] is not None else None)}
                for r in cur.fetchall()
            ]
            sig["run_receipts_window"] = runs

            done_slot_keys = [r["slot_key"] for r in runs if r["status"] == "done"]
            atoms_by_run: dict[str, int] = {}
            if done_slot_keys:
                cur.execute(
                    "SELECT source_ref->>'run_ref', count(*) FROM arac.memory_atoms "
                    "WHERE source_ref->>'run_ref' = ANY(%s) GROUP BY 1",
                    (done_slot_keys,),
                )
                atoms_by_run = {r[0]: int(r[1]) for r in cur.fetchall()}
            sig["atoms_in_db_by_run"] = atoms_by_run
    return sig


def _section_digestion(
    dsn: str, *, starvation_hours: float, window_days: float, coverage_omitted_min: int,
    starvation_grace_hours: float, burned_slot_recent_hours: float,
    starvation_prev: dict[str, Any] | None = None,
    starvation_repage_hours: float = STARVATION_REPAGE_HOURS_DEFAULT,
    drain_aware: bool = False,
    drain_progress_kt_min: float = DRAIN_PROGRESS_KT_MIN_DEFAULT,
) -> dict[str, Any]:
    from app.perception import ingest_watchdog as iw
    from agents.cortex import review_queue

    sig = _collect_digestion(dsn, window_days=window_days, starvation_grace_hours=starvation_grace_hours)
    violations, consigned = derive_digestion_violations(
        sig, starvation_hours=starvation_hours,
        coverage_omitted_min=coverage_omitted_min,
        quota_repeat_min=iw.QUOTA_REPEAT_MIN_COUNT,
        burned_slot_recent_hours=burned_slot_recent_hours,
        check_receipt_atom_invariant=review_queue.check_receipt_atom_invariant,
        starvation_prev=starvation_prev,
        starvation_repage_hours=starvation_repage_hours,
        drain_aware=drain_aware,
        drain_progress_kt_min=drain_progress_kt_min)
    # l'entrée d'état (fingerprint/uids/bucket/paged_this_run) remonte
    # en `extra` de la section — `main` la persiste dans le fichier state
    # (jamais dans le texte de la violation elle-même, elle en est retirée).
    starvation_state = None
    for viol in violations:
        if viol.get("code") == "STARVATION":
            starvation_state = viol.pop("starvation_state", None)
            break
    return build_section(
        violations,
        counters={
            "actionable_backlog": sig.get("actionable_backlog"),
            "actionable_ungraced": sig.get("actionable_ungraced_count"),
            "dead_letters": len(sig.get("dead_letters", [])),
            "empty_conversations": len(sig.get("empty_conversations", [])),
            "runs_checked": len(sig.get("run_receipts_window", [])),
        },
        extra={"consigned": consigned, "starvation_state": starvation_state},
    )


def _section_memoire(dsn: str, *, api_base_url: str) -> dict[str, Any]:
    # Le canari de rappel n'est pas livré par ce dépôt : son absence est
    # rendue comme une section EN ERREUR par `run_section_safely`.
    import memory_canary as mc
    import psycopg

    with psycopg.connect(dsn, connect_timeout=10) as conn:
        canary = mc.collect_memory_canary(conn=conn, api_base_url=api_base_url)
    violations = canary.get("violations", [])
    return build_section(
        violations,
        counters={"null_embedding_count": len(canary.get("null_embedding_ids", []))},
        extra={"canary_distance": canary.get("canary_distance")},
    )


def _send_telegram(text: str) -> tuple[bool, str]:
    from app.perception import ingest_watchdog as iw  # source unique de send_telegram, jamais dupliqué
    return iw.send_telegram(text)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def main() -> int:
    dsn = os.environ.get("DATABASE_URL_READONLY") or os.environ.get("DATABASE_URL_APP")
    if not dsn:
        print(json.dumps({"event": "conservation.audit", "level": "ERROR",
                          "error": "DATABASE_URL_READONLY/APP manquant"}), file=sys.stderr)
        return 2

    ok, err = _db_reachable(dsn)
    if not ok:
        msg = f"🧠🛑 ARAC conservation-audit v2 : IMPOSSIBLE DE VÉRIFIER ({err})"
        try:
            _send_telegram(msg)
        except Exception:  # noqa: BLE001
            pass
        print(json.dumps({"event": "conservation.audit", "level": "ERROR", "error": err}),
              file=sys.stderr)
        return 1

    # état durable anti-accoutumance (fichier state JSON, mécanique
    # load_state/save_state PARTAGÉE avec ingest_watchdog). Illisible/absent
    # -> {} : on retombe sur « premier franchissement » (page), jamais un
    # silence — fail-loud.
    from app.perception import ingest_watchdog as _iw
    state_path = _state_file()
    prev_state = _iw.load_state(state_path)

    now_iso = datetime.now(timezone.utc).isoformat()
    section_builders: dict[str, Any] = {
        "sources": lambda: _section_sources(dsn),
        "capture": lambda: _section_capture(dsn, freshness_hours=_capture_freshness_hours()),
        "ingest": lambda: _section_ingest(
            dsn, reconcile_window_hours=_reconcile_window_hours(),
            sample_window_hours=_receipt_sample_window_hours(),
            sample_limit=_receipt_sample_limit()),
        "digestion": lambda: _section_digestion(
            dsn, starvation_hours=_starvation_hours(), window_days=_run_window_days(),
            coverage_omitted_min=_coverage_omitted_min(),
            starvation_grace_hours=_starvation_grace_hours(),
            burned_slot_recent_hours=_burned_slot_recent_hours(),
            starvation_prev=prev_state.get("starvation"),
            starvation_repage_hours=_starvation_repage_hours(),
            drain_aware=_starvation_drain_aware(),
            drain_progress_kt_min=_drain_progress_kt_min()),
        "memoire": lambda: _section_memoire(dsn, api_base_url=_api_base_url()),
    }

    sections: dict[str, dict[str, Any]] = {
        name: run_section_safely(name, builder) for name, builder in section_builders.items()
    }
    sections["backups"] = build_backups_section()

    report = build_report(sections, generated_at=now_iso)
    print(json.dumps(report, ensure_ascii=False, default=str), file=sys.stderr)

    # Défense en profondeur (cf docstring module) : WARN/OK sont TOUJOURS
    # calculés et LOGGÉS ci-dessus (report complet sur stderr, quel que soit
    # le niveau) — mais seul CRIT PAGE (Telegram). Un bulletin nocturne ne
    # doit pas réveiller sur un WARN.
    sent_ok = False
    if should_page(report["level"]):
        try:
            sent_ok, detail = _send_telegram(format_alert(report))
            print(json.dumps({"event": "conservation.alert_sent", "ok": sent_ok, "detail": detail}),
                  file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"event": "conservation.alert_failed",
                              "error": f"{type(e).__name__}: {e}"}), file=sys.stderr)
    elif report["level"] != "OK":
        print(json.dumps({"event": "conservation.alert_suppressed", "level": report["level"],
                          "reason": "WARN nocturne — pas de page Telegram (défense en "
                                    "profondeur), rapport JSON complet ci-dessus sur stderr"}),
              file=sys.stderr)

    # persistance de l'état STARVATION. Règles (cf helper watchdog) :
    #   • pas de STARVATION ce run -> RESET (le prochain franchissement est
    #     un « premier franchissement », il page) ;
    #   • décision « page » mais envoi Telegram ÉCHOUÉ (malgré le retry)
    #     -> on GARDE l'ancienne entrée : le prochain run re-décidera de
    #     pager (une page perdue ne doit jamais être comptée comme envoyée) ;
    #   • sinon -> nouvelle entrée (pagée ou digest). Échec d'écriture du
    #     state = loggé, jamais bloquant (l'audit a déjà rendu son rapport).
    try:
        new_state = dict(prev_state)
        star_entry = (sections.get("digestion") or {}).get("starvation_state")
        if star_entry is None:
            new_state.pop("starvation", None)
        elif star_entry.pop("paged_this_run", False) and not sent_ok:
            pass  # page décidée mais non DÉLIVRÉE -> re-tenter au prochain run
        else:
            new_state["starvation"] = star_entry
        _iw.save_state(state_path, new_state)
    except Exception as e:  # noqa: BLE001 — observabilité, jamais bloquant
        print(json.dumps({"event": "conservation.state_write_failed",
                          "error": f"{type(e).__name__}: {e}"}), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
