"""
Supplier Discount Acceptance ML Model (XGBoost)
=================================================
Predicts the probability that an enterprise supplier will accept an early payment
discount offer based on transaction terms, alternative debt costs, liquidity stress (DSO),
and buyer relationship telemetry.

Capabilities:
1. Data Ingestion: Loads from local cache or directly streams/downloads from GCS.
2. Model Training: Stratified training of an XGBoost Classifier with categorical support.
3. Model Evaluation: Logs ROC-AUC, Accuracy, Precision, Recall, and Log Loss.
4. Point Inference: Predicts P(Acceptance) for a single proposed term sheet (<10ms).
5. Frontier Curve: Predicts acceptance probability curve across varying discount rates
   to allow the LangGraph Capital Structuring Agent to identify optimal win-win spreads.
6. Artifact Persistence: Saves local model bundle and syncs to GCS.

Usage:
    uv run python packages/orchestrator/ml/acceptance_model.py
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split

from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def get_gcp_project_id() -> str:
    """Retrieves GCP_PROJECT_ID from environment."""
    project_id = os.getenv("GCP_PROJECT_ID")
    if not project_id:
        raise ValueError("Environment variable 'GCP_PROJECT_ID' is required but not set.")
    return project_id

def get_gcs_bucket_name() -> str:
    """Retrieves GCS_BUCKET_NAME from environment."""
    bucket_name = os.getenv("GCS_BUCKET_NAME")
    if not bucket_name:
        raise ValueError("Environment variable 'GCS_BUCKET_NAME' is required but not set.")
    return bucket_name

GCS_DATASET_PATH: str = "datasets/ml/scf_supplier_acceptance_dataset.csv"
GCS_MODEL_PATH: str = "models/supplier_acceptance_model.json"

LOCAL_DATA_DIR: Path = Path(os.getenv("DATASET_LOCAL_OUTPUT_DIR", "data/generated"))
LOCAL_DATA_FILE: Path = LOCAL_DATA_DIR / "scf_supplier_acceptance_dataset.csv"

MODEL_DIR: Path = Path("packages/orchestrator/ml/models")
MODEL_FILE: Path = MODEL_DIR / "supplier_acceptance_model.json"
META_FILE: Path = MODEL_DIR / "model_metadata.json"

CATEGORICAL_FEATURES = [
    "supplier_risk_tier",
    "supplier_sector",
    "buyer_sector",
    "instrument_type",
]

NUMERICAL_FEATURES = [
    "supplier_alt_cost_of_debt_apr",
    "supplier_dso_days",
    "supplier_historical_acceptance_rate",
    "is_anchor_buyer",
    "days_since_last_trade",
    "invoice_face_value_usd",
    "original_tenor_days",
    "days_accelerated",
    "offered_discount_pct",
    "implied_apr",
    "quarter_end_flag",
]

ALL_FEATURE_COLUMNS = CATEGORICAL_FEATURES + NUMERICAL_FEATURES
TARGET_COLUMN = "accepted_early_offer"


class SupplierAcceptanceModel:
    """
    XGBoost Classifier for Supplier Early Payment Acceptance Prediction.
    """

    def __init__(self, model_path: Optional[Path] = None):
        self.model_path = model_path or MODEL_FILE
        self.meta_path = self.model_path.parent / "model_metadata.json"
        self.model: Optional[xgb.XGBClassifier] = None
        self.metadata: dict[str, Any] = {}
        self.categories: dict[str, list[str]] = {}

        if self.model_path.exists():
            self.load()
        else:
            if self.download_from_gcs():
                self.load()

    def download_from_gcs(self) -> bool:
        """Attempts to download model artifact and metadata from GCS."""
        try:
            from google.cloud import storage

            project_id = os.getenv("GCP_PROJECT_ID")
            bucket_name = os.getenv("GCS_BUCKET_NAME")
            if not project_id or not bucket_name:
                return False

            client = storage.Client(project=project_id)
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(GCS_MODEL_PATH)
            if blob.exists():
                self.model_path.parent.mkdir(parents=True, exist_ok=True)
                blob.download_to_filename(str(self.model_path))
                meta_blob = bucket.blob("models/model_metadata.json")
                if meta_blob.exists():
                    meta_blob.download_to_filename(str(self.meta_path))
                print(f"[Model Download] Downloaded model from gs://{bucket_name}/{GCS_MODEL_PATH}")
                return True
        except Exception as e:
            print(f"[Model Download] Could not fetch from GCS: {e}")
        return False

    def _prepare_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Converts categorical columns to pandas 'category' dtype and validates
        numerical fields.
        """
        df_copy = df[ALL_FEATURE_COLUMNS].copy()
        for cat_col in CATEGORICAL_FEATURES:
            if cat_col in df_copy.columns:
                df_copy[cat_col] = df_copy[cat_col].astype("category")
        for num_col in NUMERICAL_FEATURES:
            if num_col in df_copy.columns:
                df_copy[num_col] = pd.to_numeric(df_copy[num_col], errors="coerce").fillna(0.0)
        return df_copy

    def train(
        self,
        df: pd.DataFrame,
        test_size: float = 0.2,
        random_state: int = 42,
    ) -> dict[str, float]:
        """
        Trains the XGBoost classifier on the supplied DataFrame with stratified train/test split.
        """
        print(f"[Model Training] Preparing {len(df):,} records...")

        X = self._prepare_dataframe(df)
        y = df[TARGET_COLUMN].astype(int)

        # Record unique categories for inference alignment
        self.categories = {
            col: sorted(list(X[col].cat.categories)) for col in CATEGORICAL_FEATURES
        }

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=random_state, stratify=y
        )

        print(f"[Model Training] Train size: {len(X_train):,}, Test size: {len(X_test):,}")

        self.model = xgb.XGBClassifier(
            n_estimators=180,
            max_depth=5,
            learning_rate=0.08,
            subsample=0.85,
            colsample_bytree=0.85,
            enable_categorical=True,
            tree_method="hist",
            eval_metric="logloss",
            random_state=random_state,
            n_jobs=-1,
        )

        self.model.fit(
            X_train,
            y_train,
            eval_set=[(X_test, y_test)],
            verbose=False,
        )

        # Evaluations
        y_pred = self.model.predict(X_test)
        y_prob = self.model.predict_proba(X_test)[:, 1]

        metrics = {
            "roc_auc": round(float(roc_auc_score(y_test, y_prob)), 4),
            "accuracy": round(float(accuracy_score(y_test, y_pred)), 4),
            "precision": round(float(precision_score(y_test, y_pred)), 4),
            "recall": round(float(recall_score(y_test, y_pred)), 4),
            "f1": round(float(f1_score(y_test, y_pred)), 4),
            "log_loss": round(float(log_loss(y_test, y_prob)), 4),
        }

        # Feature Importance
        importance_scores = self.model.feature_importances_
        feature_importance = {
            feature: round(float(score), 4)
            for feature, score in zip(ALL_FEATURE_COLUMNS, importance_scores)
        }
        sorted_importance = dict(
            sorted(feature_importance.items(), key=lambda item: item[1], reverse=True)
        )

        self.metadata = {
            "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "dataset_rows": len(df),
            "test_size": test_size,
            "metrics": metrics,
            "feature_importance": sorted_importance,
            "categories": self.categories,
            "features": ALL_FEATURE_COLUMNS,
        }

        print("\n" + "=" * 55)
        print("XGBOOST MODEL TRAINING COMPLETE")
        print("=" * 55)
        print(f"  ROC-AUC:   {metrics['roc_auc']:.4f}")
        print(f"  Accuracy:  {metrics['accuracy']:.2%}")
        print(f"  Precision: {metrics['precision']:.2%}")
        print(f"  Recall:    {metrics['recall']:.2%}")
        print(f"  F1 Score:  {metrics['f1']:.4f}")
        print(f"  Log Loss:  {metrics['log_loss']:.4f}")
        print("\nTop 5 Most Important Features:")
        for feat, score in list(sorted_importance.items())[:5]:
            print(f"  - {feat:35s}: {score:.4f}")
        print("=" * 55)

        self.save()
        return metrics

    def save(self) -> None:
        """Persists model and metadata locally."""
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        if self.model is not None:
            self.model.save_model(str(self.model_path))
            print(f"[Save] Model written to: {self.model_path}")
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, indent=2)
            print(f"[Save] Metadata written to: {self.meta_path}")

    def load(self) -> None:
        """Loads model and metadata from disk."""
        if not self.model_path.exists():
            raise FileNotFoundError(f"Model file not found at {self.model_path}")
        self.model = xgb.XGBClassifier()
        self.model.load_model(str(self.model_path))
        if self.meta_path.exists():
            with open(self.meta_path, "r", encoding="utf-8") as f:
                self.metadata = json.load(f)
                self.categories = self.metadata.get("categories", {})
        print(f"[Load] Model and metadata loaded from {self.model_path}")

    def predict_probability(self, features: dict[str, Any]) -> float:
        """
        Inference method returning acceptance probability in [0.0, 1.0].
        Calculates implied_apr automatically if omitted but discount and days_accelerated exist.
        """
        if self.model is None:
            raise RuntimeError("Model is not loaded or trained. Call train() or load() first.")

        feat_copy = dict(features)

        # Auto-compute implied APR if missing
        if "implied_apr" not in feat_copy or feat_copy["implied_apr"] is None:
            disc = feat_copy.get("offered_discount_pct", 0.0) / 100.0
            days = feat_copy.get("days_accelerated", 1)
            if days > 0 and disc > 0 and disc < 1.0:
                feat_copy["implied_apr"] = round((disc / (1.0 - disc)) * (365.0 / days) * 100.0, 4)
            else:
                feat_copy["implied_apr"] = 0.0

        # Construct single-row DataFrame
        row_dict = {}
        for col in ALL_FEATURE_COLUMNS:
            row_dict[col] = [feat_copy.get(col, 0.0 if col in NUMERICAL_FEATURES else "UNKNOWN")]

        df_row = pd.DataFrame(row_dict)

        # Enforce exact category levels from training
        for cat_col in CATEGORICAL_FEATURES:
            cats = self.categories.get(cat_col, [])
            val = str(df_row[cat_col].iloc[0])
            mapped_val = val if val in cats else (cats[0] if cats else None)
            df_row[cat_col] = pd.Categorical([mapped_val], categories=cats)

        prob = float(self.model.predict_proba(df_row)[:, 1][0])
        return round(prob, 4)

    def predict_acceptance_curve(
        self,
        base_features: dict[str, Any],
        discount_rates: Optional[list[float]] = None,
    ) -> list[dict[str, Any]]:
        """
        Generates price elasticity curve for a given invoice and supplier context
        across multiple candidate discount percentages.
        """
        if discount_rates is None:
            # Standard exploration range: 0.25% to 3.0% discount in increments of 0.25%
            discount_rates = [round(r, 2) for r in np.arange(0.25, 3.25, 0.25)]

        curve = []
        days_acc = base_features.get("days_accelerated", 30)

        for disc in discount_rates:
            trial_features = dict(base_features)
            trial_features["offered_discount_pct"] = disc
            # Recompute implied APR
            d_frac = disc / 100.0
            trial_features["implied_apr"] = round(
                (d_frac / (1.0 - d_frac)) * (365.0 / max(1, days_acc)) * 100.0, 4
            )
            prob = self.predict_probability(trial_features)
            curve.append(
                {
                    "discount_pct": disc,
                    "implied_apr": trial_features["implied_apr"],
                    "acceptance_probability": prob,
                    "expected_acceptance": bool(prob >= 0.50),
                }
            )

        return curve


