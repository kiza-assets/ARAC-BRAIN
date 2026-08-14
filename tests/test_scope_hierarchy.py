"""La hiérarchie des scopes, prouvée contre une vraie base.

CE QUE CES TESTS PROUVENT
-------------------------
  - filtrer sur un chemin EXACT ne ramène que ce scope-là ;
  - filtrer sur `racine/%` agrège toutes ses feuilles, et rien d'autre ;
  - **aucun atome actif ne vit sur une racine** — c'est la règle la plus
    coûteuse du système ;
  - `CHECK depth <= 3` refuse un chemin trop profond ;
  - `ON UPDATE CASCADE` : renommer un scope emmène ses atomes avec lui ;
  - `ON DELETE RESTRICT` : supprimer un scope habité est refusé.

AUCUN NOM DE SCOPE N'EST ÉCRIT EN DUR
-------------------------------------
Les scopes utilisés viennent de l'énumération engendrée par VOTRE taxonomie
(`app.schemas.scope`), la même source que le seed SQL. Un test qui citerait
un scope nommé en dur, ou compterait « 45 lignes », testerait la taxonomie de son
auteur, pas le code : il serait rouge chez tout le monde sauf lui.

Quand la taxonomie chargée est trop petite pour un scénario (il faut une
racine à deux feuilles, et une deuxième racine), le test se DÉCLARE ignoré
plutôt que d'inventer un scope que la clé étrangère refuserait.

POURQUOI « ZÉRO ATOME SUR UNE RACINE » EST UN TEST, PAS UN CONSEIL
------------------------------------------------------------------
Une racine est un conteneur, une feuille est un rangement. Un atome posé sur
une racine est écrit, actif, facturé — et INVISIBLE au rappel : aucune
question ne le fera jamais remonter. Sur le cerveau de référence observé
huit mois, 157 atomes (9 % du corpus) sont tombés dans ce piège et n'en sont
jamais ressortis. Ce test est le grillage au bord du trou.

BASE REQUISE
------------
Sans `DATABASE_URL_ADMIN`, tout se déclare ignoré. Les mutations passent par
`arac_admin` : le pool applicatif n'a ni DELETE ni UPDATE sur `arac.scopes`.
"""

from __future__ import annotations

import os
import uuid
from typing import Iterator

import psycopg
import pytest

from app.schemas.scope import LEAVES, ROOTS

_TEST_KEY_PREFIX = "test-scope-hier-"
_NODE_ID = "claude-developer"


# ---------------------------------------------------------------------------
# La taxonomie, telle qu'elle est chargée — jamais telle qu'on l'imagine.
# ---------------------------------------------------------------------------


def _leaves_by_root() -> dict[str, list[str]]:
    par_racine: dict[str, list[str]] = {r: [] for r in ROOTS}
    for leaf in sorted(LEAVES):
        par_racine.setdefault(leaf.split("/", 1)[0], []).append(leaf)
    return par_racine


def _racine_riche_et_autre() -> tuple[str, list[str], str, str]:
    """(racine A, ses feuilles, racine B, une feuille de B).

    A est la racine la mieux fournie — c'est elle qui permet de vérifier
    l'agrégation par préfixe. B sert de témoin d'exclusion.
    """
    par_racine = {r: f for r, f in _leaves_by_root().items() if f}
    if len(par_racine) < 2:
        pytest.skip("taxonomie trop petite : il faut au moins deux racines peuplées.")
    ordre = sorted(par_racine, key=lambda r: (-len(par_racine[r]), r))
    a, b = ordre[0], ordre[1]
    if len(par_racine[a]) < 2:
        pytest.skip("taxonomie trop petite : aucune racine n'a deux feuilles.")
    return a, par_racine[a], b, par_racine[b][0]


def _admin_dsn() -> str:
    dsn = os.environ.get("DATABASE_URL_ADMIN")
    if not dsn:
        pytest.skip("DATABASE_URL_ADMIN absent — skip scope hierarchy tests.")
    return dsn


@pytest.fixture
def admin_conn() -> Iterator[psycopg.Connection]:
    """Connexion arac_admin autocommit, cleanup atomes/scopes test- avant/apres."""
    dsn = _admin_dsn()
    conn = psycopg.connect(dsn, autocommit=True)
    try:
        with conn.cursor() as cur:
            # Cleanup atomes en premier (FK atoms_scope_fk ON DELETE RESTRICT).
            cur.execute(
                "DELETE FROM arac.memory_atoms WHERE key LIKE %s",
                (f"{_TEST_KEY_PREFIX}%",),
            )
            # Cleanup scopes ephemeres test-* (forme `<root>/test-scope-hier-*`).
            cur.execute(
                "DELETE FROM arac.scopes WHERE name LIKE %s",
                (f"{_TEST_KEY_PREFIX}%",),
            )
        yield conn
    finally:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM arac.memory_atoms WHERE key LIKE %s",
                (f"{_TEST_KEY_PREFIX}%",),
            )
            cur.execute(
                "DELETE FROM arac.scopes WHERE name LIKE %s",
                (f"{_TEST_KEY_PREFIX}%",),
            )
        conn.close()


