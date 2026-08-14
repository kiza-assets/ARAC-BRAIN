"""LE RECENSEMENT DES CHEMINS LIVRÉS — combien le produit expose, combien sont EMPRUNTÉS.

CE QUE CE FICHIER MESURE, ET POURQUOI IL A FALLU L'ÉCRIRE

Le dépôt a longtemps eu pour critère de santé « une ligne verte sans `failed` ».
Ce critère a été satisfait pendant que deux routes servies rendaient 500 et qu'un
kill-switch mourait à l'import. Un compte de tests verts ne dit pas ce qui a été
EXÉCUTÉ : il dit combien d'assertions ont tenu sur les chemins que quelqu'un a
pensé à emprunter.

Ce module répond à la seule question qui rende le vert lisible :

    combien de routes, de commandes et d'unités le produit expose-t-il,
    et combien la suite en emprunte-t-elle réellement ?

DEUX INVENTAIRES, ET AUCUNE COPIE

L'inventaire n'est écrit nulle part : il est DEMANDÉ à ce qui le détient.
  · les routes : aux deux applications FastAPI elles-mêmes (`app.main.app` et
    `control_center.app.create_app()`), qui savent seules quelles routes elles
    portent ;
  · les commandes : au disque — tout script shell exécutable livré, tout module
    Python qui porte un `if __name__ == "__main__"` ;
  · les unités : aux gabarits systemd livrés sous `ops/systemd/`.
Une route ajoutée demain entre dans le compte sans que personne y pense. C'est la
même règle que le dépôt s'est déjà donnée trois fois : ne pas recopier ce qu'on
surveille, aller le lire.

« EMPRUNTÉE » A UN SENS PRÉCIS, ET CE N'EST PAS « ATTEINTE »

Le mouchard n'écoute pas les requêtes : il s'installe sur
`fastapi.routing.run_endpoint_function`, l'unique point par lequel FastAPI appelle
la fonction de route APRÈS avoir résolu ses dépendances. Une requête arrêtée par
l'authentification, par la validation des paramètres ou par une dépendance n'y
passe jamais.

C'est cette distinction qui a coûté trois manches : `make acceptance` appelle bien
`GET /v1/dashboard/search` — SANS jeton, pour vérifier le 401. La route était
« atteinte » à chaque passage du harnais, et son corps n'a jamais été exécuté une
seule fois. Le `NameError` des deux dernières lignes est resté invisible.

CE QUE LE RECENSEMENT NE PROUVE PAS
  · qu'une route empruntée est JUSTE — seulement qu'elle a été exécutée ;
  · qu'une commande ou une unité non empruntée est cassée — seulement que rien
    ici ne le saurait ;
  · rien sur ce qui se passe hors de ce processus : `make acceptance` installe un
    cerveau réel dans SES propres processus, et ses emprunts ne sont pas comptés
    ici. Le compte rendu de fin de session le dit à voix haute plutôt que de
    laisser croire à une couverture qu'il n'a pas.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

RACINE = Path(__file__).resolve().parent.parent

#: Les fonctions de route dont le CORPS a été exécuté, sous la forme
#: « module.qualname ». Rempli par le mouchard, lu en fin de session.
EMPRUNTS: set[str] = set()

_MOUCHARD_POSE = False


def cle_de_fonction(fonction: Any) -> str:
    """L'identité d'une fonction de route, stable d'une instance d'app à l'autre.

    `control_center` construit ses routes dans `_register_routes` : chaque appel
    à `create_app()` crée des OBJETS fonction neufs. L'identité par `id()` serait
    donc fausse ; le couple module + qualname, lui, ne bouge pas.
    """
    module = getattr(fonction, "__module__", "?")
    qualname = getattr(fonction, "__qualname__", getattr(fonction, "__name__", "?"))
    return f"{module}.{qualname}"


def poser_le_mouchard() -> None:
    """Enveloppe le point unique par lequel FastAPI entre dans une route.

    Posé à l'import du conftest, donc avant la création de la moindre app et
    avant le premier test. Un mouchard posé dans une fixture arrive après ce
    qu'il devait voir.
    """
    global _MOUCHARD_POSE
    if _MOUCHARD_POSE:
        return
    import fastapi.routing as _fr

    original: Callable[..., Any] = _fr.run_endpoint_function

    async def _run_endpoint_function(*, dependant, values, is_coroutine):  # type: ignore[no-untyped-def]
        appelable = getattr(dependant, "call", None)
        if appelable is not None:
            EMPRUNTS.add(cle_de_fonction(appelable))
        return await original(
            dependant=dependant, values=values, is_coroutine=is_coroutine)

    _fr.run_endpoint_function = _run_endpoint_function  # type: ignore[assignment]
    _MOUCHARD_POSE = True


# ---------------------------------------------------------------------------
# L'INVENTAIRE DES ROUTES — demandé aux applications, jamais recopié
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Route:
    application: str
    methodes: str
    chemin: str
    cle: str

    def __str__(self) -> str:  # pragma: no cover — affichage
        return f"{self.application:<8} {self.methodes:<12} {self.chemin}"


def _routes_d_une_app(nom: str, app: Any) -> list[Route]:
    routes: list[Route] = []
    for r in getattr(app, "routes", []):
        fonction = getattr(r, "endpoint", None)
        chemin = getattr(r, "path", None)
        if fonction is None or chemin is None:
            continue  # Mount, WebSocket, statique : pas une fonction de route
        methodes = sorted(getattr(r, "methods", None) or ["?"])
        routes.append(Route(nom, ",".join(methodes), chemin, cle_de_fonction(fonction)))
    return routes


def inventaire_des_routes() -> list[Route]:
    """Toutes les routes des deux applications servies, l'API et le cockpit."""
    routes: list[Route] = []
    try:
        from app.main import app as app_api

        routes.extend(_routes_d_une_app("api", app_api))
    except Exception as exc:  # noqa: BLE001 — un inventaire muet vaut mieux qu'un faux
        routes.append(Route("api", "!", f"INVENTAIRE IMPOSSIBLE : {exc}", ""))
    try:
        from control_center.app import create_app

        routes.extend(_routes_d_une_app("cockpit", create_app()))
    except Exception as exc:  # noqa: BLE001
        routes.append(Route("cockpit", "!", f"INVENTAIRE IMPOSSIBLE : {exc}", ""))
    return routes


