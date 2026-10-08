"""
tests/test_guardrails.py
========================
Rigorous test suite for Module C: Guardrail & Limit Pre-Flight Validator.

Verifies:
1. Approved Path: Clean transaction within headroom, under concentration cap, clean watchlist.
2. Facility Overdraw Breach: Blocks transactions exceeding undrawn limit.
3. Concentration Cap Breach: Blocks transactions exceeding single-supplier exposure cap (15%).
4. Sanctions Watchlist Breach: Deterministically blocks counterparties on watchlists.
5. Multiple Breaches: Accumulates all independent covenant violations.
6. Cryptographic Signatures: Produces verifiable 64-char hex SHA256 digest.
"""

from __future__ import annotations

import pytest

from packages.mcp_server.modules.guardrails import verify_facility_guardrails


class TestGuardrailValidator:
    """Unit tests for verify_facility_guardrails()."""

    def test_clean_approval_scenario(self):
        # Limit $100M, drawn $35M, available $65M.
        # Proposed $2.5M. Existing supplier exposure: $5M.
        # Concentration = (5 + 2.5) / 100 = 7.5% <= 15% cap.
        verdict = verify_facility_guardrails(
            buyer_id="CORP-INFOSYS",
            supplier_canonical_id="SUPP-00001",
            proposed_amount=2_500_000.0,
            facility_limit=100_000_000.0,
            facility_drawn=35_000_000.0,
            single_supplier_concentration_cap_pct=15.0,
            existing_supplier_exposure=5_000_000.0,
            sanctions_watchlist=["BLOCKED-ENTITY-99"],
        )

        assert verdict.is_approved is True
        assert len(verdict.breaches) == 0
        assert verdict.facility_drawn_after == 37_500_000.0
        assert verdict.facility_utilization_pct_after == 37.5
        assert verdict.headroom_available == 62_500_000.0
        assert verdict.supplier_concentration_pct == 7.5
        assert verdict.sanctions_check_passed is True
        assert len(verdict.verification_signature) == 64

    def test_facility_overdraw_breach(self):
        # Limit $50M, drawn $48M, available $2M.
        # Proposed $3.5M (exceeds headroom by $1.5M).
        verdict = verify_facility_guardrails(
            buyer_id="CORP-TATA",
            supplier_canonical_id="SUPP-00002",
            proposed_amount=3_500_000.0,
            facility_limit=50_000_000.0,
            facility_drawn=48_000_000.0,
        )

        assert verdict.is_approved is False
        assert any("FACILITY_HEADROOM_BREACH" in b for b in verdict.breaches)
        assert verdict.headroom_available < 0

    def test_supplier_concentration_cap_breach(self):
        # Limit $100M, drawn $20M.
        # Existing supplier exposure: $12M. Proposed: $5M.
        # Total supplier exposure = $17M (17% > 15% cap).
        verdict = verify_facility_guardrails(
            buyer_id="CORP-RELIANCE",
            supplier_canonical_id="SUPP-00003",
            proposed_amount=5_000_000.0,
            facility_limit=100_000_000.0,
            facility_drawn=20_000_000.0,
            single_supplier_concentration_cap_pct=15.0,
            existing_supplier_exposure=12_000_000.0,
        )

        assert verdict.is_approved is False
        assert any("CONCENTRATION_CAP_BREACH" in b for b in verdict.breaches)
        assert verdict.supplier_concentration_pct == 17.0

    def test_sanctions_watchlist_hit_blocks_offer(self):
        watchlist = ["SUPP-SANCTIONED-007", "OFAC-BAD-ACTOR"]
        verdict = verify_facility_guardrails(
            buyer_id="CORP-WALMART",
            supplier_canonical_id="SUPP-SANCTIONED-007",
            proposed_amount=100_000.0,
            facility_limit=100_000_000.0,
            facility_drawn=10_000_000.0,
            sanctions_watchlist=watchlist,
        )

        assert verdict.is_approved is False
        assert verdict.sanctions_check_passed is False
        assert any("SANCTIONS_WATCHLIST_HIT" in b for b in verdict.breaches)

    def test_multiple_breaches_accumulated(self):
        # Both limit overdraw AND sanctions match
        verdict = verify_facility_guardrails(
            buyer_id="CORP-TEST",
            supplier_canonical_id="BLOCKED-SUPP",
            proposed_amount=15_000_000.0,
            facility_limit=10_000_000.0,
            facility_drawn=5_000_000.0,
            sanctions_watchlist=["BLOCKED-SUPP"],
        )

        assert verdict.is_approved is False
        assert len(verdict.breaches) >= 2
        assert any("FACILITY_HEADROOM_BREACH" in b for b in verdict.breaches)
        assert any("SANCTIONS_WATCHLIST_HIT" in b for b in verdict.breaches)

    def test_invalid_negative_amount_raises_value_error(self):
        with pytest.raises(ValueError, match="strictly positive"):
            verify_facility_guardrails(
                buyer_id="CORP-01",
                supplier_canonical_id="SUPP-01",
                proposed_amount=-1000.0,
                facility_limit=100000.0,
                facility_drawn=0.0,
            )

