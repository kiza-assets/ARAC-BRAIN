"""Tests hermétiques du DISPOSANT cortex — fakes API scriptées, zéro réseau/DB.

Couvre les dispositions terminales (§3-4 du design) et la sémantique de
reprise : created / 409→confirmed / 409→superseded / 409→kept / policy_skip /
dédup sémantique / supersede_key_hint / API down mid-dispose (conversations
déjà committées acquises, curseur de l'in-flight gelé).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agents.cortex import dispose  # noqa: E402
from agents.cortex.atoms_client import AtomsApiDown  # noqa: E402

SCOPES = frozenset({"outillage", "outillage/infrastructure", "travail/operations"})


class FakeApi:
    """API atoms scriptée. `posts` = liste de réponses (status, body) consommées
    dans l'ordre ; `by_key` = dict (scope,key) -> incumbent ; enregistre tout."""

    AtomsApiDown = AtomsApiDown

    def __init__(self, *, posts=None, by_key=None, recall_hits=None,
                 supersede_status=201):
        self.posts = list(posts or [])
        self.by_key = dict(by_key or {})
        self.recall_hits = list(recall_hits or [])
        self.supersede_status = supersede_status
        self.calls = {"post": [], "supersede": [], "confirm": [], "recall": []}

    def post_atom(self, payload):
        self.calls["post"].append(payload)
        if not self.posts:
            return 201, {"id": "new"}
        item = self.posts.pop(0)
        if item == "DOWN":
            raise AtomsApiDown("api down")
        return item

    def get_by_key(self, scope, key):
        return self.by_key.get((scope, key))

    def supersede(self, incumbent_id, **kw):
        self.calls["supersede"].append((incumbent_id, kw))
        return self.supersede_status, {"id": "v2"}

    def confirm_unchanged(self, incumbent):
        self.calls["confirm"].append(incumbent["id"])
        return 200, incumbent

    def recall(self, query, *, scope=None, k=3, consumer=None):
        self.calls["recall"].append(query)
        return self.recall_hits


class FakeCursorLib:
    """Miroir hermétique de `curator_lib_v2` : `retry_count` par conversation
    est incrémenté par `mark_curation_failed` et REMIS À 0 par `advance_cursor`
    (même sémantique que le SQL réel) — permet de tester les 3 omissions
    CONSÉCUTIVES sur plusieurs appels successifs de `dispose_document`."""

    def __init__(self):
        self.advances = []
        self.mark_failed_calls = []
        self.parked = []
        self._retry_counts: dict[str, int] = {}

    async def advance_cursor(self, db, conv_id, new_cursor, *, atoms_generated):
        self.advances.append((conv_id, new_cursor, atoms_generated))
        self._retry_counts[conv_id] = 0

    async def mark_curation_failed(self, db, conv_id, *, error):
        self.mark_failed_calls.append((conv_id, error))
        self._retry_counts[conv_id] = self._retry_counts.get(conv_id, 0) + 1
        return self._retry_counts[conv_id]

    async def park_conversation(self, db, conv_id, *, error):
        self.parked.append((conv_id, error))


class FakeDb:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


def _atom(**over):
    base = {"kind": "gotcha", "scope": "outillage/infrastructure", "key": "test-cle",
            "value": "Un fait durable suffisamment long pour être crédible.",
            "rationale": None, "confidence_score": 90, "tags": [],
            "supersede_key_hint": None, "message_ids": [11, 12]}
    base.update(over)
    return base


def _doc(atoms, uid="conv-1"):
    return {"contract_version": "cortex-dispose/1", "run_ref": "slot",
            "complete": True, "audit_summary": "t",
            "conversations": [{"conversation_uid": uid, "atoms": atoms, "skips": []}]}


PRESENTED = {"conv-1": {"conversation_id": "c1-id", "max_id": 12,
                        "message_ids": {11, 12}, "source_type": "claude_code"}}


@pytest.fixture()
def cursor_lib(monkeypatch):
    fake = FakeCursorLib()
    monkeypatch.setattr(dispose, "curator_lib_v2", fake)
    return fake


class FakeReviewQueue:
    """Miroir hermétique de `agents.cortex.review_queue` —
    capture chaque appel `insert_review_row` sans jamais toucher une vraie DB."""

    def __init__(self):
        self.calls: list[dict] = []

    async def insert_review_row(self, conn, run_ref, conversation_uid, drop_reason,
                                proposed_atom, incumbent_atom_id, scope, kind):
        self.calls.append({
            "run_ref": run_ref, "conversation_uid": conversation_uid,
            "drop_reason": drop_reason, "proposed_atom": proposed_atom,
            "incumbent_atom_id": incumbent_atom_id, "scope": scope, "kind": kind,
        })


@pytest.fixture()
def review_queue(monkeypatch):
    fake = FakeReviewQueue()
    monkeypatch.setattr(dispose, "review_queue", fake)
    return fake


