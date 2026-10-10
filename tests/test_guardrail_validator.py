"""
tests/test_guardrail_validator.py
=================================
Unit tests for LangGraph Node 4: Guardrail Validator Agent.
"""

from __future__ import annotations

import pytest

from packages.orchestrator.nodes.guardrail_validator import guardrail_validator_node
from packages.orchestrator.state import (
    CapitalStructureOption,
    CashForecastOutput,
    FinancingInstrument,
    LiquidityStatus,
    RiskSentinelOutput,
    SCFGraphState,
    WorkflowStatus,
)


class TestGuardrailValidatorNode:
    """Verifies pre-flight credit limit, concentration cap, and audit signature checks."""

    @pytest.fixture
    def base_state(self) -> SCFGraphState:
        return {
            "raw_invoice": {
                "invoice_id": "INV-GUARD-001",
                "buyer_id": "CORP-INFOSYS",  # Limit $150M, Drawn $45M, Available $105M
                "invoice_amount": 2_500_000.0,
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
                invoice_id="INV-GUARD-001",
                vendor_canonical_id="SUPP-00001",
                vendor_canonical_name="Reliance Industries Ltd.",
                match_confidence=100.0,
                supplier_risk_tier="TIER_1_PRIME",
                is_duplicate=False,
                sanctions_cleared=True,
                idempotency_hash="hash_guardrail",
                summary_markdown="Summary",
            ),
            "optimal_structure": CapitalStructureOption(
                instrument_type=FinancingInstrument.DYNAMIC_DISCOUNTING,
                days_accelerated=30,
                offered_discount_pct=1.25,
                implied_apr_pct=15.2,
                net_advance_to_supplier_usd=2_468_750.0,
                buyer_benefit_usd=31_250.0,
                supplier_acceptance_probability=0.75,
                expected_supplier_acceptance=True,
                reasoning="Optimal offer.",
            ),
            "candidate_curve": None,
            "guardrail_verdict": None,
            "final_payload": None,
            "status": WorkflowStatus.ANALYZING,
            "audit_trail": [],
            "errors": [],
        }

    def test_clean_approval_scenario(self, base_state):
        update = guardrail_validator_node(
            state=base_state,
            existing_supplier_exposure=5_000_000.0,
            concentration_cap_pct=15.0,
        )

        assert "guardrail_verdict" in update
        verdict = update["guardrail_verdict"]

        assert verdict.is_approved is True
        assert len(verdict.breaches) == 0
        assert len(verdict.verification_signature) == 64
        assert update["status"] == WorkflowStatus.AWAITING_TREASURER_APPROVAL
        assert "APPROVED" in update["audit_trail"][0]

    def test_concentration_cap_breach_rejects(self, base_state):
        # Facility is $150M. 15% cap is $22.5M.
        # Existing exposure $21M + Proposed $2.5M = $23.5M (breaches 15% cap!)
        update = guardrail_validator_node(
            state=base_state,
            existing_supplier_exposure=21_000_000.0,
            concentration_cap_pct=15.0,
        )

        verdict = update["guardrail_verdict"]
        assert verdict.is_approved is False
        assert update["status"] == WorkflowStatus.REJECTED_GUARDRAIL
        assert any("CONCENTRATION_CAP_BREACH" in b for b in verdict.breaches)
        assert len(update["errors"]) > 0

    def test_facility_overdraw_rejects(self, base_state):
        # Set proposed amount to $200M, exceeding the $150M total limit
        state_overdraw = dict(base_state)
        state_overdraw["raw_invoice"] = {
            "invoice_id": "INV-OVERDRAW",
            "buyer_id": "CORP-INFOSYS",
            "invoice_amount": 200_000_000.0,
        }

        update = guardrail_validator_node(state_overdraw)
        verdict = update["guardrail_verdict"]

        assert verdict.is_approved is False
        assert update["status"] == WorkflowStatus.REJECTED_GUARDRAIL
        assert any("FACILITY_HEADROOM_BREACH" in b for b in verdict.breaches)

