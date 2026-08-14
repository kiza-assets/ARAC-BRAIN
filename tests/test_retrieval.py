"""Tests d'intégration retrieval Phase 4 — 6 tests obligatoires PLAN_V2.

Couvre :
- foundations() retourne uniquement les atomes pierre-angulaire actifs
- context_for() merge anti-double (un atome thématique aussi pierre-angulaire compte 1×)
- context_for() saturation_warning
- lineage() WITH RECURSIVE bidirectionnel
- Garde supersede tag pierre-angulaire — 409 sans acknowledge (Option A)
- Garde supersede tag pierre-angulaire — succès avec acknowledge_drop_pierre_angulaire=True

Stratégie :
- Tous les tests utilisent `mock_embed` (économie API + latence).
- Les atomes test-* sont nettoyés en pre/post fixture (cf conftest.py).
- Les 8 pierres-angulaires « réelles » de la BDD persistent — les tests
  qui les comptent (foundations sans tag test-*) en tiennent compte.
"""

from __future__ import annotations

import os
from collections import Counter

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL_ADMIN"),
    reason="DB reelle requise",
)

# Node seedé Phase 1b.6, FK valide pour les INSERT tests
SEED_NODE = "test-node"
PA_TAG = "pierre-angulaire"


# ============================================================================
# Test 1 — foundations() retourne uniquement les pierres-angulaires actives
# ============================================================================


async def test_foundations_returns_only_pierre_angulaire(client, mock_embed):
    """Crée un atome `test-pa` taggé pierre-angulaire + un atome `test-not-pa`
    sans tag. Vérifie que :
      - le set retourné contient le test-pa
      - tous les atomes retournés portent le tag pierre-angulaire
      - tous les atomes retournés sont status='active'
      - le test-not-pa n'est pas inclus
      - tri ordinal : decisions d'abord, puis patterns, etc. (KIND_ORDER)
    """
    # Crée un atome pierre-angulaire test
    create_pa = await client.post("/v1/atoms", json={
        "kind": "pattern",
        "scope": "outillage/assistants",
        "key": "test-pa-foundations",
        "value": "Test pierre-angulaire pour foundations",
        "tags": [PA_TAG, "test-marker"],
        "node_id": SEED_NODE,
    })
    assert create_pa.status_code == 201, create_pa.text
    pa_id = create_pa.json()["id"]

    # Crée un atome SANS le tag pierre-angulaire (ne doit pas remonter)
    create_not_pa = await client.post("/v1/atoms", json={
        "kind": "note",
        "scope": "outillage/assistants",
        "key": "test-not-pa-foundations",
        "value": "Test note pas pierre-angulaire",
        "tags": ["test-marker"],
        "node_id": SEED_NODE,
    })
    assert create_not_pa.status_code == 201, create_not_pa.text
    not_pa_id = create_not_pa.json()["id"]

    # GET /v1/atoms/foundations
    r = await client.get("/v1/atoms/foundations")
    assert r.status_code == 200, r.text
    atoms = r.json()
    assert isinstance(atoms, list)

    ids = {a["id"] for a in atoms}
    assert pa_id in ids, "atome test-pa-foundations doit être présent"
    assert not_pa_id not in ids, "atome non pierre-angulaire ne doit pas être présent"

    # Invariants des atomes pierre-angulaire : tag + status='active'
    for a in atoms:
        assert PA_TAG in a["tags"], f"atome {a['key']} sans tag {PA_TAG}"
        assert a["status"] == "active", f"atome {a['key']} status={a['status']}"

    # Tri ordinal : KIND_ORDER place decision (0) avant pattern (1) avant
    # gotcha (2) etc. Vérifie que les ordinaux des kinds sont monotones.
    from app.schemas.kind import KIND_ORDER, Kind
    kind_rank = {k.value: i for i, k in enumerate(KIND_ORDER)}
    ranks = [kind_rank[a["kind"]] for a in atoms]
    assert ranks == sorted(ranks), \
        f"foundations() doit être triée par KIND_ORDER, got {ranks}"


# ============================================================================
# Test 2 — context_for merge anti-double
# ============================================================================