# ---------------------------------------------------------------------------
# GCS / Dataset Helpers
# ---------------------------------------------------------------------------

def load_training_data() -> pd.DataFrame:
    """
    Loads training dataset: checks local file first, then falls back to GCS.
    """
    if LOCAL_DATA_FILE.exists():
        print(f"[Data Loader] Loading local dataset from {LOCAL_DATA_FILE}...")
        return pd.read_csv(LOCAL_DATA_FILE)

    bucket_name = get_gcs_bucket_name()
    print(f"[Data Loader] Local dataset not found. Streaming from gs://{bucket_name}/{GCS_DATASET_PATH}...")
    from packages.orchestrator.ml.gcs_uploader import download_dataset
    download_dataset(GCS_DATASET_PATH, LOCAL_DATA_FILE)
    return pd.read_csv(LOCAL_DATA_FILE)


def sync_model_to_gcs() -> None:
    """
    Uploads trained model and metadata to GCS bucket for remote versioning.
    """
    from google.cloud import storage

    project_id = get_gcp_project_id()
    bucket_name = get_gcs_bucket_name()

    client = storage.Client(project=project_id)
    bucket = client.bucket(bucket_name)

    if MODEL_FILE.exists():
        blob = bucket.blob(GCS_MODEL_PATH)
        blob.upload_from_filename(str(MODEL_FILE))
        print(f"[GCS Sync] Model uploaded -> gs://{bucket_name}/{GCS_MODEL_PATH}")

    if META_FILE.exists():
        meta_blob = bucket.blob("models/model_metadata.json")
        meta_blob.upload_from_filename(str(META_FILE))
        print(f"[GCS Sync] Metadata uploaded -> gs://{bucket_name}/models/model_metadata.json")


def train_and_export() -> tuple[SupplierAcceptanceModel, dict[str, float]]:
    """
    End-to-end execution: loads data, trains model, exports artifacts, and syncs to GCS.
    """
    df = load_training_data()
    model = SupplierAcceptanceModel()
    metrics = model.train(df)

    try:
        sync_model_to_gcs()
    except Exception as e:
        print(f"[GCS Sync Warning] Could not sync model to GCS: {e}")

    return model, metrics


if __name__ == "__main__":
    train_and_export()
