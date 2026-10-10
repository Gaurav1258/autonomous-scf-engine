"""
packages/orchestrator/nodes/cash_forecaster.py
==============================================
Node 1: Corporate Cash Forecaster Agent

Role:
Evaluates the corporate buyer's 60-day cash flow projection curve and revolving
bank credit facility headroom.

Microeconomic Decision Rule:
1. If the buyer's 60-day cash trough remains well above their operational floor
   (Floor + $5M buffer), the buyer has surplus idle liquidity.
   -> Recommend DYNAMIC_DISCOUNTING (Self-funded; buyer captures 100% discount).

2. If cash balance is projected to breach or hover near the minimum operational floor,
   the buyer faces seasonal cash constraints.
   -> Recommend REVERSE_FACTORING (Bank-funded via revolving credit line;
      buyer preserves cash and earns bank rebate share).

Output:
Updates state with CashForecastOutput and appends to audit_trail.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from packages.orchestrator.state import (
    CashForecastOutput,
    FinancingInstrument,
    LiquidityStatus,
    SCFGraphState,
)

# Institutional Treasury Policy Constants
DEFAULT_MINIMUM_CASH_FLOOR_USD = 10_000_000.0  # $10M inviolable liquidity cushion
SURPLUS_BUFFER_USD = 5_000_000.0              # $5M comfort buffer above floor

# Default fallback credit facilities for buyers (if external ledger not loaded)
DEFAULT_BUYER_FACILITIES: dict[str, dict[str, float]] = {
    "CORP-INFOSYS": {
        "facility_limit_usd": 150_000_000.0,
        "facility_drawn_usd": 45_000_000.0,
        "current_cash_balance_usd": 65_000_000.0,
        "min_projected_cash_60d_usd": 42_000_000.0,
    },
    "CORP-RELIANCE": {
        "facility_limit_usd": 250_000_000.0,
        "facility_drawn_usd": 110_000_000.0,
        "current_cash_balance_usd": 85_000_000.0,
        "min_projected_cash_60d_usd": 55_000_000.0,
    },
    "CORP-TATA": {
        "facility_limit_usd": 200_000_000.0,
        "facility_drawn_usd": 90_000_000.0,
        "current_cash_balance_usd": 22_000_000.0,
        "min_projected_cash_60d_usd": 11_500_000.0,  # Tight! Near $10M floor
    },
    "CORP-MAHINDRA": {
        "facility_limit_usd": 100_000_000.0,
        "facility_drawn_usd": 60_000_000.0,
        "current_cash_balance_usd": 14_000_000.0,
        "min_projected_cash_60d_usd": 7_200_000.0,   # Deficit! Below $10M floor
    },
    "CORP-DEFAULT": {
        "facility_limit_usd": 50_000_000.0,
        "facility_drawn_usd": 15_000_000.0,
        "current_cash_balance_usd": 30_000_000.0,
        "min_projected_cash_60d_usd": 20_000_000.0,
    },
}


def load_buyer_treasury_profile(buyer_id: str) -> dict[str, float]:
    """
    Fetches real-time treasury telemetry: checks generated synthetic ledger
    if available, otherwise falls back to institutional defaults.
    """
    # 1. Check synthetic facilities JSON if present
    facility_path = Path("data/generated/synthetic_buyers_facilities.json")
    if facility_path.exists():
        try:
            with open(facility_path, "r", encoding="utf-8") as f:
                facilities = json.load(f)
                for fac in facilities:
                    if fac.get("buyer_id") == buyer_id:
                        limit = fac.get("facility_limit_usd", 100_000_000.0)
                        drawn = fac.get("facility_drawn_usd", 40_000_000.0)
                        return {
                            "facility_limit_usd": limit,
                            "facility_drawn_usd": drawn,
                            "current_cash_balance_usd": limit * 0.40,
                            "min_projected_cash_60d_usd": limit * 0.25,
                        }
        except Exception:
            pass

    # 2. Institutional default fallback
    return DEFAULT_BUYER_FACILITIES.get(buyer_id, DEFAULT_BUYER_FACILITIES["CORP-DEFAULT"])


def cash_forecaster_node(state: SCFGraphState) -> dict[str, Any]:
    """
    LangGraph Node Function for Cash Forecasting & Headroom Assessment.

    Args:
        state: The current immutable state dictionary.

    Returns:
        Partial dictionary containing 'cash_forecast' and appended 'audit_trail'.
    """
    raw_invoice = state.get("raw_invoice", {})
    buyer_id = str(raw_invoice.get("buyer_id", "CORP-DEFAULT")).strip()
    invoice_amount = float(raw_invoice.get("invoice_amount", 0.0))

    # Fetch buyer's treasury profile
    profile = load_buyer_treasury_profile(buyer_id)
    current_cash = profile["current_cash_balance_usd"]
    min_projected_60d = profile["min_projected_cash_60d_usd"]
    facility_limit = profile["facility_limit_usd"]
    facility_drawn = profile["facility_drawn_usd"]

    idle_facility_headroom = max(0.0, facility_limit - facility_drawn)
    floor = DEFAULT_MINIMUM_CASH_FLOOR_USD
    safe_surplus_threshold = floor + SURPLUS_BUFFER_USD

    # ── Treasury Microeconomic Decision Logic ────────────────────────────────
    # Can the buyer self-fund without risking an operational cash crunch?
    cash_after_payment = min_projected_60d - invoice_amount

    if cash_after_payment >= safe_surplus_threshold:
        status = LiquidityStatus.SURPLUS
        recommended_instrument = FinancingInstrument.DYNAMIC_DISCOUNTING
        reasoning = (
            f"Buyer {buyer_id} projected 60-day cash trough (${min_projected_60d:,.2f}) "
            f"leaves comfortable headroom above $10M floor after paying ${invoice_amount:,.2f}. "
            f"Recommend self-funded Dynamic Discounting to maximize EBITDA yield."
        )
    elif cash_after_payment >= floor:
        status = LiquidityStatus.TIGHT
        # Cash is hovering near floor; if credit headroom exists, recommend bank funding
        if idle_facility_headroom >= invoice_amount:
            recommended_instrument = FinancingInstrument.REVERSE_FACTORING
            reasoning = (
                f"Buyer {buyer_id} cash is tight (${min_projected_60d:,.2f} trough). "
                f"Paying invoice internally would push cash near the minimum floor (${floor:,.2f}). "
                f"Ample bank headroom available (${idle_facility_headroom:,.2f}). "
                f"Recommend bank-funded Reverse Factoring."
            )
        else:
            recommended_instrument = FinancingInstrument.DYNAMIC_DISCOUNTING
            reasoning = (
                f"Buyer {buyer_id} cash is tight and credit line headroom is exhausted. "
                f"Recommend cautious self-funding Dynamic Discounting."
            )
    else:
        status = LiquidityStatus.DEFICIT
        recommended_instrument = FinancingInstrument.REVERSE_FACTORING
        reasoning = (
            f"Buyer {buyer_id} cash projected to dip below minimum operational floor (${floor:,.2f}) "
            f"at ${min_projected_60d:,.2f}. Internal payment is blocked by treasury policy. "
            f"Recommend bank-funded Reverse Factoring using available credit facility."
        )

    forecast_output = CashForecastOutput(
        buyer_id=buyer_id,
        current_cash_balance_usd=current_cash,
        min_projected_cash_60d_usd=min_projected_60d,
        minimum_cash_floor_usd=floor,
        idle_credit_facility_headroom_usd=idle_facility_headroom,
        liquidity_status=status,
        recommended_instrument=recommended_instrument,
        reasoning=reasoning,
    )

    audit_entry = (
        f"CashForecaster: Evaluated {buyer_id}. Status={status.value}, "
        f"Recommended={recommended_instrument.value}. "
        f"Min60dCash=${min_projected_60d:,.0f}, Headroom=${idle_facility_headroom:,.0f}"
    )

    return {
        "cash_forecast": forecast_output,
        "audit_trail": [audit_entry],
    }

