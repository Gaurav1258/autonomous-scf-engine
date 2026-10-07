"""
GCS Uploader — SCF Engine
==========================
Uploads all locally generated datasets from data/generated/ to the
GCS bucket mlops2215-scf-data, mirroring your existing mlops project pattern.

Bucket layout:
    gs://mlops2215-scf-data/
    └── datasets/
        ├── ml/
        │   └── scf_supplier_acceptance_dataset.csv   (XGBoost training)
        └── synthetic/
            ├── synthetic_erp_invoices.json
            ├── synthetic_vendor_master.json
            ├── synthetic_buyers_facilities.json
            └── synthetic_cash_ledger.json

Authentication:
    Uses Google Application Default Credentials (ADC) — same pattern as
    your existing mlops project (gcloud auth application-default login).

Usage:
    uv run python packages/orchestrator/ml/gcs_uploader.py
"""

from __future__ import annotations

import os
from pathlib import Path

from google.cloud import storage

# ---------------------------------------------------------------------------
# Configuration — matches your existing mlops2215 GCP project
# ---------------------------------------------------------------------------
GCP_PROJECT_ID: str = os.getenv("GCP_PROJECT_ID", "mlops2215")
GCS_BUCKET_NAME: str = os.getenv("GCS_BUCKET_NAME", "mlops2215-scf-data")
LOCAL_DATA_DIR: Path = Path(os.getenv("DATASET_LOCAL_OUTPUT_DIR", "data/generated"))

# Mapping: local filename → GCS object path
UPLOAD_MANIFEST: dict[str, str] = {
    "scf_supplier_acceptance_dataset.csv": "datasets/ml/scf_supplier_acceptance_dataset.csv",
    "synthetic_erp_invoices.json":         "datasets/synthetic/synthetic_erp_invoices.json",
    "synthetic_vendor_master.json":        "datasets/synthetic/synthetic_vendor_master.json",
    "synthetic_buyers_facilities.json":    "datasets/synthetic/synthetic_buyers_facilities.json",
    "synthetic_cash_ledger.json":          "datasets/synthetic/synthetic_cash_ledger.json",
}


def _ensure_bucket_exists(client: storage.Client, bucket_name: str) -> storage.Bucket:
    """
    Returns the bucket if it exists. Creates it in us-central1 if it doesn't.
    Matches the region used in your existing mlops2215 project.
    """
    bucket = client.bucket(bucket_name)
    if not bucket.exists():
        print(f"[GCS] Bucket '{bucket_name}' not found. Creating in us-central1...")
        bucket = client.create_bucket(bucket_name, location="us-central1")
        print(f"[GCS] Bucket created: gs://{bucket_name}/")
    else:
        print(f"[GCS] Using existing bucket: gs://{bucket_name}/")
    return bucket


def upload_datasets() -> None:
    """
    Upload all generated SCF datasets from data/generated/ to GCS.
    Prints a gs:// URI for each file after successful upload.
    """
    print(f"[GCS Uploader] Project: {GCP_PROJECT_ID}")
    print(f"[GCS Uploader] Bucket:  gs://{GCS_BUCKET_NAME}/")
    print(f"[GCS Uploader] Source:  {LOCAL_DATA_DIR.resolve()}\n")

    client = storage.Client(project=GCP_PROJECT_ID)
    bucket = _ensure_bucket_exists(client, GCS_BUCKET_NAME)

    uploaded: list[str] = []
    skipped: list[str] = []

    for local_filename, gcs_object_path in UPLOAD_MANIFEST.items():
        local_path = LOCAL_DATA_DIR / local_filename

        if not local_path.exists():
            print(f"  [SKIP] {local_filename} — not found locally. Run dataset_generator.py first.")
            skipped.append(local_filename)
            continue

        blob = bucket.blob(gcs_object_path)
        size_mb = local_path.stat().st_size / 1_048_576

        print(f"  [^] Uploading {local_filename}  ({size_mb:.1f} MB)...")
        blob.upload_from_filename(str(local_path))
        gcs_uri = f"gs://{GCS_BUCKET_NAME}/{gcs_object_path}"
        print(f"      -> {gcs_uri}")
        uploaded.append(gcs_uri)

    print("\n" + "=" * 60)
    print("UPLOAD COMPLETE")
    print("=" * 60)
    print(f"  Uploaded: {len(uploaded)} files")
    if skipped:
        print(f"  Skipped:  {len(skipped)} files (not generated yet)")
    print("\nFiles accessible at:")
    for uri in uploaded:
        print(f"  {uri}")
    print("=" * 60)


def download_dataset(gcs_object_path: str, local_dest: Path) -> Path:
    """
    Stream a single dataset file from GCS to a local path.
    Used by the training pipeline and orchestrator agents.

    Args:
        gcs_object_path: e.g. "datasets/ml/scf_supplier_acceptance_dataset.csv"
        local_dest: local path to write the file to

    Returns:
        Path to the downloaded file.
    """
    client = storage.Client(project=GCP_PROJECT_ID)
    bucket = client.bucket(GCS_BUCKET_NAME)
    blob = bucket.blob(gcs_object_path)

    local_dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"[GCS] Downloading gs://{GCS_BUCKET_NAME}/{gcs_object_path} ...")
    blob.download_to_filename(str(local_dest))
    print(f"[GCS] Saved to {local_dest}")
    return local_dest


def get_gcs_uri(local_filename: str) -> str:
    """
    Returns the full gs:// URI for a given local dataset filename.
    Used by the training script to pass to Vertex AI or pandas directly.

    Example:
        get_gcs_uri("scf_supplier_acceptance_dataset.csv")
        → "gs://mlops2215-scf-data/datasets/ml/scf_supplier_acceptance_dataset.csv"
    """
    gcs_path = UPLOAD_MANIFEST.get(local_filename)
    if not gcs_path:
        raise KeyError(f"'{local_filename}' not in upload manifest. Check UPLOAD_MANIFEST.")
    return f"gs://{GCS_BUCKET_NAME}/{gcs_path}"


if __name__ == "__main__":
    upload_datasets()

