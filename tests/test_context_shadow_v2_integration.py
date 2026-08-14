"""Tests d'intégration (FOLD V2) — hook SHADOW-V2 dans
POST /v1/atoms/recall (`context_shadow.run_shadow_v2`, pool kNN sur
`arac.memory_atom_reprs` repr_version `rm1-fold-a50`).

Couverture demandée par la mission :
  1. flags OFF (défaut) → rien : aucun reçu, réponse inchangée ;
  2. v2 ON SEUL → réponse servie BIT-IDENTIQUE + exactement UN reçu, et
     c'est un reçu v2 (`engine_version=ce-shadow-r3pur-v2-fold-a50`) dont les
     shadow_ids suivent le rang kNN des REPRS (pas celui de
     memory_atoms.embedding — prouvé par une rampe de distances INVERSÉE) ;
  3. v1 + v2 ON → DEUX reçus au MÊME `query_sha256` (comparaison vivante par
     requête), engine_versions v1 puis v2 (ordre d'exécution) ;
  4. table repr VIDE → 200 + WARNING `context_shadow_v2.no_reprs` throttlé
     (UNE fois par process), aucun reçu v2, aucun compteur d'erreur ;
  5. erreur v2 simulée → 200 + compteur `shadow_v2_error` incrémenté (JAMAIS
     `shadow_error` v1), le reçu v1 est écrit quand même.

Hygiène de contrat :
  - `REPR_VERSION_V2` (constante dupliquée anti-boot dans context_shadow)
    DOIT rester égale à `app.repr.recipe.REPR_VERSION` (clé de la table
    0031) — test croisé ;
  - importer `app.services.context_shadow` ne doit PAS charger
    `app.repr.recipe` (numpy/tiktoken hors du chemin requête) — prouvé en
    subprocess frais.

Hermétisme : mêmes gardes que test_context_shadow_integration.py — skip
module si DATABASE_URL_APP/ADMIN absentes (DSN de TEST arac_test@5433, le
garde-fou anti-prod de conftest refuse la base `arac`). Les reprs sont
posées par INSERT admin direct (embeddings contrôlés, rotation du vecteur
mock — cf `_perturbed_embedding`) : le hook v2 ne fait AUCUN embed
supplémentaire (l'embedding requête v1 est réutilisé, invariant #4).
Le cleanup conftest (atomes `key LIKE 'test-%'`) cascade sur
`memory_atom_reprs` (FK ON DELETE CASCADE, migration 0031).
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
from pathlib import Path
import sys

import psycopg
import pytest
from psycopg.rows import dict_row

from app.services import context_shadow

# Marqueur PAR TEST (pas de pytestmark module) : les deux tests de contrat
# en bas de fichier sont HERMÉTIQUES et doivent tourner dans `make test`
# (suite sans .env) — seuls les tests DB-backed skippent sans DSN.
_requires_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL_ADMIN"),
    reason="DB de test requise (DATABASE_URL_APP/ADMIN vers arac_test@5433)",
)

SEED_NODE = "test-node"
QUERY = "test fold v2 shadow requete d'integration"

# Vecteur retourné par mock_embed (conftest) — même convention que le test v1.
_MOCK_EMBEDDING = [0.001 * i for i in range(3072)]

_ALL_FLAGS = (
    context_shadow.FLAG_SHADOW_ENABLED,
    context_shadow.FLAG_SHADOW_V2_ENABLED,
    context_shadow.FLAG_CONSUMER_DEFAULT,
    context_shadow.FLAG_SERVE_CORTEX_DEDUP,
    context_shadow.FLAG_SERVE_CANARI,
)


@pytest.fixture(autouse=True)
def _flags_off(monkeypatch):
    """Défaut OFF garanti — chaque test arme explicitement ce qu'il veut."""
    for flag in _ALL_FLAGS:
        monkeypatch.delenv(flag, raising=False)


def _perturbed_embedding(step: int) -> list[float]:
    """Vecteur mock tourné sur la coordonnée 0 : step=0 → d=0 ;
    d(step) croît de façon monotone, tous << 0.08 pour step <= 3."""
    v = list(_MOCK_EMBEDDING)
    v[0] = 10.0 * step
    return v


async def _admin_conn():
    return await psycopg.AsyncConnection.connect(
        os.environ["DATABASE_URL_ADMIN"], autocommit=True)


