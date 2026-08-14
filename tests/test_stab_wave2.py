"""Tests hermétiques de la vague 2 (structure), zéro DB réelle.

Trois pas, chacun FLAG-GATÉ défaut OFF (armement au déploiement) :

  PAS 1  — pack.py : round-robin PAR SOURCE après le gate SQL inchangé
                  (`ARAC_PACK_SOURCE_FAIR`) + exclusion des messages VIDES du
                  rendu (`ARAC_PACK_DROP_EMPTY`, ids couverts par le curseur).
  PAS 2  — dispose.py : à la 3e omission, branche sur la COUVERTURE
                  (`ARAC_DISPOSE_COVERAGE_V2`) — tranche pleinement présentée
                  -> drain TRACÉ (curseur avancé + reçu d'exclusion motivée) ;
                  tranche tronquée -> backoff plafonné, JAMAIS park.
  PAS 3  — value_gate.py : scorer déterministe SHADOW LOG-ONLY (aucune
                  écriture) + prédicat `exclusion_category IS NULL` sur le
                  gate ET tous ses miroirs (watchdog/conservation/cockpit).

Propriété transverse vérifiée : FLAGS OFF = comportement identique à la
branche actuelle (mêmes packs, même park, mêmes compteurs).

Fakes : mêmes patterns que tests/test_cortex_pack.py (FakeCuratorLib,
count_fn=len) et tests/test_cortex_dispose.py (FakeCursorLib, FakeDb).
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import logging
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agents.cortex import dispose, value_gate  # noqa: E402
from agents.cortex import pack as pack_mod  # noqa: E402
from agents.lib import curator_lib_v2  # noqa: E402


# ===========================================================================
# Fakes (miroirs de test_cortex_pack / test_cortex_dispose)
# ===========================================================================


def _char_count(text: str) -> int:
    return len(text)


def _conv(conv_id, uid, *, cursor=0, source_type="claude_code", node_id="mac-1"):
    return {"id": conv_id, "conversation_uid": uid, "source_type": source_type,
            "node_id": node_id, "cursor": cursor}


def _msg(msg_id, content, *, role="user"):
    return {"id": msg_id, "message_uuid": f"u-{msg_id}", "role": role,
            "content": content, "msg_created_at": None}


class FakeCuratorLib:
    def __init__(self, conversations, messages_by_conv):
        self.conversations = conversations
        self.messages_by_conv = messages_by_conv

    async def select_eligible_conversations(self, db, *, limit):
        return self.conversations[:limit]

    async def fetch_uncurated_messages(self, db, conversation_id, cursor, *, limit=None):
        rows = [m for m in self.messages_by_conv.get(conversation_id, [])
                if m["id"] > cursor]
        return rows[:limit] if limit is not None else rows


@pytest.fixture()
def curator_lib(monkeypatch):
    fake = FakeCuratorLib([], {})
    monkeypatch.setattr(pack_mod, "curator_lib_v2", fake)

    async def _fake_known_atoms(db, uids):
        return "(aucun)"

    monkeypatch.setattr(pack_mod, "_known_atoms_block", _fake_known_atoms)
    return fake


async def _build(budget_tokens, **kw):
    return await pack_mod.build_pack(
        object(), budget_tokens=budget_tokens, count_fn=_char_count, **kw)


class FakeCursorLib:
    """Miroir hermétique de curator_lib_v2 + fix round-1 :
    `defer_conversation` (backoff plafonné 4), `mark_conversation_excluded`
    (reçu d'exclusion, first-writer-wins), `mark_full_omission` (compteur
    DÉDIÉ de présentations complètes — sémantique du marqueur réel : tout
    AUTRE writer de last_curation_error casse la série) et
    `get_atoms_generated` (garde dure du drain)."""

    def __init__(self):
        self.advances = []
        self.mark_failed_calls = []
        self.deferred_calls = []
        self.full_omission_calls = []
        self.excluded = []
        self.parked = []
        self._retry_counts: dict[str, int] = {}
        self._streaks: dict[str, int] = {}
        self._atoms: dict[str, int] = {}
        self._excluded_categories: dict[str, str] = {}

    async def advance_cursor(self, db, conv_id, new_cursor, *, atoms_generated):
        self.advances.append((conv_id, new_cursor, atoms_generated))
        self._retry_counts[conv_id] = 0
        # miroir du SQL réel : last_curation_error = NULL -> marqueur perdu.
        self._streaks[conv_id] = 0
        self._atoms[conv_id] = self._atoms.get(conv_id, 0) + atoms_generated

    async def mark_curation_failed(self, db, conv_id, *, error):
        self.mark_failed_calls.append((conv_id, error))
        self._retry_counts[conv_id] = self._retry_counts.get(conv_id, 0) + 1
        # miroir du SQL réel : écrase last_curation_error -> série cassée.
        self._streaks[conv_id] = 0
        return self._retry_counts[conv_id]

    async def defer_conversation(self, db, conv_id, *, error):
        self.deferred_calls.append((conv_id, error))
        self._retry_counts[conv_id] = min(self._retry_counts.get(conv_id, 0) + 1, 4)
        self._streaks[conv_id] = 0  # écrase le marqueur (SQL réel)
        return self._retry_counts[conv_id]

    async def mark_full_omission(self, db, conv_id, *, error):
        self.full_omission_calls.append((conv_id, error))
        self._retry_counts[conv_id] = min(self._retry_counts.get(conv_id, 0) + 1, 4)
        self._streaks[conv_id] = self._streaks.get(conv_id, 0) + 1
        return self._retry_counts[conv_id], self._streaks[conv_id]

    async def get_atoms_generated(self, db, conv_id):
        return self._atoms.get(conv_id, 0)

    async def mark_conversation_excluded(self, db, conv_id, *, category, reason, by):
        if conv_id in self._excluded_categories:
            return False  # first-writer-wins (SQL réel : WHERE ... IS NULL)
        self._excluded_categories[conv_id] = category
        self.excluded.append((conv_id, category, reason, by))
        return True

    async def park_conversation(self, db, conv_id, *, error):
        self.parked.append((conv_id, error))
        self._streaks[conv_id] = 0  # écrase le marqueur (SQL réel)


class FakeDb:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


class FakeApi:
    AtomsApiDown = dispose.default_api.AtomsApiDown

    def post_atom(self, payload):
        return 201, {"id": "new"}

    def get_by_key(self, scope, key):
        return None

    def recall(self, query, *, scope=None, k=3, consumer=None):
        return []


@pytest.fixture()
def cursor_lib(monkeypatch):
    fake = FakeCursorLib()
    monkeypatch.setattr(dispose, "curator_lib_v2", fake)

    async def _noop_review(*a, **k):
        return None

    monkeypatch.setattr(dispose.review_queue, "insert_review_row", _noop_review)
    return fake


SCOPES = frozenset({"outillage", "outillage/infrastructure"})


def _empty_doc(uid="conv-1"):
    return {"contract_version": "cortex-dispose/1", "run_ref": "slot",
            "complete": True, "audit_summary": "t",
            "conversations": [{"conversation_uid": uid, "atoms": [], "skips": []}]}


def _presented(*, fully_presented=None, max_id=12):
    meta = {"conversation_id": "c1-id", "max_id": max_id,
            "message_ids": {11, 12}, "source_type": "claude_code"}
    if fully_presented is not None:
        meta["fully_presented"] = fully_presented
    return {"conv-1": meta}


async def _dispose_once(presented, cursor_lib):
    return await dispose.dispose_document(
        FakeDb(), _empty_doc(), presented, run_ref="slot",
        node_id="arac-curator", valid_scopes=SCOPES, api=FakeApi())


# ===========================================================================
# PAS 1.a — round-robin par source (ARAC_PACK_SOURCE_FAIR)
# ===========================================================================


def test_interleave_by_source_pure_round_robin():
    """[A1,A2,A3,B1,C1] -> [A1,B1,C1,A2,A3] : 1 conv par source et par tour,
    ordre du gate CONSERVÉ intra-source (aging anti-famine intact), ordre des
    sources = première apparition dans l'ordre du gate."""
    a1 = _conv("a1", "ua1", node_id="serveur-ingest", source_type="claude_code")
    a2 = _conv("a2", "ua2", node_id="serveur-ingest", source_type="claude_code")
    a3 = _conv("a3", "ua3", node_id="serveur-ingest", source_type="claude_code")
    b1 = _conv("b1", "ub1", node_id="mac-1", source_type="claude_code")
    c1 = _conv("c1", "uc1", node_id="mac-1", source_type="desktop_chat")
    out = pack_mod._interleave_by_source([a1, a2, a3, b1, c1])
    assert [c["id"] for c in out] == ["a1", "b1", "c1", "a2", "a3"]


