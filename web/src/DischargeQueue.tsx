import { useEffect, useState } from "react";
import {
  ArrowRight, BadgeCheck, CircleAlert, ClipboardList, FileSearch, Filter,
  Inbox, Layers, ListFilter, Play, Plus, ReceiptText, Search, Send, X,
} from "lucide-react";
import { useStaffSession } from "./Auth";
import { api, displayDate } from "./api";
import { claimHref, claimPayerStatus, claimStatus, minorMoney, type DischargeClaim, type DischargeQueue, type DischargeWorklist } from "./dischargeApi";

const examples = {
  duplicate_line: "Duplicate bill line", aligned: "Aligned discharge packet",
  over_cap: "Bill exceeds written cap", missing_records: "Missing supporting records",
  unapproved_procedure: "Unapproved procedure", total_mismatch: "Invoice totals disagree",
  orphan_credit: "Unmatched credit", share_mismatch: "Patient share differs",
  member_mismatch: "Member mismatch", stay_extension: "Stay exceeds recorded dates",
  late_reply: "Late payer reply", mixed_currency: "Mixed currencies",
  unreadable_summary: "Unreadable discharge summary",
};
const queues = [
  { id: "needs", label: "Needs investigation", icon: CircleAlert },
  { id: "ready", label: "Ready for review", icon: BadgeCheck },
  { id: "payer", label: "Payer correspondence", icon: Send },
] as const;
export function ClaimPill({ status }: { status: string }) {
  const Icon = status === "needs_review" ? CircleAlert : status === "staff_reviewed" ? BadgeCheck : ClipboardList;
  return <span className={"claim-pill state-" + status}><Icon size={13} />{claimStatus(status)}</span>;
}

