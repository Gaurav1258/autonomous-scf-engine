"""
apps/api/routes/invoices.py
===========================
ERP invoice ingestion, batch querying, and simulation endpoints.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from apps.api.dependencies import StateRepository, get_graph, get_repository
from packages.orchestrator.graph import create_initial_state
from packages.orchestrator.state import WorkflowStatus

router = APIRouter(prefix="/api/invoices", tags=["Invoices"])


class InvoiceIngestRequest(BaseModel):
    """Payload representing an approved ERP payable invoice event."""
    invoice_id: str = Field(..., description="Unique invoice identifier from ERP ledger")
    buyer_id: str = Field("CORP-INFOSYS", description="Corporate anchor buyer identifier")
    vendor_name_raw: str = Field(..., description="Raw supplier name string as recorded in ERP")
    invoice_amount: float = Field(..., gt=0, description="Gross payable invoice amount")
    currency: str = Field("USD", description="Currency ISO code")
    due_date: str = Field("2026-11-30", description="Net invoice payment due date (YYYY-MM-DD)")
    issue_date: Optional[str] = Field("2026-10-01", description="Invoice issue date (YYYY-MM-DD)")
    payment_terms_raw: str = Field("2/10 Net 60", description="ERP payment terms string")
    erp_source: Optional[str] = Field("SAP_S4HANA", description="Source ERP system")
    buyer_sector: Optional[str] = Field("IT Services", description="Industry sector of anchor buyer")


def serialize_graph_state(state: dict[str, Any]) -> dict[str, Any]:
    """Recursively converts Pydantic objects and Enums inside graph state to pure JSON dicts."""
    out: dict[str, Any] = {}
    for k, v in state.items():
        if hasattr(v, "model_dump"):
            out[k] = v.model_dump(mode="json")
        elif hasattr(v, "value"):  # Enum
            out[k] = v.value
        elif isinstance(v, list):
            serialized_list = []
            for item in v:
                if hasattr(item, "model_dump"):
                    serialized_list.append(item.model_dump(mode="json"))
                elif hasattr(item, "value"):
                    serialized_list.append(item.value)
                else:
                    serialized_list.append(item)
            out[k] = serialized_list
        else:
            out[k] = v
    return out


@router.post("/process")
def process_invoice(
    payload: InvoiceIngestRequest,
    graph=Depends(get_graph),
    repo: StateRepository = Depends(get_repository),
) -> dict[str, Any]:
    """
    Ingests an approved ERP invoice, executes the full LangGraph multi-agent workflow,
    and returns the structured state dossier.
    """
    raw_dict = payload.model_dump()
    initial_state = create_initial_state(raw_dict)

    # Execute LangGraph workflow synchronously
    final_state = graph.invoke(initial_state)

    serialized = serialize_graph_state(final_state)
    record = repo.save_invoice_state(payload.invoice_id, serialized)

    return {
        "status": "success",
        "invoice_id": payload.invoice_id,
        "workflow_status": record.status,
        "data": serialized,
    }


@router.get("")
def list_invoices(
    limit: int = Query(50, ge=1, le=100),
    repo: StateRepository = Depends(get_repository),
) -> list[dict[str, Any]]:
    """Lists recently processed invoices and their current workflow status."""
    records = repo.list_invoices(limit=limit)
    return [
        {
            "invoice_id": r.invoice_id,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
            "status": r.status,
            "decision": r.decision,
            "summary": {
                "vendor": r.state.get("risk_profile", {}).get("vendor_canonical_name") if isinstance(r.state.get("risk_profile"), dict) else None,
                "amount": r.state.get("raw_invoice", {}).get("invoice_amount"),
                "instrument": r.state.get("optimal_structure", {}).get("instrument_type") if isinstance(r.state.get("optimal_structure"), dict) else None,
                "apr": r.state.get("optimal_structure", {}).get("selected_annualized_rate_pct") if isinstance(r.state.get("optimal_structure"), dict) else None,
            },
        }
        for r in records
    ]


@router.get("/{invoice_id}")
def get_invoice(
    invoice_id: str,
    repo: StateRepository = Depends(get_repository),
) -> dict[str, Any]:
    """Retrieves full state dossier for a specific invoice ID."""
    record = repo.get_invoice(invoice_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Invoice '{invoice_id}' not found.")
    return {
        "invoice_id": record.invoice_id,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "status": record.status,
        "decision": record.decision,
        "decision_notes": record.decision_notes,
        "state": record.state,
    }


@router.post("/simulate")
def simulate_scenario(
    scenario: str = Query(
        "clean_discounting",
        description="Scenario type: clean_discounting | sanctioned_entity | limit_overdraw | reverse_factoring",
    ),
    graph=Depends(get_graph),
    repo: StateRepository = Depends(get_repository),
) -> dict[str, Any]:
    """
    Simulation utility for frontend demo cockpit: creates and runs predefined scenarios.
    """
    sim_id = f"INV-SIM-{uuid.uuid4().hex[:6].upper()}"

    if scenario == "clean_discounting":
        raw = {
            "invoice_id": sim_id,
            "buyer_id": "CORP-INFOSYS",
            "vendor_name_raw": "Reliance Ind.",
            "invoice_amount": 350_000.0,
            "currency": "USD",
            "due_date": "2026-11-30",
            "issue_date": "2026-10-01",
            "payment_terms_raw": "2/10 Net 60",
            "erp_source": "SAP_S4HANA",
        }
    elif scenario == "sanctioned_entity":
        raw = {
            "invoice_id": sim_id,
            "buyer_id": "CORP-INFOSYS",
            "vendor_name_raw": "Rosneft Trading SA",
            "invoice_amount": 850_000.0,
            "currency": "USD",
            "due_date": "2026-11-30",
            "issue_date": "2026-10-01",
            "payment_terms_raw": "Net 60",
            "erp_source": "ORACLE",
        }
    elif scenario == "limit_overdraw":
        raw = {
            "invoice_id": sim_id,
            "buyer_id": "CORP-INFOSYS",
            "vendor_name_raw": "Reliance Ind.",
            "invoice_amount": 500_000_000.0,  # Exceeds $150M limit
            "currency": "USD",
            "due_date": "2026-11-30",
            "issue_date": "2026-10-01",
            "payment_terms_raw": "Net 90",
            "erp_source": "SAP_S4HANA",
        }
    elif scenario == "reverse_factoring":
        raw = {
            "invoice_id": sim_id,
            "buyer_id": "CORP-TATASTEEL",  # Heavy industrial buyer with high debt / tight cash
            "vendor_name_raw": "Tata Consultancy Services Ltd.",
            "invoice_amount": 12_500_000.0,
            "currency": "USD",
            "due_date": "2026-12-15",
            "issue_date": "2026-10-01",
            "payment_terms_raw": "Net 90",
            "erp_source": "NETSUITE",
        }
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown scenario '{scenario}'. Choose from: clean_discounting, sanctioned_entity, limit_overdraw, reverse_factoring",
        )

    initial_state = create_initial_state(raw)
    final_state = graph.invoke(initial_state)

    serialized = serialize_graph_state(final_state)
    record = repo.save_invoice_state(sim_id, serialized)

    return {
        "scenario": scenario,
        "invoice_id": sim_id,
        "workflow_status": record.status,
        "data": serialized,
    }

