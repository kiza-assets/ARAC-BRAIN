"""LA PREUVE VERTE PAR CONSTRUCTION — le garde qui ferme la classe.

CE QU'IL REFUSE, EN UNE PHRASE
==============================
Une assertion qui ne peut pas échouer. Pas « une assertion fausse » : une
assertion dont AUCUN état atteignable du code ne ferait rougir. Elle est verte
le jour où on l'écrit, verte le jour où le défaut revient, et elle occupe la
place de celle qui aurait mordu.

LE DÉFAUT QU'IL EXISTE POUR EMPÊCHER — il a coûté sept manches
==============================================================
`tests/test_cockpit_dit_vrai.py` portait ceci, avec une docstring qui concluait
« un atome naît avec sa confiance et meurt avec elle » :

    assert "confidence" not in AtomUpdate.model_fields

Le champ servi s'appelle **`confidence_score`**. La clé cherchée n'a jamais
appartenu au vocabulaire de cette collection : l'assertion était vraie de toute
éternité. Et comme elle passait, elle a CERTIFIÉ la phrase que l'installateur
imprimait à la fin de chaque installation — « la confiance d'un atome est
IMMUABLE … ne cherchez pas le réglage qui le ferait monter ».

Le réglage existe. Mesuré sur un cerveau réel, le 9 août 2026, par l'API et
non par relecture : `PATCH /v1/atoms/<id>` avec `{"confidence_score": 95}` sur
un atome à 40 rend **200**, et la base porte 95. Le CHANGELOG l'avait même
diagnostiqué — « une preuve qui interroge le mauvais nom rend “absent” avec le
même aplomb qu'une preuve juste » — et la ligne était restée telle quelle.

POURQUOI UN GARDE ET PAS UNE CORRECTION
=======================================
Corriger la ligne aurait guéri UN cas. La forme, elle, se reproduit : le même
balayage a trouvé la même faute dans `tests/test_cortex_contract.py`, où deux
des quatre champs interdits n'étaient jamais posés dans l'atome dont on
vérifiait qu'ils en étaient absents — on pouvait retirer `confidence` et
`audit_source` de `FORBIDDEN_ATOM_FIELDS` sans faire rougir personne.

LES TROIS RÈGLES, ET POURQUOI CHACUNE
=====================================
Le garde ne juge que ce qu'il peut RÉSOUDRE : une assertion
`assert "<nom>" not in <collection>` dont la collection est un nom pointé sans
appel ni indice (`AtomUpdate.model_fields`, `contract.FORBIDDEN_ATOM_FIELDS`,
une constante littérale du fichier de test). Sur celles-là, il exige :

  RÈGLE 1 — LE NOM FANTÔME. Le nom cherché doit exister quelque part dans le
      dépôt. Chercher l'absence d'un mot que le produit n'a jamais connu, c'est
      se donner raison sur rien.

  RÈGLE 2 — LE QUASI-MANQUÉ, et c'est celle qui mord ici. Si le nom cherché est
      absent de la collection mais qu'un MEMBRE de cette collection le contient
      comme sous-nom — `confidence` cherché, `confidence_score` servi — alors
      l'assertion interroge presque sûrement le mauvais nom. C'est le mécanisme
      exact par lequel une preuve vide se fabrique : on écrit le nom qu'on a en
      tête, pas celui que le code sert, et personne ne le voit puisque c'est
      vert.

  RÈGLE 3 — LE TÉMOIN. Toute assertion d'absence doit être accompagnée, dans la
      MÊME fonction de test, d'une assertion de PRÉSENCE sur la MÊME collection.
      Sans elle, on ne sait pas si l'instrument voit quoi que ce soit : une
      collection vide, un import cassé, un renommage global passeraient tous
      pour une preuve. Le témoin est le seul moyen mécanique de distinguer
      « ce nom n'y est pas » de « je ne regarde rien ».

CE QUE CE GARDE NE COUVRE PAS — écrit, pas découvert
=====================================================
Voir `ZONES_NON_COUVERTES`. Un garde qui ment sur sa portée est pire qu'un
garde absent. En particulier : il ne résout pas les collections calculées
(retour d'appel, indexation, compréhension), il ne dit rien des assertions
POSITIVES qui ne peuvent pas échouer, et il ne juge pas si un test PROUVE ce
que sa docstring annonce — cette question-là n'a pas de forme mécanique.

Hors-ligne comme toute la suite : il lit des fichiers et importe `app.*`.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
DOSSIER_TESTS = RACINE / "tests"

#: Les modules dont le garde accepte d'importer un symbole pour résoudre une
#: collection. Volontairement court : importer n'importe quoi à la collecte,
#: c'est exécuter n'importe quoi.
PAQUETS_RESOLVABLES = ("app", "agents", "control_center")

#: Un « nom » au sens de ce garde : ce qui ressemble à un identifiant de champ,
#: de clé, de route, d'unité ou de fichier. On ne juge pas les phrases.
_NOM = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-/]{2,}$")

ZONES_NON_COUVERTES: tuple[tuple[str, str], ...] = (
    ("les collections CALCULÉES",
     "`assert x not in resultat_de(...)`, `... not in d['clé']`, `... not in "
     "[f(a) for a in b]` : le garde ne les résout pas et ne les juge pas. Il "
     "les COMPTE, et le décompte est imprimé en fin de session."),
    ("les assertions POSITIVES vides",
     "`assert 'x' in collection` où la collection contient tout : la forme "
     "symétrique existe, elle est plus rare et moins toxique (elle rougit dès "
     "que la collection se vide). Non couverte."),
    ("l'écart entre la docstring et l'assertion",
     "Un test peut prouver quelque chose de VRAI qui n'est pas ce que sa "
     "docstring annonce. C'est ce qui s'est produit ici pendant sept manches. "
     "Aucune forme mécanique ne l'attrape ; seule la lecture le voit."),
    ("les collections d'un AUTRE processus",
     "Ce que sert l'API en marche, ce que contient une base réelle : cela se "
     "mesure sur un cerveau, pas dans `make test`. C'est `make acceptance`."),
    ("un nom fantôme employé comme ENTRÉE",
     "`_atom(champ_inconnu='x')` fabrique délibérément un nom que le dépôt ne "
     "connaît pas, et c'est légitime. La règle 1 ne s'applique donc qu'aux "
     "noms cherchés dans une collection RÉSOLUE, jamais à tous les littéraux."),
)


# ===========================================================================
# LE CORPUS — ce que le dépôt connaît réellement comme vocabulaire
# ===========================================================================


def _vocabulaire_du_depot() -> str:
    """Tout le texte que le dépôt transporte, concaténé une fois."""
    # Le corpus partagé du dépôt : `git ls-files` quand il est là, un repli
    # EXPLICITE et déclaré sinon. Deux corpus qui se ressemblent finissent par
    # diverger — celui-ci est celui des deux gardes documentaires.
    from tests.corpus_du_depot import fichiers_du_depot

    morceaux = []
    for rel in fichiers_du_depot():
        p = RACINE / rel
        try:
            morceaux.append(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(morceaux)


_VOCABULAIRE: str | None = None


def vocabulaire() -> str:
    global _VOCABULAIRE
    if _VOCABULAIRE is None:
        _VOCABULAIRE = _vocabulaire_du_depot()
    return _VOCABULAIRE


# ===========================================================================
# LA RÉSOLUTION — n'évaluer que ce qui ne peut rien faire
# ===========================================================================

_DOTTE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")


def _espace_de_noms(arbre: ast.Module) -> dict:
    """Les symboles qu'on peut poser sans exécuter le fichier de test.

    Deux sources, et deux seulement : les `from <paquet> import X` vers les
    paquets déclarés, et les constantes littérales du module.

    Les IMPORTS se cherchent dans TOUT l'arbre : ce dépôt écrit la moitié des
    siens DANS le corps des tests, et c'est justement le cas de
    `test_cockpit_dit_vrai.py`, où le défaut a vécu. Un garde qui ne lit que
    l'en-tête ne verrait pas la ligne pour laquelle il a été écrit.

    Les CONSTANTES, elles, ne se prennent qu'au niveau du module — et cette
    distinction a été payée : en lisant les affectations de tout l'arbre, le
    garde a résolu un `atom` local avec le littéral `atom` d'une AUTRE fonction
    du même fichier, et rendu un reproche faux. Une portée qu'on ignore, c'est
    un homonyme qu'on confond. Le contexte local est ajouté fonction par
    fonction, dans `assertions_qui_ne_peuvent_pas_rougir`.
    """
    ns: dict = {}
    for n in ast.walk(arbre):
        if isinstance(n, ast.Assign):
            continue  # les constantes : plus bas, au niveau du module seul
        if isinstance(n, ast.ImportFrom) and n.module and \
                n.module.split(".")[0] in PAQUETS_RESOLVABLES:
            try:
                mod = __import__(n.module, fromlist=["*"])
            except Exception:
                continue
            for a in n.names:
                if a.name != "*" and hasattr(mod, a.name):
                    ns[a.asname or a.name] = getattr(mod, a.name)
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.split(".")[0] in PAQUETS_RESOLVABLES:
                    try:
                        __import__(a.name)
                    except Exception:
                        continue
                    import sys
                    ns[a.asname or a.name.split(".")[0]] = sys.modules[
                        a.name if a.asname else a.name.split(".")[0]]
    ns.update(_constantes_litterales(arbre.body))
    return ns


def _constantes_litterales(corps: list) -> dict:
    """Les affectations littérales d'UNE portée — module ou fonction."""
    trouve: dict = {}
    for n in corps:
        if not isinstance(n, ast.Assign):
            continue
        for cible in n.targets:
            if isinstance(cible, ast.Name):
                try:
                    trouve[cible.id] = ast.literal_eval(n.value)
                except Exception:
                    pass
    return trouve