async def _run(doc, api, cursor_lib, presented=PRESENTED):
    db = FakeDb()
    totals, progress = await dispose.dispose_document(
        db, doc, presented, run_ref="slot", node_id="arac-curator",
        valid_scopes=SCOPES, api=api)
    return totals, progress, db


async def test_created_advances_cursor_to_presented_max(cursor_lib):
    api = FakeApi(posts=[(201, {"id": "a1"})])
    totals, progress, db = await _run(_doc([_atom()]), api, cursor_lib)
    assert totals["atoms_created"] == 1
    assert cursor_lib.advances == [("c1-id", 12, 1)]
    assert db.commits == 1
    assert progress["conv-1"]["dispositions"][0]["disposition"] == "created"


async def test_409_identical_value_confirms_without_new_version(cursor_lib):
    incumbent = {"id": "inc-1", "kind": "gotcha", "key": "test-cle",
                 "value": "  UN fait DURABLE   suffisamment long pour être crédible. ",
                 "confidence_score": 80, "source_ref": {}}
    api = FakeApi(posts=[(409, None)],
                  by_key={("outillage/infrastructure", "test-cle"): incumbent})
    totals, _, _ = await _run(_doc([_atom()]), api, cursor_lib)
    assert totals["conflicts_409"] == 1
    assert totals["atoms_confirmed"] == 1
    assert api.calls["confirm"] == ["inc-1"]
    assert not api.calls["supersede"], "valeur identique ne supersède JAMAIS"


async def test_409_different_value_higher_confidence_supersedes(cursor_lib):
    incumbent = {"id": "inc-2", "kind": "gotcha", "key": "test-cle",
                 "value": "Ancienne compréhension du fait.",
                 "confidence_score": 85, "source_ref": {}}
    api = FakeApi(posts=[(409, None)],
                  by_key={("outillage/infrastructure", "test-cle"): incumbent})
    totals, _, _ = await _run(_doc([_atom(confidence_score=90)]), api, cursor_lib)
    assert totals["atoms_superseded"] == 1
    (inc_id, kw), = api.calls["supersede"]
    assert inc_id == "inc-2"
    assert "new_tags" not in kw, "héritage des tags = pierre-angulaire préservée"


async def test_409_lower_confidence_keeps_incumbent_with_audited_counter(cursor_lib):
    incumbent = {"id": "inc-3", "kind": "gotcha", "key": "test-cle",
                 "value": "Version sûre existante.", "confidence_score": 95,
                 "source_ref": {}}
    api = FakeApi(posts=[(409, None)],
                  by_key={("outillage/infrastructure", "test-cle"): incumbent})
    totals, progress, _ = await _run(_doc([_atom(confidence_score=85)]), api, cursor_lib)
    assert totals["atoms_kept_lower_confidence"] == 1
    assert not api.calls["supersede"]
    assert progress["conv-1"]["dispositions"][0]["disposition"] == "kept"


async def test_409_kind_mismatch_quarantines_atom(cursor_lib):
    incumbent = {"id": "inc-4", "kind": "decision", "key": "test-cle",
                 "value": "x", "confidence_score": 90, "source_ref": {}}
    api = FakeApi(posts=[(409, None)],
                  by_key={("outillage/infrastructure", "test-cle"): incumbent})
    totals, _, _ = await _run(_doc([_atom()]), api, cursor_lib)
    assert totals["atoms_quarantined"] == 1


async def test_policy_skip_never_posts(cursor_lib):
    api = FakeApi()
    totals, _, _ = await _run(
        _doc([_atom(kind="agent_message")]), api, cursor_lib)
    assert totals["atoms_policy_skips"] == 1
    assert not api.calls["post"]
    # La conversation avance quand même (rien de durable à écrire = disposé).
    assert cursor_lib.advances == [("c1-id", 12, 0)]


async def test_semantic_dup_resolves_against_other_key(cursor_lib):
    incumbent = {"id": "inc-5", "kind": "gotcha", "key": "autre-cle",
                 "value": "Un fait durable suffisamment long pour être crédible.",
                 "confidence_score": 80, "source_ref": {}}
    api = FakeApi(
        recall_hits=[{"kind": "gotcha", "key": "autre-cle", "scope": "outillage/infrastructure",
                      "distance": 0.03}],
        by_key={("outillage/infrastructure", "autre-cle"): incumbent})
    totals, _, _ = await _run(_doc([_atom()]), api, cursor_lib)
    assert totals["atoms_confirmed"] == 1
    assert not api.calls["post"], "quasi-doublon -> résolution, jamais un POST"


async def test_supersede_key_hint_routes_to_incumbent(cursor_lib):
    incumbent = {"id": "inc-6", "kind": "gotcha", "key": "cle-connue",
                 "value": "Ancien état du fait connu.", "confidence_score": 80,
                 "source_ref": {}}
    api = FakeApi(by_key={("outillage/infrastructure", "cle-connue"): incumbent})
    totals, _, _ = await _run(
        _doc([_atom(supersede_key_hint="cle-connue")]), api, cursor_lib)
    assert totals["atoms_superseded"] == 1
    assert not api.calls["post"]


