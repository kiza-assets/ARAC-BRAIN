"""Discipline du frontend du cockpit — assertion **G2** du mandat.

    « Le Control Center n'affiche jamais de données calculées par le frontend.
      Aucun chiffre ne doit être simulé. Aucun JSON statique. Aucun mock. »

Ces tests lisent les sources du frontend et cherchent la trace d'une donnée
inventée ou d'un calcul métier côté client. Ils sont **tolérants à l'absence** :
tant que le frontend n'existe pas, ils sont ignorés plutôt qu'en échec — un test
rouge parce qu'une étape n'est pas commencée n'apprend rien à personne.

Le contrôle le plus fort est ``test_no_known_metric_value_is_hardcoded`` : il
cherche dans le JavaScript les valeurs RÉELLES mesurées du cerveau. Si l'une
d'elles y figure en dur, c'est qu'une donnée a été recopiée au lieu d'être
demandée à l'API — exactement ce que le mandat interdit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parent.parent / "control_center" / "cc_v1" / "static"
_JS = _STATIC / "app.js"
_CSS = _STATIC / "ds.css"
_HTML = _STATIC / "index.html"


def _read(p: Path) -> str:
    if not p.exists():
        pytest.skip(f"{p.name} pas encore construit — étape non commencée")
    return p.read_text(encoding="utf-8", errors="replace")


def _strip_comments_and_strings(js: str) -> str:
    """Retire commentaires et littéraux de chaîne.

    Les valeurs qu'on traque ne comptent que si elles sont du **code**. Une
    valeur citée dans un commentaire explicatif est de la documentation, pas une
    simulation — et le nom d'une clé de métrique contient parfois un chiffre.
    """
    js = re.sub(r"/\*.*?\*/", " ", js, flags=re.S)
    js = re.sub(r"(?m)//.*$", " ", js)
    js = re.sub(r"'(?:\\.|[^'\\])*'", "''", js)
    js = re.sub(r'"(?:\\.|[^"\\])*"', '""', js)
    js = re.sub(r"`(?:\\.|[^`\\])*`", "``", js)
    return js


# ============================================================================
# Aucune donnée simulée
# ============================================================================


def test_no_random_no_mock_no_fixture():
    """Un cockpit qui invente une valeur ne peut plus être cru sur aucune autre."""
    js = _read(_JS)
    for pattern, why in (
        (r"Math\.random", "valeur aléatoire"),
        (r"\bmock[A-Z_]?\w*\b", "donnée simulée"),
        (r"\bfixtures?\b", "jeu de données figé"),
        (r"\bfakeD?a?t?a?\b", "donnée factice"),
        (r"\bdummy\b", "donnée bouchon"),
        (r"\bsampleData\b", "donnée d'exemple"),
        (r"\bplaceholderData\b", "donnée de remplissage"),
    ):
        hits = [m.start() for m in re.finditer(pattern, js, re.IGNORECASE)]
        assert not hits, (
            f"app.js contient une {why} ({pattern!r}) à {len(hits)} endroit(s) — "
            "le mandat interdit toute donnée non issue du moteur."
        )


#: Valeurs RÉELLES du cerveau, mesurées le 2026-08-03. Aucune ne doit apparaître
#: en dur dans le code du frontend : elles se demandent, elles ne se recopient pas.
_LIVE_VALUES: tuple[tuple[str, str], ...] = (
    ("1712", "atomes actifs"),
    ("1875", "atomes totaux"),
    ("125905", "messages bruts"),
    ("125536", "messages bruts (mesure antérieure)"),
    ("3218", "reçus de rappel"),
    ("3726", "appels d'audit"),
    ("5473", "manifestes de capture"),
    ("388", "passages en quarantaine"),
    ("332", "conversations saines jetées"),
    ("755", "atomes jamais rappelés"),
    ("157", "dette root-level"),
)


def test_no_known_metric_value_is_hardcoded():
    """Le contrôle le plus discriminant : une valeur du cerveau écrite en dur.

    Si ``1712`` apparaît dans le code, c'est que quelqu'un a recopié un chiffre
    au lieu de le demander. Le jour où le cerveau en aura 1713, l'interface
    mentira — et c'est exactement le défaut que ce produit refuse.
    """
    code = _strip_comments_and_strings(_read(_JS))
    faults = []
    for value, meaning in _LIVE_VALUES:
        if re.search(rf"(?<![\w.]){re.escape(value)}(?![\w.])", code):
            faults.append(f"{value} ({meaning})")
    assert not faults, (
        "Valeurs réelles du cerveau écrites en dur dans app.js : "
        + ", ".join(faults)
        + ". Ces chiffres doivent venir de /cc/v1/metrics, pas du code."
    )


def test_data_comes_from_the_api():
    """Le frontend doit effectivement interroger le BFF."""
    js = _read(_JS)
    assert "/cc/v1/" in js, "app.js n'appelle aucune route /cc/v1/* — d'où viennent ses chiffres ?"
    assert re.search(r"\bfetch\s*\(|EventSource\s*\(", js), (
        "app.js ne fait ni fetch ni EventSource — il ne peut pas afficher de données réelles."
    )


# ============================================================================
# Aucun calcul métier côté client
# ============================================================================


def test_no_client_side_aggregation():
    """Les agrégats appartiennent au moteur.

    Somme, moyenne, ratio : si le client les calcule, deux écrans peuvent
    diverger et plus aucun chiffre n'est opposable. Le formatage reste permis —
    c'est de la présentation, pas de l'arithmétique métier.
    """
    code = _strip_comments_and_strings(_read(_JS))
    suspects = [
        (r"\.reduce\s*\(\s*\(?\s*\w+\s*,\s*\w+\s*\)?\s*=>\s*\w+\s*\+", "somme via reduce()"),
        (r"\breduce\s*\(\s*function", "agrégation via reduce(function)"),
        (r"/\s*(?:total|count|sum|length)\b", "division par un total (ratio calculé client)"),
        (r"\*\s*100\b", "conversion en pourcentage côté client"),
    ]
    faults = [why for pat, why in suspects if re.search(pat, code)]
    assert not faults, (
        "Calcul métier détecté dans app.js : " + " ; ".join(faults)
        + ". L'arithmétique doit être en SQL, dans le moteur."
    )


# ============================================================================
# Autonomie et accessibilité
# ============================================================================


def test_no_client_side_counting_of_truncated_lists():
    """Compter les lignes reçues est un calcul métier — le plus sournois de tous.

    Régression trouvée le 2026-08-03 : le nombre de décisions d'un projet était
    rendu par ``fmtNum(rows.length)`` sur une liste que le SQL avait déjà bornée à
    25 lignes par nature. Le chiffre affiché était donc produit par le navigateur,
    et faux dès qu'un projet dépassait la borne — alors que l'API servait le total.

    ``.length`` reste légitime pour décider d'un rendu (``rows.length ? table : vide``).
    Il devient une faute dès qu'il est **affiché** comme une valeur du cerveau.

    Deux usages ne sont donc PAS signalés :
      * ``rows.length ? … : …`` — une condition de rendu, rien n'est affiché ;
      * compter un inventaire d'INTERFACE (« 12 métriques ») — c'est un fait sur
        l'écran, pas une donnée du cerveau, et la liste n'est jamais tronquée.

    Le formateur ``fmtNum`` est réservé aux valeurs du cerveau : l'appliquer à un
    ``.length`` est donc le signal net d'un compte qui aurait dû venir du moteur.
    """
    js = _read(_JS)
    faults = []
    for m in re.finditer(r"fmtNum\(\s*(\w+)\.length\s*\)", js):
        line = js[: m.start()].count("\n") + 1
        faults.append(f"ligne {line} : fmtNum({m.group(1)}.length)")
    # `text: x.length` affiché — mais pas `text: x.length ? …` (ternaire = condition).
    # L'espace doit être DANS le lookahead : sinon `\s*` le consomme par retour
    # arrière et la garde tombe sur l'espace au lieu de l'opérateur qui suit.
    for m in re.finditer(r"text\s*:\s*(?:String\()?\s*(\w+)\.length(?!\s*[?&|=])", js):
        line = js[: m.start()].count("\n") + 1
        faults.append(f"ligne {line} : text: {m.group(1)}.length")
    assert not faults, (
        "Compte affiché calculé côté client : " + " ; ".join(faults)
        + ". Le total doit venir du moteur — une liste reçue peut être tronquée."
    )


def test_no_control_bytes_in_served_files():
    """Aucun octet de contrôle dans un fichier servi — la vérifiabilité en dépend.

    Régression trouvée le 2026-08-04 : un seul octet NUL, utilisé comme sentinelle
    de secteur (``'\\x00autres'``), suffisait à faire classer tout ``app.js`` comme
    binaire par GNU grep. ``grep -n "Math.random" app.js`` répondait alors
    silencieusement vide — un audit du frontend délivrait un blanc-seing **sans
    avoir rien lu**. Un fichier qu'on ne peut pas fouiller ne peut pas être audité.
    """
    autorises = {0x09, 0x0A, 0x0D}  # tabulation, saut de ligne, retour chariot
    for path in (_JS, _CSS, _HTML):
        if not path.exists():
            continue
        raw = path.read_bytes()
        fautifs = sorted({b for b in raw if b < 0x20 and b not in autorises})
        assert not fautifs, (
            f"{path.name} contient des octets de contrôle {[hex(b) for b in fautifs]} — "
            "ils rendent le fichier binaire pour grep et le soustraient à tout audit."
        )


def test_no_external_dependency():
    """Le cockpit doit fonctionner hors ligne : aucun CDN, aucune police distante."""
    for path in (_JS, _CSS, _HTML):
        if not path.exists():
            continue
        txt = path.read_text(encoding="utf-8", errors="replace")
        for pattern in (r"https?://(?!127\.0\.0\.1|localhost)", r"fonts\.googleapis",
                        r"cdn\.", r"unpkg\.com", r"jsdelivr"):
            assert not re.search(pattern, txt), (
                f"{path.name} dépend d'une ressource externe ({pattern!r}) — "
                "le cockpit doit fonctionner sans réseau."
            )


def test_reduced_motion_is_honoured():
    """Le seul élément qui respire doit cesser si l'utilisateur refuse le mouvement."""
    css = _read(_CSS)
    assert "prefers-reduced-motion" in css, (
        "ds.css ne respecte pas prefers-reduced-motion — la respiration de l'indice "
        "doit pouvoir être coupée sans perte d'information."
    )


