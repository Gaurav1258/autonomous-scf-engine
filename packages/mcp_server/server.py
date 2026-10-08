"""
scf-agent-toolkit — FastMCP Server Entry Point
==============================================
The universal Model Context Protocol (MCP) server for Autonomous Supply Chain Finance,
ERP trade context normalization, working capital math, and credit facility guardrails.

Can be run via stdio for Claude Desktop / Cursor / local LLM agents:
    uv run python packages/mcp_server/server.py

Or mounted as an SSE server for remote agent networks.
"""

from __future__ import annotations

import os
from typing import Any, Optional
from fastmcp import FastMCP

from packages.mcp_server.modules.normalizer import extract_trade_context as _extract_trade_context
from packages.mcp_server.modules.math_solver import (
    calculate_dynamic_discount as _calculate_dynamic_discount,
    simulate_reverse_factoring_spread as _simulate_reverse_factoring_spread,
)
from packages.mcp_server.modules.guardrails import verify_facility_guardrails as _verify_facility_guardrails
from packages.mcp_server.models.schemas import (
    CleanTradeContext,
    DynamicDiscountResult,
    GuardrailVerdict,
    ReverseFactoringResult,
)
from packages.orchestrator.ml.acceptance_model import SupplierAcceptanceModel, MODEL_FILE

# Initialize FastMCP Server
mcp = FastMCP(
    name="scf-agent-toolkit",
    instructions="""
You have access to the scf-agent-toolkit, an audit-grade financial toolchain for Supply Chain Finance.
Core Rules:
1. Always normalize messy ERP invoice inputs using `extract_trade_context`.
2. NEVER calculate APRs or discount amounts manually; always call `calculate_dynamic_discount` or `simulate_reverse_factoring_spread`.
3. NEVER finalize or dispatch any financing term sheet without first calling `verify_facility_guardrails`.
""",
)

# Lazy model loader
_acceptance_model: Optional[SupplierAcceptanceModel] = None


def _get_acceptance_model() -> SupplierAcceptanceModel:
    global _acceptance_model
    if _acceptance_model is None:
        if MODEL_FILE.exists():
            _acceptance_model = SupplierAcceptanceModel(model_path=MODEL_FILE)
        else:
            raise RuntimeError(f"Acceptance model not found at {MODEL_FILE}. Run acceptance_model.py first.")
    return _acceptance_model