async def test_api_down_mid_dispose_freezes_inflight_keeps_committed(cursor_lib):
    """2 conversations : la 1re aboutit (committée), l'API tombe sur la 2e ->
    AtomsApiDown remonte, curseur de la 2e JAMAIS avancé."""
    presented = {
        "conv-1": {"conversation_id": "c1-id", "max_id": 12,
                   "message_ids": {11, 12}, "source_type": "claude_code"},
        "conv-2": {"conversation_id": "c2-id", "max_id": 30,
                   "message_ids": {30}, "source_type": "claude_code"},
    }
    doc = {"contract_version": "cortex-dispose/1", "run_ref": "slot",
           "complete": True, "audit_summary": "t",
           "conversations": [
               {"conversation_uid": "conv-1", "atoms": [_atom()], "skips": []},
               {"conversation_uid": "conv-2",
                "atoms": [_atom(key="autre", message_ids=[30])], "skips": []},
           ]}
    api = FakeApi(posts=[(201, {"id": "a"}), "DOWN"])
    db = FakeDb()
    with pytest.raises(AtomsApiDown):
        await dispose.dispose_document(
            db, doc, presented, run_ref="slot", node_id="arac-curator",
            valid_scopes=SCOPES, api=api)
    assert cursor_lib.advances == [("c1-id", 12, 1)], \
        "conv-1 acquise, conv-2 gelée"


async def test_omitted_conversation_cursor_frozen(cursor_lib):
    """Conversation présentée mais ABSENTE du doc -> curseur gelé, PAS traitée
    comme un atome, mais COMPTÉE (coverage_omitted)."""
    presented = dict(PRESENTED)
    presented["conv-oubliee"] = {"conversation_id": "c9", "max_id": 99,
                                 "message_ids": {99}, "source_type": "claude_code"}
    api = FakeApi(posts=[(201, {"id": "a"})])
    totals, progress = await dispose.dispose_document(
        FakeDb(), _doc([_atom()]), presented, run_ref="slot",
        node_id="arac-curator", valid_scopes=SCOPES, api=api)
    assert [a[0] for a in cursor_lib.advances] == ["c1-id"], "curseur JAMAIS avancé pour l'omise"
    assert progress["conv-oubliee"]["coverage"] == "omitted"
    assert progress["conv-oubliee"]["cursor"] is None
    assert cursor_lib.mark_failed_calls == [("c9", "cortex_omission:absent_from_doc")]
    assert totals["coverage_presented"] == 2
    assert totals["coverage_covered"] == 1
    assert totals["coverage_omitted"] == 1
    assert totals["coverage_no_new_knowledge"] == 0


# ============================================================================
# Oracle de couverture : atoms=[] nu / no_new_knowledge / park
# ============================================================================


async def test_atoms_vide_nu_omission_curseur_gele(cursor_lib):
    """`"atoms": []` sans attestation -> OMISSION : curseur figé, comptée."""
    doc = _doc([], uid="conv-1")
    api = FakeApi()
    totals, progress = await dispose.dispose_document(
        FakeDb(), doc, PRESENTED, run_ref="slot",
        node_id="arac-curator", valid_scopes=SCOPES, api=api)
    assert not cursor_lib.advances, "curseur JAMAIS avancé sur omission nue"
    assert progress["conv-1"]["coverage"] == "omitted"
    assert progress["conv-1"]["cursor"] is None
    assert not progress["conv-1"].get("parked")
    assert totals["coverage_presented"] == 1
    assert totals["coverage_omitted"] == 1
    assert totals["coverage_covered"] == 0
    assert totals["coverage_no_new_knowledge"] == 0


async def test_no_new_knowledge_attestation_avance_le_curseur(cursor_lib):
    """`no_new_knowledge=true` : décision terminale motivée -> avance quand
    même (rien à écrire), comptée séparément de `covered`."""
    doc = {"contract_version": "cortex-dispose/1", "run_ref": "slot",
           "complete": True, "audit_summary": "t",
           "conversations": [{"conversation_uid": "conv-1", "atoms": [],
                              "no_new_knowledge": True, "skips": []}]}
    api = FakeApi()
    totals, progress = await dispose.dispose_document(
        FakeDb(), doc, PRESENTED, run_ref="slot",
        node_id="arac-curator", valid_scopes=SCOPES, api=api)
    assert cursor_lib.advances == [("c1-id", 12, 0)]
    assert progress["conv-1"]["coverage"] == "no_new_knowledge"
    assert totals["coverage_no_new_knowledge"] == 1
    assert totals["coverage_omitted"] == 0
    assert not cursor_lib.mark_failed_calls


