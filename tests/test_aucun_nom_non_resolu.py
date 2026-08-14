"""LE GARDE DES NOMS : aucun module livré ne contient un nom qu'il ne sait pas résoudre.

POURQUOI CE FICHIER EXISTE, ET CE QU'IL A COÛTÉ DE NE PAS L'AVOIR

`make test` a rendu 5266 verts, `make acceptance` trois fois « 0 en échec », et le
produit livrait au même moment QUATRE noms non importés, tous sur des chemins qu'un
utilisateur emprunte :

  · `app/routers/dashboard.py:256` et `:335` — `journal.sha8(...)` sans
    `from app import journal`. Les deux dernières instructions de
    `GET /v1/dashboard/atoms` et `GET /v1/dashboard/search` : la requête part, les
    lignes reviennent, le résultat est construit — et le `NameError` tombe juste
    avant le `return`. Deux routes SERVIES qui rendent 500 sur un cerveau sain.
  · `agents/cortex/pack.py:784` — `raison(exc)` sans son import, À L'INTÉRIEUR du
    `except TypeError` posé exprès pour que la digestion survive à des dates
    incomparables. Le filet de rattrapage tuait le cycle qu'il devait sauver.
  · `agents/lib/paid_ai_control.py:29-30` — `import paid_ai_flag` / `import
    kill_switch`, deux modules qui n'existent nulle part sous ce nom (ils vivent
    dans `agents.lib`). Le KILL-SWITCH de l'IA payante, la commande qu'on tape
    quand la facture s'emballe, mourait sur `ModuleNotFoundError` à la première
    ligne. Un test le surveillait — en LISANT SON TEXTE
    (`tests/test_stab_wave2.py`, `pac_src = (...).read_text()`) : il vérifiait
    qu'une clause SQL figurait dans le fichier, sans jamais demander à Python si
    le fichier était chargeable.

Les trois filets du dépôt ont laissé passer les quatre, et chacun pour la même
raison : AUCUN N'EXÉCUTAIT LE CODE LIVRÉ.
  · la suite : les 22 tests qui couvrent ces deux routes se déclarent *skipped*
    sans base ; un module jamais importé ne lève jamais son `NameError` ;
  · `make lint` : ne lit que du shell ;
  · `make acceptance` : appelle `/v1/dashboard/search` UNE fois, sans jeton, et
    n'observe que le 401 — le corps de la fonction n'est jamais entré.

CE QUE CE GARDE FAIT, ET POURQUOI C'EST LA BONNE FORME

Il ne relit pas le code : il le CHARGE, puis il demande à Python lui-même, pour
chaque nom global que le bytecode ira chercher, si ce nom existe quelque part où
il pourra être trouvé. Deux moitiés, indissociables :

  1. L'IMPORT. Tout module Python livré est importé. Un `ModuleNotFoundError`,
     une `SyntaxError`, une exception au chargement : rouge. C'est ce qui attrape
     `paid_ai_control`.
  2. LA RÉSOLUTION. Le module chargé, on parcourt TOUS ses objets-code (fonctions,
     méthodes, corps de classe, lambdas, compréhensions, imbrications) et on
     relève chaque `LOAD_GLOBAL` / `LOAD_NAME` / `DELETE_GLOBAL`. Un nom est
     résolu s'il est dans l'espace de noms du module APRÈS import, dans les
     `builtins`, ou s'il est écrit quelque part dans le module (`global x; x = ...`
     ou un `import` conditionnel). Sinon : rouge. C'est ce qui attrape `journal`
     et `raison`.

POURQUOI CETTE DIRECTION PLUTÔT QUE « FAIRE PASSER LA SUITE PAR CHAQUE ROUTE »

Les deux directions sont bonnes et le dépôt porte maintenant les deux (l'autre est
`tests/test_parcours_des_chemins_livres.py`). Mais elles ne prouvent pas la même
chose. Le parcours prouve qu'un chemin PRÉCIS marche — jamais qu'il n'en reste
aucun de cassé : une suite hermétique ne peut pas emprunter les routes qui exigent
une base, et une route ajoutée demain ne sera empruntée par personne. Ce garde-ci,
lui, prouve une NÉGATIVE UNIVERSELLE, et c'est rare : *aucun* module livré ne
contient *aucun* nom non résolvable. Il n'énumère pas ce qu'il interdit — il
énumère ce que le produit CHARGE, ce qui est une liste que le dépôt possède déjà
(ses fichiers) et qui grandit toute seule. Un fichier ajouté demain est couvert
sans que personne y pense : c'est la propriété que les listes d'interdits n'ont
jamais.

CE QU'IL NE COUVRE PAS — dit ici plutôt que découvert dans six mois
  · un nom résolu mais FAUX (`journal.sha9()` : `journal` existe, l'attribut non).
    Les attributs ne sont pas vérifiés : le bytecode ne dit pas si `x.y` existera,
    et le prouver demanderait de connaître le type de `x`. C'est le parcours qui
    couvre celui-là ;
  · un module qui n'est PAS un fichier `.py` livré (code généré, `exec`, plugin) ;
  · ce qu'un module fait — ce garde dit qu'il CHARGE, jamais qu'il est juste.
"""

