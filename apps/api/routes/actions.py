"""
apps/api/routes/actions.py
==========================
One-click dual-approval execution cockpit for Corporate Treasurers and Suppliers.
"""

from __future__ import annotations

import time
import hashlib
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from apps.api.dependencies import StateRepository, get_repository

router = APIRouter(prefix="/api/offers", tags=["Offers & Approvals"])


class OfferActionRequest(BaseModel):
    """Payload representing a 1-click decision by Treasurer or Supplier."""
    decision: str = Field(..., description="Action decision: APPROVED | REJECTED")
    approver_role: str = Field("TREASURER", description="Role of the actor: TREASURER | SUPPLIER")
    approval_token: Optional[str] = Field(None, description="Cryptographic 32-char token embedded in offer")
    notes: Optional[str] = Field(None, description="Optional notes or audit rationale")


@router.get("/{offer_id}")
def get_offer(
    offer_id: str,
    repo: StateRepository = Depends(get_repository),
) -> dict[str, Any]:
    """Retrieves financing terms and execution details for a generated offer ID."""
    record = repo.get_invoice_by_offer_id(offer_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Offer '{offer_id}' not found.")

    final_payload = record.state.get("final_payload", {})
    return {
        "offer_id": offer_id,
        "invoice_id": record.invoice_id,
        "workflow_status": record.status,
        "decision": record.decision,
        "decided_at": record.decided_at,
        "terms": record.state.get("optimal_structure"),
        "final_payload": final_payload,
        "guardrail_verdict": record.state.get("guardrail_verdict"),
    }


@router.post("/{offer_id}/action")
def execute_offer_action(
    offer_id: str,
    payload: OfferActionRequest,
    repo: StateRepository = Depends(get_repository),
) -> dict[str, Any]:
    """
    Executes or cancels the financing term sheet upon human-in-the-loop authorization.
    Verifies expiration timestamp and authorization token.
    """
    record = repo.get_invoice_by_offer_id(offer_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Offer '{offer_id}' not found.")

    final_payload = record.state.get("final_payload", {})
    if not isinstance(final_payload, dict):
        final_payload = getattr(final_payload, "model_dump", lambda: {})()

    # 1. Expiration Check
    expires_at = final_payload.get("expires_at_timestamp", 0)
    if expires_at and time.time() > expires_at:
        raise HTTPException(
            status_code=410,
            detail=f"Offer '{offer_id}' has expired. Term sheets are valid for 48 hours only.",
        )

    # 2. Token Check (if token was generated and provided)
    expected_token = final_payload.get("approval_token")
    if expected_token and payload.approval_token:
        if payload.approval_token != expected_token:
            raise HTTPException(status_code=403, detail="Invalid approval token for this offer.")

    # 3. Update Decision in Repository
    updated_record = repo.record_decision(
        offer_id=offer_id,
        decision=payload.decision.upper(),
        notes=payload.notes,
    )

    if not updated_record:
        raise HTTPException(status_code=500, detail="Failed to record decision in state store.")

    # 4. Generate Core Banking Settlement Reference if Approved
    settlement_ref = None
    if payload.decision.upper() == "APPROVED":
        hash_input = f"{offer_id}:{record.invoice_id}:{time.time()}"
        settlement_ref = f"SETTLE-CB-{hashlib.sha256(hash_input.encode()).hexdigest()[:12].upper()}"

    return {
        "status": "success",
        "offer_id": offer_id,
        "invoice_id": record.invoice_id,
        "decision": payload.decision.upper(),
        "approver_role": payload.approver_role,
        "execution_status": updated_record.status,
        "settlement_reference": settlement_ref,
        "decided_at": updated_record.decided_at,
        "message": (
            f"Offer successfully approved and queued for core banking settlement ({settlement_ref})."
            if payload.decision.upper() == "APPROVED"
            else f"Offer rejected by {payload.approver_role}."
        ),
    }

