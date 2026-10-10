"""
packages/orchestrator/graph.py
==============================
The Master LangGraph Multi-Agent State Machine for Autonomous SCF.

Topology & Execution Flow:

                  [START]
                     │
                     ▼
             1. cash_forecaster
                     │
                     ▼
             2. risk_sentinel
                     │
         [route_after_risk_sentinel]
          ├── If REJECTED_SANCTIONS or DUPLICATE ──────────► [END] (Compliance Freeze)
          └── If CLEAN (ANALYZING) ─────────────────────────► 3. capital_structurer
                                                                    │
                                                                    ▼
                                                            4. guardrail_validator
                                                                    │
                                                         [route_after_guardrails]
                                                          ├── If REJECTED_GUARDRAIL ──► [END] (Credit Cap Breach)
                                                          └── If APPROVED ────────────► 5. treasury_dispatcher
                                                                                                │
                                                                                                ▼
                                                                                              [END] (Dispatched)
"""

from __future__ import annotations

from typing import Any, Literal, Optional
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from packages.orchestrator.nodes.capital_structurer import capital_structurer_node
from packages.orchestrator.nodes.cash_forecaster import cash_forecaster_node
from packages.orchestrator.nodes.guardrail_validator import guardrail_validator_node
from packages.orchestrator.nodes.risk_sentinel import risk_sentinel_node
from packages.orchestrator.nodes.treasury_dispatcher import treasury_dispatcher_node
from packages.orchestrator.state import SCFGraphState, WorkflowStatus


# ---------------------------------------------------------------------------
# Conditional Routing Functions
# ---------------------------------------------------------------------------

def route_after_risk_sentinel(
    state: SCFGraphState,
) -> Literal["capital_structurer", "__end__"]:
    """
    Evaluates the compliance and fraud check from Node 2 (Risk Sentinel).

    If the supplier is on a sanctions list (OFAC) or the invoice is a duplicate,
    short-circuit immediately to END. Never compute financial math on illicit entities.
    """
    status = state.get("status")
    if status in (WorkflowStatus.REJECTED_SANCTIONS, WorkflowStatus.REJECTED_GUARDRAIL):
        return END
    return "capital_structurer"


def route_after_guardrails(
    state: SCFGraphState,
) -> Literal["treasury_dispatcher", "__end__"]:
    """
    Evaluates the credit limit and concentration check from Node 4 (Guardrail Validator).

    If the proposed advance breaches credit headroom or the 15% single-supplier cap,
    halt immediately at END. Only dispatch pre-flight approved offers.
    """
    status = state.get("status")
    if status == WorkflowStatus.REJECTED_GUARDRAIL:
        return END
    return "treasury_dispatcher"


# ---------------------------------------------------------------------------
# Graph Assembly & Compilation
# ---------------------------------------------------------------------------

def build_scf_graph(checkpointer: Optional[Any] = None) -> StateGraph:
    """
    Constructs and returns the compiled LangGraph StateGraph.

    Args:
        checkpointer: Optional persistence checkpointer (e.g., MemorySaver)
                      to pause execution for human-in-the-loop approvals.

    Returns:
        A compiled LangGraph runnable application.
    """
    # 1. Initialize StateGraph with the shared state contract
    workflow = StateGraph(SCFGraphState)

    # 2. Register the 5 Agent Worker Nodes
    workflow.add_node("cash_forecaster", cash_forecaster_node)
    workflow.add_node("risk_sentinel", risk_sentinel_node)
    workflow.add_node("capital_structurer", capital_structurer_node)
    workflow.add_node("guardrail_validator", guardrail_validator_node)
    workflow.add_node("treasury_dispatcher", treasury_dispatcher_node)

    # 3. Define Edges (How Nodes Connect)
    # Entrypoint: Start immediately at the Cash Forecaster
    workflow.add_edge(START, "cash_forecaster")

    # From Cash Forecaster -> Always proceed to Risk Sentinel
    workflow.add_edge("cash_forecaster", "risk_sentinel")

    # Conditional Branch after Risk Sentinel:
    # If sanctions hit -> END. If clean -> capital_structurer
    workflow.add_conditional_edges(
        "risk_sentinel",
        route_after_risk_sentinel,
        {
            "capital_structurer": "capital_structurer",
            END: END,
        },
    )

    # From Capital Structurer -> Always proceed to Guardrail Validator
    workflow.add_edge("capital_structurer", "guardrail_validator")

    # Conditional Branch after Guardrail Validator:
    # If limit breached -> END. If approved -> treasury_dispatcher
    workflow.add_conditional_edges(
        "guardrail_validator",
        route_after_guardrails,
        {
            "treasury_dispatcher": "treasury_dispatcher",
            END: END,
        },
    )

    # From Treasury Dispatcher -> Workflow complete
    workflow.add_edge("treasury_dispatcher", END)

    # 4. Compile the graph with optional checkpointing
    return workflow.compile(checkpointer=checkpointer)


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

