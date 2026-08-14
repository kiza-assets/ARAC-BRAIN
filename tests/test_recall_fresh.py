"""Tests d'intégration POST /v1/atoms/recall_fresh — Phase D.6 Tier 2.

Couvre :
- recall_fresh retourne uniquement des atomes status='active' (par construction)
- recall_fresh filtre les atomes stales (updated_at < NOW() - days)
- recall_fresh exempte les atomes pierre-angulaire même stales
- recall_fresh respecte les filtres scope/kind
- Validation Pydantic : 422 sur params invalides

PROSPECTIF : la 3e exemption du prototype antérieur (confirmed_until > NOW()) n'est PAS
testée car la colonne n'existe pas en BDD ARAC au 2026-05-20 — décision
d'introduction reportée Phase E (cf docstring recall_fresh endpoint).

Stratégie :
- Tous les tests utilisent `mock_embed` (économie API + latence).
- Les atomes test-* sont nettoyés en pre/post fixture (cf conftest.py).
- Pour simuler des atomes stales, on vieillit `updated_at` par la connexion
  d'administration de la session (`DATABASE_URL_ADMIN`), donc PAR LE GARDE de
  marque : aucune base qui ne se déclare pas jetable ne s'ouvre. Ce module
  lançait auparavant `sudo -u postgres psql -d arac` — un sous-processus, hors
  de tous les gardes, sur une base nommée en dur. Voir `_backdate_atom`.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL_ADMIN"),
    reason="DB reelle requise",
)

SEED_NODE = "test-node"
PA_TAG = "pierre-angulaire"


async def _backdate_atom(atom_id: str, days_ago: int) -> None:
    """Vieillit `updated_at` — par la base de test, jamais par un sous-processus.

    CE QUE CETTE FONCTION FAISAIT, ET POURQUOI C'ÉTAIT LE PIRE DÉFAUT DU DÉPÔT
    =========================================================================

    Elle lançait ceci, pendant `make test` :

        subprocess.run(["sudo", "-n", "-u", "postgres", "psql", "-d", "arac",
                        "-c", "ALTER TABLE arac.memory_atoms DISABLE TRIGGER …;
                               UPDATE arac.memory_atoms SET updated_at = … ;
                               ALTER TABLE … ENABLE TRIGGER …"])

    — du DDL et un UPDATE sur la base littéralement nommée `arac`, c'est-à-dire
    le cerveau de PRODUCTION de l'auteur, 1 919 souvenirs. Les trois gardes le
    laissaient passer, chacun pour une raison différente et chacune instructive :

      · le garde de BASE demande à la base ouverte si elle porte la marque
        `arac:base-de-test-jetable` — mais il est posé sur `psycopg`, et ceci
        n'était pas une connexion psycopg ;
      · le garde de MACHINE regardait `args[0]`, qui vaut « sudo » ;
      · le garde G1 dispense `tests/` de tous ses motifs, au motif qu'« un test
        NOMME pour affirmer ; il n'installe rien ». Cette ligne-là ne nommait
        pas : elle exécutait.

    Le nom `arac` n'était dérivé de rien. C'est exactement le défaut que
    `garde_hermetique.py` déclarait avoir corrigé — « la question n'est plus
    est-ce la base de l'auteur » — sur le seul chemin qu'il ne surveillait pas.

    CE QU'ELLE FAIT MAINTENANT
    ==========================

    Elle passe par `DATABASE_URL_ADMIN`, donc par `psycopg`, donc par le garde
    de marque : aucune base qui ne se déclare pas jetable ne s'ouvre. Le nom de
    la base n'est écrit nulle part — il vient du DSN de la session.

    Le déclencheur `memory_atoms_updated_at` n'est plus désactivé par du DDL
    (que `arac_admin` ne peut de toute façon pas exécuter, n'étant pas
    propriétaire de la table) : on pose `session_replication_role = replica`,
    qui suspend les déclencheurs POUR CETTE SESSION seulement. Si le rôle n'a
    pas ce droit, on IGNORE le test plutôt que d'ouvrir une porte hors garde —
    ne pas pouvoir mesurer n'autorise pas à contourner.
    """
    import psycopg

    dsn = os.environ["DATABASE_URL_ADMIN"]
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=False) as conn:
        async with conn.cursor() as cur:
            try:
                await cur.execute("SET session_replication_role = replica")
            except psycopg.Error as exc:
                await conn.rollback()
                pytest.skip(
                    "le rôle d'administration ne peut pas suspendre les "
                    f"déclencheurs (session_replication_role) : {exc}"
                )
            await cur.execute(
                "UPDATE arac.memory_atoms "
                "SET updated_at = NOW() - make_interval(days => %s) "
                "WHERE id = %s",
                (int(days_ago), atom_id),
            )
        await conn.commit()


# ============================================================================
# Test 1 — recall_fresh retourne des atomes actifs récents
# ============================================================================


async def test_recall_fresh_returns_active_atoms(client, mock_embed):
    """Crée un atome récent (status=active, updated_at récent). recall_fresh
    doit le ramener avec une distance numérique."""
    create = await client.post("/v1/atoms", json={
        "kind": "note",
        "scope": "outillage/assistants",
        "key": "test-rf-fresh-active",
        "value": "Atome frais pour test recall_fresh",
        "tags": ["test-marker"],
        "node_id": SEED_NODE,
    })
    assert create.status_code == 201, create.text
    atom_id = create.json()["id"]

    r = await client.post("/v1/atoms/recall_fresh", json={
        "query": "test recall fresh atome",
        "days": 14,
        "k": 50,
    })
    assert r.status_code == 200, r.text
    atoms = r.json()
    assert isinstance(atoms, list)

    ids = {a["id"] for a in atoms}
    assert atom_id in ids, f"atome fresh test-rf-fresh-active doit être présent"

    for a in atoms:
        assert a["status"] == "active", \
            f"recall_fresh ne doit retourner que status=active, got {a['status']}"
        assert a["distance"] is not None, \
            "recall_fresh doit propager la distance cosine"


# ============================================================================
# Test 2 — recall_fresh filtre les atomes stales (updated_at vieux)
# ============================================================================


async def test_recall_fresh_filters_stale_atoms(client, mock_embed):
    """Crée un atome puis backdate son updated_at à 30 jours dans le passé.
    Avec days=14, l'atome doit être filtré. Avec days=60, il doit revenir.
    """
    create = await client.post("/v1/atoms", json={
        "kind": "note",
        "scope": "outillage/assistants",
        "key": "test-rf-stale-note",
        "value": "Atome stale destiné à être backdaté",
        "tags": ["test-marker"],
        "node_id": SEED_NODE,
    })
    assert create.status_code == 201, create.text
    atom_id = create.json()["id"]

    # Backdate à 30 jours
    await _backdate_atom(atom_id, 30)

    # Avec days=14 → filtré (stale)
    r_short = await client.post("/v1/atoms/recall_fresh", json={
        "query": "atome stale backdaté",
        "days": 14,
        "k": 100,
    })
    assert r_short.status_code == 200, r_short.text
    ids_short = {a["id"] for a in r_short.json()}
    assert atom_id not in ids_short, (
        "atome backdaté 30j doit être filtré avec days=14"
    )

    # Avec days=60 → revient (fenêtre élargie)
    r_long = await client.post("/v1/atoms/recall_fresh", json={
        "query": "atome stale backdaté",
        "days": 60,
        "k": 100,
    })
    assert r_long.status_code == 200, r_long.text
    ids_long = {a["id"] for a in r_long.json()}
    assert atom_id in ids_long, (
        "atome backdaté 30j doit revenir avec days=60"
    )


# ============================================================================
# Test 3 — recall_fresh exempte les pierre-angulaire même stales
# ============================================================================


async def test_recall_fresh_exempts_pierre_angulaire(client, mock_embed):
    """Crée un atome pierre-angulaire puis backdate à 90 jours. Même avec
    days=14, l'atome doit revenir grâce à l'exemption tag."""
    create = await client.post("/v1/atoms", json={
        "kind": "pattern",
        "scope": "outillage/assistants",
        "key": "test-rf-stale-pa",
        "value": "Atome pierre-angulaire stale, doit être exempté",
        "tags": [PA_TAG, "test-marker"],
        "node_id": SEED_NODE,
    })
    assert create.status_code == 201, create.text
    atom_id = create.json()["id"]

    # Backdate à 90 jours
    await _backdate_atom(atom_id, 90)

    # Même avec days=14 (strict), l'atome PA doit être exempté
    r = await client.post("/v1/atoms/recall_fresh", json={
        "query": "pierre-angulaire stale exempté",
        "days": 14,
        "k": 100,
    })
    assert r.status_code == 200, r.text
    atoms = r.json()
    ids = {a["id"] for a in atoms}
    assert atom_id in ids, (
        "atome pierre-angulaire stale doit être exempté du filtre"
    )

    # Vérifie qu'on retrouve bien le tag dans la réponse
    matched = next(a for a in atoms if a["id"] == atom_id)
    assert PA_TAG in matched["tags"], "exempt par tag pierre-angulaire"


# ============================================================================
# Test 4 — recall_fresh respecte les filtres scope/kind
# ============================================================================


async def test_recall_fresh_respects_scope_kind_filters(client, mock_embed):
    """Crée deux atomes de scopes différents, vérifie que le filtre scope
    masque l'un quand on précise l'autre."""
    a_config = await client.post("/v1/atoms", json={
        "kind": "note",
        "scope": "outillage/assistants",
        "key": "test-rf-filter-config",
        "value": "Note scope claude-config pour filtre",
        "tags": ["test-marker"],
        "node_id": SEED_NODE,
    })
    assert a_config.status_code == 201, a_config.text
    id_config = a_config.json()["id"]

    a_strategie = await client.post("/v1/atoms", json={
        "kind": "note",
        "scope": "travail/strategie",
        "key": "test-rf-filter-strategie",
        "value": "Note scope arac-strategie pour filtre",
        "tags": ["test-marker"],
        "node_id": SEED_NODE,
    })
    assert a_strategie.status_code == 201, a_strategie.text
    id_strategie = a_strategie.json()["id"]

    # Filtre scope=claude-config → strategie absent
    r = await client.post("/v1/atoms/recall_fresh", json={
        "query": "note filtre",
        "days": 14,
        "k": 100,
        "scope": "outillage/assistants",
    })
    assert r.status_code == 200, r.text
    ids = {a["id"] for a in r.json()}
    assert id_config in ids
    assert id_strategie not in ids, (
        "atome scope arac-strategie ne doit pas remonter avec filtre scope=claude-config"
    )

    # Tous les atomes retournés doivent avoir le scope demandé
    for a in r.json():
        assert a["scope"] == "outillage/assistants"


# ============================================================================
# Test 5 — recall_fresh validation 422 sur params invalides
# ============================================================================


@pytest.mark.parametrize(
    "payload,reason",
    [
        ({"query": "", "days": 14, "k": 10}, "query empty"),
        ({"query": "ok", "days": 0, "k": 10}, "days < 1"),
        ({"query": "ok", "days": 400, "k": 10}, "days > 365"),
        ({"query": "ok", "days": 14, "k": 0}, "k < 1"),
        ({"query": "ok", "days": 14, "k": 200}, "k > 100"),
        (
            {"query": "ok", "days": 14, "k": 10, "extra_field": "x"},
            "extra forbid",
        ),
    ],
)
async def test_recall_fresh_params_validation_422(
    client, mock_embed, payload, reason
):
    """Pydantic doit rejeter params hors bornes ou inconnus."""
    r = await client.post("/v1/atoms/recall_fresh", json=payload)
    assert r.status_code == 422, (
        f"attendu 422 pour {reason}, got {r.status_code}: {r.text}"
    )
