#!/usr/bin/env python3
"""generate_scopes.py — la taxonomie de l'utilisateur devient du code et du schéma.

ARAC refuse tout scope hors liste : l'API répond 422, la base rejette par clé
étrangère. Cette rigidité est voulue — sans elle, la mémoire se fragmente en
catégories jumelles et le rappel se dilue. Mais elle impose que la liste soit
DÉCLARÉE quelque part, et jusqu'ici elle l'était en dur dans le code source,
avec les scopes d'une seule personne.

Ce script déplace cette déclaration dans ``config/scopes.toml``, que
l'utilisateur écrit, et génère depuis lui les deux artefacts qui la font
respecter :

  1. ``app/schemas/scope_generated.py`` — l'énumération Pydantic, premier
     rempart : un scope inconnu est refusé avant même d'atteindre la base ;
  2. ``db/seeds/scopes.sql`` — le peuplement de ``arac.scopes``, source de
     vérité côté base, référencée par ``memory_atoms.scope``.

Les deux sortent du MÊME fichier : ils ne peuvent donc plus diverger. C'était
un vrai défaut du cerveau de référence, où trois docstrings annonçaient
34, 40 et 45 scopes pendant que la base en portait 38.

SÛRETÉ : ce script n'écrit jamais en base. Il produit du SQL que le bootstrap
applique ensuite, après vous l'avoir montré. Une suppression de scope est
refusée tant que des atomes y vivent — le script vous dit lesquels.

Usage :
    python3 bootstrap/generate_scopes.py --config config/scopes.toml
    python3 bootstrap/generate_scopes.py --config config/scopes.toml --check
    python3 bootstrap/generate_scopes.py --config config/scopes.toml --dsn "$DATABASE_URL"
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    print("ARAC exige Python 3.11 ou plus récent (module tomllib).", file=sys.stderr)
    raise SystemExit(3)

CLE = re.compile(r"^[a-z][a-z0-9-]*$")

#: Noms qu'un scope ne peut pas porter : ils entreraient en collision avec des
#: mots réservés SQL, des identifiants Python, ou des conventions du moteur.
INTERDITS = frozenset({
    "all", "none", "null", "true", "false", "select", "from", "where", "table",
    "class", "def", "import", "return", "global", "pass", "scope", "atom",
})


class Refus(Exception):
    """Une taxonomie invalide. Le message dit quoi corriger, et où."""


# ---------------------------------------------------------------------------
# Lecture et validation
# ---------------------------------------------------------------------------


def lire(chemin: Path) -> dict:
    if not chemin.exists():
        raise Refus(
            f"{chemin} est introuvable.\n"
            f"  Copiez le modèle :  cp config/scopes.example.toml {chemin}\n"
            "  puis décrivez VOS domaines avant de relancer le bootstrap."
        )
    try:
        with chemin.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise Refus(f"{chemin} n'est pas un TOML valide : {exc}") from exc


def _valider_cle(cle: str, ou: str) -> None:
    if not CLE.match(cle or ""):
        raise Refus(
            f"{ou} : clé {cle!r} invalide.\n"
            "  Attendu : minuscules, chiffres et tirets, commençant par une lettre.\n"
            "  Cette clé devient un chemin en base et un membre d'énumération : "
            "elle ne peut contenir ni espace, ni accent, ni majuscule."
        )
    if cle in INTERDITS:
        raise Refus(f"{ou} : {cle!r} est un mot réservé. Choisissez un autre nom.")


def valider(conf: dict) -> tuple[list[dict], list[dict], dict]:
    """Retourne (racines, feuilles, options). Lève ``Refus`` avec un message utile."""
    options = conf.get("taxonomy") or {}
    profondeur = int(options.get("max_depth", 2))
    if profondeur not in (2, 3):
        raise Refus("taxonomy.max_depth doit valoir 2 ou 3 — au-delà, plus personne ne "
                    "retrouve ses souvenirs.")

    racines = list(conf.get("root") or [])
    feuilles = list(conf.get("leaf") or [])

    if not racines:
        raise Refus("Aucune racine déclarée. Un cerveau sans domaine ne peut rien ranger.\n"
                    "  Déclarez au moins une section [[root]].")
    if not feuilles:
        raise Refus(
            "Aucune feuille déclarée — et c'est l'erreur la plus coûteuse possible.\n"
            "  LES ATOMES VIVENT SUR LES FEUILLES. Un atome posé sur une racine devient\n"
            "  orphelin : la similarité pure peut encore le faire remonter, mais il est\n"
            "  exclu de l'état courant, de la vue des scopes et de la couverture, et une\n"
            "  recherche qui précise un domaine ne le trouvera jamais — l'égalité de\n"
            "  scope est stricte.\n"
            "  Déclarez au moins une [[leaf]] par racine utile."
        )

    vues: set[str] = set()
    for r in racines:
        _valider_cle(r.get("key", ""), "[[root]]")
        if r["key"] in vues:
            raise Refus(f"[[root]] : racine {r['key']!r} déclarée deux fois.")
        vues.add(r["key"])
        if not (r.get("label") or "").strip():
            raise Refus(f"[[root]] {r['key']!r} : `label` obligatoire (c'est ce qui s'affiche).")

    chemins: set[str] = set()
    par_racine: dict[str, int] = {k: 0 for k in vues}
    for f in feuilles:
        _valider_cle(f.get("key", ""), "[[leaf]]")
        racine = f.get("root", "")
        if racine not in vues:
            raise Refus(
                f"[[leaf]] {f['key']!r} : racine {racine!r} inconnue.\n"
                f"  Racines déclarées : {', '.join(sorted(vues))}"
            )
        chemin = f"{racine}/{f['key']}"
        if chemin in chemins:
            raise Refus(f"[[leaf]] : chemin {chemin!r} déclaré deux fois.")
        chemins.add(chemin)
        par_racine[racine] += 1
        if not (f.get("label") or "").strip():
            raise Refus(f"[[leaf]] {chemin!r} : `label` obligatoire.")

    orphelines = [k for k, n in par_racine.items() if n == 0]
    if orphelines:
        raise Refus(
            f"Racine(s) sans aucune feuille : {', '.join(orphelines)}.\n"
            "  Une racine sans feuille ne peut RIEN stocker de rappelable.\n"
            "  Ajoutez-lui une feuille, ou retirez-la."
        )

    return racines, feuilles, options


# ---------------------------------------------------------------------------
# Génération
# ---------------------------------------------------------------------------


def _membre(chemin: str) -> str:
    """Le nom du membre d'énumération pour un chemin de scope."""
    sans_accent = "".join(
        c for c in unicodedata.normalize("NFD", chemin) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^A-Z0-9]+", "_", sans_accent.upper()).strip("_")


