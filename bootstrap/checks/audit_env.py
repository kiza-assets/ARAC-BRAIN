#!/usr/bin/env python3
"""audit_env.py — le fichier canonique dit-il la vérité sur le code ?

POURQUOI CE CONTRÔLE EXISTE
---------------------------
Une variable d'environnement documentée mais que personne ne lit est pire
qu'une variable absente. L'absente se remarque : rien ne marche, on cherche.
La fausse, elle, se copie fidèlement, se relit, se vérifie à l'œil — et le
service refuse quand même de démarrer, sans jamais dire pourquoi.

Ce dépôt a payé le prix exact de ce défaut : `.env.example` proposait
`CC_PASSWORD_HASH`, le cockpit lisait `CC_ADMIN_PASSWORD_HASH`. Un nom.
Personne ne pouvait se connecter, et le fichier canonique jurait le contraire.

Le défaut symétrique est plus cruel encore : une variable lue par le code,
*fail-closed*, absente du fichier canonique. `ARAC_INGEST_ALLOWED_NODES` en
est l'exemple : sans elle l'ingestion refuse TOUT en `403`. Tout est installé,
tout semble vivant, et rien n'entre.

CE QUE CE CONTRÔLE PROUVE — exactement, ni plus
-----------------------------------------------
1. Aucun nom écrit dans `.env.example` n'est INCONNU du code de ce dépôt.
2. Aucun nom connu du code n'est absent À LA FOIS de `.env.example` et de
   `bootstrap/checks/env_contract.toml`.

« Connu du code » veut dire : le nom apparaît littéralement dans un fichier
source, comme chaîne Python ou comme référence shell. Ce contrôle ne prouve
donc PAS qu'une variable est *utilisée* utilement — il prouve qu'elle n'est
pas MORTE. C'est la moitié vérifiable mécaniquement, et c'est celle qui a
cassé des installations.

Un nom qui n'apparaît nulle part dans le code est, lui, mort avec certitude.

POURQUOI UN FICHIER DE CONTRAT
------------------------------
Le code lit beaucoup plus de variables que `.env.example` n'en montre, et
c'est voulu : un fichier canonique de deux cents entrées ne s'installe pas,
il se subit. Mais « voulu » doit être ÉCRIT, sinon la dérive revient. Chaque
variable lue par le code est donc soit dans `.env.example`, soit rangée dans
`env_contract.toml` sous un motif explicite. Une nouvelle variable qui
n'apparaît dans aucun des deux fait échouer ce contrôle : son auteur doit
choisir — la documenter, ou déclarer pourquoi elle n'a pas à l'être.

PÉRIMÈTRE
---------
Les espaces de noms du cerveau (`ARAC_`, `CC_`, `DATABASE_URL*`, les clés des
deux fournisseurs, `TELEGRAM_`, plus quelques noms historiques nommément
listés). Les variables du système (`PATH`, `HOME`, `PG*`…) n'appartiennent
pas à ce dépôt : il ne les documente pas et ne les contrôle pas.

Les tests sont EXCLUS du balayage. Un test qui pose une variable prouve que
le test la connaît, pas que le cerveau la lit.

USAGE
    python3 bootstrap/checks/audit_env.py           # rapport lisible
    python3 bootstrap/checks/audit_env.py --silence # rien si tout va bien

SORTIE
    0  le fichier canonique et le code disent la même chose
    1  divergence : chaque écart est listé avec le geste qui le corrige
    2  le contrôle lui-même n'a pas pu se faire (fichier manquant, TOML illisible)
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]


class SourceIncomplete(RuntimeError):
    """Le dépôt balayé n'est pas complet : aucun verdict n'est fondable."""

#: Ce que ce contrôle regarde. Hors de ces espaces de noms, une variable
#: appartient au système d'exploitation ou à un outil tiers : ce dépôt n'a
#: aucune autorité pour la documenter, et se taire vaut mieux que mentir.
PREFIXES = ("ARAC_", "CC_", "DATABASE_URL", "OPENAI_", "ANTHROPIC_", "TELEGRAM_")
NOMS_EXACTS = frozenset({"LOG_LEVEL", "MAX_INGEST_SIZE_BYTES"})

#: Les racines elles-mêmes, sans leur soulignement final. Le TRAIT FINAL est
#: ce qui distingue la racine de la variable : `DATABASE_URL` est une variable
#: (Alembic la lit), `DATABASE_URL_` est le préfixe d'un balayage. La règle ne
#: coûte donc rien aux noms réels, et vaut pour une racine ajoutée demain —
#: elle ne cite aucune des deux qui l'ont fait naître.
_RACINES = frozenset(p.rstrip("_") for p in PREFIXES)

#: Là où vit le code. `tests/` est absent, délibérément.
SOURCES = (
    "app", "agents", "control_center", "bootstrap", "ops",
    "scripts", "db", "deploy", "mac",
)

#: Sans ces dossiers-là, le balayage ne trouve presque rien — et « presque
#: rien de lu » ressemble trait pour trait à « tout est faux ». Le contrôle
#: rendrait alors un verdict accablant sur un dépôt parfaitement sain, ce qui
#: est exactement le défaut qu'il est censé traquer. Il s'arrête plutôt.
SOURCES_INDISPENSABLES = ("app", "agents", "control_center", "ops", "bootstrap")
FICHIERS_RACINE = ("arac_runtime.py", "alembic.ini", "Makefile")

SUFFIXES = {".py", ".sh", ".ini", ".toml", ".cfg", ".service", ".timer", ".conf"}

#: Une chaîne Python qui EST un nom de variable, et rien d'autre. C'est ce qui
#: attrape `os.environ.get("X")`, `_ENV_X = "X"` et `_env_flag("X")` d'un seul
#: motif — le code lit ses variables de trois façons, on ne veut pas en
#: connaître une quatrième pour que le contrôle continue de marcher.
LITTERAL_PY = re.compile(r"""["']([A-Z][A-Z0-9_]{2,})["']""")

#: Hors Python, un nom de variable est un MOT, pas une chaîne : `${X:-défaut}`,
#: `$X`, `lire_var "$f" ARAC_X`, `for cle in ARAC_A ARAC_B`. Aucun de ces
#: dialectes ne se réduit à l'autre, alors on cherche le mot nu — dans l'espace
#: de noms du cerveau, où un mot en majuscules N'EST rien d'autre qu'une
#: variable.
MOT_SH = re.compile(
    r"\b(?:ARAC_[A-Z0-9_]+|CC_[A-Z0-9_]+|DATABASE_URL[A-Z0-9_]*"
    r"|OPENAI_[A-Z0-9_]+|ANTHROPIC_[A-Z0-9_]+|TELEGRAM_[A-Z0-9_]+"
    r"|LOG_LEVEL|MAX_INGEST_SIZE_BYTES)\b"
)

#: Ce contrôle se lit lui-même s'il se balaie : il CITE des noms de variables
#: pour les chercher. On l'exclut, sinon il se déclare source de vérité.
EXCLUS = {"bootstrap/checks/audit_env.py", "bootstrap/checks/env_contract.toml"}

#: Un nom documenté dans `.env.example` : en début de ligne, actif ou proposé
#: en commentaire. Une variable proposée engage autant qu'une variable posée —
#: elle sera décommentée par quelqu'un.
DOC_ENV = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]{2,})\s*=")


