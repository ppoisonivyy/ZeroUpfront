import { useEffect, useState } from "react";
import { ArrowRight, FileText, Landmark } from "lucide-react";
import { api, displayDate, RequestError, sameOriginSource, type Source } from "./api";
import { claimPath, minorMoney, type DischargeClaim } from "./dischargeApi";
import "./pattaya.css";

type Instrument = "spot" | "forward";
type BookingAction = "book_spot" | "book_forward" | "record_short_credit" | "record_topup";
type FundingTerms = { instrument: Instrument; rate_thb_per_usd: string; usd_minor: number; trade_date: string; value_date: string };
type Review = {
  revision: number;
  workflow_version: number;
  hospital_due_date: string;
  guaranteed_minor: number;
  paid_minor: number;
  outstanding_minor: number;
  patient_fx_minor: number;
  short_credit_minor: number;
  shortfall_owner: "insurer" | null;
  booked_quote: FundingTerms | null;
  quotes: (FundingTerms & { quote_id: string })[];
  next_action: "book" | "record_short" | "top_up" | "complete" | "review";
  trace: { agent: string; status: string; summary: string; evidence: string }[];
  model_enabled: boolean;
  model_review: { status: "not_requested" | "reviewed" | "unavailable"; summary: string; tools: string[] };
};

const instrumentNames = { spot: "Spot", forward: "Forward" };
const stepNames: Record<Review["next_action"], string> = {
  book: "Choose bank funding", record_short: "Record the hospital credit", top_up: "Reconcile the short payment",
  complete: "Hospital paid in full", review: "Review the claim documents",
};
const packageUrl = "https://www.bangkokhospital.com/en/pattaya/package/lens-replacement-surgery-package-bph";

