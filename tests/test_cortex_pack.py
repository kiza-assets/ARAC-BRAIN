"""Tests hermétiques de `pack.build_pack` — sémantique de
troncature CONSERVATRICE (report solo / blocage motivé), zéro DB réelle.

Couvre l'INV-7 (`presented[uid].max_id` ne contient JAMAIS un id non
intégralement présenté) et les 3 issues d'un message de tête qui ne tient
pas dans le budget RESTANT :
  - il tient dans le budget PLEIN -> REPORT (conversation hors pack ce
    cycle, curseur inchangé, `messages_reported` incrémenté) ;
  - il ne tient même pas dans le budget PLEIN -> BLOCAGE (`oversized_messages`,
    conversation exclue, curseur gelé) ;
  - `TRUNC_MARKER`/troncature n'existent plus : `messages_truncated` == 0
    partout, jamais un message coupé au milieu.

Fakes : `curator_lib_v2` est entièrement remplacé (même style que
`tests/test_cortex_dispose.py` — `monkeypatch.setattr(pack_mod,
"curator_lib_v2", ...)`), `count_fn` est un compteur déterministe (1 char =
1 "token", même convention que `tests/test_curator_chunking.py`).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agents.cortex import pack as pack_mod  # noqa: E402


def _char_count(text: str) -> int:
    """Compteur déterministe (indépendant de tiktoken, cf test_curator_chunking)."""
    return len(text)


def _conv(conv_id: str, uid: str, *, cursor: int = 0, source_type: str = "claude_code") -> dict:
    return {"id": conv_id, "conversation_uid": uid, "source_type": source_type,
            "node_id": "mac-1", "cursor": cursor}


def _msg(msg_id: int, content: str, *, role: str = "user") -> dict:
    return {"id": msg_id, "message_uuid": f"u-{msg_id}", "role": role,
            "content": content, "msg_created_at": None}


def _prefix_len(msg_id: int, role: str = "user") -> int:
    return len(f"[id={msg_id}] {role}: ")


def _header_len(uid: str, source_type: str = "claude_code") -> int:
    return len(f"## conversation {uid} (source={source_type})")


def _msg_for_cost(msg_id: int, target_cost: int, *, role: str = "user") -> dict:
    """Construit un message dont le coût RENDU (`_render_message`) vaut
    exactement `target_cost` sous `count_fn=_char_count` — évite tout calcul
    manuel de longueur d'en-tête/préfixe dans les tests de frontière."""
    n = target_cost - _prefix_len(msg_id, role)
    assert n >= 0, "target_cost trop petit pour ce préfixe"
    return _msg(msg_id, "x" * n, role=role)


class FakeCuratorLib:
    """Remplace `curator_lib_v2` (même pattern que test_cortex_dispose.FakeCursorLib) :
    `messages_by_conv` = {conversation_id: [messages...]} déjà filtrés du curseur
    (les tests posent directement les lignes NON curées, pas de simulation
    de watermark réelle)."""

    def __init__(self, conversations: list[dict], messages_by_conv: dict[str, list[dict]]):
        self.conversations = conversations
        self.messages_by_conv = messages_by_conv

    async def select_eligible_conversations(self, db, *, limit: int) -> list[dict]:
        return self.conversations[:limit]

    async def fetch_uncurated_messages(self, db, conversation_id, cursor, *, limit=None):
        rows = self.messages_by_conv.get(conversation_id, [])
        rows = [m for m in rows if m["id"] > cursor]
        if limit is not None:
            rows = rows[:limit]
        return rows


@pytest.fixture()
def curator_lib(monkeypatch):
    """Installe un FakeCuratorLib vide par défaut ; les tests le peuplent via
    `curator_lib.conversations`/`curator_lib.messages_by_conv` avant l'appel,
    ou construisent directement leur propre instance (cf `_install`)."""
    fake = FakeCuratorLib([], {})
    monkeypatch.setattr(pack_mod, "curator_lib_v2", fake)

    async def _fake_known_atoms(db, uids):
        return "(aucun)"

    monkeypatch.setattr(pack_mod, "_known_atoms_block", _fake_known_atoms)
    return fake


def _install(curator_lib: FakeCuratorLib, conversations, messages_by_conv) -> None:
    curator_lib.conversations = conversations
    curator_lib.messages_by_conv = messages_by_conv


async def _build(budget_tokens: int, **kw):
    return await pack_mod.build_pack(
        object(), budget_tokens=budget_tokens, count_fn=_char_count, **kw)


# ---------------------------------------------------------------------------
# Cas nominal : tout tient
# ---------------------------------------------------------------------------