def enum_python(racines: list[dict], feuilles: list[dict], source: Path) -> str:
    lignes: list[str] = []
    a = lignes.append
    a('"""Énumération des scopes — FICHIER GÉNÉRÉ, NE PAS ÉDITER À LA MAIN.')
    a("")
    a(f"Source de vérité : {source}")
    a(f"Régénéré par : bootstrap/generate_scopes.py")
    a("")
    a("Toute modification manuelle sera écrasée au prochain bootstrap. Pour changer")
    a("la taxonomie, éditez le fichier de configuration puis relancez :")
    a("")
    a("    ./bootstrap/bootstrap.sh --scopes-only")
    a("")
    a("RAPPEL : les atomes vivent sur les FEUILLES — la racine est un conteneur,")
    a("pas un rangement. Un atome posé sur une racine devient orphelin : encore")
    a("rappelable par similarité pure, mais exclu de l'état courant, de la vue des")
    a("scopes et de la couverture, et introuvable par une recherche qui précise un")
    a("domaine (l'égalité de scope est stricte).")
    a('"""')
    a("")
    a("from __future__ import annotations")
    a("")
    a("from enum import Enum")
    a("")
    a("")
    a("class Scope(str, Enum):")
    a(f'    """{len(racines)} racines + {len(feuilles)} feuilles = '
      f'{len(racines) + len(feuilles)} scopes."""')
    a("")
    a("    # --- RACINES (depth=0) : conteneurs, pas rangements ---")
    for r in racines:
        a(f'    {_membre(r["key"])} = "{r["key"]}"')
    a("")
    a("    # --- FEUILLES (depth=1) : c'est ici que le savoir vit ---")
    courante = None
    for f in sorted(feuilles, key=lambda x: (x["root"], x["key"])):
        if f["root"] != courante:
            courante = f["root"]
            a(f"    # {courante}")
        a(f'    {_membre(f"{f["root"]}/{f["key"]}")} = "{f["root"]}/{f["key"]}"')
    a("")
    a("")
    a("#: Les racines seules. Un atome posé là reste rappelable par similarité")
    a("#: pure, mais il est exclu de l'état courant, de la vue des scopes et de la")
    a("#: couverture, et une recherche qui précise un domaine ne le trouvera pas")
    a("#: (l'égalité de scope est stricte). Voir docs/COMMENT-IL-CREE-SES-SCOPES.md §4.")
    a("ROOTS: frozenset[str] = frozenset({")
    for r in racines:
        a(f'    "{r["key"]}",')
    a("})")
    a("")
    a("#: Les feuilles seules — les seuls scopes où un atome doit être posé.")
    a("LEAVES: frozenset[str] = frozenset({")
    for f in sorted(feuilles, key=lambda x: (x["root"], x["key"])):
        a(f'    "{f["root"]}/{f["key"]}",')
    a("})")
    a("")
    a("#: Libellés affichés par le cockpit.")
    a("LABELS: dict[str, str] = {")
    for r in racines:
        a(f'    "{r["key"]}": {r["label"]!r},')
    for f in sorted(feuilles, key=lambda x: (x["root"], x["key"])):
        a(f'    "{f["root"]}/{f["key"]}": {f["label"]!r},')
    a("}")
    a("")
    a("")
    a("assert ROOTS & LEAVES == frozenset(), \\")
    a('    "un scope ne peut pas être à la fois racine et feuille"')
    a("assert len(Scope) == len(ROOTS) + len(LEAVES), \\")
    a('    "l\'énumération et les ensembles doivent couvrir la même chose"')
    a("")
    return "\n".join(lignes)


