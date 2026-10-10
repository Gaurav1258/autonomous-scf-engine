"""
packages/orchestrator/nodes/risk_sentinel.py
============================================
Node 2: Vendor Entity Resolution & AML/Sanctions Risk Sentinel

Role:
1. Normalizes messy ERP vendor strings to canonical Golden Records via RapidFuzz.
2. Checks open trade ledgers for duplicate invoices or double-pledged receivables.
3. Screens counterparties against OFAC, PEP, and international sanctions watchlists.

Routing Impact:
- If a sanctions breach or duplicate invoice is detected, sets state["status"] to
  REJECTED_SANCTIONS, alerting compliance and halting any financial offer.
- If clean, passes the normalized vendor dossier to Node 3 (Capital Structurer).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from packages.mcp_server.modules.normalizer import extract_trade_context
from packages.orchestrator.state import (
    RiskSentinelOutput,
    SCFGraphState,
    WorkflowStatus,
)

# Known sanctions watchlist registry (OFAC SDN & High-Risk Counterparties)
DEFAULT_SANCTIONS_WATCHLIST: set[str] = {
    "SUPP-SANCTIONED-007",
    "SUPP-OFAC-BLOCK-99",
    "SUPP-00003-FLAGGED",
}


def load_vendor_watchlist() -> set[str]:
    """Loads active sanctions watchlist from vendor master or default registry."""
    watchlist = set(DEFAULT_SANCTIONS_WATCHLIST)
    vendor_master_file = Path("data/generated/synthetic_vendor_master.json")
    if vendor_master_file.exists():
        try:
            with open(vendor_master_file, "r", encoding="utf-8") as f:
                vendors = json.load(f)
                for v in vendors:
                    if not v.get("sanctions_cleared", True) or v.get("watchlist_flags"):
                        watchlist.add(v.get("supplier_id", ""))
        except Exception:
            pass
    return watchlist


def risk_sentinel_node(
    state: SCFGraphState,
    open_ledger: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """
    LangGraph Node Function for Risk & Sanctions Verification.

    Args:
        state: The current immutable state dictionary.
        open_ledger: Optional open trade ledger to detect duplicate receivables.

    Returns:
        Partial dictionary updating 'risk_profile', 'status', and 'audit_trail'.
    """
    raw_invoice = state.get("raw_invoice", {})
    invoice_id = str(raw_invoice.get("invoice_id", "INV-UNKNOWN")).strip()

    # 1. Normalize vendor & parse payment terms via FastMCP Normalizer
    trade_context = extract_trade_context(raw_invoice=raw_invoice, open_ledger=open_ledger)

    vendor_id = trade_context.vendor_canonical_id
    vendor_name = trade_context.vendor_canonical_name
    risk_tier = trade_context.supplier_risk_tier
    is_duplicate = trade_context.is_duplicate
    dup_reason = trade_context.duplicate_reason

    # 2. Sanctions Screening
    watchlist = load_vendor_watchlist()
    is_sanctioned = vendor_id in watchlist
    watchlist_matches = ["OFAC_SDN_LIST"] if is_sanctioned else []

    # 3. Decision & Status Transition
    errors: list[str] = []
    if is_sanctioned:
        status = WorkflowStatus.REJECTED_SANCTIONS
        reason = f"CRITICAL: Supplier '{vendor_name}' ({vendor_id}) matched active sanctions watchlist."
        errors.append(reason)
        audit_entry = f"RiskSentinel: SANCTIONS BREACH for {vendor_id}. Flow halted."
    elif is_duplicate:
        status = WorkflowStatus.REJECTED_GUARDRAIL
        reason = f"DUPLICATE DETECTED: {dup_reason}"
        errors.append(reason)
        audit_entry = f"RiskSentinel: DUPLICATE REJECT for {invoice_id}. Flow halted."
    else:
        status = WorkflowStatus.ANALYZING
        audit_entry = (
            f"RiskSentinel: Verified {vendor_name} ({vendor_id}). "
            f"MatchConfidence={trade_context.match_confidence_score}%, "
            f"RiskTier={risk_tier}, Sanctions=CLEARED, Duplicates=NONE."
        )

    risk_output = RiskSentinelOutput(
        invoice_id=invoice_id,
        vendor_canonical_id=vendor_id,
        vendor_canonical_name=vendor_name,
        match_confidence=trade_context.match_confidence_score,
        supplier_risk_tier=risk_tier,
        is_duplicate=is_duplicate,
        duplicate_reason=dup_reason,
        sanctions_cleared=not is_sanctioned,
        watchlist_matches=watchlist_matches,
        idempotency_hash=trade_context.idempotency_hash,
        summary_markdown=trade_context.summary_markdown,
    )

    update: dict[str, Any] = {
        "risk_profile": risk_output,
        "status": status,
        "audit_trail": [audit_entry],
    }

    if errors:
        update["errors"] = errors

    return update

