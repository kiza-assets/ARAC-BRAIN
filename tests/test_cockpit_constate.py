"""Le cockpit CONSTATE. Il ne postule pas, il ne se souvient pas d'ailleurs.

Trois promesses que le cockpit avait rompues en silence, toutes de même
famille : **un texte servi ne doit affirmer que ce qui vient d'être regardé.**

1. AUCUN COMPTE RELEVÉ AILLEURS DANS UNE RAISON
   --------------------------------------------
   ``unavailable_reason`` est du TEXTE SERVI. Un chiffre écrit là est le compte
   de la base sur laquelle il a été relevé : chez tout autre lecteur, le cockpit
   lui annonce le corpus de quelqu'un d'autre. La raison énonce le MÉCANISME
   absent ; le compte, lui, est produit par le SQL de la métrique — c'est-à-dire
   mesuré sur la base qu'on interroge.

2. AUCUNE AFFIRMATION INCONDITIONNELLE SUR L'ÉTAT D'UNE BASE
   ----------------------------------------------------------
   Une trentaine de textes servis affirmaient « la migration 0033_atom_links
   n'est pas appliquée ». C'était vrai d'UNE base. Or ce dépôt LIVRE cette
   couche : la migration qui crée ``arac.atom_links`` FAIT PARTIE de la chaîne
   qu'``alembic upgrade head`` applique — ``app/services/atom_links.py``
   calcule les arêtes et le cycle cortex appelle leur recalcul. Chez qui a suivi
   l'installation, la table EST là, et le cockpit lui affirmait le contraire à
   chaque écran, en l'envoyant relancer une migration déjà passée.

3. UNE PAGE DÉFINITIVEMENT VIDE DIT POURQUOI
   ------------------------------------------
   Deux pages lisent des sources qu'aucun code de ce dépôt n'écrit. Elles
   rendaient un tableau vide, sans un mot : indistinguable d'une panne.

CE QUI A QUITTÉ CE FICHIER — et pourquoi son nom a changé
=========================================================
Il s'appelait ``test_cockpit_sans_auteur.py`` et portait une section « aucune
trace de l'auteur » **bornée à ``control_center/``**. Elle était verte pendant
que ``requirements.txt``, ``agents/`` et ``tests/`` étaient sales : la
réparation avait eu exactement la taille du garde-fou. Cette section vit
désormais dans ``tests/test_f1_aucune_trace_de_l_auteur.py``, qui balaie le
dépôt ENTIER plus les fichiers que l'installation engendre. Ce fichier-ci garde
ce qu'il a toujours vraiment prouvé — que le cockpit constate — et son nom le
dit maintenant.

Hors-ligne : aucun de ces tests n'ouvre de connexion. Ils lisent le code déclaré
et le HTML rendu.
"""

from __future__ import annotations

import pathlib
import re

import pytest

RACINE = pathlib.Path(__file__).resolve().parents[1]
COCKPIT = RACINE / "control_center"

# ============================================================================
# 2 & 3. Ce qu'une raison d'indisponibilité n'a pas le droit de dire
# ============================================================================


def _registre():
    from control_center.cc_v1 import registry

    return registry.REGISTRY


def test_aucune_raison_d_indisponibilite_ne_porte_un_compte_releve_ailleurs():
    """Une raison énonce un MÉCANISME. Un compte, elle le fait mesurer.

    « last_verified_at est NULL sur les 1875 atomes » était servi à l'écran :
    le cockpit d'un inconnu lui annonçait le corpus d'un autre. Le nombre est
    interdit dans la raison — pas dans le SQL, qui le mesure sur la base qu'on
    interroge.

    Les nombres d'un ou deux chiffres restent tolérés : ils désignent des
    versions et des seuils (« v2 », « 30 jours »), pas des corpus.
    """
    compte = re.compile(r"\b\d{3,}\b")
    fautives = [
        f"{m.key}: {m.unavailable_reason}"
        for m in _registre()
        if m.unavailable_reason and compte.search(m.unavailable_reason)
    ]
    assert not fautives, (
        "Une raison d'indisponibilité ne cite pas un compte : il vient d'une "
        "autre base que celle du lecteur.\n  " + "\n  ".join(fautives)
    )


