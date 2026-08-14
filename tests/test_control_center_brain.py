"""Tests du cockpit Brain (/cc/brain) du Control Center.

Couvre :
  1. Résilience du collecteur brain_api (API down → {"error": ...}, jamais d'exception).
  2. Défense anti-fuite : _strip_value retire récursivement toute clé `value`.
  3. Auth : /cc/brain sans session → redirect login (pas de 200).
  4. /cc/brain avec session + collecteurs mockés → 200, données réelles affichées.
  5. Read-only : aucun <form method=post>, dégradation gracieuse si API down.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from control_center.collectors import brain_api
from control_center.security import sign_session

_TEST_SECRET = "test_secret_cc_not_for_production_v1"
_TEST_SUBJECT = "admin_test_brain"


def _secret_env_key() -> str:
    from control_center.config import CC_SESSION_SECRET_ENV
    return CC_SESSION_SECRET_ENV


@pytest.fixture()
def cc_client():
    os.environ[_secret_env_key()] = _TEST_SECRET
    from control_center.app import create_app
    client = TestClient(create_app(), raise_server_exceptions=True)
    yield client
    os.environ.pop(_secret_env_key(), None)


def _get_authed(client, path: str):
    from control_center.config import SESSION_COOKIE_NAME
    client.cookies.set(SESSION_COOKIE_NAME, sign_session({"sub": _TEST_SUBJECT}, secret=_TEST_SECRET))
    return client.get(path, follow_redirects=False)


# --- Données factices (forme réelle des endpoints /v1/brain/*) ---------------
_FAKE_HEALTH = {
    "health_score": 52, "severity": "warn", "write_allowed": False,
    "generated_at": "2026-06-23T23:00:00+00:00",
    "headline_signals": ["1 état dirty à réconcilier."],
    "recommendations": [{"priority": "warn", "code": "W-STATE-001", "scope": "perso/administratif", "action": "générer proposition"}],
}
_FAKE_CS = {
    "coverage_pct": 5.0, "eligible_leaf_total": 20, "with_current_state": 1,
    "scopes": [{"scope": "outillage/assistants", "risk": "low", "has_current_state": False,
                "state_dirty": False, "active_count": 4, "freshness_days": 5.1}],
}
# Forme RÉELLE d'un item /v1/brain/proposals (ProposalSummaryItem) : confidence_score / lifecycle_state.
_FAKE_PROPS = {
    "count": 1,
    "proposals": [{
        "proposal_id": "csp_abc123", "scope": "outillage/infrastructure",
        "status": "proposed", "lifecycle_state": "ready_for_review",
        "confidence_score": 77, "confidence_level": "medium",
    }],
}
_FAKE_MQ = {
    "anti_drift": {"warnings": [{"code": "W-STATE-001", "severity": "warn",
                                 "scope": "perso/administratif", "description": "feuille sans état courant"}]},
    "sensitivity": {"total_scopes": 45, "by_risk": {"low": 23, "medium": 11, "high": 11}},
}


# ============================================================================
# 1. Résilience du collecteur
# ============================================================================

def test_get_resilient_on_dead_api(monkeypatch):
    """API injoignable → {"error": "unavailable"}, jamais d'exception."""
    monkeypatch.setenv("ARAC_API_BASE", "http://127.0.0.1:1")  # port refusé immédiatement
    out = brain_api.brain_health()
    assert out.get("error") == "unavailable"


def test_strip_value_removes_value_recursively():
    """_strip_value retire toute clé 'value' à tous les niveaux."""
    payload = {"scope": "x", "value": "SECRET", "nested": {"value": "SECRET2", "ok": 1},
               "list": [{"value": "SECRET3", "k": 2}]}
    cleaned = brain_api._strip_value(payload)
    assert "value" not in cleaned
    assert "value" not in cleaned["nested"]
    assert "value" not in cleaned["list"][0]
    assert cleaned["nested"]["ok"] == 1 and cleaned["list"][0]["k"] == 2


def test_brain_health_strips_value(monkeypatch):
    """Même si l'API renvoyait une clé 'value', le collecteur la retire."""
    monkeypatch.setattr(brain_api, "_get", lambda path: {"health_score": 1, "value": "LEAK"})
    out = brain_api.brain_health()
    assert "value" not in out and out["health_score"] == 1


# ============================================================================
# 2. Auth
# ============================================================================

