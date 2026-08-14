"""Le cockpit dit la même vérité que la documentation — et il la CONSTATE.

Pourquoi ce fichier existe
==========================
La manche précédente a réparé les documents : sept d'entre eux disent
désormais la même chose de la couche de liens explicites. Le cockpit, lui,
disait encore autre chose à l'écran. Un utilisateur qui lit la doc puis ouvre
son cockpit voyait deux vérités, et rien dans la suite ne s'en apercevait —
parce que le seul contrôle existant bornait son regard aux ``unavailable_reason``
du registre. Tout ce qui est servi ailleurs (les blocs ``links`` des routes de
navigation, les « limites connues » du rejeu, les lectures d'une preuve SQL)
échappait au garde-fou, et **la réparation a eu exactement la taille du
garde-fou**.

Ce fichier prend le problème par l'autre bout : il moissonne **toutes les
chaînes de caractères que le code du cockpit peut servir** — par analyse
syntaxique, docstrings et commentaires exclus — et leur applique trois règles.

RÈGLE 1 — On ne déclare pas mort un mécanisme que le dépôt livre vivant.
    « aucun agent n'y écrit de lien aujourd'hui » était servi sur la constante
    vitale V5 pendant que ``agents/cortex/cycle.py`` appelait
    ``app/services/atom_links.recompute()`` à chaque tour. Le lecteur était
    envoyé chercher un agent d'écriture qui existe déjà. La règle est
    mécanique : une phrase qui nie l'existence d'un producteur nomme un objet,
    et cet objet ne doit avoir **aucun écrivain dans le dépôt**.

RÈGLE 2 — On n'affirme pas l'état d'une base sans l'avoir regardée.
    « la colonne est NULL sur la totalité des atomes », « la table est
    absente », « vérifié exhaustif le 2026-08-04 » : ce sont des mesures faites
    sur UNE base — celle de l'auteur — gravées dans le code et resservies à
    tout le monde. Une telle phrase n'est licite que si elle DESCEND d'un
    constat : projetée par un SQL qui sonde (``to_regclass``), gardée par une
    métrique dont le SQL ne rend NULL que dans ce cas-là, ou produite par une
    sonde déclarée (``entities.TEXTES_CONSTATES``).

RÈGLE 3 — Quand on pouvait regarder, on ne sert pas le texte du « je ne sais pas ».
    ``LINKS_UNAVAILABLE`` a changé de sens : il ne dit plus « la table n'existe
    pas », il dit « je n'ai pas pu regarder ». Six routes qui, elles, venaient
    d'interroger le schéma le servaient encore tel quel — elles accusaient
    l'installation du lecteur au lieu de dire ce qu'elles avaient vu. La règle
    interdit à quiconque, hors du repli de la sonde elle-même, d'embarquer ce
    texte dans une charge utile.

Et une quatrième, d'une autre famille :

RÈGLE 4 — On ne présente comme actionnable que ce qu'on peut faire.
    Le cockpit n'a **aucune route d'écriture** : il ne peut trancher aucune
    proposition. Une page qui affiche une file de « propositions » sans dire
    où le geste se fait réellement promet un rituel impossible.

    On disait ici, en plus, « et ``confidence`` est immuable dans l'API ».
    C'était vrai du NIVEAU déclaré (``confidence``) et de la trace d'audit,
    faux du CHIFFRE (``confidence_score``), que le PATCH sert. La formule
    courte a survécu sept manches parce qu'un test l'a certifiée en
    interrogeant le mauvais nom. Le geste absent du cockpit, lui, n'a pas
    besoin de cette béquille : aucune route d'écriture, c'est déjà tout dire.

Hors-ligne, comme toute la suite : aucun test d'ici n'ouvre de connexion. Ils
lisent le code déclaré, le registre chargé, et le HTML rendu.
"""

from __future__ import annotations

import ast
import pathlib
import re
from typing import Iterator

import pytest

RACINE = pathlib.Path(__file__).resolve().parents[1]
COCKPIT = RACINE / "control_center"
MOTEUR = (RACINE / "app", RACINE / "agents")


# ============================================================================
# La moisson : tout ce que le code du cockpit peut servir
# ============================================================================


def _sources(racine: pathlib.Path) -> Iterator[pathlib.Path]:
    for p in sorted(racine.rglob("*.py")):
        if "__pycache__" not in p.parts:
            yield p


def _chaines_servies(chemin: pathlib.Path) -> Iterator[tuple[int, str]]:
    """Les chaînes littérales du fichier, **hors documentation**.

    Sont écartées : les docstrings de module, de classe et de fonction, ainsi
    que les docstrings d'attribut (une chaîne seule sur sa ligne, qui documente
    l'affectation précédente). Ces textes-là racontent souvent l'histoire d'une
    correction — « elle affirmait que la table n'existait pas » — et les
    interdire reviendrait à effacer la mémoire de la faute. Les commentaires,
    eux, ne sont pas dans l'arbre syntaxique : ils sont écartés d'office.

    Tout le reste est un candidat au service : le registre l'expose, une route
    le met dans sa charge utile, ou un SQL le projette dans une colonne.
    """
    arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    documentation: set[int] = set()
    for noeud in ast.walk(arbre):
        for enfant in ast.iter_child_nodes(noeud):
            # Une chaîne SEULE en position d'instruction n'est jamais servie :
            # c'est une docstring (module, classe, fonction) ou la
            # documentation d'un attribut.
            if (isinstance(enfant, ast.Expr)
                    and isinstance(enfant.value, ast.Constant)
                    and isinstance(enfant.value.value, str)):
                documentation.add(id(enfant.value))
    for noeud in ast.walk(arbre):
        if (isinstance(noeud, ast.Constant) and isinstance(noeud.value, str)
                and id(noeud) not in documentation and len(noeud.value) >= 8):
            yield noeud.lineno, noeud.value