def test_semantic_tokens_are_declared():
    """Les jetons de la direction E doivent exister : c'est l'identité du produit."""
    css = _read(_CSS).lower()
    for token in ("--acc", "--amber", "--ok", "--crit", "--na", "--bg", "--t1", "--t2"):
        assert token in css, f"ds.css ne déclare pas le jeton {token}"


def test_tabular_numerals_are_used():
    """Un chiffre qui saute quand la valeur change détruit le calme de l'écran."""
    css = _read(_CSS)
    assert "tabular-nums" in css, (
        "ds.css n'utilise pas font-variant-numeric: tabular-nums sur les valeurs."
    )


# ============================================================================
# Contraste — mesuré, pas déclaré
# ============================================================================
#
# Le fichier de discipline ne CALCULAIT aucun rapport : il vérifiait que les
# jetons existent, jamais qu'ils sont lisibles là où ils sont posés. Deux passes
# de remontée AA avaient donc été écrites « à l'œil », et la seconde a dû
# rattraper 20 règles que la première avait manquées. Les tests ci-dessous
# calculent la luminance relative WCAG et rejouent la cascade CSS : une teinte
# qui redescend sous le seuil, ou une règle de texte réécrite en --t3/--na,
# fait échouer la suite au lieu d'attendre un audit.


