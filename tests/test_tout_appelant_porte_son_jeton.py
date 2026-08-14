"""Le jour où le jeton est devenu exigé, ONZE appelants n'en portaient aucun.

Ce fichier est la moitié de la preuve qu'on oublie. Fermer la porte est facile ;
ce qui est difficile, c'est de ne pas casser le produit en la fermant. Le cycle,
le cockpit, les agents et le pont parlent tous à l'API par la boucle locale —
c'est-à-dire par le chemin qui vient d'être fermé. S'ils n'y présentent pas leur
jeton, l'installation démarre, aucun service ne tombe, et plus rien ne
fonctionne : le cockpit affiche « indisponible », le cycle n'écrit plus, et
personne ne sait pourquoi.

Deux gardes, et la seconde est celle qui vaut :

  1. `app/api_token.py` trouve le jeton là où systemd le pose — et refuse de
     deviner quand il y a plusieurs postes, parce que signer avec l'identité
     d'un autre poste produit un 403 incompréhensible ;

  2. AUCUN appel HTTP de ce dépôt vers l'API ne part sans en-têtes. C'est une
     garde de FORME, sur le texte des fichiers : elle attrape l'appel qu'un
     remaniement futur ajoutera sans y penser, ce qu'aucun test de
     comportement ne peut faire — il faudrait exécuter le cycle, le cockpit et
     les quatre agents contre une vraie API pour s'en apercevoir.

Hermétique : ni base, ni réseau, ni clé.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

import pytest

from app import api_token


RACINE = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 1. Où le jeton se trouve
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _environnement_nu(monkeypatch):
    """Aucune variable de jeton héritée de la machine qui lance la suite."""
    for cle in list(api_token.os.environ):
        if cle.startswith(api_token._PREFIXE_NODE) or cle in (
            api_token._VAR_CANONIQUE,
            "ARAC_NODE_ID",
        ):
            monkeypatch.delenv(cle, raising=False)
    api_token._reinitialiser_avertissement()
    yield
    api_token._reinitialiser_avertissement()


JETON = "a" * 64
AUTRE = "b" * 64


def test_le_nom_canonique_est_lu_en_premier(monkeypatch):
    """`ARAC_API_BEARER_TOKEN` : le nom que le bootstrap engendre."""
    monkeypatch.setenv(api_token._VAR_CANONIQUE, JETON)
    assert api_token.jeton_api() == JETON
    assert api_token.entetes_api() == {"Authorization": f"Bearer {JETON}"}


def test_le_nom_reconnu_par_l_api_marche_aussi(monkeypatch):
    """`ARAC_NODE_TOKEN_<SLUG>` : le nom sous lequel l'API le RECONNAÎT."""
    monkeypatch.setenv("ARAC_NODE_ID", "mon-portable")
    monkeypatch.setenv("ARAC_NODE_TOKEN_MON_PORTABLE", JETON)
    assert api_token.jeton_api() == JETON


def test_le_cycle_trouve_le_jeton_du_cerveau(monkeypatch):
    """L'unité du cycle pose `ARAC_NODE_ID=<poste>-cycle`.

    Ce poste-là n'a pas de jeton à lui — c'est le CERVEAU qui en a un. Sans
    cette règle, le cycle serait le seul appelant à repartir en 401, et il est
    aussi le seul dont l'échec ne se voit pas tout de suite : il tourne la
    nuit, en oneshot, et son reçu dit « interrompu ».
    """
    monkeypatch.setenv("ARAC_NODE_ID", "mon-portable-cycle")
    monkeypatch.setenv("ARAC_NODE_TOKEN_MON_PORTABLE", JETON)
    assert api_token.jeton_api() == JETON


def test_un_seul_poste_declare_leve_l_ambiguite(monkeypatch):
    """Dernier recours, et il n'est pas ambigu : il n'y a qu'un candidat."""
    monkeypatch.setenv("ARAC_NODE_TOKEN_UNIQUE", JETON)
    assert api_token.jeton_api() == JETON


