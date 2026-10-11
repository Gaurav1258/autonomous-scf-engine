"use client";

import React, { useState } from "react";
import { formatCurrency, formatExpiryCountdown, formatPercent } from "@/lib/formatters";
import { scfApi } from "@/lib/api-client";
import { SCFGraphState } from "@/types";

interface OneClickCardProps {
  state: SCFGraphState | null;
  onActionComplete?: () => void;
}

export function OneClickCard({ state, onActionComplete }: OneClickCardProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [settlementRef, setSettlementRef] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  if (!state) {
    return (
      <div className="flex h-full min-h-[320px] items-center justify-center rounded-xl border border-dashed border-slate-800 bg-[#0d1322] p-8 text-center text-xs text-slate-500">
        Select an invoice from the ledger or run a simulation to inspect structured terms.
      </div>
    );
  }

  const { optimal_structure, final_payload, guardrail_verdict, risk_profile, raw_invoice, status } = state;

  const handleAction = async (decision: "APPROVED" | "REJECTED", role: "TREASURER" | "SUPPLIER") => {
    if (!final_payload?.offer_id) return;
    setIsSubmitting(true);
    setActionMessage(null);
    try {
      const res = await scfApi.executeOfferAction(final_payload.offer_id, {
        decision,
        approver_role: role,
        approval_token: final_payload.approval_token,
      });

      if (res.settlement_reference) {
        setSettlementRef(res.settlement_reference);
      }
      setActionMessage(res.message);
      if (onActionComplete) onActionComplete();
    } catch (err: any) {
      setActionMessage(err.message || "Failed to execute offer action.");
    } finally {
      setIsSubmitting(false);
    }
  };

  // 1. Compliance / Credit Limit Halt Display
  if (status === "REJECTED_SANCTIONS" || status === "REJECTED_GUARDRAIL") {
    const isSanctions = status === "REJECTED_SANCTIONS";
    return (
      <div className="flex flex-col justify-between rounded-xl border border-rose-500/40 bg-[#120a14] p-5 shadow-lg">
        <div>
          <div className="flex items-center gap-2">
            <span className="flex h-2.5 w-2.5 rounded-full bg-rose-500"></span>
            <h3 className="text-sm font-bold text-rose-300">
              {isSanctions ? "Compliance Freeze: OFAC Watchlist Match" : "Risk Gate: Credit Facility Overdraw"}
            </h3>
          </div>
          <p className="mt-2 text-xs text-rose-200/80 leading-relaxed">
            {isSanctions
              ? `Counterparty '${risk_profile?.vendor_canonical_name || raw_invoice.vendor_name_raw}' matched an active sanctions list. Automated term structuring aborted pursuant to AML compliance policy.`
              : guardrail_verdict?.rejection_reason || "Requested financing exceeds allowable single-supplier concentration or facility limit."}
          </p>

          <div className="mt-4 rounded-lg bg-rose-950/40 border border-rose-800/40 p-3 font-mono text-[11px] text-rose-300">
            <div>• Invoice ID: {raw_invoice.invoice_id}</div>
            <div>• Requested Amount: {formatCurrency(raw_invoice.invoice_amount)}</div>
            <div>• Status: {status}</div>
          </div>
        </div>

        <div className="mt-6 border-t border-rose-900/40 pt-3 text-[11px] text-rose-400">
          Deterministic Guardrails: Execution blocked. Zero credit exposure drawn.
        </div>
      </div>
    );
  }

  // 2. Offer Dispatched / Active Display
  return (
    <div className="flex flex-col rounded-xl border border-slate-800/80 bg-[#0d1322] shadow-lg">
      {/* Header */}
      <div className="border-b border-slate-800/80 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="flex items-center gap-2">
              <span className="flex h-2.5 w-2.5 rounded-full bg-emerald-400"></span>
              <h3 className="text-sm font-bold text-white">
                1-Click Term Sheet Cockpit
              </h3>
              {final_payload?.offer_id && (
                <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[11px] text-sky-400">
                  {final_payload.offer_id}
                </span>
              )}
            </div>
            <p className="text-xs text-slate-400">
              FASB ASC 310 ACT/360 deterministic working capital terms
            </p>
          </div>

          {/* Expiry Pill */}
          {(final_payload?.expires_at_timestamp || final_payload?.expiry_timestamp_utc) && (
            <span className="rounded-full border border-amber-500/30 bg-amber-950/40 px-2.5 py-0.5 text-[11px] font-mono text-amber-300">
              ⏳ {formatExpiryCountdown(
                final_payload.expires_at_timestamp ||
                (final_payload.expiry_timestamp_utc ? new Date(final_payload.expiry_timestamp_utc).getTime() / 1000 : null)
              )}
            </span>
          )}
        </div>
      </div>

      {/* Financial Economics Grid */}
      <div className="p-4 space-y-4">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="rounded-lg border border-slate-800 bg-[#090e1a] p-3">
            <span className="text-[10px] uppercase tracking-wider text-slate-400">Net Supplier Advance</span>
            <div className="mt-1 text-base font-bold text-emerald-400 font-mono">
              {formatCurrency(optimal_structure?.net_advance_to_supplier_usd ?? final_payload?.net_payout_to_supplier_usd)}
            </div>
            <span className="text-[10px] text-slate-500">Gross: {formatCurrency(raw_invoice.invoice_amount)}</span>
          </div>

          <div className="rounded-lg border border-slate-800 bg-[#090e1a] p-3">
            <span className="text-[10px] uppercase tracking-wider text-slate-400">Offered APR</span>
            <div className="mt-1 text-base font-bold text-sky-400 font-mono">
              {formatPercent(optimal_structure?.implied_apr_pct ?? optimal_structure?.selected_annualized_rate_pct ?? final_payload?.annualized_apr_pct)}
            </div>
            <span className="text-[10px] text-slate-500">Accelerated: {optimal_structure?.days_accelerated ?? final_payload?.days_accelerated ?? 0} days</span>
          </div>

          <div className="rounded-lg border border-slate-800 bg-[#090e1a] p-3">
            <span className="text-[10px] uppercase tracking-wider text-slate-400">Discount Fee / Savings</span>
            <div className="mt-1 text-base font-bold text-amber-400 font-mono">
              {formatCurrency(
                optimal_structure?.buyer_benefit_usd ??
                optimal_structure?.discount_fee_amount_usd ??
                final_payload?.buyer_yield_or_rebate_usd ??
                (raw_invoice?.invoice_amount && optimal_structure?.net_advance_to_supplier_usd
                  ? raw_invoice.invoice_amount - optimal_structure.net_advance_to_supplier_usd
                  : 0)
              )}
            </div>
            <span className="text-[10px] text-slate-500">
              Buyer Yield: {formatCurrency(optimal_structure?.buyer_benefit_usd ?? optimal_structure?.buyer_rebate_yield_usd ?? final_payload?.buyer_yield_or_rebate_usd)}
            </span>
          </div>

          <div className="rounded-lg border border-slate-800 bg-[#090e1a] p-3">
            <span className="text-[10px] uppercase tracking-wider text-slate-400">Credit Concentration</span>
            <div className="mt-1 text-base font-bold text-slate-200 font-mono">
              {formatPercent(guardrail_verdict?.supplier_concentration_pct ?? guardrail_verdict?.single_supplier_concentration_pct)}
            </div>
            <span className="text-[10px] text-slate-500">Cap limit: {formatPercent(guardrail_verdict?.concentration_cap_pct ?? 15.0)}</span>
          </div>
        </div>

        {/* Cryptographic SHA256 Signature */}
        {guardrail_verdict?.verification_signature && (
          <div className="flex items-center justify-between rounded-lg border border-slate-800/80 bg-[#060a12] px-3 py-2 text-[11px] font-mono text-slate-400">
            <div className="flex items-center gap-2 truncate">
              <span className="text-slate-500">HMAC-SHA256:</span>
              <span className="truncate text-slate-300">
                {guardrail_verdict.verification_signature}
              </span>
            </div>
            <span className="ml-2 text-emerald-400 text-[10px] shrink-0">✓ VERIFIED</span>
          </div>
        )}

        {/* Settlement Reference Message */}
        {settlementRef && (
          <div className="rounded-lg border border-cyan-500/40 bg-cyan-950/20 p-3 text-xs text-cyan-200">
            <div className="font-semibold text-cyan-400">Core Banking Settlement Dispatched!</div>
            <div className="mt-1 font-mono text-[11px]">Reference: {settlementRef}</div>
          </div>
        )}

        {actionMessage && !settlementRef && (
          <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-2.5 text-xs text-slate-300">
            {actionMessage}
          </div>
        )}

        {/* 1-Click Action Buttons */}
        <div className="flex flex-wrap items-center gap-3 pt-2">
          <button
            onClick={() => handleAction("APPROVED", "TREASURER")}
            disabled={isSubmitting || !!settlementRef || !final_payload}
            className="flex-1 rounded-lg bg-emerald-600 px-4 py-2.5 text-xs font-semibold text-white shadow-md shadow-emerald-900/30 transition-all hover:bg-emerald-500 disabled:opacity-50"
          >
            {isSubmitting ? "Processing..." : "⚡ Authorize Credit Line Draw (Treasurer)"}
          </button>

          <button
            onClick={() => handleAction("APPROVED", "SUPPLIER")}
            disabled={isSubmitting || !!settlementRef || !final_payload}
            className="rounded-lg border border-sky-500/40 bg-sky-950/30 px-4 py-2.5 text-xs font-semibold text-sky-300 transition-all hover:bg-sky-900/40 hover:border-sky-500 disabled:opacity-50"
          >
            🤝 Accept Early Payment (Supplier)
          </button>

          <button
            onClick={() => handleAction("REJECTED", "TREASURER")}
            disabled={isSubmitting || !!settlementRef || !final_payload}
            className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2.5 text-xs font-semibold text-slate-400 transition-all hover:bg-slate-700 hover:text-white disabled:opacity-50"
          >
            ✕ Reject
          </button>
        </div>
      </div>
    </div>
  );
}

