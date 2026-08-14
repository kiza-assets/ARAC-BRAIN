"""G4 — TOUT GESTE QUE LE PRODUIT PRESCRIT EST SERVI PAR LE PRODUIT.

CE QUE CE GARDE MESURE, EN UNE PHRASE
=====================================
Un texte que le PROGRAMME imprime — l'écran de fin du bootstrap, un refus, un
remède, la sortie d'un contrôle, le message d'un agent — ne peut pas demander
un geste que le produit ne sert pas. Chaque geste prescrit doit se rattacher à
une capacité RÉELLE : une route servie, une commande qui existe, un fichier
qui existe.

LE DÉFAUT QU'IL EXISTE POUR EMPÊCHER — il a coûté six manches
=============================================================
L'écran de fin de `bootstrap.sh` — celui que l'ami lit juste après avoir
obtenu son cerveau, au moment où il a le plus confiance, et le seul texte de
tout le parcours que personne ne peut sauter — portait ceci :

    ◆ 98 % du savoir jamais audité
      Prenez l'habitude, une fois par semaine, d'ouvrir le cockpit et de
      trancher quelques propositions.
      — le cockpit n'a **aucune route d'écriture** : ce geste n'existe pas.

    ◆ 96 % des rappels rendus en confiance basse
      La calibration compte autant que la recherche, et elle s'améliore quand
      vous validez ou corrigez ce qu'il propose — dans le cockpit.
      — le cockpit ne valide rien : cet effet est impossible PAR LÀ.

Le cockpit n'a aucune route d'écriture : sa seule méthode mutatrice est
`POST /cc/login`, qui pose un cookie. Le geste était donc
impossible, et son prix est nommé dans `control_center/app.py` : « un lecteur
à qui la documentation a promis “ouvrez votre cockpit chaque semaine et
tranchez quelques propositions” arrive ici, cherche le bouton, et conclut que
quelque chose est cassé chez lui. »

La correction avait atteint cinq documents. Elle n'avait pas atteint
l'INSTALLATEUR.

ET LA CORRECTION ELLE-MÊME PORTAIT SA PROPRE FAUSSETÉ — la manche suivante l'a
mesurée. La phrase de remplacement disait « `confidence` est immuable : absente
du PATCH, recopiée par la supersédure ». C'est vrai du NIVEAU déclaré
(`confidence`) et de la trace d'audit (`audit_source`), qui rendent `422
extra_forbidden`. C'est FAUX du CHIFFRE : `confidence_score` est dans
`AtomUpdate`, `new_confidence_score` dans `AtomSupersede`, et un `PATCH
{"confidence_score": 95}` sur un atome à 40 rend 200. Ce garde-ci avait été
ENTRAÎNÉ sur la phrase fausse — elle figurait dans `GESTES_SERVIS` comme « la
seule forme qui enseigne ». Un garde qu'on entraîne sur un faux exemple le
protège au lieu de l'attraper ; l'entrée nomme désormais le niveau déclaré, qui
est bien ce dont on ne peut rien faire.

POURQUOI UN GARDE DE PLUS, ET PAS UNE RÈGLE DE PLUS AILLEURS
=============================================================
`tests/test_la_doc_dit_vrai.py` portait DÉJÀ le motif qui attrape la phrase
(`tranch(?:er|ez)[^.\\n]{0,60}proposition`), et il balayait DÉJÀ tout ce que
`git` transporte, `bootstrap/lib/verify.sh` compris. Il n'a rien vu. La cause
est dans sa définition de la prose : hors Markdown, `_prose()` ne garde que
les **commentaires** et les **docstrings** — c'est-à-dire ce que le
développeur se dit à lui-même. **Ce que le programme dit à l'utilisateur
n'était dans aucun corpus.**

Élargir `_prose()` aurait été le geste court, et c'est ce qu'on avait proposé.
On ne l'a pas fait, et pas par goût : **on l'a mesuré**. Les sept règles de
`test_la_doc_dit_vrai.py`, appliquées telles quelles aux 2 101 écrans extraits
ici, rendent **dix reproches, dont dix sont faux** :

  · règles 1, 2, 3, 4 et 6 : zéro reproche — elles auraient tenu ;
  · règle 5 (« un réglage que le bootstrap refuse ») : **neuf** reproches,
    tous sur `$ARAC_SCHEMA` employé comme VARIABLE dans une chaîne
    interpolée — `dire "  base $ARAC_DB (schéma $ARAC_SCHEMA)"`. La règle lit
    une recommandation là où il n'y a qu'un nom de variable ;
  · règle 7 (« la boucle locale n'est plus exemptée ») : **un** reproche, sur
    `bootstrap/checks/verify_install.sh:890`, qui déclare pourtant la posture
    morte — « ce défaut ne se voyait pas tant que la boucle locale était
    exemptée ». La forme du démenti n'est pas dans sa liste de marqueurs.

Dix reproches faux, c'est un `make test` rouge le jour de l'élargissement, et
c'est la conduite qui suit : on désarme la règle. Le dépôt l'a écrit lui-même,
à propos du mot « recalibrer » — « une règle qui reproche un vocabulaire finit
désarmée à la première gêne ». Ce qu'un programme imprime n'a pas la forme
d'un paragraphe de prose : c'est un fragment, souvent assemblé, souvent un
gabarit, souvent une variable. Il lui faut ses propres règles.

Ce garde-ci pose donc une question DIFFÉRENTE, adaptée à la matière : non pas
« cette phrase est-elle exacte ? » mais « ce geste a-t-il un organe ? ». Il ne
juge pas le style, il **résout** : chaque geste prescrit doit tomber sur une
route, une commande ou un fichier qui existe — et quand il ne tombe sur rien,
il le dit avec le nom de ce qui manque.

Division du travail, écrite pour qu'elle ne dérive pas :
  · Markdown  → `tests/test_la_doc_dit_vrai.py` (la doc dit-elle vrai ?)
  · commandes libpq imprimées → `tests/test_g3_...` (portent-elles leur port ?)
  · **ce que le programme imprime** → ici (le geste est-il servi ?)

LES TROIS RÈGLES, ET POURQUOI ELLES SONT DE CETTE FORME
========================================================
RÈGLE A — LE GESTE QUI EXIGE UN ORGANE.
    Un verbe de MUTATION adressé au lecteur (« validez », « tranchez »,
    « cochez », « promouvez »…) rencontré dans le même écran qu'un ORGANE
    nommé (le cockpit, une proposition, la confiance) : l'organe doit
    réellement servir l'écriture. Chaque organe a une prémisse **lue dans le
    produit**, jamais recopiée — la table de routage réelle, les champs réels
    des schémas. Le jour où le cockpit gagne une route d'écriture, c'est la
    prémisse qui tombe la première, et son message dit quoi relire.

    Comme partout dans ce dépôt, la règle n'interdit pas un mot : elle exige
    qu'il voyage avec sa contrepartie. Un écran qui NOMME le geste absent en
    disant, dans le même écran, qu'il est absent — c'est la seule façon
    d'enseigner la leçon — passe.

RÈGLE B — LE GESTE QUI DÉSIGNE SA CIBLE.
    « lancez `make scopes` », « ouvrez `config/scopes.toml` », « relancez
    `ops/install_check.sh` » : la cible nommée doit exister. Une cible morte
    n'est pas une faute de style, c'est un cul-de-sac imprimé au pire moment.
    Cette règle n'a besoin d'aucune liste de verbes : elle résout tout ce qui
    a la FORME d'une cible.

RÈGLE C — LA ROUTE CITÉE.
    Un chemin `/v1/...` ou `/cc/...` imprimé doit être servi par
    l'application. La table de routage est lue dans le produit ; les
    paramètres sont normalisés, parce que `{id}` et `{atom_id}` désignent la
    même route et qu'un lecteur ne peut pas le deviner.

CE QUE CE GARDE NE COUVRE PAS — voir `ZONES_NON_COUVERTES_G4`, imprimé en fin
de session. Un garde qui ne dit pas où s'arrête sa vue donne une confiance
qu'il ne mérite pas, et la confiance est ce qui empêche de regarder.

Hors-ligne : ce module lit des fichiers, importe deux schémas et construit les
deux applications en mémoire pour lire leur table de routage. Aucune base,
aucun service, aucun réseau.
"""

