"""L'IMPORT NE FABRIQUE RIEN — le garde qui aurait attrapé « static/ ».

CE QUI S'EST PASSÉ
==================

Le meilleur ami clone le dépôt, suit la documentation, installe. L'API ne
démarre jamais. Le journal répète, en boucle de redémarrage :

    File "<dépôt>/app/main.py", line 268, in <module>
      _STATIC_DIR.mkdir(parents=True, exist_ok=True)
    OSError: [Errno 30] Read-only file system: '<dépôt>/static'

Trois faits qui, séparément, ne disent rien :

  1. `app/main.py` créait `static/` AU MOMENT DE L'IMPORT, pour que
     `StaticFiles(directory=…)` trouve un répertoire existant ;
  2. `static/` est VIDE dans le dépôt, et **git ne transporte pas les
     répertoires vides** : il n'est donc dans AUCUN clone ;
  3. l'unité `*-api.service` porte `ProtectSystem=strict` — tout le disque est
     monté en lecture seule, sauf le dossier de journaux et le StateDirectory.
     Le dépôt est du CODE : il n'a aucune raison d'être inscriptible.

Sur la machine de développement, rien de tout cela ne se voyait : `make test`
crée `static/` par EFFET DE BORD (la suite importe `app.main`). **Le produit ne
démarrait qu'après le passage de sa propre suite de tests.** C'est la
définition d'un défaut invisible à celui qui l'a écrit et fatal à tous les
autres.

CE QUE CE FICHIER MESURE
========================

Deux gardes, et ils ne se remplacent pas.

`test_aucun_module_ne_fabrique_sur_le_disque_a_l_import` décrit la FORME du
défaut, pas son instance : aucun module de `app/`, `control_center/` et
`agents/` ne doit appeler, au niveau module, quoi que ce soit qui modifie le
disque. C'est le garde qui verra le PROCHAIN `mkdir` à l'import — celui qu'on
n'a pas encore écrit, sous un autre nom, dans un autre fichier.

`test_l_api_s_importe_depuis_un_clone_en_lecture_seule` reproduit la scène
exacte : un clone qui ne porte QUE ce que git transporte (donc sans répertoire
vide), en lecture seule, et l'API qui doit s'y importer sans rien créer.

POURQUOI DEUX MESURES POUR UN SEUL DÉFAUT
=========================================

La reproduction seule serait aveugle à un `mkdir` posé dans un chemin qu'elle
ne parcourt pas ; le garde de forme seul serait aveugle à un échec de démarrage
dont la cause n'est pas une écriture. Le premier généralise, le second prouve.

NOTE SUR « LECTURE SEULE » QUAND ON EST root
============================================

`chmod a-w` ne freine pas root : la suite peut tourner sous n'importe quelle
identité, et un test dont la conclusion dépend de l'UID ne prouve rien. Le
`chmod` est donc posé (il fait échouer l'écriture pour tout le monde sauf
root), mais l'ASSERTION porte sur autre chose, qui est vraie pour tous : **le
clone est identique avant et après l'import**. Un `mkdir` réussi sous root est
attrapé par le relevé d'inventaire ; le même `mkdir` refusé sous un compte de
service est attrapé par le code de sortie. Les deux chemins mènent au rouge.
"""

from __future__ import annotations

import ast
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path



RACINE = Path(__file__).resolve().parent.parent

#: Les paquets qu'un service importe. Ce sont les trois `ExecStart` du
#: bootstrap : `app.main:app` (API), `control_center.app:app` (cockpit),
#: `agents.cortex.cycle` (digestion).
PAQUETS_DE_SERVICE = ("app", "control_center", "agents")

