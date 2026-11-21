import { useEffect, useState } from "react";
import { ArrowRight, ExternalLink, FileText, Landmark } from "lucide-react";
import { api, displayDate, RequestError, sameOriginSource, type Source } from "./api";
import { claimPath, minorMoney, pattayaSteps, type DischargeClaim } from "./dischargeApi";
import { GuaranteeFees } from "./GuaranteeFees";
import "./pattaya.css";

type Instrument = "spot" | "forward";
type BookingAction = "book_spot" | "book_forward" | "record_short_credit" | "record_remittance" | "record_topup";
type FundingTerms = { instrument: Instrument; rate_thb_per_usd: string; usd_minor: number; trade_date: string; value_date: string; expires_at?: string };
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
  booked_quote: FundingTerms | null;
  quotes: (FundingTerms & { quote_id: string })[];
  next_action: keyof typeof pattayaSteps;
  trace: { agent: string; summary: string; evidence: string }[];
};

type MarketRate =
  | { status: "available"; rate_thb_per_usd: string; rate_date: string; usd_minor: number; source_url: string }
  | { status: "unavailable" };

const instrumentNames = { spot: "Spot", forward: "Forward" };
function deliveryMargin(value: string, due: string) {
  const days = Math.round((Date.parse(due) - Date.parse(value)) / 86400000);
  return days === 0 ? "On the due date" : days > 0 ? days + " days early" : -days + " days late";
}
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