from __future__ import annotations

import ast
import functools
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

# On réutilise le corpus de G1 et les marqueurs du garde documentaire plutôt
# que de les recopier : deux listes qui se ressemblent finissent par diverger,
# et le jour où elles divergent, personne ne sait laquelle des deux ment.
from tests.test_g1_aucun_nom_partage_entre_cerveaux import _fichiers_balayes
from tests.test_g3_toute_commande_imprimee_porte_son_port import (
    APPELS_DE_SORTIE,
    FONCTIONS_DE_SORTIE_SHELL,
    _DOC_EN_LIGNE,
    _est_du_shell,
    _nom_appele,
)
from tests.test_la_doc_dit_vrai import MARQUEURS_D_ABSENCE, _a_plat

RACINE = Path(__file__).resolve().parent.parent

#: Ce qu'on écoute côté Python : ce que G3 écoute déjà, plus les réponses HTTP.
_APPELS_ECOUTES = frozenset(APPELS_DE_SORTIE) | {
    "JSONResponse", "PlainTextResponse", "HTTPException",
}


# ===========================================================================
# CE QUE LE PRODUIT IMPRIME
# ===========================================================================

#: Les fonctions par lesquelles le bootstrap PARLE, en plus de celles que G3
#: écoute déjà. Elles vivent dans `bootstrap/lib/ui.sh` — c'est la voix de
#: l'installation, et c'est très exactement le texte qui manquait à tous les
#: corpus : `lecon`, la fonction qui portait le geste impossible, n'était
#: écoutée par personne.
FONCTIONS_DE_L_ECRAN = (
    "lecon", "cmd", "bien", "mal", "alerte", "action", "sous_titre",
    "titre", "banniere", "etape_entete", "echec", "note", "dire",
)

#: Une application web parle par ses RÉPONSES. `raise HTTPException(detail=…)`
#: était déjà lu — c'est un `raise`. `return JSONResponse(content={"error": …})`
#: ne l'était pas, et c'est là qu'on a trouvé la seconde prescription
#: impossible du dépôt : le 503 du cockpit non provisionné renvoyait à
#: `scripts/control_center/provision_admin.py`, qui n'existe nulle part.
#: `HTMLResponse` reste dehors : une page entière n'est pas une phrase
#: adressée, et la balayer noierait les constats sous du gabarit.
REPONSES_QUI_PARLENT = ("JSONResponse", "PlainTextResponse", "HTTPException")

_NOMS_SHELL = tuple(sorted(
    set(FONCTIONS_DE_SORTIE_SHELL) | set(FONCTIONS_DE_L_ECRAN),
    key=len, reverse=True,
))

#: L'appel de sortie, y compris **en continuation** (`|| bad "…"`,
#: `&& warn "…"`). Ce dépôt écrit la plupart de ses remèdes sous cette forme :
#: un motif ancré en tête de ligne n'en voit aucun.
_APPEL_DE_SORTIE_SH = re.compile(
    r"^\s*(?:(?:\|\||&&|;)\s*)?(?:local\s+\w+=)?(?:sudo\s+)?(?:"
    + "|".join(re.escape(n) for n in _NOMS_SHELL)
    + r")\b"
)


@dataclass(frozen=True)
class Ecran:
    """Un texte imprimé d'un seul tenant — c'est l'unité de lecture.

    Une leçon de l'installateur, un refus, un remède : le lecteur les
    rencontre d'un bloc, et c'est donc dans ce bloc qu'une prescription et
    son démenti doivent se tenir. Découper plus fin ferait reprocher au dépôt
    une phrase qu'il corrige deux lignes plus bas ; découper plus large
    laisserait la nuance d'un écran couvrir la fausseté d'un autre.
    """

    fichier: str
    ligne: int
    texte: str

    def __str__(self) -> str:
        return f"{self.fichier}:{self.ligne}"