async def test_trois_omissions_consecutives_parque_et_alerte(cursor_lib):
    """3 omissions CONSÉCUTIVES de la même conversation -> PARK :
    `park_conversation` appelé, `progress[...]["parked"]` True — le caller
    (cycle.py) alerte sur ce signal. Les 2 premières omissions NE parquent PAS."""
    doc = _doc([], uid="conv-1")
    api = FakeApi()
    for expected_retry in (1, 2):
        _, progress = await dispose.dispose_document(
            FakeDb(), doc, PRESENTED, run_ref="slot",
            node_id="arac-curator", valid_scopes=SCOPES, api=api)
        assert progress["conv-1"]["retry_count"] == expected_retry
        assert not progress["conv-1"].get("parked")
        assert not cursor_lib.parked

    _, progress = await dispose.dispose_document(
        FakeDb(), doc, PRESENTED, run_ref="slot",
        node_id="arac-curator", valid_scopes=SCOPES, api=api)
    assert progress["conv-1"]["retry_count"] == 3
    assert progress["conv-1"]["parked"] is True
    assert cursor_lib.parked == [("c1-id", "cortex_omission_park:3_consecutive")]


async def test_omission_puis_succes_reinitialise_le_compteur(cursor_lib):
    """Un succès (`no_new_knowledge` ou `atoms` non-vide) entre-temps remet le
    compteur de reprises à 0 -> les omissions ne s'accumulent QUE si
    consécutives (mêmes garanties que le `retry_count` SQL réel)."""
    api = FakeApi(posts=[(201, {"id": "a"})])
    empty_doc = _doc([], uid="conv-1")
    await dispose.dispose_document(
        FakeDb(), empty_doc, PRESENTED, run_ref="slot",
        node_id="arac-curator", valid_scopes=SCOPES, api=api)
    assert cursor_lib._retry_counts["c1-id"] == 1

    # succès entre deux -> reset.
    await dispose.dispose_document(
        FakeDb(), _doc([_atom()]), PRESENTED, run_ref="slot",
        node_id="arac-curator", valid_scopes=SCOPES, api=api)
    assert cursor_lib._retry_counts["c1-id"] == 0

    _, progress = await dispose.dispose_document(
        FakeDb(), empty_doc, PRESENTED, run_ref="slot",
        node_id="arac-curator", valid_scopes=SCOPES, api=api)
    assert progress["conv-1"]["retry_count"] == 1, "repart de 1, pas de 2"
    assert not cursor_lib.parked


async def test_arithmetique_couverture_exacte_mix(cursor_lib):
    """Invariant presented == covered + no_new_knowledge + omitted sur un
    pack mixte (3 conversations, 3 issues différentes)."""
    presented = {
        "conv-1": {"conversation_id": "c1-id", "max_id": 12,
                   "message_ids": {11, 12}, "source_type": "claude_code"},
        "conv-nnk": {"conversation_id": "c-nnk", "max_id": 20,
                    "message_ids": {20}, "source_type": "claude_code"},
        "conv-omit": {"conversation_id": "c-omit", "max_id": 30,
                     "message_ids": {30}, "source_type": "claude_code"},
    }
    doc = {"contract_version": "cortex-dispose/1", "run_ref": "slot",
           "complete": True, "audit_summary": "t",
           "conversations": [
               {"conversation_uid": "conv-1", "atoms": [_atom()], "skips": []},
               {"conversation_uid": "conv-nnk", "atoms": [],
                "no_new_knowledge": True, "skips": []},
               {"conversation_uid": "conv-omit", "atoms": [], "skips": []},
           ]}
    api = FakeApi(posts=[(201, {"id": "a"})])
    totals, _ = await dispose.dispose_document(
        FakeDb(), doc, presented, run_ref="slot",
        node_id="arac-curator", valid_scopes=SCOPES, api=api)
    assert totals["coverage_presented"] == 3
    assert (totals["coverage_covered"] + totals["coverage_no_new_knowledge"]
            + totals["coverage_omitted"]) == totals["coverage_presented"]
    assert totals["coverage_covered"] == 1
    assert totals["coverage_no_new_knowledge"] == 1
    assert totals["coverage_omitted"] == 1


# ============================================================================
# Revue humaine : chaque drop alimente arac.digestion_review_queue
# ============================================================================


async def test_created_and_confirmed_never_feed_the_review_queue(cursor_lib, review_queue):
    """Les dispositions qui ABOUTISSENT à une mémoire durable (created,
    confirmed) ne sont PAS des drops -> aucune row de revue."""
    api = FakeApi(posts=[(201, {"id": "a1"})])
    await _run(_doc([_atom()]), api, cursor_lib)
    incumbent = {"id": "inc-1", "kind": "gotcha", "key": "test-cle",
                 "value": "  UN fait DURABLE   suffisamment long pour être crédible. ",
                 "confidence_score": 80, "source_ref": {}}
    api2 = FakeApi(posts=[(409, None)], by_key={("outillage/infrastructure", "test-cle"): incumbent})
    await _run(_doc([_atom()]), api2, cursor_lib)
    assert review_queue.calls == []