def test_aucun_texte_servi_n_affirme_l_etat_d_une_migration():
    """Affirmer « migration non appliquée » sans regarder est un mensonge en attente.

    Ce dépôt livre la couche de liens : sa migration FAIT PARTIE de la chaîne
    qu'``alembic upgrade head`` applique. Un utilisateur qui suit
    l'installation l'applique donc, et le cockpit continuait de lui dire
    qu'elle manquait — en l'envoyant la relancer.

    Le seul texte autorisé à parler d'une migration est celui d'un ``CASE``
    branché sur ``to_regclass`` : il CONSTATE. On l'accepte donc quand la ligne,
    ou celles qui l'entourent, portent la sonde.
    """
    from control_center.cc_v1 import registry

    interdit = re.compile(r"migration[^.\n]{0,40}(non appliqu|pas appliqu)", re.IGNORECASE)
    fautifs: list[str] = []
    for m in registry.REGISTRY:
        for champ in ("unavailable_reason", "unavailable_gesture", "definition",
                      "formula", "evidence_label"):
            valeur = getattr(m, champ, None)
            if valeur and interdit.search(str(valeur)):
                fautifs.append(f"{m.key}.{champ}: {valeur}")
        # Dans le SQL, l'affirmation n'est licite que si la requête la CONSTATE.
        for champ in ("sql", "evidence_sql"):
            valeur = str(getattr(m, champ, "") or "")
            if interdit.search(valeur) and "to_regclass" not in valeur:
                fautifs.append(f"{m.key}.{champ} affirme sans to_regclass")
    assert not fautifs, (
        "Une affirmation sur l'état d'une base doit descendre d'un to_regclass.\n  "
        + "\n  ".join(fautifs)
    )


def test_la_metrique_de_connectivite_constate_au_lieu_de_postuler():
    """V5 — Connectivité rendait NULL dans les DEUX branches de son CASE.

    Elle affirmait, sans condition, que la migration des liens n'était pas
    appliquée. La valeur reste NULL — la mesure de densité demande une requête
    montée quand la table existe, pas un ``CASE`` : PostgreSQL analyse la requête
    entière avant de l'exécuter, donc un ``FROM arac.atom_links`` la ferait
    échouer quand la table manque, y compris dans la branche qui ne l'atteint
    jamais. Mais la RAISON, elle, est désormais projetée par la requête et
    distingue les deux absences.
    """
    from control_center.cc_v1 import registry

    m = registry.by_key("vital_connectivity")
    sql = m.sql.lower()
    assert "to_regclass" in sql
    assert " as reason" in sql, "la requête doit projeter sa propre raison"
    assert " as gesture" in sql, "la requête doit projeter son propre geste"
    # Les deux branches disent des choses DIFFÉRENTES — sans quoi le CASE est
    # décoratif, ce qu'il était : ses deux branches rendaient NULL toutes les
    # deux, et le texte servi ne dépendait donc d'aucun constat.
    branches = re.findall(r"then(.*?)else(.*?)end", m.sql, re.IGNORECASE | re.DOTALL)
    assert branches, "la requête doit porter au moins un CASE ... THEN ... ELSE"
    for alors, sinon in branches:
        assert alors.strip() != sinon.strip(), (
            "les deux branches du CASE sont identiques : le constat ne sert à rien"
        )


def test_le_service_sert_la_raison_de_la_requete_avant_celle_du_code():
    """Quand la requête a constaté, c'est elle qui parle.

    C'est le mécanisme qui rend le point précédent effectif : sans lui, la
    colonne ``reason`` du SQL serait ignorée et le texte gravé resservi.
    """
    from control_center.cc_v1 import registry, service

    m = registry.by_key("vital_connectivity")

    class _Cur:
        description = [type("d", (), {"name": n})
                       for n in ("value", "reason", "gesture")]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql):
            self.sql = sql

        def fetchone(self):
            return (None, "constaté par la requête", "le geste constaté")

    class _Conn:
        def cursor(self):
            return _Cur()

    out = service.metric_value(m.key, conn=_Conn())
    assert out["state"] == "unavailable"
    assert out["reason"] == "constaté par la requête"
    assert out["gesture"] == "le geste constaté"