def _moisson() -> list[tuple[pathlib.Path, int, str]]:
    return [(p, ln, s) for p in _sources(COCKPIT) for ln, s in _chaines_servies(p)]


MOISSON = _moisson()


def _situer(p: pathlib.Path, ln: int, s: str, motif: re.Match[str] | None = None) -> str:
    extrait = s if motif is None else s[max(0, motif.start() - 80):motif.end() + 80]
    return f"{p.relative_to(RACINE)}:{ln} — …{' '.join(extrait.split())}…"


def test_la_moisson_attrape_vraiment_ce_qui_est_servi():
    """Un moissonneur vide rendrait toutes les règles suivantes vertes pour rien.

    Deux témoins : une raison d'indisponibilité du registre (servie par l'API)
    et un fragment de SQL (projeté dans une colonne). S'ils manquent, c'est
    l'analyse syntaxique qui est cassée, pas le cockpit qui est propre.
    """
    textes = [s for _, _, s in MOISSON]
    assert len(textes) > 1000, f"moisson suspecte : {len(textes)} chaînes"
    assert any("to_regclass" in s for s in textes), "aucun SQL moissonné"
    assert any("indisponible" in s.lower() for s in textes), "aucune raison moissonnée"


# ============================================================================
# RÈGLE 1 — aucun mécanisme n'est déclaré mort alors que le dépôt le livre vivant
# ============================================================================

#: Les tournures par lesquelles un texte servi NIE l'existence d'un producteur.
#: Ce sont des affirmations sur le DÉPÔT, pas sur la base du lecteur : elles
#: sont donc vérifiables ici, sans connexion, et elles doivent être vraies.
#:
#: Les apostrophes sont doublées quand la phrase voyage dans un littéral SQL
#: (« aucun agent n''y écrit ») : c'est précisément là que se cachait la faute
#: de cette manche, dans le ``CASE`` d'une métrique et non dans un champ du
#: registre. Le motif accepte donc une ou deux apostrophes.
_NIE_UN_PRODUCTEUR = re.compile(
    r"(aucun(?:e)?\s+\w+\s+n[’']{1,2}\s*(?:y\s+)?[ée]crit"
    r"|aucun\s+agent\s+n[’']{1,2}\s*(?:y\s+)?[ée]crit"
    r"|rien\s+n[’']{1,2}\s*(?:y\s+)?[ée]crit"
    r"|rien\s+ne\s+l[’']{1,2}alimente"
    r"|n[’']est\s+pas\s+aliment[ée]e?s?"
    r"|m[ée]canisme\s+non\s+aliment[ée]"
    r"|non\s+stock[ée]e?s?"
    r"|jamais\s+aliment[ée]e?s?)", re.I)

#: Les objets dont un texte servi peut nier le producteur, et qui sont
#: vérifiables : les tables ``arac.*`` et les colonnes d'atome que le cockpit
#: cite nommément.
_COLONNES_CITABLES = ("last_verified_at", "confirmed_until", "superseded_by",
                      "supersedes")


def _sql_du_moteur() -> str:
    morceaux = []
    for racine in MOTEUR:
        for p in _sources(racine):
            morceaux.append(p.read_text(encoding="utf-8"))
    return "\n".join(morceaux)


SQL_MOTEUR = _sql_du_moteur()

#: Chaque instruction d'écriture du moteur, découpée pour qu'on puisse demander
#: « cette colonne est-elle écrite quelque part ? » sans confondre deux
#: instructions voisines.
_ECRITURES = [m.group(0) for m in re.finditer(
    r"(?is)(INSERT\s+INTO|UPDATE)\s+arac\.\w+.{0,3000}?(?=;|\"\"\")", SQL_MOTEUR)]


def _le_depot_ecrit(objet: str) -> list[str]:
    """Les instructions d'écriture du moteur qui touchent cet objet.

    Liste vide = le dépôt ne livre aucun producteur, et le cockpit a le droit
    de le dire. Liste non vide = le dire est un mensonge, et le lecteur ira
    chercher un agent qui tourne déjà.
    """
    if objet.startswith("arac."):
        motif = re.compile(r"(?is)^(INSERT\s+INTO|UPDATE)\s+" + re.escape(objet) + r"\b")
    else:
        motif = re.compile(r"(?is)\b" + re.escape(objet) + r"\b")
    return [e[:90] for e in _ECRITURES if motif.search(e)]


