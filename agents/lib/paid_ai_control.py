"""Control-plane opérateur de l'IA payante du cerveau ARAC (sobriété).

LE GESTE QUI ARME L'IA PAYANTE EST ICI, ET IL DOIT MARCHER SANS PRÉPARATIF.
Un utilisateur qui vient de lire « votre cycle est refusé : l'interrupteur 2
n'est pas armé » ne va pas d'abord exporter des DSN à la main. Toutes les
sous-commandes acceptent donc `--coffre <fichier d'environnement>` — le
`/etc/arac/<votre-base>/arac.env` que le bootstrap a écrit — et en tirent
elles-mêmes ce qu'il leur faut. Sans l'option, on cherche `ARAC_ENV_FILE`,
puis `/etc/arac/$ARAC_DB/arac.env`. Un remède qui suppose un environnement
déjà chargé est un remède qui ne sera pas joué.

Sous-commandes (à lancer par l'opérateur, root) :

  kill        Pose le KILL-SWITCH fichier (STOP immédiat de tout spawn Claude)
              + désarme le flag DB paid_ai_enabled. Aucune suppression auto.
  arm         Retire le kill-switch + arme paid_ai_enabled=true (--confirm requis).
  disarm      Désarme paid_ai_enabled=false (laisse le kill-switch tel quel).
  status      État synthétique : flag DB, kill-switch, budget du jour, backlog.
  cost-audit  Rapport détaillé du jour : runs/items/spawns/tokens, backlog,
              coût estimé, process `claude` actifs (par utilisateur).

Aucune de ces commandes n'appelle d'IA. `kill` fonctionne même sans DB
(le fichier suffit à stopper le curateur au prochain tick).
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import sys
from datetime import datetime, timezone

import arac_runtime

from agents.lib import spend_guard as sg  # noqa: E402
from agents.lib import paid_ai_flag  # noqa: E402
from agents.lib import kill_switch  # noqa: E402
from agents.lib import claude_cli  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ledger():
    """Ledger de dépense — run_receipts en DB (le fichier
    ai_spend_ledger.json est MORT : le cortex n'y écrit plus). Fallback
    fichier seulement si aucun DSN (lecture d'un état historique)."""
    dsn = (os.environ.get("DATABASE_URL_READONLY")
           or os.environ.get("DATABASE_URL_APP"))
    if dsn:
        return sg.RunReceiptLedger(dsn)
    runtime_dir = os.environ.get("ARAC_BRAIN_RUNTIME_DIR", sg.DEFAULT_RUNTIME_DIR)
    return sg.SpendLedger(os.path.join(runtime_dir, "ai_spend_ledger.json"))


def _kill_path() -> str:
    return os.environ.get("ARAC_KILL_PAID_AI_PATH", sg.DEFAULT_KILL_SWITCH)


def coffre_par_defaut() -> str:
    """Le fichier d'environnement de CE cerveau, deviné aussi peu que possible."""
    depuis_env = os.environ.get("ARAC_ENV_FILE", "").strip()
    if depuis_env:
        return depuis_env
    base = os.environ.get("ARAC_DB", "").strip()
    return f"/etc/arac/{base}/arac.env" if base else ""


def charger_coffre(chemin: str | None, *, exige: bool = False) -> str:
    """Verse dans l'environnement ce que le coffre du cerveau contient.

    Ne REMPLACE jamais une variable déjà posée (l'appelant reste maître), et
    ne lit que ce qui appartient à ce cerveau : `DATABASE_URL_*` et `ARAC_*`.
    Retourne le chemin réellement lu, ou "".

    Le fichier est en 0600 root:root — d'où le message explicite si la lecture
    échoue : « lancez-le avec sudo » vaut mieux qu'un « aucune DSN » qui
    n'apprend rien.
    """
    chemin = (chemin or coffre_par_defaut()).strip()
    if not chemin:
        if exige:
            print("Refus : aucun coffre nommé (--coffre) et ni ARAC_ENV_FILE ni "
                  "ARAC_DB dans l'environnement.", file=sys.stderr)
        return ""
    try:
        brut = open(chemin, encoding="utf-8", errors="replace").read()
    except PermissionError:
        print(f"Refus : {chemin} n'est pas lisible par ce compte (il est en 0600). "
              "Relancez avec sudo.", file=sys.stderr)
        return ""
    except OSError as e:
        if exige:
            print(f"Refus : coffre illisible ({chemin}) : {type(e).__name__}.",
                  file=sys.stderr)
        return ""
    for ligne in brut.splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, _, valeur = ligne.partition("=")
        cle = cle.strip()
        if not (cle.startswith("DATABASE_URL_") or cle.startswith("ARAC_")):
            continue
        if os.environ.get(cle):
            continue
        os.environ[cle] = valeur.strip().strip('"').strip("'")
    return chemin


def _connect(dsn_env_order=("DATABASE_URL_ADMIN", "DATABASE_URL_APP",
                            "DATABASE_URL_READONLY")):
    """Connexion sync psycopg via la 1re DSN dispo. None si aucune."""
    dsn = next((os.environ[k] for k in dsn_env_order if os.environ.get(k)), None)
    if not dsn:
        return None
    try:
        import psycopg
        return psycopg.connect(dsn)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] connexion DB impossible: {type(e).__name__}: {e}", file=sys.stderr)
        return None


def _backlog(conn) -> dict:
    """Compteurs file V2 (read-only), 2026-07-03.

    La file vivante est arac.conversations/raw_messages (curseurs watermark) ;
    le legacy raw_conversations est GELÉ (lignée). Mapping sémantique :
      pending      -> conversations avec >=1 message non curé (arithmétique
                      de curseur, indépendamment des fenêtres du gate)
      processing   -> n'existe plus en v2 (pas de claim) : 0 constant
      failed       -> dead-letter (retry épuisé, non acquitté)
      actionable   -> RÉELLEMENT éligibles au prochain batch (gate complet :
                      calme+min OU plafond d'âge, >=1 msg non vide, backoff)
    """
    _eligible_gate = (
        "SELECT count(*) FROM ( "
        "  SELECT c.id FROM arac.conversations c "
        "  JOIN arac.raw_messages m ON m.conversation_id = c.id "
        "  WHERE c.acked = false AND c.retry_count < 5 "
        # les conversations exclues-tracées sortent du backlog affiché
        # (même prédicat que le gate curateur et ses miroirs watchdog/audit).
        "    AND c.exclusion_category IS NULL "
        "    AND (c.next_retry_at IS NULL OR c.next_retry_at <= now()) "
        "  GROUP BY c.id "
        "  HAVING count(*) FILTER (WHERE m.id > c.curated_through_message_id) >= 1 "
        "     AND count(*) FILTER (WHERE m.id > c.curated_through_message_id "
        "                          AND btrim(m.content) <> '') >= 1 "
        "     AND ( "
        "          (now() - max(COALESCE(m.msg_created_at, m.received_at)) "
        "                 >= interval '2 hours' "
        "           AND count(*) FILTER (WHERE m.id > c.curated_through_message_id) >= 3) "
        "          OR min(COALESCE(m.msg_created_at, m.received_at)) "
        "               FILTER (WHERE m.id > c.curated_through_message_id) "
        "               <= now() - interval '24 hours' "
        "     ) "
        ") sub"
    )
    q = {
        "last_received": "SELECT max(received_at) FROM arac.raw_messages",
        "pending": "SELECT count(*) FROM ( "
                   "  SELECT c.id FROM arac.conversations c "
                   "  JOIN arac.raw_messages m ON m.conversation_id = c.id "
                   "  WHERE c.acked = false GROUP BY c.id "
                   "  HAVING count(*) FILTER (WHERE m.id > c.curated_through_message_id) >= 1"
                   ") sub",
        "processing": "SELECT 0",
        "failed": "SELECT count(*) FROM arac.conversations "
                  "WHERE retry_count >= 5 AND acked = false",
        "curated_today": "SELECT count(*) FROM arac.conversations "
                         "WHERE curated_at::date = (now() at time zone 'utc')::date",
        "actionable": _eligible_gate,
    }
    out = {}
    with conn.cursor() as cur:
        for k, sql in q.items():
            try:
                cur.execute(sql)
                out[k] = cur.fetchone()[0]
            except Exception as e:  # noqa: BLE001
                out[k] = f"err:{type(e).__name__}"
                conn.rollback()
    return out


def _claude_procs() -> list[dict]:
    """Scan /proc : process `claude` en cours, avec l'utilisateur propriétaire.
    Sans subprocess. Sert à répondre 'Claude actif ?'. Le curateur tourne sous
    `aracagent` ; une session opérateur sous `root` — on distingue par uid.
    """
    procs = []
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return procs
    for pid in pids:
        cl = f"/proc/{pid}/cmdline"
        try:
            with open(cl, "rb") as fh:
                raw = fh.read()
        except OSError:
            continue
        parts = raw.split(b"\x00")
        argv = [p.decode("utf-8", "replace") for p in parts if p]
        if not argv:
            continue
        exe = argv[0]
        if "claude" not in os.path.basename(exe) and not any("claude" in a for a in argv[:2]):
            continue
        # cible : le binaire claude (pas ce script python).
        if os.path.basename(exe) not in ("claude", "node") and "/claude" not in exe:
            continue
        try:
            uid = os.stat(cl).st_uid
            user = pwd.getpwuid(uid).pw_name
        except (OSError, KeyError):
            user = "?"
        procs.append({"pid": int(pid), "user": user,
                      "cmd": " ".join(argv[:4])[:120]})
    return procs


def _flag_enabled(conn) -> bool | None:
    if conn is None:
        return None
    try:
        return paid_ai_flag.read_paid_ai_enabled(conn)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] lecture flag: {type(e).__name__}: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Sous-commandes
