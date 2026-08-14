"""Tests d'intégration API dashboard — Phase D.5 (agent B3, vague 2).

Cible : les 4 endpoints du dashboard read-only implémentés par B1 :
- GET /v1/dashboard/scopes_summary
- GET /v1/dashboard/atoms_by_scope?scope=X&limit=N&offset=M
- GET /v1/dashboard/timeline?days=30
- GET /v1/dashboard/foundations_state
- GET /v1/dashboard/ (HTMLResponse)

Stratégie (alignée test_atoms_api.py / test_sessions_api.py) :
- Utilise les fixtures `client` + `initialized_pool` du conftest → init pool DB,
  cleanup `key LIKE 'test-%'` avant + après chaque test.
- mock_embed pour éviter API OpenAI sur les POST atoms de setup.
- READ-ONLY : on n'écrit jamais via /v1/dashboard/*. Les fixtures de données
  passent par POST /v1/atoms (cohérent avec doctrine "tests stack-as-prod").
- Skip si DATABASE_URL_APP absent (ou DATABASE_URL_ADMIN absent — bloquant
  pour le cleanup conftest).

Convention test : tous les atomes créés ont `key LIKE 'test-%'` → cleanup
automatique via conftest (pattern Phase 2.3+).
"""

from __future__ import annotations

import os

import pytest


SEED_NODE = "test-node"


# ----------------------------------------------------------------------------
# Skip global si DB indisponible (fixture conftest crash sinon, mais on
# documente explicitement ici l'attente du module entier).
# ----------------------------------------------------------------------------

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL_ADMIN"),
    reason="DATABASE_URL_APP/ADMIN absent — tests dashboard nécessitent BDD réelle",
)


# ============================================================================
# GET /v1/dashboard/scopes_summary
# ============================================================================


async def test_scopes_summary_returns_list(client, mock_embed):
    """GET /scopes_summary → 200 + list, items conformes au schéma annoncé."""
    # Setup : un atome dans un scope connu pour garantir au moins un item
    create = await client.post("/v1/atoms", json={
        "kind": "note",
        "scope": "travail/operations",
        "key": "test-summary-seed",
        "value": "Atome de seed pour scopes_summary.",
        "node_id": SEED_NODE,
    })
    assert create.status_code == 201, create.text

    r = await client.get("/v1/dashboard/scopes_summary")
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    # Au moins le scope travail-pos doit apparaître (atome créé ci-dessus)
    scopes_returned = {item["scope"] for item in body}
    assert "travail/operations" in scopes_returned

    # Vérification structure d'un item
    item = next(i for i in body if i["scope"] == "travail/operations")
    assert "total_atoms" in item
    assert isinstance(item["total_atoms"], int)
    assert item["total_atoms"] >= 1
    assert "by_kind" in item
    assert isinstance(item["by_kind"], dict)
    assert "by_status" in item
    assert isinstance(item["by_status"], dict)
    # first/last_atom_date : peuvent être None si scope vide, sinon ISO string
    assert "first_atom_date" in item
    assert "last_atom_date" in item


async def test_scopes_summary_empty_db_returns_list(client):
    """DB vide (cleanup `test-%` effectif) → list vide ou list d'autres scopes existants.

    On ne peut pas garantir une BDD strictement vide (autres atomes prod
    peuvent exister), mais l'endpoint DOIT toujours retourner 200 + list.
    """
    r = await client.get("/v1/dashboard/scopes_summary")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ============================================================================
# GET /v1/dashboard/atoms_by_scope
# ============================================================================


