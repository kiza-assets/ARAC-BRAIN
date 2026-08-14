"""Tests HTTP du router /v1/brain (read-only). Aucune DB : `provide_*` surchargés.

DOIT être exécuté depuis le worktree (PYTHONPATH=worktree) pour importer le bon
package `app` (celui qui enregistre le brain_router). Cf commande de reprise.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


def _brain_wired() -> bool:
    """True si la Brain API est enregistrée dans app.main (wirée)."""
    try:
        from app import main as _m
        return any(getattr(r, "path", "").startswith("/v1/brain")
                   for r in _m.app.routes)
    except Exception:
        return False


# RC1 convergence : la Brain API est volontairement NON wirée (non wirée par défaut). Ces tests HTTP
# ne valent que si le router est enregistré → skip propre sinon (et run en night-evo / post-deploy).
pytestmark = pytest.mark.skipif(
    not _brain_wired(),
    reason="Brain API non enregistrée (/v1/brain non wiré — RC1 convergence)")

_NOW = datetime(2026, 6, 22, tzinfo=timezone.utc)


def _atom(scope, kind="note", status="active", days_ago=2, key=None, idx=0):
    ts = (_NOW - timedelta(days=days_ago)).isoformat()
    a = {"id": f"{scope}-{idx}", "scope": scope, "kind": kind, "status": status,
         "created_at": ts, "updated_at": ts, "value": "SECRET-PRIVATE-XYZ"}
    if key:
        a["key"] = key
    return a


ATOMS = (
    [_atom("travail/operations", days_ago=2, idx=i) for i in range(6)]
    + [_atom("travail/operations", kind="state", key="current", days_ago=1, idx=99)]  # a un état
    + [_atom("perso/sante", days_ago=2, idx=i) for i in range(6)]           # HIGH
    + [_atom("outillage", idx=i) for i in range(9)]                              # root debt
)


@pytest_asyncio.fixture
async def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ARAC_PROPOSAL_DIR", str(tmp_path))
    from app import main as app_main
    from app.routers import brain as brain_mod

    app_main.app.dependency_overrides[brain_mod.provide_atoms] = lambda: ATOMS
    app_main.app.dependency_overrides[brain_mod.provide_conversations] = \
        lambda: {"curated": 200, "pending": 0, "failed": 1, "total": 201}
    transport = ASGITransport(app=app_main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c._brain_mod = brain_mod  # type: ignore[attr-defined]
        yield c
    app_main.app.dependency_overrides.clear()


# ----------------------------------------------------------------- health
async def test_health(client):
    r = await client.get("/v1/brain/health")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["report"] == "brain_health"
    assert b["write_allowed"] is False
    assert 0 <= b["health_score"] <= 100
    assert b["conversations"]["failed"] == 1


# ----------------------------------------------------------------- current-state
async def test_current_state(client):
    r = await client.get("/v1/brain/current-state")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["write_allowed"] is False
    scopes = {s["scope"]: s for s in b["scopes"]}
    assert scopes["travail/operations"]["has_current_state"] is True
    assert scopes["perso/sante"]["risk"] == "high"
    assert scopes["perso/sante"]["review_level"] == "mandatory"
    # racine nue arac jamais dans les feuilles
    assert "outillage" not in scopes
    # couverture sur feuilles éligibles uniquement, cohérente (déf. #15) :
    # travail/operations (éligible, a un état) + perso/sante (éligible, sans état) = 2 ; 1 couverte.
    assert b["eligible_leaf_total"] == 2
    assert b["with_current_state"] == 1
    assert b["coverage_pct"] == 50.0


async def test_current_state_filter_risk(client):
    r = await client.get("/v1/brain/current-state?risk=high")
    assert r.status_code == 200, r.text
    for s in r.json()["scopes"]:
        assert s["risk"] == "high"


async def test_current_state_filter_invalid_risk_422(client):
    r = await client.get("/v1/brain/current-state?risk=ultra")
    assert r.status_code == 422


async def test_current_state_scope_detail(client):
    r = await client.get("/v1/brain/current-state/travail/operations")
    assert r.status_code == 200, r.text
    assert r.json()["scope"]["scope"] == "travail/operations"


async def test_current_state_scope_404(client):
    r = await client.get("/v1/brain/current-state/travail/inexistant-leaf")
    assert r.status_code == 404


# ----------------------------------------------------------------- anti-drift
async def test_anti_drift(client):
    r = await client.get("/v1/brain/anti-drift")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["report"] == "anti_drift"
    # 1 conversation échouée -> W-STATE-009
    assert any(w["code"] == "W-STATE-009" for w in b["warnings"])


# ----------------------------------------------------------------- sensitivity
async def test_sensitivity(client):
    r = await client.get("/v1/brain/sensitivity")
    assert r.status_code == 200, r.text
    assert r.json()["by_risk"]["high"] >= 1


# ----------------------------------------------------------------- proposals
async def test_proposals_empty(client):
    r = await client.get("/v1/brain/proposals")
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 0


async def test_proposals_stored_and_redacted(client, tmp_path):
    store = client._brain_mod.store
    candidate = {
        "scope": "travail/operations", "proposed_key": "current", "proposed_kind": "state",
        "proposed_status": "dry_run", "summary": "3 sources ; 1 decision.",
        "active_decisions": [], "blockers": [], "next_actions": [], "risks": [],
        "stale_items": [], "source_atom_ids": ["11111111-1111-1111-1111-111111110101"],
        "source_count": 1, "source_state_ids": [], "anti_auto_citation_ok": True,
        "no_source_reason": "", "confidence_level": "agent_suggest",
        "confidence_score": 60, "human_review_required": False, "sensitive_flags": [],
        "would_force": False, "write_allowed": False,
        "generated_at": "2026-06-22T00:00:00+00:00",
    }
    prop, _ = store.create_proposal(candidate, str(tmp_path),
                                    now_iso="2026-06-22T00:00:00+00:00")
    pid = prop["proposal_id"]

    r = await client.get("/v1/brain/proposals")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1
    assert body["proposals"][0]["scope"] == "travail/operations"
    assert body["proposals"][0]["write_allowed"] is False

    r2 = await client.get(f"/v1/brain/proposals/{pid}")
    assert r2.status_code == 200, r2.text
    assert r2.json()["write_allowed"] is False


async def test_proposals_filter_by_risk(client, tmp_path):
    """VAGUE 4 : risk désormais non-null (comble le gap V2) + filtre ?risk= câblé."""
    store = client._brain_mod.store
    cand = {
        "scope": "travail/operations", "proposed_key": "current", "proposed_kind": "state",
        "proposed_status": "dry_run", "summary": "x", "active_decisions": [],
        "blockers": [], "next_actions": [], "risks": [], "stale_items": [],
        "source_atom_ids": ["11111111-1111-1111-1111-111111110101"], "source_count": 1,
        "source_state_ids": [], "anti_auto_citation_ok": True, "no_source_reason": "",
        "confidence_level": "agent_suggest", "confidence_score": 60,
        "human_review_required": False, "sensitive_flags": [], "would_force": False,
        "write_allowed": False, "generated_at": "2026-06-22T00:00:00+00:00",
    }
    store.create_proposal(cand, str(tmp_path), now_iso="2026-06-22T00:00:00+00:00")
    allp = (await client.get("/v1/brain/proposals")).json()
    assert allp["count"] == 1
    risk = allp["proposals"][0]["risk"]
    assert risk in ("low", "medium", "high")                  # plus jamais None
    assert (await client.get(f"/v1/brain/proposals?risk={risk}")).json()["count"] == 1
    other = "high" if risk != "high" else "low"
    assert (await client.get(f"/v1/brain/proposals?risk={other}")).json()["count"] == 0
    assert (await client.get("/v1/brain/proposals?risk=ultra")).status_code == 422


async def test_proposal_clean_invalid_id_404(client):
    # un id au charset slug inoffensif mais invalide = ressource
    # introuvable (404, cohérence REST avec sessions/atoms/scope). Un id réellement
    # dangereux reste un 400 (cf tests/test_assault_brain_proposal_404.py).
    r = await client.get("/v1/brain/proposals/not-a-valid-id")
    assert r.status_code == 404


async def test_proposal_unknown_404(client):
    r = await client.get("/v1/brain/proposals/csp_deadbeefdeadbeef")
    assert r.status_code == 404


# ----------------------------------------------------------------- no leak
async def test_no_atom_value_leak_any_endpoint(client):
    for path in ("/v1/brain/health", "/v1/brain/current-state",
                 "/v1/brain/anti-drift", "/v1/brain/current-state/travail/operations"):
        r = await client.get(path)
        assert "SECRET-PRIVATE-XYZ" not in r.text, path
