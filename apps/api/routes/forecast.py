"""
apps/api/routes/forecast.py
===========================
Cash flow trajectory and revolving credit line headroom visualizer data
for the Next.js CashFlowChart component.
"""

from __future__ import annotations

import datetime
import math
from typing import Any, Optional
from fastapi import APIRouter, Query

from packages.orchestrator.nodes.cash_forecaster import (
    DEFAULT_BUYER_FACILITIES,
    DEFAULT_MINIMUM_CASH_FLOOR_USD,
    load_buyer_treasury_profile,
)

router = APIRouter(prefix="/api/forecast", tags=["Cash Forecasting"])


def project_daily_cash_curve(
    baseline_cash: float,
    days: int = 60,
    buyer_id: str = "CORP-INFOSYS",
) -> list[dict[str, float]]:
    """
    Synthesizes a realistic daily cash trajectory with working capital seasonality:
    bi-weekly receivable collections, periodic payroll outflows, and seasonal vendor settlements.
    """
    points: list[dict[str, float]] = []
    current_cash = baseline_cash
    seed_offset = sum(ord(c) for c in buyer_id) % 10

    for d in range(1, days + 1):
        # Cyclical daily inflows (e.g., customer receivable collections peak every 14 days)
        inflow = (
            (baseline_cash * 0.035) * (1.0 + 0.4 * math.sin((d + seed_offset) * 2 * math.pi / 14))
            + (baseline_cash * 0.01)
        )

        # Outflows (payroll on days 1st and 15th, daily operational expenses)
        payroll_spike = baseline_cash * 0.08 if (d % 15 == 0) else 0.0
        outflow = (baseline_cash * 0.032) + payroll_spike

        net_flow = inflow - outflow
        current_cash = max(0.0, current_cash + net_flow)

        points.append({
            "day_offset": d,
            "projected_cash_usd": current_cash,
            "inflows_usd": inflow,
            "outflows_usd": outflow,
            "net_flow_usd": net_flow,
        })

    return points


@router.get("/cash-curve")
def get_cash_curve(
    buyer_id: str = Query("CORP-INFOSYS", description="Corporate anchor buyer ID"),
    days: int = Query(60, ge=15, le=120, description="Projection horizon in days"),
    simulate_advance_amount: Optional[float] = Query(
        0.0,
        ge=0,
        description="Simulated early payment advance drawdown to superimpose on the curve",
    ),
) -> dict[str, Any]:
    """
    Returns 60-day daily projected cash trajectory, corporate liquidity floor ($10M),
    and credit facility undrawn headroom for chart rendering.
    """
    profile = load_buyer_treasury_profile(buyer_id)
    baseline_cash = profile["current_cash_balance_usd"]
    facility_limit = profile["facility_limit_usd"]
    facility_drawn = profile["facility_drawn_usd"]
    cash_floor = DEFAULT_MINIMUM_CASH_FLOOR_USD

    daily_points = project_daily_cash_curve(
        baseline_cash=baseline_cash,
        days=days,
        buyer_id=buyer_id,
    )

    today = datetime.date.today()
    curve_data: list[dict[str, Any]] = []

    for pt in daily_points:
        point_date = (today + datetime.timedelta(days=int(pt["day_offset"]))).isoformat()
        simulated_balance = pt["projected_cash_usd"]
        if simulate_advance_amount and pt["day_offset"] >= 5:
            simulated_balance -= simulate_advance_amount

        curve_data.append({
            "day": int(pt["day_offset"]),
            "date": point_date,
            "projected_cash": round(pt["projected_cash_usd"], 2),
            "simulated_cash": round(simulated_balance, 2),
            "inflows": round(pt["inflows_usd"], 2),
            "outflows": round(pt["outflows_usd"], 2),
            "net_flow": round(pt["net_flow_usd"], 2),
            "min_floor": cash_floor,
            "facility_headroom": round(facility_limit - facility_drawn, 2),
        })

    return {
        "buyer_id": buyer_id,
        "as_of_date": today.isoformat(),
        "horizon_days": days,
        "current_cash_balance": baseline_cash,
        "min_cash_floor": cash_floor,
        "facility_limit": facility_limit,
        "facility_drawn": facility_drawn,
        "undrawn_headroom": facility_limit - facility_drawn,
        "daily_curve": curve_data,
    }

