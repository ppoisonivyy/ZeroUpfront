import { useEffect, useRef, useState } from "react";
import {
  ArrowRight, BadgeCheck, CircleAlert, ClipboardList, FileSearch, Filter,
  Inbox, Landmark, Layers, ListFilter, Play, Plus, ReceiptText, Search, Send, X,
} from "lucide-react";
import { useStaffSession } from "./Auth";
import { api, displayDate } from "./api";
import { claimHref, claimPayerStatus, claimStatus, minorMoney, pattayaSteps, type DischargeClaim, type DischargeQueue, type DischargeWorklist, type PattayaSettlementSummary } from "./dischargeApi";

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

function settlementLabel(settlement: PattayaSettlementSummary) {
  const task = pattayaSteps[settlement.next_action];
  return settlement.outstanding_minor ? task + " · " + minorMoney(settlement.outstanding_minor, "THB") : task;
}

// Keep searches within the signed-in discharge desk; they may contain patient identifiers.
export function useDischargeListView() {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState({ queue: "all" as DischargeQueue, search: "", page: 1 });
  const returnToRow = useRef<string | null>(null);
  return { search, setSearch, filter, setFilter, returnToRow };
}

export function DischargeList({ prior, view }: { prior?: string; view: ReturnType<typeof useDischargeListView> }) {
  const { mode } = useStaffSession();
  const [example, setExample] = useState("duplicate_line");
  const [pending, setPending] = useState("");
  const [error, setError] = useState<{ scenario: string; message: string } | null>(null);
  const { search, setSearch, filter, setFilter, returnToRow } = view;
  const listHeading = useRef<HTMLHeadingElement>(null);
  const initialFocus = useRef(document.activeElement);
  const [retry, setRetry] = useState(0);
  const [result, setResult] = useState<{ key: string; data?: DischargeWorklist; error?: string }>({ key: "" });
  const { queue, page } = filter;
  const { search: submittedSearch } = filter;
  const key = JSON.stringify([queue, submittedSearch, page, retry]);
  useEffect(() => {
    const term = search.trim();
    if (term === filter.search) return;
    const timer = window.setTimeout(() => setFilter(prev => ({ ...prev, search: term, page: 1 })), 180);
    return () => window.clearTimeout(timer);
  }, [search, filter.search]);
  useEffect(() => {
    const abort = new AbortController();
    const url = "/api/discharge/worklist";
    const request = submittedSearch
      ? api(url + "/search", {
          method: "POST", signal: abort.signal, headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ queue, page, search: submittedSearch }),
        })
      : api(url + "?" + new URLSearchParams({ queue, page: String(page) }), { signal: abort.signal });
    request
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
  }, [queue, submittedSearch, page, key]);
  const current = result.key === key && filter.search === search.trim() ? result : undefined;
  const data = current?.data;
  useEffect(() => {
    const id = returnToRow.current;
    if (!data || !id) return;
    returnToRow.current = null;
    if (document.activeElement === document.body || document.activeElement === initialFocus.current) {
      const row = document.getElementById("claim-entry-" + id);
      (row || listHeading.current)?.focus();
    }
  }, [data, returnToRow]);
  const setQueue = (next: DischargeQueue) => setFilter(prev => ({ ...prev, queue: next, page: 1 }));
  async function start(scenario: string) {
    if (pending) return;
    setPending(scenario); setError(null);
    try {
      const claim: DischargeClaim = await (await api("/api/discharge/examples/" + scenario, { method: "POST" })).json();
      location.hash = claimHref(claim.id);
    } catch (err) {
      setError({ scenario, message: err instanceof Error ? err.message : "Could not create the practice claim." });
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
    {mode === "local" && <section className="practice-panel pattaya-launch" aria-label="Pattaya settlement example">
      <div className="practice-lead"><span className="practice-symbol"><Landmark size={25} /></span><div>
        <p className="section-label">Practice case · Foreign exchange</p><h2>Pattaya hospital settlement</h2>
        <p>Fund a THB 239,000 insurer guarantee and reconcile the hospital’s bank credit.</p></div></div>
      <button type="button" className="practice-start" disabled={!!pending} onClick={() => void start("pattaya_fx")}>
        <Play size={14} />{pending === "pattaya_fx" ? "Opening…" : "Open Pattaya case"}</button>
      {error?.scenario === "pattaya_fx" && <p className="error-message" role="alert">{error.message}</p>}
    </section>}
    <section className="work-inbox" aria-label="Discharge claim worklist">
      <div className="inbox-bar"><div className="inbox-name">
        <span className="inbox-icon"><ListFilter size={19} /></span>
        <h2 ref={listHeading} tabIndex={-1}>{queue === "all" ? "All claims" : queues.find(q => q.id === queue)?.label}</h2>
        <span className="quantity" aria-live="polite">{data?.total ?? "…"}</span>
        {queue !== "all" && <button className="icon-button" onClick={() => setQueue("all")} aria-label="Clear work queue filter"><X size={14} /></button>}
      </div><label className="queue-search"><Search size={16} /><input type="search" aria-label="Find a claim"
        value={search} maxLength={250} onChange={e => setSearch(e.target.value)} placeholder="Search claims…" /></label></div>
      {current?.error ? <div className="queue-empty" role="alert"><p>{current.error}</p>
        <button className="secondary" onClick={() => setRetry(n => n + 1)}>Try again</button></div>
      : !data ? <div className="queue-empty" role="status">Loading claims…</div>
      : data.items.length > 0 ? <div className="claim-collection" role="list">
        <div className="queue-columns" aria-hidden="true"><span>Encounter</span><span>Payer</span><span>Final bill</span><span>Review status</span><span /></div>
        {data.items.map(c => <div role="listitem" key={c.id}><a className="claim-entry" href={claimHref(c.id)} id={"claim-entry-" + c.id}
          onClick={event => {
            if (!event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) returnToRow.current = c.id;
          }}>
          <span className="entry-subject"><span className="entry-icon"><ReceiptText size={18} /></span>
            <span><strong>{c.procedure}</strong><small>{c.encounter || c.member} · {displayDate(c.discharge_date)}</small></span></span>
          <span className="entry-payer"><strong>{c.insurer || "Unrecorded payer"}</strong>
            <small>{c.pattaya_settlement ? settlementLabel(c.pattaya_settlement) : claimPayerStatus(c.insurer_status || "not_sent")}</small></span>
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
      {error && error.scenario !== "pattaya_fx" && <p className="error-message" role="alert">{error.message}</p>}
    </section>}
  </>;
}