def test_le_depot_livre_bien_un_ecrivain_pour_la_couche_de_liens():
    """Le fait sur lequel tout le reste s'appuie — établi ici, pas supposé.

    Si un jour plus personne n'écrit dans ``arac.atom_links``, ce test tombe le
    premier et dit à la manche suivante que les textes du cockpit peuvent (et
    doivent) redevenir « rien ne l'alimente ». La vérité et son garde vivent au
    même endroit.
    """
    ecrivains = _le_depot_ecrit("arac.atom_links")
    assert ecrivains, (
        "aucune instruction d'écriture vers arac.atom_links dans app/ ni agents/"
    )
    cycle = (RACINE / "agents" / "cortex" / "cycle.py").read_text(encoding="utf-8")
    assert "atom_links" in cycle and "recompute" in cycle, (
        "le cycle du cortex n'appelle plus le recalcul des liens"
    )


def test_le_depot_n_ecrit_ni_last_verified_at_ni_confirmed_until():
    """Le pendant du précédent : ces deux mécanismes-là sont VRAIMENT absents.

    Le cockpit a donc raison de le dire. Le jour où quelqu'un les branche, ce
    test tombe et désigne les phrases à réécrire.
    """
    for colonne in ("last_verified_at", "confirmed_until"):
        assert not _le_depot_ecrit(colonne), (
            f"{colonne} est désormais écrite : les textes du cockpit qui la "
            f"déclarent morte sont à réécrire"
        )


_MARQUEURS_SQL = re.compile(r"\bSELECT\b|\bFROM\b|\bCASE\s+WHEN\b")
#: Un littéral SQL, apostrophes internes doublées comprises.
_LITTERAL_SQL = re.compile(r"'((?:[^']|'')*)'")


def _phrases_servies(s: str) -> list[str]:
    """Ce qu'un lecteur voit VRAIMENT, découpé comme il le voit.

    Une requête est du code : ce qui arrive sous les yeux du lecteur, ce sont
    ses littéraux — les colonnes ``reason``, ``gesture``, ``lecture``. Les
    juger avec la requête entière autour reviendrait à imputer à une phrase les
    tables que sa voisine interroge : la preuve de la couverture de
    vérification dit « aucun agent n'écrit cette colonne » **à côté** d'un
    ``FROM arac.memory_atoms``, et memory_atoms est évidemment écrite. Le
    reproche porterait sur la mauvaise table.
    """
    if _MARQUEURS_SQL.search(s):
        return [m.group(1) for m in _LITTERAL_SQL.finditer(s)] or [s]
    return [s]


def test_aucun_message_servi_ne_declare_mort_un_mecanisme_que_le_depot_livre_vivant():
    """La règle 1, appliquée à toute la moisson.

    Elle attrape la faute de cette manche : ``vital_connectivity`` servait
    « alimentez arac.atom_links : aucun agent n'y écrit de lien aujourd'hui »
    alors que le cycle du cortex y écrit trois fois par jour, et la preuve de
    l'étage graphes qualifiait les arêtes ``supersedes`` de « non stockées »
    alors que ``_UPSERT_SUPERSEDES_SQL`` les stocke.
    """
    fautifs: list[str] = []
    for p, ln, s in MOISSON:
        for phrase in _phrases_servies(s):
            motif = _NIE_UN_PRODUCTEUR.search(phrase)
            if not motif:
                continue
            objets = set(re.findall(r"arac\.\w+", phrase))
            objets |= {c for c in _COLONNES_CITABLES if re.search(rf"\b{c}\b", phrase)}
            vivants = sorted(o for o in objets if _le_depot_ecrit(o))
            if vivants:
                fautifs.append(f"{p.relative_to(RACINE)}:{ln} — "
                               f"« {' '.join(phrase.split())} »"
                               f"\n      → écrit pourtant par le dépôt : {vivants}")
    assert not fautifs, (
        "Le cockpit déclare mort un mécanisme que le dépôt livre vivant. "
        "Le lecteur est envoyé brancher ce qui tourne déjà.\n  "
        + "\n  ".join(fautifs))


# ============================================================================
# RÈGLE 2 — aucune affirmation sur l'état d'une base sans constat
# ============================================================================

#: Les tournures qui affirment l'état de LA BASE DU LECTEUR. Elles ne sont pas
#: vérifiables ici : elles doivent donc être produites par un regard.
_AFFIRME_UNE_BASE = re.compile(
    r"(est\s+NULL\s+sur\s+(?:la\s+totalit|les\b|tous\b)"
    r"|sont\s+NULL\s+sur\s+(?:la\s+totalit|les\b|tous\b)"
    r"|sur\s+la\s+totalit[ée]\s+des\s+atomes"
    r"|\(\s*0\s+atome"
    r"|table\s+[\w.]+\s+(?:est\s+)?(?:absente|pr[ée]sente|d[ée]ploy[ée]e)"
    r"|la\s+table\s+[\w.]+\s+n[’']existe\s+pas"
    r"|n[’']est\s+pas\s+d[ée]ploy[ée]e"
    r"|v[ée]rifi[ée]\w*\s+\w*\s*le\s+\d{4}-\d{2}-\d{2}"
    r"|n[’']a\s+jamais\s+[ée]t[ée]\s+enregistr)", re.I)


def _sql_du_registre() -> list[str]:
    from control_center.cc_v1 import registry

    out: list[str] = []
    for m in registry.REGISTRY:
        for champ in ("sql", "evidence_sql"):
            valeur = getattr(m, champ, None)
            if valeur:
                out.append(str(valeur))
    return out