def _relative_luminance(hex_color: str) -> float:
    """Luminance relative WCAG 2.x d'une couleur ``#rrggbb``."""
    h = hex_color.lstrip("#")
    channels = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(a: str, b: str) -> float:
    """Rapport de contraste WCAG entre deux couleurs opaques."""
    la, lb = _relative_luminance(a), _relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _tokens(css: str) -> dict[str, str]:
    """Les jetons de couleur hexadécimaux déclarés dans ``:root``."""
    return {m.group(1): m.group(2) for m in re.finditer(r"(--[a-z0-9]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;", css)}


#: Les trois SURFACES sur lesquelles du texte est réellement posé. Mesurer un
#: texte sur --bg alors qu'il est posé sur --s2 flatte le rapport de ~0,4 point :
#: c'est l'erreur exacte qu'avait faite la première passe de remontée AA.
_SURFACES = ("--bg", "--s1", "--s2")

#: Seuil AA pour du texte courant. Le seuil « grand texte » (3:1) exige 18,66 px
#: ou 14 pt gras : aucune des teintes secondaires du cockpit n'est employée à
#: cette taille, il n'est donc jamais invocable ici.
_AA_TEXT = 4.5


def test_text_tokens_pass_aa_on_every_surface():
    """Les teintes de TEXTE doivent passer AA sur les trois surfaces du cockpit.

    Garde de régression sur les jetons eux-mêmes : assombrir --t2 « pour le
    calme » casserait d'un coup toute la lisibilité du produit, silencieusement.
    """
    css = _read(_CSS)
    tok = _tokens(css)
    for name in ("--t1", "--t2", *_SURFACES):
        assert name in tok, f"ds.css ne déclare plus le jeton {name} en hexadécimal"
    faults = []
    for fg in ("--t1", "--t2"):
        for surface in _SURFACES:
            ratio = _contrast(tok[fg], tok[surface])
            if ratio < _AA_TEXT:
                faults.append(f"{fg} ({tok[fg]}) sur {surface} ({tok[surface]}) = {ratio:.2f}:1")
    assert not faults, (
        "Teintes de texte sous le seuil AA de 4.5:1 : " + " ; ".join(faults)
        + ". Ces deux jetons portent TOUT le texte lisible du cockpit."
    )