export function PattayaSettlement({ claim, onUpdated, reload, openSource }: {
  claim: DischargeClaim;
  onUpdated: (next: DischargeClaim) => void;
  reload: () => void;
  openSource: (source: Source, trigger: HTMLButtonElement) => void;
}) {
  const base = claimPath(claim.id) + "/pattaya";
  const [review, setReview] = useState<Review & { caseId: string }>();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<Error>();
  const [insurerReference, setInsurerReference] = useState("");
  const [selectedQuoteId, setSelectedQuoteId] = useState<string>();
  const [attempt, setAttempt] = useState(0);
  const [expiredSheet, setExpiredSheet] = useState<string>();
  const [verifyLedger, setVerifyLedger] = useState(false);
  const guarantee = claim.events.find(event => event.kind === "reply" && event.data.outcome === "confirmed" && event.source_url);
  const guaranteeSource = guarantee?.source_url ? {
    role: "payer_decision", label: "Final insurer guarantee", url: guarantee.source_url, page: 1,
    quote: "", recordedSummary: typeof guarantee.data.terms === "string" ? guarantee.data.terms : undefined,
  } : null;
  const revision = claim.revision, workflowVersion = claim.workflow_version;
  const current = review?.caseId === claim.id && review.revision === revision && review.workflow_version === workflowVersion ? review : undefined;
  const bookedQuote = current?.booked_quote;
  const booking = claim.events.find(event => event.kind === "fx_booking");
  const selectedQuote = current?.quotes.find(quote => quote.quote_id === selectedQuoteId);
  const remittance = claim.events.find(event => event.kind === "topup_remittance");
  const expiry = current?.next_action === "book" ? current.quotes[0]?.expires_at : undefined;
  const expired = !!expiry && (expiry === expiredSheet || Date.parse(expiry) <= Date.now());
  const receipts = claim.events.filter(event => event.kind === "payment");
  const followUpOwner = receipts.find(event => typeof event.data.shortfall_follow_up_owner === "string")?.data.shortfall_follow_up_owner;
  const preview = (kind: "instruction" | "initial_credit" | "topup_instruction" | "topup_credit") =>
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
        setReview({ ...next, caseId: claim.id });
        setVerifyLedger(false);
      })
      .catch(failure => { if (!controller.signal.aborted) setError(failure); });
    return () => controller.abort();
  }, [base, claim.id, revision, workflowVersion, attempt]);

  useEffect(() => {
    if (!expiry) return;
    const timer = window.setTimeout(() => setExpiredSheet(expiry), Math.max(0, Date.parse(expiry) - Date.now()));
    return () => window.clearTimeout(timer);
  }, [expiry]);

  function refreshSettlement() {
    setSelectedQuoteId(undefined);
    setReview(undefined);
    setAttempt(n => n + 1);
  }

  async function confirm(action: BookingAction) {
    if (pending || !current || verifyLedger) return;
    const booking = action === "book_spot" || action === "book_forward";
    if (booking && (!selectedQuote || expired)) return;
    const bankDocument = action === "record_remittance" ? "topup_instruction" : action === "record_short_credit" ? "initial_credit" : action === "record_topup" ? "topup_credit" : undefined;
    setPending(true);
    setError(undefined);
    try {
      const response = await api(base + "/actions", {
        method: "POST", headers: { "Content-Type": "application/json", "If-Match": '"' + revision + '"' },
        body: JSON.stringify({
          action, confirmed: true, workflow_version: workflowVersion,
          quote_id: booking ? selectedQuote?.quote_id : undefined, bank_document: bankDocument,
          insurer_reference: action === "record_remittance" ? insurerReference.trim() || undefined : undefined,
        }),
      });
      const next: DischargeClaim = await response.json();
      if (next.id !== claim.id || next.revision !== revision) throw new Error("The returned claim changed. Reload before continuing.");
      onUpdated(next);
    } catch (failure) {
      setSelectedQuoteId(undefined);
      setReview(undefined);
      setVerifyLedger(true);
      setError(failure instanceof RequestError && failure.status < 500 ? failure
        : new Error("Confirmation could not be verified. Check the saved ledger before taking another action."));
    } finally { setPending(false); }
  }

  return <section className="panel pattaya-panel" aria-label="Pattaya settlement simulation">
    <div className="panel-heading"><h2><Landmark size={18} />Pattaya settlement desk</h2><span className="small">Bank simulation</span></div>
    <div className="pattaya-body">
      <p className="hint">Based on Bangkok Hospital Pattaya’s <a href={packageUrl} target="_blank" rel="noreferrer">lens package</a>. The packet review and insurer guarantee are preloaded practice records. You confirm the simulated booking and each bank receipt.</p>
      {error && <div role="alert" className="error-message">{error.message}{" "}
        {verifyLedger || (error instanceof RequestError && [409, 412].includes(error.status))
          ? <button className="text-action" onClick={() => { reload(); refreshSettlement(); }}>Check saved ledger</button>
          : <button className="text-action" onClick={refreshSettlement}>Refresh settlement</button>}
      </div>}
      {!current && !error && <p className="hint" role="status">Reading the guarantee and hospital ledger…</p>}
      {current && <>
        {current.next_action !== "review" && <p className="pattaya-progress" role="status">
          {current.next_action === "complete" ? "Settlement complete" : "Settlement step " + ({ book: 1, record_short: 2, top_up: 3, confirm_topup: 4 })[current.next_action] + " of 4"}
        </p>}
        <dl className="pattaya-balances">
          <div><dt>Insurer guarantee</dt><dd>{minorMoney(current.guaranteed_minor, "THB")}</dd>
            {guaranteeSource && <button type="button" className="text-action" onClick={e => openSource(guaranteeSource, e.currentTarget)}><FileText size={13} />View final guarantee</button>}</div>
          <div><dt>Hospital credited</dt><dd>{minorMoney(current.paid_minor, "THB")}</dd></div>
          <div><dt>Outstanding hospital balance</dt><dd>{minorMoney(current.outstanding_minor, "THB")}</dd></div>
          <div><dt>Patient FX charge</dt><dd>{current.patient_fx_minor === null ? "Needs review" : minorMoney(current.patient_fx_minor, "THB")}</dd></div>
        </dl>
        <div className="pattaya-columns">
          <div className="pattaya-action" aria-busy={pending}><h3 aria-live="polite">{pattayaSteps[current.next_action]}</h3>
            {current.next_action === "book" && <>
              <p>Acting as insurer treasury, choose the terms to book. The hospital payment is due {displayDate(current.hospital_due_date)}.</p>
              <MarketReference key={base + revision} path={base + "/reference-rate?revision=" + revision} amount={current.guaranteed_minor} />
              <fieldset className="pattaya-quotes" disabled={pending || expired}><legend>Simulated bank quotes · {displayDate(current.quotes[0]?.trade_date || "")}</legend>
                {current.quotes.map(quote => <label key={quote.instrument}>
                  <input type="radio" name="pattaya-quote" value={quote.instrument} checked={selectedQuoteId === quote.quote_id} onChange={() => setSelectedQuoteId(quote.quote_id)} />
                  <span><strong>{instrumentNames[quote.instrument]}</strong><small>{displayDate(quote.value_date)} · {deliveryMargin(quote.value_date, current.hospital_due_date)}</small></span>
                  <span className="pattaya-price"><strong>{minorMoney(quote.usd_minor, "USD")}</strong><small>{quote.rate_thb_per_usd} THB / USD</small></span>
                </label>)}
              </fieldset>
              {current.quotes.length === 2 && current.quotes[0].usd_minor !== current.quotes[1].usd_minor && <p>
                {instrumentNames[current.quotes[0].usd_minor < current.quotes[1].usd_minor ? current.quotes[0].instrument : current.quotes[1].instrument]} costs {minorMoney(Math.abs(current.quotes[0].usd_minor - current.quotes[1].usd_minor), "USD")} less.
              </p>}
              {expiry && <p className="hint" role="status">{expired ? "These offers have expired." : "Offers expire at " + new Date(expiry).toLocaleTimeString() + " local time."}</p>}
              {expired ? <button className="secondary" disabled={pending} onClick={refreshSettlement}>Get current offers</button> :
              <button className="primary" disabled={pending || !selectedQuote} onClick={() => selectedQuote && void confirm(selectedQuote.instrument === "spot" ? "book_spot" : "book_forward")}>{selectedQuote ? "Book simulated " + selectedQuote.instrument + " · " + minorMoney(selectedQuote.usd_minor, "USD") + " · " + displayDate(selectedQuote.value_date) : "Select a funding option"} <ArrowRight size={14} /></button>}
            </>}
            {bookedQuote && <p className="pattaya-deal">{instrumentNames[bookedQuote.instrument]} booked {displayDate(bookedQuote.trade_date)} · {minorMoney(bookedQuote.usd_minor, "USD")} at {bookedQuote.rate_thb_per_usd} THB / USD · THB delivery {displayDate(bookedQuote.value_date)}.</p>}
            {bookedQuote && booking && <p className="pattaya-trade-ref">Recorded by {booking.actor || "practice treasury desk"}. {typeof booking.data.bank_trade_id === "string" && <>Simulated bank trade ID <code>{booking.data.bank_trade_id}</code>.</>}</p>}
            {current.next_action === "record_short" && <>
              <p>Check the receiving bank’s advice before recording the {minorMoney(current.short_credit_minor, "THB")} credited to the hospital. Recording the short credit assigns you the follow-up.</p>
              <div className="pattaya-document-links">
                <a className="text-action" href={preview("instruction")} target="_blank" rel="noreferrer"><FileText size={14} />Transfer instruction</a>
                <a className="text-action" href={preview("initial_credit")} target="_blank" rel="noreferrer"><FileText size={14} />Beneficiary credit advice</a>
              </div>
              <button className="primary" disabled={pending} onClick={() => void confirm("record_short_credit")}>Record simulated short payment</button>
            </>}
            {current.next_action === "top_up" && current.shortfall_owner === "insurer" && <>
              <p>Hospital follow-up: {typeof followUpOwner === "string" ? followUpOwner : "Owner was not recorded"}. Guaranteed payment due {displayDate(current.hospital_due_date)}.</p>
              <p><strong>The insurer owes {minorMoney(current.outstanding_minor, "THB")}.</strong> Record the sending bank’s instruction and reference. The balance stays due until the hospital confirms receipt.</p>
              <a className="text-action" href={preview("topup_instruction")} target="_blank" rel="noreferrer"><FileText size={14} />Insurer remittance instruction</a>
              <label>Insurer remittance reference (optional)<input type="text" maxLength={100} value={insurerReference} onChange={e => setInsurerReference(e.target.value)} /></label>
              <button className="primary" disabled={pending} onClick={() => void confirm("record_remittance")}>Record simulated insurer remittance</button>
            </>}
            {current.next_action === "confirm_topup" && <>
              <p>The insurer instructed {minorMoney(current.outstanding_minor, "THB")}. Check the receiving bank’s advice before recording the hospital credit.</p>
              <div className="pattaya-document-links"><a className="text-action" href={preview("topup_credit")} target="_blank" rel="noreferrer"><FileText size={14} />Insurer top-up credit advice</a></div>
              <button className="primary" disabled={pending} onClick={() => void confirm("record_topup")}>Confirm simulated hospital top-up credit</button>
            </>}
            {current.next_action === "complete" && <p>The recorded hospital receipts cover the guarantee in full.</p>}
            {current.next_action === "review" && <p>Check the guarantee terms and hospital receipts before proceeding.</p>}
          </div>
          <div className="pattaya-reviews"><h3>Settlement evidence</h3>
            <ul>{current.trace.map(step => <li key={step.agent}><strong>{step.agent}</strong><p>{step.summary}</p><small>{step.evidence}</small></li>)}</ul>
            <GuaranteeFees claim={claim} openLetter={openSource} />
          </div>
        </div>
        {remittance && <div className="pattaya-receipts"><h3>Insurer remittance instruction</h3>
          <p>{String(remittance.data.bank_reference)} · {displayDate(String(remittance.data.value_date))} · {minorMoney(Number(remittance.data.instructed_minor), "THB")}</p>
          {typeof remittance.data.insurer_reference === "string" && <p>Insurer reference · {remittance.data.insurer_reference}</p>}
          {remittance.source_url && <button className="text-action" onClick={e => openSource({ role: "bank_instruction", label: "Insurer remittance instruction", url: remittance.source_url!, page: 1, quote: "" }, e.currentTarget)}>View recorded instruction</button>}
        </div>}
        {receipts.length > 0 && <div className="pattaya-receipts"><h3>Hospital credit receipts</h3>
          <ul>{receipts.map(receipt => <li key={receipt.id}>
            <div><strong>{minorMoney(typeof receipt.data.amount_minor === "number" ? receipt.data.amount_minor : null, "THB")}</strong>
              {typeof receipt.data.value_date === "string" && <span> · {displayDate(receipt.data.value_date)}</span>}
              {receipt.source_url && typeof receipt.data.fee_minor === "number" &&
                <small>Documented bank deduction · {minorMoney(receipt.data.fee_minor, "THB")}</small>}
              {typeof receipt.data.bank_reference === "string" && <small>Bank reference · {receipt.data.bank_reference}</small>}
            </div>
            {receipt.source_url
              ? <button className="text-action" onClick={e => openSource({ role: "bank_credit", label: "Recorded beneficiary credit advice",
                url: receipt.source_url!, page: 1, quote: "" }, e.currentTarget)}><FileText size={14} />View recorded advice</button>
              : <small>No bank advice attached. The reason for any difference is unverified.</small>}
          </li>)}</ul>
        </div>}
      </>}
    </div>
  </section>;
}
