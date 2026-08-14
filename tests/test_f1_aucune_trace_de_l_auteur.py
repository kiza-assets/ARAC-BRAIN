"""F1 — le dépôt entier ne porte aucune trace de son auteur.

    « Si quelqu'un clone ce dépôt aujourd'hui, pourra-t-il créer son propre
    cerveau sans connaître l'auteur ? »  — GOAL.md

POURQUOI CE FICHIER EXISTE, ET POURQUOI IL BALAIE TOUT
======================================================

Le seul garde F1 qu'avait ce dépôt bornait son balayage à ``control_center/``
(``COCKPIT = RACINE / "control_center"``). Il était vert. Pendant ce temps
``requirements.txt`` portait « ARAC Spawn » en ligne 2 — la deuxième chose que
lit un installateur —, ``agents/`` citait l'auteur à la première personne, et
``tests/`` transportait son identifiant Telegram et son adresse professionnelle.

**La réparation a eu exactement la taille du garde-fou.** C'est la leçon, et
c'est la raison pour laquelle ce module ne connaît plus de répertoire : il
balaie tout ce que `git` rendrait à un inconnu qui clone, PLUS les fichiers
que l'installation ENGENDRE — parce que l'identité d'origine était revenue par
là (``config/brain.toml`` régénéré portait ``node_id = "nadia-spawn-arac"``,
affiché par ``make doctor``).

CE QUI EST INTERDIT, ET POURQUOI CHAQUE MOTIF L'EST
====================================================

Un motif n'est pas interdit parce qu'il est laid. Il est interdit parce qu'il
fait l'une de ces trois choses :

1. **Il nomme l'auteur** — son nom, sa société, son village, ses proches, le
   nom de son cerveau, le chemin de sa machine. Le lecteur apprend qu'il lit le
   logiciel de quelqu'un d'autre.

2. **Il cite un document que le lecteur ne peut pas ouvrir** — les identifiants
   des registres privés de l'auteur (« D-063 », « A-02 », « P-026 », « WP-01 »,
   « assault H-1 », « registre stabilisation V5 »). Une règle énoncée sans sa
   raison, adossée à une source inaccessible, n'est pas une règle : c'est une
   superstition. La consigne de réparation est toujours la même — *le renvoi
   disparaît, la raison qu'il portait survit en une phrase*.

3. **Il grave une convention qui n'a de sens que chez l'auteur** — un fuseau
   horaire, « heure de Paris », un identifiant de compte réel. Servi tel quel,
   il découpe les journées des autres au mauvais endroit ou leur envoie les
   messages de quelqu'un.

LES EXCEPTIONS SONT NOMMÉES, JUSTIFIÉES, ET PORTENT SUR UN COUPLE
=================================================================

Une exception est un couple (motif, fichier) — jamais un répertoire, jamais un
fichier en bloc. Un fichier dispensé pour « D-NNN » reste balayé pour tout le
reste. C'est ce qui empêche une dispense d'en couvrir une autre par capillarité.
Chaque entrée de ``EXCEPTIONS`` porte sa raison en clair ; une exception sans
raison écrite est une faute de plus.

Hors-ligne : ce module ne lit que des fichiers. Aucune connexion, aucun service.
"""

from __future__ import annotations

import dataclasses
import functools
import pathlib
import re

import pytest

from tests.corpus_du_depot import REGIME, fichiers_du_depot

RACINE = pathlib.Path(__file__).resolve().parents[1]


# ============================================================================
# Le périmètre : ce qu'un inconnu reçoit, plus ce que l'installation engendre
# ============================================================================

#: Les artefacts que le bootstrap ÉCRIT et que `.gitignore` exclut. Ils ne
#: partent pas dans le clone — mais ils sont ce que l'utilisateur voit à
#: l'écran (`make doctor`, `bootstrap.sh --dry-run`, le pied de page du
#: cockpit). L'identité d'origine y était revenue alors que les sources
#: étaient propres : un garde qui ne lit que les sources ne l'aurait pas vue.
ENGENDRES = (
    "config/brain.toml",
    "config/scopes.toml",
    "config/projects.toml",
    "config/sensitivity.toml",
    "config/scope_suggestions.toml",
    "config/constitution.md",
    "app/schemas/scope_generated.py",
    "db/seeds/scopes.sql",
)

#: Suffixes binaires : les balayer produirait du bruit, pas des constats.
BINAIRES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".woff", ".woff2",
            ".ttf", ".otf", ".zip", ".gz", ".dump", ".pyc", ".so"}


def _fichiers_du_clone() -> list[str]:
    """Tout ce que `git` rendrait à un inconnu : suivi + non suivi non ignoré.

    Ce dépôt n'a pas encore d'historique, donc ``git ls-files`` seul rendrait
    zéro fichier — et le garde serait vert par vacuité, ce qui est très
    exactement la panne qu'il existe pour empêcher. ``--others
    --exclude-standard`` ajoute donc les fichiers non encore suivis que
    `.gitignore` n'exclut pas : c'est la liste de ce qui partirait au premier
    ``git add .``.

    **Et quand `git` n'est pas là.** Cet appel portait un ``check=True``, et
    il s'exécute à la COLLECTE (``PERIMETRE = perimetre()``, plus bas) :
    dans une copie privée de son ``.git`` — ce que reçoit quiconque
    télécharge une archive — toute la suite tombait avant d'avoir exécuté un
    seul test, sur une ``CalledProcessError`` qui ne disait rien de la cause.
    `tests/corpus_du_depot.py` replie maintenant sur le disque et **dit**
    qu'il l'a fait ; `REGIME` nomme le chemin emprunté.
    """
    return fichiers_du_depot()


def perimetre() -> list[pathlib.Path]:
    noms = list(_fichiers_du_clone()) + list(ENGENDRES)
    vus: dict[str, pathlib.Path] = {}
    for nom in noms:
        p = RACINE / nom
        if not p.is_file() or p.suffix.lower() in BINAIRES:
            continue
        vus[nom] = p
    return [vus[n] for n in sorted(vus)]


