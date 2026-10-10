"""
tests/test_risk_sentinel.py
===========================
Unit tests for LangGraph Node 2: Risk Sentinel Agent.
"""

from __future__ import annotations

import pytest

from packages.orchestrator.nodes.risk_sentinel import risk_sentinel_node
from packages.orchestrator.state import (
    SCFGraphState,
    WorkflowStatus,
)


class TestRiskSentinelNode:
    """Verifies vendor resolution, duplicate checks, and sanctions screening."""

    def test_clean_vendor_normalized_and_cleared(self):
        state: SCFGraphState = {
            "raw_invoice": {
                "invoice_id": "INV-2026-SAP-101",
                "vendor_name_raw": "Reliance Ind.",
                "buyer_id": "CORP-INFOSYS",
                "invoice_amount": 150_000.0,
                "payment_terms_raw": "2/10 Net 60",
            },
            "cash_forecast": None,
            "risk_profile": None,
            "optimal_structure": None,
            "candidate_curve": None,
            "guardrail_verdict": None,
            "final_payload": None,
            "status": WorkflowStatus.PENDING,
            "audit_trail": [],
            "errors": [],
        }

        update = risk_sentinel_node(state)

        assert "risk_profile" in update
        risk = update["risk_profile"]

        assert risk.vendor_canonical_name == "Reliance Industries Ltd."
        assert risk.vendor_canonical_id == "SUPP-00001"
        assert risk.match_confidence >= 80.0
        assert risk.sanctions_cleared is True
        assert risk.is_duplicate is False
        assert update["status"] == WorkflowStatus.ANALYZING
        assert "RiskSentinel:" in update["audit_trail"][0]

    def test_sanctions_hit_blocks_workflow(self, monkeypatch):
        # Force vendor ID to hit the sanctions watchlist
        from packages.orchestrator.nodes import risk_sentinel
        monkeypatch.setattr(risk_sentinel, "DEFAULT_SANCTIONS_WATCHLIST", {"SUPP-00001"})

        state: SCFGraphState = {
            "raw_invoice": {
                "invoice_id": "INV-SANCTION-TEST",
                "vendor_name_raw": "Reliance Ind.",
                "buyer_id": "CORP-INFOSYS",
                "invoice_amount": 500_000.0,
            },
            "cash_forecast": None,
            "risk_profile": None,
            "optimal_structure": None,
            "candidate_curve": None,
            "guardrail_verdict": None,
            "final_payload": None,
            "status": WorkflowStatus.PENDING,
            "audit_trail": [],
            "errors": [],
        }

        update = risk_sentinel_node(state)
        risk = update["risk_profile"]

        assert risk.sanctions_cleared is False
        assert "OFAC_SDN_LIST" in risk.watchlist_matches
        assert update["status"] == WorkflowStatus.REJECTED_SANCTIONS
        assert len(update["errors"]) > 0
        assert "SANCTIONS BREACH" in update["audit_trail"][0]

    def test_duplicate_invoice_halts_flow(self):
        existing_ledger = [
            {"invoice_id": "INV-DUP-999", "status": "FINANCED"}
        ]

        state: SCFGraphState = {
            "raw_invoice": {
                "invoice_id": "INV-DUP-999",
                "vendor_name_raw": "TCS Ltd.",
                "buyer_id": "CORP-INFOSYS",
                "invoice_amount": 250_000.0,
            },
            "cash_forecast": None,
            "risk_profile": None,
            "optimal_structure": None,
            "candidate_curve": None,
            "guardrail_verdict": None,
            "final_payload": None,
            "status": WorkflowStatus.PENDING,
            "audit_trail": [],
            "errors": [],
        }

        update = risk_sentinel_node(state, open_ledger=existing_ledger)
        risk = update["risk_profile"]

        assert risk.is_duplicate is True
        assert update["status"] == WorkflowStatus.REJECTED_GUARDRAIL
        assert "DUPLICATE DETECTED" in update["errors"][0]