def test_sub_aa_tokens_are_known_to_be_sub_aa():
    """--t3 et --na sont sous AA : c'est un FAIT, et le test l'ancre.

    Si un jour ils repassent au-dessus du seuil, la doctrine « ils ne portent que
    du non-texte » devient inutilement sévère — et ce test le dira. Tant qu'ils
    sont sous le seuil, le test suivant a une raison d'exister.
    """
    tok = _tokens(_read(_CSS))
    for name in ("--t3", "--na"):
        worst = min(_contrast(tok[name], tok[s]) for s in _SURFACES)
        assert worst < _AA_TEXT, (
            f"{name} passe désormais AA partout (pire cas {worst:.2f}:1) — "
            "la liste blanche de test_no_readable_text_uses_a_sub_aa_token peut être allégée."
        )


def _color_rules(css: str) -> list[tuple[int, str, str]]:
    """Toutes les déclarations ``color:`` du fichier, à plat, dans l'ordre du texte.

    Rend ``(ligne, sélecteur normalisé, valeur)``. Les listes de sélecteurs sont
    éclatées — c'est la forme du bloc de remontée AA, et une remontée ne compte
    que si elle vise le sélecteur fautif. ``border-color`` / ``background-color``
    sont exclus : ils ne peignent pas du texte.
    """
    # Neutraliser les commentaires SANS déplacer les lignes.
    noc = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", "", m.group(0)), css, flags=re.S)
    out: list[tuple[int, str, str]] = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", noc):
        decl = re.search(r"(?<![-\w])color\s*:\s*([^;}]+)", m.group(2))
        if not decl:
            continue
        line = noc[: m.start(1)].count("\n") + 1
        prelude = m.group(1)
        # Un `@media (...) {` précède le premier sélecteur de son bloc.
        prelude = re.sub(r".*\}", "", prelude, flags=re.S)
        prelude = re.sub(r"@[^{]*\{", "", prelude)
        for sel in prelude.split(","):
            sel = " ".join(sel.split())
            if sel:
                out.append((line, sel, decl.group(1).strip()))
    return out