def _textes_constates() -> set[str]:
    """Les textes qu'une sonde DÉCLARÉE produit après avoir regardé.

    ``entities.TEXTES_CONSTATES`` est le contrat : y figurer signifie « ce
    texte n'est jamais servi sans qu'une requête l'ait justifié ». La règle 3
    vérifie que personne ne court-circuite ce contrat.
    """
    from control_center.cc_v1 import entities

    return {str(v) for bloc in entities.TEXTES_CONSTATES for v in bloc.values()}


def test_aucun_message_servi_n_affirme_l_etat_d_une_base_sans_l_avoir_constate():
    """La règle 2, appliquée à toute la moisson.

    Trois façons légitimes d'affirmer l'état d'une base :

    1. la phrase est un morceau d'un SQL qui SONDE (``to_regclass``) ou qui ne
       rend NULL que dans le cas décrit (``THEN NULL``) — le texte descend du
       constat, exactement comme les chiffres ;
    2. la phrase est produite par une sonde déclarée
       (``entities.TEXTES_CONSTATES``) ;
    3. la phrase est le repli d'une métrique dont le SQL, lui, sonde.

    Tout le reste est une mesure faite sur la base de quelqu'un d'autre, gravée
    dans le code et resservie au lecteur.
    """
    from control_center.cc_v1 import registry

    sqls = _sql_du_registre()
    constates = _textes_constates()
    replis_gardes = {
        str(getattr(m, champ))
        for m in registry.REGISTRY
        for champ in ("unavailable_reason", "unavailable_gesture")
        if getattr(m, champ, None)
        and ("to_regclass" in str(m.sql or "") or "THEN NULL" in str(m.sql or ""))
    }

    fautifs: list[str] = []
    for p, ln, s in MOISSON:
        motif = _AFFIRME_UNE_BASE.search(s)
        if not motif:
            continue
        # 1. la phrase EST un SQL qui sonde (ou en fait partie)
        if "to_regclass" in s or re.search(r"THEN\s+NULL", s, re.I):
            continue
        if any(s in sql and ("to_regclass" in sql or re.search(r"THEN\s+NULL", sql, re.I))
               for sql in sqls):
            continue
        # 2. la phrase vient d'une sonde déclarée
        if s in constates:
            continue
        # 3. la phrase est le repli d'une métrique qui, elle, sonde
        if s in replis_gardes:
            continue
        fautifs.append(_situer(p, ln, s, motif))
    assert not fautifs, (
        "Un texte servi affirme l'état d'une base sans l'avoir regardée : "
        "c'est la mesure d'une autre base, resservie au lecteur.\n  "
        + "\n  ".join(fautifs))


# ============================================================================
# RÈGLE 3 — le repli « je n'ai pas pu regarder » n'est jamais servi par un
#           organe qui pouvait regarder
# ============================================================================


def test_le_repli_de_la_sonde_n_est_embarque_par_aucune_charge_utile():
    """La régression de la manche précédente, transformée en garde.

    ``LINKS_UNAVAILABLE`` a changé de sens sans que ses appelants suivent :
    ``lifestory``, ``entities``, ``cascade`` et ``routes`` le servaient encore
    tel quel, en disant « le schéma n'a pas été interrogé » à des lecteurs dont
    la page venait précisément d'interroger le schéma. Le repli n'a qu'un seul
    usage licite : le ``except`` de la sonde elle-même, et le défaut d'une
    fonction à qui l'on n'a pas passé de constat.
    """
    autorises = {
        # La sonde le définit et le rend quand elle n'a pas pu regarder.
        "control_center/cc_v1/entities.py",
        # `_step_links` reçoit le constat du lot ; sans constat, elle retombe
        # sur le texte qui n'affirme rien. C'est le contrat, pas un oubli.
        "control_center/cc_v1/cascade.py",
    }
    fautifs: list[str] = []
    for p in _sources(COCKPIT):
        relatif = str(p.relative_to(RACINE))
        arbre = ast.parse(p.read_text(encoding="utf-8"))
        for noeud in ast.walk(arbre):
            if not (isinstance(noeud, ast.Name) and noeud.id == "LINKS_UNAVAILABLE"):
                continue
            if relatif in autorises:
                continue
            fautifs.append(f"{relatif}:{noeud.lineno}")
    assert not fautifs, (
        "Un organe du cockpit sert le texte « je n'ai pas pu regarder » alors "
        "qu'il tient une connexion : il doit appeler entities.links_dependency(conn).\n  "
        + "\n  ".join(fautifs))


def test_cascade_ne_garde_le_repli_que_comme_defaut_de_signature():
    """Le seul usage toléré dans ``cascade`` est bien celui qui est annoncé.

    Sans cette borne, l'autorisation accordée au fichier ci-dessus devient un
    passe-droit : c'est exactement la faute de la manche précédente — un
    garde-fou dont le trou a la taille de la réparation.
    """
    chemin = COCKPIT / "cc_v1" / "cascade.py"
    src = chemin.read_text(encoding="utf-8")
    lignes = src.split("\n")
    # Un nom importé n'est pas un usage : l'arbre syntaxique fait la différence
    # que la lecture ligne à ligne ne fait pas.
    usages = [n.lineno for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.Name) and n.id == "LINKS_UNAVAILABLE"]
    assert len(usages) == 1, (
        "cascade.py ne doit garder qu'UN usage du repli — le défaut de "
        "`_step_links` :\n  "
        + "\n  ".join(f"{ln}: {lignes[ln - 1].strip()}" for ln in usages))
    assert "links_dep or LINKS_UNAVAILABLE" in lignes[usages[0] - 1], lignes[usages[0] - 1]