def test_interleave_keys_on_source_type_AND_node_id():
    """Même source_type mais nodes différents = DEUX sources (la famine
    est par node : serveur-ingest vs mac, tous deux claude_code)."""
    s1 = _conv("s1", "us1", node_id="serveur-ingest")
    s2 = _conv("s2", "us2", node_id="serveur-ingest")
    m1 = _conv("m1", "um1", node_id="mac-1")
    out = pack_mod._interleave_by_source([s1, s2, m1])
    assert [c["id"] for c in out] == ["s1", "m1", "s2"]


def test_interleave_single_source_is_identity():
    convs = [_conv(f"c{i}", f"u{i}") for i in range(5)]
    assert pack_mod._interleave_by_source(convs) == convs


def test_interleave_preserves_multiset():
    convs = ([_conv(f"a{i}", f"ua{i}", node_id="n-a") for i in range(4)]
             + [_conv(f"b{i}", f"ub{i}", node_id="n-b") for i in range(2)])
    out = pack_mod._interleave_by_source(convs)
    assert sorted(c["id"] for c in out) == sorted(c["id"] for c in convs)
    assert len(out) == len(convs)


async def test_source_fair_off_pack_order_is_gate_order(curator_lib, monkeypatch):
    """FLAG OFF (défaut) : l'ordre du pack est EXACTEMENT l'ordre du gate —
    bit-identique à la branche actuelle (head-of-line conservé)."""
    monkeypatch.delenv("ARAC_PACK_SOURCE_FAIR", raising=False)
    convs = [_conv("s1", "spawn-1", node_id="serveur-ingest"),
             _conv("s2", "spawn-2", node_id="serveur-ingest"),
             _conv("m1", "mac-1c", node_id="mac-1")]
    msgs = {cid: [_msg(1, f"contenu {cid}")] for cid in ("s1", "s2", "m1")}
    curator_lib.conversations, curator_lib.messages_by_conv = convs, msgs
    built = await _build(10_000)
    assert [p["uid"] for p in built["pack_meta"]] == ["spawn-1", "spawn-2", "mac-1c"]


