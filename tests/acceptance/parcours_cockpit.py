#!/usr/bin/env python3
"""parcours_cockpit.py — LE COCKPIT MONTRE-T-IL QUELQUE CHOSE ?

    Un 200 sur une réponse vide ne prouve que l'absence d'exception.

CE QUE CE GARDE FERME, ET POURQUOI IL EXISTE
============================================
Sept routes servies du cockpit — la fiche d'un souvenir, son histoire, la fiche
d'un domaine, l'arbre de la taxonomie, la liste des projets, la liste des
conversations, la fiche d'une conversation — sont mortes sur TOUTE installation
issue du chemin documenté. Cinq parce que ``config/projects.toml`` n'existe pas
et qu'une liste vide produisait un SQL vide entre parenthèses (PostgreSQL
42601) ; deux parce que le garde de lecture seule voyait un ``--`` écrit en
PROSE dans un commentaire de bloc de sa propre requête et refusait de
l'exécuter.

**Les sept rendaient HTTP 200.** Le corps portait ``state: "unavailable"`` et
une empreinte d'erreur ; le harnais empruntait ces routes, lisait le code, et
les voyait vertes. C'est la leçon de cette manche : *le code de retour ne
prouve rien*.

CE QUE CE FICHIER FAIT, ET CE QU'IL NE FAIT PAS
===============================================
Il emprunte les routes SERVIES du cockpit — pas une liste écrite à la main,
mais celles que l'application DÉCLARE — sur un cerveau qui contient réellement
un souvenir, un domaine, une conversation et (deuxième passe) un projet, et il
exige que chacune LE RESSORTE. Trois contrôles par route, dans cet ordre :

  1. le code HTTP est celui qu'on attend ;
  2. la réponse ne se déclare pas indisponible — et quand elle le fait
     légitimement (``/cc/v1/listener/selftest`` refuse d'exécuter un NOTIFY,
     qui est une écriture), la RAISON attendue est écrite ici, en toutes
     lettres, et elle est vérifiée ;
  3. la réponse CONTIENT les marques du cerveau : l'identifiant du souvenir,
     la clé qu'il porte, l'uid de la conversation, le chemin du domaine, le
     nom du projet. Un corps qui ne les porte pas n'a rien montré.

IL N'ÉNUMÈRE PAS CE QU'IL VÉRIFIE — IL ÉNUMÈRE CE QUE LE PRODUIT SERT.
La liste des routes vient de ``control_center.app``, pas d'ici. Une route
ajoutée demain apparaît donc toute seule, et si personne ne l'a inscrite au
parcours, ce garde ROUGIT : « route servie non recensée ». C'est la seule
forme de recensement qui ne se périme pas.

CE QU'IL NE PROUVE PAS, et qui est dit dans le rapport : une route déclarée
« hors parcours » l'est avec sa raison, jamais en silence.

USAGE
=====
    parcours_cockpit.py --racine <ARAC_HOME> --base http://127.0.0.1:<port>
                        --cookie <valeur de cc_session>
                        --contexte <fichier json>
                        [--phase sans-projets|avec-projets]

Le fichier de contexte porte les marques du cerveau visité :

    {"atome_id": "...", "atome_cle": "...", "conversation_uid": "...",
     "scope": "...", "metrique": "...", "cerveau": "...", "base": "...",
     "projet_id": "...", "projet_label": "..."}

``cerveau`` est le nom donné à l'entretien (il est dans le titre des pages),
``base`` est le nom de la base qu'il en a déduit (il est dans le nom des
unités, donc dans ``/cc/healthz``). Les deux diffèrent — un tiret devient un
souligné — et les confondre ferait accuser une route saine.

Code de sortie : 0 si toutes les routes empruntées ont montré quelque chose,
1 sinon. Le rapport est écrit sur la sortie standard dans les deux cas.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Callable

# ============================================================================
# LE VOCABULAIRE DU VERDICT
# ============================================================================

MONTRE = "MONTRE"        # empruntée, et elle a ressorti ce que le cerveau contient
VIDE = "VIDE"            # empruntée, 200, et elle n'a rien montré  → ÉCHEC
MORTE = "MORTE"          # empruntée, et elle se déclare indisponible → ÉCHEC
HORS = "HORS PARCOURS"   # pas empruntée ici, et la raison est dite
INCONNUE = "NON RECENSÉE"  # servie par l'application, absente du parcours → ÉCHEC

ECHECS = (VIDE, MORTE, INCONNUE)


# ============================================================================
# CE QUI COMPTE COMME « INDISPONIBLE »
# ============================================================================
#
# Le cockpit ne lève pas : il DIT. Un état d'indisponibilité au premier niveau
# de la réponse est donc l'aveu exact qu'on cherche — c'est lui que les sept
# routes mortes portaient derrière leur 200.
#
# On ne descend PAS dans les sous-objets, et c'est délibéré : un maillon
# légitimement indisponible (`arac.atom_links` absente du schéma) vit à
# l'intérieur d'une réponse par ailleurs complète. Confondre les deux ferait
# rougir ce garde sur un cerveau sain — et un garde qui rougit à tort finit
# désarmé.

ETATS_MORTS = {"unavailable", "error", "failed", "indisponible"}


def _etat_mort(charge: Any) -> str | None:
    """L'état d'indisponibilité déclaré au premier niveau, ou ``None``."""
    if not isinstance(charge, dict):
        return None
    etat = charge.get("state")
    if isinstance(etat, str) and etat.lower() in ETATS_MORTS:
        return str(charge.get("reason") or "sans raison déclarée")
    return None


# ============================================================================
# L'EMPRUNT
# ============================================================================


def emprunter(base: str, chemin: str, cookie: str, *,
              delai: int = 60, flux: bool = False) -> tuple[Any, str]:
    """Rend ``(code, corps)``. Un échec de transport rend ``("ERR", message)``."""
    req = urllib.request.Request(
        base + chemin,
        headers={"Cookie": f"cc_session={cookie}",
                 "Accept": "text/event-stream" if flux else "*/*"},
    )
    try:
        with urllib.request.urlopen(req, timeout=delai) as rep:
            if flux:
                # UN FLUX NE SE TERMINE PAS : on lit ce qui vient, puis on part.
                # On ne s'arrête pas à la première trame vide — le flux ouvre
                # par un COMMENTAIRE SSE (« : arac cc/v1 stream … ») suivi d'une
                # ligne blanche, et s'arrêter là ferait conclure « rien montré »
                # sur un flux parfaitement vivant. On lit jusqu'à voir une
                # DONNÉE, ou jusqu'au budget.
                morceaux: list[bytes] = []
                lus = 0
                while lus < 16384:
                    bloc = rep.read1(1024) if hasattr(rep, "read1") else rep.read(1024)
                    if not bloc:
                        break
                    morceaux.append(bloc)
                    lus += len(bloc)
                    if b"data:" in b"".join(morceaux):
                        break
                return rep.status, b"".join(morceaux).decode("utf-8", "replace")
            return rep.status, rep.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 — un transport qui casse EST le résultat
        return "ERR", f"{type(exc).__name__}: {exc}"


# ============================================================================
# LE PARCOURS — une entrée par route SERVIE
# ============================================================================
#
# `chemin` reçoit le contexte (les marques du cerveau visité) et rend l'URL à
# emprunter. `exige` est la liste des chaînes qui DOIVENT apparaître dans le
# corps : ce sont elles qui font la différence entre « la route a répondu » et
# « la route a montré ». `taille_min` attrape le corps techniquement valide et
# humainement vide.


def _plan(ctx: dict[str, str], phase: str) -> dict[str, dict[str, Any]]:
    """Le parcours, construit à partir des marques du cerveau visité."""
    a = ctx["atome_id"]
    cle = ctx["atome_cle"]
    conv = ctx["conversation_uid"]
    scope = ctx["scope"]
    metrique = ctx["metrique"]
    cerveau = ctx["cerveau"]
    projet = ctx.get("projet_id") or "aucun-projet"
    avec_projets = phase == "avec-projets"

    def html(chemin: str, *marques: str, taille: int = 1200) -> dict[str, Any]:
        return {"mode": "html", "chemin": chemin, "exige": list(marques),
                "taille_min": taille}

    def js(chemin: str, *marques: str, taille: int = 20) -> dict[str, Any]:
        return {"mode": "json", "chemin": chemin, "exige": list(marques),
                "taille_min": taille}

    def hors(raison: str) -> dict[str, Any]:
        return {"mode": "hors", "raison": raison}

    plan: dict[str, dict[str, Any]] = {
        # --- la porte ---------------------------------------------------
        "/": {"mode": "html", "chemin": "/", "exige": [], "taille_min": 0,
              "codes": (200, 302, 303, 307, 308)},
        # `/cc/healthz` nomme l'UNITÉ, donc la base (`arac-<base>-cockpit`), pas
        # le nom du cerveau tel qu'on l'a écrit à l'entretien. Les deux marques
        # sont demandées séparément, sans quoi ce garde accuserait une route
        # saine de ne rien montrer.
        "/cc/healthz": js("/cc/healthz", ctx["base"], '"provisioned"'),
        "/cc/login": {"mode": "html", "chemin": "/cc/login", "exige": ["totp"],
                      "taille_min": 500, "sans_session": True},

        # --- les pages servies du socle ---------------------------------
        #
        # Chacune porte le NOM DU CERVEAU dans son titre : une page qui ne le
        # porte pas n'a pas été rendue par ce cockpit-ci. Et chaque page qui
        # sait montrer de la mémoire doit montrer CELLE-CI.
        "/cc/": html("/cc/", cerveau, "Overview"),
        "/cc/memory": html("/cc/memory", cerveau, scope),
        "/cc/queues": html("/cc/queues", cerveau),
        "/cc/council": html("/cc/council", cerveau),
        "/cc/sobriety": html("/cc/sobriety", cerveau),
        "/cc/reports": html("/cc/reports", cerveau),
        "/cc/decisions": html("/cc/decisions", cerveau),
        "/cc/commits": html("/cc/commits", cerveau),
        "/cc/system": html("/cc/system", cerveau),
        "/cc/tmux": html("/cc/tmux", cerveau),
        "/cc/timeline": html("/cc/timeline", cerveau),
        "/cc/brain": html("/cc/brain", cerveau, scope),

        # --- la perception ----------------------------------------------
        "/cc/perception": html("/cc/perception", cerveau),
        "/cc/perception/receipts": html("/cc/perception/receipts", cerveau),
        "/cc/perception/alertes": html("/cc/perception/alertes", cerveau),
        "/cc/perception/etats": html("/cc/perception/etats", cerveau),
        "/cc/perception/inflow": html("/cc/perception/inflow", cerveau),
        "/cc/perception/q1": html("/cc/perception/q1", cerveau),
        "/cc/perception/q2": html("/cc/perception/q2", cerveau),
        "/cc/perception/q3": html("/cc/perception/q3", cerveau),
        "/cc/perception/q4": html("/cc/perception/q4", cerveau),
        "/cc/perception/q5": html("/cc/perception/q5", cerveau),
        "/cc/perception/q6": html("/cc/perception/q6", cerveau),
        "/cc/perception/q7": html("/cc/perception/q7", cerveau),
        "/cc/perception/q8": html("/cc/perception/q8", cerveau),

        # --- l'API du socle ---------------------------------------------
        "/cc/api/overview": js("/cc/api/overview", scope, '"conversations"'),
        "/cc/api/memory": js("/cc/api/memory", scope, '"by_kind"'),
        "/cc/api/queues": js("/cc/api/queues", '"ipq"', '"mrq"'),
        "/cc/api/council": js("/cc/api/council"),
        "/cc/api/system": js("/cc/api/system"),

        # --- le BFF : les métriques et leur preuve ----------------------
        "/cc/v1/catalog": js("/cc/v1/catalog", metrique, '"items"'),
        "/cc/v1/metrics": js("/cc/v1/metrics", metrique),
        "/cc/v1/metrics/{key}": js(f"/cc/v1/metrics/{metrique}", metrique, '"value"'),
        "/cc/v1/evidence/{key}": js(f"/cc/v1/evidence/{metrique}", '"sql"', "SELECT"),
        "/cc/v1/status": js("/cc/v1/status", '"submodules"', '"loaded"'),

        # --- LE COCKPIT : les sept routes qui étaient mortes -------------
        "/cc/v1/conversations": js("/cc/v1/conversations", conv),
        "/cc/v1/conversations/{uid}": js(f"/cc/v1/conversations/{conv}", conv),
        "/cc/v1/atoms": js("/cc/v1/atoms", a, cle),
        "/cc/v1/atoms/{atom_id}": js(f"/cc/v1/atoms/{a}", a, cle),
        # L'HISTOIRE D'UN SOUVENIR — et la marque qu'on a le DROIT d'exiger.
        # Elle doit toujours ressortir l'atome. Elle ne peut ressortir la
        # conversation qui l'a fait naître que si CET atome en déclare une :
        # un atome entré par `POST /v1/atoms` n'en déclare aucune, et exiger
        # l'uid ici accuserait la route de taire ce que la base ne contient
        # pas. Le contexte dit lequel des deux cas on visite.
        "/cc/v1/atoms/{atom_id}/story": js(
            f"/cc/v1/atoms/{a}/story", a,
            *( (conv,) if ctx.get("atome_lie_a_la_conversation") else () )),
        "/cc/v1/scopes": js("/cc/v1/scopes", scope),
        "/cc/v1/scopes/tree": js("/cc/v1/scopes/tree", scope),
        "/cc/v1/scopes/{path:path}": js(f"/cc/v1/scopes/{scope}", scope),

        # --- les projets : les deux passes ------------------------------
        #
        # SANS `config/projects.toml`, trois documents promettent que le
        # cockpit « le dit » plutôt que de casser. On l'exige donc au mot :
        # la liste répond `ok` et porte la note ; la fiche et le graphe d'un
        # projet inexistant répondent « aucun projet déclaré », ce qui est la
        # vérité et non une panne.
        "/cc/v1/projects": (
            js("/cc/v1/projects", ctx.get("projet_label", projet), projet)
            if avec_projets else
            js("/cc/v1/projects", "aucun projet déclaré", "config/projects.toml")
        ),
        "/cc/v1/projects/{project_id}": (
            js(f"/cc/v1/projects/{projet}", projet, scope)
            if avec_projets else
            {"mode": "json", "chemin": f"/cc/v1/projects/{projet}",
             "exige": ["aucun projet déclaré"], "taille_min": 20,
             "indisponible_attendu": "aucun projet déclaré"}
        ),
        "/cc/v1/projects/{project_id}/graph": (
            js(f"/cc/v1/projects/{projet}/graph", projet, '"nodes"')
            if avec_projets else
            {"mode": "json", "chemin": f"/cc/v1/projects/{projet}/graph",
             "exige": ["aucun projet ne porte l'identifiant"], "taille_min": 20,
             "indisponible_attendu": "aucun projet ne porte l'identifiant"}
        ),

        # --- la journée, la chronologie, le rejeu ------------------------
        "/cc/v1/today": js("/cc/v1/today", "today_atoms_created", '"deltas"'),
        "/cc/v1/today/evidence/{key}": js(
            "/cc/v1/today/evidence/today_atoms_created", a, '"sql"'),
        "/cc/v1/today/narrative": js("/cc/v1/today/narrative", '"templates"'),
        "/cc/v1/timeline": js("/cc/v1/timeline", '"buckets"', '"events"'),
        "/cc/v1/replay": js("/cc/v1/replay", '"frames"', '"range"'),
        "/cc/v1/replay/days": js("/cc/v1/replay/days", '"days"'),

        # --- la cascade --------------------------------------------------
        "/cc/v1/cascade": js("/cc/v1/cascade", '"items"', '"templates"'),
        "/cc/v1/cascade/catalog": js("/cc/v1/cascade/catalog", '"templates"'),
        "/cc/v1/cascade/{conversation_uid}": js(
            f"/cc/v1/cascade/{conv}", conv, '"items"'),

        # --- le flux -----------------------------------------------------
        "/cc/v1/events": js("/cc/v1/events", '"items"', '"transport"'),
        "/cc/v1/stream": {"mode": "flux", "chemin": "/cc/v1/stream",
                          "exige": ["data:"], "taille_min": 10},
        "/cc/v1/stream/catalog": js("/cc/v1/stream/catalog", '"events"'),
        "/cc/v1/stream/state": js("/cc/v1/stream/state", '"idle"'),

        # --- l'écouteur ---------------------------------------------------
        "/cc/v1/listener/state": js("/cc/v1/listener/state", '"channels"', '"fallback"'),
        # LA SEULE INDISPONIBILITÉ LÉGITIME DU COCKPIT, et elle est écrite ici
        # au mot près : publier sur un canal est une ÉCRITURE, et ce cockpit
        # est en lecture seule. La route le dit ; ce garde exige qu'elle le
        # dise, et rougirait si elle se mettait à répondre « ok ».
        "/cc/v1/listener/selftest": {
            "mode": "json", "chemin": "/cc/v1/listener/selftest",
            "exige": ["hors périmètre lecture seule"], "taille_min": 50,
            "indisponible_attendu": "hors périmètre lecture seule"},

        # --- l'interface --------------------------------------------------
        "/cc/v1/app": html("/cc/v1/app", "cc/v1", taille=1000),
        "/cc/v1/app/health": js("/cc/v1/app/health", '"assets"', '"etag"'),
        "/cc/v1/static/{filename}": {
            "mode": "html", "chemin": "/cc/v1/static/app.js",
            "exige": ["/cc/v1/"], "taille_min": 5000},

        # --- les deux routes qu'on n'emprunte pas ICI ---------------------
        "/cc/logout": hors(
            "elle DÉTRUIT la session que ce parcours utilise : l'emprunter au "
            "milieu ferait échouer toutes les suivantes pour une raison qui "
            "n'est pas celle qu'on mesure. Elle est empruntée par l'étape 7 "
            "elle-même, après ce parcours."),
    }
    return plan


#: Les routes servies dont le VERBE n'est pas GET. Ce parcours lit ; il n'écrit
#: pas. `POST /cc/login` est la seule, et elle est empruntée par l'étape 7 pour
#: ouvrir la session sans laquelle rien de ce qui précède n'existerait.
NON_GET = {
    ("POST", "/cc/login"): (
        "seule route non-GET du cockpit. Elle est empruntée — et vérifiée — par "
        "l'étape 7 avant ce parcours : la session qui sert ici en est le produit."),
}


# ============================================================================
# LE RECENSEMENT — ce que l'application SERT, pas ce qu'on croit qu'elle sert
# ============================================================================


def routes_servies(racine: str) -> list[tuple[str, str]]:
    """Les routes déclarées par l'application, ``(verbe, chemin)``.

    On charge l'application du cerveau visité plutôt que d'écrire une liste :
    une route ajoutée demain apparaît toute seule, et le parcours qui ne la
    connaît pas rougit.
    """
    os.environ.setdefault("ARAC_HOME", racine)
    sys.path.insert(0, racine)
    from control_center.app import app  # noqa: PLC0415 — après ARAC_HOME

    vues: list[tuple[str, str]] = []
    for r in app.routes:
        chemin = getattr(r, "path", None)
        if not chemin:
            continue
        verbes = (getattr(r, "methods", None) or {"GET"}) - {"HEAD", "OPTIONS"}
        for v in sorted(verbes):
            vues.append((v, chemin))
    return sorted(set(vues))


# ============================================================================
# LE JUGEMENT D'UNE ROUTE
# ============================================================================


def juger(base: str, cookie: str, spec: dict[str, Any]) -> tuple[str, str]:
    """Rend ``(verdict, détail)`` pour une route du parcours."""
    mode = spec["mode"]
    if mode == "hors":
        return HORS, spec["raison"]

    chemin = spec["chemin"]
    attendus = spec.get("codes", (200,))
    code, corps = emprunter(
        base, chemin,
        "" if spec.get("sans_session") else cookie,
        flux=(mode == "flux"),
    )
    if code not in attendus:
        return MORTE, f"{chemin} → HTTP {code} (attendu {attendus[0]}) : {corps[:160]}"

    # Le 200 est acquis. C'est ici que commence le vrai contrôle.
    if mode in ("json", "flux") and mode == "json":
        try:
            charge = json.loads(corps)
        except Exception:
            return VIDE, f"{chemin} → 200, et le corps n'est pas du JSON : {corps[:120]}"
        raison = _etat_mort(charge)
        attendue = spec.get("indisponible_attendu")
        if raison and not attendue:
            return MORTE, f"{chemin} → 200 avec state=indisponible : {raison[:200]}"
        if attendue and not raison:
            return VIDE, (f"{chemin} → 200 alors que l'indisponibilité « {attendue} » "
                          "était attendue : la route a changé de nature sans que "
                          "ce parcours le sache")
        if attendue and raison and attendue not in raison:
            return MORTE, (f"{chemin} → indisponible pour une AUTRE raison que celle "
                           f"qui est légitime : {raison[:200]}")

    if len(corps) < spec.get("taille_min", 0):
        return VIDE, (f"{chemin} → 200, {len(corps)} octets, moins que le minimum "
                      f"{spec['taille_min']} : la page n'a rien à montrer")

    manquantes = [m for m in spec["exige"] if m and m not in corps]
    if manquantes:
        return VIDE, (f"{chemin} → 200, {len(corps)} octets, et le corps ne porte PAS "
                      f"{manquantes} : la route a répondu, elle n'a rien montré")

    for poison in ("Traceback (most recent call last)", "Internal Server Error"):
        if poison in corps:
            return MORTE, f"{chemin} → 200 avec « {poison} » dans le corps"

    return MONTRE, f"{chemin} → 200, {len(corps)} octets, {len(spec['exige'])} marque(s) retrouvée(s)"


# ============================================================================
# LE RAPPORT
# ============================================================================


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--racine", required=True, help="ARAC_HOME du cerveau visité")
    ap.add_argument("--base", required=True, help="http://127.0.0.1:<port du cockpit>")
    ap.add_argument("--cookie", required=True, help="valeur de cc_session")
    ap.add_argument("--contexte", required=True, help="fichier JSON des marques du cerveau")
    ap.add_argument("--phase", default="sans-projets",
                    choices=("sans-projets", "avec-projets"))
    ap.add_argument("--prefixe", default="", help="préfixe des lignes (pour le harnais)")
    args = ap.parse_args(argv)

    ctx = json.loads(open(args.contexte, encoding="utf-8").read())
    plan = _plan(ctx, args.phase)
    servies = routes_servies(args.racine)

    pref = args.prefixe
    print(f"{pref}parcours du cockpit — phase « {args.phase} » — {args.base}")

    montre: list[str] = []
    hors: list[tuple[str, str]] = []
    fautes: list[tuple[str, str, str]] = []
    vues: set[str] = set()

    for verbe, chemin in servies:
        if verbe != "GET":
            raison = NON_GET.get((verbe, chemin))
            if raison is None:
                fautes.append((f"{verbe} {chemin}", INCONNUE,
                               "route servie non recensée par ce parcours"))
            else:
                hors.append((f"{verbe} {chemin}", raison))
            continue
        vues.add(chemin)
        spec = plan.get(chemin)
        if spec is None:
            detail = (f"{chemin} est servie par l'application et absente de ce "
                      "parcours : personne ne sait si elle montre quelque chose")
            fautes.append((chemin, INCONNUE, detail))
            print(f"{pref}  ✗ {INCONNUE} — {detail}")
            continue
        verdict, detail = juger(args.base, args.cookie, spec)
        if verdict == MONTRE:
            montre.append(chemin)
            print(f"{pref}  ✓ {detail}")
        elif verdict == HORS:
            hors.append((chemin, detail))
        else:
            fautes.append((chemin, verdict, detail))
            print(f"{pref}  ✗ {verdict} — {detail}")

    # Une entrée de parcours qui ne correspond à aucune route servie est un
    # mensonge symétrique : on croit couvrir ce qui n'existe plus.
    for chemin in sorted(set(plan) - vues):
        detail = (f"{chemin} est inscrite à ce parcours et n'est PAS servie par "
                  "l'application : le parcours décrit un cockpit qui n'existe pas")
        fautes.append((chemin, INCONNUE, detail))
        print(f"{pref}  ✗ {INCONNUE} — {detail}")

    total_get = len([1 for v, _ in servies if v == "GET"])
    print(f"{pref}")
    print(f"{pref}LE COMPTE — routes servies par le cockpit : {len(servies)} "
          f"({total_get} en GET, {len(servies) - total_get} autre(s))")
    print(f"{pref}  empruntées AVEC vérification de contenu : {len(montre)}")
    print(f"{pref}  hors parcours (nommées, avec leur raison) : {len(hors)}")
    for chemin, raison in hors:
        print(f"{pref}    · {chemin} — {raison}")
    if fautes:
        print(f"{pref}  EN DÉFAUT : {len(fautes)}")
        for chemin, verdict, detail in fautes:
            print(f"{pref}    · {verdict} — {detail}")
    return 1 if fautes else 0


if __name__ == "__main__":
    sys.exit(main())
