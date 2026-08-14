"""Tests d'intégration Phase 4.5 anti-drift warnings.

Couvre :
- W-004 critical : 409 sans flag, 201 + warning consigné avec flag
- W-002 info : tag non-canonique au POST
- W-003 info : decision avec rationale court (< 200 chars)
- AtomRead.warnings : champ présent et vide par défaut, peuplé sinon

Stratégie cohérente avec test_atoms_api.py : mock_embed + key="test-*" pour
cleanup automatique via conftest.py.

Cf la doctrine anti-dérive §3.2 pour
le catalogue des 7 warnings et leurs déclencheurs.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL_ADMIN"),
    reason="DB reelle requise",
)

SEED_NODE = "test-node"


# ============================================================================
# W-004 — drop_pierre_angulaire_without_acknowledge (critical, 409 bloquant)
# ============================================================================


async def test_supersede_pa_without_flag_returns_409(client, mock_embed):
    """Supersede d'un atome pierre-angulaire en droppant le tag SANS flag → 409
    avec body structuré contenant un Warning W-004 critical."""
    # 1. Créer un atome pierre-angulaire
    create = await client.post(
        "/v1/atoms",
        json={
            "kind": "pattern",
            "scope": "outillage/assistants",
            "key": "test-pa-w004-base",
            "value": "Pattern pierre-angulaire de référence",
            "tags": ["pierre-angulaire"],
            "node_id": SEED_NODE,
        },
    )
    assert create.status_code == 201, create.text
    old_id = create.json()["id"]

    # 2. Supersede en droppant le tag, sans flag → doit retourner 409
    r = await client.post(
        f"/v1/atoms/{old_id}/supersede",
        json={
            "new_value": "Pattern v2 sans tag pierre-angulaire",
            "new_tags": [],  # explicit drop
            "new_node_id": SEED_NODE,
        },
    )
    assert r.status_code == 409, r.text

    body = r.json()
    # FastAPI enveloppe `detail` (dict ou str) tel quel
    detail = body["detail"]
    assert isinstance(detail, dict), f"expected dict detail, got {type(detail)}"
    assert "warnings" in detail
    assert len(detail["warnings"]) == 1
    w = detail["warnings"][0]
    assert w["code"] == "W-004"
    assert w["severity"] == "critical"
    assert "acknowledge_drop_pierre_angulaire" in (
        w.get("remediation_hint") or ""
    )
    assert w["context"]["atom_id"] == old_id
    assert w["context"]["new_tags"] == []


async def test_supersede_pa_with_flag_creates_successfully(client, mock_embed):
    """Supersede d'un atome pierre-angulaire AVEC flag d'acquittement → 201,
    le nouvel atome n'a plus le tag, le W-004 n'est pas dans warnings (il a
    été acquitté). Trace W-004 émise via log avant le 409 quand applicable,
    pas ici (pas de 409)."""
    create = await client.post(
        "/v1/atoms",
        json={
            "kind": "pattern",
            "scope": "outillage/assistants",
            "key": "test-pa-w004-ack",
            "value": "Pattern pierre-angulaire à démoter",
            "tags": ["pierre-angulaire"],
            "node_id": SEED_NODE,
        },
    )
    assert create.status_code == 201, create.text
    old_id = create.json()["id"]

    r = await client.post(
        f"/v1/atoms/{old_id}/supersede",
        json={
            "new_value": "Pattern v2 démoté volontairement après revue",
            "new_tags": [],  # explicit drop
            "new_rationale": (
                "Démotion : ne passe plus les 5 tests du critère de "
                "promotion-pierre-angulaire-critere, doublon partiel avec "
                "pattern X plus large."
            ),
            "new_node_id": SEED_NODE,
            "acknowledge_drop_pierre_angulaire": True,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["version"] == 2
    assert body["status"] == "active"
    assert "pierre-angulaire" not in body["tags"]
    # Le W-004 n'apparaît pas dans warnings (il a été acquitté → pas re-émis
    # côté success). Phase 4.6 ajoutera une trace audit_log explicite du flag.
    codes = [w["code"] for w in body.get("warnings", [])]
    assert "W-004" not in codes


# ============================================================================
# W-002 — tag_drift_non_conventional (info)
# ============================================================================


async def test_create_with_non_canonical_tag_returns_w002(client, mock_embed):
    """POST atome avec tag hors {pierre-angulaire, founding-atom,
    recalibration-candidate} → warning W-002 info."""
    r = await client.post(
        "/v1/atoms",
        json={
            "kind": "note",
            "scope": "travail/operations",
            "key": "test-w002-noncanonical",
            "value": "Note avec tag custom",
            "tags": ["random-custom-tag"],
            "node_id": SEED_NODE,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    codes = [w["code"] for w in body.get("warnings", [])]
    assert "W-002" in codes
    w002 = next(w for w in body["warnings"] if w["code"] == "W-002")
    assert w002["severity"] == "info"
    assert "random-custom-tag" in w002["context"]["non_canonical_tags"]


async def test_create_with_canonical_tag_no_w002(client, mock_embed):
    """POST avec uniquement des tags canoniques → pas de W-002."""
    r = await client.post(
        "/v1/atoms",
        json={
            "kind": "note",
            "scope": "travail/operations",
            "key": "test-w002-canonical",
            "value": "Note avec tag canonique",
            "tags": ["pierre-angulaire"],
            "node_id": SEED_NODE,
        },
    )
    assert r.status_code == 201, r.text
    codes = [w["code"] for w in r.json().get("warnings", [])]
    assert "W-002" not in codes


# ============================================================================
# W-003 — rationale_too_short_for_decision (info)
# ============================================================================


async def test_create_decision_short_rationale_returns_w003_info(
    client, mock_embed,
):
    """POST decision avec rationale < 200 chars → warning W-003 info."""
    r = await client.post(
        "/v1/atoms",
        json={
            "kind": "decision",
            "scope": "travail/operations",
            "key": "test-w003-short",
            "value": "Décision X",
            "rationale": "Parce que Y",  # 11 chars
            "node_id": SEED_NODE,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    codes = [w["code"] for w in body.get("warnings", [])]
    assert "W-003" in codes
    w003 = next(w for w in body["warnings"] if w["code"] == "W-003")
    assert w003["severity"] == "info"
    assert w003["context"]["length"] == 11
    assert w003["context"]["target_min"] == 200


async def test_create_decision_long_rationale_no_w003(client, mock_embed):
    """POST decision avec rationale >= 200 chars → pas de W-003."""
    long_rationale = "Détaillé : " + ("a" * 250)
    r = await client.post(
        "/v1/atoms",
        json={
            "kind": "decision",
            "scope": "travail/operations",
            "key": "test-w003-long",
            "value": "Décision Z",
            "rationale": long_rationale,
            "node_id": SEED_NODE,
        },
    )
    assert r.status_code == 201, r.text
    codes = [w["code"] for w in r.json().get("warnings", [])]
    assert "W-003" not in codes


# ============================================================================
# AtomRead.warnings field default + backward-compat
# ============================================================================


async def test_create_nominal_has_empty_warnings_list(client, mock_embed):
    """POST nominal (note, scope travail-pos, tag canonique ou aucun) → warnings
    field présent et tel que les warnings non-déclenchés ne sont pas listés."""
    r = await client.post(
        "/v1/atoms",
        json={
            "kind": "note",
            "scope": "travail/operations",
            "key": "test-warnings-empty",
            "value": "Note nominale sans rien de spécial",
            "node_id": SEED_NODE,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert "warnings" in body
    assert isinstance(body["warnings"], list)
    # W-002 pas déclenché (tags vides), W-003 pas déclenché (pas decision),
    # W-005 pas déclenché (mono-monde TRAVAIL), W-006 dépend de l'historique
    # récent, W-007 dépend de l'historique node — peut apparaître ou non.
    # On vérifie au minimum que W-002 et W-003 sont absents.
    codes = [w["code"] for w in body["warnings"]]
    assert "W-002" not in codes
    assert "W-003" not in codes


async def test_get_atom_warnings_empty_on_read(client, mock_embed):
    """GET /v1/atoms/{id} → warnings vide (pas re-calculés au read, Phase 4.5
    backward-compat : le champ est par défaut [])."""
    create = await client.post(
        "/v1/atoms",
        json={
            "kind": "note",
            "scope": "travail/operations",
            "key": "test-warnings-read",
            "value": "Note pour read",
            "tags": ["random-tag"],  # déclenche W-002 au POST
            "node_id": SEED_NODE,
        },
    )
    assert create.status_code == 201
    aid = create.json()["id"]
    # Le POST a émis W-002
    codes_post = [w["code"] for w in create.json()["warnings"]]
    assert "W-002" in codes_post

    # Le GET ne re-calcule pas → warnings == []
    r = await client.get(f"/v1/atoms/{aid}")
    assert r.status_code == 200
    assert r.json()["warnings"] == []