async def test_source_fair_on_pack_alternates_sources(curator_lib, monkeypatch):
    """FLAG ON : la 2e place du pack revient à l'AUTRE source (mac dégelée dès
    le cycle suivant) — le gate SQL n'a pas bougé."""
    monkeypatch.setenv("ARAC_PACK_SOURCE_FAIR", "1")
    convs = [_conv("s1", "spawn-1", node_id="serveur-ingest"),
             _conv("s2", "spawn-2", node_id="serveur-ingest"),
             _conv("m1", "mac-1c", node_id="mac-1")]
    msgs = {cid: [_msg(1, f"contenu {cid}")] for cid in ("s1", "s2", "m1")}
    curator_lib.conversations, curator_lib.messages_by_conv = convs, msgs
    built = await _build(10_000)
    assert [p["uid"] for p in built["pack_meta"]] == ["spawn-1", "mac-1c", "spawn-2"]


async def test_source_fair_on_budget_starved_head_still_serves_second_source(
        curator_lib, monkeypatch):
    """FLAG ON + budget étroit : quand seules 2 conversations tiennent, la 2e
    est celle de l'autre source (plus jamais 100 % de la source dominante)."""
    monkeypatch.setenv("ARAC_PACK_SOURCE_FAIR", "1")
    convs = [_conv("s1", "spawn-1", node_id="serveur-ingest"),
             _conv("s2", "spawn-2", node_id="serveur-ingest"),
             _conv("m1", "mac-1c", node_id="mac-1")]
    body = "x" * 300
    msgs = {cid: [_msg(1, body)] for cid in ("s1", "s2", "m1")}
    curator_lib.conversations, curator_lib.messages_by_conv = convs, msgs
    header = len("## conversation spawn-1 (source=claude_code)")
    cost = len(f"[id=1] user: {body}")
    built = await _build((header + cost) * 2 + 10)
    uids = [p["uid"] for p in built["pack_meta"]]
    assert uids[:2] == ["spawn-1", "mac-1c"]


# ===========================================================================
# PAS 1.b — exclusion des messages vides du rendu (ARAC_PACK_DROP_EMPTY)
# ===========================================================================


async def test_drop_empty_off_empties_still_rendered(curator_lib, monkeypatch):
    """FLAG OFF (défaut) : les vides sont rendus avec leur préfixe [id=..] —
    bit-identique à la branche actuelle."""
    monkeypatch.delenv("ARAC_PACK_DROP_EMPTY", raising=False)
    curator_lib.conversations = [_conv("c1", "conv-1")]
    curator_lib.messages_by_conv = {"c1": [_msg(1, ""), _msg(2, "utile")]}
    built = await _build(10_000)
    assert "[id=1] user: " in built["conversations_block"]
    assert built["presented"]["conv-1"]["message_ids"] == {1, 2}