def test_la_sonde_des_liens_distingue_ce_qu_elle_a_vu():
    """La sonde rend quatre réponses, et elles ne se confondent pas.

    - schéma illisible          → elle n'affirme rien ;
    - table absente             → il manque une migration ;
    - table là, aucune ligne    → il manque un passage du cycle ;
    - table là, des lignes      → il manque une LECTURE, pas un déploiement.

    Confondre les deux derniers, c'est envoyer le lecteur relancer une
    migration déjà passée — ou brancher un agent qui tourne déjà.
    """
    from control_center.cc_v1 import entities

    class _Cur:
        def __init__(self, reponses):
            self._reponses = list(reponses)
            self.sqls: list[str] = []

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, *a):
            self.sqls.append(sql)

        def fetchone(self):
            return self._reponses.pop(0)

    class _Conn:
        def __init__(self, reponses):
            self.cur = _Cur(reponses)

        def cursor(self):
            return self.cur

    # table absente : une seule requête suffit, on ne lit pas ce qui n'existe pas
    assert entities.links_dependency(_Conn([(False,)])) == dict(entities.LINKS_ABSENT)
    # table présente et vide
    assert entities.links_dependency(_Conn([(True,), (False,)])) == dict(entities.LINKS_EMPTY)
    # table présente et peuplée
    assert entities.links_dependency(_Conn([(True,), (True,)])) == dict(entities.LINKS_NOT_READ)

    textes = {b["reason"] for b in (entities.LINKS_ABSENT, entities.LINKS_EMPTY,
                                    entities.LINKS_NOT_READ, entities.LINKS_UNAVAILABLE)}
    assert len(textes) == 4, "deux états rendent la même phrase : le constat ne sert à rien"


def test_les_routes_de_navigation_servent_le_constat_et_non_le_postulat():
    """Chaque bloc ``links`` servi descend d'un appel à la sonde.

    C'est la contrepartie positive de la règle 3 : interdire le repli ne suffit
    pas, encore faut-il que quelque chose ait regardé.
    """
    attendus = {
        "cc_v1/lifestory.py": 3,   # histoire d'atome, graphe de projet, chronologie
        "cc_v1/entities.py": 3,    # conversation, atome, projet
        "cc_v1/cascade.py": 3,     # étape « liens », bloc de cascade, absences connues
        "cc_v1/routes.py": 1,      # /status
    }
    manquants = []
    for relatif, minimum in attendus.items():
        src = (COCKPIT / relatif).read_text(encoding="utf-8")
        n = len(re.findall(r"links_dependency\s*\(", src)) + \
            len(re.findall(r"_links_dependency\s*\(", src)) + \
            len(re.findall(r"(?<!def )_links\s*\(", src))
        if n < minimum:
            manquants.append(f"{relatif} : {n} appel(s) de sonde pour {minimum} attendu(s)")
    assert not manquants, (
        "Un bloc « liens » est servi sans que rien n'ait regardé la base.\n  "
        + "\n  ".join(manquants))


# ============================================================================
# RÈGLE 4 — rien n'est présenté comme actionnable si personne ne peut l'agir
# ============================================================================


def test_le_cockpit_n_a_aucune_route_d_ecriture_sur_le_cerveau():
    """Le fait dont dépend tout le reste de cette section.

    Une seule méthode mutatrice existe, et elle n'écrit rien du cerveau :
    ``POST /cc/login`` pose un cookie de session. Tout le reste est en lecture.
    S'il devient faux — parce qu'on a enfin branché l'écriture — ce test tombe,
    et la phrase que la documentation doit dire change avec lui.
    """
    verbes = re.compile(r"@\w+\.(post|put|patch|delete)\s*\(\s*[\"']([^\"']*)", re.I)
    routes = []
    for p in _sources(COCKPIT):
        for m in verbes.finditer(p.read_text(encoding="utf-8")):
            if m.group(2) == "/cc/login":
                continue  # ouvrir une session n'est pas modifier un souvenir
            routes.append(f"{p.relative_to(RACINE)}:{m.group(1)} {m.group(2)}")
    assert not routes, (
        "Le cockpit a désormais une route d'écriture ; les textes qui disent "
        "l'inverse sont à réécrire.\n  " + "\n  ".join(routes))

    js = (COCKPIT / "cc_v1" / "static" / "app.js").read_text(encoding="utf-8")
    assert "method" not in js.split("fetch(")[1].split(")")[0], (
        "le seul fetch du cockpit porte désormais une méthode : il écrit")
    # On regarde le HTML RENDU (les chaînes servies), pas la documentation :
    # `templates.py` rappelle dans sa docstring qu'il n'émet « zéro <form> »,
    # et cette phrase-là est justement ce qu'on veut pouvoir écrire.
    formulaires = [f"{p.relative_to(RACINE)}:{ln}"
                   for p, ln, s in MOISSON if "<form" in s.lower()]
    assert len(formulaires) == 1 and formulaires[0].startswith("control_center/app.py"), (
        f"un formulaire est rendu hors de la page de connexion : {formulaires}")


