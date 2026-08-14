"""Le garde de lecture seule ne refuse pas la requête du produit lui-même.

CE QUE CE FICHIER GARDE, ET POURQUOI IL EXISTE
==============================================

`GET /cc/v1/conversations` et `GET /cc/v1/conversations/{uid}` — la liste des
conversations et la fiche d'une conversation — étaient MORTES sur 100 % des
installations, avec ou sans configuration, sur un cerveau neuf et sain. Elles
rendaient **HTTP 200**, corps `state: "unavailable"`, empreinte
`ValueError sha8:07238b97/82`.

LA CAUSE, ET ELLE TIENT EN UNE PHRASE FRANÇAISE.
`entities._assert_read_only` retirait les littéraux entre apostrophes, puis
interdisait `--` dans ce qui restait. Il ne retirait **pas** les commentaires
en bloc `/* … */`. Or la requête des conversations en porte un, et ce
commentaire est de la PROSE :

    /* … `to_regclass` regarde le catalogue -- c'est la seule facon de le
       dire sans le supposer. */

Le garde y a vu un commentaire SQL et a refusé d'exécuter. Il avait RAISON sur
le principe — les requêtes du cockpit sont publiées comme preuve, APLATIES sur
une ligne, et un vrai `--` y avalerait tout ce qui suit, rendant la preuve
injouable donc mensongère. Il avait TORT sur la méthode : il jugeait un
CARACTÈRE là où SQL a une GRAMMAIRE. Un `--` à l'intérieur d'un `/* … */` ne
commente rien ; c'est `*/` qui referme le bloc, et l'aplatissement n'y change
rien.

CE QUE CE TEST FAIT, ET CE QU'IL NE FAIT PAS
============================================

Il n'énumère pas les requêtes interdites — il prend TOUT le SQL que le cockpit
construit sans avoir besoin d'une base, et exige que le garde le laisse passer.
La liste vient donc du produit, pas d'ici : une requête écrite demain y entre
toute seule, et la phrase française qui la condamnerait rougit le jour où elle
est écrite, pas six manches plus tard sur un cerveau réel.

Il vérifie AUSSI que le garde continue de mordre — un test qui ne prouve que la
permission finit par autoriser tout. Trois refus sont exigés : un vrai
commentaire de ligne, un bloc jamais refermé, une instruction mutante.

Ni base, ni réseau : c'est du texte.
"""

from __future__ import annotations

import importlib
import re

import pytest

# Les modules du BFF qui construisent du SQL. `families` est inclus : ses
# métriques passent par le garde de `metric`, qui partage la même grammaire.
MODULES = (
    "control_center.cc_v1.entities",
    "control_center.cc_v1.scopes",
    "control_center.cc_v1.lifestory",
    "control_center.cc_v1.cascade",
    "control_center.cc_v1.today",
    "control_center.cc_v1.stream",
    "control_center.cc_v1.replay",
    "control_center.cc_v1.listener",
    "control_center.cc_v1.registry",
)

#: Ce qui fait d'une chaîne du SQL plutôt que de la prose : un verbe de lecture
#: en tête de mot. On ne cherche pas à être exhaustif — on cherche à ne pas
#: rater ce que le produit envoie réellement au moteur.
_EST_DU_SQL = re.compile(r"\b(select|with)\b", re.IGNORECASE)


def _garde():
    from control_center.cc_v1 import entities

    return entities._assert_read_only


def _sql_des_modules() -> list[tuple[str, str]]:
    """Tout le SQL de niveau module, `(origine, requête)`."""
    trouve: list[tuple[str, str]] = []
    for nom in MODULES:
        try:
            mod = importlib.import_module(nom)
        except Exception as exc:  # noqa: BLE001 — un module absent se DIT
            pytest.fail(f"{nom} ne se charge pas : {type(exc).__name__}: {exc}")
        for attr in dir(mod):
            # Les attributs spéciaux (`__doc__` en tête) sont de la PROSE : elle
            # n'est jamais envoyée au moteur, et un tiret double y est un tiret
            # double. Les juger reviendrait à refaire, dans le test, l'erreur
            # exacte que le test existe pour fermer.
            if attr.startswith("__"):
                continue
            valeur = getattr(mod, attr, None)
            if isinstance(valeur, str) and len(valeur) > 40 and _EST_DU_SQL.search(valeur):
                trouve.append((f"{nom}.{attr}", valeur))
            elif isinstance(valeur, dict):
                for cle, v in valeur.items():
                    if isinstance(v, str) and len(v) > 40 and _EST_DU_SQL.search(v):
                        trouve.append((f"{nom}.{attr}[{cle!r}]", v))
            elif isinstance(valeur, (tuple, list)):
                for i, v in enumerate(valeur):
                    if isinstance(v, str) and len(v) > 40 and _EST_DU_SQL.search(v):
                        trouve.append((f"{nom}.{attr}[{i}]", v))
    return trouve