def _fin_de_commande(ligne: str, guillemet: str | None) -> tuple[str | None, bool]:
    """L'état de guillemet à la fin de cette ligne, et si la commande continue.

    Une chaîne shell peut traverser des dizaines de lignes — c'est le cas de
    chaque `lecon` du bootstrap — et une continuation par `\\` en traverse
    d'autres. Un extracteur qui ne suit ni l'une ni l'autre voit la ligne
    d'appel et rien du texte : c'est pour cette raison exacte que le geste
    impossible a survécu à un garde qui avait pourtant le bon motif.
    """
    i = 0
    while i < len(ligne):
        c = ligne[i]
        if guillemet is None:
            if c == "\\":
                i += 2
                continue
            if c in "\"'":
                guillemet = c
            elif c == "#":
                break
        elif c == guillemet:
            guillemet = None
        elif guillemet == '"' and c == "\\":
            i += 2
            continue
        i += 1
    return guillemet, guillemet is not None or ligne.rstrip().endswith("\\")


def ecrans_shell(p: Path) -> list[Ecran]:
    """Les blocs qu'un script fait s'afficher, un par appel de sortie."""
    rel = str(p.relative_to(RACINE)) if p.is_relative_to(RACINE) else str(p)
    lignes = p.read_text(encoding="utf-8", errors="replace").splitlines()
    ecrans: list[Ecran] = []
    courant: list[str] = []
    debut = 0
    guillemet: str | None = None
    fin_doc: str | None = None

    def clore() -> None:
        nonlocal courant
        if courant:
            ecrans.append(Ecran(rel, debut, "\n".join(courant)))
            courant = []

    for i, l in enumerate(lignes, start=1):
        if fin_doc is not None:
            if l.strip() == fin_doc:
                fin_doc = None
                clore()
            else:
                courant.append(l)
            continue
        if courant:
            courant.append(l)
            guillemet, continue_ = _fin_de_commande(l, guillemet)
            if not continue_:
                clore()
            continue
        if not _APPEL_DE_SORTIE_SH.match(l):
            continue
        debut = i
        courant = [l]
        m = _DOC_EN_LIGNE.search(l)
        if m:
            fin_doc = m.group(1)
            guillemet = None
            continue
        guillemet, continue_ = _fin_de_commande(l, None)
        if not continue_:
            clore()
    clore()
    return ecrans


def ecrans_python(p: Path) -> list[Ecran]:
    """Les chaînes qu'un `raise` ou un appel de sortie fait sortir du programme.

    Un écran = un appel : les fragments d'un même `raise` sont recollés, parce
    que c'est ainsi que le lecteur les reçoit — d'un bloc, sur son terminal.
    """
    rel = str(p.relative_to(RACINE)) if p.is_relative_to(RACINE) else str(p)
    try:
        arbre = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, ValueError):
        return []
    ecrans: list[Ecran] = []
    for n in ast.walk(arbre):
        if isinstance(n, ast.Raise) and n.exc is not None:
            racines: list[ast.AST] = [n.exc]
        elif isinstance(n, ast.Call) and _nom_appele(n) in _APPELS_ECOUTES:
            racines = list(n.args) + [k.value for k in n.keywords]
        else:
            continue
        morceaux: list[str] = []
        for r in racines:
            for c in ast.walk(r):
                if isinstance(c, ast.Constant) and isinstance(c.value, str):
                    morceaux.append(c.value)
        if morceaux:
            ecrans.append(Ecran(rel, getattr(n, "lineno", 1), "\n".join(morceaux)))
    return ecrans


def ecrans(p: Path) -> list[Ecran]:
    if p.suffix == ".py":
        return ecrans_python(p)
    if _est_du_shell(p):
        return ecrans_shell(p)
    return []


@functools.lru_cache(maxsize=1)
def tous_les_ecrans() -> tuple[Ecran, ...]:
    return tuple(e for p in _fichiers_balayes() for e in ecrans(p))


# ===========================================================================
# LES CAPACITÉS RÉELLES — lues dans le produit, jamais recopiées
# ===========================================================================


@functools.lru_cache(maxsize=1)
def routes_servies() -> frozenset[tuple[str, str]]:
    """La table de routage des DEUX applications, lue dans le produit.

    Les paramètres sont normalisés (`{atom_id}` → `{}`) : `/v1/atoms/{id}` et
    `/v1/atoms/{atom_id}` désignent la même route, et personne n'écrit à la
    main le nom de variable qu'un développeur a choisi.
    """
    couples: set[tuple[str, str]] = set()

    from app.main import app as api

    for chemin, methodes in api.openapi()["paths"].items():
        for methode in methodes:
            couples.add((methode.upper(), _normalise_route(chemin)))

    from control_center.app import create_app

    for route in create_app().routes:
        chemin = getattr(route, "path", None)
        if not chemin:
            continue
        for methode in getattr(route, "methods", None) or ["GET"]:
            couples.add((methode.upper(), _normalise_route(chemin)))
    return frozenset(couples)


_PARAMETRE = re.compile(r"\{[^}]*\}")


def _normalise_route(chemin: str) -> str:
    chemin = _PARAMETRE.sub("{}", chemin)
    return chemin.rstrip("/") or "/"


@functools.lru_cache(maxsize=1)
def cibles_make() -> frozenset[str]:
    """Les cibles que le `Makefile` sert réellement."""
    source = (RACINE / "Makefile").read_text(encoding="utf-8", errors="replace")
    return frozenset(re.findall(r"^([A-Za-z][A-Za-z0-9_-]*)\s*:", source, re.MULTILINE))