def test_le_niveau_declare_est_immuable_mais_pas_le_chiffre():
    """CE TEST A ÉTÉ VERT PENDANT SEPT MANCHES SANS RIEN PROUVER.

    Il portait ceci — et sa docstring concluait « un atome naît avec sa
    confiance et meurt avec elle » :

        assert "confidence" not in AtomUpdate.model_fields

    Le champ servi s'appelle ``confidence_score``. La clé cherchée n'a jamais
    appartenu au vocabulaire de cette collection : l'assertion était vraie de
    toute éternité, elle ne pouvait pas rencontrer son contre-exemple, et elle
    a CERTIFIÉ une fausseté que l'installateur imprimait à chaque installation
    — « la confiance d'un atome est IMMUABLE … ne cherchez pas le réglage qui
    la ferait monter ». Le réglage existe. Mesuré sur un cerveau réel le
    9 août 2026 : ``PATCH /v1/atoms/<id> {"confidence_score": 95}`` sur un
    atome à 40 rend **200**, et la base porte 95.

    Un test vert qui ne teste rien est pire qu'un test absent : il occupe la
    place. `tests/test_une_assertion_negative_doit_pouvoir_rougir.py` refuse
    désormais cette forme pour toute la suite.

    CE QUE CE TEST PROUVE MAINTENANT — les deux moitiés, dans le même geste :
    chaque absence est encadrée d'une PRÉSENCE sur la MÊME collection, faute
    de quoi on ne saurait pas si l'instrument voit quoi que ce soit.
    """
    from app.schemas.atom import AtomSupersede, AtomUpdate

    # --- le NIVEAU déclaré et la trace d'audit : immuables ------------------
    # Les collections sont nommées EN TOUTES LETTRES à chaque ligne, et non
    # rangées dans une variable locale : `test_une_assertion_negative_doit_
    # pouvoir_rougir.py` ne résout que ce qu'il voit, et se soustraire à son
    # regard par un renommage serait exactement la faute qu'il surveille.
    assert "confidence_score" in AtomUpdate.model_fields, (
        "le témoin a disparu : sans un champ que la collection sert VRAIMENT, "
        "les assertions d'absence ci-dessous ne prouveraient plus rien")
    assert "confidence" not in AtomUpdate.model_fields, (
        "le NIVEAU déclaré (producer/agent_suggest/auditor_validated) est "
        "devenu modifiable par PATCH : l'écran de fin du bootstrap et la doc "
        "qui le disent immuable sont à réécrire")
    assert "audit_source" not in AtomUpdate.model_fields, (
        "la trace d'audit est devenue modifiable : « 98 % du savoir jamais "
        "audité » cesse d'être un constat sur ce que personne ne peut toucher")

    assert "new_confidence_score" in AtomSupersede.model_fields, (
        "le témoin a disparu du corps de supersédure")
    assert "confidence" not in AtomSupersede.model_fields, (
        "la supersédure accepte désormais un NIVEAU : la doc change")
    assert "new_confidence" not in AtomSupersede.model_fields, (
        "un second nom pour le niveau est apparu dans la supersédure")
    assert "audit_source" not in AtomSupersede.model_fields, (
        "la supersédure accepte désormais une trace d'audit : la doc change")

    routeur = (RACINE / "app" / "routers" / "atoms.py").read_text(encoding="utf-8")
    assert 'old["confidence"]' in routeur, (
        "la supersédure ne recopie plus le niveau déclaré de l'atome remplacé")
    assert 'old["audit_source"]' in routeur, (
        "la supersédure ne recopie plus la trace d'audit de l'atome remplacé")


def test_le_chiffre_de_confiance_est_bel_et_bien_servi():
    """L'AUTRE MOITIÉ DE LA VÉRITÉ — celle qui manquait, et qui a coûté sept manches.

    Une assertion d'absence ne dit jamais qu'une moitié. Celle-ci dit l'autre :
    le NOMBRE est servi, par les deux routes d'écriture, et sa borne est
    déclarée. Le jour où quelqu'un le retire, ce test rougit — et l'écran de
    fin du bootstrap, qui décrit désormais ce geste, redevient à réécrire.
    """
    from app.schemas.atom import AtomSupersede, AtomUpdate

    for modele, champ in ((AtomUpdate, "confidence_score"),
                          (AtomSupersede, "new_confidence_score")):
        info = modele.model_fields[champ]
        bornes = {type(m).__name__: getattr(m, "ge", getattr(m, "le", None))
                  for m in info.metadata}
        assert bornes.get("Ge") == 0 and bornes.get("Le") == 100, (
            f"{modele.__name__}.{champ} n'est plus borné 0-100 : la leçon de "
            f"l'écran de fin parle d'« un nombre de 0 à 100 »")

    routeur = (RACINE / "app" / "routers" / "atoms.py").read_text(encoding="utf-8")
    assert "payload.confidence_score is not None" in routeur, (
        "le PATCH n'écrit plus le chiffre : la leçon « le NOMBRE se corrige » "
        "de bootstrap/lib/verify.sh devient fausse")

    # LA CONVENTION D'HÉRITAGE, SUR LES QUATRE CHAMPS À LA FOIS.
    # `new_confidence_score` passait BRUT au INSERT : une supersédure muette
    # sur le chiffre écrivait NULL, là où tags/rationale/source_ref héritaient.
    # Mesuré sur un cerveau réel avant correction : atome à 40, supersède sans
    # `new_confidence_score` -> 201, nouvel atome à NULL.
    for champ in ("new_tags", "new_rationale", "new_source_ref",
                  "new_confidence_score"):
        attendu = f"payload.{champ}\n        if payload.{champ} is not None"
        court = f"payload.{champ} if payload.{champ} is not None"
        assert attendu in routeur or court in routeur, (
            f"{champ} n'hérite plus de l'atome remplacé — c'est le défaut "
            f"exact qui effaçait la confiance en silence")


