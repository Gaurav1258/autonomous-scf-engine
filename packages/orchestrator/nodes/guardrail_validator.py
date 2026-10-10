"""
packages/orchestrator/nodes/guardrail_validator.py
==================================================
Node 4: Credit Facility & Compliance Guardrail Validator Agent

Role:
Executes deterministic pre-flight validation before any financing offer
can be finalized or dispatched to human treasurers.

Enforces:
1. Credit Facility Capacity: facility_drawn + proposed_amount <= facility_limit
2. Concentration Cap: (supplier_exposure + proposed_amount) / limit <= 15.0%
3. Watchlist Screening: Secondary verification against sanctions registries
4. Cryptographic Proof: Produces a tamper-proof SHA256 verification signature

Routing Impact:
- If approved: Sets state["status"] to AWAITING_TREASURER_APPROVAL and routes to Dispatcher.
- If rejected: Sets state["status"] to REJECTED_GUARDRAIL, logging exact covenant
  breaches and halting the workflow.
"""

from __future__ import annotations

from typing import Any, Optional

from packages.mcp_server.modules.guardrails import verify_facility_guardrails
from packages.orchestrator.nodes.cash_forecaster import load_buyer_treasury_profile
from packages.orchestrator.nodes.risk_sentinel import load_vendor_watchlist
from packages.orchestrator.state import (
    FinancingInstrument,
    GuardrailValidationOutput,
    SCFGraphState,
    WorkflowStatus,
)


def guardrail_validator_node(
    state: SCFGraphState,
    existing_supplier_exposure: float = 0.0,
    concentration_cap_pct: float = 15.0,
) -> dict[str, Any]:
    """
    LangGraph Node Function for Pre-Flight Credit Limit & Compliance Verification.

    Args:
        state: The current immutable state dictionary.
        existing_supplier_exposure: Prior active financing exposure to this vendor.
        concentration_cap_pct: Max allowed exposure to a single vendor (default 15%).

    Returns:
        Partial dictionary updating 'guardrail_verdict', 'status', and 'audit_trail'.
    """
    raw_invoice = state.get("raw_invoice", {})
    risk_profile = state.get("risk_profile")
    optimal_structure = state.get("optimal_structure")
    cash_forecast = state.get("cash_forecast")

    buyer_id = str(raw_invoice.get("buyer_id", "CORP-DEFAULT")).strip()
    supplier_id = risk_profile.vendor_canonical_id if risk_profile else "SUPP-UNKNOWN"
    proposed_amount = float(raw_invoice.get("invoice_amount", 0.0))

    # Fetch buyer's facility telemetry
    profile = load_buyer_treasury_profile(buyer_id)
    facility_limit = profile["facility_limit_usd"]
    facility_drawn = profile["facility_drawn_usd"]

    # If Dynamic Discounting (self-funded with buyer's own cash), credit line draw is 0,
    # but concentration and sanctions caps still apply to manage enterprise risk
    effective_facility_drawn = (
        facility_drawn
        if (optimal_structure and optimal_structure.instrument_type == FinancingInstrument.REVERSE_FACTORING)
        else 0.0
    )

    # Secondary sanctions screening
    watchlist = list(load_vendor_watchlist())

    # Execute deterministic FastMCP guardrail validation
    verdict = verify_facility_guardrails(
        buyer_id=buyer_id,
        supplier_canonical_id=supplier_id,
        proposed_amount=proposed_amount,
        facility_limit=facility_limit,
        facility_drawn=effective_facility_drawn,
        single_supplier_concentration_cap_pct=concentration_cap_pct,
        existing_supplier_exposure=existing_supplier_exposure,
        sanctions_watchlist=watchlist,
    )

    guardrail_output = GuardrailValidationOutput(
        is_approved=verdict.is_approved,
        facility_limit_usd=verdict.facility_limit,
        facility_drawn_after_usd=verdict.facility_drawn_after,
        facility_headroom_remaining_usd=verdict.headroom_available,
        supplier_concentration_pct=verdict.supplier_concentration_pct,
        concentration_cap_pct=verdict.single_supplier_concentration_cap_pct,
        breaches=verdict.breaches,
        verification_signature=verdict.verification_signature,
    )

    errors: list[str] = []
    if verdict.is_approved:
        status = WorkflowStatus.AWAITING_TREASURER_APPROVAL
        audit_entry = (
            f"GuardrailValidator: APPROVED for {buyer_id} / {supplier_id}. "
            f"UtilizationAfter={verdict.facility_utilization_pct_after:.1f}%, "
            f"Concentration={verdict.supplier_concentration_pct:.1f}% (Cap: {concentration_cap_pct}%). "
            f"Signature={verdict.verification_signature[:16]}..."
        )
    else:
        status = WorkflowStatus.REJECTED_GUARDRAIL
        errors = [f"GUARDRAIL BREACH: {b}" for b in verdict.breaches]
        audit_entry = (
            f"GuardrailValidator: REJECTED with {len(verdict.breaches)} covenant breach(es). "
            f"Breaches: {'; '.join(verdict.breaches)}"
        )

    update: dict[str, Any] = {
        "guardrail_verdict": guardrail_output,
        "status": status,
        "audit_trail": [audit_entry],
    }

    if errors:
        update["errors"] = errors

    return update