@functools.lru_cache(maxsize=1)
def fichiers_servis() -> frozenset[str]:
    """Ce qu'un lecteur trouvera réellement sur son disque.

    Le dépôt, PLUS ce que l'installation engendre : `config/scopes.toml` n'est
    pas versionné et existe pourtant chez tout le monde après l'entretien.
    La liste des engendrés est importée du garde F1 — elle y est déjà tenue à
    jour, et deux listes qui se ressemblent divergent.
    """
    from tests.test_f1_aucune_trace_de_l_auteur import ENGENDRES

    depot = {
        str(p.relative_to(RACINE))
        for p in _fichiers_balayes()
        if p.is_relative_to(RACINE)
    }
    return frozenset(depot | set(ENGENDRES))


def _confiance_est_modifiable() -> bool:
    from app.schemas.atom import AtomSupersede, AtomUpdate

    return (
        "confidence" in AtomUpdate.model_fields
        or "new_confidence" in AtomSupersede.model_fields
    )


def _audit_est_modifiable() -> bool:
    from app.schemas.atom import AtomSupersede, AtomUpdate

    return (
        "audit_source" in AtomUpdate.model_fields
        or "new_audit_source" in AtomSupersede.model_fields
    )


def _cockpit_ecrit() -> bool:
    """Le cockpit sert-il un geste d'écriture ?

    La connexion ne compte pas, et la nuance est due : `POST /cc/login` est
    une route mutatrice, mais elle pose un cookie signé et n'écrit ni en base
    ni dans la mémoire. La formule ronde « le cockpit n'a aucune route
    d'écriture » se fait démentir par le premier lecteur qui ouvre le fichier ;
    celle-ci tient.
    """
    return any(
        methode not in ("GET", "HEAD", "OPTIONS") and chemin != "/cc/login"
        for methode, chemin in routes_servies()
        if chemin.startswith("/cc")
    )


def _propositions_se_tranchent() -> bool:
    """Existe-t-il une route qui DÉCIDE d'une proposition ?

    `/v1/brain/proposals` les liste. Trancher voudrait dire écrire — c'est
    cette route-là qu'on cherche, dans les deux applications.
    """
    return any(
        methode not in ("GET", "HEAD", "OPTIONS") and "proposal" in chemin
        for methode, chemin in routes_servies()
    )


@dataclass(frozen=True)
class Organe:
    """Une capacité que le produit pourrait avoir — et la mesure qui le dit.

    `mesure` est lue DANS le produit à chaque passage. C'est ce qui distingue
    ce garde d'une opinion recopiée : le jour où l'organe naît, la prémisse
    devient vraie toute seule, la règle se tait toute seule, et les textes
    peuvent enfin prescrire le geste.
    """

    nom: str
    designation: str          # ce qui, dans un écran, NOMME cet organe
    mesure: object            # Callable[[], bool]
    ce_qui_manque: str

    @property
    def rx(self) -> re.Pattern[str]:
        return re.compile(self.designation, re.IGNORECASE)

    def sert(self) -> bool:
        return bool(self.mesure())          # type: ignore[operator]


ORGANES: tuple[Organe, ...] = (
    Organe(
        "le cockpit",
        r"\bcockpit\b",
        _cockpit_ecrit,
        "le cockpit n'a aucune route d'écriture — sa seule méthode mutatrice "
        "est POST /cc/login, qui pose un cookie et n'écrit ni en base ni dans "
        "la mémoire. Son rôle PostgreSQL ouvre d'ailleurs toutes ses "
        "transactions en lecture seule.",
    ),
    Organe(
        "la décision sur une proposition",
        r"\bpropositions?\b",
        _propositions_se_tranchent,
        "aucune route ne DÉCIDE d'une proposition : `/v1/brain/proposals` les "
        "liste, et rien ne les tranche. Le lecteur cherche le bouton, ne le "
        "trouve pas, et conclut que son installation est cassée.",
    ),
    Organe(
        "le NIVEAU de confiance d'un atome",
        r"\b(?:confiance|calibration)\b",
        _confiance_est_modifiable,
        "le NIVEAU déclaré — `confidence`, c'est-à-dire "
        "producer / agent_suggest / auditor_validated — est absent "
        "d'`AtomUpdate` (donc du PATCH, qui rend 422 extra_forbidden) et la "
        "supersédure le RECOPIE de l'atome remplacé (`old[\"confidence\"]`). "
        "AUCUNE VALIDATION NE LE PROMEUT. Attention à ne pas en tirer la "
        "formule courte : le CHIFFRE `confidence_score`, lui, est servi et "
        "modifiable — `PATCH {\"confidence_score\": 95}` rend 200, mesuré. "
        "C'est la confusion des deux qui a fait imprimer « la confiance d'un "
        "atome est IMMUABLE » pendant sept manches.",
    ),
    Organe(
        "le marquage d'un savoir comme vérifié",
        r"\baudit(?:é|ée|er|ez)\b|\bauditor_validated\b",
        _audit_est_modifiable,
        "`audit_source` est absent du schéma de modification et hérité par la "
        "supersédure : aucun chemin servi ne marque un savoir comme vérifié.",
    ),
)


# ===========================================================================
# RÈGLE A — LE GESTE QUI EXIGE UN ORGANE
# ===========================================================================

#: Les verbes par lesquels on demande au lecteur de CHANGER quelque chose.
#: La liste est courte et fermée : un verbe de lecture (« regardez »,
#: « lisez ») est toujours servi, et l'y mettre ferait crier le garde sur des
#: phrases justes. Les formes retenues sont l'impératif (« validez ») et
#: l'infinitif (« valider »), parce que le dépôt prescrit des deux façons —
#: « prenez l'habitude de trancher » est un impératif déguisé.
_GESTE_DE_MUTATION = re.compile(
    r"\b(?:valid(?:ez|er)|tranch(?:ez|er)|arbitr(?:ez|er)|approuv(?:ez|er)"
    r"|rejet(?:ez|er)|promouv(?:ez|oir)|coch(?:ez|er)|cliqu(?:ez|er)"
    r"|confirm(?:ez|er)|recalibr(?:ez|er)|marqu(?:ez|er))\b",
    re.IGNORECASE,
)


