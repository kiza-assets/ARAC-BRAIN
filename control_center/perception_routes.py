"""Control Center — routes du cockpit PERCEPTION (V5 vague 1, GET only).

Doctrine : OBSERVE FIRST. DO NOT CONTROL. + READ ONLY.

13 routes GET, toutes protégées session (mêmes dépendances que app.py) :
  - /cc/perception              — page maître : bandeau d'organes statique
                                  (état de déploiement, jamais un feu de
                                  santé) + les 11 panneaux résumés (tuiles).
  - /cc/perception/q1 … q8      — panneaux-preuve dédiés (tables complètes +
                                  SQL exact affiché + LIMITES CONNUES).
  - /cc/perception/etats        — S1 états de conversation EXPLICABLES.
  - /cc/perception/inflow       — S2 jauge inflow vs capacité.
  - /cc/perception/alertes      — S3 journal des alertes émises.
  - /cc/perception/receipts     — drill-to-receipt générique (whitelist
                                  STATIQUE, params validés, placeholders).

audit_read_log : route + principal UNIQUEMENT — jamais un extrait de contenu,
jamais une valeur de query param. Un journal d'accès qui recopie ce qu'il
protège n'est plus un journal d'accès : c'est une seconde copie à protéger.
"""

from __future__ import annotations

import asyncio
import html
from typing import Any, Callable

from fastapi import Depends, FastAPI, Request
from starlette.concurrency import run_in_threadpool

from control_center.collectors import perception
from control_center.security import audit_read_log
from control_center.templates import (
    render_evidence_number,
    render_organ_badge,
    render_page,
    render_refresh_link,
    render_sql_block,
    render_table,
    render_tile,
)

# Panneaux : (slug, titre, question humaine, collecteur).
_PANELS: list[tuple[str, str, str, Callable[..., dict[str, Any]]]] = [
    ("q1", "Q1 PERÇU", "Qu'est-ce qu'ARAC a vu entrer, et avec quel retard ?",
     perception.panel_q1),
    ("q2", "Q2 EN DIGESTION", "Qu'est-ce qui attend d'être digéré, et qu'est-ce qui tourne ?",
     perception.panel_q2),
    ("q3", "Q3 REJETÉ", "Qu'est-ce qu'ARAC a refusé, filtré, exclu ou écarté — et pourquoi ?",
     perception.panel_q3),
    ("q4", "Q4 APPRIS", "Qu'est-ce qui est devenu mémoire durable ?",
     perception.panel_q4),
    ("q5", "Q5 POURQUOI", "Pourquoi CET atome, CETTE exclusion, CE rejet ?",
     perception.panel_q5),
    ("q6", "Q6 CONFIANCE", "À quel point ARAC est-il sûr, et de quoi s'abstient-il ?",
     perception.panel_q6),
    ("q7", "Q7 COÛT", "Combien ça a coûté, et les freins tiennent-ils ?",
     perception.panel_q7),
    ("q8", "Q8 PREUVES", "Montre-moi la chaîne complète pour CETTE conversation.",
     perception.panel_q8),
    ("etats", "S1 ÉTATS EXPLIQUÉS",
     "Pourquoi chaque conversation en attente est-elle en attente ? (raison mécanique nommée)",
     perception.panel_explained_states),
    ("inflow", "S2 INFLOW vs CAPACITÉ",
     "Ce qui entre (kt/j par source, 7j) tient-il dans ce que le cerveau peut digérer ?",
     perception.panel_inflow_capacity),
    ("alertes", "S3 ALERTES ÉMISES",
     "Quelles alertes ont été émises, et sont-elles arrivées ? "
     "(journal des envois + détail)",
     perception.panel_alerts),
]

_STATUS_LABEL = {
    "deployed": "DÉPLOYÉ",
    "armed_empty": "ARMÉ-VIDE",
    "partial": "PARTIEL (substrat incomplet — étages manquants affichés)",
    "not_deployed": "NON DÉPLOYÉ (migrations GO-gatées)",
    "unavailable": "INDISPONIBLE (collecte en échec — jamais un zéro fabriqué)",
}


def _render_tiles(tiles: list[dict[str, Any]]) -> str:
    """Tuiles avec chiffres-preuve cliquables (drill-to-receipt)."""
    if not tiles:
        return ""
    out = '<div class="tiles">'
    for t in tiles:
        label = html.escape(str(t.get("label", "")))
        value_html = render_evidence_number(t.get("value", "—"), t.get("drill"))
        out += (
            f'<div class="tile"><div class="tile-label">{label}</div>'
            f'<div class="tile-value small">{value_html}</div></div>'
        )
    return out + "</div>"


def _render_panel_body(data: dict[str, Any], full: bool = True) -> str:
    """Rendu UNIFORME d'un panneau (dict du collecteur → HTML échappé)."""
    status = data.get("status", "unavailable")
    body = render_organ_badge(_STATUS_LABEL.get(status, status), status,
                              data.get("as_of"))
    body += _render_tiles(data.get("tiles", []))
    if not full:
        return body
    for tbl in data.get("tables", []):
        body += f"<h2>{html.escape(str(tbl.get('title', '')))}</h2>"
        body += render_table(tbl.get("headers", []),
                             [[c if c is not None else "—" for c in row]
                              for row in tbl.get("rows", [])])
    for s in data.get("sql", []):
        origin = s.get("label", "")
        executed = "" if s.get("executed") else " — documentaire, NON exécuté"
        params = f" · params : {s['params']}" if s.get("params") else ""
        body += render_sql_block(s.get("text", ""),
                                 origin=f"{origin}{executed}{params}")
    limits = data.get("limits", [])
    if limits:
        body += "<h2>Limites connues</h2><ul>"
        for li in limits:
            body += f'<li style="color:#8b949e; font-size:12px;">{html.escape(li)}</li>'
        body += "</ul>"
    return body