PERIMETRE = perimetre()


def test_le_perimetre_n_est_pas_vide():
    """Un balayage qui ne lit rien passe toujours. C'est le premier piège.

    Le garde précédent était vert pour une raison de cadrage, pas de propreté.
    Celui-ci commence donc par prouver qu'il a bien quelque chose à lire, et
    que les fichiers nommés dans les constats en font partie.
    """
    assert len(PERIMETRE) > 300, (
        f"{len(PERIMETRE)} fichiers seulement, corpus obtenu en régime "
        f"« {REGIME} » (voir tests/corpus_du_depot.py)"
    )
    relatifs = {str(p.relative_to(RACINE)) for p in PERIMETRE}
    for temoin in ("requirements.txt", "agents/cortex/pack.py",
                   "app/perception/ingest_watchdog.py",
                   "control_center/collectors/perception.py",
                   "tests/conftest.py", "README.md", "Makefile"):
        assert temoin in relatifs, f"hors du balayage : {temoin}"


# ============================================================================
# Les motifs
# ============================================================================


@dataclasses.dataclass(frozen=True)
class Motif:
    cle: str
    regex: str
    pourquoi: str
    #: Les identifiants de registre s'écrivent en MAJUSCULES. Les chercher sans
    #: la casse attrapait « slug-kebab-2-a-128-chars » et faisait passer le
    #: garde pour un imbécile — un garde qui crie à tort finit désactivé. Les
    #: noms propres, eux, restent insensibles : « KIZA », « Kiza », « kiza »
    #: désignent la même société.
    sensible: bool = False

    @property
    def rx(self) -> re.Pattern[str]:
        return re.compile(self.regex, 0 if self.sensible else re.IGNORECASE)


MOTIFS: tuple[Motif, ...] = (
    # --- 1. Ce qui nomme l'auteur ------------------------------------------
    Motif("nom", r"christophe|lewandowski",
          "le nom de l'auteur"),
    Motif("societe", r"\bkiza\w*",
          "la société de l'auteur"),
    Motif("lieux", r"kigali|tournus",
          "les villes de l'auteur"),
    Motif("proches", r"\bsandrine\b",
          "un proche de l'auteur"),
    Motif("pays_societe", r"\bestoni\w*",
          "le pays d'immatriculation de sa société"),
    Motif("cerveau_origine", r"arac[\s_-]*spawn|spawn[\s_-]*arac",
          "le nom du cerveau privé de l'auteur, toutes casses et tous "
          "séparateurs — y compris préfixé (« nadia-spawn-arac »)"),
    Motif("chemin_origine", r"/opt/arac[\s_-]*spawn",
          "le chemin de la machine de l'auteur"),
    Motif("fondateur", r"fondat(eur|rice)",
          "« le fondateur » désigne l'auteur du dépôt, jamais celui qui lit "
          "l'écran. Un inconnu n'a pas de fondateur : il a un cerveau, et "
          "c'est le sien. Employez « vous », « le lecteur », ou — pour un "
          "principe — « cardinal »"),
    Motif("projet_reel", r"\bdomotique\b",
          "un projet réel de l'auteur, cité comme exemple de mesure"),
    Motif("compte_telegram", r"\b7216067766\b",
          "l'identifiant Telegram de l'auteur — dix chiffres de forme réelle, "
          "répété comme valeur par défaut de fixture. Une fixture doit être "
          "manifestement synthétique"),
    Motif("souvenir_prive", r"44fecad0-429c-487e-acd7-72d2b97dff3c",
          "l'UUID d'un atome du cerveau de l'auteur, cité comme justification "
          "de garde-fous de production. Nul autre ne peut le lire"),
    Motif("adresse_pro", r"contact@\w*store\.com|aracgroupe\.com",
          "l'adresse professionnelle de l'auteur, à demi anonymisée : la "
          "marque a été remplacée, le motif « contact@<marque>store.com » a "
          "survécu. Les domaines réservés sont example.com / exemple.fr"),

    # --- 2. Ce qui cite un document que le lecteur ne peut pas ouvrir ------
    Motif("registre_v5", r"registre\s+stabilisation|stabilisation\s+V5",
          "« le registre stabilisation V5 » est un document de travail de "
          "l'auteur, publié nulle part"),
    Motif("registre_D", r"(?<![\w-])D-\d{2,3}(?![\w-])",
          "une décision numérotée qui ne RÉSOUT PAS — « correctif D-063 », "
          "« la migration … (D-056) » renvoyaient au registre privé de "
          "l'auteur. Depuis que ce dépôt publie le sien, une référence qui "
          "désigne une décision de docs/DECISIONS.md est légitime ; celles "
          "qui ne s'y trouvent pas restent des renvois dans le vide",
          sensible=True),
    Motif("registre_A", r"(?<![\w-])A-\d{1,3}(?![\w-])",
          "les entrées du registre de stabilisation de l'auteur "
          "(« A-02 », « A-10 »). Le cockpit en AFFICHAIT une en libellé de "
          "tuile : le lecteur voyait « événements A-10 (7 j) » sans qu'aucun "
          "document du dépôt ne puisse lui dire ce qu'est A-10", sensible=True),
    Motif("registre_P", r"(?<![\w-])P-\d{3}(?![\w-])",
          "les projets numérotés de l'auteur (« P-026 pas 3 »)", sensible=True),
    Motif("registre_WP", r"(?<![\w-])WP-\d{1,2}(?![\w-])",
          "les lots de travail de l'auteur (« WP-01 », « la spec WP-01 »)", sensible=True),
    Motif("campagne_assault", r"\bassault\s+[A-Z]{1,2}-\d",
          "les campagnes de test de l'auteur (« garde-fou anti-prod (assault "
          "H-1) »), qui renvoient à un plan qu'il est seul à avoir"),
    Motif("spec_R", r"\bSPEC\s+R-\d|\bR-\d{2}\b\s*\)|\(R-\d{2}\b",
          "les articles de la spécification privée de l'auteur "
          "(« DOCTRINE ANTI-FABULATION (R-18) », « SPEC R-03 »)", sensible=True),

    # --- 3. Ce qui grave une convention locale ------------------------------
    Motif("fuseau_grave",
          r"""["'](?:Europe|America|Asia|Africa|Australia|Pacific)/\w+["']""",
          "un fuseau écrit en dur est celui de la machine où le fichier a été "
          "écrit. Les créneaux circadiens sont des heures LOCALES : gravés sur "
          "un fuseau, ils sont faux partout ailleurs. La source déclarée est "
          "ARAC_CYCLE_TZ, repli UTC"),
    Motif("heure_de_paris", r"heure\s+de\s+Paris|UTC\+1/\+2",
          "une convention horaire qui n'a de sens que chez l'auteur. Le chien "
          "de garde taisait les alertes « ~23h→07h heure de Paris » : à Tokyo "
          "cela mute la matinée de travail et sonne toute la nuit"),
)


