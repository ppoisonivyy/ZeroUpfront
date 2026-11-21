import { useEffect, useState } from "react";
import { ArrowRight, ExternalLink, FileText, Landmark } from "lucide-react";
import { api, displayDate, RequestError, type Source } from "./api";
import { claimPath, minorMoney, type DischargeClaim } from "./dischargeApi";
import { GuaranteeFees } from "./GuaranteeFees";
import "./pattaya.css";

type Instrument = "spot" | "forward";
type BookingAction = "book_spot" | "book_forward" | "record_short_credit" | "record_topup";
type Review = {
  revision: number;
  workflow_version: number;
  hospital_due_date: string;
  guaranteed_minor: number;
  paid_minor: number;
  outstanding_minor: number;
  patient_fx_minor: number | null;
  short_credit_minor: number;
  shortfall_owner: "insurer" | null;
  booking: Instrument | null;
  quotes: { instrument: Instrument; rate_thb_per_usd: string; usd_minor: number; trade_date: string; value_date: string }[];
  next_action: "book" | "record_short" | "top_up" | "complete" | "review";
  trace: { agent: string; summary: string; evidence: string }[];
};

type MarketRate =
  | { status: "available"; rate_thb_per_usd: string; rate_date: string; usd_minor: number; source_url: string }
  | { status: "unavailable" };

const instrumentNames = { spot: "Spot", forward: "Forward" };
const stepNames: Record<Review["next_action"], string> = {
  book: "Choose funding", record_short: "Record the hospital credit", top_up: "Reconcile the short payment",
  complete: "Hospital paid in full", review: "Review the claim documents",
};
const packageUrl = "https://www.bangkokhospital.com/en/pattaya/package/lens-replacement-surgery-package-bph";

function MarketReference({ path, amount }: { path: string; amount: number }) {
  const [rate, setRate] = useState<MarketRate>();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    api(path, { signal: controller.signal })
      .then(response => response.json())
      .then((next: MarketRate) => { if (!controller.signal.aborted) setRate(next); })
      .catch(() => { if (!controller.signal.aborted) setRate({ status: "unavailable" }); });
    return () => controller.abort();
  }, [path, attempt]);

  return <section className="pattaya-reference" aria-label="Market reference">
    <h4>Market reference</h4>
    <div role="status">
      {rate?.status === "available" ? <>
        <div className="pattaya-reference-rate"><strong>1 USD = {rate.rate_thb_per_usd} THB</strong>
          <span>{displayDate(rate.rate_date)}</span></div>
        <p>{minorMoney(amount, "THB")} ≈ {minorMoney(rate.usd_minor, "USD")} before fees.</p>
        <a href={rate.source_url} target="_blank" rel="noreferrer">ECB via Frankfurter <ExternalLink size={12} aria-hidden="true" /></a>
      </> : rate ? <><p>Reference rate unavailable. You can continue with the simulated bank quotes.</p>
        <button type="button" className="text-action" onClick={() => { setRate(undefined); setAttempt(n => n + 1); }}>Retry rate lookup</button></>
        : <p>Looking up the published USD/THB rate…</p>}
    </div>
  </section>;
}

