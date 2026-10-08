"""
tests/test_normalizer.py
========================
Rigorous test suite for Module A: Trade Ledger Context Normalizer.

Verifies:
1. Payment Term Parser: Parses standard, fractional, and edge-case ERP term strings.
2. RapidFuzz Entity Resolution: Maps messy vendor names to canonical Golden Records.
3. Duplicate & Idempotency Sentinel: Prevents double-financing and duplicate receivables.
4. End-to-End Extraction: Produces valid CleanTradeContext objects with token-optimized markdown.

Run:
    uv run pytest tests/test_normalizer.py -v
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from packages.mcp_server.modules.normalizer import (
    check_duplicate_invoice,
    compute_idempotency_hash,
    extract_trade_context,
    parse_payment_terms,
    resolve_vendor_entity,
)


@pytest.fixture(scope="module")
def sample_vendor_master() -> list[dict]:
    """Sample vendor master with canonical names and registered aliases."""
    return [
        {
            "supplier_id": "SUPP-00001",
            "canonical_name": "Reliance Industries Ltd.",
            "name_aliases": [
                "Reliance Ind.",
                "RELIANCE IND LTD",
                "Reliance Industries",
                "RELIANCE INDS.",
            ],
            "tax_id": "12-3456789",
            "gstin": "27AAACR1234A1Z5",
            "sector": "Conglomerate",
            "risk_tier": "TIER_1_PRIME",
        },
        {
            "supplier_id": "SUPP-00002",
            "canonical_name": "Tata Consultancy Services Ltd.",
            "name_aliases": [
                "TCS Ltd.",
                "TATA CONSULTANCY SERV",
                "Tata Consultancy",
                "T.C.S. Limited",
            ],
            "tax_id": "98-7654321",
            "gstin": "27AAACT5678B1Z2",
            "sector": "IT Services",
            "risk_tier": "TIER_1_PRIME",
        },
        {
            "supplier_id": "SUPP-00003",
            "canonical_name": "Mahindra & Mahindra Ltd.",
            "name_aliases": [
                "M&M Ltd",
                "MAHINDRA AND MAHINDRA",
                "Mahindra Mahindra",
            ],
            "tax_id": "45-6789012",
            "gstin": "27AAACM9012C1Z8",
            "sector": "Manufacturing",
            "risk_tier": "TIER_2_STABLE",
        },
    ]


class TestPaymentTermsParser:
    """Tests for regex-based and heuristic ERP term parsing."""

    def test_standard_2_10_net_60(self):
        terms = parse_payment_terms("2/10 Net 60")
        assert terms.discount_percentage == 2.0
        assert terms.discount_days == 10
        assert terms.net_days == 60
        assert terms.is_discount_available is True

    def test_fractional_discount_terms(self):
        terms = parse_payment_terms("1.5/15 Net 45")
        assert terms.discount_percentage == 1.5
        assert terms.discount_days == 15
        assert terms.net_days == 45
        assert terms.is_discount_available is True

    def test_slash_n_notation(self):
        terms = parse_payment_terms("2/10, n/60")
        assert terms.discount_percentage == 2.0
        assert terms.discount_days == 10
        assert terms.net_days == 60

    def test_simple_net_90_no_discount(self):
        terms = parse_payment_terms("Net 90")
        assert terms.discount_percentage == 0.0
        assert terms.discount_days == 0
        assert terms.net_days == 90
        assert terms.is_discount_available is False

    def test_simple_net_30_no_discount(self):
        terms = parse_payment_terms("Net 30")
        assert terms.discount_percentage == 0.0
        assert terms.net_days == 30
        assert terms.is_discount_available is False

    def test_eom_terms(self):
        terms = parse_payment_terms("EOM + 30")
        assert terms.net_days == 60  # EOM (~30) + 30 = 60
        assert terms.discount_percentage == 0.0

    def test_empty_or_whitespace_defaults_gracefully(self):
        terms = parse_payment_terms("   ")
        assert terms.net_days == 30
        assert terms.discount_percentage == 0.0


class TestVendorEntityResolution:
    """Tests for RapidFuzz fuzzy entity mapping against Golden Records."""

    def test_exact_match(self, sample_vendor_master):
        vendor, alias, score = resolve_vendor_entity(
            "Reliance Industries Ltd.", sample_vendor_master
        )
        assert vendor["supplier_id"] == "SUPP-00001"
        assert vendor["canonical_name"] == "Reliance Industries Ltd."
        assert score >= 95.0

    def test_alias_reliance_ind(self, sample_vendor_master):
        vendor, alias, score = resolve_vendor_entity(
            "Reliance Ind.", sample_vendor_master
        )
        assert vendor["supplier_id"] == "SUPP-00001"
        assert vendor["canonical_name"] == "Reliance Industries Ltd."
        assert score >= 80.0

    def test_alias_tcs_ltd(self, sample_vendor_master):
        vendor, alias, score = resolve_vendor_entity(
            "TCS Ltd.", sample_vendor_master
        )
        assert vendor["supplier_id"] == "SUPP-00002"
        assert vendor["canonical_name"] == "Tata Consultancy Services Ltd."
        assert score >= 80.0

    def test_alias_all_caps_variation(self, sample_vendor_master):
        vendor, alias, score = resolve_vendor_entity(
            "MAHINDRA AND MAHINDRA", sample_vendor_master
        )
        assert vendor["supplier_id"] == "SUPP-00003"
        assert vendor["canonical_name"] == "Mahindra & Mahindra Ltd."
        assert score >= 85.0

    def test_unknown_vendor_falls_back_cleanly(self, sample_vendor_master):
        vendor, alias, score = resolve_vendor_entity(
            "Extraterrestrial Galactic Trading LLC", sample_vendor_master
        )
        assert vendor["supplier_id"] == "SUPP-UNREGISTERED"
        assert vendor["canonical_name"] == "Extraterrestrial Galactic Trading LLC"
        assert score < 65.0


class TestIdempotencyAndDuplicateDetection:
    """Tests for deterministic SHA256 hashing and open ledger cross-checks."""

    def test_idempotency_hash_determinism(self):
        h1 = compute_idempotency_hash("BUYER-01", "SUPP-001", "INV-100", 50000.0, "USD")
        h2 = compute_idempotency_hash("BUYER-01", "SUPP-001", "INV-100", 50000.0, "USD")
        assert h1 == h2
        assert len(h1) == 64  # SHA256 hex length

    def test_different_amount_changes_hash(self):
        h1 = compute_idempotency_hash("BUYER-01", "SUPP-001", "INV-100", 50000.0, "USD")
        h2 = compute_idempotency_hash("BUYER-01", "SUPP-001", "INV-100", 50000.01, "USD")
        assert h1 != h2

    def test_detects_existing_invoice_id(self):
        open_ledger = [
            {"invoice_id": "INV-100", "idempotency_hash": "abc", "status": "FINANCED"}
        ]
        is_dup, reason = check_duplicate_invoice("INV-100", "xyz", open_ledger)
        assert is_dup is True
        assert "already exists in ledger" in reason

    def test_detects_matching_idempotency_hash(self):
        open_ledger = [
            {"invoice_id": "INV-999", "idempotency_hash": "hash_match_123", "status": "OPEN"}
        ]
        is_dup, reason = check_duplicate_invoice("INV-DIFFERENT-ID", "hash_match_123", open_ledger)
        assert is_dup is True
        assert "Identical receivable payload hash detected" in reason

    def test_cleared_when_no_duplicate(self):
        open_ledger = [
            {"invoice_id": "INV-999", "idempotency_hash": "hash_123", "status": "OPEN"}
        ]
        is_dup, reason = check_duplicate_invoice("INV-NEW", "hash_456", open_ledger)
        assert is_dup is False
        assert reason is None


class TestExtractTradeContextEndToEnd:
    """Tests for the primary extract_trade_context tool function."""

    def test_extract_trade_context_pipeline(self, sample_vendor_master):
        raw_invoice = {
            "invoice_id": "INV-2026-SAP-8812",
            "erp_source": "SAP_S4HANA",
            "vendor_name_raw": "Reliance Ind.",
            "buyer_id": "CORP-INFOSYS",
            "invoice_amount": 340000.0,
            "currency": "USD",
            "issue_date": "2026-10-01",
            "due_date": "2026-11-30",
            "payment_terms_raw": "2/10 Net 60",
        }

        context = extract_trade_context(
            raw_invoice=raw_invoice,
            vendor_master=sample_vendor_master,
            open_ledger=[],
        )

        assert context.invoice_id == "INV-2026-SAP-8812"
        assert context.vendor_canonical_name == "Reliance Industries Ltd."
        assert context.vendor_canonical_id == "SUPP-00001"
        assert context.match_confidence_score >= 80.0
        assert context.tax_id == "12-3456789"
        assert context.payment_terms.discount_percentage == 2.0
        assert context.payment_terms.net_days == 60
        assert context.is_duplicate is False
        assert len(context.idempotency_hash) == 64
        assert "Reliance Industries Ltd." in context.summary_markdown
        assert "2.0% within 10 days" in context.summary_markdown

