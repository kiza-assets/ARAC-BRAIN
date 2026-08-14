"""Agent MONITOR — surveillance des unités de CE cerveau via journalctl.

Phase v0.4 Bloc 8 :
  - Polling `journalctl -u $ARAC_UNIT_PREFIX-* --since="N seconds ago" -o json`
    toutes les ARAC_MONITOR_INTERVAL_SEC secondes (defaut 60s).
  - Detection :
      * Service exit non-zero (UNIT_RESULT = "failed" ou code de retour > 0).
      * Restart loop : > ARAC_MONITOR_RESTART_THRESHOLD (defaut 3) restarts
        en ARAC_MONITOR_RESTART_WINDOW_SEC (defaut 300s), via
        `systemctl show -p NRestarts <service>`.
      * OOM via journalctl --grep "Out of memory".
  - Sur detection -> `bus.send(to_node="arac-telegram-bridge", ...)` avec
    value="ALERT: <service> <reason>" pour escalade humaine via Telegram.
  - Heartbeat 30s comme les autres agents (run_heartbeat_loop_async).

Convention node_id : `arac-monitor` (cf systemd unit Environment=ARAC_NODE_ID).
Pattern d'implementation : copie de la structure async orchestrator/auditor.

Garde-fous :
  - Deduplication : un meme service en alerte n'est pas re-signale tant que
    le compteur de restarts n'a pas progresse (state cache local en memoire).
  - L'agent monitor ne s'auto-surveille pas (filtre `*-monitor.service`).
  - SANS ARAC_UNIT_PREFIX, il ne surveille RIEN et le dit. Surveiller le
    voisin serait pire que ne rien surveiller : ses alertes portent le
    message journald brut de ses unités, et elles partiraient dans NOTRE
    messagerie Telegram.
  - Si journalctl n'a pas les permissions (SupplementaryGroups=systemd-journal
    manquant), log warn + tick suivant (pas de crash).

Env vars :
  - ARAC_NODE_ID                    obligatoire (cf systemd, defaut systemd "arac-monitor")
  - ARAC_API_URL                    obligatoire (aucun defaut : voir _base)
  - ARAC_HEARTBEAT_SEC              defaut 30
  - ARAC_UNIT_PREFIX                obligatoire (sans elle : rien surveillé)
  - ARAC_MONITOR_INTERVAL_SEC       defaut 60
  - ARAC_MONITOR_RESTART_THRESHOLD  defaut 3
  - ARAC_MONITOR_RESTART_WINDOW_SEC defaut 300
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import time
from typing import Any

from agents.lib import bus
from agents.lib.heartbeat import run_heartbeat_loop_async

logger = logging.getLogger("arac.monitor")

_NODE_ID = "arac-monitor"
_BRIDGE_NODE_ID = "arac-telegram-bridge"

# LES UNITÉS SURVEILLÉES PORTENT LE NOM DE CE CERVEAU.
#
# Cette liste était écrite en dur — « arac-api.service », « arac-backup.service »
# — c'est-à-dire les unités du PREMIER cerveau de la machine. Sur cette machine,
# des moniteurs d'essai rapportaient ainsi la santé des unités de PRODUCTION :
# des voyants verts qui ne parlaient pas du cerveau qu'on surveillait. Un
# diagnostic qui se trompe de sujet en disant « tout va bien » est pire que
# l'absence de diagnostic.
#
# Le préfixe vient de l'environnement (ARAC_UNIT_PREFIX, écrit par le bootstrap
# dans le fichier d'environnement du cerveau). Sans lui, on ne surveille rien
# plutôt que de surveiller le voisin.
def _prefixe_unite() -> str:
    """Le préfixe des unités de CE cerveau, ou la chaîne vide si on l'ignore."""
    return (os.environ.get("ARAC_UNIT_PREFIX") or "").strip()


def _monitored_services() -> tuple[str, ...]:
    prefixe = _prefixe_unite()
    if not prefixe:
        return ()
    return tuple(
        f"{prefixe}-{suffixe}.service"
        for suffixe in ("api", "auditor", "developer", "orchestrator",
                        "telegram-bridge", "sauvegarde")
        # NB : le moniteur lui-même est exclu, pour éviter l'auto-surveillance.
    )