export function PattayaSettlement({ claim, onUpdated, reload, openSource }: {
  claim: DischargeClaim;
  onUpdated: (next: DischargeClaim) => void;
  reload: () => void;
  openSource: (source: Source) => void;
}) {
  const base = claimPath(claim.id) + "/pattaya";
  const [review, setReview] = useState<Review>();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error>();
  const [choice, setChoice] = useState<Instrument>("spot");
  const [consent, setConsent] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const guarantee = claim.events.find(event => event.kind === "reply" && event.data.outcome === "confirmed" && event.source_url);
  const guaranteeSource = guarantee?.source_url ? {
    role: "payer_decision", label: "Final insurer guarantee", url: guarantee.source_url, page: 1,
    quote: "", recordedSummary: typeof guarantee.data.terms === "string" ? guarantee.data.terms : undefined,
  } : null;
  const revision = claim.revision, workflowVersion = claim.workflow_version;
  const current = review?.revision === revision && review.workflow_version === workflowVersion ? review : undefined;
  const bookedQuote = current?.booked_quote;
  const selectedQuote = current?.quotes.find(quote => quote.instrument === choice);
  const receipts = claim.events.filter(event => event.kind === "payment");
  const preview = (kind: "instruction" | "initial_credit" | "topup_credit") =>
    sameOriginSource(base + "/bank-documents/" + kind + "?revision=" + revision);
  useEffect(() => {
    const controller = new AbortController();
    setError(undefined);
    api(base + "?revision=" + revision, { signal: controller.signal })
      .then(res => res.json())
      .then((next: Review) => {
        if (controller.signal.aborted) return;
        if (next.revision !== revision || next.workflow_version !== workflowVersion)
          throw new RequestError(412, "The case ledger changed. Reload the claim to see the latest settlement.");
        setReview(next);
      })
      .catch(failure => { if (!controller.signal.aborted) setError(failure); });
    return () => controller.abort();
  }, [base, revision, workflowVersion, attempt]);

  async function confirm(action: BookingAction | "agent_review") {
    if (pending || !current || (action === "agent_review" && !consent)) return;
    const booking = action === "book_spot" || action === "book_forward";
    if (booking && !selectedQuote) return;
    const bankDocument = action === "record_short_credit" ? "initial_credit" : action === "record_topup" ? "topup_credit" : undefined;
    setPending(true);
    setError(undefined);
    try {
      const explain = action === "agent_review";
      const response = await api(base + (explain ? "/agent-review" : "/actions"), {
        method: "POST", headers: { "Content-Type": "application/json", "If-Match": '"' + revision + '"' },
        body: JSON.stringify(explain ? { confirmed: true } : {
          action, confirmed: true, workflow_version: workflowVersion,
          quote_id: booking ? selectedQuote?.quote_id : undefined, bank_document: bankDocument,
        }),
      });
      if (explain) {
        const next: Review = await response.json();
        if (next.revision !== revision || next.workflow_version !== workflowVersion)
          throw new RequestError(412, "The ledger changed during the agent review. Reload the claim.");
        setReview(next);
        setConsent(false);
      } else {
        const next: DischargeClaim = await response.json();
        if (next.id !== claim.id || next.revision !== revision) throw new Error("The returned claim changed. Reload before continuing.");
        setConsent(false);
        onUpdated(next);
      }
    } catch (failure) {
      if (failure instanceof RequestError && [409, 412].includes(failure.status)) setReview(undefined);
      setError(failure instanceof Error ? failure : new Error("The simulation request could not be completed."));
    } finally { setPending(false); }
  }

  return <section className="panel pattaya-panel" aria-label="Pattaya settlement simulation">
    <div className="panel-heading"><h2><Landmark size={18} />Pattaya settlement desk</h2><span className="small">Bank simulation</span></div>
    <div className="pattaya-body">
      <p className="hint">Fictional insurer guarantee based on Bangkok Hospital Pattaya’s published lens package. Bank quotes and receipts are simulated. <a href={packageUrl} target="_blank" rel="noreferrer">View package terms</a></p>
      {error && <div role="alert" className="error-message">{error.message}{" "}
        {error instanceof RequestError && [409, 412].includes(error.status)
          ? <button className="text-action" onClick={reload}>Reload claim</button>
          : <button className="text-action" onClick={() => { setReview(undefined); setAttempt(n => n + 1); }}>Refresh settlement</button>}
      </div>}
      {!current && !error && <p className="hint" role="status">Reviewing the guarantee and bank ledger…</p>}
      {current && <>
        <dl className="pattaya-balances">
          <div><dt>Insurer guarantee</dt><dd>{minorMoney(current.guaranteed_minor, "THB")}</dd>
            {guaranteeSource && <button type="button" className="text-action" onClick={() => openSource(guaranteeSource)}><FileText size={13} />View final guarantee</button>}</div>
          <div><dt>Hospital credited</dt><dd>{minorMoney(current.paid_minor, "THB")}</dd></div>
          <div><dt>Outstanding hospital balance</dt><dd>{minorMoney(current.outstanding_minor, "THB")}</dd></div>
          <div><dt>Patient FX charge</dt><dd>{minorMoney(current.patient_fx_minor, "THB")}</dd></div>
        </dl>
        <div className="pattaya-columns">
          <div className="pattaya-action" aria-busy={pending}><h3 aria-live="polite">{stepNames[current.next_action]}</h3>
            {current.next_action === "book" && <>
              <p>Quotes for {displayDate(current.quotes[0]?.trade_date || "")}. The hospital payment is due {displayDate(current.hospital_due_date)}.</p>
              <fieldset className="pattaya-quotes" disabled={pending}><legend>Choose a simulated USD/THB quote</legend>
                {current.quotes.map(quote => <label key={quote.instrument}>
                  <input type="radio" name="pattaya-quote" value={quote.instrument} checked={choice === quote.instrument} onChange={() => setChoice(quote.instrument)} />
                  <span><strong>{instrumentNames[quote.instrument]}</strong><small>THB delivered {displayDate(quote.value_date)}</small></span>
                  <span className="pattaya-price"><strong>{minorMoney(quote.usd_minor, "USD")}</strong><small>{quote.rate_thb_per_usd} THB / USD</small></span>
                </label>)}
              </fieldset>
              <button className="primary" disabled={pending || !selectedQuote} onClick={() => void confirm(choice === "spot" ? "book_spot" : "book_forward")}>Confirm simulated {choice} booking <ArrowRight size={14} /></button>
            </>}
            {bookedQuote && <p className="pattaya-deal">{instrumentNames[bookedQuote.instrument]} booked {displayDate(bookedQuote.trade_date)} · {minorMoney(bookedQuote.usd_minor, "USD")} at {bookedQuote.rate_thb_per_usd} THB / USD · THB delivery {displayDate(bookedQuote.value_date)}.</p>}
            {current.next_action === "record_short" && <>
              <p>The payer instructed a transfer. The receiving bank reports {minorMoney(current.short_credit_minor, "THB")} credited to the hospital.</p>
              <div className="pattaya-document-links">
                <a className="text-action" href={preview("instruction")} target="_blank" rel="noreferrer"><FileText size={14} />Transfer instruction</a>
                <a className="text-action" href={preview("initial_credit")} target="_blank" rel="noreferrer"><FileText size={14} />Beneficiary credit advice</a>
              </div>
              <button className="primary" disabled={pending} onClick={() => void confirm("record_short_credit")}>Record simulated short payment</button>
            </>}
            {current.next_action === "top_up" && current.shortfall_owner === "insurer" && <>
              <p><strong>The insurer owes {minorMoney(current.outstanding_minor, "THB")}.</strong> Its baht guarantee covers the shortfall. Record the separate credit when the top-up arrives.</p>
              <div className="pattaya-document-links"><a className="text-action" href={preview("topup_credit")} target="_blank" rel="noreferrer"><FileText size={14} />Insurer top-up credit advice</a></div>
              <button className="primary" disabled={pending} onClick={() => void confirm("record_topup")}>Record simulated insurer top-up</button>
            </>}
            {current.next_action === "complete" && <p>The bank credits cover the insurer’s guarantee. The patient’s FX charge is {minorMoney(current.patient_fx_minor, "THB")}.</p>}
            {current.next_action === "review" && <p>Check the source documents and payer correspondence before proceeding.</p>}
          </div>
          <div className="pattaya-reviews"><h3>Settlement agents</h3>
            <ul>{current.trace.map(step => <li key={step.agent}><strong>{step.agent}</strong><p>{step.summary}</p><small>{step.evidence}</small></li>)}</ul>
          </div>
        </div>
        {receipts.length > 0 && <div className="pattaya-receipts"><h3>Hospital credit receipts</h3>
          <ul>{receipts.map(receipt => <li key={receipt.id}>
            <div><strong>{minorMoney(typeof receipt.data.amount_minor === "number" ? receipt.data.amount_minor : null, "THB")}</strong>
              {typeof receipt.data.value_date === "string" && <span> · {displayDate(receipt.data.value_date)}</span>}
              {receipt.source_url && typeof receipt.data.fee_minor === "number" &&
                <small>Documented bank deduction · {minorMoney(receipt.data.fee_minor, "THB")}</small>}
              {typeof receipt.data.bank_reference === "string" && <small>Bank reference · {receipt.data.bank_reference}</small>}
            </div>
            {receipt.source_url
              ? <button className="text-action" onClick={() => openSource({ role: "bank_credit", label: "Recorded beneficiary credit advice",
                url: receipt.source_url!, page: 1, quote: "" })}><FileText size={14} />View recorded advice</button>
              : <small>No bank advice attached. The reason for any difference is unverified.</small>}
          </li>)}</ul>
        </div>}
        {current.model_enabled && <details className="ai-review pattaya-model"><summary>Request an OpenAI settlement review</summary>
          <fieldset className="plain-fields" disabled={pending}>
            <label className="check-field"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} />
              Send the synthetic financial figures and settlement stage to OpenAI for a read-only review.</label>
            <button className="secondary" disabled={!consent || pending} onClick={() => void confirm("agent_review")}>{pending ? "Working…" : "Run OpenAI review"}</button>
          </fieldset>
          {current.model_review.status !== "not_requested" && <div role="status"><p>{current.model_review.summary}</p>
            {current.model_review.tools.length > 0 && <small>Tools used · {current.model_review.tools.join(", ")}</small>}</div>}
        </details>}
      </>}
    </div>
  </section>;
}