async def test_kept_lower_confidence_feeds_review_queue_with_incumbent_id(cursor_lib, review_queue):
    incumbent = {"id": "inc-3", "kind": "gotcha", "key": "test-cle",
                 "value": "Version sûre existante.", "confidence_score": 95,
                 "source_ref": {}}
    api = FakeApi(posts=[(409, None)],
                  by_key={("outillage/infrastructure", "test-cle"): incumbent})
    await _run(_doc([_atom(confidence_score=85)]), api, cursor_lib)
    assert len(review_queue.calls) == 1
    call = review_queue.calls[0]
    assert call["drop_reason"] == "kept_lower_confidence"
    assert call["incumbent_atom_id"] == "inc-3"
    assert call["run_ref"] == "slot" and call["conversation_uid"] == "conv-1"
    assert (call["scope"], call["kind"]) == ("outillage/infrastructure", "gotcha")
    assert call["proposed_atom"]["key"] == "test-cle", "le candidat COMPLET (payload), pas l'atome brut"


async def test_kind_mismatch_quarantine_feeds_review_queue(cursor_lib, review_queue):
    incumbent = {"id": "inc-4", "kind": "decision", "key": "test-cle",
                 "value": "x", "confidence_score": 90, "source_ref": {}}
    api = FakeApi(posts=[(409, None)],
                  by_key={("outillage/infrastructure", "test-cle"): incumbent})
    await _run(_doc([_atom()]), api, cursor_lib)
    assert len(review_queue.calls) == 1
    call = review_queue.calls[0]
    assert call["drop_reason"] == "atom_quarantine"
    assert call["incumbent_atom_id"] == "inc-4"


async def test_supersede_unresolved_quarantine_feeds_review_queue(cursor_lib, review_queue):
    """Supersede répondant un 4xx inattendu (jamais 200/201/409) -> quarantaine
    non résolue -> review row, incumbent conservé (dernier connu)."""
    incumbent = {"id": "inc-9", "kind": "gotcha", "key": "test-cle",
                 "value": "Ancienne compréhension du fait.", "confidence_score": 85,
                 "source_ref": {}}
    api = FakeApi(posts=[(409, None)],
                  by_key={("outillage/infrastructure", "test-cle"): incumbent},
                  supersede_status=422)
    await _run(_doc([_atom(confidence_score=90)]), api, cursor_lib)
    assert len(review_queue.calls) == 1
    call = review_queue.calls[0]
    assert call["drop_reason"] == "atom_quarantine"
    assert call["incumbent_atom_id"] == "inc-9"


async def test_409_without_incumbent_final_quarantine_feeds_review_queue(cursor_lib, review_queue):
    """409 sans incumbent actif -> un seul re-POST ; si celui-ci échoue aussi
    -> quarantaine SANS incumbent connu (`incumbent_atom_id` None)."""
    api = FakeApi(posts=[(409, None), (409, None)])
    await _run(_doc([_atom()]), api, cursor_lib)
    assert len(review_queue.calls) == 1
    call = review_queue.calls[0]
    assert call["drop_reason"] == "atom_quarantine"
    assert call["incumbent_atom_id"] is None


async def test_api_contract_drift_422_feeds_review_queue(cursor_lib, review_queue):
    """422 imprévu (dérive de contrat malgré policy_check) -> quarantaine,
    review row sans incumbent."""
    api = FakeApi(posts=[(422, {"detail": "invalid payload"})])
    await _run(_doc([_atom()]), api, cursor_lib)
    assert len(review_queue.calls) == 1
    call = review_queue.calls[0]
    assert call["drop_reason"] == "atom_quarantine"
    assert call["incumbent_atom_id"] is None


async def test_policy_skip_feeds_review_queue_with_raw_atom(cursor_lib, review_queue):
    """policy_skip : le candidat n'a jamais été `finalize_atom` -> le
    `proposed_atom` de la review-queue est l'atome BRUT du LLM (pas de payload
    POST construit), scope/kind repris tels quels."""
    api = FakeApi()
    await _run(_doc([_atom(kind="agent_message")]), api, cursor_lib)
    assert len(review_queue.calls) == 1
    call = review_queue.calls[0]
    assert call["drop_reason"] == "policy_skip"
    assert call["incumbent_atom_id"] is None
    assert call["proposed_atom"]["kind"] == "agent_message"
    assert call["scope"] == "outillage/infrastructure"


async def test_coverage_omitted_feeds_review_queue_with_metadata_only(cursor_lib, review_queue):
    """Omission nue : `proposed_atom` n'est PAS un candidat d'atome (jamais
    présenté à la digestion) mais un petit dict motif+retry_count."""
    doc = _doc([], uid="conv-1")
    api = FakeApi()
    await dispose.dispose_document(
        FakeDb(), doc, PRESENTED, run_ref="slot",
        node_id="arac-curator", valid_scopes=SCOPES, api=api)
    assert len(review_queue.calls) == 1
    call = review_queue.calls[0]
    assert call["drop_reason"] == "coverage_omitted"
    assert call["proposed_atom"] == {"reason": "cortex_omission:atoms_empty", "retry_count": 1}
    assert (call["scope"], call["kind"]) == ("_systeme", "coverage_omitted")