async def _receipts_watermark() -> int:
    async with await _admin_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT COALESCE(MAX(id), 0) FROM arac.context_receipts")
            (max_id,) = await cur.fetchone()
    return int(max_id)


async def _receipts_after(watermark: int) -> list[dict]:
    async with await _admin_conn() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT * FROM arac.context_receipts WHERE id > %s ORDER BY id",
                (watermark,),
            )
            return await cur.fetchall()


async def _set_embedding(atom_id: str, embedding: list[float]) -> None:
    literal = "[" + ",".join(repr(x) for x in embedding) + "]"
    async with await _admin_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE arac.memory_atoms SET embedding = %s::halfvec(3072) "
                "WHERE id = %s",
                (literal, atom_id),
            )


async def _insert_repr(atom_id: str, embedding: list[float]) -> None:
    """Pose une repr v2 contrôlée (INSERT admin — le chemin normal est le
    batch WP-C, hors sujet ici : on teste la LECTURE shadow)."""
    literal = "[" + ",".join(repr(x) for x in embedding) + "]"
    async with await _admin_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO arac.memory_atom_reprs "
                "(atom_id, repr_version, embedding, manifest_sha) "
                "VALUES (%s::uuid, %s, %s::halfvec(3072), %s) "
                "ON CONFLICT (atom_id, repr_version) DO NOTHING",
                (atom_id, context_shadow.REPR_VERSION_V2, literal, "test-manifest"),
            )


async def _wipe_reprs() -> None:
    """Table repr VIDE garantie (DB de test uniquement — le rôle admin est
    propriétaire ; arac_app, lui, n'a PAS DELETE, grants 0031)."""
    async with await _admin_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM arac.memory_atom_reprs")


async def _seed_atoms_with_reprs(
    client, *, count: int = 3, scope: str = "outillage/assistants",
    key_prefix: str = "test-ce-v2",
) -> list[str]:
    """`count` atomes test-* : embeddings V1 en rampe CROISSANTE
    (rang dense v1 = ordre de création) et reprs V2 en rampe INVERSÉE
    (rang v2 = ordre inverse) — la divergence des deux rangs PROUVE que le
    shadow-v2 lit `memory_atom_reprs`, pas `memory_atoms.embedding`."""
    ids: list[str] = []
    for i in range(count):
        payload = {
            "kind": "note",
            "scope": scope,
            "key": f"{key_prefix}-{i}",
            "value": f"Atome fold v2 test shadow rang {i}",
            "tags": ["test-marker"],
            "node_id": SEED_NODE,
        }
        resp = await client.post("/v1/atoms", json=payload)
        assert resp.status_code == 201, resp.text
        atom_id = resp.json()["id"]
        await _set_embedding(atom_id, _perturbed_embedding(i))
        await _insert_repr(atom_id, _perturbed_embedding(count - 1 - i))
        ids.append(atom_id)
    return ids


# ============================================================================
# 1. Flags OFF (défaut) — hook v2 invisible
# ============================================================================


@_requires_db
async def test_flags_off_no_receipt_response_unchanged(client, mock_embed):
    watermark = await _receipts_watermark()
    counters_before = context_shadow.health_counters()

    r1 = await client.post("/v1/atoms/recall", json={"query": QUERY, "k": 5})
    r2 = await client.post("/v1/atoms/recall", json={"query": QUERY, "k": 5})

    assert r1.status_code == 200, r1.text
    assert r1.json() == r2.json()
    assert await _receipts_after(watermark) == []
    assert context_shadow.health_counters() == counters_before


# ============================================================================
# 2. v2 ON seul — réponse bit-identique + reçu v2 SEULEMENT
# ============================================================================


