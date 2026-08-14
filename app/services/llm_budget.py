"""Garde-fou de budget LLM — caps durs + auto-stop + journal de coût (Phase J).

Aucun appel LLM payant massif sans : dry-run, coût estimé, plafond DUR, nombre
maximal d'appels, budget par run, budget journalier, ARRÊT AUTOMATIQUE, journal
de coût, MASQUAGE des secrets. Ce module fournit la mécanique (PURE, testable) ;
les caps s'appliquent sur TOKENS et APPELS (déterministes, sans prix) et,
optionnellement, sur le COÛT si un prix est fourni (jamais inventé : prix=0 par
défaut -> seul le cap tokens/appels protège).

Auto-stop : `charge()` lève `BudgetExceeded` dès qu'un plafond serait franchi.
Le journal de coût (`cost_log_record`) masque TOUJOURS les secrets du prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.sanitize import mask_secrets


class BudgetExceeded(RuntimeError):
    """Levée quand un appel franchirait un plafond (auto-stop)."""


def estimate_cost(in_tokens: int, out_tokens: int,
                  price_per_1k_in: float, price_per_1k_out: float) -> float:
    """Coût estimé en USD. Prix en $/1k tokens (fournis par l'appelant — JAMAIS
    de prix codé en dur/inventé ici)."""
    return round((in_tokens / 1000.0) * price_per_1k_in +
                 (out_tokens / 1000.0) * price_per_1k_out, 6)


@dataclass
class LlmBudget:
    """Budget d'un run LLM. Tous les plafonds sont DURS (auto-stop via charge())."""
    max_calls: int = 30                      # défaut prudent (cf shadow curator <=30)
    max_tokens: int = 200_000
    max_cost_usd: float | None = None        # None -> cap coût inactif
    price_per_1k_in: float = 0.0             # prix fourni par l'appelant (sinon 0)
    price_per_1k_out: float = 0.0
    daily_budget_usd: float | None = None
    spent_today_usd: float = 0.0             # injecté depuis le journal du jour
    _calls: int = field(default=0, init=False)
    _tokens: int = field(default=0, init=False)
    _cost: float = field(default=0.0, init=False)

    # --- introspection ---
    def remaining_calls(self) -> int:
        return max(0, self.max_calls - self._calls)

    def remaining_tokens(self) -> int:
        return max(0, self.max_tokens - self._tokens)

    def spent_cost(self) -> float:
        return round(self._cost, 6)

    def would_exceed(self, in_tokens: int, out_tokens_est: int) -> tuple[bool, str]:
        """Sans débiter : un appel (in+out_est) franchirait-il un plafond ?"""
        if self._calls + 1 > self.max_calls:
            return True, "max_calls"
        if self._tokens + in_tokens + out_tokens_est > self.max_tokens:
            return True, "max_tokens"
        cost = estimate_cost(in_tokens, out_tokens_est, self.price_per_1k_in, self.price_per_1k_out)
        if self.max_cost_usd is not None and self._cost + cost > self.max_cost_usd:
            return True, "max_cost_usd"
        if (self.daily_budget_usd is not None and
                self.spent_today_usd + self._cost + cost > self.daily_budget_usd):
            return True, "daily_budget_usd"
        return False, ""

    def charge(self, in_tokens: int, out_tokens: int) -> dict[str, Any]:
        """Débite l'appel. Lève BudgetExceeded AVANT de débiter si un cap saute
        (auto-stop : on n'enregistre jamais un dépassement)."""
        exceed, reason = self.would_exceed(in_tokens, out_tokens)
        if exceed:
            raise BudgetExceeded(
                f"{reason}: calls={self._calls}/{self.max_calls} "
                f"tokens={self._tokens}/{self.max_tokens} cost={self._cost}")
        cost = estimate_cost(in_tokens, out_tokens, self.price_per_1k_in, self.price_per_1k_out)
        self._calls += 1
        self._tokens += in_tokens + out_tokens
        self._cost = round(self._cost + cost, 6)
        return {"call": self._calls, "in_tokens": in_tokens, "out_tokens": out_tokens,
                "cost_usd": cost, "cumulative_cost_usd": self._cost}

    def report(self) -> dict[str, Any]:
        return {
            "calls": self._calls, "max_calls": self.max_calls,
            "tokens": self._tokens, "max_tokens": self.max_tokens,
            "cost_usd": self.spent_cost(), "max_cost_usd": self.max_cost_usd,
            "daily_budget_usd": self.daily_budget_usd,
            "remaining_calls": self.remaining_calls(),
            "remaining_tokens": self.remaining_tokens(),
        }


def cost_log_record(*, model: str, in_tokens: int, out_tokens: int, cost_usd: float,
                    prompt_preview: str = "", max_preview: int = 200) -> dict[str, Any]:
    """Enregistrement de coût pour le journal. Le `prompt_preview` est TOUJOURS
    masqué (aucun secret dans les logs/atomes/artefacts)."""
    masked = mask_secrets(prompt_preview)[:max_preview] if prompt_preview else ""
    return {
        "event": "llm.cost", "model": model,
        "in_tokens": in_tokens, "out_tokens": out_tokens, "cost_usd": round(cost_usd, 6),
        "prompt_preview_masked": masked,
    }
