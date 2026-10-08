"""
tests/test_acceptance_ml.py
===========================
Rigorous test suite for the XGBoost Supplier Early Payment Acceptance Model.

Test Dimensions:
1. Artifact Verification: Model JSON and metadata exist with valid evaluation metrics.
2. Probability Invariants: Output probabilities strictly bounded in [0.0, 1.0].
3. Economic Monotonicity: Higher offered discount / implied APR leads to lower acceptance probability.
4. Risk Tier Sensitivity: Lower-tier (cash-starved) suppliers exhibit higher acceptance probability.
5. Macroeconomic Seasonality: Quarter-end liquidity squeezes increase acceptance propensity.
6. Latency Benchmarks: Single-item inference completes in < 15ms.
7. Robustness: Gracefully handles unseen categories and missing optional features.

Run:
    uv run pytest tests/test_acceptance_ml.py -v
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from packages.orchestrator.ml.acceptance_model import (
    MODEL_FILE,
    META_FILE,
    SupplierAcceptanceModel,
)


@pytest.fixture(scope="module")
def loaded_model() -> SupplierAcceptanceModel:
    """Fixture providing a loaded instance of the trained model (downloads or trains if missing)."""
    model = SupplierAcceptanceModel(model_path=MODEL_FILE)
    if not MODEL_FILE.exists() or model.model is None:
        from packages.orchestrator.ml.acceptance_model import train_and_export
        model, _ = train_and_export()
    return model


@pytest.fixture
def base_invoice_features() -> dict:
    """Standard corporate invoice telemetry for inference testing."""
    return {
        "supplier_risk_tier": "TIER_2_STABLE",
        "supplier_sector": "Manufacturing",
        "buyer_sector": "Conglomerate",
        "instrument_type": "DYNAMIC_DISCOUNTING",
        "supplier_alt_cost_of_debt_apr": 14.0,
        "supplier_dso_days": 65.0,
        "supplier_historical_acceptance_rate": 0.55,
        "is_anchor_buyer": 1,
        "days_since_last_trade": 18,
        "invoice_face_value_usd": 250_000.0,
        "original_tenor_days": 60,
        "days_accelerated": 35,
        "offered_discount_pct": 1.25,
        "implied_apr": 13.25,
        "quarter_end_flag": 0,
    }


class TestModelArtifactsAndMetrics:
    """Verify saved artifacts and performance benchmarks."""

    def test_model_files_exist(self, loaded_model):
        assert MODEL_FILE.exists(), "Model artifact file missing"
        assert META_FILE.exists(), "Model metadata file missing"
        assert MODEL_FILE.stat().st_size > 10_000, "Model file seems too small"

    def test_metadata_has_quality_metrics(self, loaded_model):
        meta = loaded_model.metadata
        assert "metrics" in meta, "Metrics key missing from metadata"
        metrics = meta["metrics"]

        # Benchmarks: model must significantly outperform random guess (0.50)
        assert metrics["roc_auc"] >= 0.70, f"ROC-AUC too low: {metrics['roc_auc']}"
        assert metrics["accuracy"] >= 0.60, f"Accuracy too low: {metrics['accuracy']}"
        assert metrics["log_loss"] <= 0.68, f"Log loss too high: {metrics['log_loss']}"

    def test_key_features_present_in_importance(self, loaded_model):
        importance = loaded_model.metadata.get("feature_importance", {})
        assert len(importance) > 0, "Feature importance dictionary empty"
        # Financial drivers must be among the top features
        top_3 = list(importance.keys())[:3]
        assert any("apr" in feat.lower() or "tier" in feat.lower() for feat in top_3), (
            f"Expected financial drivers in top 3 features, got {top_3}"
        )


class TestInferenceBoundsAndBehavior:
    """Verify inference validity and microeconomic behavior."""

    def test_probability_strictly_bounded(self, loaded_model, base_invoice_features):
        prob = loaded_model.predict_probability(base_invoice_features)
        assert 0.0 <= prob <= 1.0, f"Probability out of bounds: {prob}"

    def test_auto_computes_implied_apr_when_omitted(self, loaded_model, base_invoice_features):
        features_without_apr = dict(base_invoice_features)
        del features_without_apr["implied_apr"]

        prob = loaded_model.predict_probability(features_without_apr)
        assert 0.0 <= prob <= 1.0

    def test_economic_monotonicity_higher_discount_lowers_acceptance(
        self, loaded_model, base_invoice_features
    ):
        """
        Microeconomic law: as the discount haircut requested from the supplier increases,
        acceptance probability must decrease or remain steady (price elasticity).
        """
        low_discount = dict(base_invoice_features, offered_discount_pct=0.50, implied_apr=5.3)
        med_discount = dict(base_invoice_features, offered_discount_pct=1.50, implied_apr=16.1)
        high_discount = dict(base_invoice_features, offered_discount_pct=3.50, implied_apr=39.5)

        prob_low = loaded_model.predict_probability(low_discount)
        prob_med = loaded_model.predict_probability(med_discount)
        prob_high = loaded_model.predict_probability(high_discount)

        assert prob_low >= prob_med, f"Low discount ({prob_low}) should have >= acceptance than med ({prob_med})"
        assert prob_med >= prob_high, f"Med discount ({prob_med}) should have >= acceptance than high ({prob_high})"

    def test_risk_tier_sensitivity_distressed_accepts_more(
        self, loaded_model, base_invoice_features
    ):
        """
        Suppliers in higher risk tiers (TIER_3_ELEVATED) face higher cost of debt
        and are more eager to accept liquidity advances than prime suppliers (TIER_1_PRIME).
        """
        tier1_features = dict(
            base_invoice_features,
            supplier_risk_tier="TIER_1_PRIME",
            supplier_alt_cost_of_debt_apr=9.0,
            supplier_dso_days=45.0,
            offered_discount_pct=1.5,
            implied_apr=16.0,
        )
        tier3_features = dict(
            base_invoice_features,
            supplier_risk_tier="TIER_3_ELEVATED",
            supplier_alt_cost_of_debt_apr=21.0,
            supplier_dso_days=85.0,
            offered_discount_pct=1.5,
            implied_apr=16.0,
        )

        prob_tier1 = loaded_model.predict_probability(tier1_features)
        prob_tier3 = loaded_model.predict_probability(tier3_features)

        assert prob_tier3 > prob_tier1, (
            f"Tier 3 distressed supplier ({prob_tier3}) must accept more readily than Tier 1 ({prob_tier1})"
        )

    def test_quarter_end_boost(self, loaded_model, base_invoice_features):
        """Quarter-end cash crunch should increase or maintain acceptance likelihood."""
        normal_day = dict(base_invoice_features, quarter_end_flag=0)
        quarter_end = dict(base_invoice_features, quarter_end_flag=1)

        prob_normal = loaded_model.predict_probability(normal_day)
        prob_qend = loaded_model.predict_probability(quarter_end)

        assert prob_qend >= prob_normal - 0.05, "Quarter-end should not significantly penalize acceptance"


class TestElasticityCurveAndPerformance:
    """Verify curve generator and execution speed."""

    def test_predict_acceptance_curve_structure(self, loaded_model, base_invoice_features):
        rates = [0.5, 1.0, 1.5, 2.0, 2.5]
        curve = loaded_model.predict_acceptance_curve(base_invoice_features, discount_rates=rates)

        assert len(curve) == len(rates)
        for i, pt in enumerate(curve):
            assert pt["discount_pct"] == rates[i]
            assert "implied_apr" in pt
            assert "acceptance_probability" in pt
            assert 0.0 <= pt["acceptance_probability"] <= 1.0
            assert isinstance(pt["expected_acceptance"], bool)

        # Probabilities along curve should be generally declining
        probs = [pt["acceptance_probability"] for pt in curve]
        assert probs[0] >= probs[-1], f"Curve start ({probs[0]}) should exceed curve end ({probs[-1]})"

    def test_inference_latency_benchmark(self, loaded_model, base_invoice_features):
        """Single inference must complete under 15ms for real-time agent loops."""
        # Warmup
        loaded_model.predict_probability(base_invoice_features)

        start = time.perf_counter()
        iterations = 50
        for _ in range(iterations):
            loaded_model.predict_probability(base_invoice_features)
        duration = (time.perf_counter() - start) / iterations * 1000  # ms

        assert duration < 15.0, f"Average inference latency too high: {duration:.2f}ms (threshold: 15ms)"

    def test_unseen_category_handling_robustness(self, loaded_model, base_invoice_features):
        """Model must not crash when encountering previously unseen category labels."""
        weird_features = dict(
            base_invoice_features,
            supplier_sector="RareExoticMetalsMining",
            buyer_sector="SpaceExploration",
        )
        prob = loaded_model.predict_probability(weird_features)
        assert 0.0 <= prob <= 1.0

