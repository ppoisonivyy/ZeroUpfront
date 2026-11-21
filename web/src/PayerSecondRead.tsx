import { useState, type FormEvent } from "react";
import { FileSearch } from "lucide-react";
import { api, type Source } from "./api";
import { claimPath, dischargeRoles, type DischargeClaim, type DischargeRole } from "./dischargeApi";

type Family = "aia" | "cms" | "fep";
type Result = {
  revision: number;
  family: Family;
  model: string;
  checks: {
    field: string;
    state: string;
    observation: string;
    pages: { role: DischargeRole; page: number }[];
  }[];
};
const formNames: Record<Family, string> = {
  aia: "AIA Thailand inpatient claim",
  cms: "CMS-1450 institutional claim",
  fep: "FEP overseas medical claim",
};
const fieldNames: Record<string, string> = {
  admission: "Admission number", member: "Member ID", disposition: "Discharge destination",
  expense: "Claimed expense", consent: "Patient consent", certification: "Physician certification",
  letter: "Separate payer letter", replacement: "Original claim reference", payee: "Payment recipient",
};

const stateLabels: Record<string, string> = {
  match: "Values agree", conflict: "Discrepancy", present: "Entry present", absent: "Entry absent",
  unknown: "Needs verification", visual_review: "Inspect original mark", unsigned: "Assignment mark missing",
  hospital: "Hospital named", member: "Member reimbursement", other_provider: "Another provider named",
  original: "Original claim",
};

export function PayerSecondRead({ claim, pick }: { claim: DischargeClaim; pick: (s: Source) => void }) {
  const [family, setFamily] = useState<Family | "">("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Result | null>(null);

  async function run(e: FormEvent) {
    e.preventDefault();
    if (!confirmed || !family || busy) return;
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const response = await api(claimPath(claim.id) + "/second-read", {
        method: "POST",
        headers: { "Content-Type": "application/json", "If-Match": '"' + claim.revision + '"' },
        body: JSON.stringify({ family, confirmed: true }),
      });
      const draft: Result = await response.json();
      if (draft.revision !== claim.revision || draft.family !== family)
        throw new Error("The response does not match the selected form and revision. Reopen the case.");
      setResult(draft);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "The document review could not be completed.");
    } finally { setBusy(false); }
  }

  return <details className="ai-review">
    <summary><FileSearch size={16} />Request an AI second read</summary>
    <form onSubmit={run}>
      <p>Get draft observations on this form and the hospital exhibits. Open the cited pages to verify each observation.</p>
      <fieldset className="plain-fields" disabled={busy}>
        <label className="stack-field"><span>Payer form</span>
          <select required value={family} onChange={e => { setFamily(e.target.value as Family | ""); setResult(null); setConfirmed(false); }}>
            <option value="">Choose the form in this packet</option>
            {Object.entries(formNames).map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select>
        </label>
        <label className="check-field"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} required />
          Send the original PDFs and encounter details for R{claim.revision} to OpenAI for this read.
        </label>
        <button type="submit" className="secondary" disabled={!family || !confirmed || busy}>
          {busy ? "Reading original documents…" : "Read this revision"}
        </button>
      </fieldset>
    </form>
    {error && <p role="alert" className="error-message">{error}</p>}
    {result && <section aria-label="Draft AI observations" className="payer-fields" aria-live="polite">
      <h3>Draft observations · R{result.revision}</h3>
      <p className="hint">For staff verification. Saved claim findings and sign-off use the reviewed evidence.</p>
      {result.checks.map(check => <div key={check.field}>
        <h4>{fieldNames[check.field] || check.field} · {stateLabels[check.state] || check.state}</h4><p>{check.observation}</p>
        <div className="evidence-cites">{check.pages.map(cite => {
          const file = claim.sources.find(s => s.role === cite.role);
          return file && <button type="button" key={cite.role + cite.page}
            onClick={() => pick({ ...file, page: cite.page, quote: "" })}>
            {dischargeRoles[cite.role]} · p. {cite.page}
          </button>;
        })}</div>
      </div>)}
    </section>}
  </details>;
}
