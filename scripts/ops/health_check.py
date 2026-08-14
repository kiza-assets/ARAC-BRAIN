#!/usr/bin/env python3
"""LE CERVEAU VA-T-IL BIEN ? — un verdict, en ligne de commande.

    scripts/ops/health_check.py              le verdict, lisible
    scripts/ops/health_check.py --json       le verdict, pour une machine
    scripts/ops/health_check.py --all        les 148 métriques, pas seulement
                                             celles qui vont mal
    scripts/ops/health_check.py --metric brain_health_index

CODES DE SORTIE — alignés sur la convention des sondes (Nagios, Icinga,
check_mk, la plupart des superviseurs) :

    0  OK        tout est dans les clous
    1  WARNING   au moins un seuil d'avertissement franchi
    2  CRITICAL  une constante vitale est dans le rouge
    3  UNKNOWN   impossible de juger — base injoignable, cockpit incomplet

TROIS OUTILS, TROIS QUESTIONS — ET UN SEUL CERVEAU
---------------------------------------------------
    ./bootstrap/checks/verify_install.sh   ce cerveau est-il BIEN POSÉ ?
    sudo ops/install_check.sh              tient-il debout DANS LA DURÉE ?
    scripts/ops/health_check.py (ici)      le cerveau lui-même VA-T-IL BIEN ?

Ils ne mesurent pas la même chose, donc ils peuvent rendre des verdicts
différents sans qu'aucun ne mente. Sur un cerveau installé la minute d'avant :
la pose est bonne (verify_install : ✓), la durée n'est pas encore jugeable
(install_check : deux lignes « ? » — première sauvegarde, première
restauration), et la santé est CRITIQUE parce que la mémoire est VIDE — pas de
souvenirs, donc pas de rappel, donc les constantes vitales sont au plancher.
C'est la bonne réponse : un cerveau neuf n'est pas malade, il est neuf, et il
le restera tant qu'on ne lui aura pas donné de matière. Ce que cette sonde
mesure, c'est l'état de la MÉMOIRE, jamais celui de l'installation.

POURQUOI CE SCRIPT N'INVENTE AUCUN SEUIL
----------------------------------------
Le cockpit sert déjà 148 métriques, chacune accompagnée de sa définition, de sa
formule, de sa requête de preuve et — pour 54 d'entre elles — de ses seuils
d'avertissement et de criticité. Écrire ici un second jeu de seuils créerait
deux vérités : le tableau de bord dirait « ça va » pendant que la sonde crie,
ou l'inverse. Ce script LIT le registre du cockpit et rend son verdict. Le jour
où vous ajustez un seuil, vous l'ajustez à un seul endroit.

Il n'a pas besoin que le cockpit tourne : il parle directement à la base, avec
le rôle en lecture stricte. Une sonde qui dépend du serveur web ne dit plus rien
le jour où le serveur web est le problème.

POURQUOI « UNKNOWN » EXISTE, ET POURQUOI CE N'EST PAS « CRITICAL »
------------------------------------------------------------------
Une base injoignable et un cerveau malade ne demandent pas le même geste : dans
un cas on répare la supervision ou le réseau, dans l'autre on regarde la
digestion. Une sonde qui confond les deux vous envoie chercher au mauvais
endroit à trois heures du matin. Elle ne doit pas non plus répondre « OK » —
c'est l'erreur inverse, et la pire : elle transforme une panne d'observation en
bonne nouvelle.

LA RÈGLE DU VERDICT
-------------------
Toutes les métriques ne pèsent pas pareil, et prendre le pire des 148 ferait
hurler la sonde en permanence — un cerveau réel a toujours une métrique de trop
quelque part. La règle est donc :

    CRITICAL  si l'indice de santé cérébrale est critique,
              ou si une CONSTANTE VITALE (V1..V4) est critique.
    WARNING   si l'indice ou une constante vitale est en avertissement,
              ou si au moins une autre métrique est critique.
    OK        sinon.

Les constantes vitales sont le petit noyau que la spécification du cockpit
déclare comme portant l'état du cerveau : le rappel, la fraîcheur, la digestion,
l'intégrité. Le reste informe ; il ne réveille pas.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Le dépôt doit être importable même si ce script est appelé par son chemin
# absolu depuis une unité systemd, un cron ou une sonde.
_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# Le coffre est cherché par un seul organe, partagé avec `alerts.py` : deux
# outils voisins qui se donnent deux conventions, c'est la classe de défaut que
# ce dépôt passe des manches à éliminer, et elle s'est rouverte une fois déjà.
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import coffre as _coffre  # noqa: E402


# ---------------------------------------------------------------------------
# Ce qui décide du verdict
# ---------------------------------------------------------------------------

#: L'indice de synthèse. S'il est indisponible, on ne sait rien.
HEALTH_INDEX = "brain_health_index"

#: Les constantes vitales, telles que le cockpit les déclare. Elles ne sont pas
#: choisies ici : ce sont les métriques du domaine « etat-general » qui portent
#: un seuil. On les nomme quand même, pour que ce fichier reste lisible sans
#: aller ouvrir le registre.
VITALS = ("vital_recall", "vital_freshness", "vital_digestion", "vital_integrity")

EXIT_OK, EXIT_WARN, EXIT_CRIT, EXIT_UNKNOWN = 0, 1, 2, 3
_LABEL = {EXIT_OK: "OK", EXIT_WARN: "WARNING", EXIT_CRIT: "CRITICAL", EXIT_UNKNOWN: "UNKNOWN"}


# ---------------------------------------------------------------------------
# OÙ VIT LE COFFRE — et pourquoi ce script le cherchait au mauvais endroit
# ---------------------------------------------------------------------------
#
# Lancée à la main sur un cerveau posé par le bootstrap, cette sonde rendait
# UNKNOWN et imprimait un geste de réparation QUI N'EXISTE PAS :
#
#     set -a && . "$ARAC_HOME/.env" && set +a
#
# Il n'y a pas de `$ARAC_HOME/.env` sur une installation faite par le
# bootstrap. Le coffre vit dans `/etc/arac/<base>/arac.env`, en 0600 root, et
# c'est `EnvironmentFile=` qui l'injecte sous systemd. Le dépôt SAIT dire cela
# correctement — `ops/install_check.sh` imprime les deux cas et nomme la
# variable `ARAC_ENV_FILE`. Le renseignement existait ; il n'avait pas voyagé
# jusqu'ici. Deux outils voisins, deux conventions : c'est exactement la
# classe de défaut que ce dépôt passe des manches à éliminer.
#
# On lit donc `ARAC_ENV_FILE` — la variable que l'autre outil enseigne — et on
# la charge quand elle est lisible. Une sonde qui SAIT où est le renseignement
# et refuse d'aller le chercher fait perdre à quelqu'un la demi-heure où il
# aurait dû regarder son cerveau.

def _defaut_env_file() -> str:
    """Le coffre de CE cerveau — voir `scripts/ops/coffre.py`."""
    return _coffre.defaut_env_file()


def charger_le_coffre(chemin: str) -> int:
    """Injecte les variables du coffre — voir `scripts/ops/coffre.py`."""
    return _coffre.charger_le_coffre(chemin)


def _ce_qui_manque_pour_savoir(chemin: str) -> str:
    """Le message d'UNKNOWN : ce qui manque, où c'est, et le geste qui marche.

    « Je n'ai pas pu vérifier » n'est ni « c'est bon » ni « c'est cassé ». Mais
    un UNKNOWN qui ne dit pas ce qui lui manque ne vaut pas mieux qu'un
    silence : celui qui le lit ne sait pas s'il doit réparer sa supervision ou
    son cerveau.
    """
    ou = chemin or "/etc/arac/<votre-base>/arac.env"
    detail = _coffre.pourquoi_pas_lisible(chemin)
    return (
        "UNKNOWN : DATABASE_URL_READONLY n'est pas définie.\n"
        "\n"
        "Ce n'est pas un diagnostic du cerveau : c'est l'impossibilité d'en\n"
        "faire un. Cette sonde lit la base avec le rôle en lecture stricte —\n"
        "celui du cockpit — et cette variable est la seule chose qui lui manque.\n"
        "\n"
        f"{detail}\n"
        "\n"
        "Deux cas, ne les confondez pas :\n"
        "  · installé par le bootstrap → le coffre vit dans\n"
        "    /etc/arac/<base>/arac.env et n'est lisible que par root :\n"
        f"        sudo -E .venv/bin/python scripts/ops/health_check.py\n"
        f"      ou : sudo ARAC_ENV_FILE={ou} .venv/bin/python scripts/ops/health_check.py\n"
        "  · installation manuelle → la variable est dans votre propre fichier :\n"
        "        set -a && . <votre fichier d'environnement> && set +a\n"
        "\n"
        "Sous systemd, rien de tout cela : c'est EnvironmentFile= qui la fournit."
    )


def verdict(items: list[dict]) -> tuple[int, list[str]]:
    """Rend (code de sortie, raisons). Ne lève jamais."""
    by_key = {i["key"]: i for i in items}
    reasons: list[str] = []

    index = by_key.get(HEALTH_INDEX)
    if index is None:
        return EXIT_UNKNOWN, [
            f"la métrique {HEALTH_INDEX} n'existe pas dans ce cockpit — "
            "installation incomplète ou famille de métriques non chargée"
        ]
    if index.get("state") == "unavailable":
        return EXIT_UNKNOWN, [
            f"indice de santé indisponible : {index.get('reason') or 'raison non déclarée'}"
        ]

    code = EXIT_OK

    def _bump(new: int) -> None:
        nonlocal code
        code = max(code, new)

    if index.get("state") == "critical":
        _bump(EXIT_CRIT)
        reasons.append(f"indice de santé cérébrale {index.get('value')}/100 — critique")
    elif index.get("state") == "warn":
        _bump(EXIT_WARN)
        reasons.append(f"indice de santé cérébrale {index.get('value')}/100 — sous surveillance")

    for key in VITALS:
        m = by_key.get(key)
        if not m:
            continue
        if m.get("state") == "critical":
            _bump(EXIT_CRIT)
            reasons.append(f"{m.get('label', key)} : {m.get('value')} — constante vitale critique")
        elif m.get("state") == "warn":
            _bump(EXIT_WARN)
            reasons.append(f"{m.get('label', key)} : {m.get('value')} — constante vitale en alerte")

    others_crit = [
        i for i in items
        if i.get("state") == "critical" and i["key"] not in VITALS and i["key"] != HEALTH_INDEX
    ]
    if others_crit:
        _bump(EXIT_WARN)
        noms = ", ".join(f"{i.get('label', i['key'])}={i.get('value')}" for i in others_crit[:5])
        suite = f" (+{len(others_crit) - 5})" if len(others_crit) > 5 else ""
        reasons.append(f"{len(others_crit)} métrique(s) au-delà de leur seuil critique : {noms}{suite}")

    return code, reasons


# ---------------------------------------------------------------------------
# Affichage
# ---------------------------------------------------------------------------

_ICON = {"ok": "·", "warn": "!", "critical": "✗", "unavailable": "?"}


def render(items: list[dict], code: int, reasons: list[str], show_all: bool) -> str:
    out: list[str] = []
    counts = {"ok": 0, "warn": 0, "critical": 0, "unavailable": 0}
    for i in items:
        counts[i.get("state", "unavailable")] = counts.get(i.get("state", "unavailable"), 0) + 1

    index = next((i for i in items if i["key"] == HEALTH_INDEX), None)
    if index and index.get("value") is not None:
        out.append(f"Indice de santé cérébrale : {index['value']}/100")
        if index.get("detail"):
            out.append(f"  {index['detail']}")
    out.append(
        f"{len(items)} métriques lues — {counts['ok']} dans les clous, "
        f"{counts['warn']} en alerte, {counts['critical']} critiques, "
        f"{counts['unavailable']} indisponibles"
    )
    out.append("")

    interesting = [i for i in items if show_all or i.get("state") in ("warn", "critical", "unavailable")]
    if not interesting:
        out.append("Aucune métrique hors de ses seuils.")
    else:
        rang = {"critical": 0, "warn": 1, "unavailable": 2, "ok": 3}
        for i in sorted(interesting, key=lambda x: rang.get(x.get("state", "unavailable"), 9)):
            val = i.get("value")
            unit = i.get("unit") or ""
            line = f"  {_ICON.get(i.get('state'), '?')} {i.get('label', i['key'])} : {val} {unit}".rstrip()
            if i.get("state") == "unavailable" and i.get("reason"):
                line += f"  → {i['reason']}"
            elif i.get("target"):
                t = i["target"]
                sens = "plus c'est haut, mieux c'est" if t.get("direction") == "up" else "plus c'est bas, mieux c'est"
                line += f"   [alerte {t.get('warn')}, critique {t.get('critical')} — {sens}]"
            out.append(line)

    out.append("")
    out.append(f"VERDICT : {_LABEL[code]}")
    for r in reasons:
        out.append(f"  — {r}")
    if code == EXIT_UNKNOWN:
        out.append("")
        out.append("Ce n'est pas un diagnostic du cerveau : c'est l'impossibilité d'en faire un.")
        out.append("CE QUI MANQUE POUR SAVOIR : une base joignable avec le rôle en lecture")
        out.append("stricte (DATABASE_URL_READONLY), et un cockpit complet. Tant que l'un des")
        out.append("deux manque, cette sonde ne dit RIEN du cerveau — ni du bien, ni du mal.")
    out.append("")
    out.append("Cette sonde mesure la MÉMOIRE, pas l'installation. Un cerveau neuf et vide")
    out.append("est CRITIQUE ici et parfaitement sain ailleurs :")
    out.append("  ./bootstrap/checks/verify_install.sh   ce cerveau est-il BIEN POSÉ ?")
    # `sudo` n'est pas une décoration : le coffre est en 0700 root, et sans
    # lui ce contrôle-là REFUSE de mesurer (code 3). Une commande imprimée
    # sans le droit qu'elle exige est un cul-de-sac servi à quelqu'un qui
    # cherche déjà pourquoi son cerveau va mal.
    out.append("  sudo ops/install_check.sh              tient-il debout DANS LA DURÉE ?")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Entrée
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Rend un verdict sur l'état du cerveau, à partir des métriques du cockpit.",
        epilog="Codes de sortie : 0 OK · 1 WARNING · 2 CRITICAL · 3 UNKNOWN (convention des sondes).",
    )
    p.add_argument("--json", action="store_true", help="sortie machine")
    p.add_argument("--all", action="store_true", help="afficher toutes les métriques, pas seulement celles qui sortent des clous")
    p.add_argument("--metric", metavar="CLE", help="n'évaluer qu'une métrique et rendre son état")
    p.add_argument("--domain", metavar="DOMAINE", help="restreindre à un domaine du cockpit")
    p.add_argument("--quiet", action="store_true", help="ne rien afficher, ne rendre que le code de sortie")
    args = p.parse_args(argv)

    # Le coffre AVANT le verdict : si la variable manque et que le coffre est
    # lisible, la sonde va la chercher au lieu d'imprimer un remède.
    coffre = _defaut_env_file()
    if not os.environ.get("DATABASE_URL_READONLY") and coffre:
        charger_le_coffre(coffre)

    if not os.environ.get("DATABASE_URL_READONLY"):
        if not args.quiet:
            print(_ce_qui_manque_pour_savoir(coffre), file=sys.stderr)
        if args.json:
            print(json.dumps({
                "verdict": _LABEL[EXIT_UNKNOWN],
                "exit_code": EXIT_UNKNOWN,
                "reasons": ["DATABASE_URL_READONLY absente"],
                "ce_qui_manque_pour_savoir": {
                    "variable": "DATABASE_URL_READONLY",
                    "coffre_attendu": coffre or "/etc/arac/<votre-base>/arac.env",
                    "coffre_lisible": bool(coffre) and os.access(coffre, os.R_OK),
                },
            }, ensure_ascii=False, indent=2))
        return EXIT_UNKNOWN

    try:
        from control_center.cc_v1 import service
    except Exception as exc:  # noqa: BLE001
        if not args.quiet:
            print(f"UNKNOWN : cockpit non importable ({type(exc).__name__}: {exc})", file=sys.stderr)
        return EXIT_UNKNOWN

    if args.metric:
        item = service.metric_value(args.metric)
        items = [item]
        state = item.get("state")
        code = {"ok": EXIT_OK, "warn": EXIT_WARN, "critical": EXIT_CRIT}.get(state, EXIT_UNKNOWN)
        reasons = [f"{item.get('label', args.metric)} = {item.get('value')} ({state})"]
    else:
        result = service.all_metrics(domain=args.domain)
        items = result["items"]
        code, reasons = verdict(items)

    if args.quiet:
        return code
    if args.json:
        print(json.dumps(
            {
                "verdict": _LABEL[code],
                "exit_code": code,
                "reasons": reasons,
                "counts": {
                    s: sum(1 for i in items if i.get("state") == s)
                    for s in ("ok", "warn", "critical", "unavailable")
                },
                "metrics": items,
            },
            ensure_ascii=False, indent=2, default=str,
        ))
    else:
        print(render(items, code, reasons, show_all=args.all))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
