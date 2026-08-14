"""Tests unitaires pour agents/lib/log_capture.py — Bloc 9a Vague 2 v0.4.

Couverture :
- 13 tests de masking secrets (1 par regex définie §4.1 spec D4)
- 1 test anti-faux-positif sur identifiants ARAC (UUID, SHA, version)
- Smoke test capture write + read JSONL

Doctrine : zéro tolérance leak. Tout secret factice DOIT être remplacé par
le marker [REDACTED:*] correspondant.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agents.lib.log_capture import MissionLogger, mask_secrets


# ---------------------------------------------------------------------------
# 13 tests masking — un par regex
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, leak_substr, redact_token",
    [
        # 1. anthropic
        ("oups sk-ant-api03-AAAAaaaaBBBBccccDDDDeeeeFFFF voilà",
         "sk-ant-api03", "[REDACTED:anthropic-key]"),
        # 2. openai (>= 40 chars après sk-)
        ("X-OAI: sk-AbCdEfGhIjKlMnOpQrStUvWxYzAbCdEfGhIjKlMnOp foo",
         "sk-AbCdEfGhIjKlMnOpQrStUvWxYzAbCdEfGhIjKlMnOp", "[REDACTED:openai-key]"),
        # 3. github PAT
        ("Auth: ghp_AbCdEfGhIjKlMnOpQrStUvWxYz1234567",
         "ghp_AbCdEf", "[REDACTED:github-pat]"),
        # 4. github oauth
        ("token=gho_AbCdEfGhIjKlMnOpQrStUvWxYz1234567",
         "gho_AbCdEf", "[REDACTED:github-oauth]"),
        # 5. gitlab PAT
        ("creds: glpat-aZ12345678901234567890",
         "glpat-aZ12", "[REDACTED:gitlab-pat]"),
        # 6. slack bot
        ("slack=xoxb-1234567890-ABCDEFG",
         "xoxb-1234567890", "[REDACTED:slack-bot]"),
        # 7. aws key (AKIA + 16 chars upper/digits)
        ("AKIAIOSFODNN7EXAMPLE plain",
         "AKIAIOSFODNN7EXAMPL", "[REDACTED:aws-key]"),
        # 8. private key PEM
        ("-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----",
         "MIIEpAIBAA", "[REDACTED:private-key]"),
        # 9. JWT 3-segments
        ("jwt=eyJhbGciOiJIUzI1NiJ9XXXXXXXXXXXXX.eyJzdWIiOiIxMjM0NTYiLCJuYW1lIjoiSm9obiJ9.SignatureXXXXXXXXXXXXXX",
         "eyJhbGciOiJIUzI1NiJ9", "[REDACTED:jwt]"),
        # 10. password assignment
        ("DB_PASSWORD=h0rs3-Batt3ry-St@pl3",
         "h0rs3-Batt3ry-St@pl3", "password=[REDACTED]"),
        # 11. bearer token
        ("Authorization: Bearer abcdefghijklmnop123456",
         "abcdefghijklmnop123", "bearer [REDACTED]"),
        # 12. postgres URI with creds
        ("dsn=postgres://arac_app:s3cr3tP@host:5432/db",
         "arac_app:s3cr3t", "postgres://[REDACTED]@"),
        # 13. generic token=
        ("token=AbCdEfGhIjKlMnOpQrStUvWxYz",
         "AbCdEfGhIjKlMnOpQrStUvWxYz", "token=[REDACTED]"),
    ],
)
def test_mask_redacts_secret(raw: str, leak_substr: str, redact_token: str) -> None:
    """Chaque pattern doit être masqué et le token REDACTED apparaître."""
    masked = mask_secrets(raw)
    assert leak_substr not in masked, (
        f"LEAK: '{leak_substr}' encore présent dans:\n{masked}"
    )
    assert redact_token in masked, (
        f"Marker manquant '{redact_token}' dans:\n{masked}"
    )


# ---------------------------------------------------------------------------
# Anti-faux-positif : UUID/SHA/version ne sont PAS masqués
# ---------------------------------------------------------------------------


def test_no_false_positive_on_arac_identifiers() -> None:
    """UUIDs (mission_id), SHA git, numéros version ne déclenchent aucune regex."""
    samples = [
        "mission_id=8f3a1c2e-4d2b-4e9a-9c1f-fccf15ce0001",
        "sha=abc123def456789012345678901234567890abcd",  # 40 hex
        "version v0.4.0-rc1 phase D.4",
        "branch feature/v0-4-cloture",
        "atome trace fccf15ce kind=state",
        "node_id=claude-developer",
        # SHA-256 random hex 64 chars (atome id)
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        # UUID with hyphens
        "00000000-0000-4000-8000-000000000001",
    ]
    for s in samples:
        masked = mask_secrets(s)
        assert masked == s, (
            f"Faux positif sur '{s}'\n→ masked: '{masked}'"
        )


# ---------------------------------------------------------------------------
# Smoke test : write events + read back
# ---------------------------------------------------------------------------


def test_smoke_write_and_read(tmp_path: Path) -> None:
    """Smoke test : MissionLogger écrit, on relit, on vérifie format JSONL."""
    mission_id = "test-smoke-" + os.urandom(4).hex()
    base = tmp_path / "agents"
    logger = MissionLogger(mission_id, base_dir=str(base))
    logger.write_event("mission.start", prompt="hello world", reply_chat_id=42)
    logger.write_event("subprocess.exit", exit_code=0, duration_ms=123)
    logger.close()

    path = base / f"{mission_id}.jsonl"
    assert path.exists(), f"transcript file {path} not written"

    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 3, f"expected 3 events (start+exit+_close), got {len(lines)}: {lines}"

    rec0 = json.loads(lines[0])
    assert rec0["event_type"] == "mission.start"
    assert rec0["mission_id"] == mission_id
    assert rec0["prompt"] == "hello world"
    assert rec0["reply_chat_id"] == 42
    assert "ts" in rec0

    rec1 = json.loads(lines[1])
    assert rec1["event_type"] == "subprocess.exit"
    assert rec1["exit_code"] == 0
    assert rec1["duration_ms"] == 123

    rec2 = json.loads(lines[2])
    assert rec2["event_type"] == "_close"


def test_smoke_secret_in_event_field_is_masked(tmp_path: Path) -> None:
    """Defense-in-depth : un secret passé en event field est masqué à l'écriture."""
    mission_id = "test-leak-" + os.urandom(4).hex()
    base = tmp_path / "agents"
    logger = MissionLogger(mission_id, base_dir=str(base))
    fake_secret = "sk-ant-fake-injection-AAAA1111BBBB2222CCCC3333"
    logger.write_event("mission.start", prompt=f"oups {fake_secret} suite")
    logger.close()

    content = (base / f"{mission_id}.jsonl").read_text(encoding="utf-8")
    assert fake_secret not in content, f"LEAK: secret factice présent dans transcript"
    assert "[REDACTED:anthropic-key]" in content


def test_idempotent_close(tmp_path: Path) -> None:
    """close() multiple appels = no-op après le premier."""
    mission_id = "test-close-" + os.urandom(4).hex()
    base = tmp_path / "agents"
    logger = MissionLogger(mission_id, base_dir=str(base))
    logger.write_event("mission.start", prompt="x")
    logger.close()
    logger.close()  # ne doit pas planter
    logger.close()
    content = (base / f"{mission_id}.jsonl").read_text(encoding="utf-8")
    assert content.count("\"event_type\":\"_close\"") == 1


def test_write_after_close_does_not_raise(tmp_path: Path) -> None:
    """Écrire après close() ne raise pas (graceful, log warn)."""
    mission_id = "test-after-close-" + os.urandom(4).hex()
    base = tmp_path / "agents"
    logger = MissionLogger(mission_id, base_dir=str(base))
    logger.close()
    # Ne raise PAS, juste warn dans journald
    logger.write_event("mission.start", prompt="too-late")