def gestes_sans_organe(texte: str) -> list[str]:
    """Les gestes que cet écran prescrit et que le produit ne sert pas.

    Fonction PURE : elle prend un texte et rend des constats. C'est ce qui
    permet de l'éprouver sur la phrase exacte qui a coûté six manches, sans
    rien installer — voir `test_le_garde_voit_le_geste_impossible`.

    L'UNITÉ DE LECTURE EST LE PARAGRAPHE, ET CE N'ÉTAIT PAS LE CAS. Cette
    fonction écrasait l'écran ENTIER d'un coup de `_a_plat`, puis rendait `[]`
    dès qu'un marqueur d'absence — « immuable », « lecture seule »,
    « impossible » — paraissait N'IMPORTE OÙ dedans. Un écran de trente lignes
    était donc exempté en entier par un seul mot, écrit trois paragraphes plus
    bas, à propos d'autre chose.

    Ce n'est pas une hypothèse : on l'a MESURÉ en remettant le rituel
    hebdomadaire — « ouvrez le cockpit et tranchez quelques propositions » — en
    tête de la leçon « 96 % des rappels ». Le garde est resté VERT, parce que
    la même leçon dit plus bas que le NIVEAU déclaré est immuable. C'est-à-dire
    que le garde écrit pour attraper cette phrase-là ne l'attrapait pas, et
    qu'il ne l'aurait jamais attrapée : le mot qui le désarmait faisait partie
    de la CORRECTION.

    `tests/test_la_doc_dit_vrai.py` avait déjà nommé la règle, pour les
    documents : « une unité est un paragraphe — c'est là qu'une affirmation et
    sa nuance se tiennent, ou pas ; traiter un tableau comme un seul bloc
    laisserait la nuance d'une ligne couvrir la fausseté d'une autre ». C'est
    le même défaut, sur l'autre corpus, et c'est le même remède.

    Ce qui reste à l'échelle de l'ÉCRAN, délibérément : la rencontre du geste
    et de l'ORGANE. « Ouvrez le cockpit », puis, deux paragraphes plus bas,
    « et tranchez » — c'est une prescription, et le lecteur la reçoit d'un
    bloc. Seule l'EXEMPTION se resserre.
    """
    plat_entier = _a_plat(texte)
    constats: list[str] = []
    deja: set[str] = set()
    for paragraphe in re.split(r"\n\s*\n", texte):
        plat = _a_plat(paragraphe)
        if not plat:
            continue
        if any(m in plat.lower() for m in MARQUEURS_D_ABSENCE):
            continue  # CE paragraphe-ci déclare l'absence : il enseigne.
        geste = _GESTE_DE_MUTATION.search(plat)
        if not geste:
            continue
        for organe in ORGANES:
            if organe.rx.search(plat_entier) and not organe.sert():
                constat = (f"« {geste.group(0)} » demandé sur {organe.nom} — "
                           f"{organe.ce_qui_manque}")
                if constat not in deja:
                    deja.add(constat)
                    constats.append(constat)
    return constats


# ===========================================================================
# RÈGLE B — LE GESTE QUI DÉSIGNE SA CIBLE
# ===========================================================================

#: Ce qui a la forme d'un fichier du dépôt. Le `(?<![\w./-])` de tête écarte
#: les chemins ABSOLUS (`/etc/arac/…`, `/var/backups/…`) : ceux-là naissent de
#: l'installation, pas du dépôt, et exiger qu'ils existent reviendrait à
#: exiger que la machine du test soit une machine installée.
_CIBLE_FICHIER = re.compile(
    r"(?<![\w./-])((?:\./)?(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+"
    r"\.(?:sh|py|md|toml|sql|service|timer|template|example|txt|conf|yml|yaml|ini|json))"
)
_CIBLE_MAKE = re.compile(r"\bmake\s+([a-z][a-z0-9_-]*)")

#: Le nom d'une VARIABLE en tête de chemin (`$ARAC_HOME/config/brain.toml`).
#: Le `$` n'entre pas dans le motif ci-dessus, si bien que la variable se
#: retrouve capturée comme un répertoire. On la retire : ce qui est désigné,
#: c'est le chemin DANS le dépôt.
_VARIABLE_EN_TETE = re.compile(r"^(?:[A-Z_][A-Z0-9_]*/)+")


@functools.lru_cache(maxsize=1)
def _racines_du_depot() -> frozenset[str]:
    """Les répertoires de premier niveau du dépôt.

    Ils servent à décider si un chemin imprimé PRÉTEND désigner un fichier du
    dépôt. `db/seeds/scopes.sql` le prétend ; `arac/export-desktop/x.json`,
    écrit sous un répertoire de travail décidé à l'exécution, non — et le
    réclamer reviendrait à exiger qu'un dossier temporaire existe dans le
    clone.
    """
    return frozenset(p.name for p in RACINE.iterdir() if p.is_dir())


def cibles_absentes(texte: str) -> list[str]:
    """Les fichiers et les cibles `make` que cet écran nomme et qui n'existent pas."""
    constats = []
    for m in _CIBLE_FICHIER.finditer(texte):
        brut = m.group(1)
        brut = brut[2:] if brut.startswith("./") else brut
        chemin = _VARIABLE_EN_TETE.sub("", brut)
        if not chemin or any(c in chemin for c in "<>*{}%$"):
            continue
        if chemin.split("/")[0] not in _racines_du_depot():
            continue
        if chemin in fichiers_servis() or (RACINE / chemin).exists():
            continue
        constats.append(
            f"« {chemin} » nommé à l'écran, absent du dépôt et de ce que "
            "l'installation engendre"
        )
    for m in _CIBLE_MAKE.finditer(texte):
        if m.group(1) not in cibles_make():
            constats.append(
                f"« make {m.group(1)} » nommé à l'écran, absent du Makefile"
            )
    return constats


# ===========================================================================
# RÈGLE C — LA ROUTE CITÉE
# ===========================================================================

_CITATION_DE_ROUTE = re.compile(
    r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/(?:v1|cc)[A-Za-z0-9_/{}.-]*)"
)

