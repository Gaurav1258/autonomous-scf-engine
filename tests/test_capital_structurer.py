"""
tests/test_capital_structurer.py
================================
Unit tests for LangGraph Node 3: Capital Structurer Agent.
"""

from __future__ import annotations

import pytest

from packages.orchestrator.nodes.capital_structurer import capital_structurer_node
from packages.orchestrator.state import (
    CashForecastOutput,
    FinancingInstrument,
    LiquidityStatus,
    RiskSentinelOutput,
    SCFGraphState,
    WorkflowStatus,
)


class TestCapitalStructurerNode:
    """Verifies hybrid ML + deterministic math offer structuring."""

    @pytest.fixture
    def base_state_surplus(self) -> SCFGraphState:
        """State with surplus liquidity recommending Dynamic Discounting."""
        return {
            "raw_invoice": {
                "invoice_id": "INV-2026-CAP-001",
                "buyer_id": "CORP-INFOSYS",
                "invoice_amount": 500_000.0,
                "payment_net_days": 60,
                "buyer_sector": "IT Services",
            },
            "cash_forecast": CashForecastOutput(
                buyer_id="CORP-INFOSYS",
                current_cash_balance_usd=65_000_000.0,
                min_projected_cash_60d_usd=42_000_000.0,
                minimum_cash_floor_usd=10_000_000.0,
                idle_credit_facility_headroom_usd=105_000_000.0,
                liquidity_status=LiquidityStatus.SURPLUS,
                recommended_instrument=FinancingInstrument.DYNAMIC_DISCOUNTING,
                reasoning="Ample cash cushion.",
            ),
            "risk_profile": RiskSentinelOutput(
                invoice_id="INV-2026-CAP-001",
                vendor_canonical_id="SUPP-00001",
                vendor_canonical_name="Reliance Industries Ltd.",
                match_confidence=100.0,
                supplier_risk_tier="TIER_1_PRIME",
                is_duplicate=False,
                sanctions_cleared=True,
                idempotency_hash="hash123",
                summary_markdown="Summary",
            ),
            "optimal_structure": None,
            "candidate_curve": None,
            "guardrail_verdict": None,
            "final_payload": None,
            "status": WorkflowStatus.ANALYZING,
            "audit_trail": [],
            "errors": [],
        }

    def test_dynamic_discounting_structuring(self, base_state_surplus):
        update = capital_structurer_node(base_state_surplus)

        assert "optimal_structure" in update
        assert "candidate_curve" in update
        assert "audit_trail" in update

        struct = update["optimal_structure"]
        assert struct.instrument_type == FinancingInstrument.DYNAMIC_DISCOUNTING
        assert struct.net_advance_to_supplier_usd > 0
        assert struct.buyer_benefit_usd > 0
        assert struct.net_advance_to_supplier_usd + struct.buyer_benefit_usd == 500_000.0
        assert 0.0 <= struct.supplier_acceptance_probability <= 1.0

        curve = update["candidate_curve"]
        assert len(curve) >= 5
        assert all(0.0 <= pt["acceptance_probability"] <= 1.0 for pt in curve)

    def test_reverse_factoring_structuring(self, base_state_surplus):
        # Change forecast recommendation to Reverse Factoring
        state_rf = dict(base_state_surplus)
        state_rf["cash_forecast"] = CashForecastOutput(
            buyer_id="CORP-TATA",
            current_cash_balance_usd=12_000_000.0,
            min_projected_cash_60d_usd=8_000_000.0,
            minimum_cash_floor_usd=10_000_000.0,
            idle_credit_facility_headroom_usd=80_000_000.0,
            liquidity_status=LiquidityStatus.DEFICIT,
            recommended_instrument=FinancingInstrument.REVERSE_FACTORING,
            reasoning="Cash deficit.",
        )

        update = capital_structurer_node(state_rf)
        struct = update["optimal_structure"]

        assert struct.instrument_type == FinancingInstrument.REVERSE_FACTORING
        assert struct.implied_apr_pct > 0.0
        assert struct.buyer_benefit_usd > 0.0  # Earns bank rebate share
        assert struct.net_advance_to_supplier_usd < 500_000.0

