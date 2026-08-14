"""Control Center v1 — LA PAGE DU COCKPIT et ses fichiers statiques.

Paquet ADDITIF : ce module n'altère aucune route existante. Il est chargé par
``control_center/cc_v1/routes.py`` via ``_register_submodules`` et n'expose que
des routes ``GET``, derrière la même garde de session et le même journal de
lecture que le reste du BFF.

Ce que ce module sert
---------------------
  GET /cc/v1/app                 la coquille du cockpit (``static/index.html``)
  GET /cc/v1/static/{fichier}    ses fichiers : ``ds.css``, ``app.js``

Ce que ce module NE fait PAS
----------------------------
Il ne touche pas à PostgreSQL, il n'exécute aucune requête, il ne fabrique
aucune donnée. Il ne transporte que des octets déjà écrits sur le disque. Toutes
les valeurs affichées par le cockpit sont demandées par le navigateur aux routes
``/cc/v1/*`` déjà servies par ``routes.py``, ``entities.py`` et ``stream.py``.

Conséquence utile : cette page répond même quand la base est éteinte. Le
navigateur affichera alors des états d'indisponibilité motivés — jamais des
zéros, jamais des valeurs recopiées.

Sécurité du service de fichiers
-------------------------------
Le nom de fichier n'est jamais concaténé au chemin : il est cherché dans un
dictionnaire FERMÉ (``ASSETS``). Un nom inconnu — ``../``, un chemin absolu, un
lien symbolique — n'a aucune chance de désigner un fichier, puisqu'il n'est pas
une CLÉ. C'est une liste blanche, pas un assainissement, donc il n'y a pas de
contournement à trouver.

Cache : les fichiers sont relus à chaque appel (ils sont petits) et validés par
un ``ETag`` dérivé de leur empreinte. Un cockpit qu'on modifie doit se recharger
sans qu'on aille vider un cache ; un cockpit qu'on n'a pas modifié ne doit pas
retransférer ses octets.

Journal de lecture
------------------
Le nom de fichier demandé est journalisé **avant** la liste blanche : une
tentative sur un nom inconnu doit laisser une trace, sinon le journal ne
documente que les accès réussis. Il est donc, et il reste, une donnée entrante :
il passe par ``_journal_path`` avant d'atteindre le journal (voir la note de
cette fonction).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

__all__ = ["register", "ASSETS", "STATIC_DIR", "PAGE"]

logger = logging.getLogger("arac.cc.v1.ui")

_PREFIX = "/cc/v1"

STATIC_DIR: Path = Path(__file__).resolve().parent / "static"

#: La coquille servie par ``/cc/v1/app``.
PAGE = "index.html"

#: Liste BLANCHE des fichiers servis, avec leur type de contenu. Un fichier
#: absent de ce dictionnaire n'est pas servi, quel que soit son nom.
ASSETS: dict[str, str] = {
    "index.html": "text/html; charset=utf-8",
    "ds.css": "text/css; charset=utf-8",
    "app.js": "application/javascript; charset=utf-8",
}

#: Réponse servie quand un fichier attendu manque sur le disque. Elle dit ce qui
#: manque et le geste qui débloque — même doctrine que le reste du cockpit : une
#: absence est une information, pas une page blanche.
_MISSING_PAGE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>ARAC · cockpit incomplet</title>
<style>
 body{{background:#0d0d10;color:#eaeaee;font:14px/1.6 system-ui,sans-serif;margin:0;
      display:flex;min-height:100vh;align-items:center;justify-content:center;padding:40px}}
 div{{max-width:64ch;display:grid;gap:8px}}
 h1{{font-size:17px;font-weight:500;margin:0;color:#6b6b75}}
 code{{font-family:ui-monospace,Menlo,Consolas,monospace;color:#9a9aa3;font-size:12px}}
 p{{margin:0;color:#9a9aa3}}
</style></head>
<body><div>
<h1>◇ Le cockpit n'est pas complet</h1>
<p>Le fichier <code>{name}</code> est absent de <code>{where}</code>.</p>
<p>Geste : replacer ce fichier, puis recharger la page. Aucune donnée n'est en cause —
c'est l'interface qui manque, pas le cerveau. Les routes <code>/cc/v1/metrics</code>,
<code>/cc/v1/evidence/{{clé}}</code> et <code>/cc/v1/stream</code> restent servies.</p>
</div></body></html>
"""


def _read_asset(name: str) -> bytes | None:
    """Lit un fichier de la liste blanche. Rend ``None`` s'il manque ou casse.

    Ne lève jamais : un cockpit dont un fichier a disparu doit le DIRE, pas
    renvoyer une trace d'exception au navigateur.
    """
    if name not in ASSETS:
        return None
    path = STATIC_DIR / name
    try:
        return path.read_bytes()
    except OSError as exc:  # noqa: BLE001 — résilience volontaire
        logger.warning("cc_v1.ui.asset_unreadable", extra={"asset": name, "error": type(exc).__name__})
        return None


#: Longueur maximale d'un chemin journalisé. Un nom de 8 ko ne dit rien de plus
#: qu'un nom de 160 caractères, mais il noie la ligne suivante.
_JOURNAL_PATH_MAX = 160


