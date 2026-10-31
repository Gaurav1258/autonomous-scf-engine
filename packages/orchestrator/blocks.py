"""
packages/orchestrator/blocks.py
===============================
Certified AgentBPMN Domain Blocks for the Autonomous SCF Multi-Agent Engine.
Encapsulates institutional trading logic, XGBoost ML elasticity models,
and credit limit guardrails into strongly-typed, auditable domain capabilities.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel, Field

# Ensure agent_bpmn is importable (installed or from sibling repo)
try:
    import agent_bpmn
except ImportError:
    for candidate in [
        Path(__file__).resolve().parents[3] / "lang-bpmn",
        Path("D:/Projects/lang-bpmn"),
    ]:
        if candidate.exists() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
            break
    import agent_bpmn

from agent_bpmn.sdk import domain_block, registry
from packages.orchestrator.nodes.capital_structurer import capital_structurer_node
from packages.orchestrator.nodes.cash_forecaster import cash_forecaster_node
from packages.orchestrator.nodes.guardrail_validator import guardrail_validator_node
from packages.orchestrator.nodes.risk_sentinel import risk_sentinel_node
from packages.orchestrator.nodes.treasury_dispatcher import treasury_dispatcher_node
from packages.orchestrator.state import (
    CapitalStructureOption,
    CashForecastOutput,
    FinalExecutionPayload,
    GuardrailValidationOutput,
    RiskSentinelOutput,
    WorkflowStatus,
)


# ---------------------------------------------------------------------------
# 1. Cash Forecaster Domain Block
# ---------------------------------------------------------------------------

class CashForecasterBlockInput(BaseModel):
    """Input payload for the Corporate Cash Forecaster domain block."""
    raw_invoice: dict[str, Any] = Field(..., description="Raw ERP invoice payload")


class CashForecasterBlockOutput(BaseModel):
    """Output payload from the Corporate Cash Forecaster domain block."""
    cash_forecast: CashForecastOutput = Field(..., description="60-day cash curve and liquidity assessment")
    audit_trail: list[str] = Field(default_factory=list, description="Audit trail entries")


@domain_block(
    id="scf.cash_forecaster",
    name="Corporate Cash Forecaster",
    department="Treasury Operations",
    description="Evaluates corporate buyer 60-day cash trajectory, operational liquidity floor, and bank facility headroom.",
    icon="trending-up",
    estimated_cost_usd=0.003,
    p95_latency_ms=500,
    tags=["scf", "cash", "forecasting", "treasury"],
)
def scf_cash_forecaster_block(payload: CashForecasterBlockInput) -> CashForecasterBlockOutput:
    result = cash_forecaster_node({"raw_invoice": payload.raw_invoice})
    return CashForecasterBlockOutput(
        cash_forecast=result["cash_forecast"],
        audit_trail=result.get("audit_trail", []),
    )


# ---------------------------------------------------------------------------
# 2. Risk Sentinel Domain Block
# ---------------------------------------------------------------------------

class RiskSentinelBlockInput(BaseModel):
    """Input payload for the Vendor Entity Resolution & AML/Sanctions block."""
    raw_invoice: dict[str, Any] = Field(..., description="Raw ERP invoice payload")


class RiskSentinelBlockOutput(BaseModel):
    """Output payload from the Risk Sentinel block."""
    risk_profile: RiskSentinelOutput = Field(..., description="Normalized vendor Golden Record and AML clearance")
    status: WorkflowStatus = Field(..., description="Workflow lifecycle status after sanctions verification")
    audit_trail: list[str] = Field(default_factory=list, description="Audit entries")
    errors: list[str] = Field(default_factory=list, description="Compliance violation reasons if flagged")


@domain_block(
    id="scf.risk_sentinel",
    name="Vendor Risk & Sanctions Sentinel",
    department="Compliance & AML",
    description="Fuzzy-matches ERP vendor strings to canonical records, verifies duplicate invoices, and screens against OFAC sanctions watchlists.",
    icon="shield-alert",
    estimated_cost_usd=0.004,
    p95_latency_ms=650,
    tags=["scf", "compliance", "ofac", "kyc", "sanctions"],
)
def scf_risk_sentinel_block(payload: RiskSentinelBlockInput) -> RiskSentinelBlockOutput:
    result = risk_sentinel_node({"raw_invoice": payload.raw_invoice})
    return RiskSentinelBlockOutput(
        risk_profile=result["risk_profile"],
        status=result["status"],
        audit_trail=result.get("audit_trail", []),
        errors=result.get("errors", []),
    )


# ---------------------------------------------------------------------------
# 3. Capital Structurer Domain Block
# ---------------------------------------------------------------------------

class CapitalStructurerBlockInput(BaseModel):
    """Input payload for the Optimal Capital Structurer block."""
    raw_invoice: dict[str, Any] = Field(default_factory=dict, description="Raw ERP invoice")
    cash_forecast: Optional[CashForecastOutput] = Field(default=None, description="Cash forecast from Node 1")
    risk_profile: Optional[RiskSentinelOutput] = Field(default=None, description="Risk profile from Node 2")


class CapitalStructurerBlockOutput(BaseModel):
    """Output payload from the Capital Structurer block."""
    optimal_structure: Optional[CapitalStructureOption] = Field(default=None, description="Optimal win-win financing terms")
    candidate_curve: Optional[list[dict[str, Any]]] = Field(default=None, description="Evaluated candidate APR options")
    audit_trail: list[str] = Field(default_factory=list, description="Audit entries")


@domain_block(
    id="scf.capital_structurer",
    name="Optimal Capital Structurer",
    department="Financial Structuring",
    description="Sweeps APR elasticity curve and uses XGBoost supplier acceptance ML to find the Pareto-optimal financing structure.",
    icon="sliders",
    estimated_cost_usd=0.005,
    p95_latency_ms=750,
    tags=["scf", "structuring", "ml", "xgboost", "discounting"],
)
def scf_capital_structurer_block(payload: CapitalStructurerBlockInput) -> CapitalStructurerBlockOutput:
    result = capital_structurer_node({
        "raw_invoice": payload.raw_invoice,
        "cash_forecast": payload.cash_forecast,
        "risk_profile": payload.risk_profile,
    })
    return CapitalStructurerBlockOutput(
        optimal_structure=result.get("optimal_structure"),
        candidate_curve=result.get("candidate_curve"),
        audit_trail=result.get("audit_trail", []),
    )


# ---------------------------------------------------------------------------
# 4. Guardrail Validator Domain Block
# ---------------------------------------------------------------------------

class GuardrailValidatorBlockInput(BaseModel):
    """Input payload for the Pre-Flight Guardrail Validator block."""
    raw_invoice: dict[str, Any] = Field(default_factory=dict, description="Raw ERP invoice")
    cash_forecast: Optional[CashForecastOutput] = Field(default=None, description="Cash forecast")
    risk_profile: Optional[RiskSentinelOutput] = Field(default=None, description="Risk profile")
    optimal_structure: Optional[CapitalStructureOption] = Field(default=None, description="Proposed structure")


class GuardrailValidatorBlockOutput(BaseModel):
    """Output payload from the Guardrail Validator block."""
    guardrail_verdict: Optional[GuardrailValidationOutput] = Field(default=None, description="Credit limit and concentration verdict")
    status: WorkflowStatus = Field(..., description="Workflow status after guardrail evaluation")
    audit_trail: list[str] = Field(default_factory=list, description="Audit entries")


@domain_block(
    id="scf.guardrail_validator",
    name="Pre-Flight Credit Guardrail Validator",
    department="Risk Management",
    description="Enforces hard revolving credit facility headroom and single-supplier 15% concentration caps with cryptographic SHA256 signing.",
    icon="lock",
    estimated_cost_usd=0.002,
    p95_latency_ms=300,
    tags=["scf", "risk", "credit_limit", "guardrails"],
)
def scf_guardrail_validator_block(payload: GuardrailValidatorBlockInput) -> GuardrailValidatorBlockOutput:
    result = guardrail_validator_node({
        "raw_invoice": payload.raw_invoice,
        "cash_forecast": payload.cash_forecast,
        "risk_profile": payload.risk_profile,
        "optimal_structure": payload.optimal_structure,
    })
    return GuardrailValidatorBlockOutput(
        guardrail_verdict=result.get("guardrail_verdict"),
        status=result.get("status", WorkflowStatus.ANALYZING),
        audit_trail=result.get("audit_trail", []),
    )


# ---------------------------------------------------------------------------
# 5. Treasury Dispatcher Domain Block
# ---------------------------------------------------------------------------

class TreasuryDispatcherBlockInput(BaseModel):
    """Input payload for the 1-Click Offer Dispatcher block."""
    raw_invoice: dict[str, Any] = Field(default_factory=dict, description="Raw ERP invoice")
    cash_forecast: Optional[CashForecastOutput] = Field(default=None, description="Cash forecast")
    risk_profile: Optional[RiskSentinelOutput] = Field(default=None, description="Risk profile")
    optimal_structure: Optional[CapitalStructureOption] = Field(default=None, description="Optimal structure")
    guardrail_verdict: Optional[GuardrailValidationOutput] = Field(default=None, description="Guardrail verdict")
    status: WorkflowStatus = Field(default=WorkflowStatus.ANALYZING, description="Current workflow status")


class TreasuryDispatcherBlockOutput(BaseModel):
    """Output payload from the Treasury Dispatcher block."""
    final_payload: Optional[FinalExecutionPayload] = Field(default=None, description="1-click dual-approval execution payload")
    status: WorkflowStatus = Field(..., description="Final workflow status")
    audit_trail: list[str] = Field(default_factory=list, description="Audit entries")


@domain_block(
    id="scf.treasury_dispatcher",
    name="1-Click Treasury Offer Dispatcher",
    department="Treasury Operations",
    description="Packages pre-flight approved offers with cryptographic action tokens, treasurer approval URLs, and supplier portal links.",
    icon="send",
    estimated_cost_usd=0.002,
    p95_latency_ms=400,
    tags=["scf", "treasury", "dispatch", "settlement"],
)
def scf_treasury_dispatcher_block(payload: TreasuryDispatcherBlockInput) -> TreasuryDispatcherBlockOutput:
    result = treasury_dispatcher_node({
        "raw_invoice": payload.raw_invoice,
        "cash_forecast": payload.cash_forecast,
        "risk_profile": payload.risk_profile,
        "optimal_structure": payload.optimal_structure,
        "guardrail_verdict": payload.guardrail_verdict,
        "status": payload.status,
    })
    return TreasuryDispatcherBlockOutput(
        final_payload=result.get("final_payload"),
        status=result.get("status", payload.status),
        audit_trail=result.get("audit_trail", []),
    )


def register_scf_blocks() -> None:
    """Ensures all 5 certified SCF domain blocks are loaded and registered in AgentBPMN."""
    assert registry.has("scf.cash_forecaster")
    assert registry.has("scf.risk_sentinel")
    assert registry.has("scf.capital_structurer")
    assert registry.has("scf.guardrail_validator")
    assert registry.has("scf.treasury_dispatcher")

