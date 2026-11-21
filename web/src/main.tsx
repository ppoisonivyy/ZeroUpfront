import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowLeft,
  BookOpen,
  Building2,
  Check,
  ChevronRight,
  CircleAlert,
  ClipboardList,
  Download,
  ExternalLink,
  FileText,
  FolderOpen,
  History,
  Layers,
  LayoutList,
  ListChecks,
  MessageSquare,
  RefreshCw,
  ScanLine,
  ShieldCheck,
  Upload,
} from "lucide-react";
import type { CaseDetail, CaseSummary, PacketStatus, Source } from "./api";
import {
  api,
  blocked,
  casePath,
  displayDate,
  money,
  sameOriginSource,
  statuses,
} from "./api";
import { ApproveDraft, ReplaceEstimate } from "./ReviewForms";
import { AttachmentList } from "./Attachments";
import "./style.css";

const PdfPage = lazy(() => import("./PdfPage"));
type Route = { id: string; rev?: number };
const caseHref = (id: string, rev?: number) =>
  "#/cases/" + encodeURIComponent(id) + (rev ? "?revision=" + rev : "");
function readRoute(): Route {
  const pathAndSearch =
    location.hash.slice(1) || location.pathname + location.search;
  if (pathAndSearch === "/") return { id: "Z002" };
  const [path, search] = pathAndSearch.split("?");
  const id = path.match(/^\/cases\/([a-zA-Z0-9_-]+)$/)?.[1] || "";
  const rev = Number(new URLSearchParams(search).get("revision"));
  return { id, rev: Number.isSafeInteger(rev) && rev > 0 ? rev : undefined };
}
function useResource<T>(url: string, epoch: number) {
  const [result, set] = useState<{ key: string; data?: T; error?: string }>({
    key: "",
  });
  const key = url + ":" + epoch;
  useEffect(() => {
    const controller = new AbortController();
    api(url, { signal: controller.signal })
      .then((r) => r.json())
      .then((data) => {
        if (!controller.signal.aborted) set({ key, data });
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          set({
            key,
            error:
              error instanceof Error
                ? error.message
                : "The case could not be loaded.",
          });
      });
    return () => controller.abort();
  }, [url, key]);
  return key === result.key ? result : { key };
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
  return (
    <>
      <div className="page-title">
        <div>
          <p className="section-label">Pre-arrival coordination</p>
          <h1>Case worklist</h1>
          <p>Inpatient requests for a guarantee of payment.</p>
        </div>
      </div>
      {!data ? (
        <LoadState error={error} retry={retry} />
      ) : (
        <section className="panel">
          <div className="panel-heading">
            <h2>
              <LayoutList size={18} />
              Inpatient cases
            </h2>
            <span className="small">{data.length} cases</span>
          </div>
          {data.length === 0 ? (
            <p className="empty-view">No cases in the worklist.</p>
          ) : (
            <div className="worklist">
              {data.map((c) => (
                <a key={c.id} className="case-row" href={caseHref(c.id)}>
                  <span className="case-code">{c.id}</span>
                  <span className="row-detail">
                    <strong>{c.procedure}</strong>
                    <small>
                      {c.insurer} · {money(c.total)}
                    </small>
                  </span>
                  <Pill status={c.status} />
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
function SourceView({
  source,
  revision,
  historical,
}: {
  source: Source;
  revision: number;
  historical: boolean;
}) {
  let url = "";
  try {
    url = sameOriginSource(source.url);
  } catch {
    /* Keep the cited quote visible if the URL is invalid. */
  }
  const page = source.page || 1;
  return (
    <section
      className="panel viewer"
      id="source-view"
      aria-labelledby="source-title"
    >
      <div className="panel-heading">
        <h2 id="source-title">
          <ScanLine size={18} />
          Source viewer
        </h2>
        {url && (
          <a
            className="text-action"
            href={url + "#page=" + page}
            target="_blank"
            rel="noreferrer"
          >
            Open PDF <ExternalLink size={14} />
          </a>
        )}
      </div>
      <div className="citation" aria-live="polite">
        <div className="cite-label">
          {source.label} <span>· Page {page}</span>
        </div>
        <blockquote>
          {source.quote || "No verified excerpt is available for this source."}
        </blockquote>
      </div>
      <div className="viewer-meta">
        <span>
          <FileText size={14} />
          Original document
        </span>
        <span>
          {historical ? "Pinned" : "Case"} R{revision} · p. {page}
        </span>
      </div>
      {url ? (
        <Suspense fallback={<p className="loading">Loading viewer…</p>}>
          <PdfPage url={url} page={page} label={source.label} />
        </Suspense>
      ) : (
        <p className="empty-view">The original PDF address is unavailable.</p>
      )}
    </section>
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
          The coordinator prepares this request for the insurer. No insurer
          response has been recorded.
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
          {!pinned && packet.status === "staff_reviewed" && (
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
  notice,
}: {
  packet: CaseDetail;
  historical: boolean;
  showHistory: () => void;
  onReplace: () => void;
  onReview: () => void;
  onExport: () => void;
  notice: string;
}) {
  const { sources, status } = packet;
  const [selected, setSelected] = useState(
    sources.findIndex((s) => s.role === "policy"),
  );
  const source = sources[selected] || sources[0];
  return (
    <>
      <div className="page-title">
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
      {historical && (
        <div className="history-warning">
          <History size={17} />
          Viewing a read-only snapshot of revision R{packet.revision}.{" "}
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
                        document
                          .getElementById("source-view")
                          ?.scrollIntoView({
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
              {!historical && status === "ready_for_review" && (
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
                  {historical
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
      <aside className="insurer-response">
        <div className="response-icon">
          <MessageSquare size={19} />
        </div>
        <div>
          <h2>Insurer response</h2>
          <p>
            {packet.insurer_status === "not_sent"
              ? "Request has not been sent. No guarantee of payment on file."
              : packet.insurer_status.replaceAll("_", " ")}
          </p>
        </div>
      </aside>
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
    "review" | "replace" | "draft" | "history" | "export"
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
  if (view === "replace" && !historical)
    return <ReplaceEstimate {...formProps} />;
  if (view === "draft" && !historical && data.status === "ready_for_review")
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
    />
  );
}
function App() {
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
    document.title = route.id
      ? "Case " + route.id + " · ZeroUpfront"
      : "Case worklist · ZeroUpfront";
  }, [route.id]);
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
      <header className="app-header">
        <div className="header-inner">
          <a href="#/cases" className="brand">
            <span className="logomark" aria-hidden="true">
              Z
            </span>
            ZeroUpfront
          </a>
          <span className="header-divider" />
          <span className="header-label">Coordinator workspace</span>
          <span className="demo-label">
            <i />
            Synthetic demo
          </span>
        </div>
      </header>
      <main id="main-content" tabIndex={-1}>
        <nav className="breadcrumbs" aria-label="Breadcrumb">
          <a href="#/cases">
            <FolderOpen size={15} />
            Case worklist
          </a>
          {route.id && (
            <>
              <ChevronRight size={14} />
              <span aria-current="page">
                {route.id}
                {route.rev ? " · R" + route.rev : ""}
              </span>
            </>
          )}
        </nav>
        {route.id ? (
          <CaseView
            key={route.id + "-" + (route.rev ?? "current")}
            route={route}
            epoch={epoch}
            retry={retry}
          />
        ) : (
          <Worklist epoch={epoch} retry={retry} />
        )}
      </main>
    </>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