export function DischargeList({ prior }: { prior?: string }) {
  const { mode } = useStaffSession();
  const [example, setExample] = useState("duplicate_line");
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState({ queue: "all" as DischargeQueue, search: "", page: 1 });
  const [retry, setRetry] = useState(0);
  const [result, setResult] = useState<{ key: string; data?: DischargeWorklist; error?: string }>({ key: "" });
  const { queue, page } = filter;
  const query = new URLSearchParams({ queue, search: filter.search, page: String(page) }).toString();
  const key = query + ":" + retry;
  useEffect(() => {
    const term = search.trim();
    if (term === filter.search) return;
    const timer = window.setTimeout(() => setFilter(prev => ({ ...prev, search: term, page: 1 })), 180);
    return () => window.clearTimeout(timer);
  }, [search, filter.search]);
  useEffect(() => {
    const abort = new AbortController();
    api("/api/discharge/worklist?" + query, { signal: abort.signal })
      .then(response => response.json())
      .then((data: DischargeWorklist) => {
        if (abort.signal.aborted) return;
        const last = Math.max(1, Math.ceil(data.total / data.page_size));
        if (data.page > last) setFilter(prev => ({ ...prev, page: last }));
        else setResult({ key, data });
      })
      .catch(err => {
        if (!abort.signal.aborted) setResult({ key, error: err instanceof Error ? err.message : "Claims could not be loaded." });
      });
    return () => abort.abort();
  }, [query, key]);
  const current = result.key === key && filter.search === search.trim() ? result : undefined;
  const data = current?.data;
  const setQueue = (next: DischargeQueue) => setFilter(prev => ({ ...prev, queue: next, page: 1 }));
  async function start(scenario: string) {
    if (pending) return;
    setPending(scenario); setError("");
    try {
      const claim: DischargeClaim = await (await api("/api/discharge/examples/" + scenario, { method: "POST" })).json();
      location.hash = claimHref(claim.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the practice claim.");
    } finally { setPending(""); }
  }
  const newClaim = "#/discharge/new" + (prior ? "?case=" + encodeURIComponent(prior) : "");
  return <>
    <div className="desk-heading"><div>
      <h1>Discharge claims</h1>
      <p>Review final bills, resolve discrepancies and track payer replies.</p>
    </div><a href={newClaim} className="primary"><Plus size={17} />Open a discharge claim</a></div>
    <div className="queue-switches" role="group" aria-label="Filter claims by work queue">
      {queues.map(({ id, label, icon: Icon }) => <button type="button" className={"queue-switch queue-" + id}
        key={id} aria-pressed={queue === id} onClick={() => setQueue(queue === id ? "all" : id)}>
        <span className="queue-icon"><Icon size={20} /></span>
        <span className="queue-label">{label}</span><strong>{result.data?.counts[id] ?? "…"}</strong>
      </button>)}
    </div>
    <section className="work-inbox" aria-label="Discharge claim worklist">
      <div className="inbox-bar"><div className="inbox-name">
        <span className="inbox-icon"><ListFilter size={19} /></span>
        <h2>{queue === "all" ? "All claims" : queues.find(q => q.id === queue)?.label}</h2>
        <span className="quantity" aria-live="polite">{data?.total ?? "…"}</span>
        {queue !== "all" && <button className="icon-button" onClick={() => setQueue("all")} aria-label="Clear work queue filter"><X size={14} /></button>}
      </div><label className="queue-search"><Search size={16} /><input type="search" aria-label="Find a claim"
        value={search} maxLength={250} onChange={e => setSearch(e.target.value)} placeholder="Search claims…" /></label></div>
      {current?.error ? <div className="queue-empty" role="alert"><p>{current.error}</p>
        <button className="secondary" onClick={() => setRetry(n => n + 1)}>Try again</button></div>
      : !data ? <div className="queue-empty" role="status">Loading claims…</div>
      : data.items.length > 0 ? <div className="claim-collection" role="list">
        <div className="queue-columns" aria-hidden="true"><span>Encounter</span><span>Payer</span><span>Final bill</span><span>Review status</span><span /></div>
        {data.items.map(c => <div role="listitem" key={c.id}><a className="claim-entry" href={claimHref(c.id)}>
          <span className="entry-subject"><span className="entry-icon"><ReceiptText size={18} /></span>
            <span><strong>{c.procedure}</strong><small>{c.encounter || c.member} · {displayDate(c.discharge_date)}</small></span></span>
          <span className="entry-payer"><strong>{c.insurer || "Unrecorded payer"}</strong>
            <small>{claimPayerStatus(c.insurer_status || "not_sent")}</small></span>
          <span className="entry-amount">{minorMoney(c.bill_total_minor, c.currency)}</span>
          <ClaimPill status={c.status} /><ArrowRight className="entry-arrow" size={15} />
        </a></div>)}
      </div> : <div className="queue-empty"><span className="empty-symbol">{data.counts.all ? <Filter size={24} /> : <Inbox size={27} />}</span>
        <h3>{data.counts.all ? "No matching claims" : "Your discharge queue is empty"}</h3>
        <p>{data.counts.all ? "Change the search or clear the queue filter." : "Open a claim with the records available. Missing documents can be added later."}</p>
        {data.counts.all ? <button type="button" className="text-action" onClick={() => { setSearch(""); setFilter({ queue: "all", search: "", page: 1 }); }}>Clear filters</button>
          : <a className="text-action" href={newClaim}>Open the first claim <ArrowRight size={14} /></a>}
      </div>}
      {data && data.total > data.page_size && <nav className="claim-pages" aria-label="Discharge claim pages">
        <span aria-live="polite">Page {page} of {Math.ceil(data.total / data.page_size)}</span>
        <button type="button" className="secondary" disabled={page === 1}
          onClick={() => setFilter(prev => ({ ...prev, page: prev.page - 1 }))}>Previous</button>
        <button type="button" className="secondary" disabled={page * data.page_size >= data.total}
          onClick={() => setFilter(prev => ({ ...prev, page: prev.page + 1 }))}>Next</button>
      </nav>}
    </section>
    {mode === "local" && <section className="practice-panel" aria-label="Synthetic discharge examples">
      <div className="practice-lead"><span className="practice-symbol"><FileSearch size={26} /></span><div>
        <p className="section-label">Practice case</p><h2>Find a duplicate bill line</h2>
        <p>Compare a fictional pharmacy charge with the original invoice, then check the corrected bill.</p></div></div>
      <button className="practice-start" disabled={!!pending} onClick={() => void start("duplicate_line")}><Play size={14} />
        {pending === "duplicate_line" ? "Opening…" : "Try duplicate bill example"}</button>
      <details className="practice-options"><summary><Layers size={14} />More discharge examples</summary><div className="actions">
        <label className="stack-field">Example<select value={example} onChange={e => setExample(e.target.value)}>
          {Object.entries(examples).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
        </select></label><button className="secondary" disabled={!!pending} onClick={() => void start(example)}>Open example</button>
      </div></details>
      {error && <p className="error-message" role="alert">{error}</p>}
    </section>}
  </>;
}