def seed_sql(racines: list[dict], feuilles: list[dict], source: Path) -> str:
    def echap(s: str) -> str:
        return (s or "").replace("'", "''")

    lignes = [
        "-- Peuplement de arac.scopes — FICHIER GÉNÉRÉ, NE PAS ÉDITER À LA MAIN.",
        f"-- Source de vérité : {source}",
        f"-- Régénéré le : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
        "--",
        "-- Idempotent : rejouable sans effet de bord. Ne SUPPRIME jamais un scope —",
        "-- une suppression emporterait le savoir qu'il contient, et doit être une",
        "-- décision explicite, pas un effet de bord de régénération.",
        "",
        "BEGIN;",
        "",
        "-- 1. Les racines (depth 0, sans parent)",
    ]
    for r in racines:
        lignes.append(
            f"INSERT INTO arac.scopes (name, path, depth, description) "
            f"VALUES ('{echap(r['key'])}', '{echap(r['key'])}', 0, '{echap(r.get('description', ''))}') "
            f"ON CONFLICT (path) DO UPDATE SET description = EXCLUDED.description;")
    lignes += ["", "-- 2. Les feuilles (depth 1, rattachées à leur racine)"]
    for f in sorted(feuilles, key=lambda x: (x["root"], x["key"])):
        chemin = f"{f['root']}/{f['key']}"
        lignes.append(
            f"INSERT INTO arac.scopes (name, path, depth, description, parent_id) "
            f"SELECT '{echap(f['key'])}', '{echap(chemin)}', 1, "
            f"'{echap(f.get('description', ''))}', p.id "
            f"FROM arac.scopes p WHERE p.path = '{echap(f['root'])}' "
            f"ON CONFLICT (path) DO UPDATE SET description = EXCLUDED.description;")
    lignes += [
        "",
        "COMMIT;",
        "",
        "-- Contrôle : les scopes déclarés ici et absents de la base, ou l'inverse.",
        "-- Un scope présent en base mais retiré de la configuration n'est PAS supprimé :",
        "-- il apparaît ci-dessous pour que vous décidiez de son sort en connaissance",
        "-- du savoir qu'il porte.",
        "SELECT s.path, s.depth,",
        "       (SELECT count(*) FROM arac.memory_atoms a",
        "         WHERE a.scope = s.path AND a.status = 'active') AS atomes_vivants",
        "  FROM arac.scopes s",
        " ORDER BY s.depth, s.path;",
        "",
    ]
    return "\n".join(lignes)


