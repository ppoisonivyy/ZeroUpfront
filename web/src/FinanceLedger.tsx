import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { api } from "./api";
import { minorMoney } from "./dischargeApi";
import "./finance.css";

type Entry = {
  case_id: string; revision: number; current: boolean; currency: string | null;
  approved_minor: number | null; credited_minor: number | null; outstanding_minor: number | null;
  receipt_count: number; last_receipt_id: number | null;
  status: "awaiting_decision" | "outstanding" | "settled" | "reconciliation_required";
};
type Page = { items: Entry[]; page: number; has_more: boolean };
const labels = {
  awaiting_decision: "Awaiting payer decision", outstanding: "Outstanding",
  settled: "Settled", reconciliation_required: "Review credits",
};

export function FinanceLedger() {
  const [page, setPage] = useState(1);
  const [attempt, refresh] = useState(0);
  const [result, setResult] = useState<Page | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setResult(null); setError("");
    api("/api/finance/reconciliation?page=" + page, { signal: controller.signal })
      .then(response => response.json())
      .then(data => { if (!controller.signal.aborted) setResult(data); })
      .catch(cause => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Reconciliation could not be loaded."); });
    return () => controller.abort();
  }, [page, attempt]);

  return <section aria-labelledby="finance-title">
    <div className="page-title finance-title"><div>
      <p className="section-label">Hospital finance · Read only</p>
      <h1 id="finance-title">Assigned reconciliation</h1>
      <p>Compare the written payer decision with credits recorded against each claim revision.</p>
    </div><button className="secondary" onClick={() => refresh(n => n + 1)}>
      <RefreshCw size={15} /> Refresh
    </button></div>
    {error ? <p className="error-message" role="alert">{error}</p> : !result ?
      <p role="status">Loading assigned records…</p> : <>
      {!result.items.length ? <div className="panel queue-empty"><h2>No assigned records on this page</h2>
        {page === 1 && <p>Your hospital administrator can assign discharge case references to your finance account.</p>}
      </div> :
        <div className="work-inbox finance-list">{result.items.map(entry => <article key={entry.case_id + ":" + entry.revision}>
          <header><div><h2>{entry.case_id}</h2><p>Revision {entry.revision} · {entry.current ? "Current" : "Historical"}</p></div>
            <strong className={"claim-pill " + (entry.status === "settled" ? "state-staff_reviewed" : "state-needs_review")}>{labels[entry.status]}</strong></header>
          <dl><div><dt>Payer approved</dt><dd>{minorMoney(entry.approved_minor, entry.currency)}</dd></div>
            <div><dt>Recorded credits</dt><dd>{entry.receipt_count ? minorMoney(entry.credited_minor, entry.currency) : "None recorded"}</dd></div>
            <div><dt>Outstanding</dt><dd>{minorMoney(entry.outstanding_minor, entry.currency)}</dd></div></dl>
          {entry.last_receipt_id !== null && <small>{entry.receipt_count} recorded {entry.receipt_count === 1 ? "credit" : "credits"} · Latest ledger entry #{entry.last_receipt_id}</small>}
        </article>)}</div>}
      {(page > 1 || result.has_more) && <nav className="claim-pages" aria-label="Reconciliation pages"><span>Page {page}</span>
        <button className="secondary" disabled={page === 1} onClick={() => setPage(n => n - 1)}>Previous</button>
        <button className="secondary" disabled={!result.has_more} onClick={() => setPage(n => n + 1)}>Next</button>
      </nav>}
    </>}
  </section>;
}
