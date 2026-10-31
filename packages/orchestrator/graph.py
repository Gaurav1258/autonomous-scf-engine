"""
packages/orchestrator/graph.py
==============================
The Master Multi-Agent Process Engine for Autonomous SCF, powered by AgentBPMN (lang-bpmn).

Topology & Execution Flow:

                  [START]
                     │
                     ▼
             1. cash_forecaster (scf.cash_forecaster)
                     │
                     ▼
             2. risk_sentinel (scf.risk_sentinel)
                     │
          [Conditional Routing]
          ├── If REJECTED_SANCTIONS or DUPLICATE ──────────► [END] (Compliance Freeze)
          └── If CLEAN (ANALYZING) ─────────────────────────► 3. capital_structurer (scf.capital_structurer)
                                                                    │
                                                                    ▼
                                                            4. guardrail_validator (scf.guardrail_validator)
                                                                    │
                                                         [Conditional Routing]
                                                          ├── If REJECTED_GUARDRAIL ──► [END] (Credit Cap Breach)
                                                          └── If APPROVED ────────────► 5. treasury_dispatcher (scf.treasury_dispatcher)
                                                                                                │
                                                                                                ▼
                                                                                              [END] (Dispatched)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Literal, Optional

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

from agent_bpmn.compiler import CompiledWorkflow, GraphCompiler
from agent_bpmn.dsl import (
    NodeType,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowGuardrails,
    WorkflowMetadata,
    WorkflowNode,
    parse_workflow_yaml,
)
from packages.orchestrator.blocks import register_scf_blocks
from packages.orchestrator.state import SCFGraphState, WorkflowStatus

# Path to declarative workflow YAML definition
WORKFLOW_YAML_PATH = Path(__file__).resolve().parent / "scf_workflow.yaml"


# ---------------------------------------------------------------------------
# Declarative Workflow Topology
# ---------------------------------------------------------------------------

def get_scf_workflow_definition() -> WorkflowDefinition:
    """
    Returns the declarative WorkflowDefinition AST for Autonomous SCF.
    Loads from scf_workflow.yaml if present, or constructs the programmatic AST.
    """
    if WORKFLOW_YAML_PATH.exists():
        try:
            return parse_workflow_yaml(WORKFLOW_YAML_PATH)
        except Exception:
            pass

    return WorkflowDefinition(
        metadata=WorkflowMetadata(
            id="autonomous_scf_pipeline",
            name="Autonomous Supply Chain Finance Multi-Agent Engine",
            version="1.0.0",
            owner_department="Treasury Operations",
            description="AgentBPMN orchestration for autonomous early payment discounting and risk validation.",
        ),
        guardrails=WorkflowGuardrails(
            max_total_budget_usd=1.00,
            workflow_timeout_seconds=300,
            max_loop_iterations=3,
        ),
        nodes=[
            WorkflowNode(
                id="cash_forecaster",
                type=NodeType.BLOCK,
                name="Corporate Cash Forecaster",
                block="scf.cash_forecaster",
            ),
            WorkflowNode(
                id="risk_sentinel",
                type=NodeType.BLOCK,
                name="Vendor Risk & Sanctions Sentinel",
                block="scf.risk_sentinel",
            ),
            WorkflowNode(
                id="capital_structurer",
                type=NodeType.BLOCK,
                name="Optimal Capital Structurer",
                block="scf.capital_structurer",
            ),
            WorkflowNode(
                id="guardrail_validator",
                type=NodeType.BLOCK,
                name="Pre-Flight Credit Guardrail Validator",
                block="scf.guardrail_validator",
            ),
            WorkflowNode(
                id="treasury_dispatcher",
                type=NodeType.BLOCK,
                name="1-Click Treasury Offer Dispatcher",
                block="scf.treasury_dispatcher",
            ),
        ],
        edges=[
            WorkflowEdge(source="START", target="cash_forecaster"),
            WorkflowEdge(source="cash_forecaster", target="risk_sentinel"),
            WorkflowEdge(
                source="risk_sentinel",
                target="END",
                condition="status == 'REJECTED_SANCTIONS' or status == 'REJECTED_GUARDRAIL'",
            ),
            WorkflowEdge(
                source="risk_sentinel",
                target="capital_structurer",
                condition="status != 'REJECTED_SANCTIONS' and status != 'REJECTED_GUARDRAIL'",
            ),
            WorkflowEdge(source="capital_structurer", target="guardrail_validator"),
            WorkflowEdge(
                source="guardrail_validator",
                target="END",
                condition="status == 'REJECTED_GUARDRAIL'",
            ),
            WorkflowEdge(
                source="guardrail_validator",
                target="treasury_dispatcher",
                condition="status != 'REJECTED_GUARDRAIL'",
            ),
            WorkflowEdge(source="treasury_dispatcher", target="END"),
        ],
    )


# ---------------------------------------------------------------------------
# Conditional Routing Helper Functions (Preserved for compatibility)
# ---------------------------------------------------------------------------

def route_after_risk_sentinel(
    state: SCFGraphState,
) -> Literal["capital_structurer", "__end__"]:
    """Evaluates compliance / duplicate status after Node 2."""
    status = state.get("status")
    if status in (WorkflowStatus.REJECTED_SANCTIONS, WorkflowStatus.REJECTED_GUARDRAIL):
        return "__end__"
    return "capital_structurer"


def route_after_guardrails(
    state: SCFGraphState,
) -> Literal["treasury_dispatcher", "__end__"]:
    """Evaluates credit headroom and concentration check after Node 4."""
    status = state.get("status")
    if status == WorkflowStatus.REJECTED_GUARDRAIL:
        return "__end__"
    return "treasury_dispatcher"


# ---------------------------------------------------------------------------
# Graph Assembly & Compilation via AgentBPMN GraphCompiler
# ---------------------------------------------------------------------------

def build_scf_graph(checkpointer: Optional[Any] = None) -> CompiledWorkflow:
    """
    Constructs and returns the compiled AgentBPMN workflow.
    Translates declarative BPMN nodes and certified domain blocks into an executable runtime
    with Process Intelligence Heatmap telemetry, SLA timers, and guardrails.

    Args:
        checkpointer: Optional persistence checkpointer (e.g., MemorySaver)
                      to pause execution for human-in-the-loop approvals.

    Returns:
        A CompiledWorkflow runnable application with .invoke(), .ainvoke(), and .astream().
    """
    # 1. Ensure all 5 certified SCF domain blocks are registered
    register_scf_blocks()

    # 2. Load declarative workflow definition AST
    workflow = get_scf_workflow_definition()

    # 3. Compile declarative AST via AgentBPMN GraphCompiler
    compiler = GraphCompiler(checkpointer=checkpointer)
    return compiler.compile(workflow)


def create_initial_state(raw_invoice: dict[str, Any]) -> SCFGraphState:
    """Convenience helper to initialize an empty state dossier for a raw invoice."""
    return {
        "raw_invoice": raw_invoice,
        "cash_forecast": None,
        "risk_profile": None,
        "optimal_structure": None,
        "candidate_curve": None,
        "guardrail_verdict": None,
        "final_payload": None,
        "status": WorkflowStatus.PENDING,
        "audit_trail": ["Workflow initialized. Starting autonomous SCF analysis."],
        "errors": [],
    }
