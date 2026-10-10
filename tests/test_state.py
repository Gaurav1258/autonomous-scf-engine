"""
tests/test_state.py
===================
Tests for the LangGraph SCFGraphState schema, sub-models, and Enums.
"""

from __future__ import annotations

import operator
import pytest
from pydantic import ValidationError

from packages.orchestrator.state import (
    FinancingInstrument,
    LiquidityStatus,
    WorkflowStatus,
    CashForecastOutput,
    RiskSentinelOutput,
    CapitalStructureOption,
    GuardrailValidationOutput,
    FinalExecutionPayload,
    SCFGraphState,
)


class TestStateContracts:
    """Verifies that the LangGraph state models validate fields strictly."""

    def test_cash_forecast_output_validation(self):
        forecast = CashForecastOutput(
            buyer_id="CORP-001",
            current_cash_balance_usd=45_000_000.0,
            min_projected_cash_60d_usd=32_000_000.0,
            minimum_cash_floor_usd=10_000_000.0,
            idle_credit_facility_headroom_usd=60_000_000.0,
            liquidity_status=LiquidityStatus.SURPLUS,
            recommended_instrument=FinancingInstrument.DYNAMIC_DISCOUNTING,
            reasoning="Healthy cash balance throughout the 60-day forecast horizon.",
        )
        assert forecast.liquidity_status == LiquidityStatus.SURPLUS
        assert forecast.recommended_instrument == FinancingInstrument.DYNAMIC_DISCOUNTING

    def test_invalid_liquidity_status_raises_error(self):
        with pytest.raises(ValidationError):
            CashForecastOutput(
                buyer_id="CORP-001",
                current_cash_balance_usd=10_000.0,
                min_projected_cash_60d_usd=5_000.0,
                minimum_cash_floor_usd=1_000.0,
                idle_credit_facility_headroom_usd=50_000.0,
                liquidity_status="UNRECOGNIZED_STATUS",  # type: ignore
                recommended_instrument=FinancingInstrument.DYNAMIC_DISCOUNTING,
                reasoning="test",
            )

    def test_reducer_behavior_simulation(self):
        """Simulates how LangGraph's operator.add reducer accumulates audit logs."""
        state_log = ["Ingested invoice INV-001"]
        node_1_update = ["Cash Forecaster: Buyer has $32M surplus"]
        node_2_update = ["Risk Sentinel: Vendor resolved to Reliance Industries Ltd."]

        # LangGraph applies operator.add under the hood:
        combined = operator.add(state_log, node_1_update)
        combined = operator.add(combined, node_2_update)

        assert len(combined) == 3
        assert combined[0] == "Ingested invoice INV-001"
        assert combined[1] == "Cash Forecaster: Buyer has $32M surplus"
        assert combined[2] == "Risk Sentinel: Vendor resolved to Reliance Industries Ltd."