async def test_drop_empty_on_skips_render_but_covers_ids(curator_lib, monkeypatch):
    """FLAG ON : un vide (btrim='') n'est JAMAIS rendu (0 token de préfixe
    gaspillé) mais son id reste couvert -> le curseur passera la queue de
    vides (81 % du backlog, ~15 % de capacité pack récupérée)."""
    monkeypatch.setenv("ARAC_PACK_DROP_EMPTY", "1")
    curator_lib.conversations = [_conv("c1", "conv-1")]
    curator_lib.messages_by_conv = {
        "c1": [_msg(1, ""), _msg(2, "utile"), _msg(3, "   ")]}
    built = await _build(10_000)
    assert "[id=1]" not in built["conversations_block"]
    assert "[id=3]" not in built["conversations_block"]
    assert "[id=2] user: utile" in built["conversations_block"]
    assert built["presented"]["conv-1"]["max_id"] == 3, \
        "la queue de vides est couverte par le curseur"
    # Fix round-1 (finding 7) : seuls les ids RENDUS sont citables — un id
    # dropé (jamais montré au LLM) est un id étranger pour contract.py.
    assert built["presented"]["conv-1"]["message_ids"] == {2}
    assert built["pack_meta"][0]["n_msgs"] == 3


async def test_drop_empty_capacity_gain_more_content_fits(curator_lib, monkeypatch):
    """La capacité récupérée est réelle : avec le MÊME budget, une conversation
    frangée de vides tient en entier flag ON, pas flag OFF."""
    convs = [_conv("c1", "conv-1")]
    rows = [_msg(i, "") for i in range(1, 40)] + [_msg(40, "signal utile")]
    budget = len("## conversation conv-1 (source=claude_code)") \
        + len("[id=40] user: signal utile") + 5

    monkeypatch.setenv("ARAC_PACK_DROP_EMPTY", "1")
    curator_lib.conversations, curator_lib.messages_by_conv = convs, {"c1": rows}
    built_on = await _build(budget)
    assert built_on["presented"]["conv-1"]["max_id"] == 40

    monkeypatch.delenv("ARAC_PACK_DROP_EMPTY", raising=False)
    built_off = await _build(budget)
    covered_off = built_off["presented"].get("conv-1", {}).get("max_id", 0)
    assert covered_off < 40, "flag OFF, les préfixes des vides mangent le budget"


async def test_drop_empty_head_report_semantics_unchanged(curator_lib, monkeypatch):
    """FLAG ON : tête non-vide qui ne tient pas dans le restant mais tient
    dans le plein -> REPORT (conversation hors pack, aucune avance partielle
    sur les vides déjà vus, curseur inchangé)."""
    monkeypatch.setenv("ARAC_PACK_DROP_EMPTY", "1")
    uid, cid = "conv-r", "cR"
    content = "z" * 200
    header = len(f"## conversation {uid} (source=claude_code)")
    rendered = len(f"[id=2] user: {content}")
    curator_lib.conversations = [_conv(cid, uid)]
    curator_lib.messages_by_conv = {cid: [_msg(1, ""), _msg(2, content)]}
    built = await _build(header + rendered - 5)
    assert built["pack_meta"] == []
    assert uid not in built["presented"], "jamais d'avance partielle sur les vides"
    assert built["messages_reported"] == 1


# ===========================================================================
# PAS 1.c — threading `fully_presented` (matière du pas 2)
# ===========================================================================


async def test_fully_presented_true_when_whole_delta_in_pack(curator_lib):
    curator_lib.conversations = [_conv("c1", "conv-1")]
    curator_lib.messages_by_conv = {"c1": [_msg(1, "a"), _msg(2, "b")]}
    built = await _build(10_000)
    assert built["presented"]["conv-1"]["fully_presented"] is True


async def test_fully_presented_false_when_budget_truncates(curator_lib):
    curator_lib.conversations = [_conv("c1", "conv-1")]
    msg_a = _msg(1, "a" * 900)
    msg_b = _msg(2, "b" * 900)
    curator_lib.messages_by_conv = {"c1": [msg_a, msg_b]}
    built = await _build(1_000)
    assert built["presented"]["conv-1"]["max_id"] == 1
    assert built["presented"]["conv-1"]["fully_presented"] is False


