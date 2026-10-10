"""
tests/test_cash_forecaster.py
=============================
Unit tests for LangGraph Node 1: Cash Forecaster Agent.
"""

from __future__ import annotations

import pytest

from packages.orchestrator.nodes.cash_forecaster import cash_forecaster_node
from packages.orchestrator.state import (
    FinancingInstrument,
    LiquidityStatus,
    SCFGraphState,
    WorkflowStatus,
)


class TestCashForecasterNode:
    """Verifies treasury decision logic in the Cash Forecaster node."""

    def test_surplus_buyer_recommends_dynamic_discounting(self):
        # Buyer CORP-INFOSYS has $42M min projected cash, invoice is $500k
        state: SCFGraphState = {
            "raw_invoice": {
                "invoice_id": "INV-001",
                "buyer_id": "CORP-INFOSYS",
                "invoice_amount": 500_000.0,
            },
            "cash_forecast": None,
            "risk_profile": None,
            "optimal_structure": None,
            "candidate_curve": None,
            "guardrail_verdict": None,
            "final_payload": None,
            "status": WorkflowStatus.PENDING,
            "audit_trail": ["Workflow initialized"],
            "errors": [],
        }

        update = cash_forecaster_node(state)

        assert "cash_forecast" in update
        assert "audit_trail" in update

        forecast = update["cash_forecast"]
        assert forecast.liquidity_status == LiquidityStatus.SURPLUS
        assert forecast.recommended_instrument == FinancingInstrument.DYNAMIC_DISCOUNTING
        assert forecast.min_projected_cash_60d_usd >= 40_000_000.0
        assert "CashForecaster:" in update["audit_trail"][0]

    def test_deficit_buyer_recommends_reverse_factoring(self):
        # Buyer CORP-MAHINDRA has $7.2M min projected cash (below $10M floor)
        state: SCFGraphState = {
            "raw_invoice": {
                "invoice_id": "INV-002",
                "buyer_id": "CORP-MAHINDRA",
                "invoice_amount": 1_000_000.0,
            },
            "cash_forecast": None,
            "risk_profile": None,
            "optimal_structure": None,
            "candidate_curve": None,
            "guardrail_verdict": None,
            "final_payload": None,
            "status": WorkflowStatus.PENDING,
            "audit_trail": [],
            "errors": [],
        }

        update = cash_forecaster_node(state)
        forecast = update["cash_forecast"]

        assert forecast.liquidity_status == LiquidityStatus.DEFICIT
        assert forecast.recommended_instrument == FinancingInstrument.REVERSE_FACTORING

    def test_tight_buyer_recommends_reverse_factoring_with_open_credit_line(self):
        # Buyer CORP-TATA has $11.5M min projected cash (tight, hovering near $10M floor)
        state: SCFGraphState = {
            "raw_invoice": {
                "invoice_id": "INV-003",
                "buyer_id": "CORP-TATA",
                "invoice_amount": 500_000.0,
            },
            "cash_forecast": None,
            "risk_profile": None,
            "optimal_structure": None,
            "candidate_curve": None,
            "guardrail_verdict": None,
            "final_payload": None,
            "status": WorkflowStatus.PENDING,
            "audit_trail": [],
            "errors": [],
        }

        update = cash_forecaster_node(state)
        forecast = update["cash_forecast"]

        assert forecast.liquidity_status == LiquidityStatus.TIGHT
        assert forecast.recommended_instrument == FinancingInstrument.REVERSE_FACTORING