# ---------------------------------------------------------------------------


def cmd_kill(args) -> int:
    path = kill_switch.resolve_switch_path(_kill_path())  # valide le confinement
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "reason": args.reason or "operator_kill",
            "created_at": _now().isoformat(),
            "created_by": os.environ.get("SUDO_USER") or os.environ.get("USER") or "operator",
        }, ensure_ascii=False, indent=2))
    print(f"[KILL] kill-switch posé : {path}")
    conn = _connect()
    if conn is not None:
        try:
            paid_ai_flag.set_paid_ai_enabled(conn, False, updated_by="arac-kill-paid-ai")
            print("[KILL] flag DB paid_ai_enabled = false")
        finally:
            conn.close()
    else:
        print("[KILL] (pas de DB — le fichier kill-switch suffit à stopper le curateur)")
    print("[KILL] Le curateur ne spawnera plus aucun Claude. Pour revenir en "
          "arrière : " + sg.geste_control_plane("arm --confirm",
                                                env_file=coffre_par_defaut()))
    return 0


def cmd_arm(args) -> int:
    if not args.confirm:
        print("Refus : `arm` exige --confirm (armer l'IA payante = dépense réelle).",
              file=sys.stderr)
        return 2
    path = kill_switch.resolve_switch_path(_kill_path())
    if os.path.isfile(path):
        os.remove(path)
        print(f"[ARM] kill-switch retiré : {path}")
    conn = _connect()
    if conn is None:
        print("Refus : DB requise pour armer le flag (DATABASE_URL_ADMIN).", file=sys.stderr)
        return 2
    try:
        paid_ai_flag.set_paid_ai_enabled(conn, True, updated_by="arac-arm-paid-ai")
    finally:
        conn.close()
    print("[ARM] flag DB paid_ai_enabled = true  (INTERRUPTEUR 2 sur 2 — ouvert)")
    # LE RAPPEL NE SUFFISAIT PAS, ET C'EST MESURÉ. « l'unité systemd doit aussi
    # porter ARAC_ALLOW_PAID_AI=1 » laissait le lecteur devant deux questions
    # sans réponse : est-ce mon cas ? et où ? On CONSTATE l'état du premier
    # interrupteur, et on nomme le fichier de CE cerveau.
    coffre = coffre_par_defaut()
    if _env_allow():
        print(f"[ARM] INTERRUPTEUR 1 sur 2 (ARAC_ALLOW_PAID_AI) : déjà ouvert. "
              f"Le prochain cycle pourra dépenser.")
    else:
        print("[ARM] ATTENTION — l'INTERRUPTEUR 1 sur 2 est encore FERMÉ : "
              "ARAC_ALLOW_PAID_AI n'est pas vrai dans l'environnement lu ici. "
              "Tant qu'il l'est, le cycle refusera sur `master_switch_env_off` "
              "et ne produira aucun souvenir.")
        print(f"[ARM] Le geste : sudo sed -i "
              f"'s/^ARAC_ALLOW_PAID_AI=.*/ARAC_ALLOW_PAID_AI=1/' "
              f"{coffre or '/etc/arac/<votre-base>/arac.env'}")
    return 0