async def test_all_messages_fit_single_conversation(curator_lib):
    _install(curator_lib, [_conv("c1", "conv-1")],
             {"c1": [_msg(1, "bonjour"), _msg(2, "ça va")]})
    built = await _build(10_000)

    assert [p["uid"] for p in built["pack_meta"]] == ["conv-1"]
    assert built["presented"]["conv-1"]["max_id"] == 2
    assert built["presented"]["conv-1"]["message_ids"] == {1, 2}
    assert built["messages_reported"] == 0
    assert built["messages_truncated"] == 0
    assert built["oversized_messages"] == []


# ---------------------------------------------------------------------------
# Tête > restant, pack NON vide -> report, curseur figé
# ---------------------------------------------------------------------------


async def test_head_over_remaining_within_full_budget_non_empty_pack_reports(curator_lib):
    """2 conversations : la 1re consomme l'essentiel du budget (incluse en
    entier), la 2e porte un message de tête qui ne tient plus dans le
    RESTANT mais tiendrait dans le budget PLEIN -> reportée seule, la 1re
    reste dans le pack (pack NON vide)."""
    header_a = _header_len("conv-a")
    header_b = _header_len("conv-b")
    cost_a = 200  # tient large sous n'importe quel budget raisonnable
    msg_a = _msg_for_cost(1, cost_a)
    # Budget calé pour qu'après A il ne reste, avant l'en-tête de B, QUE
    # `header_b + 50` -> B a une marge de 50 dans le RESTANT.
    budget = header_a + cost_a + header_b + 50
    # B : coût qui dépasse ce restant (50) mais tient large dans le budget
    # PLEIN (`budget`).
    msg_b = _msg_for_cost(1, 50 + 20)
    _install(curator_lib, [_conv("cA", "conv-a"), _conv("cB", "conv-b")],
             {"cA": [msg_a], "cB": [msg_b]})
    built = await _build(budget)

    uids = [p["uid"] for p in built["pack_meta"]]
    assert uids == ["conv-a"], "seule A passe ce cycle"
    assert "conv-b" not in built["presented"], "curseur de B jamais touché"
    assert built["messages_reported"] == 1
    assert built["oversized_messages"] == []
    assert built["messages_truncated"] == 0


# ---------------------------------------------------------------------------
# Tête > restant, pack VIDE (≤ plein) -> sautée ce cycle, puis passe seule
# ---------------------------------------------------------------------------


async def test_head_over_remaining_empty_pack_then_passes_alone_next_cycle(curator_lib):
    """Seule candidate : son message de tête + l'en-tête dépassent tout juste
    le budget (report), pack VIDE ce cycle. Rejouée avec un budget PLEIN
    généreux (« cycle suivant, budget frais »), la même conversation passe
    intégralement — jamais de troncature entre les deux."""
    uid, cid = "conv-solo", "cS"
    content = "z" * 200
    header_len = len(f"## conversation {uid} (source=claude_code)")
    rendered_len = len(f"[id=1] user: {content}")
    # budget serré : le message tient dans le budget PLEIN mais pas dans
    # ce qu'il reste une fois l'en-tête compté.
    tight_budget = header_len + rendered_len - 5
    _install(curator_lib, [_conv(cid, uid)], {cid: [_msg(1, content)]})

    built = await _build(tight_budget)
    assert built["pack_meta"] == []
    assert uid not in built["presented"]
    assert built["messages_reported"] == 1
    assert built["oversized_messages"] == []

    # « Cycle suivant » : même conversation, curseur toujours à 0 (jamais
    # avancé), rejouée seule avec un budget PLEIN généreux -> passe entière.
    built2 = await _build(pack_mod.DEFAULT_PACK_TOKEN_BUDGET)
    assert [p["uid"] for p in built2["pack_meta"]] == [uid]
    assert built2["presented"][uid]["max_id"] == 1
    assert built2["messages_reported"] == 0


# ---------------------------------------------------------------------------
# Message unique > budget PLEIN -> blocage fail-closed, aucune avance
# ---------------------------------------------------------------------------


async def test_single_message_over_full_budget_is_oversized_no_advance(curator_lib):
    uid, cid = "conv-monster", "cM"
    content = "m" * 500
    _install(curator_lib, [_conv(cid, uid)], {cid: [_msg(7, content)]})
    budget = 100  # très inférieur au message -> ne tient dans AUCUN budget

    built = await _build(budget)

    assert built["pack_meta"] == []
    assert uid not in built["presented"]
    assert built["messages_reported"] == 0
    assert built["messages_truncated"] == 0
    assert len(built["oversized_messages"]) == 1
    om = built["oversized_messages"][0]
    assert om["uid"] == uid
    assert om["message_id"] == 7
    assert om["chars"] == 500
    assert om["est_tokens"] == len(f"[id=7] user: {content}")
    # Jamais de contenu tronqué/marqué nulle part.
    assert "conv-monster" not in built["conversations_block"]
    assert built["conversations_block"] == "(aucune)"