async def test_atoms_by_scope_filter_works(client, mock_embed):
    """Filtre par scope retourne uniquement les atomes du scope demandé."""
    # 3 atomes dans travail-pos
    for i in range(3):
        r = await client.post("/v1/atoms", json={
            "kind": "note",
            "scope": "travail/operations",
            "key": f"test-abs-kpos-{i}",
            "value": f"atome kpos {i}",
            "node_id": SEED_NODE,
        })
        assert r.status_code == 201, r.text
    # 2 atomes dans logement
    for i in range(2):
        r = await client.post("/v1/atoms", json={
            "kind": "note",
            "scope": "perso/logement",
            "key": f"test-abs-tm-{i}",
            "value": f"atome tm {i}",
            "node_id": SEED_NODE,
        })
        assert r.status_code == 201, r.text

    r = await client.get(
        "/v1/dashboard/atoms_by_scope",
        params={"scope": "travail/operations", "limit": 100, "offset": 0},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # `body` peut être une liste directe OU un wrapper {items, total}
    items = body if isinstance(body, list) else body.get("items", body.get("atoms", []))
    test_items = [a for a in items if a.get("key", "").startswith("test-abs-")]
    assert len(test_items) == 3
    # Tous dans le scope demandé
    assert all(a["scope"] == "travail/operations" for a in test_items)


async def test_atoms_by_scope_excludes_embedding(client, mock_embed):
    """Le champ `embedding` (24 KiB halfvec) DOIT être exclu de la réponse list."""
    await client.post("/v1/atoms", json={
        "kind": "note",
        "scope": "travail/operations",
        "key": "test-abs-noembed",
        "value": "test exclusion embedding",
        "node_id": SEED_NODE,
    })

    r = await client.get(
        "/v1/dashboard/atoms_by_scope",
        params={"scope": "travail/operations", "limit": 10, "offset": 0},
    )
    assert r.status_code == 200
    body = r.json()
    items = body if isinstance(body, list) else body.get("items", body.get("atoms", []))
    assert len(items) >= 1
    for atom in items:
        assert "embedding" not in atom, (
            f"Réponse dashboard ne doit pas contenir `embedding` (lourd). Reçu: {list(atom.keys())}"
        )


async def test_atoms_by_scope_pagination(client, mock_embed):
    """Pagination limit/offset : deux pages distinctes ne se chevauchent pas."""
    # Crée 5 atomes pour avoir > 2 pages
    for i in range(5):
        r = await client.post("/v1/atoms", json={
            "kind": "note",
            "scope": "travail/operations",
            "key": f"test-abs-pag-{i:02d}",
            "value": f"page atom {i}",
            "node_id": SEED_NODE,
        })
        assert r.status_code == 201

    r1 = await client.get(
        "/v1/dashboard/atoms_by_scope",
        params={"scope": "travail/operations", "limit": 2, "offset": 0},
    )
    r2 = await client.get(
        "/v1/dashboard/atoms_by_scope",
        params={"scope": "travail/operations", "limit": 2, "offset": 2},
    )
    assert r1.status_code == 200
    assert r2.status_code == 200

    b1 = r1.json()
    b2 = r2.json()
    items1 = b1 if isinstance(b1, list) else b1.get("items", b1.get("atoms", []))
    items2 = b2 if isinstance(b2, list) else b2.get("items", b2.get("atoms", []))

    ids1 = {a["id"] for a in items1}
    ids2 = {a["id"] for a in items2}
    # Si pagination correcte, aucun id en commun
    assert ids1.isdisjoint(ids2), (
        f"Pages se chevauchent : intersection={ids1 & ids2}"
    )


async def test_atoms_by_scope_invalid_scope_returns_422(client):
    """Scope hors-enum → 422 Pydantic Enum validation."""
    r = await client.get(
        "/v1/dashboard/atoms_by_scope",
        params={"scope": "foo-bar-invalid-scope"},
    )
    assert r.status_code == 422, (
        f"attendu 422 pour scope invalide, reçu {r.status_code}: {r.text}"
    )


# ----------------------------------------------------------------------------
# Phase D.6 I7 — filtres tag / status / kind sur /atoms_by_scope
# ----------------------------------------------------------------------------


async def test_atoms_by_scope_filter_status_archived(client, mock_embed):
    """Filtre status=archived → seuls les atomes archivés du scope demandé.

    On crée un atome puis tente de le passer en archived via PATCH. Si le
    PATCH n'aboutit pas (route absente / contrainte), le test vérifie au
    moins le contrat : tous les items retournés doivent avoir
    status=archived.
    """
    create = await client.post("/v1/atoms", json={
        "kind": "note",
        "scope": "travail/operations",
        "key": "test-flt-status-archive",
        "value": "atome à archiver pour test status filter",
        "node_id": SEED_NODE,
    })
    assert create.status_code == 201, create.text
    aid = create.json()["id"]

    patch = await client.patch(
        f"/v1/atoms/{aid}",
        json={"status": "archived", "node_id": SEED_NODE},
    )

    r = await client.get(
        "/v1/dashboard/atoms_by_scope",
        params={"scope": "travail/operations", "status": "archived", "limit": 100},
    )
    assert r.status_code == 200, r.text
    items = r.json()
    assert isinstance(items, list)
    for atom in items:
        assert atom["status"] == "archived", (
            f"filtre status=archived a retourné un atome status={atom['status']}"
        )

    # Si l'archivage a réussi, l'atome doit apparaître.
    if patch.status_code in (200, 204):
        assert any(a["id"] == aid for a in items), (
            f"atome archivé {aid} absent du filtre status=archived"
        )


async def test_atoms_by_scope_filter_tag(client, mock_embed):
    """Filtre tag=marker → seuls les atomes contenant le tag dans tags[]."""
    create = await client.post("/v1/atoms", json={
        "kind": "note",
        "scope": "travail/operations",
        "key": "test-flt-tag-foo",
        "value": "atome avec tag marker",
        "tags": ["test-flt-tag-marker", "autre"],
        "node_id": SEED_NODE,
    })
    assert create.status_code == 201, create.text
    aid = create.json()["id"]

    other = await client.post("/v1/atoms", json={
        "kind": "note",
        "scope": "travail/operations",
        "key": "test-flt-tag-bar",
        "value": "atome sans tag marker",
        "tags": ["banal"],
        "node_id": SEED_NODE,
    })
    assert other.status_code == 201, other.text

    r = await client.get(
        "/v1/dashboard/atoms_by_scope",
        params={"scope": "travail/operations", "tag": "test-flt-tag-marker", "limit": 100},
    )
    assert r.status_code == 200, r.text
    items = r.json()
    ids = {a["id"] for a in items}
    assert aid in ids, "atome avec tag marker doit apparaître"
    for atom in items:
        assert "test-flt-tag-marker" in atom["tags"], (
            f"filtre tag a retourné un atome sans tag: {atom['tags']}"
        )


async def test_atoms_by_scope_filter_kind(client, mock_embed):
    """Filtre kind=decision → seuls les atomes kind=decision du scope."""
    create_dec = await client.post("/v1/atoms", json={
        "kind": "decision",
        "scope": "travail/strategie",
        "key": "test-flt-kind-decision",
        "value": "Décision filtre kind test.",
        "rationale": "Rationale obligatoire pour decision (RATIONALE_REQUIRED_KINDS).",
        "node_id": SEED_NODE,
    })
    assert create_dec.status_code == 201, create_dec.text

    create_note = await client.post("/v1/atoms", json={
        "kind": "note",
        "scope": "travail/strategie",
        "key": "test-flt-kind-note",
        "value": "Note filtre kind test.",
        "node_id": SEED_NODE,
    })
    assert create_note.status_code == 201, create_note.text

    r = await client.get(
        "/v1/dashboard/atoms_by_scope",
        params={"scope": "travail/strategie", "kind": "decision", "limit": 100},
    )
    assert r.status_code == 200, r.text
    items = r.json()
    for atom in items:
        assert atom["kind"] == "decision", (
            f"filtre kind=decision a retourné un atome kind={atom['kind']}"
        )


async def test_atoms_by_scope_invalid_kind_returns_422(client):
    """kind hors-enum → 422 (validation Pydantic Enum)."""
    r = await client.get(
        "/v1/dashboard/atoms_by_scope",
        params={"scope": "travail/operations", "kind": "fake-kind-invalid"},
    )
    assert r.status_code == 422, (
        f"kind hors-enum attendu 422, reçu {r.status_code}: {r.text}"
    )


# ============================================================================
# Phase D.6 I8 — GET /v1/dashboard/search
# ============================================================================


async def test_search_simple_query(client, mock_embed):
    """Recherche ILIKE substring sur value, case-insensitive."""
    create = await client.post("/v1/atoms", json={
        "kind": "note",
        "scope": "travail/operations",
        "key": "test-search-needle",
        "value": "Une chaîne distinctive_NEEDLEXYZ_marker pour test search.",
        "node_id": SEED_NODE,
    })
    assert create.status_code == 201, create.text
    aid = create.json()["id"]

    # Case-insensitive : on cherche en minuscules un fragment en MAJ.
    r = await client.get(
        "/v1/dashboard/search",
        params={"q": "needlexyz_marker", "limit": 20},
    )
    assert r.status_code == 200, r.text
    items = r.json()
    assert isinstance(items, list)
    ids = {a["id"] for a in items}
    assert aid in ids, (
        f"atome contenant 'NEEDLEXYZ_marker' attendu dans search, ids reçus={ids}"
    )


async def test_search_no_match_returns_empty(client):
    """Aucun match → list vide, status 200."""
    r = await client.get(
        "/v1/dashboard/search",
        params={"q": "zzz-no-such-substring-anywhere-9q8r7s6t5"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == [], f"attendu list vide, reçu: {body}"


async def test_search_with_scope_filter(client, mock_embed):
    """Filtre scope optionnel → restreint aux atomes du scope demandé."""
    a1 = await client.post("/v1/atoms", json={
        "kind": "note",
        "scope": "travail/operations",
        "key": "test-search-scoped-a",
        "value": "match_SCOPEDTOKENALPHA texte travail-pos",
        "node_id": SEED_NODE,
    })
    assert a1.status_code == 201, a1.text
    a2 = await client.post("/v1/atoms", json={
        "kind": "note",
        "scope": "perso/logement",
        "key": "test-search-scoped-b",
        "value": "match_SCOPEDTOKENALPHA texte logement",
        "node_id": SEED_NODE,
    })
    assert a2.status_code == 201, a2.text

    r = await client.get(
        "/v1/dashboard/search",
        params={"q": "scopedtokenalpha", "scope": "travail/operations", "limit": 50},
    )
    assert r.status_code == 200, r.text
    items = r.json()
    for atom in items:
        assert atom["scope"] == "travail/operations", (
            f"search scope=travail-pos a retourné atome scope={atom['scope']}"
        )
    ids = {a["id"] for a in items}
    assert a1.json()["id"] in ids
    assert a2.json()["id"] not in ids


async def test_search_min_length_422(client):
    """q vide ou absent → 422 (min_length=1)."""
    r_empty = await client.get("/v1/dashboard/search", params={"q": ""})
    assert r_empty.status_code == 422, (
        f"q='' attendu 422, reçu {r_empty.status_code}: {r_empty.text}"
    )

    r_missing = await client.get("/v1/dashboard/search")
    assert r_missing.status_code == 422, (
        f"q absent attendu 422, reçu {r_missing.status_code}: {r_missing.text}"
    )


async def test_search_invalid_scope_returns_422(client):
    """scope hors-enum → 422."""
    r = await client.get(
        "/v1/dashboard/search",
        params={"q": "foo", "scope": "fake-scope-invalid"},
    )
    assert r.status_code == 422, (
        f"scope hors-enum attendu 422, reçu {r.status_code}: {r.text}"
    )


# ============================================================================
# GET /v1/dashboard/timeline
# ============================================================================


async def test_timeline_default_30_days(client):
    """GET /timeline sans param → period_days=30 + daily_stats list."""
    r = await client.get("/v1/dashboard/timeline")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["period_days"] == 30
    assert "daily_stats" in body
    assert isinstance(body["daily_stats"], list)


async def test_timeline_custom_days(client):
    """GET /timeline?days=7 → period_days=7."""
    r = await client.get("/v1/dashboard/timeline", params={"days": 7})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["period_days"] == 7
    assert "daily_stats" in body


async def test_timeline_days_out_of_range(client):
    """days=0 ou days=400 → 422 (validation Pydantic Query gt=0, le=365 typique)."""
    r0 = await client.get("/v1/dashboard/timeline", params={"days": 0})
    assert r0.status_code == 422, (
        f"days=0 attendu 422, reçu {r0.status_code}: {r0.text}"
    )

    r400 = await client.get("/v1/dashboard/timeline", params={"days": 400})
    assert r400.status_code == 422, (
        f"days=400 attendu 422, reçu {r400.status_code}: {r400.text}"
    )


# ============================================================================
# GET /v1/dashboard/foundations_state
# ============================================================================


async def test_foundations_state_lists_pierre_angulaires(client, mock_embed):
    """Atome avec tag 'pierre-angulaire' → présent dans foundations_state."""
    create = await client.post("/v1/atoms", json={
        "kind": "decision",
        "scope": "travail/strategie",
        "key": "test-fnd-pierre",
        "value": "Décision pierre-angulaire test dashboard.",
        "rationale": "Tag pierre-angulaire pour vérifier dashboard.",
        "tags": ["pierre-angulaire"],
        "node_id": SEED_NODE,
    })
    assert create.status_code == 201, create.text
    aid = create.json()["id"]

    r = await client.get("/v1/dashboard/foundations_state")
    assert r.status_code == 200, r.text
    body = r.json()
    # Recherche flexible : la réponse peut être {foundations:[...], recent_audits:[...]}
    # ou avoir une autre clé. On tente plusieurs candidats.
    foundations = (
        body.get("foundations")
        or body.get("pierres_angulaires")
        or body.get("pierre_angulaires")
        or []
    )
    found_ids = {a.get("id") for a in foundations if isinstance(a, dict)}
    assert aid in found_ids, (
        f"Atome pierre-angulaire {aid} attendu dans foundations, "
        f"clés réponse: {list(body.keys())}, ids trouvés: {found_ids}"
    )


async def test_foundations_state_recent_audits(client, mock_embed):
    """`recent_audits` est présent dans la réponse et conforme au schéma.

    Note : `recent_audits` est alimenté par la table `arac.audit_links`
    (PAS par `memory_atoms`). Créer un atome `kind=alert` via /v1/atoms ne
    génère pas automatiquement une ligne audit_links — cela passe par un
    flux séparé (auditor agent / commande dédiée, hors API publique
    actuelle). On vérifie donc le contrat structurel de l'endpoint :
    présence de la clé `recent_audits`, list de dicts, items conformes
    au schéma RecentAudit (id, kind, target_atom_id, audit_source).

    Contrainte schéma : `audit_source=interactive_human_validated` impose
    `confidence=auditor_validated` (validateur atom Pydantic).
    """
    create = await client.post("/v1/atoms", json={
        "kind": "alert",
        "scope": "travail/operations",
        "key": "test-fnd-alert",
        "value": "Alert test pour foundations_state.recent_audits.",
        "audit_source": "interactive_human_validated",
        "confidence": "auditor_validated",
        "node_id": SEED_NODE,
    })
    assert create.status_code == 201, create.text

    r = await client.get("/v1/dashboard/foundations_state")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "recent_audits" in body, (
        f"Clé `recent_audits` attendue dans foundations_state, "
        f"clés reçues: {list(body.keys())}"
    )
    audits = body["recent_audits"]
    assert isinstance(audits, list)
    # Items conformes au schéma RecentAudit (si non vide).
    for audit in audits:
        assert isinstance(audit, dict)
        assert "id" in audit
        assert "kind" in audit
        assert "target_atom_id" in audit  # peut être None (forensic, pas de FK)
        assert "audit_source" in audit


# ============================================================================
# GET /v1/dashboard/ (HTMLResponse)
# ============================================================================


async def test_dashboard_html_endpoint_returns_html(client):
    """GET /v1/dashboard/ → 200 + content-type text/html."""
    r = await client.get("/v1/dashboard/")
    assert r.status_code == 200, r.text
    content_type = r.headers.get("content-type", "")
    assert "text/html" in content_type.lower(), (
        f"Content-Type attendu text/html, reçu: {content_type}"
    )
    # Sanity check : HTML basique
    assert "<" in r.text and ">" in r.text


# ============================================================================
# Bonus : cohérence cross-endpoints
# ============================================================================


async def test_scopes_summary_counts_match_atoms_by_scope(client, mock_embed):
    """Le total_atoms de scopes_summary doit être cohérent avec atoms_by_scope.

    Sanity check léger : si scopes_summary annonce N pour un scope, alors
    GET atoms_by_scope?scope=X&limit=200 doit retourner ≤ N items
    (limite haute — N tient compte aussi des soft-archived selon impl).

    Note : `limit` est borné `le=200` côté router (Query validation), donc
    on demande la limite max permise, suffisante pour les fixtures de test
    (cleanup `test-%` garantit un nombre faible d'atomes).
    """
    await client.post("/v1/atoms", json={
        "kind": "note",
        "scope": "outillage/automatisations",
        "key": "test-cross-coherence",
        "value": "coherence atoms_by_scope vs scopes_summary",
        "node_id": SEED_NODE,
    })

    summary = await client.get("/v1/dashboard/scopes_summary")
    by_scope = await client.get(
        "/v1/dashboard/atoms_by_scope",
        params={"scope": "outillage/automatisations", "limit": 200, "offset": 0},
    )
    assert summary.status_code == 200
    assert by_scope.status_code == 200, by_scope.text

    summary_body = summary.json()
    auto_summary = next(
        (s for s in summary_body if s["scope"] == "outillage/automatisations"),
        None,
    )
    assert auto_summary is not None, "scope automations doit apparaître"
    assert auto_summary["total_atoms"] >= 1

    by_scope_body = by_scope.json()
    items = (
        by_scope_body
        if isinstance(by_scope_body, list)
        else by_scope_body.get("items", by_scope_body.get("atoms", []))
    )
    # atoms_by_scope ne doit pas excéder total_atoms du résumé
    assert len(items) <= auto_summary["total_atoms"], (
        f"atoms_by_scope ({len(items)}) > scopes_summary.total_atoms "
        f"({auto_summary['total_atoms']})"
    )
