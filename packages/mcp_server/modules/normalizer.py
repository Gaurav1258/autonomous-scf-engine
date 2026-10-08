"""
Module A: Trade Ledger Context Normalizer
=========================================
The "URL-to-Markdown" equivalent for Supply Chain Finance and ERP Payables.

Normalizes raw, unstandardized ERP invoice streams (SAP, Oracle, NetSuite, Tally)
into clean, deduplicated Golden Record context blocks.

Capabilities:
1. Payment Term Parser: Translates legacy ERP strings ("2/10 Net 60", "Net 90")
   into structured numerical integer fields.
2. Fuzzy Entity Resolution: Maps vendor name variations ("Reliance Ind." -> "Reliance Industries Ltd.")
   to canonical Golden Records with RapidFuzz token matching.
3. Duplicate Invoice Sentinel: Detects duplicate invoices and double-pledged receivables
   via cryptographic idempotency hashing against open ledgers.
4. Token-Optimized Markdown: Produces clean, LLM-ready markdown summaries.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any, Optional

from rapidfuzz import fuzz, process

from packages.mcp_server.models.schemas import CleanTradeContext, PaymentTerms

# Regex patterns for parsing payment terms
TERM_PATTERNS = [
    # "2/10 Net 60", "1.5/15 Net 45", "2/10, Net 60", "2/10, n/60", "2/10 n/60"
    re.compile(
        r"(?P<disc>\d+(?:\.\d+)?)\s*(?:%|\/)\s*(?P<disc_days>\d+)[,\s]+(?:net|n)[\s\/]*(?P<net_days>\d+)",
        re.IGNORECASE,
    ),
    # "2/10 n 60", "2 / 10 net 60"
    re.compile(
        r"(?P<disc>\d+(?:\.\d+)?)\s*\/\s*(?P<disc_days>\d+)\s+(?:net|n)[\s\/]*(?P<net_days>\d+)",
        re.IGNORECASE,
    ),
    # "Net 60", "N60", "Net 30", "Net 90"
    re.compile(r"net\s*(?P<net_days>\d+)", re.IGNORECASE),
    re.compile(r"^n\s*(?P<net_days>\d+)$", re.IGNORECASE),
    # "EOM + 30", "EOM 30"
    re.compile(r"eom\s*(?:\+\s*)?(?P<net_days>\d+)?", re.IGNORECASE),
]

DEFAULT_SEED_VENDOR_MASTER: list[dict[str, Any]] = [
    {
        "supplier_id": "SUPP-00001",
        "canonical_name": "Reliance Industries Ltd.",
        "name_aliases": [
            "Reliance Ind.",
            "RELIANCE IND LTD",
            "Reliance Industries",
            "RELIANCE INDS.",
            "Reliance Industries Limited",
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
            "Mahindra & Mahindra",
            "Mahindra Mahindra",
        ],
        "tax_id": "45-6789012",
        "gstin": "27AAACM9012C1Z8",
        "sector": "Manufacturing",
        "risk_tier": "TIER_2_STABLE",
    },
    {
        "supplier_id": "SUPP-00004",
        "canonical_name": "Larsen & Toubro Ltd.",
        "name_aliases": [
            "L&T Ltd",
            "LARSEN AND TOUBRO",
            "Larsen Toubro",
            "L & T Limited",
        ],
        "tax_id": "33-4455667",
        "gstin": "27AAACL3344D1Z9",
        "sector": "Construction",
        "risk_tier": "TIER_1_PRIME",
    },
    {
        "supplier_id": "SUPP-00005",
        "canonical_name": "Wipro Technologies Ltd.",
        "name_aliases": [
            "Wipro Ltd.",
            "WIPRO TECH",
            "Wipro Technologies",
            "WIPRO LTD",
        ],
        "tax_id": "55-6677889",
        "gstin": "29AAACW5566E1Z1",
        "sector": "IT Services",
        "risk_tier": "TIER_2_STABLE",
    },
]


def load_default_vendor_master() -> list[dict[str, Any]]:
    """
    Loads vendor master: checks local generated file, then GCS, and falls back
    to built-in canonical seed records.
    """
    local_file = Path("data/generated/synthetic_vendor_master.json")
    if local_file.exists():
        try:
            with open(local_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # Try downloading from GCS if configured
    try:
        from google.cloud import storage

        project_id = os.getenv("GCP_PROJECT_ID")
        bucket_name = os.getenv("GCS_BUCKET_NAME")
        if project_id and bucket_name:
            client = storage.Client(project=project_id)
            bucket = client.bucket(bucket_name)
            blob = bucket.blob("datasets/synthetic/synthetic_vendor_master.json")
            if blob.exists():
                local_file.parent.mkdir(parents=True, exist_ok=True)
                blob.download_to_filename(str(local_file))
                with open(local_file, "r", encoding="utf-8") as f:
                    return json.load(f)
    except Exception:
        pass

    return DEFAULT_SEED_VENDOR_MASTER


def parse_payment_terms(raw_term_string: str) -> PaymentTerms:
    """
    Parses ERP payment term strings into structured mathematical integers.
    Examples:
        '2/10 Net 60'   -> discount: 2.0%, discount_days: 10, net_days: 60
        '1.5/15 Net 45' -> discount: 1.5%, discount_days: 15, net_days: 45
        'Net 90'        -> discount: 0.0%, discount_days:  0, net_days: 90
        'Net 30'        -> discount: 0.0%, discount_days:  0, net_days: 30
    """
    if not raw_term_string or not raw_term_string.strip():
        return PaymentTerms(
            raw_term_string="Net 30",
            discount_percentage=0.0,
            discount_days=0,
            net_days=30,
            is_discount_available=False,
        )

    term_clean = raw_term_string.strip()

    # Pattern 1 & 2: Discount / Discount Days + Net Days
    for pattern in TERM_PATTERNS[:2]:
        match = pattern.search(term_clean)
        if match:
            disc = float(match.group("disc"))
            disc_days = int(match.group("disc_days"))
            net_days = int(match.group("net_days"))
            return PaymentTerms(
                raw_term_string=term_clean,
                discount_percentage=disc,
                discount_days=disc_days,
                net_days=net_days,
                is_discount_available=(disc > 0 and disc_days > 0),
            )

    # Pattern 3 & 4: Simple Net N
    for pattern in TERM_PATTERNS[2:4]:
        match = pattern.search(term_clean)
        if match:
            net_days = int(match.group("net_days"))
            return PaymentTerms(
                raw_term_string=term_clean,
                discount_percentage=0.0,
                discount_days=0,
                net_days=net_days,
                is_discount_available=False,
            )

    # Pattern 5: EOM (End of Month)
    eom_match = TERM_PATTERNS[4].search(term_clean)
    if eom_match:
        extra_days = int(eom_match.group("net_days")) if eom_match.group("net_days") else 30
        return PaymentTerms(
            raw_term_string=term_clean,
            discount_percentage=0.0,
            discount_days=0,
            net_days=extra_days + 30,  # Approximate EOM as 30 days + offset
            is_discount_available=False,
        )

    # Fallback default
    return PaymentTerms(
        raw_term_string=term_clean,
        discount_percentage=0.0,
        discount_days=0,
        net_days=30,
        is_discount_available=False,
    )


def resolve_vendor_entity(
    raw_vendor_name: str,
    vendor_master: list[dict[str, Any]],
    score_threshold: float = 65.0,
) -> tuple[dict[str, Any], str, float]:
    """
    Matches a messy vendor name against canonical vendor master records using RapidFuzz.
    Evaluates both canonical names and registered aliases.

    Returns:
        (canonical_vendor_dict, matched_alias_str, match_confidence_score)
    """
    if not vendor_master:
        return (
            {
                "supplier_id": "SUPP-UNREGISTERED",
                "canonical_name": raw_vendor_name,
                "risk_tier": "TIER_2_STABLE",
                "sector": "General",
                "tax_id": None,
                "gstin": None,
            },
            raw_vendor_name,
            0.0,
        )

    # Flatten master list into (search_string, vendor_record) pairs
    candidates: list[tuple[str, dict[str, Any]]] = []
    for vendor in vendor_master:
        canonical = vendor.get("canonical_name", "")
        candidates.append((canonical, vendor))
        for alias in vendor.get("name_aliases", []):
            if alias != canonical:
                candidates.append((alias, vendor))

    best_match_str = ""
    best_vendor = None
    best_score = -1.0

    # Test candidate matches using token_set_ratio (handles punctuation, suffixes, word order)
    for cand_str, vendor_rec in candidates:
        score = fuzz.token_set_ratio(raw_vendor_name, cand_str)
        if score > best_score:
            best_score = score
            best_match_str = cand_str
            best_vendor = vendor_rec

    if best_score >= score_threshold and best_vendor is not None:
        return (best_vendor, best_match_str, round(best_score, 1))

    # Unmatched fallback
    return (
        {
            "supplier_id": "SUPP-UNREGISTERED",
            "canonical_name": raw_vendor_name.strip(),
            "risk_tier": "TIER_2_STABLE",
            "sector": "General",
            "tax_id": None,
            "gstin": None,
        },
        raw_vendor_name,
        round(best_score if best_score > 0 else 0.0, 1),
    )


def compute_idempotency_hash(
    buyer_id: str,
    vendor_canonical_id: str,
    invoice_id: str,
    invoice_amount: float,
    currency: str,
) -> str:
    """Computes a deterministic SHA256 digest to prevent duplicate financing."""
    payload = f"{buyer_id}|{vendor_canonical_id}|{invoice_id.strip().upper()}|{invoice_amount:.2f}|{currency.upper()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def check_duplicate_invoice(
    invoice_id: str,
    idempotency_hash: str,
    open_ledger: Optional[list[dict[str, Any]]] = None,
) -> tuple[bool, Optional[str]]:
    """
    Checks if an invoice has already been registered or pledged in open trade ledgers.
    """
    if not open_ledger:
        return (False, None)

    for item in open_ledger:
        # Check matching invoice ID
        if item.get("invoice_id", "").strip().upper() == invoice_id.strip().upper():
            return (
                True,
                f"Invoice ID '{invoice_id}' already exists in ledger with status '{item.get('status', 'OPEN')}'",
            )
        # Check matching hash
        if item.get("idempotency_hash") == idempotency_hash:
            return (
                True,
                f"Identical receivable payload hash detected in ledger (Pledged ID: {item.get('invoice_id')})",
            )

    return (False, None)


def generate_trade_context_markdown(
    context_data: dict[str, Any],
) -> str:
    """Formats a token-optimized, high-signal Markdown context block for LLM prompts."""
    terms = context_data["payment_terms"]
    discount_str = (
        f"{terms['discount_percentage']}% within {terms['discount_days']} days, Net {terms['net_days']} days"
        if terms["is_discount_available"]
        else f"Net {terms['net_days']} days (No baseline early discount)"
    )

    dup_status = "CLEARED (No duplicates)" if not context_data["is_duplicate"] else f"FLAGGED DUPLICATE: {context_data['duplicate_reason']}"

    return f"""### Normalized Trade Context: `{context_data['invoice_id']}`
