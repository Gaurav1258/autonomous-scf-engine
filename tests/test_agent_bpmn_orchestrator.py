"""
tests/test_agent_bpmn_orchestrator.py
=====================================
Integration tests verifying AgentBPMN (lang-bpmn) orchestration for Autonomous SCF:
1. Certified Domain Block registration & Capability Catalog.
2. CompiledWorkflow execution, step-by-step state accumulation, and short-circuits.
3. Process Intelligence Heatmap telemetry tracking.
4. Declarative YAML AST specification integrity.
"""

from __future__ import annotations

import sys
from pathlib import Path
import pytest

# Ensure agent_bpmn is importable
try:
    import agent_bpmn
except ImportError:
    for candidate in [
        Path(__file__).resolve().parents[2] / "lang-bpmn",
        Path("D:/Projects/lang-bpmn"),
    ]:
        if candidate.exists() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
            break
    import agent_bpmn

from agent_bpmn.compiler import CompiledWorkflow
from agent_bpmn.sdk import registry
from packages.orchestrator.blocks import register_scf_blocks
from packages.orchestrator.graph import build_scf_graph, create_initial_state, get_scf_workflow_definition
from packages.orchestrator.state import WorkflowStatus


class TestAgentBPMNOrchestrator:
    """Verifies that the SCF engine is orchestrating via AgentBPMN."""

    def test_certified_domain_blocks_registered(self):
        """All 5 SCF domain blocks are certified and present in the Capability Registry."""
        register_scf_blocks()

        expected_blocks = [
            "scf.cash_forecaster",
            "scf.risk_sentinel",
            "scf.capital_structurer",
            "scf.guardrail_validator",
            "scf.treasury_dispatcher",
        ]
        for blk_id in expected_blocks:
            assert registry.has(blk_id), f"Missing domain block: {blk_id}"
            contract = registry.get(blk_id).contract
            assert contract.metadata.department in (
                "Treasury Operations",
                "Compliance & AML",
                "Financial Structuring",
                "Risk Management",
            )
            assert contract.metadata.estimated_cost_usd > 0
            assert contract.metadata.p95_latency_ms > 0

    def test_workflow_definition_ast_structure(self):
        """Declarative workflow definition matches the 5-node SCF topology with guardrails."""
        wf = get_scf_workflow_definition()
        assert wf.metadata.id == "autonomous_scf_pipeline"
        assert len(wf.nodes) == 5
        assert wf.guardrails.max_total_budget_usd == 1.00
        assert wf.guardrails.max_loop_iterations == 3

        node_ids = [n.id for n in wf.nodes]
        assert node_ids == [
            "cash_forecaster",
            "risk_sentinel",
            "capital_structurer",
            "guardrail_validator",
            "treasury_dispatcher",
        ]

    def test_compiled_workflow_execution_and_heatmap_telemetry(self):
        """Executing CompiledWorkflow accumulates state and records Process Intelligence Heatmap."""
        app = build_scf_graph()
        assert isinstance(app, CompiledWorkflow)

        raw_invoice = {
            "invoice_id": "INV-BPMN-TEST-001",
            "erp_source": "SAP_S4HANA",
            "vendor_name_raw": "Reliance Ind.",
            "buyer_id": "CORP-INFOSYS",
            "invoice_amount": 250_000.0,
            "currency": "USD",
            "issue_date": "2026-10-01",
            "due_date": "2026-11-30",
            "payment_terms_raw": "2/10 Net 60",
        }
        initial_state = create_initial_state(raw_invoice)
        final_state = app.invoke(initial_state)

        # 1. Verification of output state dossier
        assert final_state["status"] == WorkflowStatus.DISPATCHED
        assert final_state["cash_forecast"] is not None
        assert final_state["risk_profile"] is not None
        assert final_state["optimal_structure"] is not None
        assert final_state["guardrail_verdict"] is not None
        assert final_state["final_payload"] is not None

        # 2. Verification of Process Intelligence Heatmap
        heatmap = app.get_heatmap()
        assert heatmap is not None
        assert heatmap.workflow_id == "autonomous_scf_pipeline"
        assert heatmap.total_runs >= 1
        assert "cash_forecaster" in heatmap.node_metrics
        assert "treasury_dispatcher" in heatmap.node_metrics

