"""
Pydantic Data Contracts for scf-agent-toolkit (FastMCP Server)
==============================================================
Defines strict, audit-grade data models for trade context normalization,
deterministic working capital math, and credit facility guardrails.
"""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class PaymentTerms(BaseModel):
    """Structured representation of parsed ERP payment terms."""
    raw_term_string: str = Field(description="Raw term string from ERP (e.g. '2/10 Net 60')")
    discount_percentage: float = Field(default=0.0, description="Cash discount percentage if paid early (e.g. 2.0 for 2%)")
    discount_days: int = Field(default=0, description="Early discount window in days (e.g. 10)")
    net_days: int = Field(default=30, description="Total net credit period in days (e.g. 60)")
    is_discount_available: bool = Field(default=False, description="True if early discount terms exist")


class CleanTradeContext(BaseModel):
    """Normalized, deduplicated trade context block ready for LLM consumption."""
    invoice_id: str
    erp_source: str
    vendor_canonical_id: str
    vendor_canonical_name: str
    vendor_matched_alias: str
    match_confidence_score: float = Field(description="Fuzzy match confidence percentage (0-100)")
    tax_id: Optional[str] = None
    gstin: Optional[str] = None
    supplier_risk_tier: str = Field(default="TIER_2_STABLE")
    supplier_sector: str = Field(default="Manufacturing")
    invoice_amount: float
    currency: str = "USD"
    issue_date: str
    due_date: str
    payment_terms: PaymentTerms
    days_to_due: int
    is_duplicate: bool = False
    duplicate_reason: Optional[str] = None
    idempotency_hash: str
    summary_markdown: str = Field(description="Token-optimized Markdown summary for LLM context")


class DynamicDiscountResult(BaseModel):
    """Deterministic working capital math result for Dynamic Discounting."""
    instrument_type: str = "DYNAMIC_DISCOUNTING"
    invoice_amount: float
    days_accelerated: int
    total_tenor_days: int
    applied_discount_pct: float
    discount_amount: float
    net_advance_to_supplier: float
    buyer_yield_usd: float
    implied_apr_pct: float
    day_count_convention: str
    buyer_hurdle_rate_apr: float
    hurdle_rate_exceeded: bool
    annualized_spread_over_hurdle_pct: float


class ReverseFactoringResult(BaseModel):
    """Deterministic working capital math result for Bank Reverse Factoring."""
    instrument_type: str = "REVERSE_FACTORING"
    invoice_amount: float
    days_accelerated: int
    base_benchmark_rate_pct: float
    bank_margin_spread_pct: float
    platform_fee_pct: float
    all_in_financing_rate_pct: float
    supplier_financing_cost_usd: float
    net_advance_to_supplier: float
    bank_gross_interest_income_usd: float
    bank_net_interest_margin_usd: float
    buyer_rebate_share_pct: float
    buyer_rebate_usd: float
    day_count_convention: str = "ACT/360"


class GuardrailVerdict(BaseModel):
    """Deterministic pre-flight credit and compliance verification."""
    is_approved: bool
    buyer_id: str
    supplier_canonical_id: str
    proposed_amount: float
    facility_limit: float
    facility_drawn_before: float
    facility_drawn_after: float
    facility_utilization_pct_after: float
    headroom_available: float
    supplier_concentration_pct: float
    single_supplier_concentration_cap_pct: float
    sanctions_check_passed: bool
    breaches: list[str] = Field(default_factory=list)
    verdict_timestamp: str
    verification_signature: str