# ---------------------------------------------------------------------------
# Frontière exacte restant / plein
# ---------------------------------------------------------------------------


async def test_exact_boundary_remaining_vs_full_budget(curator_lib):
    """cost == remaining -> inclus ; cost == plein exactement -> reporté
    (borne "<= plein" INCLUSIVE) ; cost == plein+1 -> oversized."""
    uid, cid = "conv-b", "cB"
    budget = 500
    remaining_after_header = budget - _header_len(uid)

    # (a) cost == remaining exactement -> inclus (limite stricte : "> restant"
    # ne se déclenche pas à l'égalité).
    _install(curator_lib, [_conv(cid, uid)], {cid: [_msg_for_cost(1, remaining_after_header)]})
    built = await _build(budget)
    assert built["pack_meta"] and built["pack_meta"][0]["uid"] == uid
    assert built["messages_reported"] == 0
    assert built["oversized_messages"] == []

    # (b) cost == budget PLEIN exactement -> reporté (pas oversized : la
    # borne "<= plein" est INCLUSIVE).
    _install(curator_lib, [_conv(cid, uid)], {cid: [_msg_for_cost(1, budget)]})
    built2 = await _build(budget)
    assert built2["pack_meta"] == []
    assert built2["messages_reported"] == 1
    assert built2["oversized_messages"] == []

    # (c) cost == budget PLEIN + 1 -> oversized (la borne "> plein" bascule).
    _install(curator_lib, [_conv(cid, uid)], {cid: [_msg_for_cost(1, budget + 1)]})
    built3 = await _build(budget)
    assert built3["pack_meta"] == []
    assert built3["messages_reported"] == 0
    assert len(built3["oversized_messages"]) == 1


# ---------------------------------------------------------------------------
# BREAK — 400k chars : aucun chemin n'avance ni ne tronque
# ---------------------------------------------------------------------------


async def test_break_400k_chars_never_advances_nor_truncates(curator_lib):
    uid, cid = "conv-huge", "cH"
    content = "h" * 400_000
    _install(curator_lib, [_conv(cid, uid)], {cid: [_msg(1, content)]})
    built = await _build(pack_mod.DEFAULT_PACK_TOKEN_BUDGET)

    assert built["pack_meta"] == []
    assert uid not in built["presented"]
    assert built["messages_truncated"] == 0
    assert len(built["oversized_messages"]) == 1
    assert built["oversized_messages"][0]["chars"] == 400_000


# ---------------------------------------------------------------------------
# BREAK — pack de 20 conversations, la 1re géante : les 19 autres passent
# ---------------------------------------------------------------------------


async def test_break_first_of_twenty_oversized_others_pass(curator_lib):
    conversations = [_conv("c0", "conv-monster")]
    messages = {"c0": [_msg(1, "g" * 200_000)]}  # > budget PLEIN, seule -> oversized
    for i in range(1, 20):
        cid, uid = f"c{i}", f"conv-{i}"
        conversations.append(_conv(cid, uid))
        messages[cid] = [_msg(1, f"petit message {i}")]
    _install(curator_lib, conversations, messages)

    built = await _build(pack_mod.DEFAULT_PACK_TOKEN_BUDGET, max_conversations=20)

    uids = {p["uid"] for p in built["pack_meta"]}
    assert uids == {f"conv-{i}" for i in range(1, 20)}
    assert "conv-monster" not in uids
    assert len(built["oversized_messages"]) == 1
    assert built["oversized_messages"][0]["uid"] == "conv-monster"


# ---------------------------------------------------------------------------
# BREAK — deux messages géants successifs dans la même conversation
# ---------------------------------------------------------------------------


