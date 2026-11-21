import { useCallback, useRef, useState } from "react";
import { ArrowRight, BookOpen, Check, ChevronRight, CircleAlert, ClipboardList, FileText, Inbox, Paperclip, Send } from "lucide-react";
import { api, RequestError, type Source } from "./api";
import { useResource } from "./useResource";
import { SourceView } from "./SourceView";
import { useStaffSession } from "./Auth";
import "./preclaim.css";

type Stage = "needs_documents" | "ready_for_review" | "staff_reviewed" | "waiting_for_insurer";
type Rule = { clause?: string; quote: string; page: number; verified: boolean; source_url: string };
type Packet = {
  id: string; revision: number; current_revision: number; patient: string; member: string;
  form_edition: string; reviewer: string | null; procedure: string; insurer: string; total: number; currency: string; status: Stage;
  gap: (Rule & { code: string; title: string }) | null; rule: Rule;
  sources: Source[]; draft_url: string | null; submitted_revision: number | null; simulation: boolean;
};
const stages: Record<Stage, string> = {
  needs_documents: "Needs documents", ready_for_review: "Ready for staff review",
  staff_reviewed: "Staff reviewed", waiting_for_insurer: "Waiting for insurer",
};
function amount(packet: Packet) {
  return packet.currency + " " + new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(packet.total);
}
function Load({ error, refresh }: { error?: string; refresh: () => void }) {
  return <div className="state-box" role={error ? "alert" : "status"}>
    <p>{error || "Loading the request…"}</p>
    {error && <button className="secondary" onClick={refresh}>Try again</button>}
  </div>;
}

export function InsurerInbox() {
  const { insurer } = useStaffSession();
  const [epoch, setEpoch] = useState(0);
  const { data, error } = useResource<Packet[]>("/api/insurer/preclaims", epoch);
  return <>
    <div className="page-title desk-heading"><div>
      <p className="section-label">{insurer || "Payer workspace"}</p>
      <h1>Insurer inbox</h1><p>Inpatient requests submitted by hospital staff for your review.</p>
    </div></div>
    <section className="panel">
      <div className="panel-heading"><h2><Inbox size={18} />Submitted requests</h2>
        {data && <span className="small">{data.length} {data.length === 1 ? "request" : "requests"}</span>}
      </div>
      {!data ? <Load error={error} refresh={() => setEpoch(n => n + 1)} /> :
        data.length === 0 ? <p className="empty-view">No hospital requests have been submitted to your desk.</p> :
          <div className="worklist">{data.map(packet =>
            <a key={packet.id} className="case-row" href={"#/insurer/" + encodeURIComponent(packet.id) + "?revision=" + packet.submitted_revision}>
              <span className="case-code">{packet.id}</span>
              <span className="row-detail"><strong>{packet.patient} · {packet.procedure}</strong><small>{packet.insurer} · {amount(packet)}</small></span>
              <span className="pill good"><i />Received · R{packet.submitted_revision}</span><ChevronRight size={17} />
            </a>)}</div>}
    </section>
  </>;
}

export function PayerCase({ id, revision, insurer }: { id: string; revision?: number; insurer: boolean }) {
  const root = (insurer ? "/api/insurer/preclaims/" : "/api/preclaims/") + encodeURIComponent(id);
  const [epoch, setEpoch] = useState(0);
  const { data, error } = useResource<Packet>(root + (revision ? "?revision=" + revision : ""), epoch);
  const refresh = () => setEpoch(n => n + 1);
  return data ? <PacketView key={root + String(revision || "")} packet={data} root={root} insurer={insurer} refresh={refresh} />
    : <Load error={error} refresh={refresh} />;
}

