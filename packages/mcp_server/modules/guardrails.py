"""
Module C: Guardrail & Limit Pre-Flight Validator
================================================
Deterministic pre-flight risk and compliance verification for corporate credit lines.

Ensures that no autonomous agent can ever float an offer that:
1. Breaches a corporate bank credit facility limit.
2. Exceeds single-supplier exposure concentration caps (e.g. max 15% of facility).
3. Engages an entity appearing on OFAC, PEP, or internal default registries.

Returns a cryptographically verifiable boolean pass/fail GuardrailVerdict.
"""

from __future__ import annotations

import hashlib
import time
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from packages.mcp_server.models.schemas import GuardrailVerdict


def _to_decimal(val: float | int | str | Decimal) -> Decimal:
    return Decimal(str(val))


def _round_cents(val: Decimal) -> float:
    return float(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def verify_facility_guardrails(
    buyer_id: str,
    supplier_canonical_id: str,
    proposed_amount: float,
    facility_limit: float,
    facility_drawn: float,
    single_supplier_concentration_cap_pct: float = 15.0,
    existing_supplier_exposure: float = 0.0,
    sanctions_watchlist: Optional[list[str]] = None,
    secret_salt: str = "SCF_GUARDRAIL_SECRET_2026",
) -> GuardrailVerdict:
    """
    Executes deterministic compliance and credit headroom validation before
    any financing payload can be generated or dispatched.
    """
    if proposed_amount <= 0:
        raise ValueError("proposed_amount must be strictly positive")
    if facility_limit <= 0:
        raise ValueError("facility_limit must be strictly positive")

    limit_d = _to_decimal(facility_limit)
    drawn_before_d = _to_decimal(facility_drawn)
    proposed_d = _to_decimal(proposed_amount)
    cap_pct_d = _to_decimal(single_supplier_concentration_cap_pct)
    existing_exp_d = _to_decimal(existing_supplier_exposure)

    breaches: list[str] = []

    # 1. Facility Limit Capacity Check
    drawn_after_d = drawn_before_d + proposed_d
    headroom_before_d = limit_d - drawn_before_d
    headroom_after_d = limit_d - drawn_after_d

    if drawn_after_d > limit_d:
        excess = drawn_after_d - limit_d
        breaches.append(
            f"FACILITY_HEADROOM_BREACH: Proposed amount ${proposed_amount:,.2f} exceeds available headroom ${headroom_before_d:,.2f} by ${excess:,.2f}"
        )

    # 2. Supplier Concentration Cap Check
    supplier_total_exposure_d = existing_exp_d + proposed_d
    supplier_concentration_pct_d = (
        (supplier_total_exposure_d / limit_d) * Decimal("100")
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if supplier_concentration_pct_d > cap_pct_d:
        max_allowed_d = (limit_d * (cap_pct_d / Decimal("100"))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        breaches.append(
            f"CONCENTRATION_CAP_BREACH: Total supplier exposure ${supplier_total_exposure_d:,.2f} ({supplier_concentration_pct_d}%) exceeds max allowable {cap_pct_d}% (${max_allowed_d:,.2f})"
        )

    # 3. Sanctions / Watchlist Screening
    sanctions_check_passed = True
    if sanctions_watchlist:
        normalized_supplier_id = supplier_canonical_id.strip().upper()
        for flagged_item in sanctions_watchlist:
            if flagged_item.strip().upper() == normalized_supplier_id:
                sanctions_check_passed = False
                breaches.append(
                    f"SANCTIONS_WATCHLIST_HIT: Supplier '{supplier_canonical_id}' matched blocked list entry '{flagged_item}'"
                )
                break

    is_approved = len(breaches) == 0
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # 4. Cryptographic Verification Signature
    sig_payload = f"{buyer_id}|{supplier_canonical_id}|{proposed_amount:.2f}|{is_approved}|{now_iso}|{secret_salt}"
    verification_sig = hashlib.sha256(sig_payload.encode("utf-8")).hexdigest()

    utilization_after_pct = (
        (drawn_after_d / limit_d) * Decimal("100")
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return GuardrailVerdict(
        is_approved=is_approved,
        buyer_id=buyer_id,
        supplier_canonical_id=supplier_canonical_id,
        proposed_amount=_round_cents(proposed_d),
        facility_limit=_round_cents(limit_d),
        facility_drawn_before=_round_cents(drawn_before_d),
        facility_drawn_after=_round_cents(drawn_after_d),
        facility_utilization_pct_after=float(utilization_after_pct),
        headroom_available=_round_cents(headroom_after_d),
        supplier_concentration_pct=float(supplier_concentration_pct_d),
        single_supplier_concentration_cap_pct=float(cap_pct_d),
        sanctions_check_passed=sanctions_check_passed,
        breaches=breaches,
        verdict_timestamp=now_iso,
        verification_signature=verification_sig,
    )

