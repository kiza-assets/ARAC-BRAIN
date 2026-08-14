"""Garde-fou budget LLM — tests PURS (Phase J)."""

from __future__ import annotations

import pytest

from app.services import llm_budget as lb


def test_estimate_cost():
    assert lb.estimate_cost(1000, 1000, 0.01, 0.03) == pytest.approx(0.04)
    assert lb.estimate_cost(0, 0, 1.0, 1.0) == 0.0


def test_charge_increments_and_reports():
    b = lb.LlmBudget(max_calls=5, max_tokens=10000)
    b.charge(100, 50)
    b.charge(200, 100)
    rep = b.report()
    assert rep["calls"] == 2
    assert rep["tokens"] == 450
    assert rep["remaining_calls"] == 3


def test_auto_stop_on_max_calls():
    b = lb.LlmBudget(max_calls=1, max_tokens=10_000)
    b.charge(10, 10)
    with pytest.raises(lb.BudgetExceeded) as e:
        b.charge(10, 10)
    assert "max_calls" in str(e.value)


def test_auto_stop_on_max_tokens():
    b = lb.LlmBudget(max_calls=100, max_tokens=100)
    with pytest.raises(lb.BudgetExceeded) as e:
        b.charge(80, 80)               # 160 > 100
    assert "max_tokens" in str(e.value)
    assert b.report()["calls"] == 0    # rien débité (auto-stop AVANT)


def test_auto_stop_on_cost_cap():
    b = lb.LlmBudget(max_calls=100, max_tokens=10_000_000, max_cost_usd=0.01,
                     price_per_1k_in=1.0, price_per_1k_out=1.0)
    with pytest.raises(lb.BudgetExceeded) as e:
        b.charge(10_000, 0)            # 10$ >> 0.01$
    assert "max_cost_usd" in str(e.value)


def test_auto_stop_on_daily_budget():
    b = lb.LlmBudget(max_calls=100, max_tokens=10_000_000, daily_budget_usd=1.0,
                     spent_today_usd=0.99, price_per_1k_in=1.0, price_per_1k_out=0.0)
    with pytest.raises(lb.BudgetExceeded) as e:
        b.charge(100, 0)               # +0.10$ -> 1.09 > 1.0
    assert "daily_budget_usd" in str(e.value)


def test_would_exceed_does_not_charge():
    b = lb.LlmBudget(max_calls=1, max_tokens=1000)
    exceed, reason = b.would_exceed(2000, 0)
    assert exceed is True and reason == "max_tokens"
    assert b.report()["calls"] == 0    # would_exceed ne débite pas


def test_cost_log_masks_secrets():
    rec = lb.cost_log_record(
        model="claude-opus-4-8", in_tokens=10, out_tokens=5, cost_usd=0.0,
        prompt_preview="voici une clé sk-ant-abcdef0123456789abcdef à ne pas logger",
    )
    assert "sk-ant-" not in rec["prompt_preview_masked"]
    assert "REDACTED" in rec["prompt_preview_masked"]
    assert rec["event"] == "llm.cost"


def test_default_cap_is_30_calls():
    # défaut prudent aligné sur le shadow curator (<=30 atomes).
    assert lb.LlmBudget().max_calls == 30
