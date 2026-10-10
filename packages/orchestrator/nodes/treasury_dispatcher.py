"""
packages/orchestrator/nodes/treasury_dispatcher.py
==================================================
Node 5: Treasury Dispatcher & One-Click Execution Engine

Role:
Packages the approved trade finance term sheet into a secure, actionable 1-click
execution payload for the Corporate Treasurer and Supplier.

Capabilities:
1. One-Click Approval Token: Computes a secure time-limited token for execution.
2. Time-Sensitive Expiry: Sets an expiration deadline (default: 48-hour liquidity window).
3. Portal Action URLs: Prepares direct endpoints for Treasurer sign-off and Supplier portal.
4. Compliance Safeguard: Strictly blocks payload generation if guardrails or sanctions failed.

Routing Impact:
- Updates state["final_payload"] with FinalExecutionPayload.
- Updates state["status"] to DISPATCHED.
- Appends final dispatch telemetry to audit_trail.
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from packages.orchestrator.state import (
    FinalExecutionPayload,
    SCFGraphState,
    WorkflowStatus,
)

BASE_PORTAL_URL = "https://scf-engine.corp.bank"
OFFER_VALIDITY_HOURS = 48


def generate_approval_token(
    offer_id: str,
    invoice_id: str,
    buyer_id: str,
    amount: float,
    expiry_iso: str,
    secret_salt: str = "SCF_DISPATCH_SECRET_TOKEN_2026",
) -> str:
    """Generates an HMAC-style SHA256 one-time execution token."""
    raw = f"{offer_id}|{invoice_id}|{buyer_id}|{amount:.2f}|{expiry_iso}|{secret_salt}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def treasury_dispatcher_node(state: SCFGraphState) -> dict[str, Any]:
    """
    LangGraph Node Function for 1-Click Offer Dispatch.

    Args:
        state: The current immutable state dictionary.

    Returns:
        Partial dictionary updating 'final_payload', 'status', and 'audit_trail'.
    """
    # ── Safety Check ─────────────────────────────────────────────────────────
    # If the transaction was blocked upstream by sanctions or guardrails, halt immediately.
    guardrail_verdict = state.get("guardrail_verdict")
    risk_profile = state.get("risk_profile")
    current_status = state.get("status")

    if current_status in (WorkflowStatus.REJECTED_SANCTIONS, WorkflowStatus.REJECTED_GUARDRAIL):
        audit_entry = (
            f"TreasuryDispatcher: Bypassed. Transaction was blocked upstream "
            f"(Status={current_status.value}). No dispatch payload created."
        )
        return {
            "final_payload": None,
            "audit_trail": [audit_entry],
        }

    if guardrail_verdict and not guardrail_verdict.is_approved:
        audit_entry = "TreasuryDispatcher: Guardrail check failed. Dispatch aborted."
        return {
            "final_payload": None,
            "status": WorkflowStatus.REJECTED_GUARDRAIL,
            "audit_trail": [audit_entry],
        }

    raw_invoice = state.get("raw_invoice", {})
    optimal_structure = state.get("optimal_structure")

    invoice_id = str(raw_invoice.get("invoice_id", "INV-UNKNOWN")).strip()
    buyer_id = str(raw_invoice.get("buyer_id", "CORP-DEFAULT")).strip()
    supplier_id = risk_profile.vendor_canonical_id if risk_profile else "SUPP-UNKNOWN"
    face_value = float(raw_invoice.get("invoice_amount", 0.0))

    if not optimal_structure:
        return {
            "final_payload": None,
            "status": WorkflowStatus.ERROR,
            "audit_trail": ["TreasuryDispatcher: Missing optimal_structure. Cannot dispatch."],
            "errors": ["Dispatcher error: Missing structured financing options in state."],
        }

    # ── Generate Dispatch Telemetry ──────────────────────────────────────────
    now_utc = datetime.now(timezone.utc)
    expiry_dt = now_utc + timedelta(hours=OFFER_VALIDITY_HOURS)
    expiry_iso = expiry_dt.isoformat()

    # Deterministic offer identifier
    hash_seed = f"{invoice_id}-{buyer_id}-{optimal_structure.offered_discount_pct}"
    offer_suffix = hashlib.sha256(hash_seed.encode("utf-8")).hexdigest()[:8].upper()
    offer_id = f"OFFER-{offer_suffix}"

    token = generate_approval_token(
        offer_id=offer_id,
        invoice_id=invoice_id,
        buyer_id=buyer_id,
        amount=face_value,
        expiry_iso=expiry_iso,
    )

    treasurer_url = f"{BASE_PORTAL_URL}/treasury/approve?offer_id={offer_id}&token={token}"
    supplier_url = f"{BASE_PORTAL_URL}/supplier/accept?offer_id={offer_id}&token={token}"

    payload = FinalExecutionPayload(
        offer_id=offer_id,
        invoice_id=invoice_id,
        buyer_id=buyer_id,
        supplier_canonical_id=supplier_id,
        instrument=optimal_structure.instrument_type,
        invoice_face_value_usd=face_value,
        net_payout_to_supplier_usd=optimal_structure.net_advance_to_supplier_usd,
        buyer_yield_or_rebate_usd=optimal_structure.buyer_benefit_usd,
        annualized_apr_pct=optimal_structure.implied_apr_pct,
        days_accelerated=optimal_structure.days_accelerated,
        expiry_timestamp_utc=expiry_iso,
        approval_token=token,
        treasurer_action_url=treasurer_url,
        supplier_portal_url=supplier_url,
    )

    audit_entry = (
        f"TreasuryDispatcher: Created payload {offer_id} for {buyer_id} / {supplier_id}. "
        f"Instrument={optimal_structure.instrument_type.value}, "
        f"Advance=${optimal_structure.net_advance_to_supplier_usd:,.2f}, "
        f"BuyerYield=${optimal_structure.buyer_benefit_usd:,.2f}, "
        f"APR={optimal_structure.implied_apr_pct:.2f}%. "
        f"Valid until {expiry_iso[:19]} UTC."
    )

    return {
        "final_payload": payload,
        "status": WorkflowStatus.DISPATCHED,
        "audit_trail": [audit_entry],
    }

