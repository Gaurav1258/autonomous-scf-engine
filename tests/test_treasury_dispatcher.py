"""
tests/test_treasury_dispatcher.py
=================================
Unit tests for LangGraph Node 5: Treasury Dispatcher Agent.
"""

from __future__ import annotations

import pytest

from packages.orchestrator.nodes.treasury_dispatcher import treasury_dispatcher_node
from packages.orchestrator.state import (
    CapitalStructureOption,
    CashForecastOutput,
    FinancingInstrument,
    GuardrailValidationOutput,
    LiquidityStatus,
    RiskSentinelOutput,
    SCFGraphState,
    WorkflowStatus,
)


class TestTreasuryDispatcherNode:
    """Verifies 1-click execution payload assembly and safety aborts."""

    @pytest.fixture
    def approved_state(self) -> SCFGraphState:
        return {
            "raw_invoice": {
                "invoice_id": "INV-2026-DISP-001",
                "buyer_id": "CORP-INFOSYS",
                "invoice_amount": 1_000_000.0,
            },
            "cash_forecast": CashForecastOutput(
                buyer_id="CORP-INFOSYS",
                current_cash_balance_usd=65_000_000.0,
                min_projected_cash_60d_usd=42_000_000.0,
                minimum_cash_floor_usd=10_000_000.0,
                idle_credit_facility_headroom_usd=105_000_000.0,
                liquidity_status=LiquidityStatus.SURPLUS,
                recommended_instrument=FinancingInstrument.DYNAMIC_DISCOUNTING,
                reasoning="Surplus cash.",
            ),
            "risk_profile": RiskSentinelOutput(
                invoice_id="INV-2026-DISP-001",
                vendor_canonical_id="SUPP-00001",
                vendor_canonical_name="Reliance Industries Ltd.",
                match_confidence=100.0,
                supplier_risk_tier="TIER_1_PRIME",
                is_duplicate=False,
                sanctions_cleared=True,
                idempotency_hash="hash_disp",
                summary_markdown="Summary",
            ),
            "optimal_structure": CapitalStructureOption(
                instrument_type=FinancingInstrument.DYNAMIC_DISCOUNTING,
                days_accelerated=45,
                offered_discount_pct=1.50,
                implied_apr_pct=12.35,
                net_advance_to_supplier_usd=985_000.0,
                buyer_benefit_usd=15_000.0,
                supplier_acceptance_probability=0.72,
                expected_supplier_acceptance=True,
                reasoning="Optimal discount.",
            ),
            "guardrail_verdict": GuardrailValidationOutput(
                is_approved=True,
                facility_limit_usd=150_000_000.0,
                facility_drawn_after_usd=45_000_000.0,
                facility_headroom_remaining_usd=105_000_000.0,
                supplier_concentration_pct=2.5,
                concentration_cap_pct=15.0,
                breaches=[],
                verification_signature="sig_12345",
            ),
            "candidate_curve": None,
            "final_payload": None,
            "status": WorkflowStatus.AWAITING_TREASURER_APPROVAL,
            "audit_trail": [],
            "errors": [],
        }

    def test_successful_dispatch_creates_complete_payload(self, approved_state):
        update = treasury_dispatcher_node(approved_state)

        assert "final_payload" in update
        assert update["status"] == WorkflowStatus.DISPATCHED

        payload = update["final_payload"]
        assert payload is not None
        assert payload.invoice_id == "INV-2026-DISP-001"
        assert payload.buyer_id == "CORP-INFOSYS"
        assert payload.supplier_canonical_id == "SUPP-00001"
        assert payload.net_payout_to_supplier_usd == 985_000.0
        assert payload.buyer_yield_or_rebate_usd == 15_000.0
        assert payload.instrument == FinancingInstrument.DYNAMIC_DISCOUNTING
        assert len(payload.approval_token) == 32
        assert "offer_id=" in payload.treasurer_action_url
        assert "offer_id=" in payload.supplier_portal_url
        assert "TreasuryDispatcher:" in update["audit_trail"][0]

    def test_bypasses_dispatch_if_sanctioned(self, approved_state):
        sanctioned_state = dict(approved_state)
        sanctioned_state["status"] = WorkflowStatus.REJECTED_SANCTIONS

        update = treasury_dispatcher_node(sanctioned_state)
        assert update["final_payload"] is None
        assert "Bypassed" in update["audit_trail"][0]

    def test_bypasses_dispatch_if_guardrail_failed(self, approved_state):
        rejected_guardrail_state = dict(approved_state)
        rejected_guardrail_state["guardrail_verdict"] = GuardrailValidationOutput(
            is_approved=False,
            facility_limit_usd=150_000_000.0,
            facility_drawn_after_usd=160_000_000.0,
            facility_headroom_remaining_usd=-10_000_000.0,
            supplier_concentration_pct=18.0,
            concentration_cap_pct=15.0,
            breaches=["FACILITY_HEADROOM_BREACH"],
            verification_signature="sig_err",
        )

        update = treasury_dispatcher_node(rejected_guardrail_state)
        assert update["final_payload"] is None
        assert update["status"] == WorkflowStatus.REJECTED_GUARDRAIL
        assert "Dispatch aborted" in update["audit_trail"][0]

