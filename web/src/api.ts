export type PacketStatus =
  | "needs_itemization"
  | "possible_exclusion"
  | "needs_review"
  | "ready_for_review"
  | "staff_reviewed";
export type CaseSummary = {
  id: string;
  procedure: string;
  insurer: string;
  member: string;
  admission_date: string;
  total: number | null;
  status: PacketStatus;
  revision: number;
  insurer_status?: string;
  workflow_stage?: string;
  latest_event_kind?: string;
  open_hold_count?: number;
};
export type Source = {
  role: string;
  label: string;
  url: string;
  page: number;
  quote: string;
  recordedSummary?: string;
  anchors?: { page: number; quote: string; clause?: string; method?: string }[];
};
export type WorkflowAction =
  "submission" | "reply" | "supplement" | "admission" | "deposit";
export type WorkflowEvent = {
  id: number | string;
  kind: WorkflowAction;
  actor: string;
  created_at: string;
  data: Record<string, unknown>;
  source_url?: string | null;
  filename?: string | null;
};
export type Citation = { role: string; page: number; quote: string };
export type EvidenceCheck = {
  requirement: string;
  result: string;
  policy: Citation;
  support: Citation;
};
export type ManualEvidence = {
  fields: Record<string, Citation>;
  checks: EvidenceCheck[];
};
export type Charge = { label: string; amount: number };
export type CaseDetail = CaseSummary & {
  policy_edition: string;
  clause: string | null;
  reason: string;
  lines: Charge[];
  sources: Source[];
  history: { revision: number; status: PacketStatus; total: number | null }[];
  reviewer: string | null;
  insurer_status: string;
  workflow_version?: number;
  events?: WorkflowEvent[];
  allowed_actions?: (WorkflowAction | "hold" | "resolve_hold")[];
  intake?: boolean;
  input_kind?: string;
  issues?: string[];
  manual_review?: ManualEvidence | null;
  clarification_available?: boolean;
  sample_estimate_available?: boolean;
  open_holds?: {
    id: number;
    revision: number;
    category: string;
    note: string;
    actor: string;
  }[];
  admission_check?: {
    outcome: string;
    differences?: string[];
    uncertainties?: string[];
  } | null;
  deposit_decision?: {
    outcome: string;
    amount?: string;
    currency?: string;
  } | null;
};

export const caseHref = (id: string, revision?: number) =>
  "#/cases/" + encodeURIComponent(id) + (revision ? "?revision=" + revision : "");

export const statuses: Record<PacketStatus, string> = {
  needs_itemization: "Missing itemization",
  possible_exclusion: "Possible exclusion",
  needs_review: "Needs investigation",
  ready_for_review: "Ready for staff review",
  staff_reviewed: "Staff reviewed",
};
export const blocked = (status: PacketStatus) =>
  !["ready_for_review", "staff_reviewed"].includes(status);
const currency = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
export const money = (n: number | null) =>
  n === null ? "Unverified" : "THB " + currency.format(n);
export function displayDate(raw: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw || "Unrecorded";
  return new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeZone: "UTC",
  }).format(new Date(raw + "T00:00:00Z"));
}
export const hospitalPrefix = window.location.pathname.match(/^\/h\/[^/]+(?=\/|$)/)?.[0] || "";
export const casePath = (id: string) => hospitalPrefix + "/api/cases/" + encodeURIComponent(id);
export function sameOriginSource(path: string) {
  const url = new URL(path, window.location.origin);
  if (
    url.origin !== window.location.origin ||
    !["http:", "https:"].includes(url.protocol) || url.username || url.password
  ) {
    throw new Error("This document has an unsupported address.");
  }
  if (url.pathname.startsWith("/api/")) url.pathname = hospitalPrefix + url.pathname;
  if (!url.pathname.startsWith(hospitalPrefix + "/api/"))
    throw new Error("This address is outside the current hospital workspace.");
  return url.href;
}
export class RequestError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}
export async function api(path: string, options?: RequestInit) {
  let response: Response;
  try {
    response = await fetch(sameOriginSource(path), { cache: "no-store", ...options });
  } catch (err) {
    if (options?.signal?.aborted) throw err;
    throw new Error(
      "The case service could not be reached. Check the connection and try again.",
    );
  }
  if (!response.ok) {
    if (response.status === 401)
      window.dispatchEvent(new Event("staff-session-expired"));
    const payload = await response.json().catch(() => null);
    const detail =
      typeof payload?.detail === "string"
        ? payload.detail
        : Array.isArray(payload?.detail)
          ? payload.detail
              .map((issue: { loc?: string[]; msg?: string }) =>
                [issue.loc?.at(-1), issue.msg].filter(Boolean).join(" · "),
              )
              .join(". ")
          : "The case service could not complete this request.";
    const stale = response.status === 412;
    throw new RequestError(
      response.status,
      stale
        ? "Another coordinator changed this case. Reload the current revision before continuing."
        : detail,
    );
  }
  return response;
}