def test_brain_page_requires_session(cc_client):
    """/cc/brain sans cookie → redirect (pas de 200)."""
    resp = cc_client.get("/cc/brain", follow_redirects=False)
    assert resp.status_code in (302, 303, 307, 401)
    assert resp.status_code != 200


# ============================================================================
# 3. Rendu avec session + collecteurs mockés
# ============================================================================

def _patch_collectors(monkeypatch):
    monkeypatch.setattr(brain_api, "brain_health", lambda: dict(_FAKE_HEALTH))
    monkeypatch.setattr(brain_api, "current_state", lambda: dict(_FAKE_CS))
    monkeypatch.setattr(brain_api, "proposals", lambda: dict(_FAKE_PROPS))
    monkeypatch.setattr(brain_api, "memory_quality", lambda: dict(_FAKE_MQ))


def test_brain_page_200_with_session(cc_client, monkeypatch):
    """/cc/brain avec session + données → 200 et contenu réel affiché."""
    _patch_collectors(monkeypatch)
    resp = _get_authed(cc_client, "/cc/brain")
    assert resp.status_code == 200
    body = resp.text
    assert "Brain Health" in body and "52/100" in body          # health score
    assert "outillage/assistants" in body                                 # current-state leaf
    assert "W-STATE-001" in body                                 # anti-drift warning
    assert "Memory Quality" in body and "Current State" in body and "Proposals" in body


def test_brain_page_no_form_post(cc_client, monkeypatch):
    """Garantie read-only : aucune action mutatrice dans la page."""
    _patch_collectors(monkeypatch)
    body = _get_authed(cc_client, "/cc/brain").text.lower()
    assert "method=\"post\"" not in body and "method=post" not in body


def test_brain_page_proposal_real_fields_rendered(cc_client, monkeypatch):
    """M1 : la proposition affiche le vrai schéma (lifecycle_state + confidence_score)."""
    _patch_collectors(monkeypatch)
    body = _get_authed(cc_client, "/cc/brain").text
    assert "csp_abc123" in body and "outillage/infrastructure" in body
    assert "ready_for_review" in body          # lifecycle_state (Statut)
    assert "77" in body                         # confidence_score (Confiance) — était blanc avant fix


def test_brain_page_none_renders_dash(cc_client, monkeypatch):
    """L1 : un champ présent mais None s'affiche '—', jamais le littéral 'None'."""
    _patch_collectors(monkeypatch)
    monkeypatch.setattr(brain_api, "current_state", lambda: {
        "coverage_pct": 5.0, "eligible_leaf_total": 20, "with_current_state": 1,
        "scopes": [{"scope": None, "risk": None, "has_current_state": None,
                    "state_dirty": None, "active_count": None, "freshness_days": None}],
    })
    body = _get_authed(cc_client, "/cc/brain").text
    # la cellule scope/risk None ne doit pas rendre le texte 'None'
    assert "<td>None</td>" not in body


def test_brain_page_escapes_xss(cc_client, monkeypatch):
    """Sécurité : une donnée brain hostile est échappée (jamais de <script> brut)."""
    _patch_collectors(monkeypatch)
    monkeypatch.setattr(brain_api, "memory_quality", lambda: {
        "anti_drift": {"warnings": [{"code": "W-X", "severity": "warn",
                                     "scope": "<script>alert(1)</script>",
                                     "description": "<img src=x onerror=alert(1)>"}]},
        "sensitivity": {"total_scopes": 1, "by_risk": {"low": 1}},
    })
    body = _get_authed(cc_client, "/cc/brain").text
    assert "<script>alert(1)</script>" not in body
    assert "<img src=x onerror" not in body
    assert "&lt;script&gt;" in body            # bien échappé


def test_brain_page_graceful_when_api_down(cc_client, monkeypatch):
    """Si chaque collecteur renvoie une erreur, la page reste 200 et signale l'indispo."""
    monkeypatch.setattr(brain_api, "brain_health", lambda: {"error": "unavailable"})
    monkeypatch.setattr(brain_api, "current_state", lambda: {"error": "unavailable"})
    monkeypatch.setattr(brain_api, "proposals", lambda limit=25: {"error": "unavailable"})
    monkeypatch.setattr(brain_api, "memory_quality", lambda: {"anti_drift": {"error": "unavailable"}, "sensitivity": {"error": "unavailable"}})
    resp = _get_authed(cc_client, "/cc/brain")
    assert resp.status_code == 200
    assert "indisponible" in resp.text.lower()