# LA MOITIÉ QUI MANQUAIT : LE FILTRE D'ENTRÉE ET LE FILTRE DE SORTIE.
#
# `_monitored_services()` ci-dessus dérivait bien les unités du cerveau. Le
# reste du fichier, non : `fetch_journal_lines()` interrogeait `journalctl -u
# arac-*` — le journal de TOUS les cerveaux de la machine — et les deux
# détecteurs ne testaient que `unit.startswith("arac-")`.
#
# Le dégât ne se limitait pas à un diagnostic qui se trompe de sujet.
# `send_alert()` pousse `f"ALERT: {service} {reason}"` vers le pont Telegram
# de SON propriétaire, et `reason` contient `msg[:120]`, c'est-à-dire le
# MESSAGE journald brut de l'unité fautive. Le journal d'exécution du cerveau
# d'un voisin partait donc dans la messagerie de quelqu'un d'autre.
#
# Deux filtres, et pas un : journalctl peut rendre des lignes noyau sans
# `_SYSTEMD_UNIT` (le cas OOM le traite déjà), et un futur appelant pourrait
# fournir ses propres entrées. Le filtre de sortie répète donc le filtre
# d'entrée, comme une ceinture répète une bretelle.
def _appartient_a_ce_cerveau(unit: str, prefixe: str) -> bool:
    """L'unité est-elle une unité de CE cerveau ?

    `prefixe` vide veut dire « je ne sais pas ». On retombe alors sur la seule
    chose qu'on puisse encore affirmer — la FORME d'une unité ARAC — et c'est
    délibérément le seul endroit du module où l'ignorance ne ferme pas la
    porte. Elle est inatteignable à l'exécution : `fetch_journal_lines()`
    refuse d'aller chercher quoi que ce soit sans préfixe, et la boucle passe
    le sien explicitement. Ce repli ne sert qu'à un appel direct des
    détecteurs, où c'est l'appelant qui répond de ce qu'il fournit.
    """
    if not unit.endswith(".service"):
        return False
    return unit.startswith(f"{prefixe}-") if prefixe else unit.startswith("arac-")


# Calculé à CHAQUE appel, pas à l'import : une valeur figée au chargement du
# module dépendrait de l'ordre dans lequel systemd a posé l'environnement, ce
# qui est précisément le genre de dépendance invisible qu'on cherche à retirer.


def _setup_logging() -> None:
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------