# ============================================================================
# Les exceptions — un couple (motif, fichier), une raison écrite
# ============================================================================

@dataclasses.dataclass(frozen=True)
class Exception_:
    motif: str
    fichier: str
    raison: str


EXCEPTIONS: tuple[Exception_, ...] = (
    # ------------------------------------------------------------------
    # Le titulaire du copyright — décision du 10 août 2026
    # ------------------------------------------------------------------
    # Ce garde interdit le nom de la société parce qu'un cerveau ne doit
    # rien porter de son auteur : ni taxonomie, ni chemin, ni valeur par
    # défaut, ni exemple. Cette règle reste entière.
    #
    # Un titulaire de copyright, lui, DOIT être nommé — c'est ce qui donne
    # à une licence sa force. Le taire ne protégerait personne : cela
    # rendrait seulement la licence inopposable.
    #
    # La dispense est donc bornée à ce que la loi exige, et à rien d'autre :
    # deux fichiers, la licence et les métadonnées du paquet. Partout
    # ailleurs — y compris dans un exemple, un commentaire ou une valeur par
    # défaut — le nom reste interdit, et ce test le refuse comme avant.
    Exception_(
        "societe", "LICENSE",
        "Titulaire du copyright. Une licence sans titulaire nommé n'est pas "
        "une licence : c'est la seule occurrence que le droit rend "
        "nécessaire, et elle ne dit rien du cerveau de personne.",
    ),
    Exception_(
        "societe", "pyproject.toml",
        "Métadonnée `authors` du paquet, qui doit s'accorder avec LICENSE. "
        "Elle nomme le titulaire du projet, jamais un utilisateur ni une "
        "installation.",
    ),
    # RETIRÉE — `README.md` / motif « societe ».
    #
    # Elle couvrait une signature de pied de page qui disait « un projet KIZA ».
    # Le mainteneur a préféré signer de son nom d'usage, qui n'est pas la
    # société : le README ne porte plus le motif, et la dispense ne couvrait
    # donc plus rien.
    #
    # On la retire au lieu de la garder « au cas où » : une dispense sans faute
    # à couvrir est une porte laissée ouverte — le jour où le nom reviendrait
    # dans ce fichier, personne ne le verrait. C'est le test
    # `test_chaque_exception_est_justifiee_et_utile` qui l'exige, et il a raison.
    #
    # Le nom du titulaire reste où le droit l'exige : LICENSE et pyproject.toml.
    # RETIRÉE — `config/scopes.example.toml` / motif « societe ».
    #
    # Elle disait : « C'est la taxonomie de l'auteur, montrée comme un exemple
    # travaillé et marquée "ne copiez pas". Sa présence est une décision, pas
    # un oubli. » La décision a été REVUE : le fichier a été assaini, la
    # société de l'auteur n'y figure plus. La dispense, elle, était restée —
    # et une dispense sans faute à couvrir est une porte laissée ouverte : le
    # jour où le nom serait revenu dans ce fichier, personne ne l'aurait vu.
    #
    # C'est le test `test_chaque_exception_est_justifiee_et_utile` qui l'a
    # signalée, en faisant exactement son travail. Il rendait `make test`
    # ROUGE sur un clone neuf — c'est-à-dire au tout premier geste que le
    # README demande à un inconnu. La réparation n'est pas d'assouplir le
    # test : c'est de retirer la dispense morte.
    Exception_(
        "registre_D", "docs/DECISIONS-ARCHITECTURE.md",
        "Cette page explique au lecteur le format de SON registre à lui — "
        "« ### D-001 — ce que vous avez tranché » — pour le distinguer de "
        "celui du framework, qu'elle porte. Le numéro est un gabarit, jamais "
        "une citation : c'est la forme que le cockpit indexera dans "
        "docs/DECISIONS.md, le fichier de l'utilisateur.",
    ),
    Exception_(
        "registre_D", "control_center/collectors/reports_council.py",
        "Ce module PARSE un registre de décisions que L'UTILISATEUR écrit "
        "(docs/DECISIONS.md, qu'aucun code d'ici n'engendre). Les « D-NNN » "
        "qu'il porte sont le gabarit qu'il propose au lecteur — « ### D-001 — "
        "ce que vous avez tranché » — jamais une citation d'une décision de "
        "l'auteur. La numérotation de décisions est une convention publique.",
    ),
    Exception_(
        "registre_D", "tests/test_control_center_collectors.py",
        "Fixtures synthétiques du parseur ci-dessus : elles vérifient le tri, "
        "la déduplication et le refus des références en plein texte. Aucun de "
        "ces numéros ne désigne une décision réelle.",
    ),
    Exception_(
        "fuseau_grave", "control_center/config.py",
        "C'est le module qui fait DÉRIVER le fuseau de la configuration : il "
        "documente des exemples de noms IANA valides pour ARAC_CYCLE_TZ. "
        "L'interdire ici reviendrait à interdire de dire ce qu'on attend.",
    ),
    # Le garde lui-même doit nommer ce qu'il interdit, sans quoi il ne peut
    # rien expliquer au contributeur qu'il arrête.
    Exception_("*", "tests/test_f1_aucune_trace_de_l_auteur.py",
               "Le garde énonce les motifs qu'il interdit et cite les fautes "
               "réelles qui les ont fait écrire. Un garde muet sur sa raison "
               "se fait désactiver au premier échec incompris."),
)


