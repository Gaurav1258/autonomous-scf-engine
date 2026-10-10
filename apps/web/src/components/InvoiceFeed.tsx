"use client";

import React, { useState } from "react";
import { formatCurrency, formatDate } from "@/lib/formatters";
import { InvoiceListItem, WorkflowStatus } from "@/types";

interface InvoiceFeedProps {
  invoices: InvoiceListItem[];
  selectedInvoiceId: string | null;
  onSelectInvoice: (invoiceId: string) => void;
  onTriggerSimulation: (
    scenario: "clean_discounting" | "sanctioned_entity" | "limit_overdraw" | "reverse_factoring"
  ) => Promise<void>;
  isSimulating: boolean;
}

export function InvoiceFeed({
  invoices,
  selectedInvoiceId,
  onSelectInvoice,
  onTriggerSimulation,
  isSimulating,
}: InvoiceFeedProps) {
  const [activeScenario, setActiveScenario] = useState<string | null>(null);

  const handleSimulate = async (
    scenario: "clean_discounting" | "sanctioned_entity" | "limit_overdraw" | "reverse_factoring"
  ) => {
    setActiveScenario(scenario);
    try {
      await onTriggerSimulation(scenario);
    } finally {
      setActiveScenario(null);
    }
  };

  const getStatusBadge = (status: WorkflowStatus) => {
    switch (status) {
      case "DISPATCHED":
        return (
          <span className="inline-flex items-center rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] font-semibold text-emerald-400 border border-emerald-500/30">
            DISPATCHED
          </span>
        );
      case "EXECUTED_SETTLED":
        return (
          <span className="inline-flex items-center rounded-full bg-cyan-500/10 px-2 py-0.5 text-[11px] font-semibold text-cyan-400 border border-cyan-500/30">
            SETTLED
          </span>
        );
      case "REJECTED_SANCTIONS":
        return (
          <span className="inline-flex items-center rounded-full bg-rose-500/10 px-2 py-0.5 text-[11px] font-semibold text-rose-400 border border-rose-500/30">
            OFAC HALT
          </span>
        );
      case "REJECTED_GUARDRAIL":
        return (
          <span className="inline-flex items-center rounded-full bg-amber-500/10 px-2 py-0.5 text-[11px] font-semibold text-amber-400 border border-amber-500/30">
            LIMIT BREACH
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center rounded-full bg-slate-500/10 px-2 py-0.5 text-[11px] font-semibold text-slate-400 border border-slate-700">
            {status}
          </span>
        );
    }
  };

  return (
    <div className="flex flex-col rounded-xl border border-slate-800/80 bg-[#0d1322] shadow-lg">
      {/* Card Header & Simulation Controls */}
      <div className="border-b border-slate-800/80 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-bold text-white flex items-center gap-2">
              <span>ERP Payables Ledger</span>
              <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[11px] font-mono text-slate-400">
                {invoices.length} active
              </span>
            </h2>
            <p className="text-xs text-slate-400">
              Approved ERP receivables queued for autonomous working capital structuring
            </p>
          </div>

          {/* Trigger Simulations */}
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[11px] font-medium text-slate-400">Simulate:</span>
            <button
              onClick={() => handleSimulate("clean_discounting")}
              disabled={isSimulating}
              className="rounded-lg border border-emerald-500/30 bg-emerald-950/40 px-2.5 py-1 text-xs font-medium text-emerald-300 transition-all hover:bg-emerald-900/50 hover:border-emerald-500/60 disabled:opacity-50"
            >
              {activeScenario === "clean_discounting" ? "Running..." : "⚡ Clean ($350K)"}
            </button>
            <button
              onClick={() => handleSimulate("sanctioned_entity")}
              disabled={isSimulating}
              className="rounded-lg border border-rose-500/30 bg-rose-950/40 px-2.5 py-1 text-xs font-medium text-rose-300 transition-all hover:bg-rose-900/50 hover:border-rose-500/60 disabled:opacity-50"
            >
              {activeScenario === "sanctioned_entity" ? "Running..." : "🛑 Sanctions Hit"}
            </button>
            <button
              onClick={() => handleSimulate("limit_overdraw")}
              disabled={isSimulating}
              className="rounded-lg border border-amber-500/30 bg-amber-950/40 px-2.5 py-1 text-xs font-medium text-amber-300 transition-all hover:bg-amber-900/50 hover:border-amber-500/60 disabled:opacity-50"
            >
              {activeScenario === "limit_overdraw" ? "Running..." : "⚠️ Cap Breach ($500M)"}
            </button>
            <button
              onClick={() => handleSimulate("reverse_factoring")}
              disabled={isSimulating}
              className="rounded-lg border border-sky-500/30 bg-sky-950/40 px-2.5 py-1 text-xs font-medium text-sky-300 transition-all hover:bg-sky-900/50 hover:border-sky-500/60 disabled:opacity-50"
            >
              {activeScenario === "reverse_factoring" ? "Running..." : "🏦 Factoring ($12.5M)"}
            </button>
          </div>
        </div>
      </div>

      {/* Payables Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="border-b border-slate-800 bg-[#090e1a] text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            <tr>
              <th className="py-2.5 pl-4 pr-3">Invoice ID</th>
              <th className="py-2.5 px-3">Supplier Counterparty</th>
              <th className="py-2.5 px-3 text-right">Payable Amount</th>
              <th className="py-2.5 px-3">Instrument</th>
              <th className="py-2.5 px-3">Status</th>
              <th className="py-2.5 pr-4 pl-3 text-right">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 font-mono">
            {invoices.length === 0 ? (
              <tr>
                <td colSpan={6} className="py-8 text-center text-xs text-slate-500 font-sans">
                  No invoices processed yet. Click any simulation button above to trigger an autonomous workflow!
                </td>
              </tr>
            ) : (
              invoices.map((inv) => {
                const isSelected = selectedInvoiceId === inv.invoice_id;
                return (
                  <tr
                    key={inv.invoice_id}
                    onClick={() => onSelectInvoice(inv.invoice_id)}
                    className={`cursor-pointer transition-colors ${
                      isSelected
                        ? "bg-sky-950/30 border-l-2 border-sky-500"
                        : "hover:bg-slate-800/30"
                    }`}
                  >
                    <td className="py-3 pl-4 pr-3 font-semibold text-white">
                      {inv.invoice_id}
                    </td>
                    <td className="py-3 px-3 font-sans text-slate-200">
                      {inv.summary.vendor || "Pending Resolution"}
                    </td>
                    <td className="py-3 px-3 text-right font-semibold text-white">
                      {formatCurrency(inv.summary.amount)}
                    </td>
                    <td className="py-3 px-3 text-slate-400 text-[11px]">
                      {inv.summary.instrument ? (
                        <span className="font-sans font-medium text-sky-400">
                          {inv.summary.instrument === "DYNAMIC_DISCOUNTING"
                            ? "Dynamic Discounting"
                            : "Reverse Factoring"}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="py-3 px-3">{getStatusBadge(inv.status)}</td>
                    <td className="py-3 pr-4 pl-3 text-right font-sans">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelectInvoice(inv.invoice_id);
                        }}
                        className={`rounded px-2 py-0.5 text-[11px] font-medium transition-colors ${
                          isSelected
                            ? "bg-sky-500 text-white"
                            : "bg-slate-800 text-slate-300 hover:bg-slate-700"
                        }`}
                      >
                        {isSelected ? "Inspecting" : "Inspect"}
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

