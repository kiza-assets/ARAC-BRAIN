"""Tests du chunking curator — v0.6.

Découpe d'une conversation en segments <= budget de tokens, sans jamais couper
un message, avec passthrough mono-segment pour les conversations qui tiennent.
"""

from __future__ import annotations

import json

from agents.curator.chunking import split_messages_into_chunks
from agents.lib.token_count import count_tokens


# Compteur déterministe pour les tests de packing (indépendant de tiktoken) :
# 1 token = 1 caractère du JSON du message.
def _char_count(text: str) -> int:
    return len(text)


def _msg(content: str) -> dict:
    return {"role": "user", "content": content}


def test_empty_returns_no_chunk():
    assert split_messages_into_chunks(
        [], overhead_tokens=10, budget_tokens=100, count_fn=_char_count
    ) == []


def test_small_conversation_is_single_chunk_passthrough():
    msgs = [_msg("a"), _msg("b"), _msg("c")]
    chunks = split_messages_into_chunks(
        msgs, overhead_tokens=10, budget_tokens=1_000_000, count_fn=_char_count
    )
    assert len(chunks) == 1
    assert chunks[0] == msgs


def test_large_conversation_splits_and_preserves_order_and_messages():
    msgs = [_msg(f"message-{i}-" + "x" * 50) for i in range(20)]
    per = _char_count(json.dumps(msgs[0], ensure_ascii=False)) + 4
    # Budget visant ~4 messages par segment.
    budget = 10 + per * 4
    chunks = split_messages_into_chunks(
        msgs, overhead_tokens=10, budget_tokens=budget, count_fn=_char_count
    )
    assert len(chunks) > 1
    # Aucun message perdu, ordre global préservé.
    flat = [m for c in chunks for m in c]
    assert flat == msgs
    # Chaque segment (sauf cas message-seul) respecte le budget.
    for c in chunks:
        toks = sum(_char_count(json.dumps(m, ensure_ascii=False)) + 4 for m in c)
        assert len(c) == 1 or 10 + toks <= budget


def test_message_never_split_across_chunks():
    msgs = [_msg("x" * 100) for _ in range(6)]
    chunks = split_messages_into_chunks(
        msgs, overhead_tokens=0, budget_tokens=250, count_fn=_char_count
    )
    # Chaque élément de chaque segment est un message complet et intact.
    for c in chunks:
        for m in c:
            assert m == _msg("x" * 100)
    assert sum(len(c) for c in chunks) == 6


def test_single_oversized_message_gets_its_own_chunk():
    msgs = [_msg("ok"), _msg("HUGE" * 1000), _msg("ok2")]
    chunks = split_messages_into_chunks(
        msgs, overhead_tokens=0, budget_tokens=100, count_fn=_char_count
    )
    # Le message géant occupe seul un segment ; aucun message perdu.
    flat = [m for c in chunks for m in c]
    assert flat == msgs
    assert any(len(c) == 1 and len(c[0]["content"]) > 100 for c in chunks)


def test_count_tokens_returns_positive_int():
    n = count_tokens("hello world, ceci est un test de tokens")
    assert isinstance(n, int) and n > 0


def test_count_tokens_empty_is_zero():
    assert count_tokens("") == 0
