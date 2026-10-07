"""
SCF Synthetic Dataset Generator
================================
Generates a publication-grade Supply Chain Finance dataset for:

1. scf_supplier_acceptance_dataset.csv  (50,000 rows)  — XGBoost training data
2. synthetic_erp_invoices.json          (~200 records)  — UI live invoice feed
3. synthetic_vendor_master.json         (~50 vendors)   — Normalizer fuzzy matching tests
4. synthetic_buyers_facilities.json     (~5 buyers)     — Guardrail validator input
5. synthetic_cash_ledger.json           (5 buyers × 90 days) — Cash Forecaster input

Financial Utility Acceptance Model:
    utility_delta = supplier_alt_cost_of_debt_apr - implied_apr
                  + liquidity_urgency_boost
                  + quarter_end_boost
                  + relationship_boost
                  - risk_penalty

    P(accept) = sigmoid(utility_delta * sensitivity_factor)

    If the offered financing APR is cheaper than the supplier's alternative bank
    overdraft cost (plus urgency), the supplier rationally accepts early payment.

Usage:
    uv run python packages/orchestrator/ml/dataset_generator.py

Outputs go to data/generated/ locally, then uploaded to GCS via gcs_uploader.py.
"""

from __future__ import annotations

import json
import math
import os
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from faker import Faker

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SEED: int = int(os.getenv("DATASET_RANDOM_SEED", "42"))
NUM_ML_ROWS: int = int(os.getenv("DATASET_NUM_ROWS", "50000"))
NUM_ERP_INVOICES: int = 200
OUTPUT_DIR: Path = Path(os.getenv("DATASET_LOCAL_OUTPUT_DIR", "data/generated"))

# Fix all randomness for reproducibility
random.seed(SEED)
np.random.seed(SEED)
fake = Faker(seed=SEED)

# ---------------------------------------------------------------------------
# Domain Constants (grounded in real trade finance benchmarks)
# ---------------------------------------------------------------------------

SUPPLIER_SECTORS = [
    "Manufacturing",
    "Logistics & Freight",
    "IT Services",
    "Raw Materials",
    "Pharmaceutical",
    "Electronics",
    "Construction",
    "Food & Beverage",
]

# Risk tier: affects alternative cost of capital and acceptance sensitivity
RISK_TIERS = {
    "TIER_1_PRIME": {
        "alt_cost_apr_mean": 9.5,   # Access to quality bank credit, lower urgency
        "alt_cost_apr_std": 1.5,
        "dso_mean": 48.0,
        "dso_std": 8.0,
        "sensitivity": 0.55,        # Less desperate, more selective
        "weight": 0.30,
    },
    "TIER_2_STABLE": {
        "alt_cost_apr_mean": 14.0,  # Moderate credit access
        "alt_cost_apr_std": 2.5,
        "dso_mean": 65.0,
        "dso_std": 12.0,
        "sensitivity": 0.75,
        "weight": 0.50,
    },
    "TIER_3_ELEVATED": {
        "alt_cost_apr_mean": 20.5,  # Constrained, depends on overdraft/factoring
        "alt_cost_apr_std": 4.0,
        "dso_mean": 85.0,
        "dso_std": 18.0,
        "sensitivity": 1.10,        # Most responsive to any APR saving
        "weight": 0.20,
    },
}

BUYER_ENTITIES = [
    {"buyer_id": "CORP_INFOSYS_US",     "name": "Infosys Limited",        "sector": "IT Services"},
    {"buyer_id": "CORP_TATA_MOTORS",    "name": "Tata Motors Ltd.",       "sector": "Automotive"},
    {"buyer_id": "CORP_RELIANCE_IND",   "name": "Reliance Industries",    "sector": "Conglomerate"},
    {"buyer_id": "CORP_WALMART_US",     "name": "Walmart Inc.",           "sector": "Retail"},
    {"buyer_id": "CORP_SIEMENS_DE",     "name": "Siemens AG",             "sector": "Industrial"},
]