async def test_fully_presented_true_with_trailing_empties_dropped(
        curator_lib, monkeypatch):
    """FLAG drop-empty ON : une queue de vides couverte compte comme
    pleinement présentée (rien de non-montré n'existe)."""
    monkeypatch.setenv("ARAC_PACK_DROP_EMPTY", "1")
    curator_lib.conversations = [_conv("c1", "conv-1")]
    curator_lib.messages_by_conv = {"c1": [_msg(1, "utile"), _msg(2, "")]}
    built = await _build(10_000)
    assert built["presented"]["conv-1"]["max_id"] == 2
    assert built["presented"]["conv-1"]["fully_presented"] is True


# ===========================================================================
# PAS 2 — couverture v2 des omissions (ARAC_DISPOSE_COVERAGE_V2)
# ===========================================================================


async def test_flag_off_third_omission_still_parks(cursor_lib, monkeypatch):
    """FLAG OFF (défaut) : bit-identique au comportement d'origine — 3e omission = PARK,
    même si la tranche était pleinement présentée."""
    monkeypatch.delenv("ARAC_DISPOSE_COVERAGE_V2", raising=False)
    presented = _presented(fully_presented=True)
    for _ in range(2):
        _, progress = await _dispose_once(presented, cursor_lib)
        assert not progress["conv-1"].get("parked")
    _, progress = await _dispose_once(presented, cursor_lib)
    assert progress["conv-1"]["parked"] is True
    assert cursor_lib.parked == [("c1-id", "cortex_omission_park:3_consecutive")]
    assert not cursor_lib.excluded and not cursor_lib.deferred_calls
    assert not cursor_lib.advances


async def test_flag_on_fully_presented_third_omission_drains_traced(
        cursor_lib, monkeypatch):
    """FLAG ON + tranche PLEINEMENT présentée 3× sans atome : curseur avancé
    au max PRÉSENTÉ + reçu d'exclusion motivée (catégorie de la taxonomie
    0023, motif mécanique low_yield_omission, composant — jamais une PII),
    JAMAIS park. Fin de la fuite DEAD_LETTER."""
    monkeypatch.setenv("ARAC_DISPOSE_COVERAGE_V2", "1")
    presented = _presented(fully_presented=True, max_id=12)
    for expected in (1, 2):
        _, progress = await _dispose_once(presented, cursor_lib)
        assert progress["conv-1"]["retry_count"] == expected
        assert not cursor_lib.excluded and not cursor_lib.advances

    totals, progress = await _dispose_once(presented, cursor_lib)
    assert progress["conv-1"]["excluded"] is True
    assert progress["conv-1"]["cursor"] == 12
    assert not progress["conv-1"].get("parked")
    assert cursor_lib.parked == []
    assert cursor_lib.advances == [("c1-id", 12, 0)], \
        "curseur avancé au max PRÉSENTÉ, atoms_generated=0"
    assert len(cursor_lib.excluded) == 1
    conv_id, category, reason, by = cursor_lib.excluded[0]
    assert conv_id == "c1-id"
    assert category == "no_curable_content", \
        "taxonomie FERMÉE 0023 (low_yield_omission violerait la CHECK)"
    assert reason.startswith("low_yield_omission:3_full_presentations_no_atoms")
    assert by == "cortex-dispose"
    assert "alice" not in reason.lower() and "exemple" not in reason.lower()
    assert totals["coverage_omitted"] == 1, "arithmétique de couverture intacte"


async def test_flag_on_truncated_slice_backoff_never_parks_never_excludes(
        cursor_lib, monkeypatch):
    """FLAG ON + tranche TRONQUÉE (géant > budget) : l'omission ne compte
    JAMAIS vers le seuil — backoff plafonné (defer), jamais park, jamais
    exclusion, curseur intouché, même après 6 cycles."""
    monkeypatch.setenv("ARAC_DISPOSE_COVERAGE_V2", "1")
    presented = _presented(fully_presented=False)
    for _ in range(6):
        totals, progress = await _dispose_once(presented, cursor_lib)
        assert progress["conv-1"]["coverage"] == "omitted"
        assert progress["conv-1"]["deferred"] is True
        assert not progress["conv-1"].get("parked")
        assert totals["coverage_omitted"] == 1
    assert len(cursor_lib.deferred_calls) == 6
    assert cursor_lib.deferred_calls[0][1].endswith(":truncated_slice")
    assert not cursor_lib.mark_failed_calls, "jamais le compteur de park"
    assert not cursor_lib.parked and not cursor_lib.excluded
    assert not cursor_lib.advances, "curseur JAMAIS avancé sur tranche tronquée"
    assert cursor_lib._retry_counts["c1-id"] <= 4, "cap 4 : reste DANS le gate"