def test_le_repli_de_la_couche_de_liens_n_affirme_rien():
    """Quand le cockpit n'a pas pu regarder, il dit qu'il n'a pas pu regarder.

    ``LINKS_UNAVAILABLE`` était servi tel quel sur une dizaine de panneaux et
    affirmait l'absence d'une table. C'est maintenant le texte du cas « je ne
    sais pas » — le seul des quatre qui n'affirme rien.
    """
    from control_center.cc_v1 import entities

    assert "atom_links" not in entities.LINKS_UNAVAILABLE["reason"]
    assert "migration" not in entities.LINKS_UNAVAILABLE["reason"].lower()
    # Les textes CONSTATÉS, eux, ont le droit de nommer la table : ils ne sont
    # produits qu'après l'avoir regardée — et ils ne disent pas la même chose,
    # sans quoi le constat ne servirait à rien.
    constates = [b["reason"] for b in entities.TEXTES_CONSTATES]
    assert len(set(constates)) == len(constates) == 3
    assert "absente" in entities.LINKS_ABSENT["reason"]
    assert "aucune " in entities.LINKS_EMPTY["reason"]
    assert "porte des arêtes" in entities.LINKS_NOT_READ["reason"]


@pytest.mark.parametrize(
    "reponses, attendu",
    [
        # La table manque : une seule requête, et on ne lit pas ce qui n'existe pas.
        ([(False,)], "LINKS_ABSENT"),
        # La table est là mais vide : il manque un passage du cycle, pas une migration.
        ([(True,), (False,)], "LINKS_EMPTY"),
        # La table est là et peuplée : il manque une LECTURE, rien d'autre.
        ([(True,), (True,)], "LINKS_NOT_READ"),
    ],
)
def test_links_dependency_rend_ce_qu_elle_a_constate(monkeypatch, reponses, attendu):
    """La sonde tranche entre les trois états qu'elle peut voir.

    Distinguer « vide » de « peuplée » n'est pas un raffinement : c'est ce qui
    empêche le cockpit d'envoyer chercher un producteur qui tourne déjà. Le
    dépôt en livre un — ``app/services/atom_links.py``, appelé par le cycle du
    cortex à chaque tour — et le cockpit disait le contraire.
    """
    from control_center.cc_v1 import entities

    class _Cur:
        def __init__(self):
            self.restant = list(reponses)
            self.vues: list[str] = []

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql):
            self.vues.append(sql)

        def fetchone(self):
            return self.restant.pop(0)

    class _Conn:
        def __init__(self):
            self.cur = _Cur()

        def cursor(self):
            return self.cur

    conn = _Conn()
    assert entities.links_dependency(conn) == dict(getattr(entities, attendu))
    assert "to_regclass" in conn.cur.vues[0], "la première sonde ne regarde pas le catalogue"
    # La lecture du contenu ne part JAMAIS quand la table est absente : la
    # requête entière échouerait à l'analyse.
    assert len(conn.cur.vues) == len(reponses)


def test_links_dependency_ne_leve_jamais(monkeypatch):
    """Une base injoignable ne doit pas faire tomber la page qui la décrit."""
    from control_center.cc_v1 import entities, service

    def _boom():
        raise RuntimeError("base injoignable")

    monkeypatch.setattr(service, "_connect_readonly", _boom)
    assert entities.links_dependency() == dict(entities.LINKS_UNAVAILABLE)


# ============================================================================
# 4. Une page vide nomme ce qui la remplirait
# ============================================================================


def test_render_absence_rend_la_raison_et_le_geste_echappes():
    """Le rendu ne fabrique aucun texte : il n'affiche que ce qui est déclaré."""
    from control_center.templates import render_absence

    html = render_absence("il manque <X>", "écrivez & posez-le")
    assert "il manque &lt;X&gt;" in html
    assert "&amp;" in html
    assert "<X>" not in html
    # Sans raison déclarée, aucun message générique n'est inventé.
    assert render_absence(None) == ""
    assert render_absence("   ") == ""
    # Une raison sans geste reste affichable.
    assert "absence-gesture" not in render_absence("il manque X")