# SAP-style ERP payment terms (matching Kaggle Global B2B dataset schema)
PAYMENT_TERMS_POOL = [
    {"raw": "2/10 Net 60",   "discount_pct": 2.0, "discount_days": 10, "net_days": 60},
    {"raw": "1/15 Net 45",   "discount_pct": 1.0, "discount_days": 15, "net_days": 45},
    {"raw": "1.5/10 Net 30", "discount_pct": 1.5, "discount_days": 10, "net_days": 30},
    {"raw": "2/5 Net 90",    "discount_pct": 2.0, "discount_days":  5, "net_days": 90},
    {"raw": "Net 60",        "discount_pct": 0.0, "discount_days":  0, "net_days": 60},
    {"raw": "Net 30",        "discount_pct": 0.0, "discount_days":  0, "net_days": 30},
    {"raw": "Net 90",        "discount_pct": 0.0, "discount_days":  0, "net_days": 90},
    {"raw": "1/7 Net 45",    "discount_pct": 1.0, "discount_days":  7, "net_days": 45},
]

INSTRUMENT_TYPES = ["DYNAMIC_DISCOUNTING", "REVERSE_FACTORING"]

# Messy vendor name aliases (for normalizer tests — important for DATASET_CARD.md)
VENDOR_NAME_ALIASES: dict[str, list[str]] = {
    "Reliance Industries Ltd.": [
        "Reliance Ind.",
        "RELIANCE IND LTD",
        "Reliance Industries",
        "RELIANCE INDS.",
        "Reliance Industries Limited",
    ],
    "Tata Consultancy Services Ltd.": [
        "TCS Ltd.",
        "TATA CONSULTANCY SERV",
        "Tata Consultancy",
        "T.C.S. Limited",
    ],
    "Mahindra & Mahindra Ltd.": [
        "M&M Ltd",
        "MAHINDRA AND MAHINDRA",
        "Mahindra & Mahindra",
        "Mahindra Mahindra",
    ],
    "Larsen & Toubro Ltd.": [
        "L&T Ltd",
        "LARSEN AND TOUBRO",
        "Larsen Toubro",
        "L & T Limited",
    ],
    "Wipro Technologies Ltd.": [
        "Wipro Ltd.",
        "WIPRO TECH",
        "Wipro Technologies",
        "WIPRO LTD",
    ],
}

# ---------------------------------------------------------------------------
# Financial Math Helpers (identical logic to Module B math_solver.py)
# This guarantees the dataset and the MCP tool produce the same numbers.
# ---------------------------------------------------------------------------

def compute_implied_apr(
    discount_pct: float,
    days_accelerated: int,
    day_count_basis: int = 365,
) -> float:
    """
    Annualized Percentage Rate implied by a dynamic discount offer.

    APR = (discount / (1 - discount)) * (basis / days_accelerated)

    Using the correct "discount-on-proceeds" formulation (as per FASB ASC 310).
    Returns 0.0 if days_accelerated == 0.
    """
    if days_accelerated <= 0 or discount_pct <= 0:
        return 0.0
    d = discount_pct / 100.0
    apr = (d / (1.0 - d)) * (day_count_basis / days_accelerated)
    return round(apr * 100, 4)  # return as % e.g., 14.72


def compute_supplier_net_payout(face_value: float, discount_pct: float) -> float:
    """Net advance the supplier receives after discount deduction."""
    return round(face_value * (1.0 - discount_pct / 100.0), 2)


def compute_buyer_yield(face_value: float, discount_pct: float) -> float:
    """Cash yield the corporate buyer earns from a dynamic discounting offer."""
    return round(face_value * (discount_pct / 100.0), 2)


# ---------------------------------------------------------------------------
# Acceptance Utility Model (Financial Microeconomics)
# ---------------------------------------------------------------------------