def _insert_atom(conn: psycopg.Connection, scope: str, key_suffix: str) -> str:
    """Insere un atome test- avec le scope donne. Retourne l'id."""
    atom_id = str(uuid.uuid4())
    key = f"{_TEST_KEY_PREFIX}{key_suffix}"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO arac.memory_atoms
              (id, kind, scope, key, value, node_id, source_ref, tags, created_at)
            VALUES
              (%s, 'note', %s, %s, 'scope hierarchy test seed',
               %s, '{}'::jsonb, ARRAY[]::text[], NOW())
            """,
            (atom_id, scope, key, _NODE_ID),
        )
    return atom_id


# ============================================================================
# 1 — un chemin exact ne ramène que lui-même
# ============================================================================


def test_recall_by_exact_path_returns_only_that_scope(admin_conn):
    """Deux atomes sur une feuille, un sur une autre : le filtre exact en
    ramène deux."""
    _, feuilles, _, _ = _racine_riche_et_autre()
    cible, voisine = feuilles[0], feuilles[1]

    _insert_atom(admin_conn, cible, "exact-a")
    _insert_atom(admin_conn, cible, "exact-b")
    _insert_atom(admin_conn, voisine, "exact-c")

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT scope FROM arac.memory_atoms "
            "WHERE key LIKE %s AND scope = %s",
            (f"{_TEST_KEY_PREFIX}%", cible),
        )
        rows = [r[0] for r in cur.fetchall()]
    assert len(rows) == 2, f"Attendu 2 atomes {cible}, trouve {len(rows)}"
    assert set(rows) == {cible}


# ============================================================================
# 2 — `racine/%` agrège toutes ses feuilles
# ============================================================================


def test_recall_by_root_prefix_includes_all_leaves(admin_conn):
    """C'est ce préfixe qui permet de demander « tout ce domaine » sans
    maintenir une table de correspondance à côté."""
    racine, feuilles, _, temoin = _racine_riche_et_autre()

    for i, f in enumerate(feuilles):
        _insert_atom(admin_conn, f, f"prefix-{i}")
    _insert_atom(admin_conn, temoin, "prefix-hors-racine")  # exclu

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT scope FROM arac.memory_atoms "
            "WHERE key LIKE %s AND scope LIKE %s ORDER BY scope",
            (f"{_TEST_KEY_PREFIX}%", f"{racine}/%"),
        )
        rows = [r[0] for r in cur.fetchall()]
    assert set(rows) == set(feuilles)
    assert temoin not in rows


# ============================================================================
# 3 — un préfixe de racine exclut les autres racines
# ============================================================================


def test_recall_by_root_prefix_excludes_other_roots(admin_conn):
    """Deux mondes ne se mélangent pas : c'est ce qui empêche le rappel de
    diluer une question de travail dans de la vie privée."""
    racine_a, feuilles_a, racine_b, feuille_b = _racine_riche_et_autre()

    _insert_atom(admin_conn, feuille_b, "b-1")
    _insert_atom(admin_conn, feuilles_a[0], "a-exclu")

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT scope FROM arac.memory_atoms "
            "WHERE key LIKE %s AND scope LIKE %s ORDER BY scope",
            (f"{_TEST_KEY_PREFIX}%", f"{racine_b}/%"),
        )
        rows = [r[0] for r in cur.fetchall()]
    assert set(rows) == {feuille_b}
    assert feuilles_a[0] not in rows


# ============================================================================
# 4 — zéro atome actif sur une racine
# ============================================================================


def test_aucun_atome_actif_sur_une_racine(admin_conn):
    """La règle qui coûte le plus cher quand on l'oublie.

    Un atome sur une racine est en base, actif, et introuvable. Le cerveau de
    référence en comptait 157 après huit mois — 9 % de son corpus, payés puis
    perdus. Sur un cerveau neuf, ce compteur doit rester à zéro : c'est
    beaucoup plus facile que de l'y ramener.
    """
    coupables: dict[str, int] = {}
    for racine in sorted(ROOTS):
        with admin_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM arac.memory_atoms "
                "WHERE scope = %s AND status = 'active'",
                (racine,),
            )
            n = cur.fetchone()[0]
        if n:
            coupables[racine] = n
    assert not coupables, (
        f"Atomes actifs posés sur une racine : {coupables}. Ils sont invisibles "
        "au rappel. Déplacez-les vers une feuille (UPDATE scope), puis "
        "cherchez ce qui les a écrits là."
    )


# ============================================================================
# 5 — la table reflète la taxonomie déclarée
# ============================================================================


def test_scopes_table_reflete_la_taxonomie(admin_conn):
    """Autant de lignes que de scopes déclarés — ni plus, ni moins.

    L'énumération Python et le seed SQL naissent du même `config/scopes.toml`.
    S'ils divergent, l'API accepte un scope que la base refuse : l'atome part
    en 23503 APRÈS avoir été payé au fournisseur d'embeddings.
    """
    with admin_conn.cursor() as cur:
        cur.execute("SELECT path, depth FROM arac.scopes")
        rows = cur.fetchall()
    en_base = {p for p, _ in rows}
    assert en_base == set(ROOTS) | set(LEAVES), (
        "l'énumération et la table ont divergé — relancez "
        "`bootstrap/generate_scopes.py` puis rejouez `db/seeds/scopes.sql`."
    )
    assert {p for p, d in rows if d == 0} == set(ROOTS)
    assert {p for p, d in rows if d == 1} == set(LEAVES)


# ============================================================================
# 6 — CHECK depth <= 3
# ============================================================================


def test_depth_check_refuses_depth_four(admin_conn):
    """Au-delà de « racine/branche/feuille », plus personne ne retrouve rien.
    La base refuse plutôt que de laisser la taxonomie s'enfoncer."""
    with pytest.raises(psycopg.errors.CheckViolation):
        with admin_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO arac.scopes (name, path, parent_id, depth)
                VALUES (%s, %s, NULL, 4)
                """,
                (
                    f"{_TEST_KEY_PREFIX}deep4",
                    f"zzz/a/b/{_TEST_KEY_PREFIX}deep4",
                ),
            )


# ============================================================================
# 7 — ON UPDATE CASCADE : renommer un scope emmène ses atomes
# ============================================================================


def test_fk_cascade_update_propagates_path_rename(admin_conn):
    """Renommer une feuille ne doit JAMAIS orpheliner le savoir qu'elle porte.

    Scénario contenu : on crée une feuille éphémère sous une vraie racine, on
    y pose un atome, on renomme, on vérifie que l'atome a suivi, on nettoie.
    """
    racine, _, _, _ = _racine_riche_et_autre()
    ephemeral_old = f"{racine}/{_TEST_KEY_PREFIX}cascade"
    ephemeral_new = f"{racine}/{_TEST_KEY_PREFIX}cascade-renamed"

    with admin_conn.cursor() as cur:
        cur.execute("SELECT id FROM arac.scopes WHERE path = %s", (racine,))
        racine_id = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO arac.scopes (name, path, parent_id, depth)
            VALUES (%s, %s, %s, 1)
            """,
            (f"{_TEST_KEY_PREFIX}cascade", ephemeral_old, racine_id),
        )

    atom_id = _insert_atom(admin_conn, ephemeral_old, "cascade-atom")

    with admin_conn.cursor() as cur:
        cur.execute(
            "UPDATE arac.scopes SET path = %s WHERE path = %s",
            (ephemeral_new, ephemeral_old),
        )

    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT scope FROM arac.memory_atoms WHERE id = %s", (atom_id,)
        )
        new_scope = cur.fetchone()[0]
    assert new_scope == ephemeral_new, (
        f"FK CASCADE UPDATE casse : atome.scope = {new_scope!r} "
        f"alors qu'on attendait {ephemeral_new!r}."
    )

    with admin_conn.cursor() as cur:
        cur.execute("DELETE FROM arac.memory_atoms WHERE id = %s", (atom_id,))
        cur.execute("DELETE FROM arac.scopes WHERE path = %s", (ephemeral_new,))