#: Les fabriques de SQL qui n'ont besoin d'AUCUNE base : elles n'assemblent que
#: du texte et des marqueurs `%(nom)s`. Ce sont exactement celles qui ont produit
#: les deux défauts de cette manche — la prose interdite et la relation vide.
FABRIQUES = (
    ("control_center.cc_v1.entities", "_project_stats_sql"),
    ("control_center.cc_v1.scopes", "_projects_for_scope_sql"),
    ("control_center.cc_v1.scopes", "_projects_per_scope_fragment"),
    ("control_center.cc_v1.lifestory", "_projects_sql"),
    ("control_center.cc_v1.cascade", "_projects_sql"),
)


def test_tout_le_sql_du_cockpit_passe_son_propre_garde():
    """Aucune requête du produit n'est refusée par le garde du produit."""
    garde = _garde()
    refusees: list[str] = []
    for origine, sql in _sql_des_modules():
        try:
            garde(sql, origine)
        except ValueError as exc:
            refusees.append(f"{origine} → {exc}")
    assert not refusees, (
        "\n\nLE GARDE REFUSE LE SQL DU PRODUIT LUI-MÊME.\n\n"
        "  Une requête que le cockpit construit et envoie au moteur est rejetée\n"
        "  AVANT d'être exécutée. La route qui la porte rendra HTTP 200 avec\n"
        "  `state: unavailable` — un vert qui ne montre rien.\n\n"
        "  LES REQUÊTES REFUSÉES\n    " + "\n    ".join(refusees)
    )


def test_les_fabriques_de_sql_passent_le_garde_sans_projet_declare():
    """Sans `config/projects.toml`, chaque fabrique rend du SQL acceptable.

    C'est l'état de TOUTE installation issue du chemin documenté : ni le
    bootstrap ni l'entretien n'écrivent ce fichier.
    """
    garde = _garde()
    for nom_module, nom in FABRIQUES:
        mod = importlib.import_module(nom_module)
        rendu = getattr(mod, nom)()
        sql = rendu[0] if isinstance(rendu, tuple) else rendu
        assert sql.strip(), (
            f"{nom_module}.{nom}() rend une chaîne VIDE. Elle sera insérée dans un "
            "gabarit qui l'attend entre parenthèses, et PostgreSQL rendra 42601. "
            "Zéro ligne se dit `WHERE false`, jamais par le silence."
        )
        garde(sql, f"{nom_module}.{nom}")


def test_zero_projet_produit_une_relation_vide_bien_formee():
    """`union_ou_vide([])` rend une relation, pas rien."""
    from control_center.cc_v1.projects import union_ou_vide

    sql = union_ou_vide([], (("id", "text"), ("atom_id", "uuid")))
    assert sql.strip(), "une chaîne vide entre parenthèses est une erreur de syntaxe"
    bas = sql.lower()
    assert "where false" in bas, "zéro ligne se dit `WHERE false`"
    assert "null::text as id" in bas and "null::uuid as atom_id" in bas, (
        "la relation de repli doit porter les colonnes que le gabarit d'accueil "
        "nomme, et leurs types : sinon l'absence de projet ferait échouer la "
        "requête pour une AUTRE raison"
    )
    _garde()(f"SELECT * FROM (\n{sql}\n) t", "repli")


def test_une_prose_avec_un_tiret_double_dans_un_bloc_ne_condamne_pas():
    """LE DÉFAUT LUI-MÊME, rejoué à l'identique."""
    garde = _garde()
    sql = (
        "SELECT c.uid\n"
        "  FROM arac.conversations c,\n"
        "       /* `to_regclass` regarde le catalogue -- c'est la seule facon\n"
        "          de le dire sans le supposer. */\n"
        "       (SELECT 1) x"
    )
    garde(sql, "la requête des conversations")


def test_un_mot_interdit_ecrit_en_prose_dans_un_bloc_ne_condamne_pas():
    """Le faux positif symétrique, fermé par le même geste."""
    _garde()("SELECT 1 /* on ne fait jamais d'UPDATE ici */", "prose")


@pytest.mark.parametrize(
    ("sql", "attendu"),
    [
        ("SELECT 1 -- et tout le reste disparaît\n  , 2", "commentaire SQL"),
        ("SELECT 1 /* jamais refermé", "jamais refermé"),
        ("UPDATE arac.memory_atoms SET status = 'dead'", "instruction mutante"),
    ],
)
def test_le_garde_mord_toujours(sql: str, attendu: str):
    """Un test qui ne prouve que la permission finit par tout autoriser."""
    with pytest.raises(ValueError) as capture:
        _garde()(sql, "essai")
    assert attendu in str(capture.value)
