import { lazy, Suspense, useCallback, useRef, useState, type FormEvent } from "react";
import { ArrowLeft, ExternalLink, FileText } from "lucide-react";
import { api, sameOriginSource } from "./api";
import type { useSourceNavigation } from "./SourceView";

const PdfPage = lazy(() => import("./PdfPage"));

export type ReportEvidence = {
  sha256: string; pages: number; page: number | null;
  content_type: "application/pdf" | "image/png" | "image/jpeg"; original_url: string;
  status: "needs_review" | "staff_attested"; attested_by: string | null;
};

type UploadProps = {
  caseId: string; busy: boolean;
  upload: (data: FormData) => Promise<boolean>;
};

export function ReportUpload({ caseId, busy, upload }: UploadProps) {
  const [file, setFile] = useState<File | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file || !confirmed || error || busy) return;
    const data = new FormData();
    data.append("file", file);
    data.append("confirmed", "true");
    await upload(data);
  }
  return <details className="report-upload">
    <summary>Upload a physician report</summary>
    <form className="report-form" onSubmit={submit}>
      <label className="field">Physician report file
        <input required type="file" disabled={busy} accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
          onChange={event => {
            const selected = event.target.files?.[0] ?? null;
            setFile(selected); setConfirmed(false);
            setError(selected && selected.size > 12 * 1024 * 1024 ? "Choose a file of 12 MiB or less." : "");
          }} />
      </label>
      <small>PDF, PNG or JPEG, up to 12 MiB. A scan or photograph can include a handwritten mark.</small>
      {error && <p role="alert">{error}</p>}
      <label className="check"><input type="checkbox" checked={confirmed} disabled={busy || !file || !!error}
        onChange={event => setConfirmed(event.target.checked)} /> I intend to attach this file to {caseId}.</label>
      <button className="secondary" type="submit" disabled={!file || !confirmed || !!error || busy}>Save report for visual review</button>
    </form>
  </details>;
}

function SignatureHint({ path, revision, evidence }: { path: string; revision: number; evidence: ReportEvidence }) {
  const inFlight = useRef(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function request() {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setMessage("");
    try {
      const response = await api(path, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmed: true, sha256: evidence.sha256 }) });
      const result = await response.json();
      if (result.revision !== revision || result.sha256 !== evidence.sha256)
        throw new Error("The suggestion does not match this report revision.");
      const pages = Array.isArray(result.pages)
        ? result.pages.filter((p: unknown) => typeof p === "number" && Number.isInteger(p) && p >= 1 && p <= evidence.pages)
        : [];
      setMessage(result.status === "suggested" && pages.length
        ? "Possible signature on " + (pages.length === 1 ? "page " : "pages ") + pages.join(", ") + ". Inspect the original to confirm."
        : "No reliable page suggestion. Inspect the original report.");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Page suggestions are unavailable. Inspect the original report.");
    } finally { inFlight.current = false; setBusy(false); }
  }
  return <details className="report-hint">
    <summary>Find a possible signature page</summary>
    <p>Send this original report to the hospital-approved OpenAI service for a page suggestion. Hospital staff make the visual finding.</p>
    <button className="secondary" type="button" disabled={busy} onClick={request}>{busy ? "Checking pages…" : "Send report to OpenAI"}</button>
    {message && <p role="status">{message}</p>}
  </details>;
}

type ViewerProps = {
  evidence: ReportEvidence; revision: number; citedPage: number;
  patient: string; member: string; caseId: string; busy: boolean;
  navigation: ReturnType<typeof useSourceNavigation>;
  hintPath?: string;
  attest?: (page: number) => Promise<boolean>;
};

export function PhysicianReportViewer({ evidence, revision, citedPage, patient, member, caseId, busy,
  navigation, hintPath, attest }: ViewerProps) {
  const [page, setPage] = useState(citedPage);
  const [renderedPage, setRenderedPage] = useState<number | null>(null);
  const [identity, setIdentity] = useState(false);
  const [mark, setMark] = useState(false);
  const [imageError, setImageError] = useState(false);
  const selectPage = useCallback((next: number) => {
    setPage(next); setIdentity(false); setMark(false);
  }, []);
  const url = sameOriginSource(evidence.original_url);
  const pdf = evidence.content_type === "application/pdf";
  const reviewedPage = renderedPage === page && !imageError;
  return <section className="panel viewer" id="source-view" tabIndex={-1} aria-labelledby="source-title">
    <div className="panel-heading">
      <h2 id="source-title"><FileText size={18}/>Original physician report</h2>
      <a className="text-action" href={url + (pdf ? "#page=" + page : "")} target="_blank" rel="noreferrer">
        Open original <ExternalLink size={14}/></a>
    </div>
    {navigation.onReturn && <button type="button" className="text-action source-return" onClick={navigation.onReturn}>
      <ArrowLeft size={15}/> Back to review task</button>}
    <div className="viewer-meta"><span>Uploaded {pdf ? "PDF" : "image"} · R{revision}</span><span>Viewing p. {page} of {evidence.pages}</span></div>
    {evidence.status === "staff_attested" && <p className="report-finding">
      {evidence.attested_by || "Hospital staff"} recorded a visible physician mark on page {evidence.page}.</p>}
    {pdf ? <Suspense fallback={<p role="status">Loading original report…</p>}>
      <PdfPage url={url} page={citedPage} label="Original physician report" openSequence={navigation.openSequence}
        onPageChange={selectPage} onVisualPageReady={setRenderedPage} quote=""/>
    </Suspense> : <div className="report-image">
      <img src={url} alt="Uploaded physician report, page 1" onLoad={() => setRenderedPage(1)} onError={() => setImageError(true)} />
      {imageError && <p role="alert">The original image could not be displayed. Reopen the report to try again.</p>}
    </div>}
    {attest && <div className="report-visual">
      <h3>Record visual review</h3>
      <p>Read the identifiers and treatment details, then navigate to the page bearing the treating physician’s mark. This records what you observed.</p>
      {hintPath && <SignatureHint path={hintPath} revision={revision} evidence={evidence}/>}
      <fieldset disabled={busy || !reviewedPage}>
        <legend>Confirm the original report</legend>
        <label className="check"><input type="checkbox" checked={identity} onChange={e => setIdentity(e.target.checked)}/>
          I matched {patient}, member {member}, and case {caseId}, and checked the indication and planned procedure.</label>
        <label className="check"><input type="checkbox" checked={mark} onChange={e => setMark(e.target.checked)}/>
          I see the treating physician’s signature or mark on page {page}.</label>
        <button className="primary" type="button" disabled={!identity || !mark || !reviewedPage || busy}
          onClick={() => void attest(page)}>Record review of page {page}</button>
      </fieldset>
    </div>}
  </section>;
}