def concerne(nom: str) -> bool:
    """Ce nom appartient-il à l'espace de noms du cerveau — et est-ce un NOM ?

    LA RACINE D'UNE FAMILLE N'EST PAS UNE VARIABLE, ET LA CONFONDRE ACCUSE LE
    CODE CORRECT. `agents/lib/paid_ai_control.py:111` écrit
    `cle.startswith("DATABASE_URL_") or cle.startswith("ARAC_")` : il BALAIE
    l'environnement pour n'en garder que ce qui appartient à ce cerveau-là. Ces
    deux littéraux sont les racines déclarées en tête de ce fichier, pas des
    variables — personne ne pose `ARAC_=…`. Le contrôle les lisait pourtant
    comme des noms, les déclarait NON CLASSÉES, et rendait 1.

    Le geste qu'il suggérait alors était pire que le défaut : ranger `ARAC_`
    dans `[familles] prefixes` aurait fait passer, d'un coup, TOUTES les
    variables du cerveau pour déclarées — `nom.startswith(p)` les couvre
    toutes. Le contrat serait resté vert pour toujours, sur un dépôt où plus
    rien n'est déclaré. Une racine se reconnaît donc ici, à sa forme, et ne
    peut plus être « classée » nulle part.
    """
    if nom.endswith("_") and nom.rstrip("_") in _RACINES:
        return False
    return nom in NOMS_EXACTS or nom.startswith(PREFIXES)