def test_plusieurs_postes_sans_node_id_ne_devinent_PAS(monkeypatch):
    """Choisir au hasard, c'est signer avec l'identité de quelqu'un d'autre.

    L'API accepterait le jeton (il est valide), puis la liste blanche
    d'ingestion refuserait le node_id en 403 — un refus dont la cause est
    invisible. Mieux vaut ne rien envoyer et recevoir le 401 qui explique.
    """
    monkeypatch.setenv("ARAC_NODE_TOKEN_POSTE_A", JETON)
    monkeypatch.setenv("ARAC_NODE_TOKEN_POSTE_B", AUTRE)
    assert api_token.jeton_api() is None
    assert api_token.entetes_api() == {}


def test_deux_noms_pour_le_meme_jeton_ne_sont_pas_une_ambiguite(monkeypatch):
    """Le bootstrap recopie ARAC_API_BEARER_TOKEN vers l'alias du poste.

    Les deux variables portent alors la MÊME valeur. C'est le cas NORMAL d'une
    installation, pas un conflit : le refus de deviner porte sur des valeurs
    différentes, pas sur des noms différents.
    """
    monkeypatch.setenv("ARAC_NODE_TOKEN_POSTE_A", JETON)
    monkeypatch.setenv("ARAC_NODE_TOKEN_ANCIEN_NOM_DU_POSTE_A", JETON)
    assert api_token.jeton_api() == JETON


def test_l_absence_ne_leve_pas_mais_se_dit(monkeypatch, caplog):
    """Un cockpit qui refuse de démarrer est pire qu'un cockpit qui explique."""
    import logging

    with caplog.at_level(logging.WARNING, logger="arac.api_token"):
        assert api_token.entetes_api() == {}
    assert any(r.message == "api_token.absent" for r in caplog.records)


def test_le_jeton_n_est_JAMAIS_journalise(monkeypatch, caplog):
    """Un jeton dans un journal est un jeton public : les journaux se collent
    dans les rapports de bogue, et survivent à la rotation."""
    import logging

    monkeypatch.setenv(api_token._VAR_CANONIQUE, JETON)
    with caplog.at_level(logging.DEBUG, logger="arac.api_token"):
        api_token.entetes_api()
    tout = "\n".join(r.getMessage() + str(getattr(r, "cherche", "")) for r in caplog.records)
    assert JETON not in tout
    assert JETON[:8] not in tout


def test_les_entetes_supplementaires_sont_conserves(monkeypatch):
    monkeypatch.setenv(api_token._VAR_CANONIQUE, JETON)
    e = api_token.entetes_api({"X-ARAC-Node-Id": "mon-portable"})
    assert e["X-ARAC-Node-Id"] == "mon-portable"
    assert e["Authorization"] == f"Bearer {JETON}"


def test_la_convention_de_slug_est_celle_des_trois_autres_endroits():
    """`app/auth.py`, `verify_install.sh` (`tr 'a-z.-' 'A-Z__'`) et ce module
    doivent convertir un node_id de la MÊME façon. Sinon le bootstrap pose un
    jeton que le client ne trouve pas, ou que l'API ne reconnaît pas."""
    from app.auth import _env_slug_to_node_id

    for node_id in ("mon-portable", "claude.code.serveur", "a-b.c"):
        slug = api_token._slug(node_id)
        assert slug == slug.upper()
        assert "-" not in slug and "." not in slug
        # L'aller-retour rend le node_id d'origine, points devenus tirets près
        # (c'est la perte assumée et documentée de `_env_slug_to_node_id`).
        assert _env_slug_to_node_id(slug) == node_id.replace(".", "-")


# ---------------------------------------------------------------------------
# 2. La garde de forme : aucun appel nu vers l'API
# ---------------------------------------------------------------------------
#
# On regarde les fichiers qui appellent l'API de CE cerveau. Les appels vers
# des tiers (OpenAI, Telegram) portent leurs propres en-têtes et n'ont rien à
# voir ici : on ne retient donc que les appels dont l'URL est bâtie sur
# `_api_url()`, `API_URL`, `api_url` ou `base` — c'est-à-dire sur l'adresse de
# l'API ARAC.

