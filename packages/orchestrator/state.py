"""
packages/orchestrator/state.py
==============================
The shared State Schema for the LangGraph Autonomous SCF Multi-Agent Engine.

Design Principles:
1. Strict Typing: Every agent reads and writes validated Pydantic models.
2. Append-Only Audit Log: Uses LangGraph's Annotated[list, operator.add] reducer
   so agents append decision rationales without overwriting history.
3. Explicit Transitions: Uses Enums (LiquidityStatus, InstrumentType, WorkflowStatus)
   to eliminate ambiguity in conditional routing edges.
"""

from __future__ import annotations

import operator
from enum import Enum
from typing import Annotated, Any, Optional
from typing_extensions import TypedDict
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums for Deterministic State Transitions
# ---------------------------------------------------------------------------

class LiquidityStatus(str, Enum):
    """Corporate buyer cash trajectory over the 60-day horizon."""
    SURPLUS = "SURPLUS"    # Cash balance stays well above minimum floor ($10M+) -> Can self-fund discounts
    TIGHT = "TIGHT"        # Balance hovers near minimum floor -> Prefer bank credit lines
    DEFICIT = "DEFICIT"    # Cash projected to dip below floor -> Must use bank facility (Reverse Factoring)


class FinancingInstrument(str, Enum):
    """The working capital technique selected by Capital Structurer."""
    DYNAMIC_DISCOUNTING = "DYNAMIC_DISCOUNTING"  # Buyer uses own idle cash; earns 100% of discount
    REVERSE_FACTORING = "REVERSE_FACTORING"      # Bank funds supplier via credit line; buyer earns rebate


class WorkflowStatus(str, Enum):
    """Lifecycle status of the invoice through the multi-agent graph."""
    PENDING = "PENDING"
    ANALYZING = "ANALYZING"
    AWAITING_TREASURER_APPROVAL = "AWAITING_TREASURER_APPROVAL"
    DISPATCHED = "DISPATCHED"
    REJECTED_SANCTIONS = "REJECTED_SANCTIONS"
    REJECTED_GUARDRAIL = "REJECTED_GUARDRAIL"
    ERROR = "ERROR"


# ---------------------------------------------------------------------------
# Typed Sub-Models (Agent Outputs)
# ---------------------------------------------------------------------------

class CashForecastOutput(BaseModel):
    """Output from the Cash Forecaster Node."""
    buyer_id: str
    current_cash_balance_usd: float
    min_projected_cash_60d_usd: float
    minimum_cash_floor_usd: float
    idle_credit_facility_headroom_usd: float
    liquidity_status: LiquidityStatus
    recommended_instrument: FinancingInstrument
    reasoning: str


class RiskSentinelOutput(BaseModel):
    """Output from the Risk Sentinel Node."""
    invoice_id: str
    vendor_canonical_id: str
    vendor_canonical_name: str
    match_confidence: float
    supplier_risk_tier: str
    is_duplicate: bool
    duplicate_reason: Optional[str] = None
    sanctions_cleared: bool
    watchlist_matches: list[str] = Field(default_factory=list)
    idempotency_hash: str
    summary_markdown: str


class CapitalStructureOption(BaseModel):
    """Detailed financial breakdown for a proposed offer."""
    instrument_type: FinancingInstrument
    days_accelerated: int
    offered_discount_pct: float
    implied_apr_pct: float
    net_advance_to_supplier_usd: float
    buyer_benefit_usd: float          # Discount earned (DD) or bank rebate (RF)
    supplier_acceptance_probability: float  # From XGBoost model
    expected_supplier_acceptance: bool
    reasoning: str


class GuardrailValidationOutput(BaseModel):
    """Output from the Guardrail Validator Node."""
    is_approved: bool
    facility_limit_usd: float
    facility_drawn_after_usd: float
    facility_headroom_remaining_usd: float
    supplier_concentration_pct: float
    concentration_cap_pct: float
    breaches: list[str] = Field(default_factory=list)
    verification_signature: str


class FinalExecutionPayload(BaseModel):
    """1-Click Executable Payload dispatched to Treasurer & Supplier."""
    offer_id: str
    invoice_id: str
    buyer_id: str
    supplier_canonical_id: str
    instrument: FinancingInstrument
    invoice_face_value_usd: float
    net_payout_to_supplier_usd: float
    buyer_yield_or_rebate_usd: float
    annualized_apr_pct: float
    days_accelerated: int
    expiry_timestamp_utc: str
    approval_token: str
    treasurer_action_url: str
    supplier_portal_url: str


# ---------------------------------------------------------------------------
# The Shared LangGraph State
# ---------------------------------------------------------------------------

class SCFGraphState(TypedDict):
    """
    The shared state dictionary passing through all nodes in the LangGraph.

    Fields with Annotated[list, operator.add] are append-only lists:
    any node that returns {"audit_trail": ["..."]} appends to the list
    rather than overwriting prior entries.
    """
    # ── Raw Input Ingestion ──────────────────────────────────────────────────
    raw_invoice: dict[str, Any]

    # ── Node 1: Cash Forecaster Output ───────────────────────────────────────
    cash_forecast: Optional[CashForecastOutput]

    # ── Node 2: Risk Sentinel Output ─────────────────────────────────────────
    risk_profile: Optional[RiskSentinelOutput]

    # ── Node 3: Capital Structurer Output ────────────────────────────────────
    optimal_structure: Optional[CapitalStructureOption]
    candidate_curve: Optional[list[dict[str, Any]]]

    # ── Node 4: Guardrail Validator Output ───────────────────────────────────
    guardrail_verdict: Optional[GuardrailValidationOutput]

    # ── Node 5: Treasury Dispatcher Output ───────────────────────────────────
    final_payload: Optional[FinalExecutionPayload]

    # ── Workflow Telemetry & Appending Reducers ──────────────────────────────
    status: WorkflowStatus
    audit_trail: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]

