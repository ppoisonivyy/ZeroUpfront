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
};
export type Source = {
  role: string;
  label: string;
  url: string;
  page: number;
  quote: string;
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
};

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
export const casePath = (id: string) => "/api/cases/" + encodeURIComponent(id);
export function sameOriginSource(path: string) {
  const url = new URL(path, window.location.origin);
  if (
    url.origin !== window.location.origin ||
    !["http:", "https:"].includes(url.protocol)
  ) {
    throw new Error("This document has an unsupported address.");
  }
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
    response = await fetch(path, { cache: "no-store", ...options });
  } catch (err) {
    if (options?.signal?.aborted) throw err;
    throw new Error(
      "The case service could not be reached. Check the connection and try again.",
    );
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail =
      typeof payload?.detail === "string"
        ? payload.detail
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