# ============================================================================
# 8 — ON DELETE RESTRICT : supprimer un scope habité est refusé
# ============================================================================


def test_fk_restrict_delete_blocks_used_scope(admin_conn):
    """Supprimer un scope emporterait le savoir qu'il contient. Ce doit être
    une décision explicite, jamais l'effet de bord d'un nettoyage."""
    racine, _, _, _ = _racine_riche_et_autre()
    ephemeral = f"{racine}/{_TEST_KEY_PREFIX}restrict"

    with admin_conn.cursor() as cur:
        cur.execute("SELECT id FROM arac.scopes WHERE path = %s", (racine,))
        racine_id = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO arac.scopes (name, path, parent_id, depth)
            VALUES (%s, %s, %s, 1)
            """,
            (f"{_TEST_KEY_PREFIX}restrict", ephemeral, racine_id),
        )

    _insert_atom(admin_conn, ephemeral, "restrict-atom")

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with admin_conn.cursor() as cur:
            cur.execute("DELETE FROM arac.scopes WHERE path = %s", (ephemeral,))

    # Apres pytest.raises, autocommit -> l'erreur a deja rollback. Cleanup propre.
    with admin_conn.cursor() as cur:
        cur.execute(
            "DELETE FROM arac.memory_atoms WHERE key LIKE %s",
            (f"{_TEST_KEY_PREFIX}restrict%",),
        )
        cur.execute("DELETE FROM arac.scopes WHERE path = %s", (ephemeral,))