export function PattayaSettlement({ claim, onUpdated, reload, openLetter }: {
  claim: DischargeClaim;
  onUpdated: (next: DischargeClaim) => void;
  reload: () => void;
  openLetter: (source: Source) => void;
}) {
  const base = claimPath(claim.id) + "/pattaya";
  const [review, setReview] = useState<Review>();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error>();
  const [choice, setChoice] = useState<Instrument>();
  const [attempt, setAttempt] = useState(0);
  const guarantee = claim.events.find(event => event.kind === "reply" && event.data.outcome === "confirmed" && event.source_url);
  const guaranteeSource = guarantee?.source_url ? {
    role: "payer_decision", label: "Final insurer guarantee", url: guarantee.source_url, page: 1,
    quote: typeof guarantee.data.terms === "string" ? guarantee.data.terms : "",
  } : null;
  const revision = claim.revision, workflowVersion = claim.workflow_version;
  const current = review?.revision === revision && review.workflow_version === workflowVersion ? review : undefined;
  const bookedQuote = current?.quotes.find(quote => quote.instrument === current.booking);
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

  async function confirm(action: BookingAction) {
    if (pending || !current) return;
    setPending(true);
    setError(undefined);
    try {
      const response = await api(base + "/actions", {
        method: "POST", headers: { "Content-Type": "application/json", "If-Match": '"' + revision + '"' },
        body: JSON.stringify({ action, confirmed: true, workflow_version: workflowVersion }),
      });
      const next: DischargeClaim = await response.json();
      if (next.id !== claim.id || next.revision !== revision) throw new Error("The returned claim changed. Reload before continuing.");
      onUpdated(next);
    } catch (failure) {
      setError(failure instanceof Error ? failure : new Error("The simulation request could not be completed."));
    } finally { setPending(false); }
  }

  return <section className="panel pattaya-panel" aria-label="Pattaya settlement simulation">
    <div className="panel-heading"><h2><Landmark size={18} />Pattaya settlement desk</h2><span className="small">Bank simulation</span></div>
    <div className="pattaya-body">
      <p className="hint">Fictional guarantee based on Bangkok Hospital Pattaya’s <a href={packageUrl} target="_blank" rel="noreferrer">lens package</a>. All bookings and receipts are simulated.</p>
      {error && <div role="alert" className="error-message">{error.message}{" "}
        {error instanceof RequestError && [409, 412].includes(error.status)
          ? <button className="text-action" onClick={reload}>Reload claim</button>
          : <button className="text-action" onClick={() => { setReview(undefined); setAttempt(n => n + 1); }}>Refresh settlement</button>}
      </div>}
      {!current && !error && <p className="hint" role="status">Reading the guarantee and hospital ledger…</p>}
      {current && <>
        <dl className="pattaya-balances">
          <div><dt>Insurer guarantee</dt><dd>{minorMoney(current.guaranteed_minor, "THB")}</dd>
            {guaranteeSource && <button type="button" className="text-action" onClick={() => openLetter(guaranteeSource)}><FileText size={13} />View final guarantee</button>}</div>
          <div><dt>Hospital credited</dt><dd>{minorMoney(current.paid_minor, "THB")}</dd></div>
          <div><dt>Outstanding hospital balance</dt><dd>{minorMoney(current.outstanding_minor, "THB")}</dd></div>
          <div><dt>Patient FX charge</dt><dd>{current.patient_fx_minor === null ? "Needs review" : minorMoney(current.patient_fx_minor, "THB")}</dd></div>
        </dl>
        <div className="pattaya-columns">
          <div className="pattaya-action" aria-busy={pending}><h3 aria-live="polite">{stepNames[current.next_action]}</h3>
            {current.next_action === "book" && <>
              <p>The hospital payment is due {displayDate(current.hospital_due_date)}.</p>
              <MarketReference key={base + revision} path={base + "/reference-rate?revision=" + revision} amount={current.guaranteed_minor} />
              <fieldset className="pattaya-quotes" disabled={pending}><legend>Simulated bank quotes · {displayDate(current.quotes[0]?.trade_date || "")}</legend>
                {current.quotes.map(quote => <label key={quote.instrument}>
                  <input type="radio" name="pattaya-quote" value={quote.instrument} checked={choice === quote.instrument} onChange={() => setChoice(quote.instrument)} />
                  <span><strong>{instrumentNames[quote.instrument]}</strong><small>Delivery {displayDate(quote.value_date)}</small></span>
                  <span className="pattaya-price"><strong>{minorMoney(quote.usd_minor, "USD")}</strong><small>{quote.rate_thb_per_usd} THB / USD</small></span>
                </label>)}
              </fieldset>
              <button className="primary" disabled={pending || !choice} onClick={() => choice && void confirm(choice === "spot" ? "book_spot" : "book_forward")}>{choice ? "Confirm simulated " + choice + " booking" : "Select a funding option"} <ArrowRight size={14} /></button>
            </>}
            {bookedQuote && <p className="pattaya-deal">{instrumentNames[bookedQuote.instrument]} booked {displayDate(bookedQuote.trade_date)} · {minorMoney(bookedQuote.usd_minor, "USD")} at {bookedQuote.rate_thb_per_usd} THB / USD · THB delivery {displayDate(bookedQuote.value_date)}.</p>}
            {current.next_action === "record_short" && <>
              <p>The simulated bank advice shows a hospital credit of {minorMoney(current.short_credit_minor, "THB")}. Confirm the receipt to update the outstanding balance.</p>
              <button className="primary" disabled={pending} onClick={() => void confirm("record_short_credit")}>Record simulated short payment</button>
            </>}
            {current.next_action === "top_up" && current.shortfall_owner === "insurer" && <>
              <p><strong>The insurer owes {minorMoney(current.outstanding_minor, "THB")}.</strong> Its guarantee covers the shortfall. Record the separate credit when the top-up arrives.</p>
              <button className="primary" disabled={pending} onClick={() => void confirm("record_topup")}>Record simulated insurer top-up</button>
            </>}
            {current.next_action === "complete" && <p>The recorded hospital receipts cover the guarantee in full.</p>}
            {current.next_action === "review" && <p>Check the guarantee terms and hospital receipts before proceeding.</p>}
          </div>
          <div className="pattaya-reviews"><h3>Settlement evidence</h3>
            <ul>{current.trace.map(step => <li key={step.agent}><strong>{step.agent}</strong><p>{step.summary}</p><small>{step.evidence}</small></li>)}</ul>
            <GuaranteeFees claim={claim} openLetter={openLetter} />
          </div>
        </div>
      </>}
    </div>
  </section>;
}