async def test_review_queue_write_failure_never_crashes_dispose(cursor_lib):
    """BREAK : la review-queue best-effort est déjà exercée
    par les tests ci-dessus SANS monkeypatch de `review_queue` (le `FakeDb`
    n'a pas de `.cursor()` -> `insert_review_row` avale l'AttributeError en
    interne). Ce test le rend EXPLICITE : le dispose complet réussit malgré
    l'absence totale de connexion DB compatible review-queue."""
    api = FakeApi(posts=[(201, {"id": "a1"})])
    totals, progress, db = await _run(_doc([_atom()]), api, cursor_lib)
    assert totals["atoms_created"] == 1
    assert db.commits == 1


# ============================================================================
# Routage du seuil + log d'armement B `dispose.semantic_dup`
# ============================================================================

import hashlib as _hashlib
import json as _json
import logging as _logging

from agents.cortex import dedup_thresholds as _dt  # noqa: E402


def _sha8(key: str) -> str:
    """Oracle indépendant du helper testé (jamais key_sha8 lui-même)."""
    return _hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


def _dispose_logs(caplog, event):
    out = []
    for rec in caplog.records:
        if rec.name != "arac.cortex.dispose":
            continue
        try:
            payload = _json.loads(rec.getMessage())
        except ValueError:
            continue
        if payload.get("event") == event:
            out.append(payload)
    return out


def _semantic_dup_logs(caplog):
    return _dispose_logs(caplog, "dispose.semantic_dup")


def _all_dispose_msgs(caplog) -> str:
    return " ".join(r.getMessage() for r in caplog.records
                    if r.name == "arac.cortex.dispose")


async def test_semantic_distance_max_routes_v1_bit_identical():
    """Le seuil servi est ROUTÉ par dedup_thresholds mais reste BIT-IDENTIQUE
    au 0.08 historique (livraison inerte) — le carve-out cérémonie ne
    s'applique QU'À l'espace fold, jamais au chemin v1 servi."""
    assert dispose.SEMANTIC_DISTANCE_MAX == 0.08
    assert dispose.SEMANTIC_DISTANCE_MAX == _dt.get_threshold("v1")


async def test_semantic_fire_same_decision_and_arming_log(cursor_lib, caplog):
    """Scénario de tir : MÊME décision qu'avant (résolution -> confirmed,
    jamais un POST) + log d'armement B structuré émis avec les champs."""
    incumbent = {"id": "inc-5", "kind": "gotcha", "key": "autre-cle",
                 "value": "Un fait durable suffisamment long pour être crédible.",
                 "confidence_score": 80, "source_ref": {}}
    api = FakeApi(
        recall_hits=[{"kind": "gotcha", "key": "autre-cle", "scope": "outillage/infrastructure",
                      "distance": 0.03}],
        by_key={("outillage/infrastructure", "autre-cle"): incumbent})
    with caplog.at_level(_logging.INFO, logger="arac.cortex.dispose"):
        totals, _, _ = await _run(_doc([_atom()]), api, cursor_lib)
    # décision INCHANGÉE (même assertion que le test historique) :
    assert totals["atoms_confirmed"] == 1
    assert not api.calls["post"], "quasi-doublon -> résolution, jamais un POST"
    # log d'armement B : un tir = UNE ligne, champs complets, clés en SHA8
    # UNIQUEMENT (I5/V0.107 : une clé-slug peut porter une PII — jamais en
    # clair). Empreintes attendues recalculées INDÉPENDAMMENT (hashlib).
    logs = _semantic_dup_logs(caplog)
    assert len(logs) == 1
    log = logs[0]
    assert log["space"] == "v1"
    assert log["distance"] == 0.03
    assert log["key_candidate_sha8"] == _sha8("test-cle")
    assert log["key_incumbent_sha8"] == _sha8("autre-cle")
    assert "test-cle" not in _json.dumps(log)   # jamais la clé en clair
    assert "autre-cle" not in _json.dumps(log)
    assert log["ceremony_candidate"] is False
    assert log["ceremony_incumbent"] is False
    assert log["action"] == "confirmed"


async def test_semantic_dup_log_never_emits_pii_key_in_clear(cursor_lib, caplog):
    """Non-régression I5/V0.107 (finding round 1) : le corpus réel contient
    des clés-slugs à PRÉNOM (11 clés actives vérifiées arac_test/arac_bench,
    ex. `alice-prefers-…`) — un tir du backstop sur une telle clé ne
    doit JAMAIS écrire le prénom dans le log d'armement B, seulement sha8."""
    pii_key = "alice-prefers-temporal-comparative-views"
    incumbent = {"id": "inc-9", "kind": "gotcha", "key": pii_key,
                 "value": "Un fait durable suffisamment long pour être crédible.",
                 "confidence_score": 80, "source_ref": {}}
    api = FakeApi(
        recall_hits=[{"kind": "gotcha", "key": pii_key, "scope": "outillage/infrastructure",
                      "distance": 0.03}],
        by_key={("outillage/infrastructure", pii_key): incumbent})
    with caplog.at_level(_logging.INFO, logger="arac.cortex.dispose"):
        await _run(_doc([_atom()]), api, cursor_lib)
    log, = _semantic_dup_logs(caplog)
    assert log["key_incumbent_sha8"] == _sha8(pii_key)
    dispose_msgs = _all_dispose_msgs(caplog)
    assert "alice" not in dispose_msgs.lower()
    assert pii_key not in dispose_msgs