def register_perception_routes(a: FastAPI, session_html_dep: Callable) -> None:
    """Enregistre les routes PERCEPTION (GET only) sur l'app fournie.

    ``session_html_dep`` = dépendance session de app.py (_session_html) —
    même protection que toutes les pages HTML existantes.
    """

    @a.get("/cc/perception", include_in_schema=False)
    async def perception_master(request: Request,  # noqa: ARG001
                                principal: dict = Depends(session_html_dep)) -> Any:
        """Page maître : bandeau d'organes + 11 panneaux résumés (tuiles)."""
        audit_read_log("/cc/perception", principal.get("sub", "?"))
        # Collecteurs SYNC exécutés HORS event loop (threadpool starlette,
        # zéro dépendance nouvelle) et rassemblés en concurrence — la page
        # maître ne bloque plus l'unique worker uvicorn (finding round 1 :
        # 11 collecteurs séquentiels + subprocess journalctl dans une route
        # async gelaient toute requête concurrente).
        overview, *panel_data = await asyncio.gather(
            run_in_threadpool(perception.organs_overview),
            *(run_in_threadpool(collector) for _, _, _, collector in _PANELS))
        banner = "<div>"
        for organ in overview.get("organs", []):
            banner += render_organ_badge(organ["label"], organ["state"])
        as_of = html.escape(str(overview.get("as_of", "—")))
        banner += (f'<div style="color:#484f58; font-size:11px;">'
                   f"sondes to_regclass LIVE &middot; as_of {as_of} &middot; "
                   f"&eacute;tat de d&eacute;ploiement uniquement — jamais un "
                   f"feu de sant&eacute;</div></div>")
        body = render_refresh_link("/cc/perception") + banner
        for (slug, title, human, _collector), data in zip(_PANELS, panel_data):
            body += (
                f'<h2><a href="/cc/perception/{slug}" '
                f'style="color:#58a6ff;">{html.escape(title)}</a> '
                f'<span style="color:#8b949e; text-transform:none;">'
                f"— {html.escape(human)}</span></h2>"
            )
            body += _render_panel_body(data, full=False)
        return render_page("Perception — Tableau de preuves", body)

    def _make_panel_route(slug: str, title: str, human: str,
                          collector: Callable[..., dict[str, Any]]) -> None:
        @a.get(f"/cc/perception/{slug}", include_in_schema=False)
        async def panel_page(request: Request,
                             principal: dict = Depends(session_html_dep)) -> Any:
            audit_read_log(f"/cc/perception/{slug}", principal.get("sub", "?"))
            # Q5/Q8 : clé de drill optionnelle (validée par le collecteur/
            # whitelist ; JAMAIS journalisée dans l'audit log). Collecteur
            # sync → threadpool (event loop jamais bloqué par la DB).
            if slug == "q5":
                data = await run_in_threadpool(
                    perception.panel_q5, request.query_params.get("id"))
            elif slug == "q8":
                data = await run_in_threadpool(
                    perception.panel_q8, request.query_params.get("uid"))
            else:
                data = await run_in_threadpool(collector)
            body = render_refresh_link(f"/cc/perception/{slug}")
            body += f"<p>{html.escape(human)}</p>"
            body += _render_panel_body(data, full=True)
            return render_page(f"Perception — {title}", body)

    for slug, title, human, collector in _PANELS:
        _make_panel_route(slug, title, human, collector)

    @a.get("/cc/perception/receipts", include_in_schema=False)
    async def perception_receipts(request: Request,
                                  principal: dict = Depends(session_html_dep)) -> Any:
        """Drill-to-receipt générique : lignes BRUTES de la requête
        whitelistée `t` + le SQL exact (la constante importée)."""
        # route + principal SEULEMENT — jamais les valeurs de params.
        audit_read_log("/cc/perception/receipts", principal.get("sub", "?"))
        t = request.query_params.get("t", "")
        result = await run_in_threadpool(
            perception.drill_rows, t, dict(request.query_params))
        body = render_refresh_link(str(request.url.path) + "?"
                                   + str(request.url.query))
        if result.get("error") == "bad_request":
            body += ('<p class="unavailable">Requête refusée (whitelist) : '
                     f"{html.escape(str(result.get('detail', '')))}</p>")
            return render_page("Perception — Reçus", body)
        body += '<div class="tiles">' + render_tile(
            "lignes", len(result.get("rows", []))) + "</div>"
        if result.get("error") == "not_deployed":
            body += ('<p class="unavailable">Organe NON DÉPLOYÉ (table absente '
                     "— migration GO-gatée) — SQL documentaire ci-dessous.</p>")
        elif result.get("error"):
            body += ('<p class="unavailable">Source INDISPONIBLE (collecte en '
                     "échec, DB injoignable) — SQL documentaire ci-dessous.</p>")
        else:
            body += render_table(result.get("headers", []),
                                 [[c if c is not None else "—" for c in row]
                                  for row in result.get("rows", [])])
        body += render_sql_block(result.get("sql", ""),
                                 origin=f"whitelist t={t}")
        return render_page("Perception — Reçus bruts", body)