- **Vendor:** {context_data['vendor_canonical_name']} (`{context_data['vendor_canonical_id']}`)
  - Raw Input Name: *"{context_data['vendor_matched_alias']}"* (Match Score: {context_data['match_confidence_score']}%)
  - Sector: {context_data['supplier_sector']} | Risk Tier: `{context_data['supplier_risk_tier']}`
  - Tax ID / GSTIN: {context_data.get('tax_id') or 'N/A'} / {context_data.get('gstin') or 'N/A'}
- **Invoice Financials:** {context_data['currency']} {context_data['invoice_amount']:,.2f}
  - Issue Date: {context_data['issue_date']} | Net Due Date: {context_data['due_date']}
  - Days Remaining to Maturity: {context_data['days_to_due']} days
  - Standard Terms: {discount_str} (Source: *"{terms['raw_term_string']}"*)
- **Ledger Verification:** {dup_status}
- **Idempotency Hash:** `{context_data['idempotency_hash'][:16]}...`
"""


def extract_trade_context(
    raw_invoice: dict[str, Any],
    vendor_master: Optional[list[dict[str, Any]]] = None,
    open_ledger: Optional[list[dict[str, Any]]] = None,
) -> CleanTradeContext:
    """
    Main normalizer entry point: ingests raw ERP invoice dict and produces
    the validated CleanTradeContext model.
    """
    if vendor_master is None:
        vendor_master = load_default_vendor_master()

    invoice_id = str(raw_invoice.get("invoice_id", "INV-UNKNOWN")).strip()
    erp_source = str(raw_invoice.get("erp_source", "SAP_S4HANA"))
    raw_vendor = str(raw_invoice.get("vendor_name_raw", raw_invoice.get("vendor_name", "")))
    buyer_id = str(raw_invoice.get("buyer_id", "CORP-DEFAULT"))
    amount = float(raw_invoice.get("invoice_amount", 0.0))
    currency = str(raw_invoice.get("currency", "USD")).upper()
    issue_date_str = str(raw_invoice.get("issue_date", date.today().isoformat()))
    due_date_str = str(raw_invoice.get("due_date", (date.today()).isoformat()))
    raw_terms_str = str(raw_invoice.get("payment_terms_raw", raw_invoice.get("payment_terms", "Net 30")))

    # 1. Parse payment terms
    terms = parse_payment_terms(raw_terms_str)

    # 2. Fuzzy entity resolution
    vendor_rec, matched_alias, match_score = resolve_vendor_entity(raw_vendor, vendor_master)

    # 3. Calculate days to due
    try:
        due_d = date.fromisoformat(due_date_str[:10])
        days_to_due = max(0, (due_d - date.today()).days)
    except Exception:
        days_to_due = terms.net_days

    # 4. Idempotency hash & duplicate check
    idemp_hash = compute_idempotency_hash(
        buyer_id=buyer_id,
        vendor_canonical_id=vendor_rec.get("supplier_id", "SUPP-UNKNOWN"),
        invoice_id=invoice_id,
        invoice_amount=amount,
        currency=currency,
    )

    is_dup, dup_reason = check_duplicate_invoice(invoice_id, idemp_hash, open_ledger)

    context_dict = {
        "invoice_id": invoice_id,
        "erp_source": erp_source,
        "vendor_canonical_id": vendor_rec.get("supplier_id", "SUPP-UNREGISTERED"),
        "vendor_canonical_name": vendor_rec.get("canonical_name", raw_vendor),
        "vendor_matched_alias": matched_alias,
        "match_confidence_score": match_score,
        "tax_id": vendor_rec.get("tax_id"),
        "gstin": vendor_rec.get("gstin"),
        "supplier_risk_tier": vendor_rec.get("risk_tier", "TIER_2_STABLE"),
        "supplier_sector": vendor_rec.get("sector", "General"),
        "invoice_amount": amount,
        "currency": currency,
        "issue_date": issue_date_str,
        "due_date": due_date_str,
        "payment_terms": terms,
        "days_to_due": days_to_due,
        "is_duplicate": is_dup,
        "duplicate_reason": dup_reason,
        "idempotency_hash": idemp_hash,
    }

    markdown_summary = generate_trade_context_markdown(
        dict(context_dict, payment_terms=terms.model_dump())
    )

    return CleanTradeContext(
        **context_dict,
        summary_markdown=markdown_summary,
    )