#: Sélecteurs autorisés à porter --t3 ou --na SUR UN `color`, avec la raison.
#: Aucun d'eux n'affiche de mot ni de chiffre : ce sont des glyphes de
#: remplacement redondants avec un libellé voisin, ou un composant inactif.
#: Toute nouvelle entrée doit être justifiée ici — c'est le point de friction
#: qui empêche la doctrine de se déliter règle après règle.
_NON_TEXT_COLOR_RULES: dict[str, str] = {
    '.vital[data-state="unavailable"] .vital-value': "affiche « — », jamais un nombre",
    '.health[data-state="unavailable"] .health-value': "affiche « — », jamais un nombre",
    '.card[data-state="unavailable"] .card-value': "affiche « — » (aucune métrique servie n'est unavailable avec une valeur)",
    'table.data td.na': "cellule nulle : le contenu est « — »",
    '.tab[data-state="unavailable"] .tab-count': "compte non mesurable : le contenu est « — »",
    '.glyph[data-state="unavailable"]': "losange creux ◇ — un dessin, doublé par le mot d'état",
    '.na-title .glyph': "losange creux ◇ — un dessin, doublé par le titre",
    '.chip[data-state="unavailable"] .glyph': "losange creux ◇ — un dessin, doublé par le mot de la pastille",
    '.crumbs .sep': "séparateur de fil d'Ariane — un trait, pas un mot",
    '.casc-dot[data-state="skipped"]': "nœud de la cascade — un dessin, doublé par le mot d'étape",
    '.casc-dot[data-state="unavailable"]': "nœud de la cascade — un dessin, doublé par le mot d'étape",
    '.rp-play[disabled]': "WCAG 1.4.3 exempte le texte d'un composant INACTIF ; le bouton est réellement disabled",
}


def test_no_readable_text_uses_a_sub_aa_token():
    """Aucun TEXTE ne reste peint en --t3 ou --na — cascade rejouée, pas devinée.

    Régression trouvée le 2026-08-05 : la première passe de remontée AA ne
    couvrait que la surface V1. Le CSS écrit ensuite (bande temporelle, onglets,
    cascade, rejeu) a réintroduit --t3/--na sur du texte avec une spécificité
    SUPÉRIEURE — `.delta-foot .card-key` bat `.card-key` quel que soit l'ordre —
    donc gagnante. Vingt règles, de 2.80:1 à 3.45:1, dont le mot « non mesuré »
    qui EST la doctrine de l'écran.

    Le test rejoue la règle du dernier mot : pour un sélecteur donné, seule
    compte la DERNIÈRE déclaration de ``color``. Une remontée écrite sur un autre
    sélecteur (moins spécifique) ne compte donc pas — c'est exactement le piège
    dans lequel la première passe est tombée.
    """
    rules = _color_rules(_read(_CSS))
    last: dict[str, tuple[int, str]] = {}
    for line, sel, value in rules:
        last[sel] = (line, value)
    faults = []
    for sel, (line, value) in sorted(last.items(), key=lambda kv: kv[1][0]):
        if not re.search(r"var\(\s*--(t3|na)\s*\)", value):
            continue
        if sel in _NON_TEXT_COLOR_RULES:
            continue
        faults.append(f"ds.css:{line} `{sel}` → {value}")
    assert not faults, (
        "Texte peint dans une teinte sous le seuil AA (< 4.5:1) :\n  "
        + "\n  ".join(faults)
        + "\nSoit la règle passe à --t2 ou mieux, soit son sélecteur rejoint "
          "_NON_TEXT_COLOR_RULES avec la raison pour laquelle il n'affiche aucun mot."
    )