async def test_break_two_giant_messages_same_conversation(curator_lib):
    """1er message : tient seul dans le budget (inclus). 2e message : dépasse
    ce qu'il reste après le 1er -> coupure NORMALE (pas "tête", pas
    oversized cette fois) ; le curseur ne doit avancer QUE jusqu'au 1er."""
    uid, cid = "conv-double", "cD"
    budget = 1_000
    msg_a = _msg(1, "a" * 900)   # tient seul, laisse peu de restant
    msg_b = _msg(2, "b" * 900)   # ne rentre plus, mais PAS la tête -> break normal
    _install(curator_lib, [_conv(cid, uid)], {cid: [msg_a, msg_b]})

    built = await _build(budget)

    assert built["pack_meta"][0]["uid"] == uid
    assert built["presented"][uid]["max_id"] == 1, "jamais avancé jusqu'au 2e (non montré)"
    assert built["presented"][uid]["message_ids"] == {1}
    assert built["oversized_messages"] == [], "le 2e n'est pas 'tête' -> pas signalé ce cycle"
    assert built["messages_reported"] == 0


# ---------------------------------------------------------------------------
# phase 2 — budget pack surchargeable par env (ARAC_PACK_TOKEN_BUDGET)
# ---------------------------------------------------------------------------


def test_pack_budget_no_env_is_default_80k(monkeypatch):
    """Sans env : bit-identique au défaut historique 80 000."""
    monkeypatch.delenv("ARAC_PACK_TOKEN_BUDGET", raising=False)
    assert pack_mod._pack_token_budget() == 80_000 == pack_mod.DEFAULT_PACK_TOKEN_BUDGET


def test_pack_budget_env_applied(monkeypatch):
    """env=95000 (valeur cible déploiement) -> budget appliqué tel quel."""
    monkeypatch.setenv("ARAC_PACK_TOKEN_BUDGET", "95000")
    assert pack_mod._pack_token_budget() == 95_000


def test_pack_budget_env_clamped_to_hard_cap(monkeypatch):
    """env=200000 -> clampé au plafond dur 135 000 (= 150k spend_guard −
    15k d'overhead pire-cas mesuré : jamais de spawn refusé/slot brûlé)."""
    monkeypatch.setenv("ARAC_PACK_TOKEN_BUDGET", "200000")
    assert pack_mod._pack_token_budget() == 135_000 == pack_mod.PACK_TOKEN_BUDGET_HARD_CAP


def test_pack_budget_env_invalid_falls_back_with_warning(monkeypatch, caplog):
    """env illisible -> défaut 80k + WARNING, jamais un crash de cycle."""
    monkeypatch.setenv("ARAC_PACK_TOKEN_BUDGET", "quatre-vingt-mille")
    with caplog.at_level("WARNING", logger="arac.cortex.pack"):
        assert pack_mod._pack_token_budget() == 80_000
    assert any("ARAC_PACK_TOKEN_BUDGET" in r.message for r in caplog.records)


def test_pack_budget_env_non_positive_falls_back_with_warning(monkeypatch, caplog):
    """env <= 0 -> défaut 80k + WARNING (fail-safe, pas de budget nul)."""
    monkeypatch.setenv("ARAC_PACK_TOKEN_BUDGET", "-5")
    with caplog.at_level("WARNING", logger="arac.cortex.pack"):
        assert pack_mod._pack_token_budget() == 80_000
    assert any("ARAC_PACK_TOKEN_BUDGET" in r.message for r in caplog.records)


async def test_build_pack_default_budget_reads_env_each_build(curator_lib, monkeypatch):
    """Intégration : `build_pack` SANS budget explicite (le cas cycle.py:377)
    lit l'env À CHAQUE build — un message de tête de coût 150 est bloqué
    (oversized) sous env=100, puis passe sous env=200 SANS ré-import."""
    uid, cid = "conv-env", "cE"
    _install(curator_lib, [_conv(cid, uid)], {cid: [_msg_for_cost(1, 150)]})

    monkeypatch.setenv("ARAC_PACK_TOKEN_BUDGET", "100")
    built = await pack_mod.build_pack(object(), count_fn=_char_count)
    assert built["pack_meta"] == []
    assert [o["uid"] for o in built["oversized_messages"]] == [uid]

    monkeypatch.setenv("ARAC_PACK_TOKEN_BUDGET", "200")
    built = await pack_mod.build_pack(object(), count_fn=_char_count)
    assert [p["uid"] for p in built["pack_meta"]] == [uid]
    assert built["oversized_messages"] == []


async def test_build_pack_explicit_budget_wins_over_env(curator_lib, monkeypatch):
    """Un budget explicite du caller garde la main sur l'env (l'override ne
    s'applique qu'au défaut)."""
    uid, cid = "conv-exp", "cX"
    _install(curator_lib, [_conv(cid, uid)], {cid: [_msg_for_cost(1, 150)]})
    monkeypatch.setenv("ARAC_PACK_TOKEN_BUDGET", "100")
    built = await _build(10_000)
    assert [p["uid"] for p in built["pack_meta"]] == [uid]
    assert built["oversized_messages"] == []