async def test_flag_on_meta_without_fully_presented_treated_as_truncated(
        cursor_lib, monkeypatch):
    """FLAG ON + meta SANS la clé (pack d'une version antérieure, reprise
    mid-déploiement) : fail-toward-keep — traité comme tronqué (backoff),
    jamais un drain sans preuve de présentation complète."""
    monkeypatch.setenv("ARAC_DISPOSE_COVERAGE_V2", "1")
    presented = _presented(fully_presented=None)
    assert "fully_presented" not in presented["conv-1"]
    _, progress = await _dispose_once(presented, cursor_lib)
    assert progress["conv-1"]["deferred"] is True
    assert not cursor_lib.excluded and not cursor_lib.advances


async def test_flag_on_success_between_omissions_resets_counter(
        cursor_lib, monkeypatch):
    """FLAG ON : un succès entre deux omissions remet le compteur à 0 (mêmes
    garanties que le retry_count SQL) — pas de drain sur omissions non
    consécutives."""
    monkeypatch.setenv("ARAC_DISPOSE_COVERAGE_V2", "1")
    presented = _presented(fully_presented=True)
    await _dispose_once(presented, cursor_lib)
    await _dispose_once(presented, cursor_lib)
    assert cursor_lib._retry_counts["c1-id"] == 2
    # succès (no_new_knowledge) -> reset
    doc = {"contract_version": "cortex-dispose/1", "run_ref": "slot",
           "complete": True, "audit_summary": "t",
           "conversations": [{"conversation_uid": "conv-1", "atoms": [],
                              "no_new_knowledge": True, "skips": []}]}
    await dispose.dispose_document(
        FakeDb(), doc, presented, run_ref="slot", node_id="arac-curator",
        valid_scopes=SCOPES, api=FakeApi())
    assert cursor_lib._retry_counts["c1-id"] == 0
    _, progress = await _dispose_once(presented, cursor_lib)
    assert progress["conv-1"]["retry_count"] == 1
    assert not cursor_lib.excluded


def test_defer_conversation_sql_caps_retry_at_4():
    """Le SQL réel de `defer_conversation` plafonne retry_count à 4 (LEAST) et
    pose un backoff — jamais l'épuisement du cap `retry_count < 5` du gate."""
    src = inspect.getsource(curator_lib_v2.defer_conversation)
    assert "LEAST(retry_count + 1, 4)" in src
    assert "next_retry_at = now() + make_interval(" in src
    assert "GREATEST" not in src, "jamais un park déguisé"


def test_mark_conversation_excluded_sql_sets_all_four_columns():
    src = inspect.getsource(curator_lib_v2.mark_conversation_excluded)
    for col in ("exclusion_category", "exclusion_reason", "excluded_at",
                "excluded_by"):
        assert col in src
    assert "acked =" not in src, \
        "l'exclusion ne pose JAMAIS acked (chemin d'ack 0023 séparé)"
    assert "DELETE FROM" not in src.upper(), "jamais de DELETE"


def test_low_yield_category_is_in_closed_taxonomy_0023():
    """Garde anti-crash prod : la catégorie posée par le drain DOIT appartenir
    à la CHECK fermée 0023 (source de vérité partagée avec l'outil ops)."""
    # L'outil d'exclusion manuelle vit dans scripts/ops/ et n'est pas requis
    # pour que le moteur tourne : si le dépôt ne l'embarque pas, on saute
    # plutôt que d'affirmer une cohérence qu'on n'a pas vérifiée.
    tool = _REPO / "scripts" / "ops" / "exclude_conversation.py"
    if not tool.exists():
        pytest.skip("scripts/ops/exclude_conversation.py absent — rien a croiser")
    spec = importlib.util.spec_from_file_location("exclude_conversation", tool)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert dispose.LOW_YIELD_EXCLUSION_CATEGORY in mod.EXCLUSION_CATEGORIES
    assert not mod.looks_like_personal_name(dispose.LOW_YIELD_EXCLUSION_BY)


# ===========================================================================
# PAS 3 — value-gate SHADOW LOG-ONLY
# ===========================================================================


#: Le nœud OPÉRATEUR du jeu d'essai. Déclaré ici, jamais hérité d'un défaut :
#: un test qui dépend de l'identité configurée teste l'identité, pas le gate.
_OPERATOR_NODE = "test-node-server"
_OPERATORS = frozenset({_OPERATOR_NODE})


@pytest.fixture(autouse=True)
def _declare_operator_node(monkeypatch):
    monkeypatch.setenv("ARAC_VALUE_GATE_OPERATOR_NODES", _OPERATOR_NODE)


