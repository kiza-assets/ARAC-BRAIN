"""Tests du parser de message « limite de session » (v0.7)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agents.lib.session_limit import detect_session_limit, parse_reset_time

# Message réel capturé le 2026-05-23 21:09 (curator-5643f49a chunk 8/8).
REAL_MSG = "You've hit your session limit · resets 12:30am (UTC)\n"


def test_detect_real_message():
    assert detect_session_limit(REAL_MSG) is True


def test_detect_pm_variant():
    assert detect_session_limit("You've hit your session limit · resets 3pm (UTC)") is True


@pytest.mark.parametrize("text", [
    "",
    None,
    "✅ Atome 3 créé. Curation terminée.",
    # Parle de rate-limit dans le contenu mais sans annonce de reset -> pas un
    # message CLI de plafond.
    "Le rate-limit DoS sur uvicorn sans --proxy-headers est un risque.",
])
def test_no_false_positive(text):
    assert detect_session_limit(text) is False


def test_parse_real_message_next_occurrence_same_day():
    # 21:09 UTC -> prochain 00:30 = lendemain 00:30.
    now = datetime(2026, 5, 23, 21, 9, 0, tzinfo=timezone.utc)
    reset = parse_reset_time(REAL_MSG, now)
    assert reset == datetime(2026, 5, 24, 0, 30, 0, tzinfo=timezone.utc)


def test_parse_12_30am_is_midnight_thirty():
    # 12:30am == 00:30 ; à 23:00 le reset est dans 1h30 (même nuit -> lendemain 00:30).
    now = datetime(2026, 5, 23, 23, 0, 0, tzinfo=timezone.utc)
    reset = parse_reset_time(REAL_MSG, now)
    assert reset == datetime(2026, 5, 24, 0, 30, 0, tzinfo=timezone.utc)


def test_parse_3pm():
    now = datetime(2026, 5, 23, 9, 0, 0, tzinfo=timezone.utc)
    reset = parse_reset_time("hit your session limit · resets 3pm (UTC)", now)
    assert reset == datetime(2026, 5, 23, 15, 0, 0, tzinfo=timezone.utc)


def test_parse_12pm_is_noon():
    now = datetime(2026, 5, 23, 9, 0, 0, tzinfo=timezone.utc)
    reset = parse_reset_time("session limit resets 12pm (UTC)", now)
    assert reset == datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc)


def test_parse_past_time_rolls_to_next_day():
    # 10:00 maintenant, reset annoncé 9am déjà passé -> demain 09:00.
    now = datetime(2026, 5, 23, 10, 0, 0, tzinfo=timezone.utc)
    reset = parse_reset_time("session limit · resets 9am (UTC)", now)
    assert reset == datetime(2026, 5, 24, 9, 0, 0, tzinfo=timezone.utc)


def test_parse_naive_now_treated_as_utc():
    now = datetime(2026, 5, 23, 21, 9, 0)  # naïf
    reset = parse_reset_time(REAL_MSG, now)
    assert reset == datetime(2026, 5, 24, 0, 30, 0, tzinfo=timezone.utc)


def test_parse_no_match_returns_none():
    now = datetime(2026, 5, 23, 21, 9, 0, tzinfo=timezone.utc)
    assert parse_reset_time("rien à voir", now) is None
    assert parse_reset_time("", now) is None