def _dispense(motif: str, relatif: str) -> str | None:
    for e in EXCEPTIONS:
        if e.fichier == relatif and e.motif in (motif, "*"):
            return e.raison
    return None


def test_les_dispenses_de_l_ecran_sont_justifiees_et_encore_utiles():
    """Mêmes règles que pour les fichiers : raison écrite, et faute à couvrir.

    Une dispense d'écran est plus dangereuse qu'une dispense de fichier — elle
    porte sur ce que le lecteur VOIT. Elle doit donc mourir dès que le littéral
    qu'elle couvre a disparu des pages.
    """
    pages = "\n".join(servi().values())
    for cle, entrees in SERVI_DISPENSES.items():
        assert cle in {m.cle for m in MOTIFS}, cle
        for litteral, raison in entrees:
            assert len(raison) > 80, litteral
            assert litteral in pages, (
                f"dispense d'écran inutile : « {litteral} » n'est plus servi. "
                "Retirez-la."
            )
    for chemin, raison in CHEMINS_A_CREER.items():
        assert len(raison) > 80, chemin
        assert not (RACINE / chemin).exists(), (
            f"{chemin} existe désormais : la dispense n'a plus lieu d'être."
        )
        assert chemin in pages, (
            f"aucun texte servi ne cite plus {chemin} : dispense morte."
        )


def test_chaque_exception_est_justifiee_et_utile():
    """Une exception qui ne sert plus est une porte laissée ouverte.

    Deux façons de mentir avec une liste d'exceptions : ne pas écrire la
    raison, ou laisser une entrée survivre à la faute qu'elle couvrait. La
    seconde est la pire — elle rouvre le passage sans que personne le sache.
    """
    for e in EXCEPTIONS:
        assert len(e.raison) > 80, f"{e.motif}/{e.fichier} : raison trop courte"
        assert (RACINE / e.fichier).is_file(), f"exception morte : {e.fichier}"
        if e.motif != "*":
            assert e.motif in {m.cle for m in MOTIFS}, e.motif
            motif = next(m for m in MOTIFS if m.cle == e.motif)
            texte = (RACINE / e.fichier).read_text(encoding="utf-8",
                                                   errors="replace")
            assert motif.rx.search(texte), (
                f"exception inutile : {e.fichier} ne porte plus « {e.motif} ». "
                "Retirez-la — une dispense sans faute à couvrir est une porte "
                "laissée ouverte."
            )


# ============================================================================
# LE BALAYAGE
# ============================================================================


@functools.lru_cache(maxsize=1)
def _decisions_publiees() -> frozenset[str]:
    """Les décisions que CE dépôt publie, lues dans ``docs/DECISIONS.md``.

    Le motif « registre_D » a été écrit quand le dépôt ne livrait aucun registre :
    un « D-063 » ne renvoyait alors nulle part, et sa raison le disait —
    « la citation renvoie dans le vide ». **Cette raison a cessé d'être vraie** le
    jour où le dépôt s'est doté de son propre registre public.

    Plutôt que d'ajouter une dispense par fichier citant — elles auraient vieilli
    aussi mal que la raison qu'elles remplacent — on RÉSOUT : une référence est
    légitime quand elle désigne une décision réellement publiée ici, fautive
    sinon. C'est la doctrine du dépôt (voir DECISIONS.md, D-13) : ne pas recopier
    ce qu'on surveille, aller le lire.
    """
    # Deux registres portent des « D-NN », et il ne faut pas les confondre :
    # `docs/DECISIONS.md` est celui que L'UTILISATEUR écrit (le cockpit
    # l'indexe pour lui, et aucun code d'ici ne l'engendre) ;
    # `docs/DECISIONS-ARCHITECTURE.md` est celui du FRAMEWORK. Les deux sont
    # lus : une référence est légitime si elle résout dans l'un ou l'autre.
    publiees: set[str] = set()
    for nom in ("DECISIONS-ARCHITECTURE.md", "DECISIONS.md"):
        f = RACINE / "docs" / nom
        if f.is_file():
            publiees |= set(
                re.findall(r"^#{2,4}\s*(D-\d{2,3})\b",
                           f.read_text(encoding="utf-8"), re.M)
            )
    return frozenset(publiees)