async def test_context_for_merge_anti_double(client, mock_embed):
    """Crée un atome `kind=decision` taggé pierre-angulaire. Appelle
    context_for(topic). L'atome doit apparaître EXACTEMENT UNE FOIS,
    et uniquement dans son bucket `decision` via le canal foundation
    (donc avec distance=None, pas comme atome thématique).
    """
    # Crée un atome qui est À LA FOIS pierre-angulaire et sémantiquement
    # proche de notre topic — il sera dans les deux SQL (A et B) côté serveur.
    create = await client.post("/v1/atoms", json={
        "kind": "decision",
        "scope": "outillage/assistants",
        "key": "test-context-anti-double",
        "value": "Décision pierre-angulaire qui matche aussi le topic",
        "rationale": "Atome dual pour test anti-double",
        "tags": [PA_TAG],
        "node_id": SEED_NODE,
    })
    assert create.status_code == 201, create.text
    atom_id = create.json()["id"]

    r = await client.post("/v1/atoms/context_for", json={
        "topic": "test décision contexte anti double",
        "k": 10,
    })
    assert r.status_code == 200, r.text
    bundle = r.json()

    # Compte les occurrences de l'atome dans tous les buckets
    occurrences = []
    for bucket_name, bucket_atoms in bundle["buckets"].items():
        for a in bucket_atoms:
            if a["id"] == atom_id:
                occurrences.append((bucket_name, a["distance"]))

    assert len(occurrences) == 1, (
        f"atome dual doit apparaître exactement 1× dans les buckets, "
        f"got {len(occurrences)}: {occurrences}"
    )
    bucket_name, distance = occurrences[0]
    assert bucket_name == "decision", \
        f"atome decision doit aller dans bucket 'decision', got '{bucket_name}'"
    assert distance is None, (
        f"atome injecté via canal foundation doit avoir distance=None "
        f"(sélectionné par filtre tag, pas par cosine), got {distance}"
    )

    # Vérification additionnelle : l'atome est bien dans foundation_ids
    assert atom_id in bundle["foundation_ids"], \
        "atome pierre-angulaire doit apparaître dans foundation_ids"


# ============================================================================
# Test 3 — context_for saturation_warning
# ============================================================================


async def test_context_for_saturation_warning(client, mock_embed):
    """Crée 12 atomes kind=pattern taggés pierre-angulaire. Appelle
    context_for(topic, k=10). Le bucket 'pattern' contient les 12
    foundations en premier, puis tout atome thématique pattern est
    refusé (cap k=10 dépassé) → saturation_warning rempli.

    Le PLAN_V2 spécifie 20 atomes, mais le test fonctionnel demande
    juste un bucket saturé par les foundations au-delà de k. 12 suffit
    et reste rapide (insertions séquentielles via TestClient).
    """
    # Crée 12 atomes pierre-angulaire kind=pattern (clé unique chacun)
    foundation_ids = []
    for i in range(12):
        r = await client.post("/v1/atoms", json={
            "kind": "pattern",
            "scope": "outillage/assistants",
            "key": f"test-saturation-pa-{i:02d}",
            "value": f"Pierre-angulaire pattern numéro {i} pour test saturation",
            "tags": [PA_TAG],
            "node_id": SEED_NODE,
        })
        assert r.status_code == 201, r.text
        foundation_ids.append(r.json()["id"])

    # Crée un atome thématique kind=pattern SANS le tag pierre-angulaire,
    # qui devrait normalement être ajouté au bucket pattern mais sera
    # refusé car le bucket est saturé par les 12 foundations (> cap k=10).
    r_thematic = await client.post("/v1/atoms", json={
        "kind": "pattern",
        "scope": "outillage/assistants",
        "key": "test-saturation-thematic",
        "value": "Pattern thématique non pierre-angulaire qui devrait être refusé",
        "tags": ["test-marker"],
        "node_id": SEED_NODE,
    })
    assert r_thematic.status_code == 201, r_thematic.text
    thematic_id = r_thematic.json()["id"]

    # Appel context_for avec k=10
    r = await client.post("/v1/atoms/context_for", json={
        "topic": "test saturation pattern",
        "k": 10,
    })
    assert r.status_code == 200, r.text
    bundle = r.json()

    # Le bucket pattern doit contenir AU MOINS les 12 foundations
    # (ils sont injectés avant le cap, le cap s'applique aux thématiques)
    pattern_bucket = bundle["buckets"]["pattern"]
    pa_in_bucket = [a for a in pattern_bucket if PA_TAG in a["tags"]]
    assert len(pa_in_bucket) >= 12, (
        f"12 pierres-angulaires pattern doivent être injectées avant cap, "
        f"got {len(pa_in_bucket)}"
    )

    # L'atome thématique NE doit PAS être dans le bucket pattern
    # (cap dépassé par les foundations → refusé)
    thematic_in_bucket = [a for a in pattern_bucket if a["id"] == thematic_id]
    assert thematic_in_bucket == [], (
        "atome thématique pattern doit être refusé du bucket saturé"
    )

    # saturation_warning doit être rempli avec un message qui mentionne
    # le bucket pattern et le key de l'atome refusé.
    assert len(bundle["saturation_warning"]) >= 1, (
        f"saturation_warning doit être rempli, "
        f"got {bundle['saturation_warning']}"
    )
    warnings_str = " ".join(bundle["saturation_warning"])
    assert "pattern" in warnings_str, \
        f"warning doit mentionner le bucket pattern, got: {warnings_str}"
    assert "test-saturation-thematic" in warnings_str, (
        f"warning doit mentionner la key de l'atome refusé, got: {warnings_str}"
    )


