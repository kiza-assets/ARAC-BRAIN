#!/usr/bin/env python3
"""LES QUATRE ALARMES — ce qui mérite de réveiller quelqu'un.

    scripts/ops/alerts.py             les alarmes, en clair
    scripts/ops/alerts.py --json      pour une machine
    scripts/ops/alerts.py --explain   les seuils, et d'où ils viennent

CODES DE SORTIE   0 rien à signaler · 1 au moins une alarme · 3 impossible de juger

CE QUE CE FICHIER N'EST PAS
---------------------------
Ce n'est pas un doublon de `scripts/ops/health_check.py`. Celui-ci lit les 148
métriques du cockpit et dit « comment va le cerveau » — c'est un bulletin de
santé, qu'on regarde quand on se pose la question.

Les alarmes ci-dessous répondent à une autre question, beaucoup plus étroite :
**qu'est-ce qui doit vous chercher, vous, alors que vous ne regardiez pas ?**
Elles sont peu nombreuses, et c'est délibéré. Une liste d'alarmes qu'on finit
par ignorer ne protège plus rien ; elle apprend juste à ignorer les alarmes.

Chacune est une CONJONCTION, pas un seuil isolé. « Aucun atome depuis 48 h »
n'est pas une panne : c'est peut-être un week-end sans conversation. « Aucun
atome depuis 48 h ALORS QUE des conversations attendent » est une panne, parce
que le cerveau avait de quoi apprendre et n'a rien appris.

D'OÙ VIENNENT LES SEUILS
------------------------
Aucun n'est une convention. Deux se déduisent d'une cadence observable, un se
calcule sur VOTRE historique, un se calibre tout seul sur votre propre base. Le
détail est dans `--explain`, et dans le corps de chaque fonction.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# --- OÙ EST LE COFFRE ------------------------------------------------------
#
# Cette sonde ne lisait que `DATABASE_URL_READONLY` dans son environnement.
# Or ce DSN vit dans `/etc/arac/<base>/arac.env`, en 0600 root : lancée telle
# que `docs/EXPLOITATION.md` §1 et §3 l'écrivent, elle rendait « UNKNOWN » et
# le code 3 sur un cerveau parfaitement sain — y compris préfixée de
# `ARAC_ENV_FILE`, la variable que tout le reste d'`ops/` enseigne. La
# troisième des « cinq commandes qu'on peut lancer cent fois » ne pouvait pas
# se lancer une seule fois. Le renseignement existait chez sa voisine
# (`health_check.py`) ; il n'avait pas voyagé jusqu'ici. Il vit désormais dans
# `scripts/ops/coffre.py`, une seule fois, et les deux sondes l'importent.
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import coffre as _coffre  # noqa: E402


# ===========================================================================
# Réglages — chacun explicable, aucun arbitraire
# ===========================================================================

#: Silence d'apprentissage toléré, en heures.
#:
#: Le cerveau de référence digère par CYCLES, pas en continu : trois par jour
#: (04:00, 13:00, 21:00). 48 h, ce sont donc SIX cycles consécutifs qui n'ont
#: produit aucun atome. Un cycle stérile est banal — sur ce même cerveau, 36 %
#: des cycles sont partis en quarantaine sans rien produire. Six d'affilée ne
#: l'est pas : si les cycles étaient indépendants au même taux d'échec, cela
#: arriverait une fois sur cinq cents.
#:
#: Si vous digérez une fois par jour, 48 h ne valent plus que deux cycles :
#: montez ce seuil à 72 ou 96 h, sinon vous serez réveillé pour rien.
STALL_HOURS = int(os.environ.get("ARAC_ALERT_STALL_HOURS", "48"))

#: Probabilité en dessous de laquelle une série d'échecs cesse d'être de la
#: malchance. On ne fixe PAS « trois échecs d'affilée » : trois échecs sur un
#: cerveau qui en rate 36 % arrivent une fois par semaine (0,36³ ≈ 4,7 %), et
#: une alarme hebdomadaire finit ignorée. On calcule votre taux d'échec réel, et
#: on alerte quand la série observée devient improbable à ce taux-là.
STREAK_P = float(os.environ.get("ARAC_ALERT_STREAK_P", "0.01"))

#: Longueur minimale d'une série pour qu'on la regarde, quelle que soit la
#: probabilité. Deux échecs consécutifs sur un cerveau très fiable seraient déjà
#: « improbables » — c'est trop tôt pour crier.
STREAK_MIN = int(os.environ.get("ARAC_ALERT_STREAK_MIN", "3"))

#: Nombre de cycles nécessaires avant de pouvoir estimer un taux d'échec.
#: En dessous, l'alarme dit « non calibrée » — elle ne devine pas.
STREAK_MIN_HISTORY = int(os.environ.get("ARAC_ALERT_STREAK_HISTORY", "10"))

#: Facteur de croissance anormale de la base. La base grossit tous les jours :
#: c'est le signe qu'elle vit. Ce qui alarme, c'est un jour qui ne ressemble à
#: aucun autre. On compare donc la croissance du jour à la MÉDIANE de vos
#: croissances quotidiennes — la médiane, pas la moyenne, pour qu'un seul jour
#: d'import massif ne relève pas le seuil pour toujours.
GROWTH_FACTOR = float(os.environ.get("ARAC_ALERT_GROWTH_FACTOR", "5"))

#: Plancher absolu de croissance, en octets. En dessous, on ne dit rien même si
#: le facteur est dépassé : sur une base jeune, passer de 2 à 20 Mio est un
#: facteur 10 et n'a aucune importance.
GROWTH_FLOOR = int(os.environ.get("ARAC_ALERT_GROWTH_FLOOR", str(100 * 1024 * 1024)))

#: Nombre de mesures nécessaires avant que l'alarme de croissance ait un sens.
#: Sept jours : une semaine complète, week-end compris.
GROWTH_MIN_SAMPLES = int(os.environ.get("ARAC_ALERT_GROWTH_SAMPLES", "7"))

#: Silence d'ingestion toléré, en heures. La synchronisation depuis le poste
#: source tourne au moins une fois par jour. 26 h = un passage manqué + 2 h de
#: marge. Au-delà, ce n'est plus « vous n'avez pas travaillé » : c'est le pont
#: entre votre machine et le serveur qui est coupé — tunnel SSH tombé, tâche
#: planifiée désactivée, jeton de nœud révoqué.
INGEST_SILENCE_HOURS = int(os.environ.get("ARAC_ALERT_INGEST_SILENCE_HOURS", "26"))


# ===========================================================================
# Socle
# ===========================================================================

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _state_dir() -> Path:
    """Où l'on garde la mémoire des mesures. Sans état, pas de calibration."""
    import arac_runtime

    d = Path(os.environ.get("ARAC_ALERT_STATE") or (arac_runtime.var_dir() / "alerts"))
    d.mkdir(parents=True, exist_ok=True)
    return d