# ============================================================================
# Le tiroir de preuve doit sortir du flux quand il est fermé
# ============================================================================


def test_closed_drawer_is_removed_from_the_flow():
    """Un panneau `aria-hidden` ne doit contenir aucun élément focusable.

    Régression trouvée le 2026-08-05 : le tiroir fermé n'était masqué que par
    `transform: translateX(101%)`. Une translation ne retire rien du document —
    le bouton « Échap ✕ », les boutons « copier » et les lignes du tableau de
    preuve restaient tabulables hors écran. Après Échap, le focus clavier
    quittait la page ; et `aria-hidden="true"` posé sur un ancêtre d'éléments
    focusables est une violation ARIA documentée.

    La garde vérifie ce que le CSS AFFIRME : le tiroir fermé est `visibility:
    hidden` (donc ni focusable, ni lu, ni cliquable) et redevient `visible`
    ouvert. `display`, `inert` ou `content-visibility` conviendraient tout autant
    — le test accepte n'importe lequel, il refuse l'absence des trois.
    """
    css = _read(_CSS)
    closed = re.search(r"#drawer\s*\{([^}]*)\}", css)
    assert closed, "ds.css ne définit plus le tiroir #drawer"
    body = closed.group(1)
    assert re.search(r"(?<![-\w])(visibility\s*:\s*hidden|display\s*:\s*none|content-visibility\s*:\s*hidden)", body), (
        "#drawer fermé n'est masqué que par une transformation : ses boutons restent "
        "dans l'ordre de tabulation hors écran, sous un ancêtre aria-hidden.\n"
        + body.strip()
    )
    opened = re.search(r'#drawer\[data-open="1"\]\s*\{([^}]*)\}', css)
    assert opened, 'ds.css ne définit plus #drawer[data-open="1"]'
    assert re.search(r"(?<![-\w])(visibility\s*:\s*visible|display\s*:\s*flex|display\s*:\s*grid|content-visibility\s*:\s*visible)", opened.group(1)), (
        "#drawer ouvert ne rétablit pas sa visibilité — le tiroir resterait invisible "
        "après avoir été masqué à la fermeture."
    )


def test_drawer_markup_is_labelled_and_closable():
    """La coquille du tiroir doit rester un dialogue nommé, avec un bouton nommé."""
    html = _read(_HTML)
    drawer = re.search(r"<aside[^>]*id=\"drawer\"[^>]*>", html)
    assert drawer, "index.html ne contient plus le tiroir de preuve #drawer"
    tag = drawer.group(0)
    for attr in ('role="dialog"', "aria-labelledby=", "data-open="):
        assert attr in tag, f"le tiroir #drawer a perdu {attr} — il n'est plus annonçable"
    assert re.search(r'class="drawer-close"[^>]*aria-label="[^"]+"', html), (
        "le bouton de fermeture du tiroir n'a plus de nom accessible : « Échap ✕ » "
        "seul ne dit pas ce qu'il ferme."
    )


