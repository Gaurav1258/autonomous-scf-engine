"""
tests/test_graph.py
===================
End-to-End integration tests for the compiled LangGraph State Machine.

Verifies:
1. Happy Path: Traverses all 5 nodes, creating a final dispatch payload.
2. Compliance Short-Circuit: Halts at Risk Sentinel if sanctions hit, skipping structuring.
3. Guardrail Short-Circuit: Halts at Guardrail Validator if credit limit is breached.
"""

from __future__ import annotations

import pytest

from packages.orchestrator.graph import build_scf_graph, create_initial_state
from packages.orchestrator.state import FinancingInstrument, WorkflowStatus


class TestLangGraphEndToEnd:
    """Verifies end-to-end execution and conditional branch routing."""

    def test_end_to_end_successful_flow(self):
        """Clean invoice passes all 5 nodes and dispatches an approved payload."""
        app = build_scf_graph()

        raw_invoice = {
            "invoice_id": "INV-E2E-SUCCESS-001",
            "erp_source": "SAP_S4HANA",
            "vendor_name_raw": "Reliance Ind.",
            "buyer_id": "CORP-INFOSYS",
            "invoice_amount": 350_000.0,
            "currency": "USD",
            "issue_date": "2026-10-01",
            "due_date": "2026-11-30",
            "payment_terms_raw": "2/10 Net 60",
            "buyer_sector": "IT Services",
        }

        initial_state = create_initial_state(raw_invoice)
        final_state = app.invoke(initial_state)

        # 1. Verify Node 1 Output
        assert final_state["cash_forecast"] is not None
        assert final_state["cash_forecast"].buyer_id == "CORP-INFOSYS"

        # 2. Verify Node 2 Output
        assert final_state["risk_profile"] is not None
        assert final_state["risk_profile"].vendor_canonical_name == "Reliance Industries Ltd."
        assert final_state["risk_profile"].sanctions_cleared is True

        # 3. Verify Node 3 Output
        assert final_state["optimal_structure"] is not None
        assert final_state["optimal_structure"].net_advance_to_supplier_usd > 0
        assert final_state["candidate_curve"] is not None
        assert len(final_state["candidate_curve"]) >= 5

        # 4. Verify Node 4 Output
        assert final_state["guardrail_verdict"] is not None
        assert final_state["guardrail_verdict"].is_approved is True
        assert len(final_state["guardrail_verdict"].verification_signature) == 64

        # 5. Verify Node 5 Output
        assert final_state["final_payload"] is not None
        assert final_state["status"] == WorkflowStatus.DISPATCHED
        assert "offer_id=" in final_state["final_payload"].treasurer_action_url

        # 6. Verify Full Audit Trail Accumulated
        assert len(final_state["audit_trail"]) >= 5
        trail_text = " | ".join(final_state["audit_trail"])
        assert "CashForecaster:" in trail_text
        assert "RiskSentinel:" in trail_text
        assert "CapitalStructurer:" in trail_text
        assert "GuardrailValidator:" in trail_text
        assert "TreasuryDispatcher:" in trail_text

    def test_sanctions_short_circuit_halts_at_node_2(self, monkeypatch):
        """Sanctions hit must short-circuit directly to END without calling structurer or dispatcher."""
        from packages.orchestrator.nodes import risk_sentinel
        # Force SUPP-00001 (Reliance) onto sanctions list for this test
        monkeypatch.setattr(risk_sentinel, "DEFAULT_SANCTIONS_WATCHLIST", {"SUPP-00001"})

        app = build_scf_graph()

        raw_invoice = {
            "invoice_id": "INV-E2E-SANCTION-BLOCK",
            "erp_source": "ORACLE",
            "vendor_name_raw": "Reliance Ind.",
            "buyer_id": "CORP-INFOSYS",
            "invoice_amount": 500_000.0,
        }

        initial_state = create_initial_state(raw_invoice)
        final_state = app.invoke(initial_state)

        # Reached Node 1 and Node 2
        assert final_state["cash_forecast"] is not None
        assert final_state["risk_profile"] is not None
        assert final_state["risk_profile"].sanctions_cleared is False
        assert final_state["status"] == WorkflowStatus.REJECTED_SANCTIONS

        # Node 3, 4, 5 were NEVER executed
        assert final_state["optimal_structure"] is None
        assert final_state["guardrail_verdict"] is None
        assert final_state["final_payload"] is None

        # Verify audit trail stops at Risk Sentinel
        trail_text = " | ".join(final_state["audit_trail"])
        assert "SANCTIONS BREACH" in trail_text
        assert "CapitalStructurer:" not in trail_text
        assert "TreasuryDispatcher:" not in trail_text

    def test_guardrail_breach_short_circuit_halts_at_node_4(self):
        """Limit breach must halt at Guardrail Validator without calling Dispatcher."""
        app = build_scf_graph()

        # Massive invoice of $500M exceeds the $150M limit
        raw_invoice = {
            "invoice_id": "INV-E2E-OVERDRAW",
            "erp_source": "SAP",
            "vendor_name_raw": "Reliance Ind.",
            "buyer_id": "CORP-INFOSYS",
            "invoice_amount": 500_000_000.0,
        }

        initial_state = create_initial_state(raw_invoice)
        final_state = app.invoke(initial_state)

        # Passed Node 1, 2, 3
        assert final_state["cash_forecast"] is not None
        assert final_state["risk_profile"] is not None
        assert final_state["optimal_structure"] is not None

        # Caught and rejected by Node 4
        assert final_state["guardrail_verdict"] is not None
        assert final_state["guardrail_verdict"].is_approved is False
        assert final_state["status"] == WorkflowStatus.REJECTED_GUARDRAIL

        # Node 5 was NEVER executed
        assert final_state["final_payload"] is None
        trail_text = " | ".join(final_state["audit_trail"])
        assert "TreasuryDispatcher:" not in trail_text