#: LA FORME QUE CE GARDE NE VOYAIT PAS — éprouvé, pas supposé.
#:
#: `routes_absentes` n'a jamais reconnu qu'une seule écriture : « MÉTHODE
#: /chemin ». Or la façon dont un écran montre une route à quelqu'un qui doit
#: la taper, c'est une commande complète :
#:
#:     curl -X POST http://127.0.0.1:8000/v1/atoms/valider
#:
#: Remis dans `bootstrap/lib/verify.sh` le 9 août 2026, le garde a rendu
#: « 20 passed ». La même route écrite « POST /v1/atoms/valider » le faisait
#: rougir. Le corpus imprimé n'en contenait alors AUCUNE — la faute était
#: latente, pas active ; c'est le bon moment pour la fermer.
#:
#: Deux prudences, apprises de ce qu'un écran écrit vraiment :
#:   · l'hôte et le port sont ignorés (ils viennent d'une variable) ;
#:   · sans `-X`, curl fait un GET : on ne devine pas, on le sait.
_CURL_VERS_UNE_ROUTE = re.compile(
    r"curl\b[^\n|;]*?(?:-X\s+(GET|POST|PUT|PATCH|DELETE)\b[^\n|;]*?)?"
    r"https?://[^\s'\"`]*?(/(?:v1|cc)[A-Za-z0-9_/{}.-]*)"
)


def _routes_citees(texte: str) -> list[tuple[str, str]]:
    """(méthode, chemin) pour les deux écritures reconnues."""
    citees = list(_CITATION_DE_ROUTE.findall(texte))
    for methode, chemin in _CURL_VERS_UNE_ROUTE.findall(texte):
        citees.append((methode or "GET", chemin))
    return citees


def routes_absentes(texte: str) -> list[str]:
    """Les routes citées avec leur méthode et que l'application ne sert pas.

    On n'exige la méthode que lorsqu'elle est ÉCRITE : un chemin cité seul,
    au fil d'une phrase, ne dit pas comment on l'appelle, et le reprocher
    reviendrait à interdire d'en parler. La seule exception est `curl`, où
    l'absence de `-X` n'est pas un silence : c'est un GET.
    """
    constats = []
    for methode, chemin in _routes_citees(texte):
        normalise = _normalise_route(chemin)
        if (methode.upper(), normalise) in routes_servies():
            continue
        if any(c in chemin for c in "<>"):
            continue
        constats.append(
            f"« {methode} {chemin} » cité à l'écran : l'application ne sert "
            "pas cette route"
        )
    return constats


# ===========================================================================
# LE BALAYAGE
# ===========================================================================


def balayage_g4() -> list[str]:
    fautes = []
    for e in tous_les_ecrans():
        for constat in (gestes_sans_organe(e.texte)
                        + cibles_absentes(e.texte)
                        + routes_absentes(e.texte)):
            fautes.append(f"{e}  {constat}")
    return fautes


def test_aucun_ecran_ne_prescrit_un_geste_que_le_produit_ne_sert_pas() -> None:
    """LE CONTRÔLE. Un texte imprimé qui prescrit l'impossible est un piège.

    Le moment où ces lignes sont lues est le pire de tous : l'ami vient
    d'obtenir son cerveau, il a confiance, et il fait ce qu'on lui dit. S'il
    cherche vingt minutes un bouton qui n'existe pas, ce n'est pas le texte
    qu'il accuse — c'est lui-même, ou son installation.
    """
    fautes = balayage_g4()
    assert fautes == [], (
        "un texte IMPRIMÉ par le produit prescrit un geste que le produit ne "
        "sert pas. Ou bien la phrase dit ce qui existe, ou bien elle nomme "
        "l'absence dans le même écran — c'est la seule forme qui enseigne au "
        "lieu de piéger.\n  " + "\n  ".join(fautes)
    )


# ===========================================================================
# LES PRÉMISSES — elles tombent AVANT la règle, et disent quoi relire
# ===========================================================================


def test_les_organes_sont_mesures_dans_le_produit() -> None:
    """PRÉMISSE. Le jour où l'un de ces organes naît, c'est ici que ça se voit.

    Un garde documentaire qui recopie le fait qu'il vérifie pourrit avec lui.
    Ce test établit, depuis le produit, l'état de chaque organe — et son
    message nomme ce qu'il faudra relire quand l'état changera.
    """
    assert not _cockpit_ecrit(), (
        "le cockpit a gagné une route d'écriture : la règle A de ce module est "
        "devenue trop sévère, et tous les textes qui disent « lecture seule » "
        "sont à relire — bootstrap/lib/verify.sh, control_center/app.py, et "
        "les manuels que garde tests/test_la_doc_dit_vrai.py."
    )
    assert not _propositions_se_tranchent(), (
        "une route décide désormais d'une proposition : le rituel « ouvrez le "
        "cockpit et tranchez quelques propositions » redevient possible, et "
        "l'écran de fin du bootstrap peut le prescrire à nouveau."
    )
    assert not _confiance_est_modifiable(), (
        "`confidence` est devenu modifiable : « la calibration s'améliore "
        "quand vous validez » redevient vrai, et bootstrap/lib/verify.sh doit "
        "être relu."
    )
    assert not _audit_est_modifiable(), (
        "`audit_source` est devenu modifiable : marquer un savoir comme "
        "vérifié est enfin possible, et l'écran de fin du bootstrap le dit "
        "encore impossible."
    )


def test_les_capacites_lues_ne_sont_pas_vides() -> None:
    """Un registre vide rendrait la règle B et la règle C vertes par vacuité —
    et ce sont elles qui répondent « une route, une commande, un fichier »."""
    routes = routes_servies()
    assert len(routes) > 40, sorted(routes)[:10]
    assert ("GET", "/healthz") in routes
    assert ("POST", "/cc/login") in routes
    assert ("PATCH", "/v1/atoms/{}") in routes, (
        "le PATCH d'un atome a disparu : c'est le seul geste de correction que "
        "l'écran de fin du bootstrap promet encore."
    )
    assert {"test", "venv", "scopes", "doctor"} <= cibles_make(), sorted(cibles_make())
    assert len(fichiers_servis()) > 300, len(fichiers_servis())