# Deux façons LÉGITIMES de porter le jeton, et le contrôle doit connaître les
# deux — sinon il pousse à réécrire du code correct pour satisfaire un test.
#
#   · PAR APPEL   : `client.post(url, json=…, headers=entetes_api())`. C'est le
#     cas des fichiers qui ouvrent un client httpx court par requête.
#   · PAR CLIENT  : `httpx.Client(base_url=…, headers=entetes_api())`, puis des
#     appels relatifs. C'est le cas de `atoms_client.py`, dont TOUS les appels
#     passent par une seule fabrique `_client()`.
#
# Les deux tiennent. Ce qui ne tient pas, c'est un appel qui ne relève ni de
# l'une ni de l'autre.
_APPELANTS_PAR_APPEL = [
    "agents/lib/bus.py",
    "agents/lib/heartbeat.py",
    "agents/lib/llm_auditor.py",
    "agents/auditor/main.py",
    "agents/developer/main.py",
    "agents/orchestrator/main.py",
    "control_center/collectors/brain_api.py",
]

_APPELANTS_PAR_CLIENT = ["agents/cortex/atoms_client.py"]

_APPELANTS = _APPELANTS_PAR_APPEL + _APPELANTS_PAR_CLIENT

# `client.post(f"{_api_url()}/v1/…"` et toutes ses variantes, jusqu'à la
# parenthèse fermante de l'appel (les appels de ce dépôt tiennent en ≤ 6 lignes).
#
# LA LISTE DE FICHIERS N'ÉTAIT PAS LA SEULE ÉNUMÉRATION — mesuré le 9 août 2026.
# Le balayage de tout le dépôt a bien fermé le trou de la liste fermée : le même
# appel nu ajouté à `control_center/collectors/db_metrics.py`, qui n'est PAS
# listé, fait maintenant rougir (« 1 failed »). Mais le MOTIF, lui, énumérait
# encore la façon d'écrire l'URL — `{_api_url()}`, `{api_url}`, `{base}`,
# `base +`, `"/v1/`. Deux écritures ordinaires restaient invisibles, dans le
# fichier listé comme dans l'autre :
#
#   client.get(f"{BASE}/v1/atoms")            → 29 passed   (variable en capitales)
#   client.get(urljoin(BASE, "/v1/atoms"))    → 29 passed
#
# C'est la même faute de forme, d'un cran plus bas : on reconnaissait un STYLE
# d'écriture au lieu d'une CIBLE. Le motif ci-dessous ne demande plus comment la
# base est nommée — il demande si l'appel vise `/v1/` ou `/cc/` de CE cerveau.
# Mesuré après élargissement, sur tout le dépôt hors `tests/` : exactement les
# mêmes huit fichiers, exactement les mêmes appels, aucun reproche neuf.
#: LE MOTIF RECONNAISSAIT ENCORE UN STYLE — mesuré une manche plus tard.
#:
#: La rédaction précédente écrivait, à juste titre : « on reconnaissait un STYLE
#: d'écriture au lieu d'une CIBLE ». La phrase n'était pas encore vraie. Le
#: motif exigeait toujours que le littéral d'URL soit ÉCRIT AU POINT D'APPEL, et
#: que le verbe soit l'un des cinq nommés. Trois écritures parfaitement
#: ordinaires restaient invisibles, dans un fichier listé comme dans un autre —
#: reproduites dans `control_center/collectors/db_metrics.py`, garde muet :
#:
#:   client.request("GET", f"{BASE}/v1/atoms")   → le verbe normal de httpx
#:   url = f"{BASE}/v1/atoms" ; client.get(url)  → dès qu'il y a des paramètres
#:   client.get("%s/v1/atoms" % BASE)            → l'interpolation à l'ancienne
#:
#: Le prix n'est pas une fuite : c'est un appelant qui repart en 401 le jour où
#: quelqu'un écrit son appel autrement — c'est-à-dire le défaut d'origine, celui
#: des onze appelants nus.
#:
#: ON NE LIT PLUS L'APPEL AVEC UN SEUL MOTIF. On découpe l'appel (les
#: parenthèses se comptent, elles ne se devinent pas), puis on pose DEUX
#: questions à ce qu'il contient : y a-t-il un littéral qui vise `/v1/` ou
#: `/cc/` de ce cerveau, où qu'il soit dans les arguments ? sinon, le premier
#: argument est-il une variable à laquelle ce fichier a affecté une telle URL ?