# ---------------------------------------------------------------------------
# LE VOCABULAIRE DE L'ÉCRITURE
#
# Deux listes, parce que Python homonyme. `str.replace`, `list.remove` et
# `dict.copy` portent le nom d'un geste destructeur sans en être un : les
# confondre rendrait ce garde bruyant, et un garde bruyant finit désarmé.
#
#   · SANS_HOMONYME : ces noms n'appartiennent qu'au disque. On les refuse
#     quel que soit l'objet sur lequel ils sont appelés.
#   · AVEC_HOMONYME : on ne les refuse que si la racine de l'expression est un
#     module de système de fichiers (`os`, `shutil`, `pathlib`, `Path`).
# ---------------------------------------------------------------------------
SANS_HOMONYME = frozenset({
    "mkdir", "makedirs", "write_text", "write_bytes", "touch",
    "rmdir", "unlink", "rmtree", "copytree", "copyfile", "symlink",
    "mkstemp", "mkdtemp", "chmod", "chown", "lchown", "truncate",
})
AVEC_HOMONYME = frozenset({"replace", "remove", "rename", "copy", "copy2", "move", "link"})
RACINES_DE_FICHIER = frozenset({"os", "shutil", "pathlib", "Path", "tempfile"})


def _racine_de_l_expression(noeud: ast.AST) -> str:
    """Le nom le plus à gauche d'une chaîne d'attributs : `os.path.join` → `os`."""
    while isinstance(noeud, (ast.Attribute, ast.Subscript)):
        noeud = noeud.value
    if isinstance(noeud, ast.Call):
        return _racine_de_l_expression(noeud.func)
    return noeud.id if isinstance(noeud, ast.Name) else ""


def _mode_d_ouverture_ecrit(appel: ast.Call) -> bool:
    """`open(p, "w")` / `open(p, mode="a")` écrivent ; `open(p)` ne l'est pas."""
    mode: ast.AST | None = appel.args[1] if len(appel.args) > 1 else None
    for kw in appel.keywords:
        if kw.arg == "mode":
            mode = kw.value
    return (
        isinstance(mode, ast.Constant)
        and isinstance(mode.value, str)
        and any(c in mode.value for c in "wax+")
    )