def _resoudre(noeud: ast.expr, ns: dict) -> tuple[set[str] | None, str]:
    """Rend l'ensemble des membres STRING d'une collection, ou None.

    On n'évalue qu'un nom pointé — jamais un appel, jamais une indexation,
    jamais une compréhension. `eval` ne voit ici qu'un chemin d'attributs sur
    des objets déjà importés : il ne peut rien déclencher de plus que ce que la
    collecte de pytest a déjà fait en important le module.
    """
    src = ast.unparse(noeud)
    if isinstance(noeud, (ast.Set, ast.List, ast.Tuple, ast.Dict)):
        try:
            valeur = ast.literal_eval(noeud)
        except Exception:
            return None, src
    elif _DOTTE.match(src):
        try:
            valeur = eval(src, {"__builtins__": {}}, dict(ns))  # noqa: S307
        except Exception:
            return None, src
    else:
        return None, src
    try:
        membres = set(valeur)
    except TypeError:
        return None, src
    if not membres or not all(isinstance(m, str) for m in membres):
        return None, src
    return membres, src


def _sous_nom(cherche: str, membre: str) -> bool:
    """`confidence` est un sous-nom de `confidence_score`, pas de `cofidence`.

    On exige une frontière de nom : le membre commence ou finit par le nom
    cherché, ou le porte entouré de séparateurs d'identifiant.
    """
    if cherche == membre:
        return False
    return bool(re.search(rf"(^|[_\-./]){re.escape(cherche)}([_\-./]|$)", membre))