#: Les verbes. `request`, `stream` et `send` manquaient — et `request` est la
#: forme NORMALE de `httpx` dès qu'on veut choisir la méthode.
_VERBES_HTTP = "get|post|patch|put|delete|request|stream|send"

_DEBUT_D_APPEL = re.compile(r"(?:await\s+)?[\w.]+\.(?:" + _VERBES_HTTP + r")\(")

#: Un littéral qui vise CE cerveau — quelle que soit la façon dont la base est
#: nommée, et quelle que soit sa place dans les arguments.
_CIBLE_DE_CE_CERVEAU = re.compile(r"[\"'][^\"'\n]*/(?:v1|cc)/")

#: `url = f"{BASE}/v1/atoms"` — la cible nommée une ligne plus haut. Sans cette
#: règle, il suffit d'une variable intermédiaire pour redevenir invisible.
_URL_COMPOSEE = re.compile(
    r"^[ \t]*(\w+)\s*(?::[^=\n]+)?=\s*[^\n]*[\"'][^\"'\n]*/(?:v1|cc)/",
    re.MULTILINE,
)


def _appels_http(texte: str):
    """(position, texte de l'appel) pour chaque appel HTTP, parenthèses comptées."""
    for debut in _DEBUT_D_APPEL.finditer(texte):
        i = texte.find("(", debut.end() - 1)
        if i < 0:  # pragma: no cover — impossible, le motif finit par `(`
            continue
        profondeur, j = 0, i
        while j < len(texte):
            if texte[j] == "(":
                profondeur += 1
            elif texte[j] == ")":
                profondeur -= 1
                if profondeur == 0:
                    break
            j += 1
        yield debut.start(), texte[debut.start():j + 1]


def _appels_nus_d_un_texte(texte: str) -> list[str]:
    """Les appels vers l'API de CE cerveau qui ne portent pas d'en-têtes."""
    portees = set(_URL_COMPOSEE.findall(texte))
    nus: list[str] = []
    for position, appel in _appels_http(texte):
        if "headers=" in appel:
            continue
        avant = texte[max(0, position - 40):position + len(appel)]
        if _DECLARATION_DE_ROUTE.search(avant):
            continue
        vise = bool(_CIBLE_DE_CE_CERVEAU.search(appel))
        if not vise and portees:
            premier = appel[appel.find("(") + 1:].lstrip()
            mot = re.match(r"[\w.]+", premier)
            vise = bool(mot and mot.group(0).split(".")[0] in portees)
        if vise:
            nus.append(appel)
    return nus


@pytest.mark.parametrize("relatif", _APPELANTS_PAR_APPEL)
def test_aucun_appel_a_l_api_ne_part_sans_entetes(relatif):
    """Chaque appel vers l'API de ce cerveau doit porter `headers=`.

    Garde de FORME, volontairement : le seul test de comportement qui
    attraperait ça exigerait d'exécuter le cycle, le cockpit et les quatre
    agents contre une vraie API — c'est-à-dire de n'attraper le défaut qu'en
    production, ce qui est précisément ce qui s'est passé.
    """
    chemin = RACINE / relatif
    nus = _appels_nus_d_un_texte(chemin.read_text(encoding="utf-8"))
    assert not nus, (
        f"{relatif} : {len(nus)} appel(s) à l'API sans en-têtes. "
        "L'API exige le jeton de TOUTE requête, boucle locale comprise. "
        "Le geste : `from app.api_token import entetes_api`, puis "
        "`headers=entetes_api()`.\n" + "\n---\n".join(nus)
    )