# ===========================================================================
# ÉPROUVER LE GARDE — sur la phrase exacte qui a coûté six manches
# ===========================================================================

#: Les deux leçons telles qu'elles étaient imprimées par `bootstrap/lib/
#: verify.sh` à la fin de chaque installation, plus les formes voisines qui
#: ont vécu ailleurs. Elles sont posées ici, dans une liste, DÉLIBÉRÉMENT :
#: ce qui est posé dans une liste n'est pas imprimé, donc le garde ne se
#: reproche pas à lui-même de les citer (voir
#: `test_le_garde_lit_ce_qui_est_imprime_et_pas_le_reste`).
GESTES_IMPOSSIBLES = (
    ("Prenez l'habitude, une fois par semaine, d'ouvrir le cockpit et de "
     "trancher quelques propositions.",
     "le rituel hebdomadaire de l'écran de fin du bootstrap"),
    ("La calibration compte autant que la recherche, et elle s'améliore quand "
     "vous validez ou corrigez ce qu'il propose — dans le cockpit.",
     "la promesse de calibration de la même leçon"),
    ("Ouvrez le cockpit et validez les atomes que le curateur propose.",
     "la même prescription, à l'impératif direct"),
    ("Cochez dans le cockpit ce que vous avez audité.",
     "un verbe voisin, sur le même organe absent"),
)

#: Des écrans qui prescrivent des gestes SERVIS, ou qui nomment l'absence.
#: Un garde qui crie sur ceux-là finirait désarmé, et le dépôt l'a écrit.
GESTES_SERVIS = (
    ("Ouvrez le cockpit et LISEZ ce qui a été appris : il est en lecture seule.",
     "lire est servi, et l'écran nomme l'absence"),
    ("Le niveau declare d'un atome est immuable ; on ne le valide nulle part.",
     "le geste est NOMMÉ pour être déclaré absent — la seule forme qui enseigne"),
    ("Corrigez config/scopes.toml, puis relancez.",
     "un geste sur un fichier qui existe"),
    ("Relancez : make scopes",
     "une cible du Makefile"),
    ("Le poste est déjà déclaré : rien à valider ici.",
     "un verbe de mutation sans organe nommé"),
    ("Appelez POST /v1/atoms/{id}/supersede pour remplacer un atome dépassé.",
     "une route réellement servie, paramètre nommé autrement"),
)


@pytest.mark.parametrize("phrase,pourquoi", GESTES_IMPOSSIBLES)
def test_le_garde_voit_le_geste_impossible(phrase: str, pourquoi: str) -> None:
    assert gestes_sans_organe(phrase), (
        f"Le garde n'a rien vu dans : {phrase}\n  ({pourquoi})\n"
        "C'est la phrase même qui a survécu à six manches et à un garde "
        "documentaire qui portait pourtant le bon motif."
    )


@pytest.mark.parametrize("phrase,pourquoi", GESTES_SERVIS)
def test_le_garde_se_tait_quand_le_geste_est_servi(phrase: str, pourquoi: str) -> None:
    constats = (gestes_sans_organe(phrase) + cibles_absentes(phrase)
                + routes_absentes(phrase))
    assert constats == [], f"Le garde a crié à tort sur : {phrase}\n  ({pourquoi})\n{constats}"


@pytest.mark.parametrize("phrase,attendu", [
    ("Ouvrez bootstrap/lib/inexistant.sh", "inexistant"),
    ("Relancez : make cible-qui-nexiste-pas", "cible-qui-nexiste-pas"),
])
def test_le_garde_voit_la_cible_morte(phrase: str, attendu: str) -> None:
    """RÈGLE B éprouvée : une cible imprimée qui n'existe pas est un cul-de-sac
    délivré à quelqu'un dont l'installation vient de tomber."""
    constats = cibles_absentes(phrase)
    assert constats and attendu in constats[0], constats


def test_le_garde_voit_la_route_qui_n_existe_pas() -> None:
    """RÈGLE C éprouvée. Le cas réel : deux chemins cités sans leur `/v1`,
    qui rendent 404 quand on les exécute."""
    assert routes_absentes("Appelez POST /v1/atoms/context_for") == []
    assert routes_absentes("Appelez POST /cc/atoms/valider")


def test_le_garde_lit_l_ecran_du_bootstrap_et_pas_le_reste(tmp_path: Path) -> None:
    """LA PRÉMISSE DE L'EXTRACTION, et c'est elle qui manquait à tout le monde.

    Trois faits sur un script fabriqué ici : le corps d'une `lecon` étalé sur
    plusieurs lignes après une continuation `\\` est LU ; un remède écrit en
    continuation (`|| bad "…"`) est LU — c'est la forme sous laquelle ce dépôt
    écrit la plupart de ses remèdes ; et une chaîne posée dans une variable,
    que personne n'imprime, ne l'est pas.
    """
    script = tmp_path / "sonde.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "SPECIMEN=\"ouvrez le cockpit et tranchez quelques propositions\"\n"
        "lecon \"98 % du savoir jamais audité\" \\\n"
        "\"Prenez l'habitude d'ouvrir le cockpit et de\n"
        "trancher quelques propositions.\"\n"
        "[ \"$N\" -gt 0 ] \\\n"
        "    && ok \"des scopes\" \\\n"
        "    || bad \"aucun scope en base\" \"make remede-absent\"\n",
        encoding="utf-8",
    )
    vus = ecrans_shell(script)
    textes = [e.texte for e in vus]
    assert any("trancher quelques propositions" in t for t in textes), (
        "le corps multi-lignes d'une `lecon` n'est pas lu : c'est très "
        "exactement l'angle mort par lequel le geste impossible a survécu."
    )
    assert not any("SPECIMEN=" in t for t in textes), textes
    assert any("make remede-absent" in t for t in textes), (
        "un remède écrit en continuation (`|| bad …`) n'est pas lu ; ce dépôt "
        "en compte des dizaines."
    )
    fautes = [f for e in vus for f in gestes_sans_organe(e.texte)]
    assert fautes, "le geste impossible n'est pas vu dans l'écran extrait"


