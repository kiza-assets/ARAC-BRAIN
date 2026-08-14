#!/usr/bin/env python3
"""audit_schema_refs.py — le code et le schéma disent-ils la même chose ?

POURQUOI CE FICHIER EXISTE
==========================

Une table absente ne fait aucun bruit. `arac.memory_review_queue` était lue par
deux consommateurs de production — la métrique de profondeur des files de revue
(`app/perception/ingest_watchdog.py`) et le résumé servi par le cockpit
(`control_center/collectors/db_metrics.py`) — et créée par AUCUNE migration. Son
DDL dormait dans `db/migrations/proposals/`, un répertoire que rien n'applique.
Les deux lecteurs dégradent proprement (SAVEPOINT, try/except) : la panne était
donc silencieuse, permanente, et invisible à l'installation comme aux tests.

Aucun garde-fou du dépôt ne pouvait l'attraper, parce qu'aucun ne CROISAIT les
deux moitiés de la vérité : ce que le code nomme, et ce que les migrations
bâtissent. C'est ce croisement, et rien d'autre, que fait ce fichier.

CE QU'IL COMPARE
================

  · à gauche — les objets `arac.<nom>` que le CODE nomme (app/, agents/,
    control_center/, scripts/, ops/, bootstrap/). Deux formes sont reconnues :
    la référence SQL (précédée de FROM, JOIN, INSERT INTO, REFERENCES…) et le
    nom de table porté par un littéral de chaîne, parce que la moitié des
    requêtes de ce dépôt sont assemblées à partir d'un nom en variable ;

  · à droite — les objets que le SCHÉMA porte. Deux sources possibles :
      · par défaut, la lecture STATIQUE des migrations (`db/`) : hermétique,
        sans base, donc jouable dans `make test` et dans l'intégration continue ;
      · avec `--objets`, la liste RÉELLE lue dans le catalogue d'une base
        installée — c'est ce que fait `verify_install.sh`, et c'est la seule
        mesure qui fasse foi sur une machine.

    Les deux sont utiles et ne disent pas la même chose : la première attrape le
    défaut dans le dépôt AVANT l'installation, la seconde attrape la base qui a
    dérivé de ses migrations.

CE QU'IL N'EST PAS
==================

Ce n'est pas un analyseur SQL. Il ne cherche pas à comprendre les requêtes : il
relève des NOMS. Le prix de cette simplicité est une famille de faux positifs
connue et nommée ci-dessous (`_NON_RELATION`) : `arac.` sert aussi de préfixe à
des hiérarchies de journaux (`logging.getLogger("arac.api")`), à des noms
d'événements SSE et à des canaux LISTEN/NOTIFY. Ces lignes sont écartées par
leur CONTEXTE, jamais par une liste de noms — une liste de noms se périme en
silence, un contexte se relit.

Sortie : 0 tout se résout · 1 au moins une référence sans objet · 2 non mesuré.

Usage :
    python3 bootstrap/checks/audit_schema_refs.py
    python3 bootstrap/checks/audit_schema_refs.py --objets liste.txt
    ... | python3 bootstrap/checks/audit_schema_refs.py --objets -
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]

#: Là où vit le CODE qui consomme le schéma. `db/` en est absent volontairement :
#: c'est la DÉFINITION, pas un consommateur, et ses `downgrade()` nomment des
#: tables qu'ils viennent de supprimer.
RACINES_CODE = ("app", "agents", "control_center", "scripts", "ops", "bootstrap")

#: Là où vit la définition du schéma, quand on la lit statiquement.
#: `db/migrations/proposals/` est EXCLU, et c'est tout le sujet : un DDL posé
#: dans un répertoire que rien n'applique n'est pas un schéma, c'est une note.
SOURCES_SCHEMA = (
    "db/migrations/*.sql",
    "db/alembic/versions/*.py",
)

EXTENSIONS = {".py", ".sql", ".sh"}

#: Une référence à une relation, dans sa forme SQL. Le mot-clé qui précède est
#: ce qui distingue « la table arac.x » de « le journal arac.x ».
_REF_SQL = re.compile(
    r"\b(?:FROM|JOIN|INTO|UPDATE|TABLE|REFERENCES|TRUNCATE|ANALYZE)\s+"
    r"arac\.([a-z_][a-z0-9_]*)",
    re.IGNORECASE,
)

#: Un nom de table porté par un littéral : `("memory_review_queue",
#: "arac.memory_review_queue", …)` puis `f"SELECT … FROM {table}"`. Sans cette
#: seconde forme, la référence qui manquait ici serait passée inaperçue.
_REF_LITTERAL = re.compile(r"""['"]arac\.([a-z_][a-z0-9_]*)['"]""")

#: Les autres habitants du préfixe `arac.`, reconnus à leur CONTEXTE de ligne.
#: Chacun est un espace de noms légitime qui n'a jamais été un objet SQL :
#:   getLogger/logging/logger  la hiérarchie des journaux (« arac.api », « arac.cortex ») ;
#:   event_name                le nom d'événement du flux SSE du cockpit (« arac.event ») ;
#:   NOTIFY/LISTEN/channel     les canaux PostgreSQL, qui ne sont pas des relations ;
#:   SyslogIdentifier          l'étiquette de journal des unités systemd.
_NON_RELATION = re.compile(
    r"getLogger|logging\.|\blogger\b|LOGGER|event_name|SyslogIdentifier"
    r"|\bNOTIFY\b|\bLISTEN\b|channel",
    re.IGNORECASE,
)

