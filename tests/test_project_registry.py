"""Tests hermétiques du routeur de reprise (app/services/project_registry).

Sans DB : on injecte une fausse connexion async qui renvoie des lignes canoniques
selon le SQL. Valide : littéral vecteur, projection atome, routage confiant,
rejet open-set (fail-open), expansion top-2.
"""
import asyncio

from app.services import project_registry as pr


def test_vec_literal():
    assert pr._vec_literal([1.0, 2.5, -0.25]) == "[1.0,2.5,-0.25]"


def test_atom_projection():
    a = pr._atom({"id": "abc", "kind": "fact", "scope": "travail/finance",
                  "key": "k", "value": "v", "distance": 0.4})
    assert a == {"id": "abc", "kind": "fact", "scope": "travail/finance",
                 "key": "k", "value": "v", "distance": 0.4}


class _FakeCur:
    def __init__(self, nearest, atoms, raise_on_nearest=False):
        self._nearest, self._atoms, self._raise = nearest, atoms, raise_on_nearest
        self._last = ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, sql, params=None):
        self._last = sql
        if "project_registry" in sql and self._raise:
            raise RuntimeError("relation does not exist")

    async def fetchall(self):
        if "project_registry" in self._last:
            return list(self._nearest)
        return list(self._atoms)


class _FakeConn:
    def __init__(self, nearest, atoms, raise_on_nearest=False):
        self._n, self._a, self._r = nearest, atoms, raise_on_nearest

    def cursor(self, row_factory=None):
        return _FakeCur(self._n, self._a, self._r)

    async def rollback(self):
        pass


def test_route_confident():
    nearest = [{"scope": "travail/finance", "member_count": 15, "dist": 0.49},
               {"scope": "travail/operations", "member_count": 250, "dist": 0.60}]
    atoms = [{"id": "1", "kind": "fact", "scope": "travail/finance", "key": "k", "value": "v", "distance": 0.49}]
    r = asyncio.run(pr.route(_FakeConn(nearest, atoms), [0.1] * 3072, k=5))
    assert r["routed_scope"] == "travail/finance"
    assert r["rejected"] is False
    assert r["expanded_scopes"] == ["travail/finance"]  # marge > 0.03 -> pas d'expansion


def test_route_top2_expansion():
    nearest = [{"scope": "spa", "member_count": 9, "dist": 0.50},
               {"scope": "piscine", "member_count": 12, "dist": 0.51}]  # marge 0.01 < 0.03
    atoms = [{"id": "1", "kind": "fact", "scope": "spa", "key": "k", "value": "v", "distance": 0.50}]
    r = asyncio.run(pr.route(_FakeConn(nearest, atoms), [0.1] * 3072, k=5))
    assert r["routed_scope"] == "spa"
    assert set(r["expanded_scopes"]) == {"spa", "piscine"}


def test_route_open_set_reject():
    nearest = [{"scope": "projets/en-cours", "member_count": 36, "dist": 0.80}]
    atoms = [{"id": "1", "kind": "fact", "scope": "x", "key": "k", "value": "v", "distance": 0.80}]
    r = asyncio.run(pr.route(_FakeConn(nearest, atoms), [0.1] * 3072, k=5))
    assert r["rejected"] is True
    assert r["routed_scope"] is None
    assert r["reason"] == "open_set_reject"


def test_route_fail_open_when_registry_missing():
    atoms = [{"id": "1", "kind": "fact", "scope": "x", "key": "k", "value": "v", "distance": 0.3}]
    r = asyncio.run(pr.route(_FakeConn([], atoms, raise_on_nearest=True), [0.1] * 3072, k=5))
    assert r["rejected"] is True
    assert r["reason"] == "registry_unavailable"
    assert len(r["atoms"]) == 1
