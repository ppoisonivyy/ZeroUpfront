import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowLeft,
  BookOpen,
  ChevronDown,
  Hospital,
  LogOut,
  ArrowLeftRight,
  Building2,
  Check,
  ChevronRight,
  CircleAlert,
  ClipboardList,
  Download,
  FileText,
  FolderOpen,
  History,
  Layers,
  LayoutList,
  ListChecks,
  Plus,
  RefreshCw,
  ShieldCheck,
  Upload,
} from "lucide-react";
import type { CaseDetail, CaseSummary, PacketStatus } from "./api";
import { api, blocked, caseHref, casePath, displayDate, hospitalPrefix, money, statuses } from "./api";
import { ApproveDraft, ReplaceEstimate } from "./ReviewForms";
import { SourceView } from "./SourceView";
import { AttachmentList } from "./Attachments";
import { NewCase } from "./CaseIntake";
import { CaseWorkflow, payerStatus } from "./CaseWorkflow";
import { EvidenceReview } from "./EvidenceReview";
import { AuthGate, useStaffSession } from "./Auth";
import { FinanceLedger } from "./FinanceLedger";
import { OperationalHolds } from "./OperationalHolds";
import { useResource } from "./useResource";
import { PayerCase, InsurerInbox } from "./Preclaim";
import "./style.css";
import "./caseflow.css";
import "./workspace.css";