# ---------------------------------------------------------------------------
# Lecture des trois sources de vérité
# ---------------------------------------------------------------------------


def lire_documentees(chemin: Path) -> dict[str, int]:
    """Les noms écrits dans `.env.example`, et leur ligne."""
    trouves: dict[str, int] = {}
    for numero, ligne in enumerate(chemin.read_text(encoding="utf-8").splitlines(), 1):
        m = DOC_ENV.match(ligne)
        if m and concerne(m.group(1)):
            trouves.setdefault(m.group(1), numero)
    return trouves


def fichiers_source() -> list[Path]:
    vus: list[Path] = []
    for nom in SOURCES:
        base = RACINE / nom
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*")):
            if not f.is_file() or "__pycache__" in f.parts:
                continue
            if f.suffix in SUFFIXES or "template" in f.name:
                vus.append(f)
    for nom in FICHIERS_RACINE:
        f = RACINE / nom
        if f.is_file():
            vus.append(f)
    return vus


def lire_connues() -> dict[str, set[str]]:
    """Les noms qui apparaissent dans le code, et où."""
    connues: dict[str, set[str]] = {}

    def poser(nom: str, fichier: Path) -> None:
        if concerne(nom):
            connues.setdefault(nom, set()).add(
                str(fichier.relative_to(RACINE))
            )

    for f in fichiers_source():
        if str(f.relative_to(RACINE)) in EXCLUS:
            continue
        try:
            texte = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if f.suffix == ".py":
            for m in LITTERAL_PY.finditer(texte):
                poser(m.group(1), f)
        else:
            # Les lignes de commentaire sont retirées : un nom CITÉ n'est pas
            # un nom LU. Sans ce tri, il suffirait d'écrire « ne posez pas
            # ARAC_TRUC » quelque part pour que le contrôle croie que
            # ARAC_TRUC existe — et ce dépôt commente beaucoup.
            for ligne in texte.splitlines():
                if ligne.lstrip().startswith("#"):
                    continue
                for m in MOT_SH.finditer(ligne):
                    poser(m.group(0), f)
    return connues


def lire_contrat(chemin: Path) -> tuple[dict[str, str], tuple[str, ...]]:
    """Le contrat : {nom: motif} et les familles à préfixe."""
    donnees = tomllib.loads(chemin.read_text(encoding="utf-8"))
    motifs: dict[str, str] = {}
    for groupe in donnees.get("groupe", []):
        raison = groupe.get("raison", "").strip()
        if not raison:
            raise ValueError(
                "un groupe du contrat n'a pas de `raison` : un classement sans "
                "motif n'est pas un contrat, c'est une liste d'exceptions."
            )
        for nom in groupe.get("variables", []):
            if nom in motifs:
                raise ValueError(f"{nom} est classé deux fois dans le contrat")
            motifs[nom] = raison
    prefixes = tuple(donnees.get("familles", {}).get("prefixes", []))
    return motifs, prefixes


# ---------------------------------------------------------------------------
# Le contrôle
# ---------------------------------------------------------------------------


