"""Tests HERMÉTIQUES (zéro DB) des gardes kNN de
`app/services/context_shadow._knn_pool` (FOLD V2, fix revue
adversariale round 1).

Finding corrigé : `hnsw.ef_search = 100 == LIMIT 100` ne garantit PAS le
contrat top-100 — l'index HNSW émet exactement `ef_search` tuples et les
filtres de la requête (status/scope/kind) s'appliquent APRÈS la sortie du
graphe (prouvé pgvector 0.8.2 : pool 0/100 sous index avec 300 voisins
plus proches hors-filtre). Le garant est
`SET LOCAL hnsw.iterative_scan = strict_order`, posé dans un SAVEPOINT
dédié, sondé UNE fois par process, avec repli bruyant ef_search seul sur
pgvector < 0.8 (GUC absent → UndefinedObject).

La preuve SQL réelle (index + filtre + iterative_scan → 100/100) est le
repro d'audit `repro2b_ef_search.sql`, pas un test CI — ici on prouve le
CONTRAT du code : ordre des SET, savepoint d'isolation, sonde cachée,
repli sans erreur par requête.
"""

from __future__ import annotations

import logging

import pytest
from psycopg import errors as pg_errors

from app.services import context_shadow


class FakeTransaction:
    """CM async minimal : compte les entrées (savepoints) ; une exception
    dans le corps se propage (comme psycopg : ROLLBACK TO SAVEPOINT puis
    re-raise)."""

    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        self._conn.savepoints += 1
        return self

    async def __aexit__(self, *exc):
        return False


class FakeCursor:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, sql, params=None):
        self._conn.executed.append(sql)
        if (self._conn.iterative_scan_guc_missing
                and "hnsw.iterative_scan" in sql):
            raise self._conn.guc_error_cls(
                'unrecognized configuration parameter "hnsw.iterative_scan"')

    async def fetchall(self):
        return []


class FakeConn:
    def __init__(self, *, iterative_scan_guc_missing=False,
                 guc_error_cls=pg_errors.UndefinedObject):
        self.executed: list[str] = []
        self.savepoints = 0
        self.iterative_scan_guc_missing = iterative_scan_guc_missing
        self.guc_error_cls = guc_error_cls

    def cursor(self, **kw):
        return FakeCursor(self)

    def transaction(self):
        return FakeTransaction(self)


@pytest.fixture(autouse=True)
def _reset_probe(monkeypatch):
    """La sonde est cachée au niveau process — chaque test repart de None."""
    monkeypatch.setattr(context_shadow, "_ITERATIVE_SCAN_SUPPORTED", None)


async def test_knn_pool_pins_ef_search_then_iterative_scan_in_savepoint():
    """Les DEUX SET précèdent le kNN ; iterative_scan vit dans son propre
    savepoint (un GUC absent ne doit jamais empoisonner la transaction de
    l'appelant) ; la sonde est mémorisée True."""
    conn = FakeConn()
    candidates, scope_by_id = await context_shadow._knn_pool(
        conn, "SELECT knn", ("p",))
    assert candidates == [] and scope_by_id == {}
    assert conn.executed == [
        context_shadow._SET_EF_SEARCH_SQL,
        context_shadow._SET_ITERATIVE_SCAN_SQL,
        "SELECT knn",
    ]
    assert conn.savepoints == 1  # savepoint DÉDIÉ au SET iterative_scan
    assert context_shadow._ITERATIVE_SCAN_SUPPORTED is True


@pytest.mark.parametrize("error_cls", [
    # 42704 : GUC inconnu (préfixe hnsw non réservé / pas de pgvector) ;
    # 42602 : pgvector < 0.8 chargé — préfixe `hnsw` RÉSERVÉ → « invalid
    # configuration parameter name » (le visage RÉEL de l'absence du GUC
    # quand l'extension est là).
    pg_errors.UndefinedObject,
    pg_errors.InvalidName,
])
async def test_knn_pool_falls_back_loudly_when_guc_missing(
        caplog, monkeypatch, error_cls):
    """pgvector < 0.8 : échec du SET → repli ef_search seul (comportement
    pré-fix), WARNING bruyant, le kNN s'exécute quand même — JAMAIS une
    erreur par requête."""
    monkeypatch.setattr(context_shadow, "_ITERATIVE_SCAN_SUPPORTED", None)
    conn = FakeConn(iterative_scan_guc_missing=True, guc_error_cls=error_cls)
    with caplog.at_level(logging.WARNING,
                         logger="arac.services.context_shadow"):
        await context_shadow._knn_pool(conn, "SELECT knn", ("p",))
    assert conn.executed[-1] == "SELECT knn"  # le kNN a bien tourné
    assert context_shadow._ITERATIVE_SCAN_SUPPORTED is False
    assert any("iterative_scan_unavailable" in r.getMessage()
               for r in caplog.records)


async def test_probe_cached_false_skips_the_set_on_next_calls():
    """Sonde False mémorisée : les appels suivants ne re-tentent JAMAIS le
    SET (zéro savepoint, zéro statement inutile par requête)."""
    conn = FakeConn(iterative_scan_guc_missing=True)
    await context_shadow._knn_pool(conn, "SELECT knn", ("p",))
    conn2 = FakeConn(iterative_scan_guc_missing=True)
    await context_shadow._knn_pool(conn2, "SELECT knn", ("p",))
    assert conn2.savepoints == 0
    assert not any("iterative_scan" in s for s in conn2.executed)
    assert conn2.executed == [context_shadow._SET_EF_SEARCH_SQL, "SELECT knn"]