class Alarm:
    """Une alarme : ce qui ne va pas, pourquoi c'est le seuil, et quoi regarder."""

    def __init__(self, key: str, level: str, title: str, detail: str,
                 threshold: str, evidence: str = "") -> None:
        self.key, self.level, self.title = key, level, title
        self.detail, self.threshold, self.evidence = detail, threshold, evidence

    def as_dict(self) -> dict:
        return {"key": self.key, "level": self.level, "title": self.title,
                "detail": self.detail, "threshold": self.threshold,
                "evidence": self.evidence}


# ===========================================================================
# 1. Le cerveau a cessé d'apprendre
# ===========================================================================

def alarm_learning_stalled(cur, schema: str) -> Alarm | None:
    """Aucun atome depuis N heures ALORS QUE des conversations attendent.

    La conjonction est tout. Un cerveau qui n'apprend rien parce qu'on ne lui a
    rien donné se porte bien ; un cerveau qui n'apprend rien avec une file
    pleine est en panne. Sans cette seconde condition, l'alarme sonnerait
    pendant chaque vacances, et on la couperait.
    """
    cur.execute(f"""
        SELECT round((extract(epoch FROM now() - max(created_at)) / 3600.0)::numeric, 1)
          FROM {schema}.memory_atoms
         WHERE kind <> 'agent_message'
    """)
    row = cur.fetchone()
    age_h = float(row[0]) if row and row[0] is not None else None

    cur.execute(f"""
        SELECT count(*)
          FROM {schema}.conversations c
         WHERE c.curated_through_message_id IS NULL
            OR c.curated_through_message_id < (
                   SELECT max(rm.id) FROM {schema}.raw_messages rm
                    WHERE rm.conversation_id = c.id)
    """)
    backlog = cur.fetchone()[0]

    if age_h is None:
        if backlog > 0:
            return Alarm(
                "learning_stalled", "critical",
                "Le cerveau n'a JAMAIS appris",
                f"Aucun atome en base, et {backlog} conversation(s) attendent d'être lues. "
                "La digestion n'a jamais produit — vérifiez que ARAC_ALLOW_PAID_AI vaut 1 "
                "et que la clé de curation est valide.",
                "aucun atome + file non vide",
                f"SELECT count(*) FROM {schema}.run_receipts ORDER BY 1;",
            )
        return None

    if age_h >= STALL_HOURS and backlog > 0:
        return Alarm(
            "learning_stalled", "critical",
            "Le cerveau a cessé d'apprendre",
            f"Dernier atome il y a {age_h:g} h, et {backlog} conversation(s) attendent. "
            "Il avait de quoi apprendre et n'a rien appris.",
            f"≥ {STALL_HOURS} h sans atome ET file de curation non vide",
            f"""SELECT id, slot_key, status, stop_reason, started_at, atoms_created
  FROM {schema}.run_receipts ORDER BY started_at DESC LIMIT 10;""",
        )

    if age_h >= STALL_HOURS:
        return Alarm(
            "learning_idle", "info",
            "Le cerveau se repose",
            f"Dernier atome il y a {age_h:g} h, mais la file est vide : il n'a rien à digérer. "
            "L'état de repos est normal — un cerveau digère par cycles, pas en continu.",
            f"≥ {STALL_HOURS} h sans atome, file vide → pas une alarme",
        )
    return None


