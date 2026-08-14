"""Collecteur SOBRIÉTÉ — visibilité coût IA du cerveau (READ-ONLY).

Répond aux questions que le cockpit ne savait pas montrer pendant l'incident :
dernière conversation reçue, backlog (pending/processing/failed/actionable),
curated aujourd'hui, IA payante armée O/N, kill-switch, budget du jour, et
« Claude actif O/N » (process `claude`, distingués par utilisateur : le curateur
tourne sous `aracagent`).

Doctrine : OBSERVE FIRST. READ ONLY. Aucune écriture, aucun subprocess mutateur,
aucun appel IA. Toute panne -> valeur dégradée ("unavailable"/"unknown"), jamais
d'exception propagée au cockpit.
"""

from __future__ import annotations

import os
import pwd
from typing import Any

from control_center.collectors import db_metrics, system_metrics

_UNAVAILABLE = "unavailable"
_UNKNOWN = "unknown"


def _db_sobriety() -> dict[str, Any]:
    """Backlog + flag paid_ai_enabled via la connexion read-only."""
    try:
        conn = db_metrics._connect_readonly()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT max(received_at) FROM arac.raw_conversations")
                last_received = cur.fetchone()[0]
                cur.execute(
                    "SELECT "
                    " count(*) FILTER (WHERE status='pending'), "
                    " count(*) FILTER (WHERE status='processing'), "
                    " count(*) FILTER (WHERE status='failed'), "
                    " count(*) FILTER (WHERE status='curated' "
                    "   AND curated_at::date = (now() at time zone 'utc')::date), "
                    " count(*) FILTER (WHERE acked=false AND retry_count<5 AND ("
                    "   status='pending' OR status='processing' OR "
                    "   (status='failed' AND (next_retry_at IS NULL OR next_retry_at<=now())))) "
                    "FROM arac.raw_conversations")
                pending, processing, failed, curated_today, actionable = cur.fetchone()
            # flag paid_ai_enabled (best-effort : le rôle readonly peut ne pas
            # avoir SELECT sur arac_config -> unknown, dégradation propre).
            paid_ai_enabled: Any = _UNKNOWN
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT value FROM arac.arac_config WHERE key='paid_ai_enabled'")
                    row = cur.fetchone()
                    paid_ai_enabled = (row[0] is True) if row else False
            except Exception:
                paid_ai_enabled = _UNKNOWN
        finally:
            conn.close()
        return {
            "last_received": last_received,
            "pending": int(pending), "processing": int(processing),
            "failed": int(failed), "curated_today": int(curated_today),
            "actionable": int(actionable),
            "paid_ai_enabled": paid_ai_enabled,
        }
    except Exception:
        return {"error": _UNAVAILABLE, "paid_ai_enabled": _UNKNOWN}


def _claude_running() -> dict[str, Any]:
    """Process `claude` en cours, comptés par utilisateur (via /proc, sans subprocess).

    Le curateur spawn `claude` sous `aracagent` ; une session opérateur sous
    `root`. `curator_active` = au moins un `claude` détenu par `aracagent`.
    """
    total = 0
    by_user: dict[str, int] = {}
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return {"total": _UNKNOWN, "curator_active": _UNKNOWN}
    for pid in pids:
        cl = f"/proc/{pid}/cmdline"
        try:
            with open(cl, "rb") as fh:
                argv = [p.decode("utf-8", "replace") for p in fh.read().split(b"\x00") if p]
        except OSError:
            continue
        if not argv:
            continue
        exe = argv[0]
        if os.path.basename(exe) != "claude" and "/claude" not in exe:
            continue
        total += 1
        try:
            user = pwd.getpwuid(os.stat(cl).st_uid).pw_name
        except (OSError, KeyError):
            user = "?"
        by_user[user] = by_user.get(user, 0) + 1
    return {"total": total, "by_user": by_user,
            "curator_active": by_user.get("aracagent", 0) > 0}


# L'UNITÉ DU CURATEUR PORTE LE NOM DE CE CERVEAU — comme toutes les autres.
#
# Ce collecteur interrogeait « arac-curator-batch.service » et son timer : un
# nom figé, identique pour tous les cerveaux, et qui n'est celui d'AUCUNE unité
# posée par le bootstrap (`bootstrap/lib/services.sh` rend
# `$ARAC_UNIT_PREFIX-{api,cockpit,cycle,sauvegarde}`). Deux conséquences, les
# deux mauvaises :
#
#   · sur une machine neuve, `systemctl is-active` rend « inactive » pour une
#     unité qui n'existe pas, et le cockpit affiche un verdict de santé rendu
#     sur du vide ;
#   · sur une machine qui porte déjà un cerveau ainsi nommé, le cockpit du
#     second affiche la santé du curateur du PREMIER.
#
# C'est exactement le défaut que l'unité du cockpit dit avoir corrigé pour
# `system_metrics` — « deux noms qui, sur une machine à deux cerveaux,
# désignent le VOISIN » — survivant dans le collecteur d'à côté.
#
# La règle retenue est la même que pour le moniteur : le nom se DÉRIVE du
# préfixe du cerveau, et sans préfixe on ne rend pas un état, on rend
# « inconnu » avec sa raison. Ne pas savoir n'est pas « inactif ».
_SUFFIXE_CURATEUR = "cycle"


def _unite_curateur() -> str | None:
    """L'unité de digestion de CE cerveau, ou None si on ignore laquelle."""
    prefixe = (os.environ.get("ARAC_UNIT_PREFIX") or "").strip()
    if not prefixe:
        return None
    # Une variable dédiée reste possible pour une installation qui aurait
    # nommé son unité autrement ; elle l'emporte, mais elle n'invente rien.
    explicite = (os.environ.get("ARAC_UNIT_CURATEUR") or "").strip()
    return explicite or f"{prefixe}-{_SUFFIXE_CURATEUR}"


def _curator_service() -> dict[str, Any]:
    """État systemd du curateur (lecture seule via systemctl is-active/is-enabled)."""
    unite = _unite_curateur()
    if not unite:
        raison = "ARAC_UNIT_PREFIX absente : on ignore de quel cerveau lire l'unité"
        return {
            "service_active": _UNKNOWN,
            "timer_active": _UNKNOWN,
            "timer_enabled": _UNKNOWN,
            "unit": None,
            "reason": raison,
        }

    def one(unit: str, verb: str) -> str:
        r = system_metrics._run_readonly(["systemctl", verb, unit])
        out = (r.get("stdout") or "").strip()
        return out or r.get("error") or _UNKNOWN
    return {
        "service_active": one(f"{unite}.service", "is-active"),
        "timer_active": one(f"{unite}.timer", "is-active"),
        "timer_enabled": one(f"{unite}.timer", "is-enabled"),
        "unit": unite,
    }


def sobriety_summary() -> dict[str, Any]:
    """Vue de sobriété complète pour le cockpit (jamais d'exception)."""
    db = _db_sobriety()
    claude = _claude_running()
    svc = _curator_service()
    env_allow = os.environ.get("ARAC_ALLOW_PAID_AI", "").strip().lower() in (
        "1", "true", "yes", "on")
    armed = bool(env_allow) and (db.get("paid_ai_enabled") is True)
    return {
        "paid_ai_armed": armed,
        "env_allow": env_allow,
        "paid_ai_enabled": db.get("paid_ai_enabled"),
        "backlog": {k: db.get(k) for k in
                    ("last_received", "pending", "processing", "failed",
                     "curated_today", "actionable")},
        "claude_running": claude,
        "curator_service": svc,
        "db_error": db.get("error"),
    }