# ---------------------------------------------------------------------------
# L'INVENTAIRE DES COMMANDES — demandé au disque
# ---------------------------------------------------------------------------
#: Là où le produit range ce qu'un humain, une unité systemd ou une minuterie
#: lance. `tests/` en est exclu : ce n'est pas ce que le produit livre à qui
#: l'installe.
DOSSIERS_DE_COMMANDES = ("bootstrap", "ops", "scripts", "agents", "app",
                         "control_center", "mac", "deploy")


def inventaire_des_commandes() -> list[str]:
    """Tout ce qui se lance : scripts shell exécutables et modules `__main__`."""
    commandes: set[str] = set()
    for dossier in DOSSIERS_DE_COMMANDES:
        base = RACINE / dossier
        if not base.is_dir():
            continue
        for chemin in base.rglob("*"):
            if not chemin.is_file() or "__pycache__" in chemin.parts:
                continue
            relatif = str(chemin.relative_to(RACINE))
            if chemin.suffix == ".sh":
                executable = bool(chemin.stat().st_mode & stat.S_IXUSR)
                commandes.add(relatif + ("" if executable else "  (non exécutable)"))
            elif chemin.suffix == ".py":
                try:
                    texte = chemin.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):  # pragma: no cover
                    continue
                if '__name__ == "__main__"' in texte or "__name__ == '__main__'" in texte:
                    commandes.add(relatif)
    return sorted(commandes)


