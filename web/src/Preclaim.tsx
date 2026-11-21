import { useCallback, useRef, useState } from "react";
import { ArrowRight, BookOpen, Check, ChevronRight, CircleAlert, ClipboardList, FileText, Inbox, Paperclip, Send } from "lucide-react";
import { api, RequestError, type Source } from "./api";
import { useResource } from "./useResource";
import { SourceView, useSourceNavigation } from "./SourceView";
import { useStaffSession } from "./Auth";
import { PreclaimQuestions, handoffTime, type CitedQuestion } from "./PreclaimQuestions";
import "./preclaim.css";

type Stage = "needs_documents" | "ready_for_review" | "staff_reviewed" | "waiting_for_insurer" | "hospital_reply_needed" | "hospital_replied";
type Rule = { clause?: string; quote: string; page: number; verified: boolean; source_url: string };
type Packet = {
  id: string; revision: number; current_revision: number; patient: string; member: string;
  form_edition: string; reviewer: string | null; procedure: string; insurer: string; total: number; currency: string; status: Stage;
  gap: (Rule & { code: string; title: string }) | null; rule: Rule;
  submitted_at: string | null; questions: CitedQuestion[];
  sources: Source[]; draft_url: string | null; submitted_revision: number | null; simulation: boolean;
};
const stages: Record<Stage, string> = {
  needs_documents: "Needs documents", ready_for_review: "Ready for staff review",
  staff_reviewed: "Staff reviewed", waiting_for_insurer: "Waiting for insurer",
  hospital_reply_needed: "Hospital reply needed", hospital_replied: "Hospital replied",
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
              <span className="pill good"><i />{packet.status === "waiting_for_insurer" ? "Received" : stages[packet.status]} · R{packet.submitted_revision}</span><ChevronRight size={17} />
            </a>)}</div>}
    </section>
  </>;
}

export function PayerCase({ id, revision, insurer }: { id: string; revision?: number; insurer: boolean }) {
  const root = (insurer ? "/api/insurer/preclaims/" : "/api/preclaims/") + encodeURIComponent(id);
  const [epoch, setEpoch] = useState(0);
  const { data, error, status } = useResource<Packet>(root + (revision ? "?revision=" + revision : ""), epoch);
  const refresh = () => setEpoch(n => n + 1);
  if (status === 404) return <section className="state-box" aria-label="Unavailable case">
    <h1>Case unavailable</h1><p>This request or revision is unavailable in your workspace.</p>
    <a className="secondary" href={insurer ? "#/insurer" : "#/cases"}>{insurer ? "Open insurer inbox" : "Open hospital queue"}</a>
  </section>;
  return data ? <PacketView key={root + String(revision || "")} packet={data} root={root} insurer={insurer} refresh={refresh} />
    : <Load error={error} refresh={refresh} />;
}