#: Ce qu'une migration BÂTIT. On ne lit que les créations : les `DROP` des
#: `downgrade()` retireraient de la liste des tables parfaitement présentes.
_CREE = re.compile(
    r"\bCREATE\s+(?:OR\s+REPLACE\s+)?"
    r"(?:TABLE|(?:MATERIALIZED\s+)?VIEW|SEQUENCE|INDEX|FUNCTION)\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?:CONCURRENTLY\s+)?"
    r"arac\.([a-z_][a-z0-9_]*)",
    re.IGNORECASE,
)
#: `CREATE INDEX <nom> ON arac.<table>` : l'index n'est pas préfixé, la table si.
#: On enregistre les deux — l'index est un objet du schéma, lui aussi nommable.
_CREE_INDEX = re.compile(
    r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?"
    r"([a-z_][a-z0-9_]*)\s+ON\s+(?:ONLY\s+)?arac\.([a-z_][a-z0-9_]*)",
    re.IGNORECASE,
)


def _lignes_utiles(chemin: Path) -> list[tuple[int, str]]:
    """Les lignes du fichier, commentaires de bout de ligne retirés.

    Un commentaire qui NOMME une table n'est pas une référence : l'en-tête de
    `01_init.sql` annonçait `memory_review_queue` sans qu'aucun code ne la lise.
    Compter les commentaires reviendrait à croire un fichier sur parole, ce qui
    est exactement le défaut qu'on cherche.
    """
    try:
        brut = chemin.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    sortie = []
    for n, ligne in enumerate(brut.splitlines(), 1):
        nu = ligne.lstrip()
        if nu.startswith("#") or nu.startswith("--"):
            continue
        sortie.append((n, ligne))
    return sortie


def references(racine: Path) -> dict[str, list[str]]:
    """Les objets `arac.<nom>` que le code nomme → où il les nomme."""
    trouve: dict[str, list[str]] = {}
    for dossier in RACINES_CODE:
        base = racine / dossier
        if not base.is_dir():
            continue
        for chemin in sorted(base.rglob("*")):
            if chemin.suffix not in EXTENSIONS or "__pycache__" in chemin.parts:
                continue
            for n, ligne in _lignes_utiles(chemin):
                noms = set(_REF_SQL.findall(ligne))
                if not _NON_RELATION.search(ligne):
                    noms |= set(_REF_LITTERAL.findall(ligne))
                for nom in noms:
                    trouve.setdefault(nom.lower(), []).append(
                        f"{chemin.relative_to(racine)}:{n}"
                    )
    return trouve


def schema_statique(racine: Path) -> set[str]:
    """Les objets que les migrations du dépôt BÂTISSENT."""
    objets: set[str] = set()
    for motif in SOURCES_SCHEMA:
        for chemin in sorted(racine.glob(motif)):
            for _n, ligne in _lignes_utiles(chemin):
                objets.update(m.lower() for m in _CREE.findall(ligne))
                for index, table in _CREE_INDEX.findall(ligne):
                    objets.add(index.lower())
                    objets.add(table.lower())
    return objets


def schema_depuis_fichier(source) -> set[str]:
    """Les objets que porte une base RÉELLE : un nom par ligne."""
    return {
        ligne.strip().lower()
        for ligne in source
        if ligne.strip() and not ligne.lstrip().startswith("#")
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Croise les références arac.<objet> du code et le schéma bâti."
    )
    p.add_argument("--racine", default=str(RACINE), help="racine du dépôt")
    p.add_argument(
        "--objets",
        help="fichier (ou « - ») listant les objets RÉELS du schéma, un par "
        "ligne. Sans lui, le schéma est déduit statiquement des migrations.",
    )
    p.add_argument("--silencieux", action="store_true", help="n'affiche que les manques")
    a = p.parse_args(argv)

    racine = Path(a.racine).resolve()
    if not (racine / "db").is_dir():
        print(f"  db/ introuvable sous {racine} — rien n'a pu être croisé.", file=sys.stderr)
        return 2

    if a.objets:
        try:
            if a.objets == "-":
                bati = schema_depuis_fichier(sys.stdin)
            else:
                with open(a.objets, encoding="utf-8") as fh:
                    bati = schema_depuis_fichier(fh)
        except OSError as e:
            print(f"  liste d'objets illisible : {e}", file=sys.stderr)
            return 2
        origine = "le catalogue de la base installée"
        if not bati:
            print("  la liste d'objets est vide — rien n'a pu être croisé.", file=sys.stderr)
            return 2
    else:
        bati = schema_statique(racine)
        origine = "les migrations du dépôt (lecture statique)"
        if not bati:
            print("  aucune migration lisible — rien n'a pu être croisé.", file=sys.stderr)
            return 2

    nommes = references(racine)
    if not nommes:
        print("  aucune référence arac.<objet> trouvée — rien n'a pu être croisé.",
              file=sys.stderr)
        return 2

    manquants = {n: ou for n, ou in sorted(nommes.items()) if n not in bati}

    if not a.silencieux:
        print(f"  {len(nommes)} objet(s) nommé(s) par le code, "
              f"{len(bati)} porté(s) par {origine}.")

    if not manquants:
        if not a.silencieux:
            print("  Toutes les références se résolvent.")
        return 0

    print()
    print("  Références sans objet dans le schéma :")
    for nom, endroits in manquants.items():
        print(f"    arac.{nom}  ({len(endroits)} référence(s))")
        for e in endroits[:5]:
            print(f"        {e}")
        if len(endroits) > 5:
            print(f"        … et {len(endroits) - 5} autre(s)")
    print()
    print("  Deux issues, et il faut trancher — pas laisser en l'état :")
    print("    · l'objet doit exister  → une MIGRATION le crée (jamais un")
    print("      correctif à la main : la base suivante ne l'aurait pas) ;")
    print("    · l'objet est mort      → retirez ses lecteurs, qui dégradent")
    print("      aujourd'hui en silence et ne remonteront jamais rien.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