# ============================================================================
# Test 4 — lineage WITH RECURSIVE bidirectionnel
# ============================================================================


async def test_lineage_with_recursive_returns_ancestors_and_descendants(
    client, mock_embed
):
    """Crée une chaîne v1 → v2 → v3 via supersede répétés. Appelle
    lineage(v2) et vérifie :
      - chain length = 3
      - depth=-1 : v1 (ancestor)
      - depth= 0 : v2 (self)
      - depth=+1 : v3 (descendant)
      - branch matche le depth
    """
    # Créer v1
    r_v1 = await client.post("/v1/atoms", json={
        "kind": "note",
        "scope": "outillage/assistants",
        "key": "test-lineage-chain",
        "value": "Version 1 de la chaîne",
        "node_id": SEED_NODE,
    })
    assert r_v1.status_code == 201, r_v1.text
    v1_id = r_v1.json()["id"]

    # Supersede v1 → v2
    r_v2 = await client.post(f"/v1/atoms/{v1_id}/supersede", json={
        "new_value": "Version 2 de la chaîne",
        "new_node_id": SEED_NODE,
    })
    assert r_v2.status_code == 201, r_v2.text
    v2_id = r_v2.json()["id"]

    # Supersede v2 → v3
    r_v3 = await client.post(f"/v1/atoms/{v2_id}/supersede", json={
        "new_value": "Version 3 de la chaîne",
        "new_node_id": SEED_NODE,
    })
    assert r_v3.status_code == 201, r_v3.text
    v3_id = r_v3.json()["id"]

    # GET lineage de v2 (le milieu de la chaîne)
    r = await client.get(f"/v1/atoms/{v2_id}/lineage")
    assert r.status_code == 200, r.text
    lineage_data = r.json()
    assert lineage_data["atom_id"] == v2_id

    chain = lineage_data["chain"]
    assert len(chain) == 3, f"chain length attendue 3, got {len(chain)}"

    # Trie par depth (déjà trié par le SQL, mais sécurité)
    chain_by_depth = {node["depth"]: node for node in chain}
    assert set(chain_by_depth.keys()) == {-1, 0, 1}, (
        f"depths attendus {{-1, 0, 1}}, got {set(chain_by_depth.keys())}"
    )

    # depth=-1 : v1 (ancestor)
    ancestor = chain_by_depth[-1]
    assert ancestor["id"] == v1_id
    assert ancestor["branch"] == "ancestor"
    assert ancestor["status"] == "superseded"
    assert ancestor["version"] == 1

    # depth=0 : v2 (self)
    self_node = chain_by_depth[0]
    assert self_node["id"] == v2_id
    assert self_node["branch"] == "self"
    assert self_node["status"] == "superseded"  # v2 a été superseded par v3
    assert self_node["version"] == 2

    # depth=+1 : v3 (descendant)
    descendant = chain_by_depth[1]
    assert descendant["id"] == v3_id
    assert descendant["branch"] == "descendant"
    assert descendant["status"] == "active"
    assert descendant["version"] == 3


# ============================================================================
# Test 5 — Garde supersede pierre-angulaire sans acknowledge → 409 (Option A)
# ============================================================================


