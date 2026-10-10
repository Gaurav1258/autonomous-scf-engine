"""
tests/test_api_routes.py
========================
Integration test suite for the FastAPI Gateway:
Verifies REST endpoints, SSE telemetry streaming, simulation triggers,
cash curve projections, and 1-click dual-approval execution.
"""

from __future__ import annotations

import json
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app

client = TestClient(app)


class TestFastAPIRoutes:
    """Verifies all FastAPI Gateway endpoints."""

    def test_root_and_health_endpoints(self):
        """Root welcoming and health check probe endpoints return 200."""
        # 1. Test Root
        root_res = client.get("/")
        assert root_res.status_code == 200
        root_data = root_res.json()
        assert root_data["status"] == "ONLINE"
        assert "Autonomous Supply Chain Finance" in root_data["engine"]

        # 2. Test Health
        health_res = client.get("/health")
        assert health_res.status_code == 200
        health_data = health_res.json()
        assert health_data["status"] == "HEALTHY"
        assert health_data["subsystems"]["langgraph_multi_agent"] == "INITIALIZED"
        assert health_data["subsystems"]["fastmcp_toolkit"] == "READY"

    def test_process_invoice_synchronous_flow(self):
        """Processes a clean invoice through LangGraph synchronously via REST."""
        payload = {
            "invoice_id": "INV-API-TEST-001",
            "buyer_id": "CORP-INFOSYS",
            "vendor_name_raw": "Reliance Ind.",
            "invoice_amount": 350_000.0,
            "currency": "USD",
            "due_date": "2026-11-30",
            "issue_date": "2026-10-01",
            "payment_terms_raw": "2/10 Net 60",
            "erp_source": "SAP_S4HANA",
        }

        res = client.post("/api/invoices/process", json=payload)
        assert res.status_code == 200
        data = res.json()

        assert data["status"] == "success"
        assert data["invoice_id"] == "INV-API-TEST-001"
        assert data["workflow_status"] == "DISPATCHED"

        # Verify state details
        state = data["data"]
        assert state["risk_profile"]["vendor_canonical_name"] == "Reliance Industries Ltd."
        assert state["optimal_structure"]["net_advance_to_supplier_usd"] > 0
        assert state["final_payload"]["offer_id"] is not None

        # Verify it appears in listing
        list_res = client.get("/api/invoices")
        assert list_res.status_code == 200
        items = list_res.json()
        assert any(item["invoice_id"] == "INV-API-TEST-001" for item in items)

        # Verify fetching individual invoice
        get_res = client.get("/api/invoices/INV-API-TEST-001")
        assert get_res.status_code == 200
        assert get_res.json()["invoice_id"] == "INV-API-TEST-001"

    def test_get_nonexistent_invoice_returns_404(self):
        """Unknown invoice ID returns 404."""
        res = client.get("/api/invoices/INV-DOES-NOT-EXIST")
        assert res.status_code == 404

    def test_simulation_scenarios(self):
        """Simulate pre-configured test scenarios for the frontend cockpit."""
        # 1. Clean Discounting
        res1 = client.post("/api/invoices/simulate?scenario=clean_discounting")
        assert res1.status_code == 200
        assert res1.json()["workflow_status"] == "DISPATCHED"

        # 2. Sanctioned Entity (Rosneft)
        res2 = client.post("/api/invoices/simulate?scenario=sanctioned_entity")
        assert res2.status_code == 200
        assert res2.json()["workflow_status"] == "REJECTED_SANCTIONS"

        # 3. Limit Overdraw ($500M)
        res3 = client.post("/api/invoices/simulate?scenario=limit_overdraw")
        assert res3.status_code == 200
        assert res3.json()["workflow_status"] == "REJECTED_GUARDRAIL"

        # 4. Invalid Scenario
        res4 = client.post("/api/invoices/simulate?scenario=invalid_scenario")
        assert res4.status_code == 400

    def test_sse_streaming_endpoint(self):
        """Verifies Server-Sent Events (SSE) telemetry stream delivers multi-agent updates."""
        with client.stream("GET", "/api/stream/invoice/INV-STREAM-TEST-01?amount=250000.0") as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")

            # Consume lines
            events: list[str] = []
            for line in response.iter_lines():
                if line.startswith("event:"):
                    events.append(line.replace("event:", "").strip())

            # Verify that essential workflow events were streamed
            assert "workflow_init" in events
            assert "agent_step" in events
            assert "workflow_complete" in events

    def test_one_click_approval_and_settlement_action(self):
        """Tests Treasurer 1-click authorization of a generated term sheet."""
        # 1. First process an invoice to generate an offer
        process_payload = {
            "invoice_id": "INV-OFFER-ACTION-001",
            "vendor_name_raw": "Reliance Ind.",
            "invoice_amount": 100_000.0,
            "currency": "USD",
            "due_date": "2026-11-30",
            "payment_terms_raw": "2/10 Net 60",
        }
        res = client.post("/api/invoices/process", json=process_payload)
        offer_id = res.json()["data"]["final_payload"]["offer_id"]
        token = res.json()["data"]["final_payload"]["approval_token"]

        # 2. Retrieve offer via GET /api/offers/{offer_id}
        get_offer_res = client.get(f"/api/offers/{offer_id}")
        assert get_offer_res.status_code == 200
        assert get_offer_res.json()["invoice_id"] == "INV-OFFER-ACTION-001"

        # 3. Authorize offer with 1-click action
        action_payload = {
            "decision": "APPROVED",
            "approver_role": "TREASURER",
            "approval_token": token,
            "notes": "Authorized by Corporate Treasurer for immediate settlement",
        }
        action_res = client.post(f"/api/offers/{offer_id}/action", json=action_payload)
        assert action_res.status_code == 200
        action_data = action_res.json()

        assert action_data["status"] == "success"
        assert action_data["execution_status"] == "EXECUTED_SETTLED"
        assert action_data["settlement_reference"] is not None
        assert action_data["settlement_reference"].startswith("SETTLE-CB-")

    def test_cash_curve_forecasting_endpoint(self):
        """Verifies 60-day cash curve forecasting data for frontend chart."""
        res = client.get("/api/forecast/cash-curve?buyer_id=CORP-INFOSYS&days=60")
        assert res.status_code == 200
        data = res.json()

        assert data["buyer_id"] == "CORP-INFOSYS"
        assert data["min_cash_floor"] == 10_000_000.0
        assert data["facility_limit"] == 150_000_000.0
        assert len(data["daily_curve"]) == 60

        first_pt = data["daily_curve"][0]
        assert "projected_cash" in first_pt
        assert "min_floor" in first_pt
        assert "facility_headroom" in first_pt

