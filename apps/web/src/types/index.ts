/**
 * apps/web/src/types/index.ts
 * ===========================
 * TypeScript domain contracts matching FastAPI & LangGraph Pydantic schemas.
 */

export type WorkflowStatus =
  | "PENDING"
  | "ANALYZING"
  | "STRUCTURING"
  | "APPROVED"
  | "DISPATCHED"
  | "REJECTED_SANCTIONS"
  | "REJECTED_GUARDRAIL"
  | "EXECUTED_SETTLED"
  | "CANCELLED_BY_TREASURER";

export type FinancingInstrument = "DYNAMIC_DISCOUNTING" | "REVERSE_FACTORING";

export interface RawInvoice {
  invoice_id: string;
  buyer_id: string;
  vendor_name_raw: string;
  invoice_amount: number;
  currency: string;
  due_date: string;
  issue_date?: string;
  payment_terms_raw: string;
  erp_source?: string;
  buyer_sector?: string;
}

export interface PaymentTerms {
  raw_term_string: string;
  discount_percentage: number;
  discount_days: number;
  net_days: number;
  is_discount_available: boolean;
}

export interface CashForecastTelemetry {
  buyer_id: string;
  current_cash_balance_usd: number;
  facility_limit_usd: number;
  facility_drawn_usd: number;
  undrawn_headroom_usd: number;
  min_projected_cash_60d_usd: number;
  min_cash_floor_usd: number;
  surplus_above_floor_usd: number;
  liquidity_status: "HEALTHY" | "TIGHT" | "DEFICIT";
  recommended_instrument: FinancingInstrument;
}

export interface SupplierRiskProfile {
  vendor_canonical_id: string;
  vendor_canonical_name: string;
  vendor_matched_alias: string;
  match_confidence_score: number;
  supplier_risk_tier: string;
  supplier_sector: string;
  sanctions_cleared: boolean;
  watchlist_matches: string[];
  is_duplicate: boolean;
  duplicate_reason?: string | null;
  summary_markdown: string;
}

export interface ElasticityCurvePoint {
  annualized_rate_pct: number;
  predicted_acceptance_prob: number;
  net_advance_to_supplier: number;
  discount_amount: number;
  buyer_yield_apr: number;
  is_recommended: boolean;
}

export interface FinancingStructure {
  instrument_type: FinancingInstrument;
  selected_annualized_rate_pct: number;
  predicted_acceptance_prob: number;
  baseline_gross_amount_usd: number;
  discount_fee_amount_usd: number;
  net_advance_to_supplier_usd: number;
  buyer_rebate_yield_usd: number;
  bank_interest_margin_usd: number;
  days_accelerated: number;
  tenor_total_days: number;
  cost_of_capital_delta_pct: number;
  pricing_rationale: string;
}

export interface GuardrailVerdict {
  is_approved: boolean;
  facility_headroom_usd: number;
  proposed_utilization_pct: number;
  single_supplier_concentration_pct: number;
  concentration_cap_usd: number;
  rejection_reason?: string | null;
  verification_signature: string;
}

export interface DispatchedPayload {
  offer_id: string;
  invoice_id: string;
  buyer_id: string;
  supplier_id: string;
  instrument_type: FinancingInstrument;
  offered_apr_pct: number;
  net_payout_amount: number;
  currency: string;
  accelerated_payment_date: string;
  original_due_date: string;
  expires_at_timestamp: number;
  approval_token: string;
  treasurer_action_url: string;
  supplier_action_url: string;
}

export interface SCFGraphState {
  raw_invoice: RawInvoice;
  cash_forecast?: CashForecastTelemetry | null;
  risk_profile?: SupplierRiskProfile | null;
  optimal_structure?: FinancingStructure | null;
  candidate_curve?: ElasticityCurvePoint[] | null;
  guardrail_verdict?: GuardrailVerdict | null;
  final_payload?: DispatchedPayload | null;
  status: WorkflowStatus;
  audit_trail: string[];
  errors: string[];
}

export interface InvoiceListItem {
  invoice_id: string;
  created_at: number;
  updated_at: number;
  status: WorkflowStatus;
  decision?: string | null;
  summary: {
    vendor?: string | null;
    amount?: number | null;
    instrument?: FinancingInstrument | null;
    apr?: number | null;
  };
}

export interface CashCurvePoint {
  day: number;
  date: string;
  projected_cash: number;
  simulated_cash: number;
  inflows: number;
  outflows: number;
  net_flow: number;
  min_floor: number;
  facility_headroom: number;
}

export interface CashCurveResponse {
  buyer_id: string;
  as_of_date: string;
  horizon_days: number;
  current_cash_balance: number;
  min_cash_floor: number;
  facility_limit: number;
  facility_drawn: number;
  undrawn_headroom: number;
  daily_curve: CashCurvePoint[];
}

export interface SSEAgentStepPayload {
  invoice_id: string;
  timestamp: number;
  node: string;
  status: WorkflowStatus;
  summary: string;
  delta: Partial<SCFGraphState>;
  audit_trail: string[];
}