@_requires_db
async def test_v2_alone_bit_identical_response_and_v2_receipt_only(
    client, mock_embed, monkeypatch
):
    ids = await _seed_atoms_with_reprs(client, count=3)

    body = {"query": QUERY, "k": 5}
    r_off = await client.post("/v1/atoms/recall", json=body)
    assert r_off.status_code == 200, r_off.text
    dense = r_off.json()
    # Prémisse : le rang dense v1 = ordre de création (rampe croissante).
    assert [a["id"] for a in dense[:3]] == ids

    watermark = await _receipts_watermark()
    monkeypatch.setenv(context_shadow.FLAG_SHADOW_V2_ENABLED, "1")
    r_on = await client.post("/v1/atoms/recall", json=body)

    assert r_on.status_code == 200, r_on.text
    # INVARIANT : la réponse servie est BIT-IDENTIQUE flag v2 ON/OFF.
    assert r_on.json() == dense

    receipts = await _receipts_after(watermark)
    assert len(receipts) == 1  # v2 SEUL : jamais de reçu v1
    rec = receipts[0]
    assert rec["engine_version"] == context_shadow.ENGINE_VERSION_V2
    assert rec["consumer"] == "shadow"  # run anonyme, même convention que v1
    # Bandes/calibration V1 = PROXY consigné : la row porte la calib v1 À
    # CÔTÉ de l'engine_version v2 — c'est la mention dans le reçu.
    assert rec["calibration_version"] == "r3-calib-v1-20260708"
    assert rec["query_sha256"] == hashlib.sha256(QUERY.encode("utf-8")).hexdigest()
    assert rec["k_requested"] == 5
    # Vérité du chemin servi : les ids servis du reçu = la réponse dense.
    assert [str(u) for u in rec["served_ids"]] == [a["id"] for a in r_on.json()]
    # LE point du fold : le rang shadow v2 suit les REPRS (rampe INVERSÉE),
    # pas memory_atoms.embedding — preuve que le kNN lit memory_atom_reprs.
    assert [str(u) for u in rec["shadow_ids"]] == list(reversed(ids))
    assert len(rec["shadow_ids"]) == len(rec["shadow_distances"])
    assert rec["shadow_latency_ms"] >= 0.0
    assert rec["shadow_error"] is None


# ============================================================================
# 3. v1 + v2 ON — deux reçus, même query_sha256
# ============================================================================


@_requires_db
async def test_v1_and_v2_two_receipts_same_query_sha(
    client, mock_embed, monkeypatch
):
    ids = await _seed_atoms_with_reprs(client, count=3)

    watermark = await _receipts_watermark()
    monkeypatch.setenv(context_shadow.FLAG_SHADOW_ENABLED, "1")
    monkeypatch.setenv(context_shadow.FLAG_SHADOW_V2_ENABLED, "1")
    r = await client.post("/v1/atoms/recall", json={"query": QUERY, "k": 5})
    assert r.status_code == 200, r.text

    receipts = await _receipts_after(watermark)
    assert len(receipts) == 2
    rec_v1, rec_v2 = receipts  # ordre d'insertion = v1 PUIS v2 (hook)
    assert rec_v1["engine_version"] == context_shadow.ENGINE_VERSION
    assert rec_v2["engine_version"] == context_shadow.ENGINE_VERSION_V2
    # La clé de la comparaison vivante : MÊME requête, même sha — les deux
    # moteurs sont interrogeables côte à côte par simple GROUP BY.
    assert rec_v1["query_sha256"] == rec_v2["query_sha256"]
    assert rec_v1["consumer"] == rec_v2["consumer"] == "shadow"
    # Et les deux voient le monde différemment (v1 = rampe des embeddings
    # memory_atoms, v2 = rampe INVERSÉE des reprs) — la matière de l'analyse.
    assert [str(u) for u in rec_v1["shadow_ids"]][:3] == ids
    assert [str(u) for u in rec_v2["shadow_ids"]][:3] == list(reversed(ids))
    # served_ids identiques : la vérité servie est UNE (chemin dense prod).
    assert rec_v1["served_ids"] == rec_v2["served_ids"]


# ============================================================================
# 4. Table repr vide — no-op bruyant UNE fois, jamais une erreur par requête
# ============================================================================


