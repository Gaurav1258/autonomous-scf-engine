/**
 * apps/web/src/lib/api-client.ts
 * ==============================
 * Typed HTTP & SSE client connecting to the deployed Google Cloud Run API
 * or local FastAPI gateway.
 */

import {
  CashCurveResponse,
  InvoiceListItem,
  RawInvoice,
  SCFGraphState,
} from "@/types";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "https://scf-api-8938740754.us-central1.run.app";

async function fetchJson<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;
  const res = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers || {}),
    },
  });

  if (!res.ok) {
    const errorBody = await res.text();
    throw new Error(`API Error [${res.status}] ${endpoint}: ${errorBody}`);
  }

  return res.json() as Promise<T>;
}

export const scfApi = {
  // 1. Health Probe
  async getHealth() {
    return fetchJson<{
      status: string;
      environment: string;
      subsystems: Record<string, string>;
    }>("/health");
  },

  // 2. Invoice Ledger
  async listInvoices(limit: number = 50): Promise<InvoiceListItem[]> {
    return fetchJson<InvoiceListItem[]>(`/api/invoices?limit=${limit}`);
  },

  async getInvoice(invoiceId: string): Promise<{
    invoice_id: string;
    status: string;
    decision?: string;
    state: SCFGraphState;
  }> {
    return fetchJson(`/api/invoices/${encodeURIComponent(invoiceId)}`);
  },

  async processInvoice(payload: RawInvoice): Promise<{
    status: string;
    invoice_id: string;
    workflow_status: string;
    data: SCFGraphState;
  }> {
    return fetchJson("/api/invoices/process", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  async simulateScenario(
    scenario: "clean_discounting" | "sanctioned_entity" | "limit_overdraw" | "reverse_factoring"
  ): Promise<{
    scenario: string;
    invoice_id: string;
    workflow_status: string;
    data: SCFGraphState;
  }> {
    return fetchJson(`/api/invoices/simulate?scenario=${scenario}`, {
      method: "POST",
    });
  },

  // 3. Cash Forecasting
  async getCashCurve(
    buyerId: string = "CORP-INFOSYS",
    days: number = 60,
    simulateAdvance: number = 0
  ): Promise<CashCurveResponse> {
    const params = new URLSearchParams({
      buyer_id: buyerId,
      days: days.toString(),
      simulate_advance_amount: simulateAdvance.toString(),
    });
    return fetchJson<CashCurveResponse>(`/api/forecast/cash-curve?${params.toString()}`);
  },

  // 4. One-Click Dual Approvals
  async getOffer(offerId: string) {
    return fetchJson<{
      offer_id: string;
      invoice_id: string;
      workflow_status: string;
      decision?: string;
      terms: any;
      final_payload: any;
      guardrail_verdict: any;
    }>(`/api/offers/${encodeURIComponent(offerId)}`);
  },

  async executeOfferAction(
    offerId: string,
    action: {
      decision: "APPROVED" | "REJECTED";
      approver_role?: "TREASURER" | "SUPPLIER";
      approval_token?: string;
      notes?: string;
    }
  ) {
    return fetchJson<{
      status: string;
      offer_id: string;
      execution_status: string;
      settlement_reference?: string;
      message: string;
    }>(`/api/offers/${encodeURIComponent(offerId)}/action`, {
      method: "POST",
      body: JSON.stringify(action),
    });
  },

  // 5. Server-Sent Events (SSE) Stream URL Builder
  getStreamUrl(invoiceId: string, scenario?: string, amount?: number): string {
    const params = new URLSearchParams();
    if (scenario) params.set("scenario", scenario);
    if (amount) params.set("amount", amount.toString());
    return `${API_BASE_URL}/api/stream/invoice/${encodeURIComponent(invoiceId)}?${params.toString()}`;
  },
};