# ===========================================================================
# 2. Les cycles échouent en série
# ===========================================================================

def alarm_failure_streak(cur, schema: str) -> Alarm | None:
    """Une série d'échecs trop longue pour être de la malchance.

    On mesure VOTRE taux d'échec, puis on calcule la probabilité de la série
    observée à ce taux. C'est la seule façon d'avoir un seuil qui reste juste
    quand votre cerveau devient meilleur : sur un cerveau qui rate un cycle sur
    trois, trois échecs d'affilée sont banals ; sur un cerveau qui en rate un
    sur vingt, deux d'affilée sont déjà un signal.
    """
    cur.execute(f"""
        SELECT count(*), count(*) FILTER (WHERE status <> 'done')
          FROM {schema}.run_receipts
         WHERE status <> 'started'
    """)
    total, failed = cur.fetchone()
    if not total or total < STREAK_MIN_HISTORY:
        return None  # non calibrée : on ne devine pas un taux sur trois cycles

    cur.execute(f"""
        SELECT status FROM {schema}.run_receipts
         WHERE status <> 'started'
         ORDER BY started_at DESC LIMIT 50
    """)
    streak = 0
    for (status,) in cur.fetchall():
        if status == "done":
            break
        streak += 1

    if streak < STREAK_MIN:
        return None

    p = failed / total
    proba = p ** streak
    if proba >= STREAK_P:
        return None

    return Alarm(
        "failure_streak", "critical",
        f"{streak} cycles de digestion ratés d'affilée",
        f"Votre taux d'échec habituel est de {p * 100:.0f} %. Une série de {streak} "
        f"a une probabilité de {proba * 100:.2f} % si les cycles étaient indépendants. "
        "Ce n'est plus de la malchance : cherchez une cause commune — identifiants "
        "incohérents dans la tranche, quota atteint, tranche trop grosse.",
        f"probabilité de la série < {STREAK_P * 100:g} % au taux d'échec observé "
        f"(et série ≥ {STREAK_MIN})",
        f"""SELECT id, slot_key, status, stop_reason, quarantine_errors, started_at
  FROM {schema}.run_receipts WHERE status <> 'done'
 ORDER BY started_at DESC LIMIT {max(streak, 5)};""",
    )


# ===========================================================================
# 3. La base grossit anormalement
# ===========================================================================

