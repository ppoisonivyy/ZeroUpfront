import { useEffect, useRef, useState } from "react";
import { FileText } from "lucide-react";
import { api, type Source } from "./api";
import { claimPath, type DischargeClaim } from "./dischargeApi";

type Finding = {
  category: "exchange_difference" | "bank_fees";
  payer: "insurer" | "patient" | "hospital" | "other" | "unclear";
  page: number;
  quote: string;
  definition?: { name: string; page: number; quote: string };
};
type Assessment = { status: "cited" | "needs_review"; reason: string; findings: Finding[]; source_url: string };
const categories = { exchange_difference: "Exchange-rate differences", bank_fees: "Bank fees" };
const payers = { insurer: "Insurer", patient: "Patient", hospital: "Hospital", other: "Another party", unclear: "Needs review" };

function FeeReader({ path, revision, eventId, source, openLetter }: {
  path: string; revision: number; eventId: number; source: Source; openLetter: (source: Source, trigger: HTMLButtonElement) => void;
}) {
  const [result, setResult] = useState<Assessment>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);

  async function read() {
    if (request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true);
    setError("");
    try {
      const response = await api(path, {
        method: "POST", headers: { "Content-Type": "application/json", "If-Match": '"' + revision + '"' },
        body: JSON.stringify({ confirmed: true, event_id: eventId }), signal: controller.signal,
      });
      const assessment: Assessment = await response.json();
      if (!controller.signal.aborted) setResult(assessment);
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "The fee reader is unavailable.");
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy(false); }
    }
  }

  return <section className="guarantee-fees" aria-label="Guarantee fee terms">
    <h3>Who covers the FX costs?</h3>
    <button type="button" className="text-action" onClick={event => openLetter(source, event.currentTarget)}><FileText size={14} />Open original payer letter</button>
    <p>Reading the terms sends the original payer PDF to OpenAI to identify who covers exchange differences and bank fees in Thai or English.</p>
    <button type="button" className="secondary" disabled={busy || !!result} onClick={() => void read()}>{busy ? "Reading the payer letter…" : "Read fee terms with OpenAI"}</button>
    {error && <p role="alert" className="error-message">{error}</p>}
    {result && <div aria-live="polite" className="guarantee-fee-results">
      <strong>{result.status === "needs_review" ? "Terms need staff review" : "Check the cited terms"}</strong>
      {result.reason && <p>{result.reason}</p>}
      {result.findings.length > 0 && <dl>{result.findings.map(finding => <div key={finding.category}>
        <dt>{categories[finding.category]}</dt><dd>{payers[finding.payer]}</dd>
        {finding.page > 0 && finding.quote && <dd className="guarantee-fee-citation"><q lang={/[\u0E00-\u0E7F]/u.test(finding.quote) ? "th" : undefined}>{finding.quote}</q>{" "}
          <button type="button" className="text-action" onClick={event => openLetter({ ...source, page: finding.page, quote: finding.quote }, event.currentTarget)}>View page {finding.page}</button>
        </dd>}
        {finding.definition && <dd className="guarantee-fee-citation">Party definition: <q>{finding.definition.quote}</q>{" "}
          <button type="button" className="text-action" onClick={event => openLetter({ ...source, page: finding.definition!.page, quote: finding.definition!.quote }, event.currentTarget)}>View definition on page {finding.definition.page}</button>
        </dd>}
      </div>)}</dl>}
      <p>Confirm each responsibility against the signed letter before assigning a charge.</p>
    </div>}
  </section>;
}

export function GuaranteeFees({ claim, openLetter }: { claim: DischargeClaim; openLetter: (source: Source, trigger: HTMLButtonElement) => void }) {
  const reply = [...claim.events].reverse().find(event => event.kind === "reply");
  if (!reply?.source_url || (reply.data.outcome !== "confirmed" && reply.data.outcome !== "partial")) return null;
  const source = { role: "payer_decision", label: "Payer decision letter", url: reply.source_url, page: 1, quote: "" };
  return <FeeReader key={[claim.id, claim.revision, reply.id].join("/")} path={claimPath(claim.id) + "/guarantee-fees"}
    revision={claim.revision} eventId={Number(reply.id)} source={source} openLetter={openLetter} />;
}
