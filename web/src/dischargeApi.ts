import type { Source, WorkflowEvent } from "./api";
import { hospitalPrefix } from "./api";

export const dischargeRoles = {
  bill: "Final itemized bill",
  summary: "Discharge summary",
  letter: "Written payer letter",
  records: "Supporting records",
};
export type DischargeRole = keyof typeof dischargeRoles;
export type ClaimAction = "submission" | "reply" | "payment";
export type ClaimFinding = {
  code: string;
  severity: string;
  message: string;
  owner: string;
  sources: { role: string; page: number; quote: string; method?: string }[];
};
export type DischargeClaim = {
  ai_review_enabled?: boolean;
  staff_practice_hospital?: string | null;
  example_scenario?: string | null;
  id: string;
  revision: number;
  status: string;
  member: string;
  encounter: string;
  procedure: string;
  insurer?: string;
  facility?: string;
  sample_bill_available?: boolean;
  ocr_review_available?: boolean;
  ocr_page_count?: number;
  ocr_attestation?: {
    reviewer?: string;
    actor?: string;
    pages?: unknown[];
  } | null;
  settlement_status: string;
  case_paid_by_currency?: Record<string, number>;
  paid_by_currency: Record<string, number>;
  payer_decision: {
    outcome: string;
    amount_minor?: number;
    currency?: string;
  } | null;
  admission_date: string;
  discharge_date: string;
  prior_case_id?: string | null;
  currency: string | null;
  bill_total_minor: number | null;
  source_reported_cap_minor: number | null;
  source_reported_patient_share_minor: number | null;
  payable_minor: number | null;
  sources: Source[];
  findings: ClaimFinding[];
  checks?: Omit<ClaimFinding, "severity" | "owner">[];
  history: { revision: number; status: string }[];
  reviewer: string | null;
  insurer_status: string;
  workflow_version: number;
  allowed_actions: ClaimAction[];
  events: (Omit<WorkflowEvent, "kind"> & { kind: string })[];
};
export type DischargeQueue = "all" | "needs" | "ready" | "payer";
export const pattayaSteps = {
  book: "Insurer treasury · Choose funding",
  record_short: "Hospital finance · Verify bank credit",
  top_up: "Insurer treasury · Record top-up remittance",
  confirm_topup: "Hospital finance · Verify top-up credit",
  complete: "Hospital paid in full",
  review: "Hospital finance · Review settlement evidence",
};
export type PattayaSettlementSummary = {
  next_action: keyof typeof pattayaSteps;
  status: "unpaid" | "partially_paid" | "paid" | "reconciliation_required";
  outstanding_minor: number | null;
};
export type DischargeWorklist = {
  items: (Pick<DischargeClaim, "id" | "encounter" | "member" | "procedure" | "insurer" |
    "discharge_date" | "insurer_status" | "bill_total_minor" | "currency" | "status"> & {
    pattaya_settlement?: PattayaSettlementSummary | null;
  })[];
  counts: Record<DischargeQueue, number>;
  total: number;
  page: number;
  page_size: number;
};
export const claimPath = (id: string) =>
  hospitalPrefix + "/api/discharge/" + encodeURIComponent(id);
export const claimHref = (id: string, revision?: number) =>
  "#/discharge/" +
  encodeURIComponent(id) +
  (revision ? "?revision=" + revision : "");
export const claimStatus = (status: string) =>
  ({
    needs_review: "Needs investigation",
    ready_for_review: "Ready for staff review",
    ready_for_staff_review: "Ready for staff review",
    staff_reviewed: "Staff reviewed",
  })[status] || status.replaceAll("_", " ");
export const claimPayerStatus = (status: string) =>
  ({
    not_sent: "Awaiting submission",
    submitted: "Sent to insurer",
    query: "Insurer query",
    partial: "Partially confirmed",
    confirmed: "Confirmed by insurer",
    declined: "Declined by insurer",
    paid: "Payment recorded",
  })[status] || status.replaceAll("_", " ");
export function minorMoney(
  amount: number | null | undefined,
  currency?: string | null,
) {
  if (amount == null || !currency) return "Unverified";
  try {
    const format = new Intl.NumberFormat("en-GB", {
      style: "currency",
      currency,
      currencyDisplay: "code",
    });
    const decimals = format.resolvedOptions().maximumFractionDigits ?? 2;
    return format.format(amount / 10 ** decimals);
  } catch {
    return "Unverified";
  }
}