def alarm_growth(cur, schema: str) -> Alarm | None:
    """Une croissance sans commune mesure avec l'habitude.

    Personne ne peut dire quelle taille doit faire votre cerveau, ni à quelle
    vitesse il doit grossir : cela dépend de combien vous parlez. Un seuil en
    gigaoctets serait donc faux pour tout le monde. On garde à la place un
    registre local des tailles quotidiennes, et on compare le jour au reste.

    Tant qu'il n'y a pas une semaine de mesures, l'alarme le DIT au lieu de se
    taire : « pas encore calibrée » est une information, « rien à signaler » sur
    une mesure impossible est un mensonge.
    """
    cur.execute("SELECT pg_database_size(current_database())")
    size = int(cur.fetchone()[0])

    ledger = _state_dir() / "db_size"
    samples: list[tuple[float, int]] = []
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            try:
                ts, val = line.split()
                samples.append((float(ts), int(val)))
            except ValueError:
                continue

    now_ts = _now().timestamp()
    # Une mesure par jour au plus : le registre doit décrire des journées, pas
    # des exécutions. Sinon un chien de garde toutes les 30 minutes remplirait
    # la médiane de zéros et rendrait la moindre croissance « anormale ».
    if not samples or (now_ts - samples[-1][0]) >= 20 * 3600:
        with ledger.open("a", encoding="utf-8") as fh:
            fh.write(f"{now_ts:.0f} {size}\n")
        samples.append((now_ts, size))
        if len(samples) > 120:
            ledger.write_text(
                "".join(f"{t:.0f} {v}\n" for t, v in samples[-120:]), encoding="utf-8"
            )

    if len(samples) < GROWTH_MIN_SAMPLES:
        return Alarm(
            "growth_uncalibrated", "info",
            "Croissance de la base : pas encore calibrée",
            f"{len(samples)} mesure(s) sur les {GROWTH_MIN_SAMPLES} nécessaires. "
            f"Taille actuelle : {size / 1024 / 1024:.0f} Mio. "
            "Cette alarme ne peut rien dire tant qu'elle n'a pas vu une semaine.",
            f"≥ {GROWTH_MIN_SAMPLES} mesures quotidiennes requises",
        )

    deltas: list[int] = []
    for (t0, v0), (t1, v1) in zip(samples, samples[1:]):
        days = max((t1 - t0) / 86400.0, 0.1)
        deltas.append(int((v1 - v0) / days))
    if len(deltas) < 2:
        return None

    ordered = sorted(deltas[:-1])  # l'habitude, sans le jour qu'on juge
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) // 2
    today = deltas[-1]

    if today < GROWTH_FLOOR:
        return None
    if median <= 0 or today < GROWTH_FACTOR * median:
        return None

    return Alarm(
        "growth_abnormal", "warn",
        "La base grossit anormalement",
        f"+{today / 1024 / 1024:.0f} Mio depuis la dernière mesure, contre "
        f"+{median / 1024 / 1024:.1f} Mio d'habitude (médiane). "
        "Causes fréquentes, dans l'ordre : un import massif, une boucle de "
        "ré-ingestion qui redépose les mêmes messages, un recalcul complet des "
        "embeddings (3072 dimensions par atome, c'est ce qui pèse).",
        f"croissance > {GROWTH_FACTOR:g} × la médiane ET > "
        f"{GROWTH_FLOOR / 1024 / 1024:.0f} Mio",
        f"""SELECT relname, pg_size_pretty(pg_total_relation_size(c.oid)) AS taille
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = '{schema}' AND c.relkind = 'r'
 ORDER BY pg_total_relation_size(c.oid) DESC LIMIT 10;""",
    )


# ===========================================================================
# 4. Plus rien n'entre
# ===========================================================================