def test_aria_controls_point_to_existing_ids():
    """`aria-controls` doit désigner un élément QUI EXISTE, et le bon.

    Régression trouvée le 2026-08-05 : le bouton du flux annonçait contrôler
    `flux-body` (le journal d'événements) alors que la règle qui replie est
    `#flux[data-open="0"] .flux-body { display: none }` — dont le porteur est
    `flux-body-wrap`, qui contient aussi `flux-rest`. Un lecteur d'écran suivant
    la relation atterrissait dans le journal et manquait le reste replié.

    Le test vérifie deux choses : la cible existe, et — pour les boutons repliants
    — elle porte bien la classe que le CSS masque.
    """
    html = _read(_HTML)
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    faults = []
    for m in re.finditer(r'aria-controls="([^"]+)"', html):
        for target in m.group(1).split():
            if target not in ids:
                faults.append(f"aria-controls=\"{target}\" ne désigne aucun id de la page")
    assert not faults, "; ".join(faults)

    toggle = re.search(r'<button[^>]*id="flux-toggle"[^>]*>', html)
    assert toggle and 'aria-expanded=' in toggle.group(0), (
        "le bouton du flux n'annonce plus son état replié/déplié"
    )
    controls = re.search(r'aria-controls="([^"]+)"', toggle.group(0))
    assert controls, "le bouton du flux n'annonce plus la région qu'il replie"
    target = re.search(r'<[^>]*\bid="' + re.escape(controls.group(1)) + r'"[^>]*>', html)
    assert target, f"aucun élément ne porte l'id {controls.group(1)!r}"
    classes = re.search(r'class="([^"]*)"', target.group(0))
    assert classes and "flux-body" in classes.group(1).split(), (
        f"le bouton du flux dit replier #{controls.group(1)}, mais le CSS replie "
        "`.flux-body` (`#flux[data-open=\"0\"] .flux-body { display: none }`) — "
        "la relation annoncée ne décrit pas ce qui se replie."
    )


# ============================================================================
# Le journal de lecture doit rester tenable sur une ligne
# ============================================================================


def test_static_route_sanitises_the_journalled_path():
    """Un nom de fichier ne doit pas pouvoir forger une ligne du journal d'accès.

    Régression trouvée le 2026-08-05 : ``/cc/v1/static/{filename}`` journalise le
    nom demandé AVANT sa liste blanche — ce qui est juste, une tentative doit
    laisser une trace. Mais ``filename`` est un paramètre de CHEMIN, donc décodé :
    ``%0d%0a`` devient un vrai CRLF. Or ``audit_read_log`` écrit
    ``ISO8601 | CC_ACCESS | <principal> | <chemin>\\n`` et ne nettoie que le
    ``principal`` (security.py, red-team V1.7B). Un seul GET écrivait donc deux
    lignes dans un journal append-only, la seconde entièrement forgée.

    Le test exerce la ROUTE, avec un journal factice : c'est la valeur réellement
    remise au journal qui est vérifiée, pas une fonction interne.
    """
    fastapi = pytest.importorskip("fastapi", reason="fastapi absent — route non testable")
    testclient = pytest.importorskip("fastapi.testclient", reason="starlette TestClient absent")
    try:
        from control_center.cc_v1 import ui as cc_ui
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"control_center.cc_v1.ui non importable : {exc}")

    journal: list[str] = []
    app = fastapi.FastAPI()
    cc_ui.register(app, lambda: {"sub": "test"}, lambda path, principal: journal.append(path))
    client = testclient.TestClient(app)

    # `%2F` ne peut pas figurer dans la charge : Starlette décode le chemin AVANT
    # de router, un `/` ajouterait un segment et la route ne matcherait plus. La
    # ligne forgée se passe très bien de barre oblique.
    attacks = [
        "x%0d%0a2026-08-05T00:00:00Z%20%7C%20CC_ACCESS%20%7C%20root%20%7C%20forge",
        "y%0aforge",
        "z%00nul",
    ]
    for raw in attacks:
        journal.clear()
        client.get("/cc/v1/static/" + raw)
        assert journal, f"la tentative {raw!r} n'a laissé AUCUNE trace — le journal doit voir les refus"
        for line in journal:
            faulty = sorted({c for c in line if not c.isprintable()})
            assert not faulty, (
                f"le chemin journalisé pour {raw!r} contient {[hex(ord(c)) for c in faulty]} : "
                "une ligne du journal d'accès est forgeable depuis l'URL.\n" + repr(line)
            )

    # Le chemin légitime, lui, doit rester lisible tel quel.
    journal.clear()
    client.get("/cc/v1/static/ds.css")
    assert journal == ["/cc/v1/static/ds.css"], (
        f"le nettoyage a déformé un chemin légitime : {journal!r}"
    )