# ===========================================================================
# LE BALAYAGE
# ===========================================================================


def assertions_qui_ne_peuvent_pas_rougir(
    source: str, nom_fichier: str = "<essai>",
) -> list[str]:
    """Les reproches, un par assertion vide. Liste vide = rien à dire.

    Écrit comme une FONCTION et non comme un test, pour la même raison que
    `gestes_sans_organe` dans G4 : un garde qu'on ne peut pas éprouver sur une
    entrée fabriquée n'est pas éprouvé du tout.
    """
    reproches: list[str] = []
    arbre = ast.parse(source)
    ns = _espace_de_noms(arbre)
    vocab = vocabulaire()

    for fonction in ast.walk(arbre):
        if not isinstance(fonction, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        #: le contexte LOCAL de cette fonction, et de lui seul : deux fonctions
        #: d'un même fichier nomment souvent `atom` deux choses différentes.
        ns_local = dict(ns)
        ns_local.update(_constantes_litterales(fonction.body))

        #: les collections sur lesquelles CETTE fonction porte un témoin positif
        temoins: set[str] = set()
        #: {collection : les noms littéraux que CETTE fonction y interroge}
        interroges: dict[str, set[str]] = {}
        for n in ast.walk(fonction):
            if isinstance(n, ast.Compare) and len(n.ops) == 1 \
                    and isinstance(n.ops[0], (ast.In, ast.NotIn)):
                ou_ = ast.unparse(n.comparators[0])
                if isinstance(n.ops[0], ast.In):
                    temoins.add(ou_)
                if isinstance(n.left, ast.Constant) and isinstance(n.left.value, str):
                    interroges.setdefault(ou_, set()).add(n.left.value)
            elif isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) \
                    and isinstance(n.slice.value, str):
                # `AtomUpdate.model_fields["confidence_score"]` nomme le champ
                # aussi sûrement qu'un `in` : c'est même une preuve plus forte.
                ou_ = ast.unparse(n.value)
                interroges.setdefault(ou_, set()).add(n.slice.value)

        for n in ast.walk(fonction):
            if not isinstance(n, ast.Assert):
                continue
            for cmp_ in ast.walk(n.test):
                if not (isinstance(cmp_, ast.Compare) and len(cmp_.ops) == 1
                        and isinstance(cmp_.ops[0], ast.NotIn)
                        and isinstance(cmp_.left, ast.Constant)
                        and isinstance(cmp_.left.value, str)):
                    continue
                cherche = cmp_.left.value
                if not _NOM.match(cherche):
                    continue  # une phrase, pas un nom : hors de portée
                membres, src = _resoudre(cmp_.comparators[0], ns_local)
                if membres is None:
                    continue  # collection non résolue — comptée, pas jugée
                ou = f"{nom_fichier}:{n.lineno}"

                # RÈGLE 1 — le nom fantôme
                if vocab.count(cherche) <= 1:
                    reproches.append(
                        f"{ou} — RÈGLE 1 (nom fantôme) : « {cherche} » cherché "
                        f"dans {src} n'existe nulle part ailleurs dans le "
                        f"dépôt. Une absence qu'on constate sur un mot que le "
                        f"produit n'a jamais connu ne prouve rien.")
                    continue

                # RÈGLE 2 — le quasi-manqué
                proches = sorted(m for m in membres if _sous_nom(cherche, m))
                muets = [m for m in proches
                         if m not in interroges.get(src, set())]
                if muets:
                    reproches.append(
                        f"{ou} — RÈGLE 2 (quasi-manqué) : « {cherche} » est "
                        f"absent de {src}, mais {src} sert {muets}, dont ce "
                        f"test ne dit RIEN. Les deux noms sont confusables et "
                        f"un seul est interrogé : le lecteur croira que "
                        f"l'assertion porte sur l'autre. C'est la faute exacte "
                        f"qui a fait certifier « la confiance d'un atome est "
                        f"IMMUABLE » pendant sept manches, alors que "
                        f"`confidence_score` était servi et modifiable. "
                        f"Le remède est d'un mot : dites dans le MÊME test ce "
                        f"que vous savez de {muets} — sa présence, sa borne, "
                        f"son absence — et l'ambiguïté meurt.")
                    continue

                # RÈGLE 3 — le témoin
                if src not in temoins:
                    reproches.append(
                        f"{ou} — RÈGLE 3 (témoin absent) : « {cherche} » est "
                        f"déclaré absent de {src}, et rien dans "
                        f"« {fonction.name} » ne prouve que {src} contient "
                        f"quoi que ce soit. Ajoutez une assertion de PRÉSENCE "
                        f"sur la MÊME collection : sans elle, un import cassé "
                        f"ou une collection vide passent pour une preuve.")
    return reproches