# ---------------------------------------------------------------------------
# Contrôle de sûreté : ne jamais orpheliner du savoir
# ---------------------------------------------------------------------------


def scopes_habites_absents(dsn: str, declares: set[str]) -> list[tuple[str, int]]:
    """Les scopes qui portent des atomes vivants mais ne sont plus déclarés.

    Lecture seule. Retourne une liste vide si la base est injoignable — le
    bootstrap le signalera ; ce n'est pas à ce script de décider qu'une base
    absente vaut approbation.
    """
    try:
        import psycopg
    except ModuleNotFoundError:
        return []
    try:
        with psycopg.connect(dsn, connect_timeout=8) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT scope, count(*) FROM arac.memory_atoms "
                "WHERE status = 'active' GROUP BY scope ORDER BY 2 DESC")
            return [(s, n) for s, n in cur.fetchall() if s not in declares]
    except Exception:
        return []


def main() -> int:
    p = argparse.ArgumentParser(description="Génère l'énumération et le seed des scopes.")
    p.add_argument("--config", default="config/scopes.toml", type=Path)
    p.add_argument("--enum-out", default="app/schemas/scope_generated.py", type=Path)
    p.add_argument("--sql-out", default="db/seeds/scopes.sql", type=Path)
    p.add_argument("--dsn", default=None,
                   help="DSN de contrôle : refuse de retirer un scope encore habité")
    p.add_argument("--check", action="store_true",
                   help="valide et compare sans rien écrire (code 1 si divergence)")
    args = p.parse_args()

    try:
        racines, feuilles, _ = valider(lire(args.config))
    except Refus as exc:
        print(f"\n  TAXONOMIE REFUSÉE\n\n  {exc}\n", file=sys.stderr)
        return 2

    declares = {r["key"] for r in racines} | {f"{f['root']}/{f['key']}" for f in feuilles}

    if args.dsn:
        habites = scopes_habites_absents(args.dsn, declares)
        if habites:
            print("\n  RETRAIT REFUSÉ — du savoir vivant serait orphelin :\n", file=sys.stderr)
            for s, n in habites:
                print(f"    {s:<34} {n} atome(s) vivant(s)", file=sys.stderr)
            print("\n  Deux issues, toutes deux explicites :\n"
                  "    · remettez ces scopes dans la configuration ;\n"
                  "    · ou déplacez d'abord leurs atomes, puis relancez.\n"
                  "  Ce script ne tranchera pas à votre place.\n", file=sys.stderr)
            return 4

    enum_txt, sql_txt = enum_python(racines, feuilles, args.config), seed_sql(racines, feuilles, args.config)

    if args.check:
        ecarts = []
        for chemin, attendu in ((args.enum_out, enum_txt), (args.sql_out, sql_txt)):
            actuel = chemin.read_text(encoding="utf-8") if chemin.exists() else None
            # Le seed porte un horodatage : on compare hors de cette ligne.
            norm = lambda t: "\n".join(  # noqa: E731
                l for l in (t or "").split("\n") if not l.startswith("-- Régénéré le"))
            if norm(actuel) != norm(attendu):
                ecarts.append(str(chemin))
        if ecarts:
            print(f"  DIVERGENCE : {', '.join(ecarts)} ne reflète plus {args.config}.\n"
                  "  Relancez sans --check pour régénérer.", file=sys.stderr)
            return 1
        print(f"  Taxonomie à jour : {len(racines)} racines, {len(feuilles)} feuilles.")
        return 0

    for chemin, contenu in ((args.enum_out, enum_txt), (args.sql_out, sql_txt)):
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(contenu, encoding="utf-8")

    print(f"\n  Taxonomie générée depuis {args.config}")
    print(f"    {len(racines)} racines, {len(feuilles)} feuilles, "
          f"{len(racines) + len(feuilles)} scopes")
    print(f"    → {args.enum_out}")
    print(f"    → {args.sql_out}")
    print("\n  Rappel : les atomes vivent sur les feuilles. Un atome posé sur une "
          "racine\n  devient orphelin — la similarité pure peut encore le faire "
          "remonter, mais il\n  sort de l'état courant, de la vue des scopes et de la "
          "couverture, et une\n  recherche qui précise un domaine ne le trouvera "
          "jamais.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