def _env_allow() -> bool:
    return os.environ.get("ARAC_ALLOW_PAID_AI", "").strip().lower() in (
        "1", "true", "yes", "on")


def cmd_disarm(args) -> int:
    conn = _connect()
    if conn is None:
        print("Refus : DB requise (DATABASE_URL_ADMIN).", file=sys.stderr)
        return 2
    try:
        paid_ai_flag.set_paid_ai_enabled(conn, False, updated_by="arac-disarm-paid-ai")
    finally:
        conn.close()
    print("[DISARM] flag DB paid_ai_enabled = false (kill-switch inchangé).")
    return 0


def _gather(args) -> dict:
    conn = _connect()
    try:
        snap = _ledger().snapshot(_now())
        cfg = sg.BudgetConfig.from_env()
        procs = _claude_procs()
        aracagent_claude = [p for p in procs if p["user"] == "aracagent"]
        report = {
            "date": snap["date"],
            "paid_ai": {
                "env_allow": _env_allow(),
                "config_enabled": _flag_enabled(conn),
                "kill_switch_active": os.path.isfile(kill_switch.resolve_switch_path(_kill_path())),
                "kill_switch_path": kill_switch.resolve_switch_path(_kill_path()),
            },
            "budget": {
                "runs": f"{snap['runs']}/{cfg.max_runs_per_day}",
                "items": f"{snap['items']}/{cfg.max_items_per_day}",
                "spawns": f"{snap['spawns']}/{cfg.max_spawns_per_day}",
                "tokens": f"{snap['tokens']}/{cfg.daily_token_budget}",
                "last_run_at_epoch": snap["last_run_at_epoch"],
                "last_outcome": snap["last_outcome"],
            },
            "claude_running": {
                "total": len(procs),
                "curator_aracagent": len(aracagent_claude),
                "procs": procs,
            },
        }
        price = os.environ.get("ARAC_TOKEN_PRICE_PER_1K")
        if price:
            try:
                report["budget"]["estimated_cost_today"] = round(
                    snap["tokens"] / 1000.0 * float(price), 4)
            except ValueError:
                pass
        if conn is not None:
            report["backlog"] = _backlog(conn)
        return report
    finally:
        if conn is not None:
            conn.close()