type View = "rule" | "draft" | "example" | `file:${string}`;
function PacketView({ packet: initial, root, insurer, refresh }: { packet: Packet; root: string; insurer: boolean; refresh: () => void }) {
  const [packet, setPacket] = useState(initial);
  const [view, setView] = useState<View>(insurer && initial.draft_url ? "draft" : "rule");
  const [reviewedForm, setReviewedForm] = useState(false);
  const formReady = useCallback(() => setReviewedForm(true), []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [stale, setStale] = useState(false);
  const pending = useRef(false);
  const rule = packet.rule;
  const historical = packet.revision < packet.current_revision;
  const waiting = packet.status === "waiting_for_insurer";
  const ruleSource: Source = { role: "policy", label: "Insurer rule " + (rule.clause || ""), url: rule.source_url, page: rule.page, quote: rule.verified ? rule.quote : "", method: rule.verified ? "digital" : "unverified" };
  const draftSource: Source | null = packet.draft_url ? {
    role: "draft", label: packet.insurer + " form " + packet.form_edition, url: packet.draft_url, page: 1, quote: "",
    recordedSummary: waiting ? "The request form submitted by the hospital." : "Inpatient request prepared for staff review.",
  } : null;
  const example: Source = { role: "example", label: "Signed sample report", url: root + "/report-example", page: 1, quote: "", recordedSummary: "Synthetic signed report available to attach to this case." };
  const source = (view === "draft" ? draftSource : view === "example" && !insurer ? example : packet.sources.find(s => "file:" + s.role === view)) || ruleSource;
  function show(next: View) {
    setView(next);
    if (window.matchMedia("(max-width: 900px)").matches)
      requestAnimationFrame(() => document.getElementById("source-view")?.scrollIntoView({ block: "start" }));
  }
  async function advance(action: "attach-report" | "review" | "submit") {
    if (pending.current || insurer || historical || stale) return;
    pending.current = true; setBusy(true); setError("");
    try {
      const response = await api(root + "/" + action, { method: "POST", headers: {
        "Content-Type": "application/json", "If-Match": '"' + packet.revision + '"',
      }, body: JSON.stringify({ confirmed: true }) });
      const next: Packet = await response.json();
      setPacket(next);
      if (action === "attach-report") {
        setView("file:report"); setReviewedForm(false);
      } else setView("draft");
    } catch (e) {
      setError(e instanceof Error ? e.message : "The action could not be saved.");
      setStale(e instanceof RequestError && (e.status === 409 || e.status === 412));
    } finally { pending.current = false; setBusy(false); }
  }
  return <>
    <header className="page-title desk-heading preclaim-heading"><div>
      <p className="section-label">{packet.id} · Inpatient preauthorization {packet.simulation && "· Synthetic case"}</p>
      <h1>{packet.patient}</h1>
      <p>{packet.procedure}</p>
    </div><div className="preclaim-total"><strong>{amount(packet)}</strong><span>Estimated treatment cost</span></div></header>
    <div className="workspace-grid preclaim-grid">
      <section className="panel preclaim-file" aria-label="Request review">
        <div className="panel-heading"><h2><ClipboardList size={18}/>Request review</h2><span className="small">R{packet.revision}</span></div>
        <div className="preclaim-body">
          <div className="preclaim-metadata"><div><span>Insurer</span><strong>{packet.insurer}</strong></div><div><span>Member</span><strong>{packet.member}</strong></div></div>
          <section className={"preclaim-next " + (packet.gap ? "needs-document" : "")} aria-live="polite">
            <h3>{packet.gap ? <CircleAlert size={18}/> : <Check size={18}/>} {stages[packet.status]}</h3>
            {packet.gap ? <><strong>{packet.gap.title}</strong><p>{rule.clause || "Insurer rule"} · Page {rule.page} · {rule.verified ? "Quote verified against the original" : "Quote requires staff verification"}</p></>
              : <p>{waiting ? (insurer ? "The hospital sent this revision to your desk. The payer decision is pending." : "Submitted to the shared insurer desk. A payer decision is pending.") :
                packet.status === "staff_reviewed" ? "A staff member reviewed the insurer form. The hospital can now send the packet." : "The signed report is attached. Open the insurer form and check the request before sending."}</p>}
            {packet.gap && <button className="text-action" onClick={() => show("rule")}><BookOpen size={15}/> View cited clause</button>}
          </section>
          {!insurer && !historical && packet.status === "needs_documents" && <div className="preclaim-actions">
            <button className="secondary" onClick={() => show("example")}><FileText size={16}/> Preview signed sample</button>
            <button className="primary" disabled={busy || stale} onClick={() => void advance("attach-report")}><Paperclip size={16}/> Attach signed sample report</button>
          </div>}
          {draftSource && <div className="preclaim-actions">
            <button className="secondary" onClick={() => show("draft")}><FileText size={16}/> {waiting ? "View submitted form" : "Review insurer form"}</button>
            {!insurer && !historical && packet.status === "ready_for_review" && <button className="primary" disabled={!reviewedForm || !rule.verified || busy || stale} onClick={() => void advance("review")}><Check size={16}/> Mark draft reviewed</button>}
            {!insurer && !historical && packet.status === "staff_reviewed" && <button className="primary" disabled={busy || stale} onClick={() => void advance("submit")}><Send size={16}/> Submit to insurer desk</button>}
          </div>}
          {error && <div role="alert" className="error-message">{error} {stale && <button onClick={refresh}>Reload current request</button>}</div>}
          <h3 className="packet-files-title">Packet documents</h3>
          <div className="packet-files">
            {packet.sources.map(s => <button key={s.role} onClick={() => show(`file:${s.role}`)} aria-pressed={view === "file:" + s.role}>
              <FileText size={16}/><span>{s.label}</span><ArrowRight size={15}/>
            </button>)}
          </div>
        </div>
      </section>
      <SourceView key={packet.status + source.url} source={source} revision={packet.revision} historical={historical || insurer} onReady={view === "draft" ? formReady : undefined} />
    </div>
  </>;
}