# ---------------------------------------------------------------------------
# L'INVENTAIRE DES UNITÉS — demandé aux gabarits livrés
# ---------------------------------------------------------------------------
def inventaire_des_unites() -> list[str]:
    """Les unités et minuteries systemd que l'installation pose.

    DEUX SOURCES, parce que le produit en a deux, et n'en compter qu'une
    donnerait un inventaire faux de moitié :
      · les gabarits de `ops/systemd/`, rendus par `ops/systemd/render.sh` ;
      · les unités que le bootstrap écrit lui-même, nommées par les variables
        `U_*` de `bootstrap/lib/services.sh` et posées par `_poser_unite`.
    On lit la LISTE DES POSES (`_poser_unite "$U_X.service"`), pas une liste
    recopiée à côté : une unité ajoutée demain y entre toute seule.
    """
    unites: list[str] = []
    base = RACINE / "ops" / "systemd"
    if base.is_dir():
        unites += [
            "ops/systemd/" + p.name
            for p in sorted(base.iterdir())
            if p.is_file() and (".service" in p.name or ".timer" in p.name)
        ]
    services = RACINE / "bootstrap" / "lib" / "services.sh"
    if services.is_file():
        import re

        texte = services.read_text(encoding="utf-8")
        for m in re.finditer(r'_poser_unite\s+"\$([A-Z_]+)\.(service|timer)"', texte):
            unites.append(f"bootstrap:{m.group(1)}.{m.group(2)}")
    return sorted(set(unites))


# ---------------------------------------------------------------------------
# LE COMPTE RENDU — imprimé en fin de session par le conftest
# ---------------------------------------------------------------------------
def compte_rendu() -> list[str]:
    """Les lignes du recensement, prêtes à imprimer. Ne lève jamais."""
    lignes: list[str] = []
    try:
        routes = inventaire_des_routes()
        empruntees = [r for r in routes if r.cle in EMPRUNTS]
        delaissees = [r for r in routes if r.cle and r.cle not in EMPRUNTS]
        commandes = inventaire_des_commandes()
        unites = inventaire_des_unites()
    except Exception as exc:  # noqa: BLE001 — pragma: no cover
        return [f"recensement impossible : {type(exc).__name__}: {exc}"]

    total = len([r for r in routes if r.cle])
    part = f"{len(empruntees)}/{total}" if total else "0/0"
    lignes.append(
        f"ROUTES SERVIES : {total} — EMPRUNTÉES par cette session : {part}")
    lignes.append(
        "  « empruntée » = le CORPS de la fonction de route a été exécuté. Une "
        "route arrêtée")
    lignes.append(
        "  par l'authentification ou la validation n'est pas empruntée : c'est "
        "cette nuance")
    lignes.append(
        "  qui a laissé partir deux routes en 500 avec le harnais au vert.")
    if delaissees:
        lignes.append(f"  ROUTES JAMAIS EMPRUNTÉES ({len(delaissees)}) :")
        for r in delaissees:
            lignes.append(f"      {r}")
    lignes.append(
        f"COMMANDES LIVRÉES : {len(commandes)} — scripts shell et modules "
        f"lançables.")
    lignes.append(
        f"UNITÉS LIVRÉES : {len(unites)} — services et minuteries systemd.")
    lignes.append(
        "  Ni les commandes ni les unités ne s'empruntent dans une suite "
        "hermétique : elles")
    lignes.append(
        "  s'exécutent sur une machine. Leur emprunt se prouve dans "
        "`make acceptance`, qui")
    lignes.append(
        "  installe un cerveau réel — et le détail est dans le rapport qu'il "
        "imprime.")
    if os.environ.get("ARAC_PARCOURS_DETAIL"):
        lignes.append("  DÉTAIL DES COMMANDES :")
        lignes.extend(f"      {c}" for c in commandes)
        lignes.append("  DÉTAIL DES UNITÉS :")
        lignes.extend(f"      {u}" for u in unites)
    return lignes