def cmd_status(args) -> int:
    r = _gather(args)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
        return 0
    p = r["paid_ai"]
    armed = p["env_allow"] and p["config_enabled"] and not p["kill_switch_active"]
    print(f"=== ARAC brain sobriety — {r['date']} (UTC) ===")
    print(f"IA payante ARMÉE : {'OUI' if armed else 'NON'}  "
          f"(env_allow={p['env_allow']} config={p['config_enabled']} "
          f"kill_switch={'ACTIF' if p['kill_switch_active'] else 'off'})")
    # CE QUI ARRÊTE, ET LE GESTE — pas seulement trois booléens. Un état
    # « NON » qui n'apprend pas lequel des trois freins tient, c'est le mur
    # devant lequel un utilisateur a laissé son cerveau ne rien apprendre.
    if not armed:
        coffre = coffre_par_defaut() or "/etc/arac/<votre-base>/arac.env"
        if not p["env_allow"]:
            print("  → " + sg.remede_pour("master_switch_env_off", env_file=coffre))
        elif not p["config_enabled"]:
            print("  → " + sg.remede_pour("master_switch_config_off", env_file=coffre))
        else:
            print("  → " + sg.remede_pour("kill_switch_active", env_file=coffre,
                                          kill_switch_path=p["kill_switch_path"]))
    # LE PRÉREQUIS QUE PERSONNE NE VÉRIFIAIT : la curation n'appelle aucune
    # API, elle lance un binaire. Armé ou non, sans lui rien ne sera digéré.
    dispo, chemin, remede = claude_cli.curation_disponible()
    print(f"Curation (binaire): {'OUI' if dispo else 'NON'} — {chemin}")
    if not dispo:
        print(f"  → {remede}")
    b = r["budget"]
    print(f"Budget jour     : runs {b['runs']} · items {b['items']} · "
          f"spawns {b['spawns']} · tokens {b['tokens']}")
    print(f"Dernier verdict : {b['last_outcome']}")
    c = r["claude_running"]
    print(f"Claude actif    : total={c['total']} · curateur(aracagent)={c['curator_aracagent']}")
    if "backlog" in r:
        bl = r["backlog"]
        print(f"Backlog         : pending={bl.get('pending')} processing={bl.get('processing')} "
              f"failed={bl.get('failed')} actionable={bl.get('actionable')} "
              f"curated_aujd={bl.get('curated_today')}")
        print(f"Dernière conv   : {bl.get('last_received')}")
    return 0