# ----------------------------------------------------------------------------
# Non-régression I5/V0.107 (finding round 2) : les branches QUARANTAINE de
# `_resolve_against` et le fallthrough POST loggent aussi — sur le MÊME chemin
# de tir que le backstop — et ne doivent JAMAIS écrire la clé-slug en clair
# (le corpus réel contient des clés à prénom), ni rejouer le corps 422
# pydantic-v2 dont `detail[i].input` écho la valeur soumise (texte de
# conversation potentiel). Scénarios A'/B'/C de la repro confirmée.
# ----------------------------------------------------------------------------

PII_KEY = "alice-prefers-temporal-comparative-views-v2"


async def test_identity_kind_mismatch_log_never_emits_pii_key_in_clear(cursor_lib, caplog):
    """Scénario A' : candidat à clé-prénom, tir du backstop, l'incumbent
    re-fetché a un kind DIVERGENT -> le MÊME tir émet `semantic_dup` (sha8)
    PUIS `identity_kind_mismatch` : ce second log doit lui aussi être en
    sha8 UNIQUEMENT, jamais la clé candidate en clair."""
    incumbent = {"id": "inc-km", "kind": "decision", "key": "autre-cle",
                 "value": "x", "confidence_score": 90, "source_ref": {}}
    api = FakeApi(
        recall_hits=[{"kind": "gotcha", "key": "autre-cle", "scope": "outillage/infrastructure",
                      "distance": 0.03}],
        by_key={("outillage/infrastructure", "autre-cle"): incumbent})
    with caplog.at_level(_logging.INFO, logger="arac.cortex.dispose"):
        totals, _, _ = await _run(_doc([_atom(key=PII_KEY)]), api, cursor_lib)
    assert totals["atoms_quarantined"] == 1
    log, = _dispose_logs(caplog, "dispose.identity_kind_mismatch")
    assert log["key_sha8"] == _sha8(PII_KEY)
    assert "key" not in log, "plus aucun champ clé-en-clair dans ce log"
    dispose_msgs = _all_dispose_msgs(caplog)
    assert "alice" not in dispose_msgs.lower()
    assert PII_KEY not in dispose_msgs


async def test_supersede_unresolved_log_never_emits_pii_key_in_clear(cursor_lib, caplog):
    """Scénario B' : candidat à clé-prénom, tir du backstop, supersede répond
    un 4xx inattendu -> `supersede_unresolved` en sha8 UNIQUEMENT."""
    incumbent = {"id": "inc-su", "kind": "gotcha", "key": "autre-cle",
                 "value": "Ancienne compréhension du fait.",
                 "confidence_score": 60, "source_ref": {}}
    api = FakeApi(
        recall_hits=[{"kind": "gotcha", "key": "autre-cle", "scope": "outillage/infrastructure",
                      "distance": 0.03}],
        by_key={("outillage/infrastructure", "autre-cle"): incumbent},
        supersede_status=422)
    with caplog.at_level(_logging.INFO, logger="arac.cortex.dispose"):
        totals, _, _ = await _run(
            _doc([_atom(key=PII_KEY, confidence_score=90)]), api, cursor_lib)
    assert totals["atoms_quarantined"] == 1
    log, = _dispose_logs(caplog, "dispose.supersede_unresolved")
    assert log["key_sha8"] == _sha8(PII_KEY)
    dispose_msgs = _all_dispose_msgs(caplog)
    assert "alice" not in dispose_msgs.lower()
    assert PII_KEY not in dispose_msgs


async def test_api_contract_drift_log_sanitized_no_key_no_body_echo(cursor_lib, caplog):
    """Scénario C : POST -> 422 avec un corps pydantic-v2 PAR DÉFAUT dont
    `detail[i].input` écho la valeur soumise -> le log `api_contract_drift`
    porte la clé en sha8 et un detail RÉDUIT à type+loc — ni la clé, ni la
    valeur, ni le prénom ne sortent en clair dans journald."""
    echoed_value = "TEXTE DE CONVERSATION PRIVEE mentionnant alice en clair."
    body_422 = {"detail": [{
        "type": "string_too_long",
        "loc": ["body", "value"],
        "msg": "String should have at most 10 characters",
        "input": echoed_value,
    }]}
    api = FakeApi(posts=[(422, body_422)])
    with caplog.at_level(_logging.INFO, logger="arac.cortex.dispose"):
        totals, _, _ = await _run(
            _doc([_atom(key=PII_KEY, value=echoed_value)]), api, cursor_lib)
    assert totals["atoms_quarantined"] == 1
    log, = _dispose_logs(caplog, "dispose.api_contract_drift")
    assert log["status"] == 422
    assert log["key_sha8"] == _sha8(PII_KEY)
    assert log["detail"] == [{"type": "string_too_long", "loc": ["body", "value"]}]
    dispose_msgs = _all_dispose_msgs(caplog)
    assert "alice" not in dispose_msgs.lower()
    assert PII_KEY not in dispose_msgs
    assert "TEXTE DE CONVERSATION" not in dispose_msgs


