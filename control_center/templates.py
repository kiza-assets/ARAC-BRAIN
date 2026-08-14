"""ARAC — Control Center : rendu HTML (stdlib uniquement, zéro Jinja2).

Doctrine : OBSERVE FIRST. DO NOT CONTROL. + READ ONLY.

Ce module génère du HTML via concaténation Python + html.escape() stdlib.
Jinja2 N'EST PAS installé sur l'instance — aucune dépendance externe ici.

Garanties :
  - Tout contenu dynamique est échappé via html.escape() (injection XSS impossible).
  - Zéro <form method="post"> ni méthode HTTP mutatrice dans les rendus.
  - Le seul «bouton» interactif est un lien GET (⟳ Rafraîchir → <a href>).
  - Aucun CDN, aucune ressource externe — CSS inline uniquement.
  - Aucune écriture DB, aucun subprocess, aucune action système.
"""

from __future__ import annotations

import html
from typing import Any

from starlette.responses import HTMLResponse

# ============================================================================
# CSS inline (copié dans chaque page — minimaliste, sans dépendance externe)
# ============================================================================

_CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: 'Courier New', Courier, monospace;
    background: #0d1117;
    color: #c9d1d9;
    font-size: 14px;
    line-height: 1.6;
}
header {
    background: #161b22;
    border-bottom: 2px solid #21262d;
    padding: 12px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
}
header .brand {
    font-size: 16px;
    font-weight: bold;
    color: #f0f6fc;
    letter-spacing: 0.05em;
}
header .mode-badge {
    background: #1f6feb;
    color: #f0f6fc;
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 12px;
    font-weight: bold;
    letter-spacing: 0.08em;
}
nav {
    background: #161b22;
    border-bottom: 1px solid #21262d;
    padding: 8px 24px;
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
}
nav a {
    color: #58a6ff;
    text-decoration: none;
    padding: 4px 10px;
    border-radius: 6px;
    font-size: 13px;
    border: 1px solid #30363d;
}
nav a:hover { background: #21262d; }
main {
    max-width: 1200px;
    margin: 0 auto;
    padding: 24px;
}
h1 {
    font-size: 20px;
    color: #f0f6fc;
    margin-bottom: 20px;
    border-bottom: 1px solid #21262d;
    padding-bottom: 10px;
}
h2 {
    font-size: 15px;
    color: #8b949e;
    margin: 24px 0 12px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
}
.tiles {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    margin-bottom: 24px;
}
.tile {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 14px 18px;
    min-width: 180px;
    flex: 1;
}
.tile .tile-label {
    font-size: 11px;
    color: #8b949e;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-bottom: 6px;
}
.tile .tile-value {
    font-size: 22px;
    color: #f0f6fc;
    font-weight: bold;
}
.tile .tile-value.small {
    font-size: 13px;
    word-break: break-all;
}
table {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 20px;
    background: #161b22;
    border-radius: 8px;
    overflow: hidden;
}
th {
    background: #21262d;
    color: #8b949e;
    text-align: left;
    padding: 8px 12px;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    border-bottom: 1px solid #30363d;
}
td {
    padding: 8px 12px;
    border-bottom: 1px solid #21262d;
    color: #c9d1d9;
    font-size: 13px;
    word-break: break-all;
}
tr:last-child td { border-bottom: none; }
tr:hover td { background: #1c2128; }
.empty-state {
    color: #8b949e;
    font-style: italic;
    padding: 12px;
}
.refresh-link {
    display: inline-block;
    color: #58a6ff;
    text-decoration: none;
    border: 1px solid #30363d;
    padding: 6px 14px;
    border-radius: 6px;
    font-size: 12px;
    margin-bottom: 20px;
}
.refresh-link:hover { background: #21262d; }
.observe-banner {
    background: #0d419d;
    border: 1px solid #1f6feb;
    border-radius: 8px;
    padding: 12px 18px;
    margin-bottom: 20px;
    font-size: 13px;
    color: #cae8ff;
}
.login-box {
    max-width: 440px;
    margin: 60px auto;
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 32px;
}
.login-box h1 { border: none; }
.login-field {
    margin: 16px 0;
}
.login-field label {
    display: block;
    font-size: 12px;
    color: #8b949e;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 6px;
}
.login-field input {
    width: 100%;
    background: #0d1117;
    border: 1px solid #30363d;
    color: #c9d1d9;
    padding: 8px 12px;
    border-radius: 6px;
    font-family: inherit;
    font-size: 14px;
}
.unavailable {
    color: #f85149;
    font-size: 12px;
    font-style: italic;
}
.absence {
    background: #161b22;
    border: 1px solid #30363d;
    border-left: 3px solid #d29922;
    border-radius: 6px;
    padding: 12px 16px;
    margin: 12px 0;
    font-size: 13px;
}
.absence .absence-reason { color: #c9d1d9; }
.absence .absence-gesture {
    color: #8b949e;
    font-size: 12px;
    margin-top: 8px;
}
.absence .absence-gesture code {
    color: #58a6ff;
    background: #0d1117;
    padding: 1px 5px;
    border-radius: 4px;
}
footer {
    background: #161b22;
    border-top: 1px solid #21262d;
    padding: 10px 24px;
    text-align: center;
    font-size: 11px;
    color: #484f58;
    margin-top: 40px;
}
"""

# ============================================================================
# Navigation
# ============================================================================

_NAV_LINKS = [
    ("/cc/", "⊞ Overview"),
    ("/cc/brain", "⊕ Brain"),
    ("/cc/memory", "⬡ Memory"),
    ("/cc/queues", "↕ Queues"),
    ("/cc/council", "⚖ Council"),
    ("/cc/sobriety", "⛽ Sobriety"),
    ("/cc/reports", "⊟ Reports"),
    ("/cc/decisions", "⊛ Decisions"),
    ("/cc/commits", "⊕ Commits"),
    ("/cc/system", "⊙ System"),
    ("/cc/tmux", "⊞ Tmux"),
    ("/cc/timeline", "⊘ Timeline"),
    ("/cc/perception", "⊚ Perception"),
]


def _nav_html() -> str:
    """Génère la barre de navigation (liens GET uniquement)."""
    links = "".join(
        f'<a href="{html.escape(href)}">{html.escape(label)}</a>'
        for href, label in _NAV_LINKS
    )
    return f"<nav>{links}</nav>"


# ============================================================================
# Composants publics
# ============================================================================


def render_tile(label: str, value: Any, small: bool = False) -> str:
    """Rend une tuile key/value avec échappement HTML.

    Args:
        label: libellé de la tuile (texte affiché en petit).
        value: valeur principale (convertie en str, échappée).
        small: si True, applique la classe 'small' pour les longues valeurs.

    Returns:
        Fragment HTML <div class="tile">...</div> (JAMAIS de form/action).
    """
    escaped_label = html.escape(str(label))
    escaped_value = html.escape(str(value))
    size_class = " small" if small else ""
    return (
        f'<div class="tile">'
        f'<div class="tile-label">{escaped_label}</div>'
        f'<div class="tile-value{size_class}">{escaped_value}</div>'
        f"</div>"
    )


def render_table(headers: list[str], rows: list[list[Any]]) -> str:
    """Rend une table HTML avec échappement de toutes les cellules.

    Args:
        headers: liste des en-têtes de colonnes.
        rows:    liste de lignes, chaque ligne étant une liste de valeurs.

    Returns:
        Fragment HTML <table>...</table> (lecture seule, zéro action mutatrice).
        Si rows est vide, retourne un paragraphe « Aucune donnée ».
    """
    if not rows:
        return '<p class="empty-state">Aucune donnée disponible.</p>'

    th_cells = "".join(f"<th>{html.escape(str(h))}</th>" for h in headers)
    thead = f"<thead><tr>{th_cells}</tr></thead>"

    tbody_rows = []
    for row in rows:
        tds = "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row)
        tbody_rows.append(f"<tr>{tds}</tr>")
    tbody = f"<tbody>{''.join(tbody_rows)}</tbody>"

    return f"<table>{thead}{tbody}</table>"


def render_refresh_link(href: str) -> str:
    """Rend un lien de rafraîchissement GET (jamais un formulaire mutateur).

    Args:
        href: URL cible (chemin interne /cc/...). Échappé en attribut HTML.

    Returns:
        Fragment HTML <a href="..." class="refresh-link">⟳ Rafraîchir</a>.
        C'est un GET pur — aucune action serveur déclenchée.
    """
    return f'<a href="{html.escape(href)}" class="refresh-link">&#x27F3; Rafra&icirc;chir</a>'


def render_sql_block(sql: str, origin: str = "") -> str:
    """Rend la requête SQL EXACTE exécutée (signature du cockpit PERCEPTION).

    Le texte affiché doit être LA constante importée du module SQL partagé
    (``control_center.sql.perception_queries``) — jamais une copie — sinon le
    panneau ment sur sa propre requête (anti-fabrication).

    <details> natif HTML (zéro JS). Tout est échappé via html.escape().
    """
    origin_html = (
        f'<div style="color:#8b949e; font-size:11px; margin:4px 0;">'
        f"{html.escape(origin)}</div>" if origin else ""
    )
    return (
        "<details style='margin:8px 0;'>"
        "<summary style='color:#58a6ff; cursor:pointer; font-size:12px;'>"
        "SQL ex&eacute;cut&eacute;</summary>"
        f"{origin_html}"
        f"<pre style='background:#161b22; border:1px solid #30363d; "
        f"border-radius:6px; padding:12px; font-size:11px; overflow-x:auto; "
        f"white-space:pre-wrap; word-break:break-word;'>{html.escape(sql)}</pre>"
        "</details>"
    )


def render_absence(reason: str | None, gesture: str | None = None) -> str:
    """Rend une absence DÉCLARÉE : pourquoi c'est vide, et ce qui le remplirait.

    POURQUOI CE RENDU EXISTE
    ------------------------
    Certaines sources du cockpit ne sont produites par AUCUN code de ce dépôt :
    un registre de décisions, des sessions de délibération, une convention de
    nommage de branches. Chez un cerveau neuf elles n'existent pas, et leurs
    pages sont donc vides — définitivement, tant que le lecteur n'a pas décidé
    de les tenir lui-même.

    Un tableau vide sans un mot ne distingue pas trois situations très
    différentes : le cockpit est cassé, la base est tombée, ou il n'y a
    simplement rien à montrer parce que rien ne l'écrit. Le lecteur conclut au
    pire, et il a raison de le faire. Une page qui ne peut rien afficher doit
    donc NOMMER ce qui manque et le geste qui le créerait — sinon elle ment par
    silence.

    Ce rendu ne fabrique aucun texte : il n'affiche que la ``reason`` et le
    ``gesture`` déclarés par le collecteur, qui sont seuls à connaître le chemin
    réellement consulté. Tout est échappé.

    Args:
        reason:  ce qui manque, tel que le collecteur l'a constaté.
        gesture: le geste qui le remplirait. Facultatif.

    Returns:
        Fragment HTML, ou chaîne vide si aucune raison n'est déclarée — une
        absence non déclarée ne doit pas inventer de message générique ici.
    """
    if not (reason or "").strip():
        return ""
    gesture_html = ""
    if (gesture or "").strip():
        gesture_html = (
            f'<div class="absence-gesture">Ce qui la remplirait : '
            f"{html.escape(str(gesture))}</div>"
        )
    return (
        '<div class="absence">'
        f'<div class="absence-reason">{html.escape(str(reason))}</div>'
        f"{gesture_html}"
        "</div>"
    )


def render_limite(limite: str | None, ailleurs: str | None = None) -> str:
    """Rend une LIMITE déclarée : ce que cette page ne peut pas faire, et où
    le geste se fait réellement.

    POURQUOI CE RENDU N'EST PAS ``render_absence``
    ----------------------------------------------
    Une absence dit « il n'y a rien ici, et voici ce qui le remplirait ». Une
    limite dit autre chose : « il y a bien quelque chose ici, mais vous ne
    pouvez pas l'actionner depuis cette page ». Servir la seconde avec le
    gabarit de la première fait afficher « Ce qui la remplirait » au-dessus
    d'un tableau plein — un contresens à l'écran.

    Le cas qui a rendu ce rendu nécessaire : la file de propositions. Elle
    s'affiche, elle est pleine, et la documentation promet qu'on la tranche
    chaque semaine depuis le cockpit. Or le cockpit n'a aucune route
    d'écriture. La page doit donc dire les deux choses — ce qu'elle ne peut
    pas, et où cela se fait — sans prétendre être vide.

    Ce rendu ne fabrique aucun texte : il n'affiche que ce qu'on lui déclare,
    échappé.

    Args:
        limite:   ce que cette page ne peut pas faire.
        ailleurs: où le geste existe réellement. Facultatif.

    Returns:
        Fragment HTML, ou chaîne vide si aucune limite n'est déclarée.
    """
    if not (limite or "").strip():
        return ""
    ailleurs_html = ""
    if (ailleurs or "").strip():
        ailleurs_html = (
            f'<div class="absence-gesture">Où le geste se fait : '
            f"{html.escape(str(ailleurs))}</div>"
        )
    return (
        '<div class="absence limite">'
        f'<div class="absence-reason">{html.escape(str(limite))}</div>'
        f"{ailleurs_html}"
        "</div>"
    )


def render_evidence_number(value: Any, drill_href: str | None) -> str:
    """Rend un chiffre-preuve : lien GET vers ses reçus bruts (drill-to-receipt).

    Sans drill_href, rend la valeur simple échappée (jamais un faux lien).
    """
    escaped = html.escape(str(value))
    if not drill_href:
        return escaped
    return (
        f'<a href="{html.escape(drill_href)}" '
        f'style="color:#58a6ff; text-decoration:underline;">{escaped}</a>'
    )


# États d'organe (protocole d'honnêteté 3 états) → libellé + couleur.
# JAMAIS un feu de santé : uniquement l'état de DÉPLOIEMENT du substrat.
_ORGAN_STATES = {
    "deployed":     ("D&Eacute;PLOY&Eacute;", "#3fb950"),
    "armed_empty":  ("ARM&Eacute;-VIDE", "#d29922"),
    "partial":      ("PARTIEL", "#db6d28"),
    "not_deployed": ("NON D&Eacute;PLOY&Eacute;", "#8b949e"),
    "unavailable":  ("INDISPONIBLE", "#f85149"),
}


def render_organ_badge(label: str, state: str, as_of: str | None = None) -> str:
    """Pastille d'état d'organe (bandeau statique — emprunt minimal vision A).

    N'encode QUE l'état de déploiement (déployé / armé-vide / non-déployé /
    indisponible) + estampille as_of. Aucun jugement de santé, aucun JS,
    aucune animation.
    """
    text, color = _ORGAN_STATES.get(state, _ORGAN_STATES["unavailable"])
    as_of_html = (
        f'<span style="color:#484f58; font-size:10px;"> as_of {html.escape(as_of)}</span>'
        if as_of else ""
    )
    return (
        f'<span style="display:inline-block; border:1px solid {color}; '
        f'border-radius:12px; padding:2px 10px; margin:2px; font-size:11px;">'
        f"{html.escape(label)} &middot; "
        f'<span style="color:{color}; font-weight:bold;">{text}</span>'
        f"{as_of_html}</span>"
    )


#: Ce que le cockpit affiche quand le cerveau n'a pas encore de nom — ni le nom
#: d'un dépôt, ni celui de personne. Le repli doit rester lisible par un inconnu
#: qui vient d'ouvrir le cockpit avant d'avoir écrit `config/brain.toml`.
_BRAND_FALLBACK = "ARAC Control Center"


def brand() -> str:
    """La marque affichée en tête et en pied de page.

    POURQUOI : le cockpit n'appartient pas au dépôt qui l'a produit, il
    appartient au cerveau qu'il observe. Le nom vient donc de
    ``config/brain.toml`` (via ``arac_runtime.brain_name()``), jamais d'une
    constante gravée ici — une constante gravée, c'est le nom du cerveau d'un
    autre servi en HTML à chaque page.

    Un cockpit ouvert avant l'entretien doit quand même rendre ses pages : toute
    erreur de lecture de la configuration retombe donc sur un repli neutre.
    L'affichage n'est jamais une raison de refuser une page.
    """
    try:
        import arac_runtime

        name = (arac_runtime.brain_name() or "").strip()
    except Exception:
        return _BRAND_FALLBACK
    if not name:
        return _BRAND_FALLBACK
    return f"{name} — Control Center"


def render_page(title: str, body_html: str) -> HTMLResponse:
    """Rend une page HTML complète avec layout commun.

    Layout :
      - <header> : marque + badge READ ONLY
      - <nav> : liens GET vers les sections du Control Center
      - <main> : body_html injecté (doit déjà être du HTML valide et échappé)
      - <footer> : rappel lecture seule

    IMPORTANT : body_html est injecté SANS échappement supplémentaire.
    Il est de la responsabilité de l'appelant de s'assurer que tout
    CONTENU DYNAMIQUE dans body_html a été échappé via html.escape()
    AVANT d'être inséré dans body_html. Les helpers render_tile / render_table
    garantissent cet échappement. Ne jamais injecter directement des données
    utilisateur ou DB dans body_html sans passer par ces helpers.

    Args:
        title:     titre de la page (affiché dans <title> et <h1>).
        body_html: contenu HTML de la zone principale (déjà échappé).

    Returns:
        HTMLResponse Starlette (200, media_type text/html; charset=utf-8).
        Aucune dépendance externe (pas de Jinja2, pas de CDN).
    """
    escaped_title = html.escape(str(title))
    escaped_brand = html.escape(brand())
    page = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escaped_brand} — {escaped_title}</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <span class="brand">{escaped_brand}</span>
  <span>OBSERVE FIRST &middot; READ ONLY</span>
  <span class="mode-badge">READ-ONLY</span>
</header>
{_nav_html()}
<main>
<h1>{escaped_title}</h1>
{body_html}
</main>
<footer>lecture seule &mdash; aucune action &mdash; {escaped_brand} &mdash; mode observation</footer>
</body>
</html>"""
    return HTMLResponse(content=page, status_code=200)
