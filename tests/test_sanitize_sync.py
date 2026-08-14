"""CI test anti-drift : app/services/sanitize.py equiv agents/lib/log_capture.py.

Doctrine A3 v0.5 (frontiere app vs agents) : on duplique volontairement les
13 patterns secrets dans `app/services/sanitize.py` plutot que d importer
cross-package. Ce test garantit que les deux sources restent byte-for-byte
synchronisees - si une regex evolue dans log_capture.py sans MAJ de
sanitize.py (ou inverse), CI rouge.

Si ce test casse :
  1. Verifier quelle source a ete modifiee (git log).
  2. Reporter la modif dans l autre source.
  3. Penser : les agents Mac (log_capture.py) et l API ingest
     (sanitize.py) DOIVENT masquer exactement les memes secrets - drift =
     potentiel leak silencieux.
"""

from __future__ import annotations

from agents.lib.log_capture import _SECRET_PATTERNS as PATTERNS_AGENTS
from app.services.sanitize import _SECRET_PATTERNS as PATTERNS_APP


def test_sanitize_patterns_count_equal():
    """Meme nombre de patterns dans les deux sources."""
    assert len(PATTERNS_APP) == len(PATTERNS_AGENTS), (
        f"drift: app={len(PATTERNS_APP)} vs agents={len(PATTERNS_AGENTS)}"
    )


def test_sanitize_patterns_byte_for_byte():
    """Chaque (pattern, replacement, flags) est strictement egal."""
    for i, ((pa, ra), (pb, rb)) in enumerate(zip(PATTERNS_APP, PATTERNS_AGENTS)):
        assert pa.pattern == pb.pattern, (
            f"drift pattern[{i}]: app={pa.pattern!r} vs agents={pb.pattern!r}"
        )
        assert pa.flags == pb.flags, (
            f"drift flags[{i}]: app={pa.flags} vs agents={pb.flags}"
        )
        assert ra == rb, (
            f"drift repl[{i}]: app={ra!r} vs agents={rb!r}"
        )


def test_mask_secrets_idempotent():
    """mask_secrets(mask_secrets(x)) == mask_secrets(x)."""
    from app.services.sanitize import mask_secrets

    s = "sk-ant-abcdefgh1234 token=ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
    once = mask_secrets(s)
    twice = mask_secrets(once)
    assert once == twice