@_requires_db
async def test_v2_empty_table_noop_warns_once_never_errors(
    client, mock_embed, monkeypatch, caplog
):
    await _wipe_reprs()
    monkeypatch.setattr(context_shadow, "_V2_NOOP_WARNED", False)
    monkeypatch.setenv(context_shadow.FLAG_SHADOW_V2_ENABLED, "1")
    errors_before = context_shadow.COUNTERS["shadow_v2_error"]
    watermark = await _receipts_watermark()

    with caplog.at_level(logging.WARNING, logger="arac.services.context_shadow"):
        r1 = await client.post("/v1/atoms/recall", json={"query": QUERY, "k": 5})
        r2 = await client.post("/v1/atoms/recall", json={"query": QUERY, "k": 5})

    assert r1.status_code == 200 and r2.status_code == 200
    # No-op : aucun reçu (un reçu d'abstention serait un mensonge — pas de
    # corpus v2), aucun compteur d'erreur.
    assert await _receipts_after(watermark) == []
    assert context_shadow.COUNTERS["shadow_v2_error"] == errors_before
    # Bruyant UNE fois par process (throttlé) — pas une ligne par requête.
    warnings = [
        rec for rec in caplog.records
        if rec.getMessage() == "context_shadow_v2.no_reprs"
    ]
    assert len(warnings) == 1
    assert getattr(warnings[0], "reason", None) == "empty"


# ============================================================================
# 5. Erreur v2 simulée — 200, compteur v2 (jamais v1), reçu v1 intact
# ============================================================================


@_requires_db
async def test_v2_error_never_breaks_recall_and_counter_is_separate(
    client, mock_embed, monkeypatch, caplog
):
    await _seed_atoms_with_reprs(client, count=3)
    monkeypatch.setenv(context_shadow.FLAG_SHADOW_ENABLED, "1")
    monkeypatch.setenv(context_shadow.FLAG_SHADOW_V2_ENABLED, "1")

    async def _boom(*args, **kwargs):
        raise RuntimeError("panne shadow v2 simulee")

    monkeypatch.setattr(context_shadow, "_shadow_v2_candidates", _boom)
    v1_errors_before = context_shadow.COUNTERS["shadow_error"]
    v2_errors_before = context_shadow.COUNTERS["shadow_v2_error"]
    watermark = await _receipts_watermark()

    with caplog.at_level(logging.ERROR, logger="arac.services.context_shadow"):
        r = await client.post("/v1/atoms/recall", json={"query": QUERY, "k": 5})

    # INVARIANT : une panne v2 ne fait JAMAIS échouer le recall...
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)
    # ... compteur v2 incrémenté, compteur v1 INTACT (observabilité séparée).
    assert context_shadow.COUNTERS["shadow_v2_error"] == v2_errors_before + 1
    assert context_shadow.COUNTERS["shadow_error"] == v1_errors_before
    error_events = [
        rec for rec in caplog.records
        if rec.levelno == logging.ERROR
        and rec.getMessage() == "context_shadow_v2.failed"
    ]
    assert error_events, "log ERROR context_shadow_v2.failed attendu"
    assert getattr(error_events[0], "error", None) == "RuntimeError"

    # Le reçu V1, lui, est écrit quand même (les moteurs sont indépendants).
    receipts = await _receipts_after(watermark)
    assert len(receipts) == 1
    assert receipts[0]["engine_version"] == context_shadow.ENGINE_VERSION

    # La connexion poolée reste saine après le SAVEPOINT rollback v2.
    r2 = await client.post("/v1/atoms/recall", json={"query": QUERY, "k": 5})
    assert r2.status_code == 200


# ============================================================================
# Hygiène de contrat (hermétique — pas besoin de DB)
# ============================================================================


def test_repr_version_v2_matches_recipe_key():
    """La constante anti-boot de context_shadow DOIT égaler la clé de table
    gelée de la recette (app/repr/recipe.py) — une divergence rendrait le
    shadow-v2 silencieusement aveugle (kNN sur une version inexistante)."""
    from app.repr.recipe import REPR_VERSION

    assert context_shadow.REPR_VERSION_V2 == REPR_VERSION


def test_context_shadow_does_not_import_repr_lib_at_module_level():
    """Garde anti-boot : importer le moteur shadow ne charge JAMAIS
    `app.repr.*` (numpy/tiktoken hors du chemin requête API) — prouvé dans
    un interpréteur FRAIS (sys.modules du process de test est pollué par
    les autres imports)."""
    code = (
        "import sys; import app.services.context_shadow; "
        "polluted = [m for m in sys.modules if m.startswith('app.repr')]; "
        "assert not polluted, polluted"
    )
    # cwd = la racine du dépôt, résolue depuis ce fichier — jamais un chemin
    # absolu écrit en dur : la suite doit tourner chez n'importe qui.
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    assert proc.returncode == 0, proc.stderr