def fetch_journal_lines(since_sec: int, prefixe: str | None = None) -> list[dict[str, Any]]:
    """Recupere les lignes journald des unités de CE cerveau depuis N secondes.

    Retourne une liste de dicts (JSON output de journalctl). En cas d'echec
    (permissions, journalctl absent, etc.), log warn et retourne [].

    SANS PRÉFIXE, LA LECTURE EST CELLE D'AVANT — `arac-*`, c'est-à-dire le
    journal de TOUS les cerveaux de la machine — et elle est signalée comme
    telle. Ce chemin n'existe que pour un appel direct, à des fins d'examen ;
    la boucle, elle, refuse de tourner sans préfixe (voir `run_monitor_loop`),
    et rien de ce qui sortirait d'une telle lecture ne peut être ÉMIS : le
    filtre de sortie, juste avant la messagerie, refuse toute unité qui ne
    porte pas notre préfixe.

    La distinction compte : lire le journal de la machine sur laquelle on
    tourne n'est pas le dégât. Le dégât, c'est d'en pousser une ligne — le
    MESSAGE journald brut d'un service privé — vers le Telegram de quelqu'un
    d'autre. C'est donc l'émission qui est fermée d'abord, et la lecture qui
    est fermée en amont dans le seul chemin qui émet.
    """
    if prefixe is None:
        prefixe = _prefixe_unite()
    if not prefixe:
        logger.warning(json.dumps({
            "event": "monitor.sans_prefixe",
            "detail": "ARAC_UNIT_PREFIX absent : lecture du journal de TOUS les "
                      "cerveaux (arac-*). Aucune alerte ne peut en sortir.",
        }))

    glob = f"{prefixe}-*" if prefixe else "arac-*"

    # `journalctl -u <glob> --since="N seconds ago" -o json --no-pager`
    # NB : le glob est expanse par journalctl lui-meme (pas le shell).
    cmd = [
        "journalctl",
        "-u",
        glob,
        "--since",
        f"{since_sec} seconds ago",
        "-o",
        "json",
        "--no-pager",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError:
        logger.warning(json.dumps({"event": "monitor.journalctl_missing"}))
        return []
    except subprocess.TimeoutExpired:
        logger.warning(json.dumps({"event": "monitor.journalctl_timeout"}))
        return []

    if result.returncode != 0:
        logger.warning(json.dumps({
            "event": "monitor.journalctl_fail",
            "rc": result.returncode,
            "stderr": result.stderr[:200],
        }))
        return []

    entries: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def detect_exit_nonzero(
    entries: list[dict[str, Any]], prefixe: str | None = None
) -> list[dict[str, str]]:
    """Detecte les unités de CE cerveau ayant exit avec un code non-zero.

    Heuristique : message systemd contient "Main process exited" + code != 0,
    ou champ JOB_RESULT="failed" / UNIT_RESULT="failed".

    Retourne liste de {service, reason}.
    """
    if prefixe is None:
        prefixe = _prefixe_unite()
    alerts: list[dict[str, str]] = []
    seen_units: set[str] = set()
    for e in entries:
        unit = e.get("_SYSTEMD_UNIT") or e.get("UNIT") or ""
        if not _appartient_a_ce_cerveau(unit, prefixe):
            continue
        # Pas d'auto-surveillance. Le test porte sur le SUFFIXE, pas sur un
        # nom complet : le moniteur du cerveau « nadia_brain » s'appelle
        # `arac-nadia_brain-monitor.service`, et « arac-monitor.service »
        # écrit en toutes lettres ne reconnaissait que celui du premier
        # cerveau installé — les autres se seraient auto-signalés.
        if unit.endswith("-monitor.service"):
            continue

        msg = e.get("MESSAGE", "")
        # systemd loggue typiquement : "<unit>: Main process exited, code=exited, status=N/SIGNAL"
        # avec status != 0. Ou "<unit>: Failed with result '<reason>'".
        result_field = e.get("UNIT_RESULT") or e.get("JOB_RESULT") or ""
        is_exit_nonzero = (
            ("Main process exited" in msg and "status=0" not in msg and "code=killed" not in msg)
            or (result_field == "failed")
            or ("Failed with result" in msg)
        )
        if is_exit_nonzero and unit not in seen_units:
            seen_units.add(unit)
            alerts.append({"service": unit, "reason": f"exit_nonzero: {msg[:120]}"})
    return alerts


def detect_oom(
    entries: list[dict[str, Any]], prefixe: str | None = None
) -> list[dict[str, str]]:
    """Detecte les OOM kills via 'Out of memory' / 'oom-kill' dans les logs.

    Retourne liste de {service, reason}.
    """
    if prefixe is None:
        prefixe = _prefixe_unite()
    alerts: list[dict[str, str]] = []
    seen_units: set[str] = set()
    for e in entries:
        msg = e.get("MESSAGE", "")
        if "Out of memory" not in msg and "oom-kill" not in msg.lower():
            continue
        unit = e.get("_SYSTEMD_UNIT") or e.get("UNIT") or ""
        # OOM peut etre loggue par le kernel sans _SYSTEMD_UNIT - on tente
        # de matcher le nom du process tue dans le message. La liste où l'on
        # cherche est celle de CE cerveau : un OOM qui tue l'orchestrateur du
        # voisin ne doit pas lever une alerte sous notre nom.
        if not _appartient_a_ce_cerveau(unit, prefixe):
            for svc in _monitored_services():
                base = svc.replace(".service", "")
                if base in msg.lower():
                    unit = svc
                    break
        if _appartient_a_ce_cerveau(unit, prefixe) and unit not in seen_units:
            seen_units.add(unit)
            alerts.append({"service": unit, "reason": f"oom: {msg[:120]}"})
    return alerts


def get_nrestarts(service: str) -> int:
    """Retourne NRestarts pour un service via `systemctl show -p NRestarts`.

    Retourne -1 en cas d'erreur (service inconnu, systemctl indisponible).
    """
    try:
        r = subprocess.run(
            ["systemctl", "show", "-p", "NRestarts", "--value", service],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return -1
    if r.returncode != 0:
        return -1
    val = r.stdout.strip()
    try:
        return int(val)
    except ValueError:
        return -1


def detect_restart_loop(
    services: list[str],
    state: dict[str, dict[str, Any]],
    threshold: int,
    window_sec: int,
    now: float,
) -> list[dict[str, str]]:
    """Detecte les services qui restartent trop souvent.

    Algo : on memorise pour chaque service la liste des timestamps ou
    NRestarts a augmente. Si >= `threshold` increments dans `window_sec`,
    on alerte. State mute en place.

    Retourne liste de {service, reason}.
    """
    alerts: list[dict[str, str]] = []
    for svc in services:
        # Pas d'auto-surveillance — et le nom du moniteur porte lui aussi le
        # préfixe de son cerveau : le tester en toutes lettres ne reconnaissait
        # que celui du premier cerveau installé.
        if svc.endswith("-monitor.service"):
            continue
        nrestarts = get_nrestarts(svc)
        if nrestarts < 0:
            continue
        prev = state.setdefault(svc, {"last_count": 0, "tx": [], "last_alert_count": -1})
        last_count = prev["last_count"]
        if nrestarts > last_count:
            # NRestarts a augmente depuis le dernier tick
            prev["tx"].append(now)
            prev["last_count"] = nrestarts
        # Purge timestamps hors fenetre
        cutoff = now - window_sec
        prev["tx"] = [t for t in prev["tx"] if t >= cutoff]
        if len(prev["tx"]) >= threshold and prev["last_alert_count"] != nrestarts:
            prev["last_alert_count"] = nrestarts
            alerts.append({
                "service": svc,
                "reason": f"restart_loop: {len(prev['tx'])} restarts en {window_sec}s (NRestarts={nrestarts})",
            })
    return alerts


async def _dormir(stop_event: asyncio.Event, interval: int) -> bool:
    """Attend `interval` secondes, interruptible. Rend True s'il faut s'arrêter.

    Extrait de la boucle parce qu'il y a désormais DEUX sorties de tour : le
    tour normal, et le tour où l'on ne sait pas de quel cerveau on est le
    moniteur. Dupliquer l'attente aurait été dupliquer la condition d'arrêt.
    """
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=interval)
        return True
    except asyncio.TimeoutError:
        return False
    except asyncio.CancelledError:
        return True


async def send_alert(service: str, reason: str) -> None:
    """Envoie un ALERT vers arac-telegram-bridge via le bus."""
    value = f"ALERT: {service} {reason}"
    try:
        await bus.send(
            from_node=_NODE_ID,
            to_node=_BRIDGE_NODE_ID,
            value=value,
            metadata={
                "type": "monitor_alert",
                "service": service,
                "reason": reason,
            },
        )
        logger.info(json.dumps({
            "event": "monitor.alert_sent",
            "service": service,
            "reason": reason[:100],
        }))
    except Exception as e:  # noqa: BLE001
        logger.error(json.dumps({
            "event": "monitor.alert_send_fail",
            "service": service,
            "error": type(e).__name__,
            "detail": str(e)[:200],
        }))


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


async def run_monitor_loop(stop_event: asyncio.Event) -> int:
    """Boucle de polling journald + systemctl. Termine sur stop_event."""
    interval = _env_int("ARAC_MONITOR_INTERVAL_SEC", 60)
    threshold = _env_int("ARAC_MONITOR_RESTART_THRESHOLD", 3)
    window = _env_int("ARAC_MONITOR_RESTART_WINDOW_SEC", 300)

    logger.info(json.dumps({
        "event": "monitor.boot",
        "node_id": _NODE_ID,
        "interval_sec": interval,
        "restart_threshold": threshold,
        "restart_window_sec": window,
        "monitored_services": list(_monitored_services()),
    }))

    # State pour detection restart loop (timestamps + last_count par service).
    restart_state: dict[str, dict[str, Any]] = {}
    # Dedup des alertes exit_nonzero / oom : un meme service ne re-alerte pas
    # tant qu'on n'a pas eu un "tick clean" entre temps.
    seen_alerts: dict[str, str] = {}

    while not stop_event.is_set():
        try:
            # LE PRÉFIXE EST LU À CHAQUE TOUR ET PASSÉ EXPLICITEMENT.
            #
            # Lu à chaque tour, parce qu'une valeur figée à l'import dépendrait
            # de l'ordre dans lequel systemd a posé l'environnement. Passé
            # explicitement, parce que c'est ICI qu'on sait de quel cerveau on
            # est le moniteur : les détecteurs, eux, ne doivent pas avoir à le
            # deviner.
            prefixe = _prefixe_unite()
            if not prefixe:
                # ON NE SURVEILLE RIEN PLUTÔT QUE DE SURVEILLER LE VOISIN.
                # Le même réflexe que `_monitored_services()`, appliqué au
                # tour de boucle entier : sans préfixe, il n'y a pas de
                # journal à lire qui soit le nôtre, donc rien à lire du tout.
                logger.warning(json.dumps({
                    "event": "monitor.sans_prefixe.tick_ignore",
                    "detail": "ARAC_UNIT_PREFIX absent : ce moniteur ne sait pas "
                              "de quel cerveau il est le moniteur. Il ne lit rien.",
                }))
                if await _dormir(stop_event, interval):
                    break
                continue

            entries = fetch_journal_lines(since_sec=interval + 10, prefixe=prefixe)  # marge 10s

            exit_alerts = detect_exit_nonzero(entries, prefixe)
            oom_alerts = detect_oom(entries, prefixe)
            restart_alerts = detect_restart_loop(
                list(_monitored_services()),
                restart_state,
                threshold=threshold,
                window_sec=window,
                now=time.time(),
            )

            all_alerts = exit_alerts + oom_alerts + restart_alerts

            # Dedup : on n'envoie pas 2 fois la meme alerte (service, reason_kind)
            for alert in all_alerts:
                svc = alert["service"]
                reason = alert["reason"]
                # LE DERNIER FILTRE, JUSTE AVANT LA MESSAGERIE.
                #
                # `reason` transporte le message journald BRUT de l'unité.
                # Envoyer cela, c'est envoyer une ligne du journal d'exécution
                # d'un cerveau. Le seul destinataire légitime est son
                # propriétaire ; on refuse donc de sortir quoi que ce soit qui
                # ne porte pas notre préfixe, même si un détecteur s'est
                # trompé, même si l'appelant a mal filtré.
                if not _appartient_a_ce_cerveau(svc, prefixe):
                    logger.warning(json.dumps({
                        "event": "monitor.alerte_etrangere_refusee",
                        "service": svc,
                        "prefixe": prefixe,
                    }))
                    continue
                reason_kind = reason.split(":", 1)[0]
                key = f"{svc}::{reason_kind}"
                if seen_alerts.get(key) == reason:
                    continue  # deja signale a l'identique
                seen_alerts[key] = reason
                await send_alert(svc, reason)

            # Si rien detecte, on log un tick "ok" toutes les ~5 min seulement
            # pour eviter le bruit (interval=60 -> 1 log/5 ticks).
            if not all_alerts:
                logger.debug(json.dumps({
                    "event": "monitor.tick_ok",
                    "entries_scanned": len(entries),
                }))

        except Exception as e:  # noqa: BLE001
            logger.error(json.dumps({
                "event": "monitor.tick_error",
                "error": type(e).__name__,
                "detail": str(e)[:200],
            }))

        # Sleep interruptible
        if await _dormir(stop_event, interval):
            break

    logger.info(json.dumps({"event": "monitor.shutdown.clean", "node_id": _NODE_ID}))
    return 0


async def amain() -> int:
    _setup_logging()
    logger.info(json.dumps({
        "event": "boot.ok",
        "node_id": _NODE_ID,
        "phase": "v0.4 Bloc 8",
        "mode": "async + journalctl polling + systemctl NRestarts",
    }))

    stop_event = asyncio.Event()

    tasks = [
        asyncio.create_task(run_heartbeat_loop_async(stop_event=stop_event), name="heartbeat"),
        asyncio.create_task(run_monitor_loop(stop_event), name="monitor_loop"),
    ]

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info(json.dumps({"event": "shutdown.clean", "node_id": _NODE_ID}))
    return 0


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    sys.exit(main())
