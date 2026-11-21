import { AlertTriangle, ChevronDown, FileSearch, FileText, UserRound } from "lucide-react";
import type { ClaimFinding } from "./dischargeApi";
import { dischargeRoles } from "./dischargeApi";
import type { Source } from "./api";

const labels: Record<string, string> = {
  aia_admission_mismatch: "AIA admission number differs", aia_amount_mismatch: "AIA expense differs from bill",
  aia_missing_consent: "Check the patient consent mark", aia_missing_certification: "Check the physician certification",
  aia_signature_review: "Verify the original signature areas", cms_member_mismatch: "CMS member ID differs",
  cms_disposition_mismatch: "Discharge destinations differ", cms_original_claim_reference: "Original claim reference needed",
  cms_total_mismatch: "CMS charges differ from the account", fep_total_mismatch: "FEP expense differs from the invoice",
  fep_assignment_signature: "Provider assignment needs a signature", fep_assignment_provider: "Assignment names another facility",
  fep_payee_review: "Check the payment election", cms_member_review: "Check the member ID on the form",
  duplicate_line: "Repeated invoice item", missing_records: "Missing supporting records",
  orphan_credit: "Credit without a matching charge", over_cap: "Charges exceed the written cap",
  total_mismatch: "Invoice total differs from its lines", share_mismatch: "Patient share differs",
  member_mismatch: "Member details differ", encounter_mismatch: "Encounter details differ",
  unapproved_procedure: "Procedure differs from authorization", stay_extension: "Stay exceeds authorized dates",
  late_reply: "Late payer response", mixed_currency: "Mixed currencies", verify_ocr: "Verify scanned pages",
  unrecognized_layout: "Unrecognized document layout", missing_or_ambiguous_field: "Missing or ambiguous field",
  missing_support: "Missing service evidence",
};
function title(code: string) {
  return labels[code] || (code.charAt(0).toUpperCase() + code.slice(1)).replaceAll("_", " ");
}
export function ClaimFindings({ findings, sources, pick }:
  { findings: ClaimFinding[]; sources: Source[]; pick: (s: Source, trigger: HTMLButtonElement) => void }) {
  const layout = findings.find(f => f.code === "unrecognized_layout");
  const unreadable = findings.find(f => f.code.startsWith("unreadable_"));
  const manual = layout || unreadable;
  const cite = manual?.sources.find(c => sources.some(s => c.role === s.role));
  const original = cite && sources.find(s => s.role === cite.role);
  return <div className="finding-stack">
    {manual && <div className="manual-action"><h3><FileSearch size={17} />Review the original form</h3>
      <p>{layout
        ? "This layout needs manual review. Compare the encounter and amounts, then check any signatures the payer requires. Uploading the same layout leaves this hold open."
        : "Check the original against the encounter and amounts. Request a legible copy or use the scan verification workflow when the text is unclear."}</p>
      {cite && original && <button className="text-action" onClick={event => pick({ ...original, page: cite.page, quote: cite.quote }, event.currentTarget)}>Inspect original · p. {cite.page}</button>}
    </div>}
    {findings.map((finding, i) =>
    <details className="finding-item" key={finding.code + i} open={i === 0}>
      <summary>
        <span className="finding-glyph"><AlertTriangle size={17} /></span>
        <span><small>{finding.severity === "blocker" ? "Blocking issue" : "Needs review"}</small>
          <strong>{title(finding.code)}</strong></span>
        <ChevronDown className="disclosure-chevron" size={16} />
      </summary>
      <div className="finding-content"><p>{finding.message}</p>
        <span className="finding-owner"><UserRound size={13} />{finding.owner || "Hospital coordinator"}</span>
        {finding.sources.length > 0 && <div className="evidence-cites">
          {finding.sources.map((cite, n) => {
            const file = sources.find(s => s.role === cite.role);
            if (!file) return null;
            const label = dischargeRoles[cite.role as keyof typeof dischargeRoles] || file.label;
            return <button type="button" key={n} onClick={event => pick({ ...file, page: cite.page, quote: cite.quote }, event.currentTarget)}
              title={cite.quote || file.label} aria-label={`Inspect ${label}, page ${cite.page}. ${cite.quote || ""}`}>
              <FileText size={13} />{label} · p. {cite.page}</button>;
          })}
        </div>}
      </div>
    </details>)}</div>;
}
