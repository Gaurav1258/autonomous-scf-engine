# Supply Chain Finance (SCF) Supplier Acceptance & Trade Optimization Dataset

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Storage-Google_Cloud_Storage-4285F4.svg)](#cloud-storage-gcs)
[![Samples](https://img.shields.io/badge/Records-50%2C000_Transactions-emerald.svg)](#dataset-summary)
[![Domain](https://img.shields.io/badge/Domain-Quantitative_Corporate_Finance-purple.svg)](#context)

An institutional-grade benchmark dataset simulating **Supply Chain Finance (Reverse Factoring & Dynamic Discounting)** negotiations, supplier early payment price elasticity, and ERP payables liquidity.

---

## 📌 Context & Motivation

In global corporate trade, enterprise buyers approve hundreds of billions in supplier invoices with payment terms ranging from Net 30 to Net 120 days. When corporate buyers or partner banks propose an early payment discount (e.g., paying 35 days early for a 1.5% discount), the supplier faces a microeconomic decision:

> *Is the implied Annual Percentage Rate (APR) of this early payment discount lower or higher than my alternative cost of short-term borrowing (e.g., bank overdrafts, commercial paper, or predatory factoring), given my current working capital stress?*

Existing public datasets (e.g., Kaggle accounts receivable datasets) capture invoice amounts and historical payment delay dates, but **lack the bid/ask dynamic discounting offer terms, implied APRs, and supplier acceptance ground truth**. This dataset closes that gap.

---

## 🔬 Microeconomic Ground Truth Formulation

Supplier acceptance ($y \in \{0, 1\}$) is modeled via a **financial utility spread** normalized by temperature $T = 6.0$:

$$\Delta U = (\text{APR}_{\text{alt\_debt}} - \text{APR}_{\text{implied}}) + U_{\text{urgency}} + U_{\text{quarter\_end}} + U_{\text{relationship}}$$

Where:
- $\text{APR}_{\text{implied}} = \left(\frac{d}{1 - d}\right) \times \left(\frac{365}{\text{Days Accelerated}}\right)$ (FASB ASC 310 formulation).
- $U_{\text{urgency}} = \max\left(0, \frac{\text{DSO} - 60}{40}\right) \times 2.0$ (DSO above 60 days signals liquidity stress).
- $U_{\text{quarter\_end}} = 1.5$ if invoice falls within 15 days of calendar quarter close (cash squeeze).
- $U_{\text{relationship}} = 0.8$ if buyer is an anchor corporate counterparty.

The probability of acceptance is:
$$P(\text{Accept}) = \sigma\left(\frac{\Delta U}{T} \times \text{Sensitivity}_{\text{tier}}\right)$$

This guarantees a realistic **~51.8% overall acceptance rate**, reflecting real-world SCF platform take-up benchmarks (C2FO, Taulia).

---

## 📊 Dataset Schema (`scf_supplier_acceptance_dataset.csv`)

| Column | Type | Description |
| :--- | :--- | :--- |
| `row_id` | String | Unique transaction ID (`SCF-000001`) |
| `invoice_date` | String | ISO 8601 invoice approval date |
| `buyer_id` | String | Corporate buyer entity identifier |
| `buyer_sector` | String | Buyer industry (Automotive, IT, Conglomerate, Retail, Industrial) |
| `payment_terms_raw` | String | ERP payment term string (e.g., `2/10 Net 60`, `Net 90`) |
| `original_tenor_days` | Integer | Total net payment days (30, 45, 60, 90) |
| `supplier_sector` | String | Supplier industry (Manufacturing, Logistics, IT, Pharma, etc.) |
| `supplier_risk_tier` | String | `TIER_1_PRIME`, `TIER_2_STABLE`, `TIER_3_ELEVATED` |
| `supplier_alt_cost_of_debt_apr` | Float | Alternative borrowing cost APR % (overdraft, loan) |
| `supplier_dso_days` | Float | Supplier Days Sales Outstanding (DSO) |
| `supplier_historical_acceptance_rate` | Float | Historical acceptance frequency (0.0 to 1.0) |
| `is_anchor_buyer` | Integer | Binary flag: 1 if key anchor buyer, 0 otherwise |
| `days_since_last_trade` | Integer | Number of days since last transaction |
| `invoice_face_value_usd` | Float | Invoice gross amount (\$5,000 to \$5,000,000) |
| `days_accelerated` | Integer | Days accelerated ahead of net due date |
| `offered_discount_pct` | Float | Proposed dynamic discount rate % |
| `instrument_type` | String | `DYNAMIC_DISCOUNTING` or `REVERSE_FACTORING` |
| `implied_apr` | Float | Annualized Percentage Rate implied by discount |
| `supplier_net_payout_usd` | Float | Net cash advance to supplier |
| `buyer_yield_usd` | Float | Nominal discount capture earned by buyer |
| `quarter_end_flag` | Integer | Binary flag: 1 if near quarter end |
| `utility_delta` | Float | Ground-truth economic utility spread |
| `acceptance_probability` | Float | Underlying model probability |
| **`accepted_early_offer`** | **Integer** | **Target Label: 1 = Accepted, 0 = Rejected** |

---

## ☁️ Google Cloud Storage (GCS) Lake Layout

Datasets are hosted in Google Cloud Storage:
```
gs://<your-gcs-bucket-name>/
└── datasets/
    ├── ml/
    │   └── scf_supplier_acceptance_dataset.csv       (50,000 rows, 9.3 MB)
    └── synthetic/
        ├── synthetic_erp_invoices.json               (200 raw ERP payables events)
        ├── synthetic_vendor_master.json              (50 canonical vendors + aliases)
        ├── synthetic_buyers_facilities.json          (5 revolving credit facilities)
        └── synthetic_cash_ledger.json                (450 daily cash ledger points)
```

---

## 🚀 Quickstart: Loading the Data with Python

```python
import os
import pandas as pd
from google.cloud import storage

# Option 1: Direct from local file
df = pd.read_csv("data/generated/scf_supplier_acceptance_dataset.csv")

# Option 2: Stream directly from GCS (requires gcloud ADC)
project_id = os.getenv("GCP_PROJECT_ID", "your-gcp-project-id")
bucket_name = os.getenv("GCS_BUCKET_NAME", "your-gcs-bucket-name")

client = storage.Client(project=project_id)
bucket = client.bucket(bucket_name)
blob = bucket.blob("datasets/ml/scf_supplier_acceptance_dataset.csv")
blob.download_to_filename("scf_dataset.csv")
df = pd.read_csv("scf_dataset.csv")

print(f"Dataset shape: {df.shape}")
print(f"Overall acceptance rate: {df['accepted_early_offer'].mean():.1%}")
```

---

## 📄 License
This dataset and generator are open-sourced under the [Apache License 2.0](LICENSE).