def _occurrences(motif: Motif) -> list[str]:
    trouves: list[str] = []
    publiees = _decisions_publiees() if motif.cle == "registre_D" else frozenset()
    for p in PERIMETRE:
        relatif = str(p.relative_to(RACINE))
        if _dispense(motif.cle, relatif):
            continue
        for n, ligne in enumerate(
            p.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            m = motif.rx.search(ligne)
            if not m:
                continue
            # Une référence qui RÉSOUT n'est pas une trace : elle renvoie à une
            # décision que ce dépôt publie. Seules les autres restent fautives.
            if publiees and all(r in publiees for r in motif.rx.findall(ligne)):
                continue
            trouves.append(f"{relatif}:{n}: {ligne.strip()[:120]}")
    return trouves


@pytest.mark.parametrize("motif", MOTIFS, ids=lambda m: m.cle)
def test_aucune_trace_de_l_auteur(motif: Motif):
    """Un motif, un verdict, et la raison de l'interdit dans le message.

    Le balayage est découpé par motif plutôt que rendu en un seul verdict :
    un échec doit dire LEQUEL des interdits est rompu et POURQUOI c'en est un,
    sinon le contributeur qui le lit corrige au hasard — ou le désactive.
    """
    trouves = _occurrences(motif)
    assert not trouves, (
        f"\n\nF1 rompu — motif « {motif.cle} » : {motif.pourquoi}.\n"
        f"{len(trouves)} occurrence(s) :\n  " + "\n  ".join(trouves[:60])
        + ("\n  … et " + str(len(trouves) - 60) + " autres" if len(trouves) > 60 else "")
    )


# ============================================================================
# La preuve qui compte : ce qui s'AFFICHE
# ============================================================================
#
# Un nom d'auteur dans un commentaire est une faute ; à l'écran, c'en est une
# autre. Les trois pires trouvailles de cette manche naissent de textes
# ASSEMBLÉS À L'EXÉCUTION — un libellé de tuile composé d'un identifiant de
# registre, un geste concaténé avec un chemin de document. Aucune lecture de
# source ne les attrape. On rend donc les pages et on cherche dans le HTML.

_TEST_SECRET = "test_secret_f1_sans_auteur_not_for_production"


def _routes_html() -> list[str]:
    """Toute route GET sans paramètre de chemin que le cockpit déclare.

    Énumérée depuis l'application, jamais écrite à la main : une liste écrite à
    la main vieillit moins vite que le cockpit, et la prochaine page fautive
    serait précisément celle qu'on aurait oublié d'y ajouter.

    Les flux (``…/stream``) sont écartés — ce sont des SSE sans fin : les
    demander bloquerait le balayage pour toujours. Ils ne composent aucun texte
    qui leur soit propre ; leur catalogue et leur état, eux, sont des routes
    ordinaires et RESTENT balayés (``/cc/v1/stream/catalog``, ``…/state``).
    """
    from control_center.app import create_app

    routes: list[str] = []
    for r in create_app().routes:
        chemin = getattr(r, "path", "")
        methodes = getattr(r, "methods", set()) or set()
        if "GET" not in methodes or "{" in chemin or chemin.endswith("/stream"):
            continue
        routes.append(chemin)
    return sorted(set(routes))


#: Dispenses du balayage de l'ÉCRAN. Elles portent sur un LITTÉRAL servi, pas
#: sur une page : dispenser une page entière rouvrirait tout ce qu'elle affiche.
SERVI_DISPENSES: dict[str, tuple[tuple[str, str], ...]] = {
    "registre_D": ((
        "### D-001 — ce que vous avez tranché",
        "Le GABARIT que le cockpit propose à l'UTILISATEUR pour son propre "
        "registre (docs/DECISIONS.md, que ce dépôt n'engendre pas). Ce n'est "
        "pas une citation : c'est la forme du titre qu'on l'invite à écrire, "
        "et sans elle le geste ne dit plus quoi écrire.\n"
        "\n"
        "Cette dispense a été RETIRÉE puis RÉTABLIE le même jour, et la raison "
        "vaut d'être gardée : la page du registre affiche SOIT les décisions "
        "indexées, SOIT ce geste — jamais les deux. Le jour où un "
        "docs/DECISIONS.md a existé dans l'arbre, le gabarit a cessé d'être "
        "servi et la dispense est devenue morte ; son retrait était juste. "
        "Le fichier a ensuite été renommé (le framework tient son registre "
        "dans DECISIONS-ARCHITECTURE.md, pour ne pas occuper la place de "
        "celui du lecteur), la page est revenue à son état vide, et le "
        "gabarit avec elle. Une dispense d'écran dépend donc de l'ÉTAT du "
        "cerveau observé, pas seulement du code — c'est pourquoi le test qui "
        "la vérifie doit rester, et pourquoi celle-ci porte son histoire.",
    ),),
}

#: Les chemins que des textes servis citent alors qu'ils n'existent pas — et
#: qui ont le droit de ne pas exister, parce que le cockpit demande au lecteur
#: de LES CRÉER. Un geste qui nomme un fichier absent est fautif quand il
#: prétend le faire LIRE ; il est juste quand il demande de l'écrire.
CHEMINS_A_CREER: dict[str, str] = {
    "docs/DECISIONS.md":
        "Le registre de décisions du LECTEUR. Aucun code de ce dépôt ne "
        "l'engendre, et la page « Décisions » le dit : elle nomme le fichier "
        "et le geste qui le crée. Le faire exister ici reviendrait à livrer à "
        "tout le monde les décisions d'une seule personne.",
    "config/projects.toml":
        "La déclaration de projets du LECTEUR, exclue du versionnement par "
        "`.gitignore` au même titre que sa taxonomie. Le cockpit la nomme pour "
        "que l'absence de projets se lise comme « rien de déclaré » et non "
        "comme une panne.",
}


_SERVI: dict[str, str] | None = None


def servi() -> dict[str, str]:
    """Le HTML de toutes les pages, rendu UNE fois, en mémoire.

    Rendre par motif coûterait cinquante-six pages fois vingt-deux motifs. On
    rend donc une fois et on relit le texte — le balayage est une lecture, pas
    une requête.

    Aucun ``DATABASE_URL_READONLY`` n'est posé : le cockpit tombe sur ses
    chemins d'indisponibilité, c'est-à-dire exactement l'état d'un cerveau qui
    vient d'être cloné — et c'est là que vivent les textes d'absence, ceux qui
    portaient les identifiants de registre et les gestes morts.
    """
    global _SERVI
    if _SERVI is not None:
        return _SERVI

    import os

    from fastapi.testclient import TestClient

    from control_center.app import create_app
    from control_center.config import CC_SESSION_SECRET_ENV, SESSION_COOKIE_NAME
    from control_center.security import sign_session

    ancien = os.environ.get(CC_SESSION_SECRET_ENV)
    os.environ[CC_SESSION_SECRET_ENV] = _TEST_SECRET
    try:
        client = TestClient(create_app(), raise_server_exceptions=False)
        client.cookies.set(
            SESSION_COOKIE_NAME,
            sign_session({"sub": "test_f1"}, secret=_TEST_SECRET),
        )
        pages: dict[str, str] = {}
        for chemin in _routes_html():
            r = client.get(chemin, follow_redirects=False)
            if r.status_code < 500 and r.text:
                pages[chemin] = r.text
    finally:
        if ancien is None:
            os.environ.pop(CC_SESSION_SECRET_ENV, None)
        else:
            os.environ[CC_SESSION_SECRET_ENV] = ancien
    _SERVI = pages
    return pages


def test_le_cockpit_declare_bien_des_pages_a_rendre():
    """Sans ce contrôle, un changement de routage rendrait le suivant vide."""
    routes = _routes_html()
    assert len(routes) > 20, routes
    assert "/cc/perception" in routes, routes


@pytest.mark.parametrize("motif", MOTIFS, ids=lambda m: m.cle)
def test_rien_de_l_auteur_ne_s_affiche(motif: Motif):
    """Le HTML SERVI, pas les sources : c'est là que « A-10 » est apparu.

    « A-10 » n'était pas dans un commentaire. Il était le libellé d'une tuile,
    le titre d'un tableau, le sous-titre d'une page et un message de limite —
    quatre textes composés à l'exécution, sur deux pages. Un balayage de
    sources l'aurait manqué à chaque fois qu'il est assemblé.
    """
    publiees = _decisions_publiees() if motif.cle == "registre_D" else frozenset()
    fautifs: list[str] = []
    for chemin, page in servi().items():
        for m in motif.rx.finditer(page):
            extrait = page[max(0, m.start() - 70):m.end() + 70]
            if any(lit in extrait for lit, _ in SERVI_DISPENSES.get(motif.cle, ())):
                continue
            # Même règle qu'aux sources : une référence qui désigne une décision
            # que CE dépôt publie n'est pas une trace. Le cockpit sert d'ailleurs
            # `docs/DECISIONS.md` — la page du registre lit le fichier réel, et
            # c'est ce qu'on veut voir à l'écran.
            if m.group(0) in publiees:
                continue
            fautifs.append(f"{chemin} → …{extrait.strip()!r}…")
    assert not fautifs, (
        f"\n\nF1 rompu À L'ÉCRAN — motif « {motif.cle} » : {motif.pourquoi}.\n"
        + "\n  ".join(fautifs[:30])
    )


def test_aucun_geste_servi_ne_renvoie_vers_un_fichier_absent():
    """Un geste qui envoie nulle part est pire qu'aucun geste.

    ``/cc/v1/listener/state`` servait un champ ``gesture`` qui disait au lecteur
    d'aller lire ``docs/COCKPIT-EVENT-CHANNEL.md`` — un fichier que ce dépôt ne
    contient pas — puis de publier depuis ``scripts/brain/spend_guard.py``, qui
    n'existe pas davantage (le module réel est ``agents/lib/spend_guard.py``).
    Le lecteur qui suit l'instruction perd son après-midi et conclut que son
    installation est incomplète. Elle ne l'est pas : c'est l'instruction qui
    décrit l'arborescence d'un autre dépôt.

    On ne vérifie ici que les chemins CITÉS DANS DU TEXTE SERVI : c'est la
    catégorie où l'erreur devient une consigne.
    """
    chemin_rx = re.compile(
        r"\b((?:docs|scripts|mcp|bootstrap|app|agents|control_center|db|ops|"
        r"deploy|config|tests|mac)/[\w./-]*[\w/])"
    )
    fautifs: set[str] = set()
    for route, page in servi().items():
        for m in chemin_rx.finditer(page):
            cite = m.group(1).rstrip("./")
            # Un répertoire cité (« scripts/ops/ ») compte s'il n'existe pas.
            if (RACINE / cite).exists():
                continue
            if cite in CHEMINS_A_CREER:
                continue
            # Les motifs de fichiers (« backup_*.sh ») sont résolus par glob.
            if any(c in cite for c in "*?["):
                if list(RACINE.glob(cite)):
                    continue
            fautifs.add(f"{route} → {cite}")
    assert not fautifs, (
        "\n\nDes textes SERVIS citent des chemins que ce dépôt ne contient "
        "pas. Le renvoi doit disparaître ; la raison qu'il portait survit en "
        "une phrase.\n  " + "\n  ".join(sorted(fautifs)[:40])
    )


def test_aucune_source_ne_renvoie_vers_un_chemin_du_depot_d_origine():
    """Les mêmes renvois morts, mais dans le code — 65 avaient été relevés.

    Le constat avait déjà été signalé une manche plus tôt et n'avait pas été
    traité : ``scripts/brain/``, ``scripts/ingest/``, ``scripts/memory/``,
    ``scripts/ops/backup_*.sh``, ``scripts/mac/``, ``mcp/arac_mcp/``. Un lecteur
    qui suit une piste tombe dans le vide, et apprend au passage la forme d'un
    dépôt qu'il n'a pas.

    Ne sont visés que les préfixes qui désignaient des organes du dépôt
    d'origine et qui n'existent nulle part ici : le motif est fermé, énuméré,
    et chaque entrée disparaîtra le jour où l'organe existera pour de bon.
    """
    morts = {
        "scripts/brain/": "les scripts du moteur vivent dans agents/",
        "scripts/ingest/": "l'ingestion vit dans app/perception/ et app/routers/",
        "scripts/memory/": "la mémoire vit dans app/services/ et app/context/",
        "scripts/mac/": "le pont Mac vit dans mac/",
        "mcp/arac_mcp/": "aucun serveur MCP n'est livré par ce dépôt",
        "bootstrap/profils/": "l'entretien n'a pas de répertoire de profils",
    }
    fautifs: list[str] = []
    for p in PERIMETRE:
        relatif = str(p.relative_to(RACINE))
        if relatif == "tests/test_f1_aucune_trace_de_l_auteur.py":
            continue
        texte = p.read_text(encoding="utf-8", errors="replace")
        for n, ligne in enumerate(texte.splitlines(), 1):
            for prefixe in morts:
                if prefixe in ligne:
                    fautifs.append(f"{relatif}:{n}: {ligne.strip()[:110]}")
    assert not fautifs, (
        "\n\nDes renvois pointent vers l'arborescence du dépôt d'origine :\n  "
        + "\n  ".join(fautifs[:60])
        + "\n\nRaisons de remplacement :\n  "
        + "\n  ".join(f"{k} → {v}" for k, v in morts.items())
    )


# ============================================================================
# Ce que le bootstrap ENGENDRE
# ============================================================================


def test_l_identifiant_de_poste_ne_derive_jamais_du_nom_de_la_machine():
    """La fabrique du node_id, pas seulement son produit.

    ``config/brain.toml`` régénéré portait ``node_id = "nadia-spawn-arac"`` :
    le nom du cerveau d'origine, revenu PRÉFIXÉ, et affiché par ``make
    doctor``. Les sources étaient propres — c'est la FABRIQUE qui le
    reconstituait, en prenant ``os.uname().nodename`` comme valeur par défaut.

    Or l'entretien tourne sur le SERVEUR, et le node_id nomme le POSTE (« votre
    Mac, en général ») : le nom d'hôte de la machine qui pose la question n'est
    jamais la bonne réponse. Le défaut était donc à la fois une fuite d'identité
    et une réponse fausse. Purger le fichier engendré sans purger la fabrique
    l'aurait fait revenir au prochain entretien.
    """
    source = (RACINE / "bootstrap" / "wizard.py").read_text(encoding="utf-8")
    zone = source[source.index("node_id"):]
    for interdit in ("os.uname", "nodename", "gethostname", "socket.gethostname"):
        assert interdit not in zone, (
            f"La valeur par défaut du node_id dérive de « {interdit} » : le nom "
            "de la machine qui fait tourner l'entretien. C'est le serveur, pas "
            "le poste — et chez l'auteur, c'était le nom de son cerveau."
        )


# ============================================================================
# Les conventions gravées : le fuseau, les heures, la nuit
# ============================================================================
#
# Un fuseau ou une heure gravés ne se voient dans aucun balayage de mots : la
# chaîne « Europe/Paris » peut disparaître alors que les HEURES qu'elle servait
# à découper restent, elles, écrites en dur. Ces trois gardes prouvent donc un
# COMPORTEMENT, pas une absence de texte — c'est la seule preuve qui vaille ici.


def test_le_moteur_decoupe_ses_journees_sur_le_fuseau_declare():
    """Le moteur et le cockpit doivent lire LA MÊME source de fuseau.

    ``agents/cortex/cycle.py`` portait un fuseau IANA en dur : les créneaux
    circadiens tombaient donc aux heures d'un seul pays, alors que la
    documentation promet ``ARAC_CYCLE_TZ`` — et que le cockpit, lui, l'honorait
    déjà. Un cockpit et un moteur qui ne découpent pas la même journée ne
    peuvent pas se prouver l'un l'autre.

    La preuve est un MÊME instant UTC lu depuis trois fuseaux : il doit tomber
    dans trois créneaux différents.
    """
    import os
    from datetime import datetime, timezone

    from agents.cortex import cycle

    instant = datetime(2026, 8, 7, 3, 0, tzinfo=timezone.utc)
    lus: dict[str, str] = {}
    for tz in ("UTC", "America/Montreal", "Asia/Tokyo"):
        ancien = os.environ.get(cycle.CYCLE_TZ_ENV)
        os.environ[cycle.CYCLE_TZ_ENV] = tz
        try:
            lus[tz] = cycle.resolve_slot(instant)[0]
        finally:
            if ancien is None:
                os.environ.pop(cycle.CYCLE_TZ_ENV, None)
            else:
                os.environ[cycle.CYCLE_TZ_ENV] = ancien

    assert len(set(lus.values())) == 3, (
        "Le même instant doit tomber dans trois créneaux différents selon le "
        f"fuseau déclaré ; obtenu : {lus}"
    )


def test_le_fuseau_du_moteur_retombe_sur_utc_et_ne_leve_jamais():
    """Rien de déclaré, ou un nom illisible : UTC — le fuseau de personne.

    Un repli implicite sur l'heure de la machine serait un fuseau plausible et
    faux, sans le dire. Et un nom de fuseau invalide ne doit pas empêcher le
    cerveau de tourner : c'est un réglage d'affichage du temps, pas une panne.
    """
    import os

    from agents.cortex import cycle

    for valeur in (None, "", "   ", "Pas/UnFuseau"):
        ancien = os.environ.get(cycle.CYCLE_TZ_ENV)
        if valeur is None:
            os.environ.pop(cycle.CYCLE_TZ_ENV, None)
        else:
            os.environ[cycle.CYCLE_TZ_ENV] = valeur
        try:
            assert str(cycle.cycle_tz()) == "UTC", valeur
        finally:
            if ancien is None:
                os.environ.pop(cycle.CYCLE_TZ_ENV, None)
            else:
                os.environ[cycle.CYCLE_TZ_ENV] = ancien


def test_les_heures_des_creneaux_viennent_de_la_cadence_declaree(monkeypatch):
    """Le fuseau était réparé ; les HEURES, non — la moitié d'un correctif.

    ``cycle_tz()`` lisait bien ``ARAC_CYCLE_TZ``, mais les fenêtres restaient
    gravées sur 04:00 / 13:00 / 21:00 — les créneaux d'une seule installation.
    Or ``ARAC_CYCLES`` est présenté comme réglable dans quatre documents, et
    c'est de cette variable que le bootstrap tire les ``OnCalendar=`` de la
    minuterie.

    Conséquence, et elle se paie : qui déclarait ``ARAC_CYCLES="09:00 18:00"``
    voyait sa minuterie tirer à 09:00 et le moteur répondre ``manual@<minute>``.
    Le slot_key cessait d'être unique par jour ; comme la minuterie porte
    ``Persistent=true``, le rattrapage et le tir nominal obtenaient DEUX reçus
    distincts — deux cycles payants là où il n'en fallait qu'un.
    """
    from datetime import datetime, timezone

    from agents.cortex import cycle

    monkeypatch.setenv(cycle.CYCLE_TZ_ENV, "UTC")
    monkeypatch.setenv(cycle.CYCLES_ENV, "09:00 18:00")

    trig, slot = cycle.resolve_slot(datetime(2026, 8, 7, 9, 0, tzinfo=timezone.utc))
    assert trig == "circadian_0900", trig
    # Le rattrapage tardif retombe sur LE MÊME slot_key : un seul reçu, donc
    # un seul cycle payant.
    _, rattrapage = cycle.resolve_slot(datetime(2026, 8, 7, 11, 45, tzinfo=timezone.utc))
    assert rattrapage == slot, (slot, rattrapage)
    # Et une heure hors de toute fenêtre déclarée reste manuelle.
    assert cycle.resolve_slot(
        datetime(2026, 8, 7, 3, 0, tzinfo=timezone.utc))[0] == "manual"


def test_la_cadence_par_defaut_reproduit_exactement_l_ancien_decoupage(monkeypatch):
    """Rendre une constante configurable ne doit rien changer à qui n'y touche pas.

    C'est la contrepartie du test précédent : sans lui, « paramétrable » serait
    une façon polie de dire « le comportement a changé pour tout le monde ».
    Les vingt-quatre heures sont comparées au découpage d'origine, une à une.
    """
    from datetime import datetime, timezone

    from agents.cortex import cycle

    monkeypatch.setenv(cycle.CYCLE_TZ_ENV, "UTC")
    monkeypatch.delenv(cycle.CYCLES_ENV, raising=False)

    def historique(h: int) -> str:
        if 2 <= h <= 7:
            return "circadian_0400"
        if 11 <= h <= 16:
            return "circadian_1300"
        if 19 <= h <= 23:
            return "circadian_2100"
        return "manual"

    ecarts = {
        h: (historique(h), cycle.resolve_slot(
            datetime(2026, 8, 7, h, 0, tzinfo=timezone.utc))[0])
        for h in range(24)
        if historique(h) != cycle.resolve_slot(
            datetime(2026, 8, 7, h, 0, tzinfo=timezone.utc))[0]
    }
    assert not ecarts, ecarts


def test_une_cadence_illisible_ne_fait_pas_tomber_le_cycle(monkeypatch):
    """Une liste d'heures mal écrite est une faute de configuration, pas une panne."""
    from datetime import datetime, timezone

    from agents.cortex import cycle

    monkeypatch.setenv(cycle.CYCLE_TZ_ENV, "UTC")
    for valeur in ("", "   ", "pas des heures", "99:99", ","):
        monkeypatch.setenv(cycle.CYCLES_ENV, valeur)
        assert cycle.declared_cycles() == ((4, 0), (13, 0), (21, 0)), valeur
        assert cycle.resolve_slot(
            datetime(2026, 8, 7, 4, 0, tzinfo=timezone.utc))[0] == "circadian_0400"


def test_les_heures_calmes_du_chien_de_garde_sont_locales(monkeypatch):
    """« La nuit » doit être la nuit du lecteur, pas celle d'un fuseau gravé.

    Le chien de garde taisait les WARN entre 21:00 et 05:00 **UTC**, et le
    commentaire admettait la raison : « ~23h→07h heure de Paris ». À Tokyo, cela
    taisait la matinée de travail (06:00–14:00 locales) et faisait sonner toute
    la nuit — l'inverse exact de l'intention. La fenêtre est désormais LOCALE,
    au fuseau que le cerveau déclare déjà pour ses cycles.
    """
    from agents.cortex import cycle
    from app.perception import ingest_watchdog as iw

    monkeypatch.setenv(cycle.CYCLE_TZ_ENV, "Asia/Tokyo")
    assert iw._in_quiet_hours(23) is True, "23h locales sont la nuit"
    assert iw._in_quiet_hours(2) is True, "02h locales sont la nuit"
    assert iw._in_quiet_hours(9) is False, "09h locales sont la matinée de travail"
    assert iw._in_quiet_hours(14) is False
    # Sans argument, l'heure lue est l'heure locale — et l'appel ne lève jamais,
    # même si le fuseau déclaré est illisible.
    monkeypatch.setenv(cycle.CYCLE_TZ_ENV, "Pas/UnFuseau")
    assert isinstance(iw._in_quiet_hours(), bool)


def test_le_moteur_ne_charge_aucun_module_par_un_chemin_construit():
    """Un import par chemin échoue à l'INCIDENT, pas à l'import.

    ``cycle._alert`` chargeait ``ingest_watchdog`` depuis un chemin de fichier
    assemblé à l'exécution — un chemin qui n'existe pas dans ce dépôt. Chaque
    alerte du moteur tombait donc en silence dans ``cortex.alert_failed``, et le
    seul symptôme visible était l'absence d'alerte : le mode de panne le plus
    coûteux, puisqu'il ne se manifeste que le jour où l'on avait besoin d'être
    prévenu.
    """
    import inspect

    from agents.cortex import cycle

    source = inspect.getsource(cycle._alert)
    assert "spec_from_file_location" not in source, source
    assert "os.path.join" not in source, source
    # Et la cible existe vraiment : l'import ordinaire est la preuve.
    from app.perception.ingest_watchdog import send_telegram

    assert callable(send_telegram)