def alarm_ingest_silence(cur, schema: str) -> Alarm | None:
    """Aucune conversation reçue depuis N heures.

    Distincte de l'alarme d'apprentissage : là, le cerveau ne digère plus ; ici,
    il ne REÇOIT plus. Les causes sont ailleurs — tunnel SSH tombé, tâche
    planifiée du poste source désactivée, jeton de nœud révoqué. Un cerveau qui
    ne reçoit plus finit par se taire, mais des semaines plus tard : c'est
    exactement le genre de panne qu'on découvre trop tard.
    """
    cur.execute(f"""
        SELECT round((extract(epoch FROM now() - max(received_at)) / 3600.0)::numeric, 1)
          FROM {schema}.raw_messages
    """)
    row = cur.fetchone()
    if not row or row[0] is None:
        return Alarm(
            "ingest_never", "critical",
            "Aucune conversation n'est jamais entrée",
            "La table des messages est vide. La chaîne poste source → tunnel → "
            "API n'a jamais fonctionné, ou n'a jamais été lancée.",
            "aucun message en base",
            f"SELECT outcome, count(*) FROM {schema}.ingest_receipts GROUP BY 1;",
        )
    age_h = float(row[0])
    if age_h < INGEST_SILENCE_HOURS:
        return None

    cur.execute(f"""
        SELECT outcome, count(*) FROM {schema}.ingest_receipts
         WHERE created_at > now() - interval '7 days'
         GROUP BY 1 ORDER BY 2 DESC LIMIT 3
    """)
    recent = ", ".join(f"{o}={n}" for o, n in cur.fetchall()) or "aucun reçu d'ingestion"

    return Alarm(
        "ingest_silence", "critical",
        "Plus aucune conversation n'entre",
        f"Dernier message reçu il y a {age_h:g} h. Reçus des 7 derniers jours : {recent}. "
        "Le cerveau ne se tait pas encore — il digère ce qu'il a — mais il est déjà coupé "
        "de sa source.",
        f"≥ {INGEST_SILENCE_HOURS} h sans message reçu "
        "(une synchronisation quotidienne + 2 h de marge)",
        f"""SELECT node_id, max(received_at) AS dernier, count(*) AS messages
  FROM {schema}.raw_messages GROUP BY 1 ORDER BY 2 DESC;""",
    )


CHECKS = (alarm_learning_stalled, alarm_failure_streak, alarm_growth, alarm_ingest_silence)


# ===========================================================================
# Entrée
# ===========================================================================