def test_le_garde_voit_l_ecran_de_fin_de_l_installation() -> None:
    """Un balayage qui ne lit rien passe toujours. C'est le premier piège, et
    ce garde existe précisément parce qu'un corpus par ailleurs correct ne
    contenait pas CE texte-là.

    Les témoins sont nommés : l'écran de fin du bootstrap, le contrôle qu'on
    relance des mois plus tard, le contrôle de durée, et un programme Python
    qui parle à l'utilisateur.
    """
    par_fichier = {e.fichier for e in tous_les_ecrans()}
    for temoin in (
        "bootstrap/lib/verify.sh",          # l'écran de fin — le blocage
        "bootstrap/checks/verify_install.sh",
        "ops/install_check.sh",
        "scripts/ops/health_check.py",
        "mac/arac-pont.sh",
    ):
        assert temoin in par_fichier, f"{temoin} n'imprime rien selon G4 — vérifiez l'extraction"
    assert len(tous_les_ecrans()) > 500, len(tous_les_ecrans())
    # Et l'écran de fin est lu jusqu'à son CORPS, pas seulement à sa ligne
    # d'appel : c'est la différence entre voir la faute et la manquer.
    epilogue = "\n".join(
        e.texte for e in tous_les_ecrans() if e.fichier == "bootstrap/lib/verify.sh")
    assert "confiance basse" in epilogue and "jamais audité" in epilogue, (
        "les leçons de l'écran de fin ne sont pas dans le corpus de G4"
    )


# ===========================================================================
# CE QUE CE GARDE NE COUVRE PAS
# ===========================================================================


@dataclass(frozen=True)
class ZoneAveugleG4:
    zone: str
    pourquoi: str


ZONES_NON_COUVERTES_G4: tuple[ZoneAveugleG4, ...] = (
    ZoneAveugleG4(
        "le Markdown, et toute la documentation",
        "Ce garde ne lit que ce qu'un PROGRAMME imprime. Les manuels sont le "
        "corpus de `tests/test_la_doc_dit_vrai.py`, qui pose sur eux sept "
        "règles de prose. Les faire balayer par les deux serait pire que par "
        "un seul : deux gardes aux règles voisines sur le même texte finissent "
        "par diverger, et le jour où ils divergent, personne ne sait lequel "
        "des deux ment. La conséquence est réelle et assumée : une promesse "
        "impossible écrite dans un `.md` est vue par l'autre garde, pas par "
        "celui-ci.",
    ),
    ZoneAveugleG4(
        "les verbes de mutation qu'on n'a pas nommés",
        "`_GESTE_DE_MUTATION` est une liste fermée, donc elle oublie. "
        "L'inversion — énumérer les verbes qui ne prescrivent RIEN — n'a pas "
        "de sens : cette liste-là est infinie, et une règle qui reproche un "
        "vocabulaire entier crie à tort dès la première phrase juste. Un garde "
        "désarmé ne garde rien. Le prix est assumé, et il est écrit ici.",
    ),
    ZoneAveugleG4(
        "l'organe qui n'est pas nommé dans le même écran",
        "La règle A exige que le geste et l'organe se rencontrent dans le même "
        "texte imprimé. Une prescription étalée sur deux écrans successifs — "
        "« ouvrez le cockpit », puis, dix lignes plus bas, « et tranchez » — "
        "n'est pas vue. Élargir la fenêtre laisserait la nuance d'un écran "
        "couvrir la fausseté d'un autre, ce qui est le défaut inverse et le "
        "plus coûteux des deux.",
    ),
    ZoneAveugleG4(
        "les chemins ABSOLUS nommés à l'écran",
        "`/etc/arac/<base>/arac.env`, `/var/backups/…` : ces chemins naissent "
        "de l'installation, pas du dépôt. Exiger qu'ils existent reviendrait à "
        "exiger que la machine qui lance la suite soit une machine installée — "
        "et la suite doit tourner sur un clone nu. Ce qui les garde, ce sont "
        "les contrôles d'installation, qui les mesurent sur une vraie machine.",
    ),
    ZoneAveugleG4(
        "le geste servi mais SANS EFFET",
        "Ce garde répond « cet organe existe-t-il ? », jamais « fait-il ce que "
        "la phrase promet ? ». Une route qui accepterait le geste et "
        "l'ignorerait passerait ici. C'est la limite de toute vérification "
        "statique : la seule réponse à celle-là est de jouer le geste sur un "
        "cerveau réel, ce que fait `make acceptance`.",
    ),
)


def test_le_garde_declare_ce_qu_il_ne_couvre_pas() -> None:
    assert ZONES_NON_COUVERTES_G4, (
        "Un garde qui ne déclare aucune limite prétend n'en avoir aucune."
    )
    for z in ZONES_NON_COUVERTES_G4:
        assert len(z.pourquoi) > 120, (
            f"La zone « {z.zone} » ne dit pas assez POURQUOI elle n'est pas "
            "couverte. « Non couvert » sans raison mécanique est une excuse."
        )


def test_les_fonctions_de_l_ecran_existent_encore() -> None:
    """Écouter un vocabulaire mort rend le même vert qu'écouter le bon.

    `bootstrap/lib/ui.sh` est la voix de l'installation : chaque fonction
    nommée ici doit y être définie, sinon ce garde écoute une porte murée.
    """
    ui = (RACINE / "bootstrap" / "lib" / "ui.sh").read_text(encoding="utf-8")
    definies = set(re.findall(r"^(\w+)\(\)", ui, re.MULTILINE))
    manquantes = [f for f in FONCTIONS_DE_L_ECRAN if f not in definies]
    assert manquantes == [], (
        f"ces fonctions ne sont plus définies dans bootstrap/lib/ui.sh : "
        f"{manquantes}. G4 écoute un vocabulaire que le produit n'emploie plus."
    )
