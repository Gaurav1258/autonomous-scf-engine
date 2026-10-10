"""
apps/api/routes/stream.py
=========================
Server-Sent Events (SSE) telemetry feed streaming live multi-agent execution
and reasoning steps to the frontend Treasury Cockpit in real time.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, AsyncGenerator, Optional
from fastapi import APIRouter, Depends, Query, Request
from sse_starlette.sse import EventSourceResponse

from apps.api.dependencies import StateRepository, get_graph, get_repository
from apps.api.routes.invoices import InvoiceIngestRequest, serialize_graph_state
from packages.orchestrator.graph import create_initial_state
from packages.orchestrator.state import WorkflowStatus

router = APIRouter(prefix="/api/stream", tags=["Streaming Telemetry"])


async def _run_streaming_pipeline(
    raw_invoice: dict[str, Any],
    graph: Any,
    repo: StateRepository,
) -> AsyncGenerator[dict[str, Any], None]:
    """
    Asynchronously executes the LangGraph state machine with stream_mode='updates'
    and yields SSE formatted event payloads.
    """
    invoice_id = str(raw_invoice.get("invoice_id", "INV-UNKNOWN"))
    initial_state = create_initial_state(raw_invoice)

    # 1. Yield Workflow Initialized Event
    yield {
        "event": "workflow_init",
        "data": json.dumps({
            "invoice_id": invoice_id,
            "timestamp": time.time(),
            "status": "INITIALIZED",
            "message": f"Ingested invoice {invoice_id} for ${raw_invoice.get('invoice_amount', 0):,.2f}",
            "raw_invoice": raw_invoice,
        }),
    }

    accumulated_state: dict[str, Any] = dict(initial_state)

    # 2. Stream node-by-node execution deltas
    try:
        async for chunk in graph.astream(initial_state, stream_mode="updates"):
            # chunk is a dict of {node_name: {updated_fields}}
            for node_name, updates in chunk.items():
                accumulated_state.update(updates)
                serialized_updates = serialize_graph_state(updates)

                # Build human-readable agent telemetry explanation
                agent_summary = _build_agent_telemetry_summary(node_name, updates)

                yield {
                    "event": "agent_step",
                    "data": json.dumps({
                        "invoice_id": invoice_id,
                        "timestamp": time.time(),
                        "node": node_name,
                        "status": accumulated_state.get("status", WorkflowStatus.ANALYZING).value
                        if hasattr(accumulated_state.get("status"), "value")
                        else str(accumulated_state.get("status")),
                        "summary": agent_summary,
                        "delta": serialized_updates,
                        "audit_trail": accumulated_state.get("audit_trail", []),
                    }),
                }

                # Brief async tick to yield control to event loop
                await asyncio.sleep(0.05)

    except Exception as exc:
        yield {
            "event": "workflow_error",
            "data": json.dumps({
                "invoice_id": invoice_id,
                "timestamp": time.time(),
                "error": str(exc),
            }),
        }
        return

    # 3. Save final state to repository
    serialized_final = serialize_graph_state(accumulated_state)
    record = repo.save_invoice_state(invoice_id, serialized_final)

    # 4. Yield Terminal Event (Complete or Short-Circuit Halt)
    terminal_event = (
        "workflow_halted"
        if record.status in ("REJECTED_SANCTIONS", "REJECTED_GUARDRAIL")
        else "workflow_complete"
    )

    yield {
        "event": terminal_event,
        "data": json.dumps({
            "invoice_id": invoice_id,
            "timestamp": time.time(),
            "final_status": record.status,
            "final_payload": serialized_final.get("final_payload"),
            "audit_trail": serialized_final.get("audit_trail", []),
            "summary_markdown": serialized_final.get("risk_profile", {}).get("summary_markdown")
            if isinstance(serialized_final.get("risk_profile"), dict)
            else None,
        }),
    }


def _build_agent_telemetry_summary(node_name: str, updates: dict[str, Any]) -> str:
    """Creates a concise high-signal description of what the agent decided."""
    if node_name == "cash_forecaster":
        fc = updates.get("cash_forecast")
        rec = getattr(fc, "recommended_instrument", "UNKNOWN") if fc else "ANALYZING"
        return f"Forecaster evaluated 60-day cash floor. Recommended instrument: {rec}."
    elif node_name == "risk_sentinel":
        rp = updates.get("risk_profile")
        vendor = getattr(rp, "vendor_canonical_name", "Supplier") if rp else "Supplier"
        cleared = getattr(rp, "sanctions_cleared", True) if rp else True
        if not cleared:
            return f"Risk Sentinel: CRITICAL OFAC watchlist breach on {vendor}! Halting workflow."
        return f"Risk Sentinel resolved Golden Record '{vendor}'. Sanctions verified clean."
    elif node_name == "capital_structurer":
        st = updates.get("optimal_structure")
        apr = getattr(st, "selected_annualized_rate_pct", 0.0) if st else 0.0
        payout = getattr(st, "net_advance_to_supplier_usd", 0.0) if st else 0.0
        return f"Structurer optimized ML elasticity curve: Selected {apr:.2f}% APR, net payout ${payout:,.2f}."
    elif node_name == "guardrail_validator":
        gv = updates.get("guardrail_verdict")
        approved = getattr(gv, "is_approved", True) if gv else True
        if not approved:
            reason = getattr(gv, "rejection_reason", "Facility limit breach") if gv else "Limit breach"
            return f"Guardrail Validator REJECTED: {reason}."
        return "Guardrail Validator: Credit limit & concentration verified. SHA256 digest signed."
    elif node_name == "treasury_dispatcher":
        pl = updates.get("final_payload")
        oid = getattr(pl, "offer_id", "OFFER") if pl else "OFFER"
        return f"Treasury Dispatcher packaged 1-click execution payload: Offer ID {oid} (expires in 48h)."
    return f"Completed step: {node_name}."


@router.get("/invoice/{invoice_id}")
async def stream_invoice_events(
    invoice_id: str,
    request: Request,
    scenario: Optional[str] = Query(None, description="Optional simulation preset"),
    amount: Optional[float] = Query(None, description="Optional amount override"),
    vendor: Optional[str] = Query(None, description="Optional vendor name override"),
    graph=Depends(get_graph),
    repo: StateRepository = Depends(get_repository),
) -> EventSourceResponse:
    """
    Standard Server-Sent Events (SSE) endpoint for web clients (e.g., EventSource in Next.js).
    """
    # Build invoice context
    raw_invoice = {
        "invoice_id": invoice_id,
        "buyer_id": "CORP-INFOSYS",
        "vendor_name_raw": vendor or "Reliance Ind.",
        "invoice_amount": amount or 350_000.0,
        "currency": "USD",
        "due_date": "2026-11-30",
        "issue_date": "2026-10-01",
        "payment_terms_raw": "2/10 Net 60",
        "erp_source": "SAP_S4HANA",
    }

    if scenario == "sanctioned_entity":
        raw_invoice["vendor_name_raw"] = "Rosneft Trading SA"
    elif scenario == "limit_overdraw":
        raw_invoice["invoice_amount"] = 500_000_000.0
    elif scenario == "reverse_factoring":
        raw_invoice["buyer_id"] = "CORP-TATASTEEL"
        raw_invoice["vendor_name_raw"] = "Tata Consultancy Services Ltd."
        raw_invoice["invoice_amount"] = 12_500_000.0

    generator = _run_streaming_pipeline(raw_invoice, graph, repo)
    return EventSourceResponse(generator)


@router.post("/process")
async def stream_process_custom_invoice(
    payload: InvoiceIngestRequest,
    graph=Depends(get_graph),
    repo: StateRepository = Depends(get_repository),
) -> EventSourceResponse:
    """
    Streams SSE live telemetry for a custom submitted invoice payload.
    """
    raw_invoice = payload.model_dump()
    generator = _run_streaming_pipeline(raw_invoice, graph, repo)
    return EventSourceResponse(generator)

