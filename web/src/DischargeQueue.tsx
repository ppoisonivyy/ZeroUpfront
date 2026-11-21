import { useState } from "react";
import {
  ArrowRight, BadgeCheck, CircleAlert, ClipboardList, FileSearch, Filter,
  Inbox, Layers, ListFilter, Play, Plus, ReceiptText, Search, Send, X,
} from "lucide-react";
import { useStaffSession } from "./Auth";
import { api, displayDate } from "./api";
import { claimHref, claimPayerStatus, claimStatus, minorMoney, type DischargeClaim } from "./dischargeApi";

const examples = {
  duplicate_line: "Duplicate bill line", aligned: "Aligned discharge packet",
  over_cap: "Bill exceeds written cap", missing_records: "Missing supporting records",
  unapproved_procedure: "Unapproved procedure", total_mismatch: "Invoice totals disagree",
  orphan_credit: "Unmatched credit", share_mismatch: "Patient share differs",
  member_mismatch: "Member mismatch", stay_extension: "Stay exceeds recorded dates",
  late_reply: "Late payer reply", mixed_currency: "Mixed currencies",
  unreadable_summary: "Unreadable discharge summary",
};
type Queue = "all" | "needs" | "ready" | "payer";
const queues = [
  { id: "needs", label: "Needs investigation", icon: CircleAlert },
  { id: "ready", label: "Ready for review", icon: BadgeCheck },
  { id: "payer", label: "Payer correspondence", icon: Send },
] as const;
function belongsTo(claim: DischargeClaim, queue: Queue) {
  if (queue === "needs") return claim.status === "needs_review";
  if (queue === "ready") return ["ready_for_review", "ready_for_staff_review"].includes(claim.status);
  if (queue === "payer") return !!claim.insurer_status && claim.insurer_status !== "not_sent";
  return true;
}
function actionOrder(claim: DischargeClaim) {
  if (claim.status === "needs_review" || claim.insurer_status === "query") return 0;
  if (belongsTo(claim, "ready")) return 1;
  return 2;
}
export function ClaimPill({ status }: { status: string }) {
  const Icon = status === "needs_review" ? CircleAlert : status === "staff_reviewed" ? BadgeCheck : ClipboardList;
  return <span className={"claim-pill state-" + status}><Icon size={13} />{claimStatus(status)}</span>;
}

export function DischargeList({ rows, prior }: { rows: DischargeClaim[]; prior?: string }) {
  const { mode } = useStaffSession();
  const [example, setExample] = useState("duplicate_line");
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [queue, setQueue] = useState<Queue>("all");
  const term = search.trim().toLowerCase();
  const filtered = rows.filter(c => belongsTo(c, queue) && [c.id, c.encounter, c.member, c.procedure, c.insurer]
    .some(value => value?.toLowerCase().includes(term)))
    .sort((a, b) => actionOrder(a) - actionOrder(b) || a.discharge_date.localeCompare(b.discharge_date) || a.id.localeCompare(b.id));
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
        <span className="queue-label">{label}</span><strong>{rows.filter(c => belongsTo(c, id)).length}</strong>
      </button>)}
    </div>
    <section className="work-inbox" aria-label="Discharge claim worklist">
      <div className="inbox-bar"><div className="inbox-name">
        <span className="inbox-icon"><ListFilter size={19} /></span>
        <h2>{queue === "all" ? "All claims" : queues.find(q => q.id === queue)?.label}</h2>
        <span className="quantity" aria-live="polite">{filtered.length}</span>
        {queue !== "all" && <button className="icon-button" onClick={() => setQueue("all")} aria-label="Clear work queue filter"><X size={14} /></button>}
      </div><label className="queue-search"><Search size={16} /><input type="search" aria-label="Find a claim"
        value={search} onChange={e => setSearch(e.target.value)} placeholder="Search claims…" /></label></div>
      {filtered.length > 0 ? <div className="claim-collection" role="list">
        <div className="queue-columns" aria-hidden="true"><span>Encounter</span><span>Payer</span><span>Final bill</span><span>Review status</span><span /></div>
        {filtered.map(c => <div role="listitem" key={c.id}><a className="claim-entry" href={claimHref(c.id)}>
          <span className="entry-subject"><span className="entry-icon"><ReceiptText size={18} /></span>
            <span><strong>{c.procedure}</strong><small>{c.encounter || c.member} · {displayDate(c.discharge_date)}</small></span></span>
          <span className="entry-payer"><strong>{c.insurer || "Unrecorded payer"}</strong>
            <small>{claimPayerStatus(c.insurer_status || "not_sent")}</small></span>
          <span className="entry-amount">{minorMoney(c.bill_total_minor, c.currency)}</span>
          <ClaimPill status={c.status} /><ArrowRight className="entry-arrow" size={15} />
        </a></div>)}
      </div> : <div className="queue-empty"><span className="empty-symbol">{rows.length ? <Filter size={24} /> : <Inbox size={27} />}</span>
        <h3>{rows.length ? "No matching claims" : "Your discharge queue is empty"}</h3>
        <p>{rows.length ? "Change the search or clear the queue filter." : "Open a claim with the records available. Missing documents can be added later."}</p>
        {rows.length ? <button type="button" className="text-action" onClick={() => { setSearch(""); setQueue("all"); }}>Clear filters</button>
          : <a className="text-action" href={newClaim}>Open the first claim <ArrowRight size={14} /></a>}
      </div>}
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