_FABRIQUE_NUE = re.compile(r"httpx\.(?:Async)?Client\((?![^)]*headers=)[^)]*\)")


@pytest.mark.parametrize("relatif", _APPELANTS_PAR_CLIENT)
def test_le_client_partage_porte_les_entetes(relatif):
    """Quand les en-têtes sont portés par le CLIENT, aucun client ne doit être
    bâti sans eux : il suffirait d'une seconde fabrique pour rouvrir la porte.

    On vérifie aussi que les en-têtes sont relus à chaque construction plutôt
    que figés à l'import — sinon une rotation de jeton laisserait un cycle de
    longue haleine parler avec un jeton révoqué.
    """
    texte = (RACINE / relatif).read_text(encoding="utf-8")
    nues = _FABRIQUE_NUE.findall(texte)
    assert not nues, (
        f"{relatif} : client httpx bâti sans en-têtes — {nues}. "
        "Tous les appels de ce fichier passent par la fabrique ; une fabrique "
        "nue rouvrirait la porte sans qu'aucun appel n'ait l'air fautif."
    )
    assert "headers=entetes_api()" in texte


@pytest.mark.parametrize("relatif", _APPELANTS)
def test_chaque_appelant_passe_par_le_module_partage(relatif):
    """Onze copies de « lire une variable, bâtir un en-tête », c'est onze
    occasions d'oublier — et onze endroits à retrouver le jour d'une rotation."""
    texte = (RACINE / relatif).read_text(encoding="utf-8")
    assert "from app.api_token import entetes_api" in texte, (
        f"{relatif} n'importe pas le module partagé. Ne recopiez pas la "
        "recherche du jeton : `app/api_token.py` la fait pour tout le monde."
    )


# ---------------------------------------------------------------------------
# 3. LA LISTE FERMÉE ÉTAIT LE TROU — mesuré, pas supposé
# ---------------------------------------------------------------------------
#
# `_APPELANTS` est une liste ÉCRITE : huit chemins. Le garde de forme ci-dessus
# ne regarde qu'eux. Éprouvé le 9 août 2026 en remettant le défaut aux deux
# endroits, avec le MÊME appel nu :
#
#   · ajouté à `agents/lib/bus.py` (listé)                     → 1 failed
#   · ajouté à `control_center/collectors/db_metrics.py` (non) → 27 passed
#
# Un appelant NEUF — et il y en a eu onze le jour où la porte s'est fermée —
# n'est vu par personne jusqu'à ce que quelqu'un pense à l'inscrire. C'est
# exactement la faiblesse que la liste devait corriger, déplacée d'un cran.
#
# Le balayage ci-dessous ne remplace pas la liste : la liste dit ce qu'on SAIT,
# et son test nomme le fichier fautif. Le balayage dit ce qu'on IGNORE.

#: Ce qui ressemble à un appel mais n'en est pas : la DÉCLARATION d'une route.
#: `app.get("/v1/constitution/hash")` dans `app/main.py` est le cas réel — le
#: motif d'appel le prend pour un `client.get`, et un balayage naïf accuserait
#: le serveur de s'appeler lui-même sans jeton.
_DECLARATION_DE_ROUTE = re.compile(
    r"(?:^|\n)\s*@?\s*(?:_?app|a|router|_router)\.(get|post|patch|put|delete)\("
)


def _appels_nus_du_depot() -> dict[str, list[str]]:
    """{fichier : appels à l'API de CE cerveau qui ne portent pas d'en-têtes}.

    Balaie tout le dépôt hors `tests/` — un test qui appelle l'API le fait
    contre un double, et la porte du sous-processus garde ce périmètre-là.
    """
    nus: dict[str, list[str]] = {}
    for chemin in sorted(RACINE.rglob("*.py")):
        rel = chemin.relative_to(RACINE).as_posix()
        if rel.startswith(("tests/", ".venv/")) or "/.venv/" in rel:
            continue
        if rel in _APPELANTS_PAR_CLIENT:
            continue  # en-têtes portés par la fabrique — test dédié ci-dessus
        try:
            texte = chemin.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        fautifs = _appels_nus_d_un_texte(texte)
        if fautifs:
            nus[rel] = fautifs
    return nus