def auditer() -> tuple[list[str], list[str]]:
    """Rend (fantomes, non_classees)."""
    env_example = RACINE / ".env.example"
    contrat = RACINE / "bootstrap" / "checks" / "env_contract.toml"
    for f in (env_example, contrat):
        if not f.is_file():
            raise FileNotFoundError(f)

    manquants = [d for d in SOURCES_INDISPENSABLES if not (RACINE / d).is_dir()]
    if manquants:
        raise SourceIncomplete(
            f"il manque {', '.join(manquants)} sous {RACINE}. Sans le code, "
            f"ce contrôle déclarerait fausse chaque variable du fichier "
            f"canonique — un verdict qu'il n'a pas les moyens de fonder. "
            f"Ce contrôle audite l'arbre qui CONTIENT ce script, pas une "
            f"installation déployée : lancez-le depuis un dépôt complet."
        )

    documentees = lire_documentees(env_example)
    connues = lire_connues()
    motifs, prefixes = lire_contrat(contrat)

    def le_code_connait(nom: str) -> bool:
        if nom in connues:
            return True
        # Une famille à préfixe : `app/auth.py` balaie l'environnement à la
        # recherche de `ARAC_NODE_TOKEN_`. Aucun nom complet n'existe dans le
        # code, et c'est correct — c'est le préfixe qui est lu.
        return any(
            nom.startswith(p) and p in connues for p in prefixes
        )

    # Une variable documentée que le code ignore est un fantôme — SAUF si le
    # contrat l'a nommément justifiée (cas d'un programme tiers qui la
    # consomme). L'exception doit être écrite quelque part ; le silence n'en
    # est pas une.
    fantomes = [
        f"{nom}  (.env.example ligne {ligne}) — aucun fichier source ne "
        f"contient ce nom"
        for nom, ligne in sorted(documentees.items())
        if not le_code_connait(nom) and nom not in motifs
    ]

    non_classees = [
        f"{nom}  (lue dans {', '.join(sorted(connues[nom])[:3])})"
        for nom in sorted(connues)
        if nom not in documentees
        and nom not in motifs
        and not any(nom.startswith(p) for p in prefixes)
    ]
    return fantomes, non_classees


def main() -> int:
    p = argparse.ArgumentParser(add_help=True, description=__doc__)
    p.add_argument("--silence", action="store_true",
                   help="n'écrit que si quelque chose ne va pas")
    args = p.parse_args()

    try:
        fantomes, non_classees = auditer()
    except (FileNotFoundError, SourceIncomplete, ValueError,
            tomllib.TOMLDecodeError) as e:
        print(f"Le contrôle n'a pas pu se faire : {e}", file=sys.stderr)
        return 2

    if not fantomes and not non_classees:
        if not args.silence:
            print("Le contrat des variables tient : "
                  ".env.example et le code disent la même chose.")
        return 0

    if fantomes:
        print()
        print("VARIABLES FANTÔMES — documentées, jamais lues")
        print()
        print("  Quelqu'un va les recopier dans son `.env`, et attendre un effet")
        print("  qui ne viendra pas. C'est le défaut le plus coûteux du lot :")
        print("  il ne produit aucun message d'erreur.")
        print()
        for f in fantomes:
            print(f"    ✗ {f}")
        print()
        print("  Le geste : dans `.env.example`, corrigez le nom en celui que le")
        print("  code lit réellement — ou retirez la ligne. Si la variable est")
        print("  bien consommée mais par un programme TIERS (le binaire `claude`,")
        print("  par exemple), rangez-la dans `bootstrap/checks/env_contract.toml`")
        print("  avec le motif : le contrat accepte l'exception, pas l'oubli.")

    if non_classees:
        print()
        print("VARIABLES NON CLASSÉES — lues par le code, nulle part déclarées")
        print()
        print("  Le code s'en sert ; ni le fichier canonique ni le contrat n'en")
        print("  parlent. Tant qu'elle reste implicite, personne ne peut savoir")
        print("  qu'elle existe — ni ce qui casse quand elle manque.")
        print()
        for f in non_classees:
            print(f"    ✗ {f}")
        print()
        print("  Le geste : documentez-la dans `.env.example` si l'installateur")
        print("  doit la poser ; sinon rangez-la dans un groupe de")
        print("  `bootstrap/checks/env_contract.toml`, avec le motif qui explique")
        print("  pourquoi elle n'a pas à figurer dans le fichier canonique.")
    print()
    return 1


if __name__ == "__main__":
    sys.exit(main())
