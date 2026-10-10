"""
apps/api/dependencies.py
========================
Dependency injection, shared singleton services, and in-memory state repository
for the FastAPI gateway.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Optional
from pydantic import BaseModel, Field

from packages.orchestrator.graph import build_scf_graph, create_initial_state
from packages.orchestrator.state import SCFGraphState, WorkflowStatus


class InvoiceRecord(BaseModel):
    """Stores the execution snapshot and current state of an invoice workflow."""
    invoice_id: str
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    state: dict[str, Any]
    status: str
    decision: Optional[str] = None  # None | "APPROVED" | "REJECTED"
    decision_notes: Optional[str] = None
    decided_at: Optional[float] = None


class StateRepository:
    """Thread-safe in-memory store for active invoice workflows and treasury offers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._invoices: dict[str, InvoiceRecord] = {}
        self._offers: dict[str, str] = {}  # offer_id -> invoice_id

    def save_invoice_state(self, invoice_id: str, state: dict[str, Any]) -> InvoiceRecord:
        with self._lock:
            status_val = state.get("status")
            status_str = status_val.value if hasattr(status_val, "value") else str(status_val)
            
            # If an offer was generated, index it
            final_payload = state.get("final_payload")
            if final_payload is not None:
                offer_id = getattr(final_payload, "offer_id", None) or (
                    final_payload.get("offer_id") if isinstance(final_payload, dict) else None
                )
                if offer_id:
                    self._offers[offer_id] = invoice_id

            rec = self._invoices.get(invoice_id)
            if rec:
                rec.state = state
                rec.status = status_str
                rec.updated_at = time.time()
            else:
                rec = InvoiceRecord(
                    invoice_id=invoice_id,
                    state=state,
                    status=status_str,
                )
                self._invoices[invoice_id] = rec
            return rec

    def get_invoice(self, invoice_id: str) -> Optional[InvoiceRecord]:
        with self._lock:
            return self._invoices.get(invoice_id)

    def list_invoices(self, limit: int = 50) -> list[InvoiceRecord]:
        with self._lock:
            records = list(self._invoices.values())
            records.sort(key=lambda r: r.created_at, reverse=True)
            return records[:limit]

    def get_invoice_by_offer_id(self, offer_id: str) -> Optional[InvoiceRecord]:
        with self._lock:
            inv_id = self._offers.get(offer_id)
            if not inv_id:
                return None
            return self._invoices.get(inv_id)

    def record_decision(
        self,
        offer_id: str,
        decision: str,
        notes: Optional[str] = None,
    ) -> Optional[InvoiceRecord]:
        with self._lock:
            inv_id = self._offers.get(offer_id)
            if not inv_id:
                return None
            rec = self._invoices.get(inv_id)
            if not rec:
                return None
            rec.decision = decision
            rec.decision_notes = notes
            rec.decided_at = time.time()
            rec.status = "EXECUTED_SETTLED" if decision == "APPROVED" else "CANCELLED_BY_TREASURER"
            rec.updated_at = time.time()
            return rec


# Singletons
_repo_instance = StateRepository()
_graph_app = None
_graph_lock = threading.Lock()


def get_repository() -> StateRepository:
    """Dependency injector for state repository."""
    return _repo_instance


def get_graph():
    """Dependency injector for compiled LangGraph state machine singleton."""
    global _graph_app
    if _graph_app is None:
        with _graph_lock:
            if _graph_app is None:
                _graph_app = build_scf_graph()
    return _graph_app

