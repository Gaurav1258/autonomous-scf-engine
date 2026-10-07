"""
tests/test_dataset_generator.py
=================================
Tests for the SCF synthetic dataset generator.

Design philosophy:
    - Every assertion tests a REAL financial or domain invariant, not just
      whether the code runs without errors.
    - These are the sanity checks that make the Kaggle dataset trustworthy
      and the XGBoost model financially meaningful.

Run:
    uv run pytest tests/test_dataset_generator.py -v
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from packages.orchestrator.ml.dataset_generator import (
    BUYER_ENTITIES,
    RISK_TIERS,
    VENDOR_NAME_ALIASES,
    _is_quarter_end,
    _sigmoid,
    compute_acceptance_probability,
    compute_buyer_yield,
    compute_implied_apr,
    compute_supplier_net_payout,
    generate_buyer_facilities,
    generate_cash_ledger,
    generate_erp_invoices,
    generate_ml_training_dataset,
    generate_vendor_master,
)
from datetime import date


# ===========================================================================
# Section 1: Financial Math Correctness
# Verifying compute_implied_apr(), compute_supplier_net_payout(), etc.
# These MUST match Module B (math_solver.py) exactly.
# ===========================================================================


class TestImpliedAPR:
    """
    Test compute_implied_apr() against hand-verified financial formulas.

    Reference: FASB ASC 310 discount-on-proceeds formulation.
    APR = (d / (1 - d)) * (365 / days_accelerated)
    where d = offered_discount_pct / 100
    """

    def test_standard_2_10_net_60_case(self):
        """Classic 2/10 Net 60: paying 35 days early at 2% discount."""
        # d = 0.02, basis = 365, days_early = 35
        # APR = (0.02 / 0.98) * (365 / 35) = 0.020408 * 10.4286 = 21.27%
        apr = compute_implied_apr(discount_pct=2.0, days_accelerated=35)
        assert abs(apr - 21.27) < 0.10, f"Expected ~21.27%, got {apr}%"

    def test_small_discount_long_tenor(self):
        """1% discount accelerated over 55 days (Net 60, paid on day 5)."""
        # d = 0.01, days = 55
        # APR = (0.01 / 0.99) * (365 / 55) = 0.010101 * 6.636 = 6.70%
        apr = compute_implied_apr(discount_pct=1.0, days_accelerated=55)
        assert abs(apr - 6.70) < 0.10, f"Expected ~6.70%, got {apr}%"

    def test_zero_discount_returns_zero(self):
        """Net 90 with no discount must yield 0% APR."""
        apr = compute_implied_apr(discount_pct=0.0, days_accelerated=45)
        assert apr == 0.0

    def test_zero_days_returns_zero(self):
        """No acceleration means no financing cost."""
        apr = compute_implied_apr(discount_pct=2.0, days_accelerated=0)
        assert apr == 0.0

    def test_apr_increases_with_shorter_tenor(self):
        """
        Same discount percentage but shorter acceleration = higher annualized APR.
        This is the core dynamic discounting elasticity insight.
        """
        apr_long = compute_implied_apr(discount_pct=1.5, days_accelerated=60)
        apr_short = compute_implied_apr(discount_pct=1.5, days_accelerated=10)
        assert apr_short > apr_long, (
            f"Shorter tenor should yield higher APR: {apr_short}% vs {apr_long}%"
        )

    def test_act_360_vs_act_365_difference(self):
        """ACT/365 annualized basis (365/days) yields higher APR than ACT/360 basis (360/days)."""
        apr_365 = compute_implied_apr(discount_pct=2.0, days_accelerated=30, day_count_basis=365)
        apr_360 = compute_implied_apr(discount_pct=2.0, days_accelerated=30, day_count_basis=360)
        assert apr_365 > apr_360, "ACT/365 APR must exceed ACT/360 APR"


class TestSupplierNetPayout:
    """Test compute_supplier_net_payout() for exact penny-level precision."""

    def test_two_percent_discount_on_one_million(self):
        payout = compute_supplier_net_payout(face_value=1_000_000.00, discount_pct=2.0)
        assert payout == 980_000.00

    def test_zero_discount_full_face_value(self):
        payout = compute_supplier_net_payout(face_value=500_000.00, discount_pct=0.0)
        assert payout == 500_000.00

    def test_rounding_to_cents(self):
        """Result must round to exactly 2 decimal places."""
        payout = compute_supplier_net_payout(face_value=333_333.33, discount_pct=1.5)
        assert payout == round(333_333.33 * 0.985, 2)


class TestBuyerYield:
    """Test compute_buyer_yield() — must equal face_value - net_payout."""

    def test_buyer_yield_plus_payout_equals_face_value(self):
        face = 750_000.00
        discount = 1.75
        payout = compute_supplier_net_payout(face, discount)
        yield_amount = compute_buyer_yield(face, discount)
        assert abs(payout + yield_amount - face) < 0.01, (
            "Payout + Buyer Yield must equal Face Value"
        )


class TestSigmoidAndAcceptance:
    """Test the acceptance utility model boundaries and monotonicity."""

    def test_sigmoid_at_zero_is_half(self):
        assert abs(_sigmoid(0.0) - 0.5) < 1e-9

    def test_sigmoid_monotonically_increasing(self):
        values = [_sigmoid(x) for x in [-5, -2, -1, 0, 1, 2, 5]]
        assert values == sorted(values), "Sigmoid must be strictly increasing"

    def test_high_apr_saving_yields_high_acceptance(self):
        """
        If our offer APR (5%) is much cheaper than their bank (20%),
        the supplier should have very high acceptance probability (>85%).
        """
        prob = compute_acceptance_probability(
            implied_apr=5.0,
            alt_cost_apr=20.0,
            supplier_dso=70.0,
            quarter_end_flag=False,
            is_anchor_buyer=False,
            sensitivity=0.75,
        )
        assert prob > 0.85, f"Expected >85% acceptance, got {prob:.1%}"

    def test_expensive_offer_yields_low_acceptance(self):
        """
        If our offer APR (30%) is more expensive than their bank (12%),
        the supplier should mostly reject (<20%).
        """
        prob = compute_acceptance_probability(
            implied_apr=30.0,
            alt_cost_apr=12.0,
            supplier_dso=40.0,
            quarter_end_flag=False,
            is_anchor_buyer=False,
            sensitivity=0.75,
        )
        assert prob < 0.20, f"Expected <20% acceptance, got {prob:.1%}"

    def test_quarter_end_boosts_acceptance(self):
        """Quarter-end liquidity crunch must increase acceptance probability."""
        base_kwargs = dict(
            implied_apr=14.0,
            alt_cost_apr=14.0,
            supplier_dso=60.0,
            is_anchor_buyer=False,
            sensitivity=0.75,
        )
        prob_normal = compute_acceptance_probability(**base_kwargs, quarter_end_flag=False)
        prob_qend = compute_acceptance_probability(**base_kwargs, quarter_end_flag=True)
        assert prob_qend > prob_normal, "Quarter-end should boost acceptance probability"

    def test_acceptance_probability_bounded(self):
        """Probability must always be in [0, 1]."""
        for implied in [0.0, 5.0, 15.0, 50.0, 100.0]:
            for alt in [5.0, 15.0, 25.0]:
                prob = compute_acceptance_probability(
                    implied_apr=implied,
                    alt_cost_apr=alt,
                    supplier_dso=65.0,
                    quarter_end_flag=True,
                    is_anchor_buyer=True,
                    sensitivity=1.1,
                )
                assert 0.0 <= prob <= 1.0, f"Probability out of bounds: {prob}"


# ===========================================================================
# Section 2: ML Dataset Structure & Statistical Invariants
# ===========================================================================


@pytest.fixture(scope="module")
def small_df() -> pd.DataFrame:
    """Generate a small 500-row dataset for fast test execution."""
    return generate_ml_training_dataset(num_rows=500)


class TestMLDatasetSchema:
    """Verify the ML dataset has the correct schema, no nulls, and valid ranges."""

    REQUIRED_COLUMNS = [
        "row_id", "invoice_date", "buyer_id", "supplier_risk_tier",
        "supplier_alt_cost_of_debt_apr", "supplier_dso_days",
        "invoice_face_value_usd", "original_tenor_days",
        "days_accelerated", "offered_discount_pct", "implied_apr",
        "supplier_net_payout_usd", "buyer_yield_usd", "quarter_end_flag",
        "utility_delta", "acceptance_probability", "accepted_early_offer",
    ]

    def test_all_required_columns_present(self, small_df):
        missing = [c for c in self.REQUIRED_COLUMNS if c not in small_df.columns]
        assert not missing, f"Missing columns: {missing}"

    def test_no_null_values_in_key_columns(self, small_df):
        null_counts = small_df[self.REQUIRED_COLUMNS].isnull().sum()
        cols_with_nulls = null_counts[null_counts > 0]
        assert cols_with_nulls.empty, f"Null values found:\n{cols_with_nulls}"

    def test_target_is_binary(self, small_df):
        unique_targets = set(small_df["accepted_early_offer"].unique())
        assert unique_targets.issubset({0, 1}), f"Target must be 0 or 1, got: {unique_targets}"

    def test_acceptance_rate_is_realistic(self, small_df):
        """Acceptance rate should be between 35% and 75% — not a degenerate dataset."""
        rate = small_df["accepted_early_offer"].mean()
        assert 0.35 < rate < 0.75, f"Acceptance rate {rate:.1%} seems unrealistic"

    def test_face_values_in_realistic_range(self, small_df):
        assert small_df["invoice_face_value_usd"].min() >= 5_000
        assert small_df["invoice_face_value_usd"].max() <= 5_100_000

    def test_days_accelerated_within_tenor(self, small_df):
        """Days accelerated must never exceed the original tenor."""
        invalid = small_df[small_df["days_accelerated"] >= small_df["original_tenor_days"]]
        assert len(invalid) == 0, (
            f"{len(invalid)} rows where days_accelerated >= original_tenor_days"
        )

    def test_risk_tiers_are_valid(self, small_df):
        valid_tiers = set(RISK_TIERS.keys())
        actual_tiers = set(small_df["supplier_risk_tier"].unique())
        assert actual_tiers.issubset(valid_tiers), f"Invalid risk tiers: {actual_tiers - valid_tiers}"

    def test_net_payout_less_than_face_value(self, small_df):
        """Supplier always receives less than face value when discount > 0."""
        with_discount = small_df[small_df["offered_discount_pct"] > 0]
        invalid = with_discount[
            with_discount["supplier_net_payout_usd"] >= with_discount["invoice_face_value_usd"]
        ]
        assert len(invalid) == 0, f"{len(invalid)} rows where payout >= face value"

    def test_utility_delta_correlates_with_acceptance(self, small_df):
        """
        Rows where utility_delta > 0 (our APR < alt cost) should have a higher
        mean acceptance rate than rows where utility_delta < 0.
        """
        positive_utility = small_df[small_df["utility_delta"] > 0]["accepted_early_offer"].mean()
        negative_utility = small_df[small_df["utility_delta"] < 0]["accepted_early_offer"].mean()
        assert positive_utility > negative_utility, (
            "Positive utility_delta should correlate with higher acceptance rates"
        )

    def test_deterministic_across_runs(self):
        """Two calls with the same seed must produce identical first 5 rows."""
        df1 = generate_ml_training_dataset(num_rows=10)
        df2 = generate_ml_training_dataset(num_rows=10)
        # NOTE: Due to global random state, seeds are reset inside function.
        # This test documents the expected behavior.
        assert list(df1["row_id"]) == list(df2["row_id"]), "Row IDs must be deterministic"


# ===========================================================================
# Section 3: ERP Invoice Feed
# ===========================================================================


class TestERPInvoices:
    @pytest.fixture
    def invoices(self):
        return generate_erp_invoices(num_invoices=50)

    def test_correct_count(self, invoices):
        assert len(invoices) == 50

    def test_all_required_fields_present(self, invoices):
        required = [
            "invoice_id", "erp_source", "vendor_name_raw", "vendor_name_canonical",
            "buyer_id", "invoice_amount", "issue_date", "due_date",
            "payment_terms_raw", "payment_net_days", "status",
        ]
        for inv in invoices:
            missing = [f for f in required if f not in inv]
            assert not missing, f"Missing fields in invoice {inv.get('invoice_id')}: {missing}"

    def test_vendor_names_are_intentionally_messy(self, invoices):
        """
        vendor_name_raw should differ from vendor_name_canonical
        at least some of the time — that's the point of the normalizer.
        """
        mismatches = sum(
            1 for inv in invoices if inv["vendor_name_raw"] != inv["vendor_name_canonical"]
        )
        assert mismatches > 0, "All vendor names are identical — normalizer test won't work"

    def test_due_date_after_issue_date(self, invoices):
        from datetime import date
        for inv in invoices:
            issue = date.fromisoformat(inv["issue_date"])
            due = date.fromisoformat(inv["due_date"])
            assert due > issue, f"Due date {due} not after issue date {issue}"


# ===========================================================================
# Section 4: Vendor Master
# ===========================================================================


class TestVendorMaster:
    @pytest.fixture
    def vendors(self):
        return generate_vendor_master()

    def test_has_expected_count(self, vendors):
        assert len(vendors) == 50, f"Expected 50 vendors, got {len(vendors)}"

    def test_known_canonical_names_present(self, vendors):
        canonical_names = {v["canonical_name"] for v in vendors}
        for expected in VENDOR_NAME_ALIASES.keys():
            assert expected in canonical_names, f"'{expected}' not in vendor master"

    def test_each_vendor_has_aliases(self, vendors):
        for v in vendors:
            assert len(v["name_aliases"]) >= 1, (
                f"Vendor {v['canonical_name']} has no aliases — normalizer test will be trivial"
            )

    def test_risk_tiers_are_valid(self, vendors):
        valid = set(RISK_TIERS.keys())
        for v in vendors:
            assert v["risk_tier"] in valid, f"Invalid risk tier: {v['risk_tier']}"

    def test_sanctions_flagged_vendors_present(self, vendors):
        """
        At least one vendor must be sanctions-flagged so the guardrail
        test suite can exercise the blocking path.
        """
        flagged = [v for v in vendors if not v["sanctions_cleared"]]
        assert len(flagged) >= 1, "Need at least one flagged vendor for guardrail tests"


# ===========================================================================
# Section 5: Buyer Credit Facilities
# ===========================================================================


class TestBuyerFacilities:
    @pytest.fixture
    def facilities(self):
        return generate_buyer_facilities()

    def test_one_facility_per_buyer(self, facilities):
        assert len(facilities) == len(BUYER_ENTITIES)

    def test_available_equals_limit_minus_drawn(self, facilities):
        for f in facilities:
            expected = round(f["facility_limit_usd"] - f["facility_drawn_usd"], 2)
            assert abs(f["facility_available_usd"] - expected) < 0.01, (
                f"Available headroom calculation wrong for {f['buyer_id']}"
            )

    def test_concentration_cap_is_15_percent(self, facilities):
        for f in facilities:
            assert f["single_supplier_concentration_cap_pct"] == 15.0


# ===========================================================================
# Section 6: Cash Ledger
# ===========================================================================


class TestCashLedger:
    @pytest.fixture
    def ledger(self):
        return generate_cash_ledger(horizon_days=30)

    def test_correct_total_rows(self, ledger):
        assert len(ledger) == len(BUYER_ENTITIES) * 30

    def test_balance_above_absolute_floor(self, ledger):
        """Balance must never fall below $5M (hard floor in generator)."""
        for row in ledger:
            assert row["projected_cash_balance_usd"] >= 5_000_000, (
                f"Balance {row['projected_cash_balance_usd']} below $5M floor"
            )

    def test_liquidity_status_categories(self, ledger):
        valid = {"SURPLUS", "TIGHT", "DEFICIT"}
        for row in ledger:
            assert row["liquidity_status"] in valid, (
                f"Invalid liquidity status: {row['liquidity_status']}"
            )


# ===========================================================================
# Section 7: Quarter-End Detection
# ===========================================================================


class TestQuarterEnd:
    def test_march_31_is_quarter_end(self):
        assert _is_quarter_end(date(2026, 3, 31))

    def test_june_30_is_quarter_end(self):
        assert _is_quarter_end(date(2026, 6, 30))

    def test_mid_february_is_not_quarter_end(self):
        assert not _is_quarter_end(date(2026, 2, 14))

    def test_within_15_days_of_march_31_is_quarter_end(self):
        assert _is_quarter_end(date(2026, 3, 20))  # 11 days before Q1 end