def _fichiers_de_test() -> list[Path]:
    return sorted(p for p in DOSSIER_TESTS.rglob("*.py")
                  if p.name != Path(__file__).name)


# ===========================================================================
# LE GARDE
# ===========================================================================


def test_aucune_assertion_negative_ne_peut_etre_verte_par_construction() -> None:
    """LE GATE. Toute la suite, toutes les collections résolues."""
    reproches: list[str] = []
    for f in _fichiers_de_test():
        try:
            source = f.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            reproches += assertions_qui_ne_peuvent_pas_rougir(
                source, str(f.relative_to(RACINE)))
        except SyntaxError:
            continue
    assert not reproches, (
        "Des assertions d'absence ne peuvent pas rougir. Un test vert qui ne "
        "teste rien est pire qu'un test absent : il occupe la place.\n\n  "
        + "\n\n  ".join(reproches))


# ===========================================================================
# ÉPROUVER LE GARDE — on lui remet le défaut, et on regarde s'il rougit
# ===========================================================================

#: L'assertion vide, DANS SA FORME EXACTE, telle qu'elle a vécu sept manches à
#: `tests/test_cockpit_dit_vrai.py:538`. Elle est ici dans une chaîne : le garde
#: la lit comme un fichier fabriqué, il ne se la reproche pas à lui-même.
LA_LIGNE_QUI_A_VECU_SEPT_MANCHES = '''
from app.schemas.atom import AtomUpdate

def test_confidence_est_immuable_dans_l_api():
    assert "confidence" not in AtomUpdate.model_fields
'''