type View = "rule" | "draft" | "example" | `file:${string}`;
function PacketView({ packet: initial, root, insurer, refresh }: { packet: Packet; root: string; insurer: boolean; refresh: () => void }) {
  const [packet, setPacket] = useState(initial);
  const [view, setView] = useState<View>(insurer && initial.draft_url ? "draft" : "rule");
  const [citedSource, setCitedSource] = useState<Source | null>(null);
  const [reviewedForm, setReviewedForm] = useState(false);
  const formReady = useCallback(() => setReviewedForm(true), []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [stale, setStale] = useState(false);
  const pending = useRef(false);
  const navigation = useSourceNavigation();
  const rule = packet.rule;
  const historical = packet.revision < packet.current_revision;
  const waiting = packet.submitted_revision !== null;
  const lastQuestion = packet.questions.at(-1);
  const handoffAt = lastQuestion?.replied_at || lastQuestion?.asked_at || packet.submitted_at;
  const nextDesk = packet.status === "hospital_reply_needed" ? "Hospital IPD" : packet.insurer;
  const ruleSource: Source = { role: "policy", label: "Insurer rule " + (rule.clause || ""), url: rule.source_url, page: rule.page, quote: rule.verified ? rule.quote : "", method: rule.verified ? "digital" : "unverified" };
  const draftSource: Source | null = packet.draft_url ? {
    role: "draft", label: packet.insurer + " form " + packet.form_edition, url: packet.draft_url, page: 1, quote: "",
    recordedSummary: waiting ? "The request form submitted by the hospital." : "Inpatient request prepared for staff review.",
  } : null;
  const example: Source = { role: "example", label: "Signed sample report", url: root + "/report-example", page: 1, quote: "", recordedSummary: "Synthetic signed report available to attach to this case." };
  const source = citedSource || (view === "draft" ? draftSource : view === "example" && !insurer ? example : packet.sources.find(s => "file:" + s.role === view)) || ruleSource;
  function show(next: View, trigger: HTMLButtonElement) {
    setCitedSource(null);
    setView(next);
    navigation.open(trigger);
  }
  async function save(action: string, payload: Record<string, unknown>) {
    if (pending.current || historical || stale) return false;
    pending.current = true; setBusy(true); setError("");
    try {
      const response = await api(root + "/" + action, { method: "POST", headers: {
        "Content-Type": "application/json", "If-Match": '"' + packet.revision + '"',
      }, body: JSON.stringify(payload) });
      const next: Packet = await response.json();
      setPacket(next);
      if (action === "attach-report") {
        setView("file:report"); setReviewedForm(false);
      } else if (action === "review" || action === "submit") setView("draft");
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "The action could not be saved.");
      setStale(e instanceof RequestError && (e.status === 409 || e.status === 412));
      return false;
    } finally { pending.current = false; setBusy(false); }
  }
  function advance(action: "attach-report" | "review" | "submit") {
    return save(action, { confirmed: true });
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
              : <p>{waiting ? (packet.status === "hospital_reply_needed" ? "Hospital IPD can answer the cited question below." :
                packet.status === "hospital_replied" ? "The insurer can review the hospital’s answer beside the cited document." : "The submitted request is awaiting the insurer’s review.") :
                packet.status === "staff_reviewed" ? "A staff member reviewed the insurer form. The hospital can now send the packet." : "The signed report is attached. Open the insurer form and check the request before sending."}</p>}
            {waiting && <p className="handoff-line">{nextDesk} · Last handoff {handoffTime(handoffAt)}</p>}
            {waiting && !historical && ((insurer && packet.status === "hospital_reply_needed") ||
              (!insurer && packet.status !== "hospital_reply_needed")) &&
              <button type="button" className="text-action" onClick={refresh}>Check for an update</button>}
            {packet.gap?.code === "missing_signed_report" && <p>Treating physician signs the replacement. Hospital IPD attaches it for recheck.</p>}
            {packet.gap && <button className="text-action" onClick={e => show("rule", e.currentTarget)}><BookOpen size={15}/> View cited clause</button>}
          </section>
          {!insurer && !historical && packet.status === "needs_documents" && <div className="preclaim-actions">
            <button className="secondary" onClick={e => show("example", e.currentTarget)}><FileText size={16}/> Preview signed sample</button>
            <button className="primary" disabled={busy || stale} onClick={() => void advance("attach-report")}><Paperclip size={16}/> Attach signed sample report</button>
          </div>}
          {draftSource && <div className="preclaim-actions">
            <button className="secondary" onClick={e => show("draft", e.currentTarget)}><FileText size={16}/> {waiting ? "View submitted form" : "Review insurer form"}</button>
            {!insurer && !historical && packet.status === "ready_for_review" && <button className="primary" disabled={!reviewedForm || !rule.verified || busy || stale} onClick={() => void advance("review")}><Check size={16}/> Mark draft reviewed</button>}
            {!insurer && !historical && packet.status === "staff_reviewed" && <button className="primary" disabled={busy || stale} onClick={() => void advance("submit")}><Send size={16}/> Submit to insurer desk</button>}
          </div>}
          {waiting && !historical && draftSource && <PreclaimQuestions
            questions={packet.questions} revision={packet.revision} insurer={insurer} busy={busy || stale}
            sources={[...packet.sources, { ...draftSource, role: "request" }]} send={save}
            inspect={(s, trigger) => {
              show(s.role === "request" ? "draft" : `file:${s.role}`, trigger);
              setCitedSource(s);
            }}/>}
          {error && <div role="alert" className="error-message">{error} {stale && <button onClick={refresh}>Reload current request</button>}</div>}
          <h3 className="packet-files-title">Packet documents</h3>
          <div className="packet-files">
            {packet.sources.map(s => <button key={s.role} onClick={e => show(`file:${s.role}`, e.currentTarget)} aria-pressed={view === "file:" + s.role}>
              <FileText size={16}/><span>{s.label}</span><ArrowRight size={15}/>
            </button>)}
          </div>
        </div>
      </section>
      <SourceView key={packet.status + source.url + ":" + source.page} source={source} revision={packet.revision} historical={historical || insurer} onReturn={navigation.onReturn} onReady={view === "draft" ? formReady : undefined} />
    </div>
  </>;
}