def _journal_path(path: str) -> str:
    """Rend un chemin sûr à écrire dans le journal de lecture, sur UNE ligne.

    CE QUI ÉTAIT FAUX (corrigé le 2026-08-05) : ``filename`` est un paramètre de
    chemin, donc décodé par Starlette — ``%0d%0a`` devient un vrai CRLF. Il était
    interpolé tel quel dans ``audit_read_log``, dont le format est
    ``ISO8601 | CC_ACCESS | <principal> | <chemin>\\n``. Un appel à
    ``/cc/v1/static/x%0d%0a2026-08-05T00:00:00Z%20|%20CC_ACCESS%20|%20root%20|%20/cc/forge``
    écrivait donc DEUX lignes dans un journal append-only, la seconde entièrement
    forgée. Reproduit en isolation : le chemin reçu par le journal valait
    ``'/cc/v1/static/x\\r\\nforge'``. La garde symétrique existait déjà pour le
    ``principal`` (``security.py`` : « Anti-injection de ligne de log », red-team
    V1.7B) ; le chemin, lui, n'en avait jamais reçu.

    CE QUE CETTE VERSION GARANTIT : un appel produit exactement UNE ligne de
    journal. Tout octet de contrôle est remplacé par un point d'interrogation —
    remplacé, pas supprimé, pour que la tentative reste visible au lieu d'être
    silencieusement recousue en un nom d'apparence banale. La trace de la
    tentative est conservée : c'est la liste blanche qui refuse le fichier, pas
    le journal qui l'ignore.
    """
    cleaned = "".join(ch if ch.isprintable() else "?" for ch in path)
    if len(cleaned) > _JOURNAL_PATH_MAX:
        cleaned = cleaned[:_JOURNAL_PATH_MAX] + "…[tronqué]"
    return cleaned


def _etag(payload: bytes) -> str:
    """Empreinte forte du contenu servi — un octet change, l'étiquette change."""
    return '"' + hashlib.sha256(payload).hexdigest()[:32] + '"'


def _serve(request: Request, name: str) -> Response:
    """Sert un fichier de la liste blanche, avec validation par ``ETag``."""
    payload = _read_asset(name)
    if payload is None:
        body = _MISSING_PAGE.format(name=name, where=str(STATIC_DIR))
        return HTMLResponse(body, status_code=503, headers={"Cache-Control": "no-store"})

    tag = _etag(payload)
    if request.headers.get("if-none-match") == tag:
        return Response(status_code=304, headers={"ETag": tag, "Cache-Control": "no-cache"})

    return Response(
        content=payload,
        media_type=ASSETS[name],
        headers={
            "ETag": tag,
            # « no-cache » n'interdit pas le cache : il impose de le REVALIDER.
            # Le navigateur garde les octets, le serveur confirme d'un 304.
            "Cache-Control": "no-cache, must-revalidate",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "same-origin",
        },
    )


def register(
    a: FastAPI,
    session_api: Callable[..., Any],
    audit_read_log: Callable[[str, str], Any],
) -> None:
    """Enregistre la page du cockpit et ses fichiers statiques.

    Args:
        a: l'instance FastAPI du Control Center.
        session_api: la dépendance de session en mode API (401 JSON si absente).
        audit_read_log: le journal de lecture du socle (chemin, principal).
    """

    @a.get(f"{_PREFIX}/app")
    def cc_v1_app(request: Request, principal: dict = Depends(session_api)) -> Response:
        """LA PAGE : la coquille du cockpit.

        Elle ne contient aucune donnée. Tout ce qu'elle affiche est demandé par
        le navigateur aux routes ``/cc/v1/*``, donc traçable jusqu'à sa source.
        """
        audit_read_log(f"{_PREFIX}/app", principal.get("sub", "?"))
        return _serve(request, PAGE)

    @a.get(f"{_PREFIX}/static/{{filename}}")
    def cc_v1_static(
        filename: str,
        request: Request,
        principal: dict = Depends(session_api),
    ) -> Response:
        """Les fichiers du cockpit — liste blanche stricte, ``GET`` seulement.

        Un nom hors de ``ASSETS`` ne désigne aucun fichier : il n'est pas
        assaini, il n'est simplement pas une clé du dictionnaire.
        """
        audit_read_log(_journal_path(f"{_PREFIX}/static/{filename}"), principal.get("sub", "?"))
        if filename not in ASSETS:
            return JSONResponse(
                {
                    "state": "unavailable",
                    "reason": "fichier hors de la liste blanche du cockpit",
                    "served": sorted(ASSETS),
                },
                status_code=404,
                headers={"Cache-Control": "no-store"},
            )
        return _serve(request, filename)

    @a.get(f"{_PREFIX}/app/health")
    def cc_v1_app_health(principal: dict = Depends(session_api)) -> JSONResponse:
        """Ce que l'interface sait d'ELLE-MÊME : ses fichiers, leur empreinte.

        Sert au smoke test et à l'auto-diagnostic : un fichier manquant est une
        information exploitable, pas une page blanche à interpréter.
        """
        audit_read_log(f"{_PREFIX}/app/health", principal.get("sub", "?"))
        assets: dict[str, Any] = {}
        for name in sorted(ASSETS):
            payload = _read_asset(name)
            if payload is None:
                assets[name] = {"state": "unavailable", "reason": "fichier absent ou illisible"}
            else:
                assets[name] = {"state": "ok", "bytes": len(payload), "etag": _etag(payload)}
        missing = [n for n, v in assets.items() if v["state"] != "ok"]
        return JSONResponse({
            "state": "ok" if not missing else "unavailable",
            "reason": None if not missing else f"fichiers absents : {', '.join(missing)}",
            "directory": str(STATIC_DIR),
            "page": f"{_PREFIX}/app",
            "assets": assets,
            "note": ("ce module ne lit pas la base : il ne transporte que des octets. "
                     "Toutes les valeurs du cockpit viennent des routes /cc/v1/*."),
        })