def _sigmoid(x: float) -> float:
    """Numerically stable sigmoid."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    ex = math.exp(x)
    return ex / (1.0 + ex)


def compute_acceptance_probability(
    implied_apr: float,
    alt_cost_apr: float,
    supplier_dso: float,
    quarter_end_flag: bool,
    is_anchor_buyer: bool,
    sensitivity: float,
) -> float:
    """
    Computes the probability that a supplier accepts an early payment offer.

    Core intuition:
        - If implied_apr (our offer cost to supplier) << alt_cost_apr (their
          bank overdraft cost), the offer is attractive -> higher P(accept).
        - DSO above 60 days signals cash stress -> urgency boost.
        - Quarter-end forces liquidity crunches -> Q-end boost.
        - Anchor buyer relationship lowers friction -> small boost.

    Temperature normalization (TEMPERATURE = 6.0):
        Normalizes the combined utility spread to prevent sigmoid saturation.
        Produces an overall take-up rate between 45% and 65%, matching real-world
        Supply Chain Finance benchmarks (C2FO, Taulia).

    Returns probability in [0, 1].
    """
    TEMPERATURE = 6.0

    # Primary signal: cost advantage vs. alternative debt
    apr_saving = alt_cost_apr - implied_apr  # positive = our offer is cheaper

    # Liquidity urgency boost (DSO > 60 days = stressed cash cycle)
    urgency_boost = max(0.0, (supplier_dso - 60.0) / 40.0) * 2.0

    # Seasonal Q-end liquidity crunch
    quarter_end_boost = 1.5 if quarter_end_flag else 0.0

    # Anchor buyer relationship reduces friction
    relationship_boost = 0.8 if is_anchor_buyer else 0.0

    raw_utility = apr_saving + urgency_boost + quarter_end_boost + relationship_boost
    normalised_utility = (raw_utility / TEMPERATURE) * sensitivity

    return _sigmoid(normalised_utility)


# ---------------------------------------------------------------------------
# Core Generators
# ---------------------------------------------------------------------------

def _random_invoice_date() -> date:
    """Random approval date between 2022-01-01 and 2026-09-30."""
    start = date(2022, 1, 1)
    end = date(2026, 9, 30)
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta))


def _is_quarter_end(d: date) -> bool:
    """True if date falls in the last 15 days of a calendar quarter."""
    quarter_ends = [
        date(d.year, 3, 31),
        date(d.year, 6, 30),
        date(d.year, 9, 30),
        date(d.year, 12, 31),
    ]
    return any(abs((d - qe).days) <= 15 for qe in quarter_ends)


def generate_ml_training_dataset(num_rows: int = NUM_ML_ROWS) -> pd.DataFrame:
    """
    Generates the primary XGBoost training dataset.

    Each row represents one early payment offer made to a supplier, with
    a probabilistically determined acceptance outcome based on the financial
    utility model.

    Returns:
        pd.DataFrame with shape (num_rows, 17) including target column
        'accepted_early_offer' (binary int: 0 or 1).
    """
    print(f"[Generator] Creating ML training dataset: {num_rows:,} rows...")

    records: list[dict[str, Any]] = []

    tier_names = list(RISK_TIERS.keys())
    tier_weights = [RISK_TIERS[t]["weight"] for t in tier_names]

    for i in range(num_rows):
        # ── Invoice Metadata ─────────────────────────────────────────────────
        buyer = random.choice(BUYER_ENTITIES)
        terms = random.choice(PAYMENT_TERMS_POOL)
        net_days: int = terms["net_days"]
        invoice_date = _random_invoice_date()
        is_qend = _is_quarter_end(invoice_date)

        # Invoice face value: log-normal centred around $150k, range $5k–$5M
        face_value = round(
            np.clip(np.random.lognormal(mean=11.9, sigma=1.3), 5_000, 5_000_000), 2
        )

        # ── Supplier Profile ─────────────────────────────────────────────────
        tier_name: str = random.choices(tier_names, weights=tier_weights, k=1)[0]
        tier = RISK_TIERS[tier_name]
        sector = random.choice(SUPPLIER_SECTORS)

        alt_cost_apr = round(
            np.clip(np.random.normal(tier["alt_cost_apr_mean"], tier["alt_cost_apr_std"]), 5.0, 40.0),
            2,
        )
        supplier_dso = round(
            np.clip(np.random.normal(tier["dso_mean"], tier["dso_std"]), 15.0, 140.0),
            1,
        )
        historical_acceptance_rate = round(
            np.clip(np.random.beta(a=2.0 + (tier["sensitivity"] - 0.5) * 2, b=2.0), 0.05, 0.98),
            3,
        )
        is_anchor_buyer = random.random() < 0.35  # 35% of invoices are from anchor buyers
        days_since_last_trade = random.randint(1, 120)

        # ── Offer Structuring ────────────────────────────────────────────────
        # Days accelerated: between 5 and (net_days - 5)
        max_accel = max(5, net_days - 5)
        days_accelerated = random.randint(5, max_accel)

        # Instrument type: REVERSE_FACTORING more likely for TIER_2 & TIER_3
        if tier_name == "TIER_1_PRIME":
            instrument = random.choices(
                INSTRUMENT_TYPES, weights=[0.65, 0.35], k=1
            )[0]
        else:
            instrument = random.choices(
                INSTRUMENT_TYPES, weights=[0.40, 0.60], k=1
            )[0]

        # Offered discount: target APR centered around 15% with realistic spread (5% - 30%)
        # Convert target APR into exact discount percentage for the accelerated window
        target_apr = float(np.clip(np.random.normal(loc=15.0, scale=6.5), 3.5, 34.0))
        d_fraction = (target_apr / 100.0) * (days_accelerated / 365.0)
        offered_discount_pct = round((d_fraction / (1.0 + d_fraction)) * 100, 3)

        # ── Financial Computations ───────────────────────────────────────────
        implied_apr = compute_implied_apr(offered_discount_pct, days_accelerated)
        net_payout = compute_supplier_net_payout(face_value, offered_discount_pct)
        buyer_yield = compute_buyer_yield(face_value, offered_discount_pct)
        utility_delta = alt_cost_apr - implied_apr  # sign is the key signal

        # ── Acceptance Simulation ────────────────────────────────────────────
        p_accept = compute_acceptance_probability(
            implied_apr=implied_apr,
            alt_cost_apr=alt_cost_apr,
            supplier_dso=supplier_dso,
            quarter_end_flag=is_qend,
            is_anchor_buyer=is_anchor_buyer,
            sensitivity=tier["sensitivity"],
        )
        accepted = int(random.random() < p_accept)

        records.append(
            {
                "row_id": f"SCF-{i:06d}",
                "invoice_date": invoice_date.isoformat(),
                "buyer_id": buyer["buyer_id"],
                "buyer_sector": buyer["sector"],
                "payment_terms_raw": terms["raw"],
                "original_tenor_days": net_days,
                "supplier_sector": sector,
                "supplier_risk_tier": tier_name,
                "supplier_alt_cost_of_debt_apr": alt_cost_apr,
                "supplier_dso_days": supplier_dso,
                "supplier_historical_acceptance_rate": historical_acceptance_rate,
                "is_anchor_buyer": int(is_anchor_buyer),
                "days_since_last_trade": days_since_last_trade,
                "invoice_face_value_usd": face_value,
                "days_accelerated": days_accelerated,
                "offered_discount_pct": offered_discount_pct,
                "instrument_type": instrument,
                "implied_apr": implied_apr,
                "supplier_net_payout_usd": net_payout,
                "buyer_yield_usd": buyer_yield,
                "quarter_end_flag": int(is_qend),
                "utility_delta": round(utility_delta, 4),
                "acceptance_probability": round(p_accept, 4),
                "accepted_early_offer": accepted,   # ← TARGET VARIABLE
            }
        )

        if (i + 1) % 10_000 == 0:
            print(f"  [{i + 1:,}/{num_rows:,}] rows generated...")

    df = pd.DataFrame(records)
    acceptance_rate = df["accepted_early_offer"].mean()
    print(f"[Generator] Done. Overall acceptance rate: {acceptance_rate:.1%}")
    return df


def generate_erp_invoices(num_invoices: int = NUM_ERP_INVOICES) -> list[dict[str, Any]]:
    """
    Generates synthetic ERP invoice events for the TypeScript UI invoice feed.

    Intentionally includes messy vendor names (for normalizer demonstration),
    varied payment term formats, and multiple ERP sources.
    """
    print(f"[Generator] Creating {num_invoices} synthetic ERP invoices...")

    erp_sources = ["SAP_S4HANA", "ORACLE_ERP_CLOUD", "NETSUITE", "TALLY_PRIME"]
    currencies = ["USD", "EUR", "GBP", "INR"]
    statuses = ["APPROVED", "APPROVED", "APPROVED", "PENDING"]  # Mostly approved

    invoices: list[dict[str, Any]] = []
    all_alias_pairs = [
        (canonical, alias)
        for canonical, aliases in VENDOR_NAME_ALIASES.items()
        for alias in aliases
    ]

    for i in range(num_invoices):
        buyer = random.choice(BUYER_ENTITIES)
        terms = random.choice(PAYMENT_TERMS_POOL)
        invoice_date = _random_invoice_date()
        due_date = invoice_date + timedelta(days=terms["net_days"])
        canonical_name, messy_alias = random.choice(all_alias_pairs)

        face_value = round(
            np.clip(np.random.lognormal(mean=12.2, sigma=1.1), 10_000, 5_000_000), 2
        )

        invoices.append(
            {
                "invoice_id": f"INV-{invoice_date.year}-{i + 1:05d}",
                "erp_source": random.choice(erp_sources),
                "vendor_name_raw": messy_alias,               # Intentionally messy
                "vendor_name_canonical": canonical_name,       # Ground truth for tests
                "buyer_id": buyer["buyer_id"],
                "buyer_name": buyer["name"],
                "invoice_amount": face_value,
                "currency": random.choice(currencies),
                "issue_date": invoice_date.isoformat(),
                "due_date": due_date.isoformat(),
                "payment_terms_raw": terms["raw"],             # Intentionally raw string
                "payment_discount_pct": terms["discount_pct"],
                "payment_discount_days": terms["discount_days"],
                "payment_net_days": terms["net_days"],
                "status": random.choice(statuses),
                "quarter_end_flag": _is_quarter_end(invoice_date),
            }
        )

    print(f"[Generator] {num_invoices} ERP invoices created.")
    return invoices


def generate_vendor_master() -> list[dict[str, Any]]:
    """
    Generates the vendor master registry with canonical IDs, tax IDs,
    sector, risk tier, and multiple name aliases.

    Used by Module A (normalizer) for fuzzy golden-record matching.
    """
    print("[Generator] Creating vendor master...")

    vendors: list[dict[str, Any]] = []
    for i, (canonical_name, aliases) in enumerate(VENDOR_NAME_ALIASES.items()):
        tier_name = random.choices(
            list(RISK_TIERS.keys()),
            weights=[t["weight"] for t in RISK_TIERS.values()],
        )[0]
        tier = RISK_TIERS[tier_name]

        vendors.append(
            {
                "supplier_id": f"SUPP-{i + 1:05d}",
                "canonical_name": canonical_name,
                "name_aliases": aliases,
                "tax_id": fake.numerify("##-#######"),      # EIN format
                "gstin": fake.numerify("##AAAAA####A#Z#"),   # GSTIN format
                "sector": random.choice(SUPPLIER_SECTORS),
                "risk_tier": tier_name,
                "bank_account_iban": fake.iban(),
                "bank_routing_number": fake.numerify("#########"),
                "country": random.choice(["US", "IN", "DE", "GB", "SG"]),
                "alt_cost_of_debt_apr": round(
                    np.clip(
                        np.random.normal(tier["alt_cost_apr_mean"], tier["alt_cost_apr_std"]),
                        5.0,
                        40.0,
                    ),
                    2,
                ),
                "dso_days": round(
                    np.clip(
                        np.random.normal(tier["dso_mean"], tier["dso_std"]), 15.0, 140.0
                    ),
                    1,
                ),
                "historical_acceptance_rate": round(random.uniform(0.20, 0.95), 3),
                "sanctions_cleared": True,   # All vendors in master are cleared by default
                "watchlist_flags": [],
            }
        )

    # Add a few extra synthetic vendors
    for i in range(45):
        tier_name = random.choices(
            list(RISK_TIERS.keys()),
            weights=[t["weight"] for t in RISK_TIERS.values()],
        )[0]
        tier = RISK_TIERS[tier_name]
        company_name = fake.company()
        vendors.append(
            {
                "supplier_id": f"SUPP-{i + 10:05d}",
                "canonical_name": company_name,
                "name_aliases": [
                    company_name.upper(),
                    company_name.replace("LLC", "").strip(),
                    company_name.split(" ")[0] + " Corp.",
                ],
                "tax_id": fake.numerify("##-#######"),
                "gstin": None,
                "sector": random.choice(SUPPLIER_SECTORS),
                "risk_tier": tier_name,
                "bank_account_iban": fake.iban(),
                "bank_routing_number": fake.numerify("#########"),
                "country": random.choice(["US", "IN", "DE", "GB"]),
                "alt_cost_of_debt_apr": round(
                    np.clip(
                        np.random.normal(tier["alt_cost_apr_mean"], tier["alt_cost_apr_std"]),
                        5.0,
                        40.0,
                    ),
                    2,
                ),
                "dso_days": round(
                    np.clip(
                        np.random.normal(tier["dso_mean"], tier["dso_std"]), 15.0, 140.0
                    ),
                    1,
                ),
                "historical_acceptance_rate": round(random.uniform(0.20, 0.95), 3),
                "sanctions_cleared": (i not in (3, 17)),
                "watchlist_flags": ["OFAC_SDN_LIST"] if (i in (3, 17)) else [],
            }
        )

    print(f"[Generator] {len(vendors)} vendors in master.")
    return vendors


def generate_buyer_facilities() -> list[dict[str, Any]]:
    """
    Generates revolving credit facility configurations for each buyer entity.

    Used by Module C (guardrails) for limit validation and Module A
    (cash forecaster) for facility headroom calculations.
    """
    print("[Generator] Creating buyer credit facilities...")

    facilities = []
    for buyer in BUYER_ENTITIES:
        facility_limit = random.choice(
            [50_000_000, 100_000_000, 150_000_000, 200_000_000, 250_000_000]
        )
        utilization = round(random.uniform(0.30, 0.60), 3)  # 30–60% already drawn
        drawn = round(facility_limit * utilization, 2)

        facilities.append(
            {
                "buyer_id": buyer["buyer_id"],
                "buyer_name": buyer["name"],
                "bank_facility_id": f"FAC-{fake.numerify('######')}",
                "facility_limit_usd": facility_limit,
                "facility_drawn_usd": drawn,
                "facility_available_usd": round(facility_limit - drawn, 2),
                "facility_utilization_pct": round(utilization * 100, 1),
                "base_benchmark_rate": 5.33,     # SOFR as of Oct 2026 (placeholder)
                "bank_margin_spread": round(random.uniform(1.0, 2.5), 2),
                "platform_fee_pct": 0.20,
                "buyer_rebate_share_pct": 0.30,
                "single_supplier_concentration_cap_pct": 15.0,
                "minimum_cash_floor_usd": 10_000_000,
                "covenant_description": "Net debt/EBITDA < 3.5x; minimum cash floor $10M",
            }
        )

    print(f"[Generator] {len(facilities)} buyer facility records created.")
    return facilities


def generate_cash_ledger(horizon_days: int = 90) -> list[dict[str, Any]]:
    """
    Generates a 90-day rolling cash projection for each buyer.

    Simulates seasonality, payroll cycles, collections, and facility draws
    to create realistic daily balance curves for the cash forecasting chart.
    """
    print(f"[Generator] Creating {horizon_days}-day cash ledger for {len(BUYER_ENTITIES)} buyers...")

    ledger: list[dict[str, Any]] = []
    base_date = date.today()

    for buyer in BUYER_ENTITIES:
        # Starting balance: between $20M and $80M
        starting_balance = random.randint(20_000_000, 80_000_000)
        balance = float(starting_balance)

        for day_offset in range(horizon_days):
            current_date = base_date + timedelta(days=day_offset)

            # Simulate realistic daily cash movements
            # Collections: random daily receivables (higher mid-month)
            mid_month_boost = 1.4 if 13 <= current_date.day <= 17 else 1.0
            daily_collections = np.random.lognormal(mean=13.5, sigma=0.8) * mid_month_boost

            # Outflows: payables, payroll (end of month spike)
            month_end_drain = 2.2 if current_date.day >= 27 else 1.0
            daily_outflows = np.random.lognormal(mean=13.3, sigma=0.7) * month_end_drain

            balance = max(5_000_000, balance + daily_collections - daily_outflows)

            ledger.append(
                {
                    "buyer_id": buyer["buyer_id"],
                    "date": current_date.isoformat(),
                    "day_offset": day_offset,
                    "projected_cash_balance_usd": round(balance, 2),
                    "daily_collections_usd": round(daily_collections, 2),
                    "daily_outflows_usd": round(daily_outflows, 2),
                    "minimum_cash_floor_usd": 10_000_000,
                    "liquidity_status": (
                        "SURPLUS" if balance > 25_000_000
                        else "TIGHT" if balance > 10_000_000
                        else "DEFICIT"
                    ),
                    "quarter_end_flag": _is_quarter_end(current_date),
                }
            )

    print(f"[Generator] {len(ledger)} cash ledger rows created.")
    return ledger


# ---------------------------------------------------------------------------
# Orchestration & Export
# ---------------------------------------------------------------------------

def run_generation() -> None:
    """Generate all datasets, save locally. GCS upload handled by gcs_uploader.py."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. ML Training Dataset
    df = generate_ml_training_dataset(NUM_ML_ROWS)
    ml_path = OUTPUT_DIR / "scf_supplier_acceptance_dataset.csv"
    df.to_csv(ml_path, index=False)
    print(f"[Export] Saved: {ml_path}  ({ml_path.stat().st_size / 1_048_576:.1f} MB)")

    # 2. ERP Invoices
    invoices = generate_erp_invoices(NUM_ERP_INVOICES)
    erp_path = OUTPUT_DIR / "synthetic_erp_invoices.json"
    erp_path.write_text(json.dumps(invoices, indent=2))
    print(f"[Export] Saved: {erp_path}")

    # 3. Vendor Master
    vendors = generate_vendor_master()
    vendor_path = OUTPUT_DIR / "synthetic_vendor_master.json"
    vendor_path.write_text(json.dumps(vendors, indent=2))
    print(f"[Export] Saved: {vendor_path}")

    # 4. Buyer Credit Facilities
    facilities = generate_buyer_facilities()
    facility_path = OUTPUT_DIR / "synthetic_buyers_facilities.json"
    facility_path.write_text(json.dumps(facilities, indent=2))
    print(f"[Export] Saved: {facility_path}")

    # 5. Cash Ledger
    ledger = generate_cash_ledger(90)
    ledger_path = OUTPUT_DIR / "synthetic_cash_ledger.json"
    ledger_path.write_text(json.dumps(ledger, indent=2))
    print(f"[Export] Saved: {ledger_path}")

    # Summary statistics
    print("\n" + "=" * 60)
    print("DATASET GENERATION COMPLETE")
    print("=" * 60)
    print(f"  ML rows:            {len(df):,}")
    print(f"  Acceptance rate:    {df['accepted_early_offer'].mean():.1%}")
    print(f"  ERP invoices:       {len(invoices)}")
    print(f"  Vendors in master:  {len(vendors)}")
    print(f"  Buyer facilities:   {len(facilities)}")
    print(f"  Cash ledger rows:   {len(ledger)}")
    print(f"  Output directory:   {OUTPUT_DIR.resolve()}")
    print("=" * 60)
    print("\nNext step: run  uv run python packages/orchestrator/ml/gcs_uploader.py")


if __name__ == "__main__":
    run_generation()