_TEST_SECRET = "test_secret_cockpit_sans_auteur_not_for_production"


@pytest.fixture()
def cockpit(monkeypatch):
    """Un cockpit authentifié, dont les deux sources absentes le sont VRAIMENT.

    Les collecteurs pointent sur des chemins inexistants : c'est exactement
    l'état d'un cerveau neuf, celui de l'inconnu qui vient de cloner le dépôt.
    """
    from fastapi.testclient import TestClient

    from control_center.app import create_app
    from control_center.collectors import reports_council
    from control_center.config import CC_SESSION_SECRET_ENV, SESSION_COOKIE_NAME
    from control_center.security import sign_session

    monkeypatch.setenv(CC_SESSION_SECRET_ENV, _TEST_SECRET)
    monkeypatch.setattr(reports_council, "_docs_dir",
                        lambda: RACINE / "_repertoire_absent_docs_")
    monkeypatch.setattr(reports_council, "_council_sessions_dir",
                        lambda: RACINE / "_repertoire_absent_council_")

    client = TestClient(create_app(), raise_server_exceptions=True)
    client.cookies.set(
        SESSION_COOKIE_NAME,
        sign_session({"sub": "test_sans_auteur"}, secret=_TEST_SECRET),
    )
    return client


@pytest.mark.parametrize(
    "chemin, attendu",
    [
        ("/cc/decisions", "DECISIONS.md"),
        ("/cc/council", "session_"),
    ],
)
def test_les_pages_qui_ne_peuvent_rien_afficher_disent_pourquoi(cockpit, chemin, attendu):
    """/cc/decisions et /cc/council lisent des sources qu'aucun code d'ici n'écrit.

    Elles rendaient un tableau vide, muet. Chez un inconnu, cela se lit comme une
    panne du cockpit — ou pire, comme un cerveau qui n'a rien à raconter. Chaque
    page nomme donc, DANS SON HTML, le fichier ou le répertoire attendu et le
    geste qui le crée.
    """
    r = cockpit.get(chemin, follow_redirects=False)
    assert r.status_code == 200, r.status_code
    page = r.text
    assert 'class="absence"' in page, "la page ne déclare pas son absence"
    assert "Ce qui la remplirait" in page, "la page ne dit pas ce qui la remplirait"
    assert attendu in page, f"la page ne nomme pas la source attendue ({attendu})"


def test_la_timeline_sans_convention_declaree_dit_pourquoi_elle_est_vide(cockpit, monkeypatch):
    """Aucune convention de branches déclarée : le panneau le dit, il ne se tait pas.

    Il affichait « Branches chore/closeout-* » — la convention d'un dépôt
    particulier — et restait vide chez tout le monde d'autre, sans un mot.
    """
    from control_center.collectors import reports_council

    monkeypatch.delenv(reports_council.RELEASE_BRANCH_GLOB_ENV, raising=False)
    r = cockpit.get("/cc/timeline", follow_redirects=False)
    assert r.status_code == 200
    assert 'class="absence"' in r.text
    assert reports_council.RELEASE_BRANCH_GLOB_ENV in r.text
    assert "closeout" not in r.text


def test_le_tableau_de_bord_lit_la_cle_que_le_collecteur_produit():
    """Une tuile branchée sur une clé morte affiche 0 en permanence.

    Le collecteur ne suppose plus aucune convention de nommage de branches et
    publie ``release_branches`` ; le tableau de bord lisait encore
    ``closeout_branches`` — la convention d'un dépôt particulier — et affichait
    donc zéro même chez qui avait déclaré la sienne. Un zéro faux est pire
    qu'une absence : il se mesure.
    """
    source = (COCKPIT / "app.py").read_text(encoding="utf-8")
    # On vise les LECTURES de la clé, pas les commentaires qui racontent la
    # correction : un commentaire qui nomme l'ancienne clé est ce qui empêche
    # de la réintroduire par distraction.
    lectures = re.findall(r"""\.get\(\s*["'](\w*branches)["']""", source)
    assert lectures, "le tableau de bord doit lire une clé de branches"
    assert set(lectures) == {"release_branches"}, lectures