def ecritures_au_niveau_module(source: str) -> list[tuple[int, str]]:
    """Les appels qui modifient le disque et qui s'exécutent À L'IMPORT.

    On descend dans `if`, `try`, `with`, `for`, `class` — tout cela s'exécute
    quand le module est importé. On s'arrête aux corps de fonctions et aux
    lambdas : ils ne s'exécutent que lorsqu'on les appelle, c'est-à-dire quand
    un appelant a décidé qu'il était temps, en sachant sous quelle identité et
    sur quel disque il tourne.
    """
    trouvailles: list[tuple[int, str]] = []

    def descendre(noeud: ast.AST) -> None:
        for enfant in ast.iter_child_nodes(noeud):
            if isinstance(enfant, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if isinstance(enfant, ast.Call):
                fonction = enfant.func
                nom = (
                    fonction.attr if isinstance(fonction, ast.Attribute)
                    else fonction.id if isinstance(fonction, ast.Name)
                    else ""
                )
                if nom in SANS_HOMONYME:
                    trouvailles.append((enfant.lineno, nom))
                elif nom in AVEC_HOMONYME and isinstance(fonction, ast.Attribute):
                    if _racine_de_l_expression(fonction.value) in RACINES_DE_FICHIER:
                        trouvailles.append((enfant.lineno, nom))
                elif nom == "open" and _mode_d_ouverture_ecrit(enfant):
                    trouvailles.append((enfant.lineno, "open(…, 'w')"))
            descendre(enfant)

    descendre(ast.parse(source))
    return trouvailles


def _modules_de_service() -> list[Path]:
    fichiers: list[Path] = []
    for paquet in PAQUETS_DE_SERVICE:
        racine = RACINE / paquet
        if not racine.is_dir():
            continue
        fichiers += [
            p for p in sorted(racine.rglob("*.py"))
            if "__pycache__" not in p.parts
        ]
    return fichiers


def test_aucun_module_ne_fabrique_sur_le_disque_a_l_import() -> None:
    """Aucune écriture disque au niveau module dans app/, control_center/, agents/.

    Le défaut d'origine — `app/main.py:268` — est ici décrit par sa FORME. Un
    `mkdir` posé demain dans un autre fichier, sous un autre nom de variable,
    est vu le jour où il est écrit, et non le jour où quelqu'un installe.
    """
    fichiers = _modules_de_service()
    assert fichiers, "aucun module de service trouvé — le garde ne mesure rien"

    coupables: list[str] = []
    for chemin in fichiers:
        try:
            source = chemin.read_text(encoding="utf-8")
        except OSError:  # pragma: no cover — un fichier illisible n'est pas un défaut d'import
            continue
        for ligne, geste in ecritures_au_niveau_module(source):
            coupables.append(f"{chemin.relative_to(RACINE)}:{ligne} — {geste}")

    assert not coupables, (
        "Ces modules modifient le disque AU MOMENT DE L'IMPORT :\n\n  "
        + "\n  ".join(coupables)
        + "\n\n"
        "Au moment de l'import, on ne sait ni sous quelle identité on tourne,\n"
        "ni ce qui est monté en écriture, ni si l'on est dans un service, un\n"
        "test, une migration ou un « --help ». Les unités du bootstrap portent\n"
        "ProtectSystem=strict : le dépôt y est en LECTURE SEULE, et une\n"
        "écriture à l'import fait échouer le démarrage avant la première ligne\n"
        "applicative — en boucle, et sans qu'aucun message applicatif ne le\n"
        "dise.\n\n"
        "Ce qui doit exister est créé par CELUI QUI INSTALLE : le bootstrap,\n"
        "StateDirectory=, ReadWritePaths=. Si un chemin doit être écrit pendant\n"
        "l'exécution, créez-le dans la fonction qui écrit, pas à l'import."
    )


# ---------------------------------------------------------------------------
# LA REPRODUCTION
# ---------------------------------------------------------------------------


def _fabriquer_le_clone(destination: Path) -> None:
    """Ce que git transporte, et RIEN d'autre.

    Deux soustractions, et la seconde est celle qui a coûté une installation :

      · les fichiers ignorés (`.gitignore`), le dossier `.git`, `.venv` et les
        caches — un clone ne les porte pas ;
      · **les répertoires VIDES** — git ne suit pas les répertoires, seulement
        les fichiers : un dossier sans fichier suivi n'existe dans aucun clone.
        C'est exactement ce qui est arrivé à `static/`.
    """
    ignores = {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache",
               ".ruff_cache", "logs", "var", "data", "staging", "backups",
               "secrets", "node_modules"}

    def filtrer(dossier: str, noms: list[str]) -> set[str]:
        return {n for n in noms if n in ignores or n.endswith((".pyc", ".log"))}

    shutil.copytree(RACINE, destination, ignore=filtrer, symlinks=True)

    # Les artefacts engendrés et l'identité ne sont dans aucun clone.
    for relatif in (".env", "config/brain.toml", "config/scopes.toml",
                    "config/projects.toml", "config/sensitivity.toml",
                    "config/constitution.md", "app/schemas/scope_generated.py",
                    "db/seeds/scopes.sql"):
        cible = destination / relatif
        if cible.exists():
            cible.unlink()

    # Puis la soustraction qui compte : git ne porte pas un répertoire vide.
    # On boucle, parce qu'en retirer un peut en vider un autre.
    encore = True
    while encore:
        encore = False
        for dossier in sorted(destination.rglob("*"), reverse=True):
            if dossier.is_dir() and not any(dossier.iterdir()):
                dossier.rmdir()
                encore = True


def _inventaire(racine: Path) -> set[str]:
    """L'arborescence, moins le cache d'octets de l'interpréteur.

    `__pycache__` n'est pas une écriture de l'APPLICATION : c'est CPython qui
    mémorise sa compilation, et il sait déjà se taire quand l'arbre est en
    lecture seule (l'échec d'écriture d'un `.pyc` n'est jamais fatal). Le
    sous-processus tourne d'ailleurs avec `-B`, qui la supprime. On l'exclut
    donc explicitement, pour que ce qui reste ne désigne que du code applicatif.
    """
    return {
        str(p.relative_to(racine))
        for p in racine.rglob("*")
        if "__pycache__" not in p.parts and p.suffix != ".pyc"
    }


def _rendre_lecture_seule(racine: Path) -> None:
    for chemin in sorted(racine.rglob("*"), reverse=True):
        mode = chemin.stat().st_mode
        os.chmod(chemin, mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    mode = racine.stat().st_mode
    os.chmod(racine, mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def _rendre_inscriptible(racine: Path) -> None:
    for chemin in [racine, *racine.rglob("*")]:
        try:
            os.chmod(chemin, chemin.stat().st_mode | stat.S_IWUSR)
        except OSError:  # pragma: no cover
            pass


def test_l_api_s_importe_depuis_un_clone_en_lecture_seule(tmp_path: Path) -> None:
    """La scène exacte de l'échec : clone sans répertoire vide, dépôt figé.

    L'assertion est double, et c'est volontaire :

      · le sous-processus doit rendre 0 — sous un compte de service, une
        écriture dans le dépôt lève `OSError: [Errno 30]` et l'import échoue ;
      · le clone doit être IDENTIQUE après l'import — sous root, la même
        écriture RÉUSSIT silencieusement, et seul l'inventaire la voit.

    Un seul de ces deux contrôles laisserait le défaut passer selon l'identité
    de celui qui lance la suite.
    """
    clone = tmp_path / "clone"
    _fabriquer_le_clone(clone)

    assert not (clone / "static").exists(), (
        "le fabricant de clone n'a pas retiré les répertoires vides : "
        "il ne reproduit donc pas ce que git transporte"
    )

    # Ce que fait le bootstrap AVANT de poser les unités : engendrer
    # l'énumération de scopes depuis le modèle. Sans elle, `app.main` refuse de
    # s'importer — et pour une raison qui n'a rien à voir avec ce qu'on mesure.
    shutil.copyfile(clone / "config" / "scopes.example.toml",
                    clone / "config" / "scopes.toml")
    engendre = subprocess.run(
        [sys.executable, str(clone / "bootstrap" / "generate_scopes.py")],
        cwd=clone, capture_output=True, text=True, timeout=120,
    )
    assert engendre.returncode == 0, (
        f"bootstrap/generate_scopes.py a rendu {engendre.returncode} :\n{engendre.stderr[-2000:]}"
    )
    for parasite in clone.rglob("__pycache__"):
        shutil.rmtree(parasite, ignore_errors=True)

    _rendre_lecture_seule(clone)
    try:
        avant = _inventaire(clone)
        # `-c` place le répertoire courant en tête de sys.path : l'`app`
        # importé est celui du CLONE, et le contrôle ci-dessous le prouve.
        programme = (
            "import sys, pathlib\n"
            "import app.main as m\n"
            "assert pathlib.Path(m.__file__).resolve().is_relative_to("
            f"pathlib.Path({str(clone)!r}).resolve()), m.__file__\n"
            "print('IMPORT-OK', m.__file__)\n"
        )
        # `-B` : pas de `.pyc`. Pas pour cacher une écriture — CPython tolère
        # déjà un arbre figé — mais pour que l'inventaire ne parle que de code
        # applicatif. `-I`, `-E` et `-S` sont, eux, interdits par le garde
        # hermétique : ils désarmeraient le `sitecustomize` du fils.
        resultat = subprocess.run(
            [sys.executable, "-B", "-c", programme],
            cwd=clone, capture_output=True, text=True, timeout=180,
        )
        apres = _inventaire(clone)
    finally:
        _rendre_inscriptible(clone)

    assert resultat.returncode == 0, (
        "L'API ne s'importe pas depuis un clone en lecture seule — c'est\n"
        "l'échec de démarrage que voit celui qui installe, en boucle, avant\n"
        "toute ligne applicative :\n\n"
        f"{resultat.stderr[-3000:]}"
    )
    assert "IMPORT-OK" in resultat.stdout

    nes = sorted(apres - avant)
    assert not nes, (
        "L'import a FABRIQUÉ ceci dans le dépôt :\n\n  "
        + "\n  ".join(nes)
        + "\n\n"
        "Sous root l'écriture réussit et personne ne la voit ; sous le compte\n"
        "de service, `ProtectSystem=strict` la refuse et l'unité ne démarre\n"
        "jamais. Le dépôt est du code : il est monté en lecture seule."
    )
