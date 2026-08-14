"""Smoke tests du collecteur sobriété du Control Center (READ-ONLY, dégradation)."""

from __future__ import annotations

import os

import pytest

from control_center.collectors import sobriety


def test_sobriety_summary_shape_and_no_raise(monkeypatch):
    # Sans DSN readonly -> _db_sobriety renvoie error unavailable ; ne lève jamais.
    monkeypatch.delenv("DATABASE_URL_READONLY", raising=False)
    monkeypatch.delenv("ARAC_ALLOW_PAID_AI", raising=False)
    s = sobriety.sobriety_summary()
    assert set(["paid_ai_armed", "env_allow", "paid_ai_enabled", "backlog",
                "claude_running", "curator_service"]).issubset(s.keys())
    assert s["paid_ai_armed"] is False           # fail-closed sans env/flag
    assert s["env_allow"] is False


def test_paid_ai_armed_requires_env_and_flag(monkeypatch):
    # env seul ne suffit pas (le flag DB est unknown/False sans DB) -> non armé.
    monkeypatch.setenv("ARAC_ALLOW_PAID_AI", "1")
    monkeypatch.delenv("DATABASE_URL_READONLY", raising=False)
    s = sobriety.sobriety_summary()
    assert s["env_allow"] is True
    assert s["paid_ai_armed"] is False           # flag absent -> pas armé


def test_claude_running_detection_shape():
    c = sobriety._claude_running()
    assert "total" in c and "curator_active" in c
