"use client";

import React, { useEffect, useState } from "react";
import { AgentTelemetry } from "@/components/AgentTelemetry";
import { CashFlowChart } from "@/components/CashFlowChart";
import { InvoiceFeed } from "@/components/InvoiceFeed";
import { OneClickCard } from "@/components/OneClickCard";
import { scfApi } from "@/lib/api-client";
import { InvoiceListItem, SCFGraphState } from "@/types";

export default function TreasuryCockpitPage() {
  const [invoices, setInvoices] = useState<InvoiceListItem[]>([]);
  const [selectedInvoiceId, setSelectedInvoiceId] = useState<string | null>(null);
  const [selectedInvoiceState, setSelectedInvoiceState] = useState<SCFGraphState | null>(null);
  const [isSimulating, setIsSimulating] = useState(false);

  // Load invoices on mount
  const refreshInvoices = async () => {
    try {
      const data = await scfApi.listInvoices(20);
      setInvoices(data);
      // Auto-select first invoice if none selected
      if (!selectedInvoiceId && data.length > 0) {
        setSelectedInvoiceId(data[0].invoice_id);
      }
    } catch (err) {
      console.error("Failed to load invoices:", err);
    }
  };

  useEffect(() => {
    refreshInvoices();
  }, []);

  // Fetch full state when an invoice is selected
  useEffect(() => {
    if (!selectedInvoiceId) {
      setSelectedInvoiceState(null);
      return;
    }

    scfApi
      .getInvoice(selectedInvoiceId)
      .then((res) => {
        setSelectedInvoiceState(res.state);
      })
      .catch((err) => {
        console.error("Failed to fetch invoice details:", err);
      });
  }, [selectedInvoiceId]);

  // Handle Simulation Trigger
  const handleTriggerSimulation = async (
    scenario: "clean_discounting" | "sanctioned_entity" | "limit_overdraw" | "reverse_factoring"
  ) => {
    setIsSimulating(true);
    try {
      const res = await scfApi.simulateScenario(scenario);
      await refreshInvoices();
      setSelectedInvoiceId(res.invoice_id);
      setSelectedInvoiceState(res.data);
    } catch (err) {
      console.error("Simulation failed:", err);
    } finally {
      setIsSimulating(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Telemetry KPI Bar */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-xl border border-slate-800/80 bg-[#0d1322] p-4 shadow-md">
          <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
            Revolving Credit Headroom
          </div>
          <div className="mt-1 font-mono text-xl font-black text-emerald-400">
            $105.0M
          </div>
          <div className="mt-1 text-[11px] text-slate-500">
            Facility: $150.0M Limit | 30.0% Drawn
          </div>
        </div>

        <div className="rounded-xl border border-slate-800/80 bg-[#0d1322] p-4 shadow-md">
          <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
            Corporate Cash Floor
          </div>
          <div className="mt-1 font-mono text-xl font-black text-white">
            $10.0M
          </div>
          <div className="mt-1 text-[11px] text-emerald-400">
            Surplus buffer: +$55.0M healthy
          </div>
        </div>

        <div className="rounded-xl border border-slate-800/80 bg-[#0d1322] p-4 shadow-md">
          <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
            Avg Early Payment APR
          </div>
          <div className="mt-1 font-mono text-xl font-black text-sky-400">
            12.8%
          </div>
          <div className="mt-1 text-[11px] text-slate-500">
            Microeconomic XGBoost ML optimal pricing
          </div>
        </div>

        <div className="rounded-xl border border-slate-800/80 bg-[#0d1322] p-4 shadow-md">
          <div className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
            Origination Velocity
          </div>
          <div className="mt-1 font-mono text-xl font-black text-amber-400">
            &lt; 5s
          </div>
          <div className="mt-1 text-[11px] text-slate-500">
            vs 5–7 business days legacy banking
          </div>
        </div>
      </div>

      {/* Main 2-Column Workstation Grid */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Left Column: ERP Payables Feed & Cash Forecaster */}
        <div className="space-y-6 lg:col-span-7">
          <InvoiceFeed
            invoices={invoices}
            selectedInvoiceId={selectedInvoiceId}
            onSelectInvoice={(id) => setSelectedInvoiceId(id)}
            onTriggerSimulation={handleTriggerSimulation}
            isSimulating={isSimulating}
          />

          <CashFlowChart buyerId="CORP-INFOSYS" />
        </div>

        {/* Right Column: Live Multi-Agent Telemetry & 1-Click Term Sheet */}
        <div className="space-y-6 lg:col-span-5">
          <AgentTelemetry
            invoiceId={selectedInvoiceId}
            onWorkflowComplete={refreshInvoices}
          />

          <OneClickCard
            state={selectedInvoiceState}
            onActionComplete={refreshInvoices}
          />
        </div>
      </div>
    </div>
  );
}

