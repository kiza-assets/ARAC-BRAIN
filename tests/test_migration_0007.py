"""Migration 0007 — la table des scopes, et ce qu'elle rend impossible.

CE QUE CES TESTS PROUVENT
-------------------------
Que la base, et pas seulement l'API, fait respecter la forme de votre mémoire :

  - ``arac.scopes`` existe, avec sa hiérarchie (racine → feuille) ;
  - la clé étrangère ``atoms_scope_fk`` REFUSE un atome dont le scope n'existe
    pas dans l'arbre — c'est le second rempart, celui qu'aucun bug applicatif
    ne peut contourner ;
  - un chemin trop profond est refusé par un CHECK ;
  - les index de lecture sont là.

CE QU'ILS NE PROUVENT PAS, ET POURQUOI
--------------------------------------
Aucun test ici n'attend un NOMBRE de scopes, ni un nom de scope particulier.
La migration 0007 ne sème rien : elle crée la table VIDE. Le peuplement vient
de ``db/seeds/scopes.sql``, engendré depuis VOTRE ``config/scopes.toml``. Un
test qui exigerait « 34 lignes » ou « la feuille perso/sante » ne testerait
pas la migration : il testerait la taxonomie de quelqu'un d'autre, et virerait
au rouge chez tout le monde sauf lui.

Les scopes utilisés ci-dessous sont donc LUS dans l'énumération engendrée
(``app.schemas.scope``) — la même source que le seed SQL. C'est ce qui rend
ces tests vrais quelle que soit la taxonomie.

BASE REQUISE
------------
Ces tests parlent à une vraie base (migrations appliquées + seed joué). Sans
``DATABASE_URL_ADMIN``, ils se DÉCLARENT ignorés : un test rouge doit vouloir
dire « le code est cassé », jamais « PostgreSQL n'est pas lancé ».

Le nettoyage passe par ``DATABASE_URL_ADMIN`` et jamais par le pool
applicatif : ``arac_app`` n'a délibérément pas le droit DELETE (soft-delete
only en production).
"""

from __future__ import annotations

import os
import uuid
from typing import Iterator

import psycopg
import pytest

from app.schemas.scope import LEAVES, ROOTS

_REVISION = "0007_scopes_hierarchique"
_TEST_KEY_PREFIX = "test-0007-"

#: Un scope qui n'existe dans AUCUNE taxonomie plausible. Sert à prouver le
#: refus : la FK doit lever une 23503 (foreign_key_violation) avant écriture.
_SCOPE_INEXISTANT = "zzz-territoire-absent/zzz-feuille-absente"

#: Une forme « plate » (sans « / ») : la taxonomie n'accepte que des chemins
#: racine/feuille pour les atomes, et la FK le fait respecter.
_SCOPE_PLAT = "zzz-territoire-absent"


def _admin_dsn() -> str:
    dsn = os.environ.get("DATABASE_URL_ADMIN")
    if not dsn:
        pytest.skip("DATABASE_URL_ADMIN absent — skip migration 0007 tests.")
    return dsn


def _une_feuille() -> str:
    """Une feuille RÉELLE de la taxonomie chargée, choisie de façon stable.

    Triée : deux exécutions doivent porter sur le même scope, sinon un échec
    n'est pas reproductible.
    """
    if not LEAVES:
        pytest.skip("taxonomie vide — lancez `make scopes` avant ces tests.")
    return sorted(LEAVES)[0]


@pytest.fixture
def admin_conn() -> Iterator[psycopg.Connection]:
    """Connexion arac_admin autocommit, cleanup atomes test- avant/apres."""
    dsn = _admin_dsn()
    conn = psycopg.connect(dsn, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM arac.memory_atoms WHERE key LIKE %s",
                (f"{_TEST_KEY_PREFIX}%",),
            )
        yield conn
    finally:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM arac.memory_atoms WHERE key LIKE %s",
                (f"{_TEST_KEY_PREFIX}%",),
            )
        conn.close()


# ============================================================================
# LA TABLE ET SA HIÉRARCHIE
# ============================================================================


def test_scopes_table_reflete_la_taxonomie_declaree(admin_conn):
    """`arac.scopes` contient exactement les scopes de VOTRE taxonomie.

    L'énumération Python et le seed SQL sortent du MÊME `config/scopes.toml`.
    S'ils divergent, l'API accepterait un scope que la base refuse (ou
    l'inverse) : l'atome partirait en 23503 au moment de l'écriture, donc
    après avoir été payé au fournisseur d'embeddings. Ce test est le seul
    endroit qui compare les deux artefacts jumeaux.
    """
    with admin_conn.cursor() as cur:
        cur.execute("SELECT path FROM arac.scopes")
        en_base = {r[0] for r in cur.fetchall()}
    attendu = set(ROOTS) | set(LEAVES)
    assert en_base == attendu, (
        "l'énumération et la table ont divergé — relancez "
        "`bootstrap/generate_scopes.py` puis rejouez le seed.\n"
        f"  en base et pas dans l'énumération : {sorted(en_base - attendu)}\n"
        f"  dans l'énumération et pas en base : {sorted(attendu - en_base)}"
    )