_SECRET_ESSAI = "test_secret_cockpit_dit_vrai_not_for_production"


@pytest.fixture()
def cockpit(monkeypatch):
    """Un cockpit authentifié dont l'API cerveau répond une file non vide.

    C'est le seul état où la faute est visible : une file vide n'a rien à
    promettre. On sert donc deux propositions plausibles, comme l'API le ferait.
    """
    from fastapi.testclient import TestClient

    from control_center.app import create_app
    from control_center.collectors import brain_api
    from control_center.config import CC_SESSION_SECRET_ENV, SESSION_COOKIE_NAME
    from control_center.security import sign_session

    monkeypatch.setenv(CC_SESSION_SECRET_ENV, _SECRET_ESSAI)
    monkeypatch.setattr(brain_api, "proposals", lambda: {
        "count": 2,
        "proposals": [
            {"proposal_id": "p-1", "scope": "essai/un",
             "lifecycle_state": "needs_review", "confidence_score": 61},
            {"proposal_id": "p-2", "scope": "essai/deux",
             "lifecycle_state": "needs_review", "confidence_score": 44},
        ],
    })
    client = TestClient(create_app(), raise_server_exceptions=True)
    client.cookies.set(
        SESSION_COOKIE_NAME,
        sign_session({"sub": "test_dit_vrai"}, secret=_SECRET_ESSAI))
    return client


def test_la_file_des_propositions_dit_ou_le_geste_se_fait(cockpit):
    """Une file qu'on ne peut pas trancher doit dire où on la tranche.

    Le tableau « Proposals » est la seule chose du cockpit qui ressemble à une
    file d'attente. Sans un mot, elle se lit comme le rituel hebdomadaire que
    quatre documents décrivent — un rituel que le cockpit ne peut pas servir :
    il n'a aucune route d'écriture. (Le geste, lui, existe : il est à l'API,
    et c'est ce que la page doit nommer.)

    Le contrôle porte sur le HTML RENDU, pas sur le code : c'est ce que le
    lecteur voit qui doit dire la vérité.
    """
    r = cockpit.get("/cc/brain", follow_redirects=False)
    assert r.status_code == 200, r.status_code
    page = r.text
    assert "p-1" in page, "la file de propositions n'est pas rendue"
    assert 'class="absence limite"' in page, (
        "la file est affichée sans dire que le cockpit ne peut pas la trancher")
    assert "ne les tranche pas" in page, (
        "la page ne dit pas que le cockpit lit sans trancher")
    # Une limite n'est pas une absence : la file EST pleine. Le gabarit ne doit
    # donc pas promettre « ce qui la remplirait », mais nommer l'endroit du geste.
    assert "Où le geste se fait" in page and "/v1/atoms" in page, (
        "la page ne dit pas OÙ le geste se fait réellement")


# ============================================================================
# Un geste servi doit désigner quelque chose qui existe
# ============================================================================


def test_aucun_geste_ne_renvoie_a_un_chantier_introuvable():
    """« persister le NRB en base (chantier moteur B11) » : B11 n'est nulle part.

    Un geste de déblocage qui cite un identifiant de chantier privé est
    inactionnable par définition : le lecteur ne peut ni l'ouvrir, ni savoir
    ce qu'il contient. Le geste doit dire QUOI faire, pas dans quel registre
    c'est écrit.
    """
    from control_center.cc_v1 import registry

    renvoi = re.compile(r"\b(chantier|lot|ticket|registre)\s+\w*\s*[A-Z]-?\d{1,3}\b|"
                        r"\bchantier\s+\w+\s+[A-Z]\d{1,2}\b", re.I)
    fautifs = [
        f"{m.key}: {m.unavailable_gesture}"
        for m in registry.REGISTRY
        if m.unavailable_gesture and renvoi.search(m.unavailable_gesture)
    ]
    assert not fautifs, (
        "Un geste renvoie à un chantier que le lecteur ne peut pas ouvrir.\n  "
        + "\n  ".join(fautifs))