def test_aucun_fichier_du_depot_n_appelle_l_api_sans_entetes() -> None:
    """LE BALAYAGE — il voit l'appelant que la liste ne connaît pas encore."""
    nus = _appels_nus_du_depot()
    assert not nus, (
        "des appels à l'API de ce cerveau partent sans en-têtes, hors des "
        "fichiers que la liste `_APPELANTS` surveille :\n"
        + "\n".join(f"  {f} — {len(v)} appel(s)\n    "
                    + "\n    ".join(x.replace("\n", " ")[:160] for x in v)
                    for f, v in nus.items())
        + "\n\nLe geste : `from app.api_token import entetes_api`, puis "
          "`headers=entetes_api()`. Et inscrivez le fichier dans "
          "`_APPELANTS_PAR_APPEL` pour que le reproche le nomme."
    )


def test_le_balayage_voit_bien_quelque_chose() -> None:
    """TÉMOIN. Un balayage qui ne trouverait AUCUN appel serait vert pour la
    pire des raisons : le motif ne reconnaît plus rien, et l'absence de
    reproche ne prouverait plus l'absence de faute."""
    vus = 0
    for relatif in _APPELANTS_PAR_APPEL:
        texte = (RACINE / relatif).read_text(encoding="utf-8")
        vus += sum(1 for _, appel in _appels_http(texte)
                   if _CIBLE_DE_CE_CERVEAU.search(appel))
    assert vus >= 10, (
        f"le motif d'appel ne reconnaît plus que {vus} appels dans les "
        f"{len(_APPELANTS_PAR_APPEL)} fichiers connus : il a cessé de voir, "
        f"et tous les tests de cette section sont devenus verts par vacuité.")


def test_le_pont_porte_deja_son_jeton():
    """`mac/arac-sync.py` sert le pont Mac ET le pont sans-Mac (même script).

    Il lisait déjà son jeton dans un fichier et posait l'en-tête : c'est la
    raison pour laquelle ce changement ne demande rien à l'utilisateur. On le
    vérifie ici pour que ça reste vrai.
    """
    texte = (RACINE / "mac" / "arac-sync.py").read_text(encoding="utf-8")
    assert '"Authorization": f"Bearer {jeton}"' in texte


# ---------------------------------------------------------------------------
# 4. CE QUE CE GARDE NE COUVRE PAS — un garde de forme qui ne le dit pas se
#    fait croire complet
# ---------------------------------------------------------------------------
#
# Quatre autres gardes de ce dépôt (G1, G3, G4, la porte du sous-processus)
# impriment leurs zones aveugles en fin de session. Celui-ci n'en déclarait
# aucune, et il en a : il lit du TEXTE, et le texte se contourne.
#
# UNE PROPOSITION A ÉTÉ ÉPROUVÉE PUIS ÉCARTÉE, et il faut dire pourquoi. Le
# constat précédent proposait « la règle qui ne se contourne pas » : interdire à
# tout module hors `tests/` de bâtir un client HTTP sans en-têtes, comme
# `agents/cortex/atoms_client.py` le fait déjà. Mesuré sur le dépôt : QUINZE
# clients `httpx` sont bâtis sans en-têtes hors de `tests/`, et ils ont raison
# de l'être — `agents/telegram_bridge` parle à Telegram, `agents/lib/
# llm_auditor` à un fournisseur de modèle, `agents/lib/heartbeat` à une sonde.
# Leur imposer le jeton de CE cerveau serait l'envoyer à des tiers. La règle
# aurait donc dû énumérer les clients dispensés — c'est-à-dire redevenir une
# liste, un cran plus bas. On garde le garde de forme, et on déclare ses trous.


class ZoneAveugleDuJeton(NamedTuple):
    zone: str
    mecanique: str