_EXPLAIN = f"""LES SEUILS, ET D'OÙ ILS VIENNENT

1. LE CERVEAU A CESSÉ D'APPRENDRE
   Seuil    : aucun atome depuis {STALL_HOURS} h ET file de curation non vide.
   Pourquoi : le cerveau digère par cycles — trois par jour sur l'installation
              de référence (04:00, 13:00, 21:00). {STALL_HOURS} h, ce sont donc
              six cycles consécutifs stériles. Un cycle stérile est banal (36 %
              des cycles du cerveau de référence sont partis en quarantaine sans
              produire un atome) ; six d'affilée ne l'est pas.
   Conjonc. : la file NON VIDE est ce qui distingue une panne d'un week-end.
              Sans elle, l'alarme sonnerait chaque fois que vous ne travaillez
              pas, et vous la couperiez.
   À régler  : si vous digérez une fois par jour, montez à 72 ou 96 h.

2. LES CYCLES ÉCHOUENT EN SÉRIE
   Seuil    : probabilité de la série < {STREAK_P * 100:g} % au taux d'échec
              que VOUS observez, et série d'au moins {STREAK_MIN}.
   Pourquoi : « trois échecs d'affilée » n'est pas un seuil : sur un cerveau qui
              en rate 36 %, cela arrive une fois par semaine (0,36³ ≈ 4,7 %) et
              l'alarme devient du bruit. On calcule donc votre taux réel, et on
              alerte quand la série cesse d'être explicable par lui.
   Calibr.  : inactive tant que moins de {STREAK_MIN_HISTORY} cycles sont
              enregistrés — on n'estime pas un taux sur trois mesures.

3. LA BASE GROSSIT ANORMALEMENT
   Seuil    : croissance quotidienne > {GROWTH_FACTOR:g} × la médiane de vos
              croissances, ET > {GROWTH_FLOOR / 1024 / 1024:.0f} Mio en absolu.
   Pourquoi : aucun seuil en gigaoctets ne peut être juste pour tout le monde —
              cela dépend de combien vous parlez. On se calibre donc sur votre
              propre historique. La médiane, et non la moyenne, pour qu'un seul
              jour d'import massif ne relève pas le seuil pour toujours. Le
              plancher absolu évite de crier quand une base jeune passe de 2 à
              20 Mio : facteur 10, aucune importance.
   Calibr.  : inactive tant que moins de {GROWTH_MIN_SAMPLES} mesures
              quotidiennes existent, et elle le DIT au lieu de se taire.

4. PLUS RIEN N'ENTRE
   Seuil    : aucun message reçu depuis {INGEST_SILENCE_HOURS} h.
   Pourquoi : la synchronisation depuis le poste source tourne au moins une fois
              par jour ; {INGEST_SILENCE_HOURS} h = un passage manqué + 2 h de
              marge. Cette panne-là est la plus sournoise : le cerveau continue
              de digérer son arriéré pendant des semaines, donc tout paraît
              normal, pendant que la source est coupée.

TOUTES ces valeurs se règlent par variable d'environnement (ARAC_ALERT_*).
Changez la cadence de digestion, changez les seuils : un seuil qui ne
correspond plus à la réalité apprend à ignorer les alarmes.
"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Les alarmes qui doivent chercher un humain.")
    p.add_argument("--json", action="store_true")
    p.add_argument("--explain", action="store_true", help="les seuils et leur justification")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    if args.explain:
        print(_EXPLAIN)
        return 0

    # Le coffre AVANT le verdict : si la variable manque et que le coffre est
    # lisible, on va la chercher au lieu d'imprimer un constat sans geste.
    trouvee, chemin = _coffre.resoudre("DATABASE_URL_READONLY")
    dsn = os.environ.get("DATABASE_URL_READONLY")
    if not trouvee or not dsn:
        if not args.quiet:
            print(
                "UNKNOWN : DATABASE_URL_READONLY n'est pas définie.\n"
                "\n"
                "Ce n'est pas un diagnostic du cerveau : c'est l'impossibilité d'en\n"
                "faire un. Ces alarmes lisent la base avec le rôle en lecture stricte,\n"
                "et cette variable est la seule chose qui leur manque.\n"
                "\n"
                f"{_coffre.pourquoi_pas_lisible(chemin)}\n"
                "\n"
                "Le geste qui marche, sur CE cerveau :\n"
                f"    {_coffre.geste_qui_marche('scripts/ops/alerts.py', chemin)}\n"
                "\n"
                "Sous systemd, rien de tout cela : c'est EnvironmentFile= qui la fournit.",
                file=sys.stderr)
        if args.json:
            print(json.dumps({
                "alarms": [], "raised": 0, "verdict": "UNKNOWN",
                "ce_qui_manque_pour_savoir": {
                    "variable": "DATABASE_URL_READONLY",
                    "coffre_attendu": chemin or "/etc/arac/<votre-base>/arac.env",
                    "coffre_lisible": bool(chemin) and os.access(chemin, os.R_OK),
                },
            }, ensure_ascii=False, indent=2))
        return 3

    schema = os.environ.get("ARAC_DB_SCHEMA", "arac")

    try:
        import psycopg
    except ImportError:
        print("UNKNOWN : psycopg absent — utilisez l'interpréteur de l'installation "
              "($ARAC_HOME/.venv/bin/python).", file=sys.stderr)
        return 3

    alarms: list[Alarm] = []
    try:
        with psycopg.connect(dsn, options="-c default_transaction_read_only=on") as conn:
            with conn.cursor() as cur:
                for check in CHECKS:
                    try:
                        a = check(cur, schema)
                    except Exception as exc:  # noqa: BLE001
                        a = Alarm(check.__name__, "info",
                                  f"Contrôle « {check.__name__} » impossible",
                                  f"{type(exc).__name__}: {exc}", "—")
                    if a is not None:
                        alarms.append(a)
    except Exception as exc:  # noqa: BLE001
        if not args.quiet:
            print(f"UNKNOWN : base injoignable ({type(exc).__name__}). "
                  "Ce n'est pas un diagnostic du cerveau, c'est l'impossibilité d'en faire un.",
                  file=sys.stderr)
        return 3

    real = [a for a in alarms if a.level in ("warn", "critical")]

    if args.quiet:
        return 1 if real else 0

    if args.json:
        print(json.dumps({"alarms": [a.as_dict() for a in alarms],
                          "raised": len(real),
                          "at": _now().isoformat()},
                         ensure_ascii=False, indent=2))
        return 1 if real else 0

    if not alarms:
        print("Aucune alarme. Le cerveau reçoit, digère et grossit normalement.")
        return 0

    for a in alarms:
        icon = {"critical": "✗", "warn": "!", "info": "·"}.get(a.level, "·")
        print(f"{icon} {a.title}")
        print(f"    {a.detail}")
        print(f"    seuil : {a.threshold}")
        if a.evidence:
            print("    pour regarder vous-même :")
            for line in a.evidence.strip().splitlines():
                print(f"        {line}")
        print()

    if real:
        print(f"{len(real)} alarme(s) réelle(s). `--explain` dit d'où viennent les seuils.")
    else:
        print("Rien qui doive vous réveiller (les lignes ci-dessus sont informatives).")
    return 1 if real else 0


if __name__ == "__main__":
    raise SystemExit(main())