def _row(**over):
    base = {"id": "cid", "conversation_uid": "uid-1", "node_id": _OPERATOR_NODE,
            "source_type": "claude_code", "atoms_generated": 0, "cursor": 500,
            "uncured_chars": 600_000}  # 600k chars ~ 150 ktok
    base.update(over)
    return base


def test_score_row_low_value_candidate_with_figures():
    cand = value_gate.score_row(_row(), operator_nodes=_OPERATORS)
    assert cand is not None
    assert cand["uid"] == "uid-1"
    assert cand["atoms_generated"] == 0
    assert cand["cursor"] == 500
    assert cand["uncured_ktok"] == 150.0
    assert cand["score"] == "low_value_operator_session"


def test_score_row_protects_conversations_with_atoms():
    """GARDE DURE : atoms_generated>0 n'est JAMAIS candidate —
    4dfafcdc (6 atomes) et 8e352c9c (1 atome) restent hors liste."""
    assert value_gate.score_row(_row(atoms_generated=6), operator_nodes=_OPERATORS) is None
    assert value_gate.score_row(_row(atoms_generated=1), operator_nodes=_OPERATORS) is None


def test_score_row_protects_never_engaged_cursor_zero():
    assert value_gate.score_row(_row(cursor=0), operator_nodes=_OPERATORS) is None


def test_score_row_protects_non_operator_nodes():
    assert value_gate.score_row(_row(node_id="mac-1"), operator_nodes=_OPERATORS) is None
    assert value_gate.score_row(_row(node_id="arac-curator"), operator_nodes=_OPERATORS) is None


def test_score_row_protects_below_mass_threshold():
    # 100 kt = 400k chars : juste en-dessous -> protégée.
    assert value_gate.score_row(_row(uncured_chars=399_999), operator_nodes=_OPERATORS) is None
    assert value_gate.score_row(_row(uncured_chars=400_000), operator_nodes=_OPERATORS) is not None


def test_thresholds_from_env_defaults_and_overrides(monkeypatch):
    for var in ("ARAC_VALUE_GATE_UNCURED_KTOK_MIN",
                "ARAC_VALUE_GATE_ENGAGED_CURSOR_MIN",
                "ARAC_VALUE_GATE_OPERATOR_NODES"):
        monkeypatch.delenv(var, raising=False)
    th = value_gate.thresholds_from_env()
    assert th["uncured_ktok_min"] == 100.0
    assert th["engaged_cursor_min"] == 1
    # Le nœud opérateur par défaut est DÉRIVÉ de l'identité du cerveau
    # (`<node_id>-server`), jamais écrit en dur. Si l'identité n'est pas
    # connue, l'ensemble est VIDE : aucun nœud opérateur, donc le gate ne
    # propose l'exclusion de rien — se taire est le bon défaut.
    assert th["operator_nodes"] == value_gate.DEFAULT_OPERATOR_NODES
    for n in th["operator_nodes"]:
        assert n.endswith("-server")

    monkeypatch.setenv("ARAC_VALUE_GATE_UNCURED_KTOK_MIN", "50")
    monkeypatch.setenv("ARAC_VALUE_GATE_OPERATOR_NODES", f"{_OPERATOR_NODE}, autre-node")
    th2 = value_gate.thresholds_from_env()
    assert th2["uncured_ktok_min"] == 50.0
    assert th2["operator_nodes"] == frozenset({_OPERATOR_NODE, "autre-node"})

    monkeypatch.setenv("ARAC_VALUE_GATE_UNCURED_KTOK_MIN", "pas-un-nombre")
    assert value_gate.thresholds_from_env()["uncured_ktok_min"] == 100.0, \
        "env illisible -> défaut, jamais un crash de cycle"


class _ShadowCursor:
    """Curseur DB fake : enregistre chaque SQL exécuté (preuve read-only)."""

    def __init__(self, rows):
        self._rows = rows
        self.executed: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, sql, params=None):
        self.executed.append(sql)

    async def fetchall(self):
        return self._rows


class _ShadowDb:
    def __init__(self, rows):
        self.cur = _ShadowCursor(rows)
        self.committed = False

    def cursor(self):
        return self.cur

    async def commit(self):
        self.committed = True


