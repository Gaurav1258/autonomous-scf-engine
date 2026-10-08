"""
tests/test_math_solver.py
=========================
Rigorous test suite for Module B: Deterministic Working Capital Math Solver.

Verifies:
1. Dynamic Discounting: Sliding scale, exact penny conservation, and FASB APR formulas.
2. Reverse Factoring: ACT/360 money market discounting, bank NIM, and corporate rebate splits.
3. Accounting Conservation: Net Advance + Haircut == Gross Face Value (zero penny drift).
4. Boundary & Error Handling: Negative amounts, zero tenors, over-acceleration errors.
"""

from __future__ import annotations

import pytest

from packages.mcp_server.modules.math_solver import (
    calculate_dynamic_discount,
    simulate_reverse_factoring_spread,
)


class TestDynamicDiscountingMath:
    """Tests for calculate_dynamic_discount() with exact decimal precision."""

    def test_classic_dynamic_discount_30_days_early(self):
        # Invoice $1,000,000, 30 days accelerated out of 60 days tenor, 2.0% base discount
        # Applied discount = 2.0 * (30 / 60) = 1.0000%
        # Discount amount = $10,000.00
        # Net payout = $990,000.00
        # APR = (10,000 / 990,000) * (365 / 30) * 100 = 12.2896%
        result = calculate_dynamic_discount(
            invoice_amount=1_000_000.0,
            days_accelerated=30,
            total_tenor_days=60,
            buyer_hurdle_rate_apr=10.0,
            baseline_discount_pct=2.0,
            day_count_convention="ACT/365",
        )

        assert result.applied_discount_pct == 1.0
        assert result.discount_amount == 10_000.0
        assert result.net_advance_to_supplier == 990_000.0
        assert result.buyer_yield_usd == 10_000.0
        assert abs(result.implied_apr_pct - 12.2896) < 0.01
        assert result.hurdle_rate_exceeded is True
        assert result.annualized_spread_over_hurdle_pct > 0

    def test_accounting_conservation_zero_penny_leakage(self):
        """Net advance to supplier + discount amount must identically equal invoice gross amount."""
        odd_amount = 387_491.83
        result = calculate_dynamic_discount(
            invoice_amount=odd_amount,
            days_accelerated=27,
            total_tenor_days=45,
            buyer_hurdle_rate_apr=12.0,
            baseline_discount_pct=1.85,
        )

        total = round(result.net_advance_to_supplier + result.discount_amount, 2)
        assert total == odd_amount, f"Accounting discrepancy: {total} != {odd_amount}"

    def test_hurdle_rate_not_exceeded(self):
        """When APR falls below hurdle rate, hurdle_rate_exceeded must be False."""
        result = calculate_dynamic_discount(
            invoice_amount=500_000.0,
            days_accelerated=10,
            total_tenor_days=60,
            buyer_hurdle_rate_apr=20.0,  # High hurdle
            baseline_discount_pct=1.0,
        )
        assert result.hurdle_rate_exceeded is False
        assert result.annualized_spread_over_hurdle_pct < 0

    def test_act_360_day_count_option(self):
        """ACT/360 uses basis of 360 instead of 365."""
        res_365 = calculate_dynamic_discount(
            invoice_amount=100_000.0,
            days_accelerated=30,
            total_tenor_days=60,
            buyer_hurdle_rate_apr=5.0,
            day_count_convention="ACT/365",
        )
        res_360 = calculate_dynamic_discount(
            invoice_amount=100_000.0,
            days_accelerated=30,
            total_tenor_days=60,
            buyer_hurdle_rate_apr=5.0,
            day_count_convention="ACT/360",
        )
        # 365 multiplier yields higher APR than 360 multiplier for fixed discount
        assert res_365.implied_apr_pct > res_360.implied_apr_pct


class TestReverseFactoringMath:
    """Tests for simulate_reverse_factoring_spread() with ACT/360 convention."""

    def test_reverse_factoring_standard_flow(self):
        # Invoice $500,000, 45 days accelerated
        # Base benchmark: 5.3% (SOFR)
        # Bank margin: 1.8%
        # Platform fee: 0.2%
        # All-in rate: 5.3 + 1.8 + 0.2 = 7.3000%
        # Supplier haircut = 500,000 * 0.073 * (45 / 360) = $4,562.50
        # Net advance = 500,000 - 4,562.50 = $495,437.50
        # Bank gross income = 500,000 * (0.053 + 0.018) * (45 / 360) = $4,437.50
        # Bank NIM = 500,000 * 0.018 * (45 / 360) = $1,125.00
        # Buyer rebate (30% of NIM) = 1,125.00 * 0.30 = $337.50
        result = simulate_reverse_factoring_spread(
            invoice_amount=500_000.0,
            days_accelerated=45,
            base_benchmark_rate=5.3,
            bank_margin_spread=1.8,
            platform_fee_pct=0.20,
            buyer_rebate_share_pct=0.30,
        )

        assert result.all_in_financing_rate_pct == 7.3
        assert result.supplier_financing_cost_usd == 4562.50
        assert result.net_advance_to_supplier == 495437.50
        assert result.bank_gross_interest_income_usd == 4437.50
        assert result.bank_net_interest_margin_usd == 1125.00
        assert result.buyer_rebate_usd == 337.50
        assert result.day_count_convention == "ACT/360"

    def test_reverse_factoring_accounting_conservation(self):
        """Supplier net advance + haircut must identically equal invoice gross amount."""
        amount = 1_284_920.40
        result = simulate_reverse_factoring_spread(
            invoice_amount=amount,
            days_accelerated=38,
            base_benchmark_rate=5.25,
            bank_margin_spread=2.10,
        )

        total = round(result.net_advance_to_supplier + result.supplier_financing_cost_usd, 2)
        assert total == amount, f"Discrepancy: {total} != {amount}"


class TestMathSolverValidationAndErrors:
    """Tests for edge cases and input validation."""

    def test_negative_or_zero_amount_raises_error(self):
        with pytest.raises(ValueError, match="strictly positive"):
            calculate_dynamic_discount(invoice_amount=-100.0, days_accelerated=10, total_tenor_days=30, buyer_hurdle_rate_apr=5.0)

        with pytest.raises(ValueError, match="strictly positive"):
            simulate_reverse_factoring_spread(invoice_amount=0.0, days_accelerated=10, base_benchmark_rate=5.0, bank_margin_spread=1.5)

    def test_zero_or_negative_days_accelerated_raises_error(self):
        with pytest.raises(ValueError, match="at least 1 day"):
            calculate_dynamic_discount(invoice_amount=1000.0, days_accelerated=0, total_tenor_days=30, buyer_hurdle_rate_apr=5.0)

    def test_acceleration_exceeding_tenor_raises_error(self):
        with pytest.raises(ValueError, match="cannot exceed"):
            calculate_dynamic_discount(invoice_amount=1000.0, days_accelerated=45, total_tenor_days=30, buyer_hurdle_rate_apr=5.0)

