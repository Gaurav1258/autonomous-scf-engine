"""
packages/orchestrator/nodes/capital_structurer.py
=================================================
Node 3: Quantitative Capital Structurer Agent

Role:
Structures the optimal win-win financing offer by fusing:
1. Deterministic Financial Math (Module B: FastMCP Math Solver)
2. Machine Learning Price Elasticity (XGBoost Supplier Acceptance Model)

Mechanism:
1. Reads recommended instrument from Node 1 (Dynamic Discounting vs Reverse Factoring).
2. Generates a candidate discount curve (0.50% to 2.50%).
3. Evaluates supplier acceptance probability P(accept) across the curve using the
   trained XGBoost model.
4. Identifies the optimal trade finance spread that maximizes corporate buyer yield
   while maintaining high supplier take-up probability (target >= 65%).
5. Executes audit-grade math for exact penny advances, implied APRs, and bank margins.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from packages.mcp_server.modules.math_solver import (
    calculate_dynamic_discount,
    simulate_reverse_factoring_spread,
)
from packages.orchestrator.ml.acceptance_model import (
    MODEL_FILE,
    SupplierAcceptanceModel,
)
from packages.orchestrator.state import (
    CapitalStructureOption,
    FinancingInstrument,
    SCFGraphState,
)

# Benchmark rate defaults (SOFR + Corporate hurdle rates)
DEFAULT_BUYER_HURDLE_APR = 9.50      # Corporate buyer's cost of capital / hurdle rate
DEFAULT_BENCHMARK_RATE_APR = 5.30    # 1-Month SOFR benchmark rate
DEFAULT_BANK_MARGIN_SPREAD = 1.80    # Bank credit facility margin spread
TARGET_ACCEPTANCE_THRESHOLD = 0.65   # Target supplier take-up probability (65%+)

# Lazy global model holder
_acceptance_model_instance: Optional[SupplierAcceptanceModel] = None


def get_acceptance_model() -> SupplierAcceptanceModel:
    """Returns singleton instance of the trained XGBoost model."""
    global _acceptance_model_instance
    if _acceptance_model_instance is None:
        if MODEL_FILE.exists():
            _acceptance_model_instance = SupplierAcceptanceModel(model_path=MODEL_FILE)
        else:
            # Fall back to self-healing instance
            _acceptance_model_instance = SupplierAcceptanceModel(model_path=MODEL_FILE)
    return _acceptance_model_instance


def capital_structurer_node(state: SCFGraphState) -> dict[str, Any]:
    """
    LangGraph Node Function for Optimal Capital Structuring.

    Args:
        state: The current immutable state dictionary.

    Returns:
        Partial dictionary updating 'optimal_structure', 'candidate_curve', and 'audit_trail'.
    """
    raw_invoice = state.get("raw_invoice", {})
    cash_forecast = state.get("cash_forecast")
    risk_profile = state.get("risk_profile")

    # Ingestion values
    invoice_amount = float(raw_invoice.get("invoice_amount", 100_000.0))
    net_days = int(raw_invoice.get("payment_net_days", 60))

    # Days accelerated: advance payment to Day 10 of invoice lifecycle
    days_accelerated = max(10, net_days - 10)

    # Determine instrument from Cash Forecaster recommendation
    if cash_forecast and cash_forecast.recommended_instrument == FinancingInstrument.REVERSE_FACTORING:
        instrument = FinancingInstrument.REVERSE_FACTORING
    else:
        instrument = FinancingInstrument.DYNAMIC_DISCOUNTING

    # Telemetry for ML acceptance prediction
    tier_name = risk_profile.supplier_risk_tier if risk_profile else "TIER_2_STABLE"
    sector = risk_profile.supplier_sector if hasattr(risk_profile, "supplier_sector") else "Manufacturing"
    buyer_sector = raw_invoice.get("buyer_sector", "Conglomerate")

    # Supplier proxy features based on tier
    tier_alt_cost = 9.5 if "1" in tier_name else (14.0 if "2" in tier_name else 21.0)
    tier_dso = 45.0 if "1" in tier_name else (65.0 if "2" in tier_name else 85.0)

    base_ml_features = {
        "supplier_risk_tier": tier_name,
        "supplier_sector": sector,
        "buyer_sector": buyer_sector,
        "instrument_type": instrument.value,
        "supplier_alt_cost_of_debt_apr": tier_alt_cost,
        "supplier_dso_days": tier_dso,
        "supplier_historical_acceptance_rate": 0.55,
        "is_anchor_buyer": 1,
        "days_since_last_trade": 20,
        "invoice_face_value_usd": invoice_amount,
        "original_tenor_days": net_days,
        "days_accelerated": days_accelerated,
        "quarter_end_flag": 0,
    }

    # ── 1. Query XGBoost Acceptance Elasticity Curve ─────────────────────────
    candidate_discount_rates = [0.50, 0.75, 1.00, 1.25, 1.50, 1.75, 2.00, 2.25]
    model = get_acceptance_model()

    if model.model is not None:
        elasticity_curve = model.predict_acceptance_curve(
            base_features=base_ml_features,
            discount_rates=candidate_discount_rates,
        )
    else:
        # Fallback heuristic if model file is uninitialized
        elasticity_curve = [
            {
                "discount_pct": r,
                "implied_apr": round((r / 100) * (365 / days_accelerated) * 100, 2),
                "acceptance_probability": max(0.20, round(0.90 - (r * 0.25), 3)),
                "expected_acceptance": True,
            }
            for r in candidate_discount_rates
        ]

    # ── 2. Select Optimal Win-Win Financing Point ────────────────────────────
    # Find candidate rate with highest buyer return subject to P(accept) >= TARGET_ACCEPTANCE_THRESHOLD
    qualified_options = [
        pt for pt in elasticity_curve if pt["acceptance_probability"] >= TARGET_ACCEPTANCE_THRESHOLD
    ]

    if qualified_options:
        # Pick the highest discount among qualified (maximizes buyer yield while supplier accepts)
        chosen_point = max(qualified_options, key=lambda pt: pt["discount_pct"])
    else:
        # If none hit threshold, pick the most competitive rate that maximizes acceptance
        chosen_point = max(elasticity_curve, key=lambda pt: pt["acceptance_probability"])

    chosen_discount_pct = float(chosen_point["discount_pct"])
    acceptance_prob = float(chosen_point["acceptance_probability"])

    # ── 3. Deterministic Working Capital Math ────────────────────────────────
    if instrument == FinancingInstrument.DYNAMIC_DISCOUNTING:
        math_result = calculate_dynamic_discount(
            invoice_amount=invoice_amount,
            days_accelerated=days_accelerated,
            total_tenor_days=net_days,
            buyer_hurdle_rate_apr=DEFAULT_BUYER_HURDLE_APR,
            baseline_discount_pct=chosen_discount_pct * (net_days / days_accelerated),
            day_count_convention="ACT/365",
        )
        net_payout = math_result.net_advance_to_supplier
        buyer_benefit = math_result.buyer_yield_usd
        implied_apr = math_result.implied_apr_pct
        reasoning = (
            f"Structured self-funded Dynamic Discounting offer at {chosen_discount_pct:.2f}% discount "
            f"for {days_accelerated} days acceleration. Implied APR is {implied_apr:.2f}%. "
            f"Buyer earns ${buyer_benefit:,.2f} yield. XGBoost model predicts {acceptance_prob:.1%} "
            f"supplier acceptance probability."
        )
    else:
        # Reverse Factoring (Bank Funded)
        rf_result = simulate_reverse_factoring_spread(
            invoice_amount=invoice_amount,
            days_accelerated=days_accelerated,
            base_benchmark_rate=DEFAULT_BENCHMARK_RATE_APR,
            bank_margin_spread=DEFAULT_BANK_MARGIN_SPREAD,
            platform_fee_pct=0.20,
            buyer_rebate_share_pct=0.30,
        )
        net_payout = rf_result.net_advance_to_supplier
        buyer_benefit = rf_result.buyer_rebate_usd
        implied_apr = rf_result.all_in_financing_rate_pct
        reasoning = (
            f"Structured bank-funded Reverse Factoring facility at {implied_apr:.2f}% all-in APR "
            f"(SOFR {DEFAULT_BENCHMARK_RATE_APR:.2f}% + margin {DEFAULT_BANK_MARGIN_SPREAD:.2f}%). "
            f"Supplier receives ${net_payout:,.2f}. Corporate buyer earns ${buyer_benefit:,.2f} "
            f"bank rebate share. Supplier acceptance probability is {acceptance_prob:.1%}."
        )

    optimal_option = CapitalStructureOption(
        instrument_type=instrument,
        days_accelerated=days_accelerated,
        offered_discount_pct=chosen_discount_pct,
        implied_apr_pct=implied_apr,
        net_advance_to_supplier_usd=net_payout,
        buyer_benefit_usd=buyer_benefit,
        supplier_acceptance_probability=acceptance_prob,
        expected_supplier_acceptance=bool(acceptance_prob >= 0.50),
        reasoning=reasoning,
    )

    audit_entry = (
        f"CapitalStructurer: Selected {instrument.value}. "
        f"Discount={chosen_discount_pct:.2f}%, APR={implied_apr:.2f}%, "
        f"Advance=${net_payout:,.2f}, BuyerBenefit=${buyer_benefit:,.2f}, "
        f"P(Accept)={acceptance_prob:.1%}"
    )

    return {
        "optimal_structure": optimal_option,
        "candidate_curve": elasticity_curve,
        "audit_trail": [audit_entry],
    }