ZONES_NON_COUVERTES_DU_JETON: tuple[ZoneAveugleDuJeton, ...] = (
    ZoneAveugleDuJeton(
        "une URL composée dans un AUTRE fichier",
        "La règle de la variable (`url = f\"{BASE}/v1/atoms\"` puis "
        "`client.get(url)`) ne regarde que le fichier où l'appel est écrit. Une "
        "constante importée d'un module voisin — `from app.routes import "
        "URL_ATOMS` — ne porte aucun littéral ici, et l'appel redevient "
        "invisible. Suivre les imports demanderait de résoudre les noms, "
        "c'est-à-dire d'écrire un interpréteur.",
    ),
    ZoneAveugleDuJeton(
        "un transport qui n'est pas un appel `<objet>.<verbe>(`",
        "`urllib.request.urlopen(requete)`, une socket écrite à la main, un "
        "`curl` lancé en sous-processus : aucun n'a la forme que ce garde "
        "cherche. Les deux premiers ne sont employés nulle part dans ce dépôt "
        "aujourd'hui — c'est une mesure, pas un espoir — et le troisième "
        "appartient à G4, qui vérifie que tout geste imprimé tombe sur une "
        "route réelle.",
    ),
    ZoneAveugleDuJeton(
        "des en-têtes portés autrement que par `headers=`",
        "Un client bâti avec ses en-têtes rend l'appel indifférent à sa forme, "
        "et c'est le bon geste — mais ce garde ne sait le reconnaître que "
        "fichier par fichier (`_APPELANTS_PAR_CLIENT`). Un appelant qui "
        "porterait ses en-têtes par un `httpx.Request` construit ailleurs "
        "serait accusé à tort, et le premier faux positif est ce qui fait "
        "désactiver un garde. La contrepartie est assumée : on préfère "
        "l'énumération COURTE et relue des porteurs par client à une règle qui "
        "enverrait le jeton de ce cerveau chez Telegram.",
    ),
)


def test_les_zones_du_jeton_sont_declarees_et_motivees():
    """Un aveu sans mécanique est une excuse ; on exige la mécanique."""
    assert ZONES_NON_COUVERTES_DU_JETON
    for z in ZONES_NON_COUVERTES_DU_JETON:
        assert len(z.zone) > 15, f"zone trop vague : {z.zone!r}"
        assert len(z.mecanique) > 120, (
            f"« {z.zone} » : dites POURQUOI c'est ouvert, pas seulement que ça "
            "l'est."
        )


def test_les_trois_formes_qui_manquaient_sont_vues():
    """Les trois écritures mesurées invisibles, éprouvées sur du texte.

    Ce sont des SONDES, pas des appels : rien ici ne part sur le réseau. Le
    garde qui les manquait rendait « 29 passed » sur les trois.
    """
    sondes = [
        'def s(client, BASE):\n    return client.request("GET", f"{BASE}/v1/atoms")\n',
        'def s(client, BASE):\n    url = f"{BASE}/v1/atoms"\n    return client.get(url)\n',
        'def s(client, BASE):\n    return client.get("%s/v1/atoms" % BASE)\n',
        'def s(client, BASE):\n    return client.stream("GET", urljoin(BASE, "/cc/x"))\n',
    ]
    for texte in sondes:
        assert _appels_nus_d_un_texte(texte), (
            f"forme non vue par le garde :\n{texte}"
        )


def test_le_garde_du_jeton_ne_crie_pas_au_loup():
    """La contre-épreuve : ce qui n'est pas un appel à CE cerveau doit passer."""
    innocents = [
        'x = {"a": 1}\nv = x.get("a")\n',                     # un dictionnaire
        'r = client.get(f"{BASE}/v1/atoms", headers=entetes_api())\n',
        'r = await client.post("https://api.telegram.org/botX/sendMessage")\n',
        'chemin = "/v1/atoms"\n',                             # pas un appel
    ]
    for texte in innocents:
        assert not _appels_nus_d_un_texte(texte), (
            f"faux positif du garde du jeton :\n{texte}"
        )