const Discharge = lazy(() =>
  import("./Discharge").then((m) => ({ default: m.Discharge })),
);
type Route = {
  id: string;
  rev?: number;
  create?: boolean;
  preclaim?: boolean;
  inbox?: boolean;
  discharge?: boolean;
  prior?: string;
};
function readRoute(): Route {
  const pathAndSearch =
    location.hash.slice(1) || (location.pathname.slice(hospitalPrefix.length) || "/") + location.search;
  const [path, search] = pathAndSearch.split("?");
  if (path === "/") return { id: "", discharge: true };
  const params = new URLSearchParams(search);
  const revision = Number(params.get("revision"));
  const rev =
    Number.isSafeInteger(revision) && revision > 0 ? revision : undefined;
  const discharge = path.match(/^\/discharge(?:\/([a-zA-Z0-9_-]+))?$/);
  if (discharge)
    return {
      discharge: true,
      id: discharge[1] || "",
      prior: params.get("case") || undefined,
      rev,
    };
  const preclaim = path.match(/^\/(preclaims|insurer)(?:\/([a-zA-Z0-9_-]+))?$/);
  if (preclaim) return { id: preclaim[2] || "", preclaim: !!preclaim[2], inbox: preclaim[1] === "insurer", rev };
  if (path === "/new") return { id: "", create: true };
  const id = path.match(/^\/cases\/([a-zA-Z0-9_-]+)$/)?.[1] || "";
  return { id, rev };
}
function Pill({ status }: { status: PacketStatus }) {
  return (
    <span className={"pill " + (blocked(status) ? "warning" : "good")}>
      <i />
      {statuses[status] || status}
    </span>
  );
}
function LoadState({ error, retry }: { error?: string; retry: () => void }) {
  return (
    <div className="state-box" role={error ? "alert" : "status"}>
      {error ? (
        <>
          <CircleAlert />
          <h2>Unable to load this view</h2>
          <p>{error}</p>
          <button className="secondary" onClick={retry}>
            <RefreshCw size={15} />
            Try again
          </button>
        </>
      ) : (
        <>
          <span className="spinner" />
          <p>Loading case records…</p>
        </>
      )}
    </div>
  );
}
function Worklist({ epoch, retry }: { epoch: number; retry: () => void }) {
  const { data, error } = useResource<CaseSummary[]>("/api/cases", epoch);
  const session = useStaffSession();
  const [example, setExample] = useState("");
  const [exampleError, setExampleError] = useState("");
  const examples = [
    [
      "missing-estimate",
      "Missing itemization",
      "Find the missing service prices and correct the estimate.",
    ],
    [
      "possible-exclusion",
      "Possible exclusion",
      "Compare the stated treatment purpose with an exclusion.",
    ],
    [
      "partial-guarantee",
      "Partial guarantee",
      "Read the insurer letter and compare its limited amount.",
    ],
    [
      "admission-mismatch",
      "Admission mismatch",
      "Inspect the discrepancy between the planned and admitted encounters.",
    ],
  ];
  async function startExample(key: string) {
    if (example) return;
    setExample(key);
    setExampleError("");
    try {
      const packet: CaseDetail = await (
        await api("/api/examples/" + key, { method: "POST" })
      ).json();
      location.hash = "/cases/" + encodeURIComponent(packet.id);
    } catch (e) {
      setExampleError(
        e instanceof Error ? e.message : "This example could not be created.",
      );
    } finally {
      setExample("");
    }
  }
  const [term, setTerm] = useState("");
  const [filter, setFilter] = useState("all");
  const rows = (data || []).filter((c) => {
    const found = [c.id, c.member, c.procedure, c.insurer, c.patient || ""].some((x) =>
      x.toLocaleLowerCase().includes(term.trim().toLocaleLowerCase()),
    );
    if (!found) return false;
    if (filter === "attention") return blocked(c.status) || !!c.open_hold_count;
    if (filter === "review")
      return c.status === "ready_for_review" && !c.open_hold_count;
    if (filter === "insurer")
      return ["submitted", "query", "supplement_sent"].includes(
        c.insurer_status || "",
      );
    return true;
  });
  return (
    <>
      <div className="page-title desk-heading">
        <div>
          <p className="section-label">Pre-arrival coordination</p>
          <h1>Hospital work queue</h1>
          <p>Inpatient requests for a guarantee of payment.</p>
        </div>
        <a href="#/new" className="primary">
          <Plus size={17} />
          Create a case
        </a>
      </div>
      {session.mode === "local" && (
        <details className="examples">
          <summary>Try a case</summary>
          <p>Open a fresh synthetic example in this local workspace.</p>
          <div className="example-grid">
            {examples.map(([id, title, desc]) => (
              <button
                type="button"
                key={id}
                disabled={!!example}
                onClick={() => void startExample(id)}
              >
                <span className="row-detail">
                  <strong>
                    {example === id ? "Creating example…" : title}
                  </strong>
                  <small>{desc}</small>
                </span>
                <ChevronRight size={16} />
              </button>
            ))}
          </div>
          {exampleError && (
            <p className="error-message" role="alert">
              {exampleError}
            </p>
          )}
        </details>
      )}
      {!data ? (
        <LoadState error={error} retry={retry} />
      ) : (
        <section className="panel">
          <div className="panel-heading">
            <h2>
              <LayoutList size={18} />
              Inpatient cases
            </h2>
            <span className="small">
              {rows.length} of {data.length} cases
            </span>
          </div>
          <div className="worklist-filters">
            <label className="stack-field">
              <span>Find a case</span>
              <input
                type="search"
                placeholder="Patient, case, procedure or insurer"
                value={term}
                onChange={(e) => setTerm(e.target.value)}
              />
            </label>
            <label className="stack-field">
              <span id="queue-filter-label">Work queue</span>
              <select aria-labelledby="queue-filter-label"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              >
                <option value="all">All cases</option>
                <option value="attention">Needs evidence</option>
                <option value="review">Ready for review</option>
                <option value="insurer">Waiting for insurer</option>
              </select>
            </label>
          </div>
          {rows.length === 0 ? (
            <p className="empty-view">
              {data.length
                ? "No cases match these filters."
                : "No cases in the worklist."}
            </p>
          ) : (
            <div className="worklist">
              {rows.map((c) => (
                <a key={c.id} className="case-row" href={c.input_kind === "payer_preclaim" ? "#/preclaims/" + encodeURIComponent(c.id) : caseHref(c.id)}>
                  <span className="case-code" title={c.id}>
                    {c.id.length > 14
                      ? c.id.slice(0, 7) + "…" + c.id.slice(-4)
                      : c.id}
                  </span>
                  <span className="row-detail">
                    <strong>{c.patient ? c.patient + " · " : ""}{c.procedure}</strong>
                    <small>
                      {c.insurer} · {money(c.total)} ·{" "}
                      {displayDate(c.admission_date)}
                    </small>
                    {!!c.open_hold_count && (
                      <small className="queue-hold">
                        {c.open_hold_count} open{" "}
                        {c.open_hold_count === 1 ? "hold" : "holds"}
                      </small>
                    )}
                    {c.input_kind !== "payer_preclaim" && c.insurer_status && c.insurer_status !== "not_sent" && (
                      <small>
                        {c.insurer_status === "submitted" ? "Waiting for insurer" : payerStatus(c.insurer_status)}
                        {c.latest_event_kind === "deposit"
                          ? " · Deposit recorded"
                          : c.latest_event_kind === "admission"
                            ? " · Admission checked"
                            : ""}
                      </small>
                    )}
                  </span>
                  {c.input_kind === "payer_preclaim" && c.workflow_stage === "waiting_for_insurer" ? <span className="pill good"><i />Waiting for insurer</span> : c.input_kind === "payer_preclaim" && c.workflow_stage === "needs_documents" ? <span className="pill warning"><i />Needs documents</span> : <Pill status={c.status} />}
                  <ChevronRight size={17} />
                </a>
              ))}
            </div>
          )}
        </section>
      )}
    </>
  );
}
const headings: Record<PacketStatus, string> = {
  needs_itemization: "Itemized estimate required",
  possible_exclusion: "Possible policy exclusion",
  needs_review: "Packet needs investigation",
  ready_for_review: "Ready for coordinator review",
  staff_reviewed: "Request reviewed by staff",
};
function ExportReview({
  packet,
  pinned,
  onBack,
}: {
  packet: CaseDetail;
  pinned: boolean;
  onBack: () => void;
}) {
  const [exportError, setExportError] = useState("");
  const [exportBusy, setExportBusy] = useState(false);
  const downloadUrl = useRef("");
  useEffect(
    () => () => {
      if (downloadUrl.current) URL.revokeObjectURL(downloadUrl.current);
    },
    [],
  );
  async function exportRequest() {
    setExportBusy(true);
    setExportError("");
    try {
      const response = await api(
        casePath(packet.id) + "/export?revision=" + packet.revision,
      );
      if (!response.headers.get("Content-Type")?.includes("application/pdf"))
        throw new Error(
          "The case service did not return a PDF. Reload the current case and try again.",
        );
      const blob = await response.blob();
      if (downloadUrl.current) URL.revokeObjectURL(downloadUrl.current);
      downloadUrl.current = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = downloadUrl.current;
      anchor.download =
        packet.id + "-preauthorization-R" + packet.revision + ".pdf";
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
    } catch (err) {
      setExportError(
        err instanceof Error
          ? err.message
          : "Export failed. Reload the current revision.",
      );
    } finally {
      setExportBusy(false);
    }
  }
  return (
    <section className="form-wrap">
      <div className="page-title">
        <div>
          <p className="section-label">
            Case {packet.id} · Revision {packet.revision}
          </p>
          <h1>Request and attachments</h1>
          <p>{packet.insurer} · Pre-arrival guarantee-of-payment request</p>
        </div>
      </div>
      <div className="panel form-body">
        <div className="export-heading">
          <h2>Packet details</h2>
          <Pill status={packet.status} />
        </div>
        <dl className="summary-list">
          {[
            ["Member reference", packet.member],
            ["Procedure", packet.procedure],
            ["Total estimate", money(packet.total)],
            ["Staff reviewer", packet.reviewer || "Awaiting review"],
          ].map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
        <AttachmentList packet={packet} />
        <p className="body-copy">
          Payer tracking · {payerStatus(packet.insurer_status)}.
        </p>
        {pinned && (
          <p className="footnote">
            This is a pinned revision.{" "}
            <a href={caseHref(packet.id)}>Open the current case</a> to check
            export eligibility.
          </p>
        )}
        {exportError && (
          <p role="alert" className="error-message">
            {exportError}{" "}
            <button
              className="text-button"
              onClick={() => window.location.reload()}
            >
              Reload case
            </button>
          </p>
        )}
        <div className="actions">
          {!pinned &&
            !packet.open_holds?.length &&
            packet.status === "staff_reviewed" && (
              <button
                className="primary"
                disabled={exportBusy}
                onClick={() => void exportRequest()}
              >
                <Download size={16} />
                {exportBusy ? "Preparing PDF…" : "Download reviewed request"}
              </button>
            )}
          <button className="secondary" onClick={onBack}>
            <ArrowLeft size={16} />
            Back to packet
          </button>
        </div>
      </div>
    </section>
  );
}
function CaseWorkspace({
  packet,
  historical,
  showHistory,
  onReplace,
  onReview,
  onExport,
  onEvidence,
  onWorkflowSaved,
  onReload,
  notice,
}: {
  packet: CaseDetail;
  historical: boolean;
  showHistory: () => void;
  onReplace: () => void;
  onReview: () => void;
  onExport: () => void;
  onEvidence: () => void;
  onWorkflowSaved: () => void;
  onReload: () => void;
  notice: string;
}) {
  const { sources, status } = packet;
  const [selected, setSelected] = useState(
    sources.findIndex((s) => s.role === "policy"),
  );
  const source = sources[selected] || sources[0];
  const intake = packet.intake || packet.input_kind === "intake";
  const [clarificationError, setClarificationError] = useState("");
  const [preparing, setPreparing] = useState(false);
  const linkRef = useRef("");
  useEffect(
    () => () => {
      if (linkRef.current) URL.revokeObjectURL(linkRef.current);
    },
    [],
  );
  async function downloadClarification() {
    setPreparing(true);
    setClarificationError("");
    try {
      const res = await api(
        casePath(packet.id) + "/clarification?revision=" + packet.revision,
      );
      if (!res.headers.get("Content-Type")?.includes("application/pdf"))
        throw new Error(
          "The information request is unavailable. Reload the case and try again.",
        );
      if (linkRef.current) URL.revokeObjectURL(linkRef.current);
      linkRef.current = URL.createObjectURL(await res.blob());
      const link = document.createElement("a");
      link.href = linkRef.current;
      link.download = packet.id + "-R" + packet.revision + "-clarification.pdf";
      document.body.append(link);
      link.click();
      link.remove();
    } catch (e) {
      setClarificationError(
        e instanceof Error
          ? e.message
          : "Unable to download the information request.",
      );
    } finally {
      setPreparing(false);
    }
  }
  return (
    <>
      <div className="page-title case-jacket">
        <div>
          <div className="section-label">
            Pre-arrival request <span className="label-sep">/</span>{" "}
            <span className="mono">Case {packet.id}</span>
          </div>
          <h1>{packet.procedure}</h1>
          <p>
            <Building2 size={15} />
            {packet.insurer}
            <span className="bullet-sep">·</span>
            <span>Guarantee-of-payment request</span>
          </p>
        </div>
        <Pill status={status} />
      </div>
      <dl className="facts">
        <div>
          <dt>Member reference</dt>
          <dd>{packet.member}</dd>
        </div>
        <div>
          <dt>Admission date</dt>
          <dd>{displayDate(packet.admission_date)}</dd>
        </div>
        <div>
          <dt>Estimated charges</dt>
          <dd>{money(packet.total)}</dd>
        </div>
        <div>
          <dt>Packet revision</dt>
          <dd>
            R{packet.revision} <span>{historical ? "Pinned" : "Current"}</span>
          </dd>
        </div>
      </dl>
      {notice && (
        <p className="notice" role="status">
          <Check size={16} />
          {notice}
        </p>
      )}
      {!!packet.open_holds?.length && (
        <div className="hold-banner" role="status">
          <CircleAlert size={16} />
          <span>
            {packet.open_holds.length} open{" "}
            {packet.open_holds.length === 1 ? "hold" : "holds"} · Review and
            export are paused.
          </span>
          <a
            href="#operational-holds"
            onClick={(e) => {
              e.preventDefault();
              document
                .getElementById("operational-holds")
                ?.scrollIntoView({ block: "start" });
            }}
          >
            View holds
          </a>
        </div>
      )}
      {historical && (
        <div className="history-warning">
          <History size={17} />
          Viewing packet revision R{packet.revision}.{" "}
          <a href={caseHref(packet.id)}>Open current case</a>
        </div>
      )}
      <div className="workspace-grid">
        <section className="panel">
          <div className="panel-heading">
            <h2>
              <ListChecks size={18} />
              Packet review
            </h2>
            <button className="text-action" onClick={showHistory}>
              <History size={15} />
              Version history
            </button>
          </div>
          <div className="review-body">
            <div className={"finding " + (blocked(status) ? "gap" : "pass")}>
              <div className="finding-kicker">
                {blocked(status) ? (
                  <CircleAlert size={14} />
                ) : (
                  <ShieldCheck size={15} />
                )}{" "}
                {blocked(status) ? "Requires attention" : "Review status"}
              </div>
              <h3>{headings[status] || "Packet status"}</h3>
              <p>{packet.reason}</p>
              {!!packet.issues?.length && (
                <ul className="case-issues">
                  {packet.issues.map((issue, i) => (
                    <li key={i}>{issue}</li>
                  ))}
                </ul>
              )}
              {packet.reviewer && <p>Reviewed by {packet.reviewer}.</p>}
            </div>
            <div className="subhead">
              <h3>Supporting evidence</h3>
              <span>{sources.length} sources</span>
            </div>
            <div className="source-list">
              {sources.map((s, i) => {
                const Icon =
                  s.role === "policy"
                    ? BookOpen
                    : s.role === "plan"
                      ? ClipboardList
                      : FileText;
                return (
                  <button
                    key={s.url + "-" + i}
                    className={"source-row " + (s === source ? "chosen" : "")}
                    aria-pressed={s === source}
                    onClick={() => {
                      setSelected(i);
                      if (window.matchMedia("(max-width: 760px)").matches)
                        document.getElementById("source-view")?.scrollIntoView({
                          block: "start",
                          behavior: "instant",
                        });
                    }}
                  >
                    <span className="file-icon">
                      <Icon size={18} />
                    </span>
                    <span className="row-detail">
                      <strong>{s.label}</strong>
                      <small>
                        {s.role === "policy"
                          ? packet.policy_edition
                          : "Case " + packet.id + " · R" + packet.revision}{" "}
                        · p. {s.page || 1}
                      </small>
                    </span>
                    <ChevronRight size={16} />
                  </button>
                );
              })}
            </div>
            <div className="actions">
              {intake && !historical && status !== "staff_reviewed" && (
                <button
                  className={
                    status === "needs_review" ? "primary" : "secondary"
                  }
                  onClick={onEvidence}
                >
                  <BookOpen size={16} />
                  Review policy evidence
                </button>
              )}
              {intake && !historical && packet.clarification_available && (
                <button
                  className="secondary"
                  disabled={preparing}
                  onClick={() => void downloadClarification()}
                >
                  <Download size={16} />
                  {preparing
                    ? "Preparing PDF…"
                    : "Download clarification request"}
                </button>
              )}
              {!historical &&
                !packet.open_holds?.length &&
                status === "ready_for_review" && (
                  <button className="primary" onClick={onReview}>
                    <ShieldCheck size={16} />
                    Review request draft
                  </button>
                )}
              {(historical || status === "staff_reviewed") && (
                <button
                  className={historical ? "secondary" : "primary"}
                  onClick={onExport}
                >
                  <FileText size={16} />
                  {historical || !!packet.open_holds?.length
                    ? "Preview attachments"
                    : "Review export and attachments"}
                </button>
              )}
              {!historical && (
                <button
                  className={
                    status === "needs_itemization" ? "primary" : "secondary"
                  }
                  onClick={onReplace}
                >
                  <Upload size={16} />
                  Replace estimate
                </button>
              )}
            </div>
            {clarificationError && (
              <p className="error-message" role="alert">
                {clarificationError}
              </p>
            )}
          </div>
        </section>
        {source && (
          <SourceView
            source={source}
            revision={packet.revision}
            historical={historical}
          />
        )}
      </div>
      <div id="operational-holds">
        <OperationalHolds
          packet={packet}
          pinned={historical}
          onSaved={onWorkflowSaved}
          onReload={onReload}
        />
      </div>
      <CaseWorkflow
        packet={packet}
        pinned={historical}
        onSaved={onWorkflowSaved}
        onReload={onReload}
      />
      {!historical && (
        <div className="prior-link">
          <a href={"#/discharge/new?case=" + encodeURIComponent(packet.id)}>
            Open a linked discharge claim
          </a>
        </div>
      )}
    </>
  );
}
function CaseView({
  route,
  epoch,
  retry,
}: {
  route: Route;
  epoch: number;
  retry: () => void;
}) {
  const { data, error } = useResource<CaseDetail>(
    casePath(route.id) + (route.rev ? "?revision=" + route.rev : ""),
    epoch,
  );
  const [view, setView] = useState<
    "review" | "replace" | "draft" | "history" | "export" | "evidence"
  >("review");
  const [notice, setNotice] = useState("");
  const historical = !!route.rev;
  function current() {
    setView("review");
    setNotice("");
    retry();
  }
  if (!data) return <LoadState error={error} retry={retry} />;
  function saved() {
    setNotice(
      view === "draft"
        ? "Staff review saved. The reviewed request is available for download."
        : "Estimate attached. The packet has been rechecked.",
    );
    setView("review");
    retry();
  }
  const formProps = {
    packet: data,
    onSaved: saved,
    onCancel: () => {
      setView("review");
      setNotice("");
    },
    onStale: current,
  };
  if (view === "evidence" && !historical)
    return (
      <EvidenceReview
        packet={data}
        onBack={() => setView("review")}
        onSaved={() => {
          setNotice(
            "Evidence review saved. The current packet reflects the verified findings.",
          );
          setView("review");
          retry();
        }}
        onReload={current}
      />
    );
  if (view === "replace" && !historical)
    return <ReplaceEstimate {...formProps} />;
  if (
    view === "draft" &&
    !historical &&
    !data.open_holds?.length &&
    data.status === "ready_for_review"
  )
    return <ApproveDraft {...formProps} />;
  if (view === "export")
    return (
      <ExportReview
        packet={data}
        pinned={historical}
        onBack={() => setView("review")}
      />
    );
  if (view === "history")
    return (
      <div className="form-wrap">
        <div className="page-title">
          <div>
            <p className="section-label">Case {data.id}</p>
            <h1>Version history</h1>
            <p>{data.procedure}</p>
          </div>
        </div>
        <section className="panel">
          <div className="panel-heading">
            <h2>
              <Layers size={18} />
              Packet revisions
            </h2>
          </div>
          {[...data.history]
            .sort((a, b) => b.revision - a.revision)
            .map((r) => (
              <a
                className="case-row"
                key={r.revision}
                href={caseHref(data.id, r.revision)}
                onClick={() => setView("review")}
              >
                <span className="case-code">R{r.revision}</span>
                <span className="row-detail">
                  <strong>{money(r.total)}</strong>
                  <small>Open revision and its sources</small>
                </span>
                <Pill status={r.status} />
                <ChevronRight size={16} />
              </a>
            ))}
        </section>
        <button
          className="secondary back-action"
          onClick={() => setView("review")}
        >
          <ArrowLeft size={16} />
          Back to packet
        </button>
      </div>
    );
  return (
    <CaseWorkspace
      key={data.id + ":" + data.revision + ":" + data.status}
      packet={data}
      historical={historical}
      notice={notice}
      showHistory={() => setView("history")}
      onReplace={() => setView("replace")}
      onReview={() => setView("draft")}
      onExport={() => setView("export")}
      onEvidence={() => setView("evidence")}
      onWorkflowSaved={() => {
        setNotice("Case timeline updated.");
        retry();
      }}
      onReload={current}
    />
  );
}
function App() {
  const session = useStaffSession();
  const insurer = session.role === "insurer";
  const finance = session.role === "finance";
  const [route, setRoute] = useState<Route>(readRoute);
  const [epoch, setEpoch] = useState(0);
  const retry = () => setEpoch((n) => n + 1);
  useEffect(() => {
    const change = () => {
      setRoute(readRoute());
      window.scrollTo({ top: 0, behavior: "instant" });
    };
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);
  useEffect(() => {
    document.title = insurer ? "Insurer inbox · ZeroUpfront" : finance ? "Finance reconciliation · ZeroUpfront" : route.discharge
      ? "Discharge claims · ZeroUpfront"
      : route.id
        ? "Case " + route.id + " · ZeroUpfront"
        : route.create
          ? "Create a case · ZeroUpfront"
          : "Case worklist · ZeroUpfront";
  }, [route.id, route.create, route.discharge, insurer, finance]);
  return (
    <>
      <a
        href="#main-content"
        className="skip-link"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById("main-content")?.focus();
        }}
      >
        Skip to case workspace
      </a>
      <div className="app-layout">
        <header className="hospital-masthead">
          <div className="mast-inner">
            <a href={insurer ? "#/insurer" : finance ? "#/finance" : "#/discharge"} className="mast-brand" aria-label="ZeroUpfront home">
              <span className="mast-symbol"><Layers size={20} aria-hidden="true" /></span>
              ZeroUpfront
            </a>
            <nav className="mast-nav" aria-label="Desk workflows">
              {insurer ? <a aria-current="page" href="#/insurer">Insurer inbox</a> : finance ? <a href="#/finance" aria-current="page">Reconciliation</a> : <>
              <a aria-current={route.discharge ? "page" : undefined} href="#/discharge">Discharge claims</a>
              <a aria-current={!route.discharge ? "page" : undefined} href="#/cases">Pre-arrival cases</a></>}
            </nav>
            <button className="mast-context" popoverTarget="workspace-context" title={session.hospital_name || "Hospital workspace"}>
              <Hospital size={15} /><span>{(insurer && session.insurer) || session.hospital_name || "Hospital"}</span><ChevronDown size={13} />
            </button>
            <div id="workspace-context" className="workspace-context" popover="auto">
              <strong>{session.hospital_name || "Hospital workspace"}</strong>
              <span>{session.mode === "local" ? "Local rehearsal" : session.actor}</span>
              {!finance && <nav aria-label="Workspace shortcuts" onClick={() => document.getElementById("workspace-context")?.hidePopover()}>
                {insurer ? <a href="#/insurer">Insurer inbox <ChevronRight size={15} /></a> : <>
                <a href="#/discharge">Discharge worklist <ChevronRight size={15} /></a>
                <a href="#/cases">Pre-arrival worklist <ChevronRight size={15} /></a></>}
              </nav>}
              {session.mode === "staff" && <div className="account-actions">
                {!finance && <button disabled={session.busy} onClick={() => void session.signOut(false, insurer ? "hospital" : "insurer")}><LogOut size={15} />Switch to {insurer ? "hospital" : "insurer"} desk</button>}
                {hospitalPrefix && <button disabled={session.busy} onClick={() => void session.signOut(true)}>
                  <ArrowLeftRight size={15} />Switch hospital
                </button>}
                <button disabled={session.busy} onClick={() => void session.signOut()}>
                  <LogOut size={15} />Sign out
                </button>
                {session.problem && <p className="error-message" role="alert">{session.problem}</p>}
              </div>}
            </div>
          </div>
        </header>
        <div className="app-content">
          <main id="main-content" tabIndex={-1}>
        {finance ? <FinanceLedger /> : <>
        {(insurer ? route.inbox && route.id : route.id || route.create) && (
          <nav className="breadcrumbs" aria-label="Breadcrumb">
            <a href={insurer ? "#/insurer" : route.discharge ? "#/discharge" : "#/cases"}>
              <FolderOpen size={15} />
              {insurer ? "Insurer inbox" : route.discharge ? "Discharge worklist" : "Case worklist"}
            </a>
            {(route.id || route.create) && (
              <>
                <ChevronRight size={14} />
                <span aria-current="page" title={route.id && route.id !== "new" ? route.id : undefined}>
                  {route.create
                    ? "Create a case"
                    : route.discharge && route.id === "new"
                      ? "Open a claim"
                      : route.id}
                  {route.rev ? " · R" + route.rev : ""}
                </span>
              </>
            )}
          </nav>
        )}
        {insurer ? (route.inbox && route.id ? <PayerCase key={route.id} id={route.id} revision={route.rev} insurer /> : <InsurerInbox />)
         : route.preclaim && !route.inbox ? <PayerCase key={route.id} id={route.id} revision={route.rev} insurer={false} />
         : route.discharge ? (
          <Suspense
            fallback={<p className="loading">Opening discharge workspace…</p>}
          >
            <Discharge
              key={route.id + ":" + String(route.rev)}
              id={route.id || undefined}
              prior={route.prior}
              revision={route.rev}
            />
          </Suspense>
        ) : route.inbox ? <Worklist epoch={epoch} retry={retry} /> : route.create ? (
          <NewCase />
        ) : route.id ? (
          <CaseView
            key={route.id + "-" + (route.rev ?? "current")}
            route={route}
            epoch={epoch}
            retry={retry}
          />
        ) : (
          <Worklist epoch={epoch} retry={retry} />
        )}
        </>}
          </main>
        </div>
      </div>
    </>
  );
}
createRoot(document.getElementById("root")!).render(
  <AuthGate>
    <App />
  </AuthGate>,
);