async def test_supersede_pierre_angulaire_without_tag_returns_409(
    client, mock_embed
):
    """Crée un atome taggé pierre-angulaire. Tente de le superseder avec
    new_tags=['autre-tag-sans-pa'] sans acknowledge_drop_pierre_angulaire.
    Doit retourner 409 avec un message explicite.
    """
    # Crée un atome pierre-angulaire
    create = await client.post("/v1/atoms", json={
        "kind": "decision",
        "scope": "outillage/assistants",
        "key": "test-garde-pa-sans-ack",
        "value": "Decision pierre-angulaire test garde",
        "rationale": "Test garde supersede pierre-angulaire sans acknowledge",
        "tags": [PA_TAG],
        "node_id": SEED_NODE,
    })
    assert create.status_code == 201, create.text
    pa_id = create.json()["id"]

    # Tentative de supersede qui drop le tag pierre-angulaire SANS acknowledge
    r = await client.post(f"/v1/atoms/{pa_id}/supersede", json={
        "new_value": "Decision modifiee sans le tag pa",
        "new_tags": ["autre-tag"],
        "new_node_id": SEED_NODE,
    })
    assert r.status_code == 409, (
        f"supersede doit retourner 409 quand new_tags drop {PA_TAG} sans acknowledge, "
        f"got {r.status_code}: {r.text}"
    )
    body = r.json()
    # Phase 4.5 : `detail` est désormais un dict structuré avec un Warning
    # W-004 critical (règle héritée de la doctrine anti-dérive)
    # §3.2). On vérifie le code/severity du warning + la mention du tag dans
    # le message d'erreur.
    detail = body["detail"]
    assert isinstance(detail, dict), (
        f"Phase 4.5 : detail doit être dict structuré, got {type(detail)}"
    )
    assert PA_TAG in detail["message"], (
        f"message d'erreur doit mentionner {PA_TAG}, got: {detail['message']}"
    )
    assert "acknowledge_drop_pierre_angulaire" in detail["message"], (
        f"message d'erreur doit indiquer le flag d'acquittement, got: {detail['message']}"
    )
    # Warning W-004 critical présent dans le body
    assert "warnings" in detail
    assert any(w["code"] == "W-004" for w in detail["warnings"]), (
        f"warning W-004 doit être présent, got: {detail['warnings']}"
    )

    # Verification additionnelle : l'atome n'a PAS été modifié (rejet pré-embed)
    check = await client.get(f"/v1/atoms/{pa_id}")
    assert check.status_code == 200
    assert check.json()["status"] == "active", \
        "atome rejeté doit rester actif (transaction non démarrée)"
    assert check.json()["version"] == 1, \
        "atome rejeté doit garder version=1"


# ============================================================================
# Test 6 — Garde supersede pierre-angulaire avec acknowledge → succès
# ============================================================================


async def test_supersede_pierre_angulaire_with_acknowledge_drop_succeeds(
    client, mock_embed
):
    """Même scénario que test 5, mais avec acknowledge_drop_pierre_angulaire=True.
    Doit réussir (201). L'atome v2 ne porte pas le tag pierre-angulaire.
    """
    create = await client.post("/v1/atoms", json={
        "kind": "decision",
        "scope": "outillage/assistants",
        "key": "test-garde-pa-avec-ack",
        "value": "Decision pierre-angulaire test garde acknowledge",
        "rationale": "Test garde supersede avec acknowledge",
        "tags": [PA_TAG],
        "node_id": SEED_NODE,
    })
    assert create.status_code == 201, create.text
    pa_id = create.json()["id"]

    # Supersede avec acknowledge → autorisé
    r = await client.post(f"/v1/atoms/{pa_id}/supersede", json={
        "new_value": "Decision modifiee avec acknowledge",
        "new_tags": ["autre-tag"],
        "new_node_id": SEED_NODE,
        "acknowledge_drop_pierre_angulaire": True,
    })
    assert r.status_code == 201, (
        f"supersede avec acknowledge doit réussir, got {r.status_code}: {r.text}"
    )
    new_atom = r.json()
    assert new_atom["status"] == "active"
    assert new_atom["version"] == 2
    assert PA_TAG not in new_atom["tags"], \
        f"new atom ne doit pas porter {PA_TAG}, got tags={new_atom['tags']}"

    # Vérifie que l'ancien est bien superseded
    old = await client.get(f"/v1/atoms/{pa_id}")
    assert old.status_code == 200
    assert old.json()["status"] == "superseded"
    assert PA_TAG in old.json()["tags"], "ancien atome garde le tag historique"