# ---------------------------------------------------------------------------
# MCP Tool 1: Module A — Trade Ledger Context Normalizer
# ---------------------------------------------------------------------------
@mcp.tool(
    name="extract_trade_context",
    description="Normalizes raw ERP invoice data, parses payment terms (e.g. '2/10 Net 60'), resolves vendor name to canonical Golden Record using RapidFuzz, and checks for duplicate receivables.",
)
def extract_trade_context(
    raw_invoice: dict[str, Any],
    vendor_master: Optional[list[dict[str, Any]]] = None,
    open_ledger: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Normalizes raw ERP invoice into a CleanTradeContext block."""
    result = _extract_trade_context(raw_invoice, vendor_master, open_ledger)
    return result.model_dump()


# ---------------------------------------------------------------------------
# MCP Tool 2: Module B — Dynamic Discounting Math Solver
# ---------------------------------------------------------------------------
@mcp.tool(
    name="calculate_dynamic_discount",
    description="Calculates exact, audit-grade Dynamic Discounting terms (sliding scale discount, net supplier payout, FASB ASC 310 implied APR, and corporate buyer yield) with decimal precision.",
)
def calculate_dynamic_discount(
    invoice_amount: float,
    days_accelerated: int,
    total_tenor_days: int,
    buyer_hurdle_rate_apr: float,
    baseline_discount_pct: float = 2.0,
    day_count_convention: str = "ACT/365",
) -> dict[str, Any]:
    """Deterministic calculation of Dynamic Discounting economics."""
    result = _calculate_dynamic_discount(
        invoice_amount=invoice_amount,
        days_accelerated=days_accelerated,
        total_tenor_days=total_tenor_days,
        buyer_hurdle_rate_apr=buyer_hurdle_rate_apr,
        baseline_discount_pct=baseline_discount_pct,
        day_count_convention=day_count_convention,
    )
    return result.model_dump()


# ---------------------------------------------------------------------------
# MCP Tool 3: Module B — Reverse Factoring Spread Simulator
# ---------------------------------------------------------------------------
@mcp.tool(
    name="simulate_reverse_factoring_spread",
    description="Simulates bank-funded Reverse Factoring (Payables Finance) mechanics using ACT/360 money market discounting: computes all-in rate, supplier advance, Bank Net Interest Margin (NIM), and buyer rebate.",
)
def simulate_reverse_factoring_spread(
    invoice_amount: float,
    days_accelerated: int,
    base_benchmark_rate: float,
    bank_margin_spread: float,
    platform_fee_pct: float = 0.20,
    buyer_rebate_share_pct: float = 0.30,
) -> dict[str, Any]:
    """Deterministic calculation of bank-funded Reverse Factoring economics."""
    result = _simulate_reverse_factoring_spread(
        invoice_amount=invoice_amount,
        days_accelerated=days_accelerated,
        base_benchmark_rate=base_benchmark_rate,
        bank_margin_spread=bank_margin_spread,
        platform_fee_pct=platform_fee_pct,
        buyer_rebate_share_pct=buyer_rebate_share_pct,
    )
    return result.model_dump()


# ---------------------------------------------------------------------------
# MCP Tool 4: Module C — Guardrail & Pre-Flight Validator
# ---------------------------------------------------------------------------
@mcp.tool(
    name="verify_facility_guardrails",
    description="Pre-flight compliance check: verifies available facility limit headroom, enforces 15% single-supplier concentration caps, and screens against OFAC/sanctions watchlists.",
)
def verify_facility_guardrails(
    buyer_id: str,
    supplier_canonical_id: str,
    proposed_amount: float,
    facility_limit: float,
    facility_drawn: float,
    single_supplier_concentration_cap_pct: float = 15.0,
    existing_supplier_exposure: float = 0.0,
    sanctions_watchlist: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Deterministic validation of credit line covenants and AML compliance."""
    result = _verify_facility_guardrails(
        buyer_id=buyer_id,
        supplier_canonical_id=supplier_canonical_id,
        proposed_amount=proposed_amount,
        facility_limit=facility_limit,
        facility_drawn=facility_drawn,
        single_supplier_concentration_cap_pct=single_supplier_concentration_cap_pct,
        existing_supplier_exposure=existing_supplier_exposure,
        sanctions_watchlist=sanctions_watchlist,
    )
    return result.model_dump()


# ---------------------------------------------------------------------------
# MCP Tool 5: Hybrid ML — Supplier Discount Acceptance Prediction
# ---------------------------------------------------------------------------
@mcp.tool(
    name="predict_supplier_acceptance_probability",
    description="Uses the trained XGBoost model to predict the probability that a supplier will accept an early payment discount offer.",
)
def predict_supplier_acceptance_probability(
    features: dict[str, Any],
) -> dict[str, Any]:
    """Returns acceptance probability and whether expected_acceptance is True/False."""
    model = _get_acceptance_model()
    prob = model.predict_probability(features)
    return {
        "acceptance_probability": prob,
        "expected_acceptance": bool(prob >= 0.50),
        "model_version": model.metadata.get("metrics", {}),
    }


# ---------------------------------------------------------------------------
# MCP Tool 6: Hybrid ML — Price Elasticity Curve Explorer
# ---------------------------------------------------------------------------
@mcp.tool(
    name="predict_supplier_acceptance_curve",
    description="Generates an acceptance probability curve across multiple candidate discount rates, allowing the agent to find the optimal win-win financing spread.",
)
def predict_supplier_acceptance_curve(
    base_features: dict[str, Any],
    discount_rates: Optional[list[float]] = None,
) -> list[dict[str, Any]]:
    """Returns price elasticity curve across candidate discount rates."""
    model = _get_acceptance_model()
    return model.predict_acceptance_curve(base_features, discount_rates)


if __name__ == "__main__":
    # Standard FastMCP CLI runner (supports stdio by default)
    mcp.run()