CAS_REFUSES: tuple[tuple[str, str, str], ...] = (
    (LA_LIGNE_QUI_A_VECU_SEPT_MANCHES, "RÈGLE 2",
     "la ligne exacte du défaut : `confidence` cherché, `confidence_score` servi"),
    ('''
from app.schemas.atom import AtomSupersede

def test_x():
    assert "confidence" not in AtomSupersede.model_fields
''', "RÈGLE 2", "le jumeau, sur la supersédure : `new_confidence_score` est servi"),
    ('''
from agents.cortex.contract import FORBIDDEN_ATOM_FIELDS

def test_x():
    assert "node_id" not in FORBIDDEN_ATOM_FIELDS
''', "RÈGLE 3", "une absence sans témoin — ici elle est en plus FAUSSE"),
    ('''
def test_x():
    assert "confidance_scor" not in {"confidence_score", "value"}
''', "RÈGLE 1", "une faute de frappe : le nom cherché n'existe nulle part"),
)

CAS_ACCEPTES: tuple[tuple[str, str], ...] = (
    ('''
from app.schemas.atom import AtomUpdate

def test_x():
    assert "confidence_score" in AtomUpdate.model_fields
    assert "kind" not in AtomUpdate.model_fields
''', "un témoin positif, et un nom sans homonyme dans la collection"),
    ('''
from app.schemas.atom import AtomUpdate

def test_x():
    assert "confidence_score" in AtomUpdate.model_fields
    assert "confidence" not in AtomUpdate.model_fields
''', "le quasi-manqué est LEVÉ dès que le test dit ce qu'il sait de l'autre nom"),
    ('''
def test_x():
    resultat = calcule()
    assert "confidence" not in resultat
''', "collection non résolue : le garde ne juge pas ce qu'il ne voit pas"),
    ('''
def test_x():
    assert "Ouvrez le cockpit et tranchez" not in page
''', "une phrase, pas un nom : hors de portée, et c'est le travail de G4"),
)


@pytest.mark.parametrize("source,regle,pourquoi", CAS_REFUSES)
def test_le_garde_rougit_quand_on_lui_remet_le_defaut(
    source: str, regle: str, pourquoi: str,
) -> None:
    reproches = assertions_qui_ne_peuvent_pas_rougir(source, "essai.py")
    assert reproches, (
        f"LE GARDE N'A RIEN VU — et c'est {pourquoi}.\n{source}")
    assert any(regle in r for r in reproches), (
        f"vu, mais pas par la bonne règle (attendu {regle}) : {reproches}")


@pytest.mark.parametrize("source,pourquoi", CAS_ACCEPTES)
def test_le_garde_se_tait_quand_l_assertion_peut_rougir(
    source: str, pourquoi: str,
) -> None:
    reproches = assertions_qui_ne_peuvent_pas_rougir(source, "essai.py")
    assert reproches == [], (
        f"Le garde a crié à tort — {pourquoi} :\n{reproches}")


def test_le_garde_declare_ce_qu_il_ne_voit_pas() -> None:
    """L'AVEU, et il est chiffré.

    Le garde ne juge que les collections qu'il résout. Combien en laisse-t-il
    passer ? La question a une réponse, et elle doit être IMPRIMÉE : un garde
    qui tait sa portée donne confiance là où il ne regarde pas.
    """
    resolues = non_resolues = 0
    for f in _fichiers_de_test():
        try:
            arbre = ast.parse(f.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        ns = _espace_de_noms(arbre)
        for fonction in ast.walk(arbre):
            if not isinstance(fonction, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            ns_local = dict(ns)
            ns_local.update(_constantes_litterales(fonction.body))
            for n in ast.walk(fonction):
                if not (isinstance(n, ast.Compare) and len(n.ops) == 1
                        and isinstance(n.ops[0], ast.NotIn)
                        and isinstance(n.left, ast.Constant)
                        and isinstance(n.left.value, str)
                        and _NOM.match(n.left.value)):
                    continue
                membres, _ = _resoudre(n.comparators[0], ns_local)
                if membres is None:
                    non_resolues += 1
                else:
                    resolues += 1

    assert resolues > 0, (
        "le garde ne résout plus AUCUNE collection : il est devenu un décor")
    assert len(ZONES_NON_COUVERTES) >= 5, ZONES_NON_COUVERTES
    print(f"\nGARDE « une assertion négative doit pouvoir rougir » — PORTÉE "
          f"RÉELLE : {resolues} assertion(s) d'absence jugée(s), "
          f"{non_resolues} hors de portée (collection calculée). "
          f"Ce que le garde ne couvre pas, nommément :")
    for titre, detail in ZONES_NON_COUVERTES:
        print(f"  · {titre} — {detail}")