def test_scopes_racines_depth_zero_parent_null(admin_conn):
    """Une racine a depth=0 et parent_id NULL : c'est un conteneur, pas un
    rangement. Un atome posé dessus serait invisible au rappel."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT path FROM arac.scopes "
            "WHERE depth = 0 AND parent_id IS NULL ORDER BY path"
        )
        rows = {r[0] for r in cur.fetchall()}
    assert rows == set(ROOTS), f"racines en base {sorted(rows)} != {sorted(ROOTS)}"


def test_scopes_feuilles_rattachees_a_leur_racine(admin_conn):
    """Chaque feuille pointe la racine dont son chemin porte le préfixe.

    C'est ce qui permet d'agréger « tout travail » par un simple LIKE
    'travail/%' sans maintenir une seconde table de correspondance.
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.path, p.path AS parent_path
            FROM arac.scopes s
            JOIN arac.scopes p ON s.parent_id = p.id
            WHERE s.depth = 1
            ORDER BY s.path
            """
        )
        rows = cur.fetchall()
    assert {r[0] for r in rows} == set(LEAVES)
    for leaf_path, parent_path in rows:
        assert leaf_path.startswith(parent_path + "/"), (
            f"Feuille {leaf_path} doit prefixer racine {parent_path}/"
        )


def test_aucun_atome_sur_un_scope_plat(admin_conn):
    """Aucun atome ne vit sur un scope sans « / ».

    Un scope plat est soit une racine (invisible au rappel), soit un vestige
    d'avant la hiérarchie. Les deux cas sont du savoir perdu en silence.
    """
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT scope FROM arac.memory_atoms "
            "WHERE scope NOT LIKE '%/%'"
        )
        plats = [r[0] for r in cur.fetchall()]
    assert plats == [], f"Atomes sur un scope plat : {plats}"


# ============================================================================
# LA CLÉ ÉTRANGÈRE — le rempart que le code ne peut pas contourner
# ============================================================================


def test_fk_atoms_scope_constraint_present(admin_conn):
    """La contrainte atoms_scope_fk existe sur arac.memory_atoms."""
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT conname FROM pg_constraint
            WHERE conrelid = 'arac.memory_atoms'::regclass
              AND conname = 'atoms_scope_fk'
            """
        )
        assert cur.fetchone() is not None, (
            "FK atoms_scope_fk absente sur arac.memory_atoms."
        )


def test_fk_refuse_un_scope_inconnu(admin_conn):
    """Un scope hors taxonomie -> 23503, l'atome n'entre pas."""
    test_key = f"{_TEST_KEY_PREFIX}orphan-{uuid.uuid4().hex[:8]}"
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with admin_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO arac.memory_atoms
                  (id, kind, scope, key, value, node_id, source_ref, tags, created_at)
                VALUES
                  (gen_random_uuid(), 'note', %s, %s,
                   'orphan scope test', 'claude-developer',
                   '{}'::jsonb, ARRAY[]::text[], NOW())
                """,
                (_SCOPE_INEXISTANT, test_key),
            )


def test_fk_refuse_un_scope_plat(admin_conn):
    """Une forme plate (sans « / ») est refusée comme n'importe quel inconnu."""
    test_key = f"{_TEST_KEY_PREFIX}flat-{uuid.uuid4().hex[:8]}"
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with admin_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO arac.memory_atoms
                  (id, kind, scope, key, value, node_id, source_ref, tags, created_at)
                VALUES
                  (gen_random_uuid(), 'note', %s, %s,
                   'flat scope test', 'claude-developer',
                   '{}'::jsonb, ARRAY[]::text[], NOW())
                """,
                (_SCOPE_PLAT, test_key),
            )


def test_fk_accepte_une_feuille_de_la_taxonomie(admin_conn):
    """Une feuille réellement déclarée passe : le rempart n'est pas un mur."""
    test_key = f"{_TEST_KEY_PREFIX}valid-{uuid.uuid4().hex[:8]}"
    feuille = _une_feuille()
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO arac.memory_atoms
              (id, kind, scope, key, value, node_id, source_ref, tags, created_at)
            VALUES
              (gen_random_uuid(), 'note', %s, %s,
               'valid hierarchical scope test', 'claude-developer',
               '{}'::jsonb, ARRAY[]::text[], NOW())
            """,
            (feuille, test_key),
        )
        cur.execute(
            "SELECT COUNT(*) FROM arac.memory_atoms WHERE key = %s",
            (test_key,),
        )
        assert cur.fetchone()[0] == 1


# ============================================================================
# PROFONDEUR ET INDEX
# ============================================================================


def test_depth_constraint_max_three(admin_conn):
    """CHECK depth <= 3 : au-delà de « racine/branche/feuille », plus personne
    ne retrouve rien. La base le refuse plutôt que de laisser faire."""
    with pytest.raises(psycopg.errors.CheckViolation):
        with admin_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO arac.scopes (name, path, parent_id, depth)
                VALUES ('test-deep', 'zzz/a/b/c', NULL, 4)
                """
            )


def test_indexes_present(admin_conn):
    """3 index attendus : btree path, gin trgm path, btree parent_id."""
    with admin_conn.cursor() as cur:
        cur.execute(
            """
            SELECT indexname FROM pg_indexes
            WHERE schemaname = 'arac' AND tablename = 'scopes'
            ORDER BY indexname
            """
        )
        names = [r[0] for r in cur.fetchall()]
    expected_subset = {
        "idx_scopes_path_btree",
        "idx_scopes_path_trgm",
        "idx_scopes_parent",
    }
    missing = expected_subset - set(names)
    assert not missing, f"Index manquants : {missing} (presents : {names})"
