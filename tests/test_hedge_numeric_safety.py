from __future__ import annotations

import math
import unittest
from types import SimpleNamespace

from src.hedge_src.agents.phil_fisher import analyze_margins_stability
from src.hedge_src.agents.stanley_druckenmiller import analyze_risk_reward
from src.hedge_src.agents.valuation import (
    calculate_ev_ebitda_value,
    calculate_fcf_volatility,
)
from src.hedge_src.tools.api import _safe_float
from src.hedge_src.utils.numeric import finite_float_or_none, finite_float_values


class HedgeNumericSafetyTests(unittest.TestCase):
    def test_finite_float_values_drops_invalid_numbers(self) -> None:
        values = finite_float_values([1, "2.5", None, float("nan"), float("inf"), "bad"])

        self.assertEqual(values, [1.0, 2.5])

    def test_finite_float_or_none_rejects_nonfinite_values(self) -> None:
        self.assertIsNone(finite_float_or_none(float("nan")))
        self.assertIsNone(finite_float_or_none(float("inf")))
        self.assertIsNone(_safe_float(float("-inf")))
        self.assertEqual(finite_float_or_none("3.25"), 3.25)

    def test_margin_stability_ignores_nan_operating_margin(self) -> None:
        items = [
            SimpleNamespace(operating_margin=0.12, gross_margin=0.35),
            SimpleNamespace(operating_margin=float("nan"), gross_margin=0.34),
            SimpleNamespace(operating_margin=0.13, gross_margin=0.36),
        ]

        result = analyze_margins_stability(items)

        self.assertTrue(math.isfinite(result["score"]))
        self.assertIn("Operating margin", result["details"])

    def test_fcf_volatility_ignores_nan_and_infinite_values(self) -> None:
        result = calculate_fcf_volatility([100.0, float("nan"), 120.0, float("inf"), -5.0])

        self.assertTrue(math.isfinite(result))

    def test_risk_reward_ignores_invalid_prices(self) -> None:
        line_items = [SimpleNamespace(total_debt=10.0, shareholders_equity=100.0)]
        prices = [
            SimpleNamespace(time=f"2026-01-{day:02d}", close=100.0 + day)
            for day in range(1, 13)
        ]
        prices[3].close = float("nan")
        prices[7].close = float("inf")

        result = analyze_risk_reward(line_items, prices)

        self.assertTrue(math.isfinite(result["score"]))
        self.assertIn("volatility", result["details"].lower())

    def test_ev_ebitda_valuation_ignores_invalid_multiples(self) -> None:
        metrics = [
            SimpleNamespace(
                enterprise_value=1000.0,
                enterprise_value_to_ebitda_ratio=10.0,
                market_cap=800.0,
            ),
            SimpleNamespace(
                enterprise_value=900.0,
                enterprise_value_to_ebitda_ratio=float("nan"),
                market_cap=700.0,
            ),
            SimpleNamespace(
                enterprise_value=1100.0,
                enterprise_value_to_ebitda_ratio=12.0,
                market_cap=850.0,
            ),
        ]

        self.assertEqual(calculate_ev_ebitda_value(metrics), 900.0)


if __name__ == "__main__":
    unittest.main()