from __future__ import annotations

import builtins
import dis
import importlib
import importlib.util
import pkgutil
import sys
from pathlib import Path
from types import CodeType
from typing import Iterator

import pytest

RACINE = Path(__file__).resolve().parent.parent

# Les PAQUETS livrés : importables par leur nom, parcourus récursivement.
PAQUETS_LIVRES = ("app", "agents", "control_center")

# Le code livré qui n'est PAS dans un paquet : l'utilisateur et les unités
# systemd le lancent par son CHEMIN (`python3 bootstrap/wizard.py`), alembic
# charge ses versions par chemin. Il est livré, donc il est couvert.
DOSSIERS_HORS_PAQUET = (
    "bootstrap",
    "bootstrap/checks",
    "bootstrap/lib",
    "scripts/ops",
    "db/alembic",
    "db/alembic/versions",
    "mac",
)

# Les fichiers de la racine du dépôt.
FICHIERS_RACINE = ("arac_runtime.py",)

# LES MODULES QUI NE SE CHARGENT QUE DANS LEUR EXÉCUTEUR — et la raison, REPROUVÉE
# à chaque passage plutôt que crue sur parole.
#
# `db/alembic/env.py` fait `config = context.config` à la première ligne utile :
# `alembic.context` est un proxy que l'outil alembic REMPLIT avant de charger le
# fichier. Hors d'alembic, l'attribut n'existe pas. Ce n'est pas un défaut du
# dépôt, c'est le contrat d'alembic — mais une exception dont on ne vérifie plus
# la raison finit par cacher un vrai défaut (le dépôt en a la cicatrice). Alors
# la raison est ÉCRITE ET CONTRÔLÉE : le module doit échouer, et échouer
# EXACTEMENT sur cet obstacle-là. S'il tombe un jour sur autre chose — un import
# supprimé, une faute de frappe — le garde rougit.
#
# Ses NOMS, eux, sont vérifiés comme ceux de tous les autres : un module qui ne
# se charge pas garde son bytecode, et c'est le bytecode qui dit ce qu'il ira
# chercher.
CHARGEURS_ETRANGERS: dict[str, str] = {
    "db/alembic/env.py": "module 'alembic.context' has no attribute 'config'",
}


# ---------------------------------------------------------------------------
# L'inventaire de ce qui est LIVRÉ — construit en regardant le disque, jamais
# recopié d'une liste. Un fichier ajouté demain y entre sans qu'on le sache.
# ---------------------------------------------------------------------------
def _modules_de_paquet() -> list[str]:
    noms: list[str] = []
    for paquet in PAQUETS_LIVRES:
        pkg = importlib.import_module(paquet)
        noms.append(paquet)
        for info in pkgutil.walk_packages(pkg.__path__, paquet + "."):
            noms.append(info.name)
    return sorted(set(noms))


def _fichiers_hors_paquet() -> list[Path]:
    fichiers: list[Path] = []
    for dossier in DOSSIERS_HORS_PAQUET:
        d = RACINE / dossier
        if not d.is_dir():
            continue
        fichiers.extend(sorted(p for p in d.glob("*.py") if p.name != "__init__.py"))
    for nom in FICHIERS_RACINE:
        p = RACINE / nom
        if p.is_file():
            fichiers.append(p)
    return fichiers


# ---------------------------------------------------------------------------
# La résolution des noms
# ---------------------------------------------------------------------------
def _objets_code(co: CodeType, vus: set[int]) -> Iterator[CodeType]:
    """Tous les objets-code d'un module : le corps, et tout ce qu'il contient."""
    if id(co) in vus:
        return
    vus.add(id(co))
    yield co
    for const in co.co_consts:
        if isinstance(const, CodeType):
            yield from _objets_code(const, vus)


def _noms_non_resolus(espace: dict[str, object], source: Path) -> list[str]:
    """Les noms globaux que ce module ira chercher et ne trouvera nulle part.

    `espace` est l'espace de noms du module APRÈS import — vide pour les rares
    modules qui ne se chargent qu'à l'intérieur de leur exécuteur (cf.
    `CHARGEURS_ETRANGERS`). Le contrôle reste utile dans ce cas : les noms
    ÉCRITS par le module sont relevés dans son bytecode, et c'est précisément
    ce relevé — pas l'espace de noms — qui manque quand un import a été oublié.
    """
    try:
        texte = source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:  # pragma: no cover — disque
        pytest.fail(f"{source} illisible : {exc}")
    sommet = compile(texte, str(source), "exec")

    # Ce que le module ÉCRIT quelque part dans son espace global — y compris
    # depuis une fonction (`global x; x = ...`) et depuis un import conditionnel.
    # Sans ce relevé, un module qui pose son nom à l'exécution serait accusé à tort.
    ecrits: set[str] = set()
    lus: list[tuple[str, int]] = []
    for co in _objets_code(sommet, set()):
        for ins in dis.get_instructions(co):
            if ins.opname in ("STORE_GLOBAL", "STORE_NAME", "IMPORT_NAME"):
                ecrits.add(str(ins.argval).split(".", 1)[0])
            elif ins.opname in ("LOAD_GLOBAL", "LOAD_NAME", "DELETE_GLOBAL"):
                ligne = ins.positions.lineno if ins.positions else None
                lus.append((str(ins.argval), ligne or 0))

    manquants: list[str] = []
    for nom, ligne in lus:
        if nom in espace or nom in ecrits or hasattr(builtins, nom):
            continue
        manquants.append(f"{source.relative_to(RACINE)}:{ligne} — nom `{nom}`")
    # Un même nom peut manquer à plusieurs lignes : on les garde toutes, elles
    # sont autant d'endroits où le produit lèvera `NameError`.
    return sorted(set(manquants))


