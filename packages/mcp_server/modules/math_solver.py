"""
Module B: Deterministic Working Capital Math Solver
===================================================
Audit-grade, deterministic financial calculation engine for Supply Chain Finance.

Enforces the "Iron Wall" boundary:
LLMs must NEVER perform arithmetic, calculate APRs, or compute money splits.
This module executes all trade finance math with decimal.Decimal precision
under FASB ASC 310 guidelines.

Capabilities:
1. Dynamic Discounting Sliding Scale: Computes linear acceleration discount,
   implied APR, supplier advance, and buyer cash-on-cash yield.
2. Reverse Factoring (Bank-Funded) Mechanics: Computes all-in financing rate,
   supplier haircut, Bank Net Interest Margin (NIM), and buyer corporate rebate.
3. Day-Count Conventions: Supports ACT/360 (Money Market / US Bank Standard)
   and ACT/365 (Bond / UK Standard).
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from packages.mcp_server.models.schemas import (
    DynamicDiscountResult,
    ReverseFactoringResult,
)


def _to_decimal(val: float | int | str | Decimal) -> Decimal:
    """Helper converting any numerical input to a Decimal safely."""
    return Decimal(str(val))


def _round_cents(val: Decimal) -> float:
    """Rounds Decimal to 2 decimal places (bank cents) using ROUND_HALF_UP."""
    return float(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _round_pct(val: Decimal) -> float:
    """Rounds Decimal percentage to 4 decimal places."""
    return float(val.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def calculate_dynamic_discount(
    invoice_amount: float,
    days_accelerated: int,
    total_tenor_days: int,
    buyer_hurdle_rate_apr: float,
    baseline_discount_pct: float = 2.0,
    day_count_convention: str = "ACT/365",
) -> DynamicDiscountResult:
    """
    Computes exact Dynamic Discounting economics.

    Formula:
        Sliding Scale Discount Rate d = baseline_discount_pct * (days_accelerated / total_tenor_days)
        Discount Amount Δ = invoice_amount * (d / 100)
        Net Supplier Payout = invoice_amount - Δ
        Implied APR = (Δ / Net Payout) * (Basis / days_accelerated) * 100
        Buyer Yield = Δ
    """
    if invoice_amount <= 0:
        raise ValueError("invoice_amount must be strictly positive")
    if total_tenor_days <= 0:
        raise ValueError("total_tenor_days must be strictly positive")
    if days_accelerated <= 0:
        raise ValueError("days_accelerated must be at least 1 day for early financing")
    if days_accelerated > total_tenor_days:
        raise ValueError(
            f"days_accelerated ({days_accelerated}) cannot exceed total_tenor_days ({total_tenor_days})"
        )

    amt = _to_decimal(invoice_amount)
    days_acc = _to_decimal(days_accelerated)
    tenor = _to_decimal(total_tenor_days)
    base_disc = _to_decimal(baseline_discount_pct)
    hurdle = _to_decimal(buyer_hurdle_rate_apr)

    basis_val = Decimal("360") if "360" in day_count_convention.upper() else Decimal("365")

    # Sliding scale discount rate: d = base_disc * (days_acc / tenor)
    applied_discount_rate = (base_disc * (days_acc / tenor)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )

    # Discount amount in currency: Δ = amt * (applied_discount_rate / 100)
    discount_amount = (amt * (applied_discount_rate / Decimal("100"))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    # Supplier payout: Net = amt - discount_amount
    net_payout = amt - discount_amount

    # Implied APR: (Δ / Net) * (Basis / days_acc) * 100
    if net_payout > 0 and days_acc > 0:
        implied_apr = (
            (discount_amount / net_payout) * (basis_val / days_acc) * Decimal("100")
        ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    else:
        implied_apr = Decimal("0.0")

    hurdle_exceeded = bool(implied_apr >= hurdle)
    spread_over_hurdle = implied_apr - hurdle

    return DynamicDiscountResult(
        instrument_type="DYNAMIC_DISCOUNTING",
        invoice_amount=_round_cents(amt),
        days_accelerated=days_accelerated,
        total_tenor_days=total_tenor_days,
        applied_discount_pct=_round_pct(applied_discount_rate),
        discount_amount=_round_cents(discount_amount),
        net_advance_to_supplier=_round_cents(net_payout),
        buyer_yield_usd=_round_cents(discount_amount),
        implied_apr_pct=_round_pct(implied_apr),
        day_count_convention="ACT/360" if "360" in day_count_convention.upper() else "ACT/365",
        buyer_hurdle_rate_apr=_round_pct(hurdle),
        hurdle_rate_exceeded=hurdle_exceeded,
        annualized_spread_over_hurdle_pct=_round_pct(spread_over_hurdle),
    )


def simulate_reverse_factoring_spread(
    invoice_amount: float,
    days_accelerated: int,
    base_benchmark_rate: float,
    bank_margin_spread: float,
    platform_fee_pct: float = 0.20,
    buyer_rebate_share_pct: float = 0.30,
) -> ReverseFactoringResult:
    """
    Computes exact Bank-Funded Reverse Factoring economics (Payables Finance).

    Convention: Standard Trade Finance utilizes ACT/360 basis for money market pricing.
    Formula:
        All-in Financing Rate r = base_benchmark_rate + bank_margin_spread + platform_fee_pct
        Supplier Financing Haircut = invoice_amount * (r / 100) * (days_accelerated / 360)
        Net Supplier Payout = invoice_amount - Supplier Financing Haircut
        Bank Gross Revenue = invoice_amount * ((base_benchmark + margin) / 100) * (days_accelerated / 360)
        Bank Net Interest Margin = invoice_amount * (margin / 100) * (days_accelerated / 360)
        Corporate Buyer Rebate = Bank NIM * buyer_rebate_share_pct
    """
    if invoice_amount <= 0:
        raise ValueError("invoice_amount must be strictly positive")
    if days_accelerated <= 0:
        raise ValueError("days_accelerated must be at least 1 day")

    amt = _to_decimal(invoice_amount)
    days_acc = _to_decimal(days_accelerated)
    benchmark = _to_decimal(base_benchmark_rate)
    margin = _to_decimal(bank_margin_spread)
    platform_fee = _to_decimal(platform_fee_pct)
    rebate_share = _to_decimal(buyer_rebate_share_pct)
    basis_360 = Decimal("360")

    # All-in financing rate
    all_in_rate = benchmark + margin + platform_fee

    # Time fraction
    time_factor = days_acc / basis_360

    # Supplier financing cost: haircut
    supplier_cost = (amt * (all_in_rate / Decimal("100")) * time_factor).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    # Net advance to supplier
    net_payout = amt - supplier_cost

    # Bank gross revenue (benchmark interest + bank margin)
    bank_gross = (amt * ((benchmark + margin) / Decimal("100")) * time_factor).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    # Bank Net Interest Margin (pure spread above cost of funds)
    bank_nim = (amt * (margin / Decimal("100")) * time_factor).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    # Corporate buyer rebate (working capital program yield sharing)
    buyer_rebate = (bank_nim * rebate_share).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    return ReverseFactoringResult(
        instrument_type="REVERSE_FACTORING",
        invoice_amount=_round_cents(amt),
        days_accelerated=days_accelerated,
        base_benchmark_rate_pct=_round_pct(benchmark),
        bank_margin_spread_pct=_round_pct(margin),
        platform_fee_pct=_round_pct(platform_fee),
        all_in_financing_rate_pct=_round_pct(all_in_rate),
        supplier_financing_cost_usd=_round_cents(supplier_cost),
        net_advance_to_supplier=_round_cents(net_payout),
        bank_gross_interest_income_usd=_round_cents(bank_gross),
        bank_net_interest_margin_usd=_round_cents(bank_nim),
        buyer_rebate_share_pct=_round_pct(rebate_share * Decimal("100")),
        buyer_rebate_usd=_round_cents(buyer_rebate),
        day_count_convention="ACT/360",
    )

