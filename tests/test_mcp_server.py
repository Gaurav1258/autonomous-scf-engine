"""
tests/test_mcp_server.py
========================
Tests for the scf-agent-toolkit FastMCP Server tools.

Verifies that all 6 exposed tools callable via MCP execute without error
and return audit-grade data structures.
"""

from __future__ import annotations

import pytest

from packages.mcp_server.server import (
    calculate_dynamic_discount,
    extract_trade_context,
    predict_supplier_acceptance_curve,
    predict_supplier_acceptance_probability,
    simulate_reverse_factoring_spread,
    verify_facility_guardrails,
)


class TestMCPServerTools:
    """Verifies that all FastMCP tools return valid dict responses."""

    def test_tool_extract_trade_context(self):
        raw_invoice = {
            "invoice_id": "INV-MCP-001",
            "erp_source": "SAP",
            "vendor_name_raw": "Reliance Ind.",
            "buyer_id": "CORP-INFOSYS",
            "invoice_amount": 150000.0,
            "currency": "USD",
            "issue_date": "2026-10-01",
            "due_date": "2026-11-30",
            "payment_terms_raw": "2/10 Net 60",
        }
        res = extract_trade_context(raw_invoice)
        assert isinstance(res, dict)
        assert res["invoice_id"] == "INV-MCP-001"
        assert res["vendor_canonical_name"] == "Reliance Industries Ltd."
        assert "summary_markdown" in res

    def test_tool_calculate_dynamic_discount(self):
        res = calculate_dynamic_discount(
            invoice_amount=500000.0,
            days_accelerated=30,
            total_tenor_days=60,
            buyer_hurdle_rate_apr=10.0,
            baseline_discount_pct=2.0,
        )
        assert isinstance(res, dict)
        assert res["instrument_type"] == "DYNAMIC_DISCOUNTING"
        assert res["discount_amount"] == 5000.0
        assert res["net_advance_to_supplier"] == 495000.0
        assert res["hurdle_rate_exceeded"] is True

    def test_tool_simulate_reverse_factoring_spread(self):
        res = simulate_reverse_factoring_spread(
            invoice_amount=500000.0,
            days_accelerated=45,
            base_benchmark_rate=5.33,
            bank_margin_spread=1.80,
        )
        assert isinstance(res, dict)
        assert res["instrument_type"] == "REVERSE_FACTORING"
        assert res["day_count_convention"] == "ACT/360"
        assert res["all_in_financing_rate_pct"] == 7.33

    def test_tool_verify_facility_guardrails(self):
        res = verify_facility_guardrails(
            buyer_id="CORP-INFOSYS",
            supplier_canonical_id="SUPP-00001",
            proposed_amount=1000000.0,
            facility_limit=50000000.0,
            facility_drawn=10000000.0,
        )
        assert isinstance(res, dict)
        assert res["is_approved"] is True
        assert len(res["verification_signature"]) == 64

    def test_tool_predict_supplier_acceptance_probability(self):
        features = {
            "supplier_risk_tier": "TIER_2_STABLE",
            "supplier_sector": "Manufacturing",
            "buyer_sector": "Conglomerate",
            "instrument_type": "DYNAMIC_DISCOUNTING",
            "supplier_alt_cost_of_debt_apr": 14.0,
            "supplier_dso_days": 65.0,
            "supplier_historical_acceptance_rate": 0.55,
            "is_anchor_buyer": 1,
            "days_since_last_trade": 18,
            "invoice_face_value_usd": 250000.0,
            "original_tenor_days": 60,
            "days_accelerated": 35,
            "offered_discount_pct": 1.25,
            "implied_apr": 13.25,
            "quarter_end_flag": 0,
        }
        res = predict_supplier_acceptance_probability(features)
        assert isinstance(res, dict)
        assert "acceptance_probability" in res
        assert 0.0 <= res["acceptance_probability"] <= 1.0

    def test_tool_predict_supplier_acceptance_curve(self):
        features = {
            "supplier_risk_tier": "TIER_2_STABLE",
            "supplier_sector": "Manufacturing",
            "buyer_sector": "Conglomerate",
            "instrument_type": "DYNAMIC_DISCOUNTING",
            "supplier_alt_cost_of_debt_apr": 14.0,
            "supplier_dso_days": 65.0,
            "supplier_historical_acceptance_rate": 0.55,
            "is_anchor_buyer": 1,
            "days_since_last_trade": 18,
            "invoice_face_value_usd": 250000.0,
            "original_tenor_days": 60,
            "days_accelerated": 35,
            "quarter_end_flag": 0,
        }
        curve = predict_supplier_acceptance_curve(features, discount_rates=[0.5, 1.0, 1.5, 2.0])
        assert isinstance(curve, list)
        assert len(curve) == 4
        assert curve[0]["discount_pct"] == 0.5
        assert curve[-1]["discount_pct"] == 2.0