def test_aucune_revision_de_migration_servie_n_est_inventee():
    """Nommer une révision, c'est promettre qu'on peut aller la lire.

    Le cockpit a servi « migration 0033_atom_links non appliquée » (une
    révision réelle, mais un état qu'il n'avait pas regardé), puis
    « head prod 0019 » (la tête de la chaîne d'UNE installation, servie comme
    la cause d'une absence constatée chez le lecteur). Les deux envoyaient
    chercher quelque chose qui n'était pas là.

    La règle : toute révision citée dans un texte servi doit exister dans
    ``db/alembic/versions/``. Une révision qu'on peut ouvrir est une
    information ; un numéro qui ne correspond à rien est du bruit qui inquiète.
    """
    revisions = {f.stem for f in (RACINE / "db" / "alembic" / "versions").glob("*.py")}
    numeros = {r.split("_", 1)[0] for r in revisions}
    cite = re.compile(r"\b(?:head|migration|r[ée]vision)\s+(?:prod\s+)?(\d{3,4})(_[a-z_]+)?", re.I)
    fautifs: list[str] = []
    for p, ln, texte in MOISSON:
        for m in cite.finditer(texte):
            numero, suffixe = m.group(1), m.group(2)
            nom = f"{numero}{suffixe}" if suffixe else None
            if nom is not None and nom not in revisions:
                fautifs.append(f"{p.relative_to(RACINE)}:{ln} — révision inconnue « {nom} »")
            elif nom is None and numero not in numeros:
                fautifs.append(f"{p.relative_to(RACINE)}:{ln} — numéro de révision "
                               f"inconnu « {numero} »")
    assert not fautifs, (
        "Un texte servi nomme une révision de migration que le lecteur ne "
        "trouvera pas dans db/alembic/versions/.\n  " + "\n  ".join(fautifs))

    # Et surtout : la TÊTE de chaîne du lecteur ne se devine pas. Elle vit dans
    # `alembic_version`, que le cockpit n'interroge nulle part. « head prod
    # 0019 » servait la tête d'une installation comme la cause d'une absence
    # constatée chez quelqu'un d'autre : le constat était juste, la cause
    # inventée. Nommer une tête est donc interdit, quelle qu'elle soit.
    tete = re.compile(r"\bhead\s+(?:prod\s+)?\d{3,4}", re.I)
    tetes = [f"{p.relative_to(RACINE)}:{ln} — « {' '.join(texte.split())[:120]} »"
             for p, ln, texte in MOISSON if tete.search(texte)]
    assert not tetes, (
        "Un texte servi affirme la tête de la chaîne Alembic du lecteur, qu'il "
        "n'a pas interrogée.\n  " + "\n  ".join(tetes))


# ============================================================================
# Le registre lui-même ne perd rien en silence
# ============================================================================


@pytest.mark.parametrize("famille", [
    "etat_general", "aujourdhui", "confiance", "vues", "memoire",
    "croissance", "pipeline", "digestion", "rappel", "projets",
])
def test_le_registre_charge_ses_familles_quel_que_soit_l_ordre_d_import(famille):
    """Une famille escamotée est une page vide qui ne dit pas pourquoi.

    ``Metric`` vivait dans ``registry.py`` et les familles l'importaient de là,
    pendant que le registre importait les familles : un cycle. Quand une
    famille était importée EN PREMIER — ce que fait
    ``tests/test_cc_v1_preuve_complete.py`` — le registre la retrouvait à
    moitié initialisée, n'y voyait pas de ``METRICS``, et continuait sans un
    mot : 130 métriques au lieu de 148, les dix-huit du panneau
    « Aujourd'hui » disparues, ``LOAD_ERRORS`` vide.

    Le test importe la famille AVANT le registre, dans un interpréteur neuf, et
    exige que le registre soit complet et muet d'erreurs. Il tombe si quelqu'un
    remet ``Metric`` dans le module qui dépend des familles.
    """
    import subprocess
    import sys

    code = (
        f"import control_center.cc_v1.families.{famille}\n"
        "from control_center.cc_v1 import registry\n"
        "familles = sorted({m.domain for m in registry.REGISTRY})\n"
        "print(len(registry.REGISTRY), registry.LOAD_ERRORS, familles)\n"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=RACINE,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    total, reste = r.stdout.split(" ", 1)
    assert reste.startswith("{}"), (
        f"le registre déclare des erreurs de chargement quand `{famille}` est "
        f"importée d'abord : {reste}")
    assert int(total) == _TAILLE_ATTENDUE, (
        f"le registre perd des métriques quand `{famille}` est importée "
        f"d'abord : {total} au lieu de {_TAILLE_ATTENDUE}")


#: La taille du registre, mesurée dans l'ordre d'import nominal. Ce n'est pas un
#: seuil de qualité — c'est le témoin : toutes les familles doivent produire le
#: MÊME registre quel que soit l'ordre où on les importe.
def _taille_nominale() -> int:
    from control_center.cc_v1 import registry

    return len(registry.REGISTRY)


_TAILLE_ATTENDUE = _taille_nominale()


@pytest.mark.parametrize("cle", ["vital_connectivity", "pipeline_graph_stage_installed",
                                 "today_links_created", "view_graph_orphans"])
def test_chaque_metrique_de_liens_porte_une_preuve_rejouable(cle):
    """La doctrine qui doit survivre à la correction : la preuve reste.

    Rendre un texte conditionnel ne doit pas coûter sa preuve SQL. Chacune de
    ces quatre métriques parle de ``arac.atom_links`` ; chacune doit dire, en
    SQL rejouable, ce qu'elle a regardé.
    """
    from control_center.cc_v1 import registry

    m = registry.by_key(cle)
    assert m.evidence_sql and "select" in m.evidence_sql.lower()
    assert "to_regclass" in (m.sql or "") + (m.evidence_sql or ""), (
        f"{cle} parle de la table sans jamais la sonder")