async def test_api_contract_drift_non_pydantic_body_reduced_to_shape(cursor_lib, caplog):
    """Corps d'erreur NON pydantic (str, None, dict applicatif) : fail-toward-
    silence — jamais d'écho du contenu, seulement la forme (`body_type`)."""
    api = FakeApi(posts=[(400, f"clé {PII_KEY} rejetée")])
    with caplog.at_level(_logging.INFO, logger="arac.cortex.dispose"):
        totals, _, _ = await _run(_doc([_atom(key=PII_KEY)]), api, cursor_lib)
    assert totals["atoms_quarantined"] == 1
    log, = _dispose_logs(caplog, "dispose.api_contract_drift")
    assert log["detail"] == {"body_type": "str"}
    dispose_msgs = _all_dispose_msgs(caplog)
    assert "alice" not in dispose_msgs.lower()


async def test_ceremony_keys_still_fire_on_v1_but_are_flagged(cursor_lib, caplog):
    """Sur le chemin v1 SERVI, une clé cérémonie TIRE toujours (aucun
    carve-out actif aujourd'hui — observabilité pure, zéro changement de
    décision) ; le log la FLAGGE pour le monitoring d'armement (soak)."""
    incumbent = {"id": "inc-c", "kind": "gotcha", "key": "mission-d1-11ea5e33",
                 "value": "Un fait durable suffisamment long pour être crédible.",
                 "confidence_score": 80, "source_ref": {}}
    api = FakeApi(
        recall_hits=[{"kind": "gotcha", "key": "mission-d1-11ea5e33",
                      "scope": "outillage/infrastructure", "distance": 0.05}],
        by_key={("outillage/infrastructure", "mission-d1-11ea5e33"): incumbent})
    with caplog.at_level(_logging.INFO, logger="arac.cortex.dispose"):
        totals, _, _ = await _run(
            _doc([_atom(key="mission-d1-05ba6993")]), api, cursor_lib)
    assert totals["atoms_confirmed"] == 1, \
        "v1 servi : la résolution a bien lieu, carve-out INACTIF"
    assert not api.calls["post"]
    log, = _semantic_dup_logs(caplog)
    assert log["ceremony_candidate"] is True
    assert log["ceremony_incumbent"] is True
    assert log["action"] == "confirmed"


async def test_no_fire_above_threshold_no_arming_log(cursor_lib, caplog):
    """distance > seuil -> pas de tir, pas de log semantic_dup, POST normal
    (le log d'armement ne trace QUE les tirs, jamais les non-tirs)."""
    api = FakeApi(
        posts=[(201, {"id": "a1"})],
        recall_hits=[{"kind": "gotcha", "key": "autre-cle", "scope": "outillage/infrastructure",
                      "distance": 0.09}])
    with caplog.at_level(_logging.INFO, logger="arac.cortex.dispose"):
        totals, _, _ = await _run(_doc([_atom()]), api, cursor_lib)
    assert totals["atoms_created"] == 1
    assert _semantic_dup_logs(caplog) == []


async def test_fire_interrupted_by_api_down_still_logs_action_interrupted(cursor_lib, caplog):
    """AtomsApiDown PENDANT la résolution d'un tir : le log d'armement est
    quand même émis (try/finally), action='interrupted' — un tir n'est
    JAMAIS silencieux, même interrompu."""
    class DownOnSupersede(FakeApi):
        def supersede(self, incumbent_id, **kw):
            raise AtomsApiDown("api down")

    incumbent = {"id": "inc-7", "kind": "gotcha", "key": "autre-cle",
                 "value": "Ancienne compréhension du fait.",
                 "confidence_score": 60, "source_ref": {}}
    api = DownOnSupersede(
        recall_hits=[{"kind": "gotcha", "key": "autre-cle", "scope": "outillage/infrastructure",
                      "distance": 0.02}],
        by_key={("outillage/infrastructure", "autre-cle"): incumbent})
    with caplog.at_level(_logging.INFO, logger="arac.cortex.dispose"):
        with pytest.raises(AtomsApiDown):
            await _run(_doc([_atom(confidence_score=90)]), api, cursor_lib)
    log, = _semantic_dup_logs(caplog)
    assert log["action"] == "interrupted"
    assert not cursor_lib.advances, "curseur gelé (reprise idempotente)"