async def test_shadow_scan_logs_candidates_and_never_writes(caplog):
    """SHADOW : les candidats sont retournés + loggés avec leurs chiffres ;
    AUCUNE écriture (un seul SELECT, jamais d'UPDATE/INSERT, jamais commit)."""
    rows = [
        ("c1", "uid-monster", _OPERATOR_NODE, "claude_code", 0, 500, 2_216_000),
        ("c2", "uid-4dfafcdc", _OPERATOR_NODE, "claude_code", 6, 900, 2_000_000),
        ("c3", "uid-mac", "mac-1", "claude_code", 0, 10, 900_000),
    ]
    db = _ShadowDb(rows)
    with caplog.at_level(logging.INFO, logger="arac.cortex.value_gate"):
        candidates = await value_gate.shadow_scan(db)

    assert [c["uid"] for c in candidates] == ["uid-monster"], \
        "atomes>0 et node non-opérateur protégés"
    assert candidates[0]["uncured_ktok"] == 554.0

    assert len(db.cur.executed) == 1
    sql = db.cur.executed[0].strip().upper()
    assert sql.startswith("SELECT")
    for verb in ("UPDATE", "INSERT", "DELETE"):
        assert verb not in sql
    assert db.committed is False, "aucune écriture de décision en shadow"

    events = [json.loads(r.message) for r in caplog.records]
    excludes = [e for e in events if e["event"] == "value_gate.shadow_exclude"]
    summaries = [e for e in events if e["event"] == "value_gate.shadow_summary"]
    assert len(excludes) == 1 and excludes[0]["uid"] == "uid-monster"
    assert summaries and summaries[0]["would_be_excluded"] == 1
    assert summaries[0]["scanned"] == 3


def test_candidates_sql_is_read_only_and_excludes_already_excluded():
    sql = value_gate._CANDIDATES_SQL.upper()
    assert sql.strip().startswith("SELECT")
    for verb in ("UPDATE", "INSERT", "DELETE", "FOR UPDATE"):
        assert verb not in sql
    assert "EXCLUSION_CATEGORY IS NULL" in sql


def test_value_gate_has_no_enforce_writer():
    """AUCUNE écriture de décision dans le module (enforce = pas 4, GO
    cockpit) : pas d'accès aux writers de curator_lib_v2, pas d'UPDATE."""
    src = inspect.getsource(value_gate)
    assert "mark_conversation_excluded" not in src.replace(
        "curator_lib_v2.mark_conversation_excluded`)", "")  # docstring seule
    assert "UPDATE " not in src


def test_cycle_shadow_call_is_flag_gated_and_non_blocking():
    """cycle.py : le scan shadow est gaté par ARAC_VALUE_GATE_SHADOW (défaut
    OFF) et enveloppé try/except + ROLLBACK (fix round-1 : un échec SQL sans
    rollback laissait la transaction avortée et cassait tout le cycle)."""
    from agents.cortex import cycle
    src = inspect.getsource(cycle.run_cycle)
    assert 'ARAC_VALUE_GATE_SHADOW' in src
    idx = src.index("ARAC_VALUE_GATE_SHADOW")
    assert "_shadow_scan_guarded" in src[idx:idx + 300]
    helper = inspect.getsource(cycle._shadow_scan_guarded)
    assert "value_gate.shadow_scan" in helper
    assert "except Exception" in helper
    assert "rollback" in helper, "fix round-1 : transaction avortée nettoyée"


# ===========================================================================
# PAS 3 — prédicat `exclusion_category IS NULL` : gate + TOUS les miroirs
# ===========================================================================


def test_gate_and_all_mirrors_carry_exclusion_predicate():
    """Le prédicat d'exclusion est posé AUX QUATRE endroits (:
    un miroir oublié re-signale les exclues -> faux STARVATION) : gate
    (select+count), miroir watchdog, détail conservation-audit, cockpit
    coût."""
    clause = "c.exclusion_category IS NULL"
    assert clause in inspect.getsource(curator_lib_v2.select_eligible_conversations)
    assert clause in inspect.getsource(curator_lib_v2.count_uncurated)

    wd_spec = importlib.util.spec_from_file_location(
        "iw_stab", _REPO / "app" / "perception" / "ingest_watchdog.py")
    wd = importlib.util.module_from_spec(wd_spec)
    wd_spec.loader.exec_module(wd)
    assert clause in wd._ACTIONABLE_BACKLOG_SQL

    ca_spec = importlib.util.spec_from_file_location(
        "ca_stab", _REPO / "app" / "perception" / "conservation_audit.py")
    ca = importlib.util.module_from_spec(ca_spec)
    ca_spec.loader.exec_module(ca)
    assert clause in ca._ACTIONABLE_BACKLOG_DETAIL_SQL

    pac_src = (_REPO / "agents" / "lib" / "paid_ai_control.py").read_text()
    assert clause in pac_src