# ---------------------------------------------------------------------------
# LES DEUX MOITIÉS DU GARDE
# ---------------------------------------------------------------------------
def test_tout_module_livre_est_chargeable_et_ses_noms_sont_resolus() -> None:
    """Le produit charge, et rien de ce qu'il charge ne contient de nom mort.

    Un seul test pour les deux moitiés, volontairement : un module qui ne
    s'importe pas ne peut pas voir ses noms vérifiés, et rendre deux rouges pour
    une seule cause fait chercher deux fois.
    """
    echecs_de_chargement: list[str] = []
    noms_morts: list[str] = []
    charges = 0

    for nom in _modules_de_paquet():
        try:
            module = importlib.import_module(nom)
        except BaseException as exc:  # noqa: BLE001 — TOUT échec de chargement compte
            echecs_de_chargement.append(
                f"{nom} — {type(exc).__name__}: {exc}")
            continue
        charges += 1
        fichier = getattr(module, "__file__", None)
        if fichier and fichier.endswith(".py"):
            noms_morts.extend(_noms_non_resolus(vars(module), Path(fichier)))

    for chemin in _fichiers_hors_paquet():
        relatif = chemin.relative_to(RACINE)
        # Un nom de module qui ne peut entrer en collision avec rien de livré :
        # deux fichiers de dossiers différents peuvent porter le même nom, et
        # écraser une entrée de `sys.modules` fausserait le module suivant.
        nom_technique = "_livre_" + str(relatif).replace("/", "_")[:-3]
        spec = importlib.util.spec_from_file_location(nom_technique, chemin)
        if spec is None or spec.loader is None:  # pragma: no cover
            echecs_de_chargement.append(f"{relatif} — spec introuvable")
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules[nom_technique] = module
        attendu = CHARGEURS_ETRANGERS.get(str(relatif))
        try:
            spec.loader.exec_module(module)
        except BaseException as exc:  # noqa: BLE001
            if attendu is None:
                echecs_de_chargement.append(
                    f"{relatif} — {type(exc).__name__}: {exc}")
                continue
            if attendu not in str(exc):
                echecs_de_chargement.append(
                    f"{relatif} — ce module est déclaré chargeable seulement "
                    f"par son exécuteur, sur l'obstacle « {attendu} ». Il vient "
                    f"d'échouer sur AUTRE CHOSE : {type(exc).__name__}: {exc}. "
                    f"L'exception ne couvre plus ce qu'elle disait couvrir.")
                continue
            # Chargement impossible pour la raison prévue, et REVÉRIFIÉE :
            # l'espace de noms reste vide, les noms sont jugés sur le bytecode.
            noms_morts.extend(_noms_non_resolus({}, chemin))
            continue
        else:
            if attendu is not None:
                echecs_de_chargement.append(
                    f"{relatif} — déclaré « ne se charge que dans son "
                    f"exécuteur » ({attendu}), et il vient de se charger tout "
                    f"seul. L'exception a cessé d'être vraie : retirez-la de "
                    f"CHARGEURS_ETRANGERS.")
        finally:
            sys.modules.pop(nom_technique, None)
        charges += 1
        noms_morts.extend(_noms_non_resolus(vars(module), chemin))

    assert charges > 150, (
        f"seulement {charges} modules chargés — l'inventaire s'est vidé, et un "
        f"garde qui ne regarde rien est vert par construction")

    rapport: list[str] = []
    if echecs_de_chargement:
        rapport.append(
            "MODULES LIVRÉS QUI NE SE CHARGENT PAS "
            f"({len(echecs_de_chargement)}) — le produit ne peut pas les "
            "exécuter :")
        rapport.extend("    " + e for e in echecs_de_chargement)
    if noms_morts:
        rapport.append(
            f"NOMS NON RÉSOLUS ({len(noms_morts)}) — `NameError` à l'exécution, "
            "là où un utilisateur passe :")
        rapport.extend("    " + n for n in noms_morts)
    assert not rapport, "\n" + "\n".join(rapport) + (
        "\n\nUn import manquant ne se voit pas à la lecture et ne rougit aucun "
        "test tant que la ligne n'est pas exécutée. C'est exactement ce qui a "
        "livré deux routes en 500 et un kill-switch mort avec la suite au vert."
    )