def cmd_cost_audit(args) -> int:
    r = _gather(args)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
        return 0
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    # `--coffre` est déclaré une fois et hérité par chaque sous-commande : il
    # s'écrit donc AVANT comme APRÈS le verbe. Personne ne devrait avoir à
    # deviner la place d'une option dans un remède qu'on vient de lui donner.
    commun = argparse.ArgumentParser(add_help=False)
    # `default=SUPPRESS` n'est pas un raffinement : sans lui, le défaut de la
    # SOUS-commande écrase la valeur lue par le parser principal, et
    # `… --coffre X arm --confirm` repart avec coffre=None (mesuré).
    commun.add_argument(
        "--coffre", default=argparse.SUPPRESS, metavar="FICHIER",
        help="Le fichier d'environnement du cerveau (/etc/arac/<base>/arac.env). "
             "À défaut : $ARAC_ENV_FILE, puis /etc/arac/$ARAC_DB/arac.env.")
    p = argparse.ArgumentParser(
        parents=[commun],
        description="Control-plane IA payante — cerveau ARAC (sobriété).")
    sub = p.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("kill", parents=[commun],
                       help="STOP immédiat (kill-switch + désarme flag)")
    k.add_argument("--reason", default=None)
    k.set_defaults(func=cmd_kill)
    a = sub.add_parser("arm", parents=[commun],
                       help="Arme l'IA payante (--confirm requis)")
    a.add_argument("--confirm", action="store_true")
    a.set_defaults(func=cmd_arm)
    d = sub.add_parser("disarm", parents=[commun],
                       help="Désarme le flag (kill-switch inchangé)")
    d.set_defaults(func=cmd_disarm)
    s = sub.add_parser("status", parents=[commun], help="État synthétique")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_status)
    c = sub.add_parser("cost-audit", parents=[commun],
                       help="Rapport détaillé du jour")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_cost_audit)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    # Le coffre est versé AVANT la sous-commande : c'est lui qui porte les DSN,
    # le chemin du kill-switch et l'état de l'interrupteur côté service.
    charger_coffre(getattr(args, "coffre", None), exige=bool(getattr(args, "coffre", None)))
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
