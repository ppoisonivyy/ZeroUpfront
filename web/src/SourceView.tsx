import { lazy, Suspense } from "react";
import { ExternalLink, FileText, ScanLine } from "lucide-react";
import { sameOriginSource, type Source } from "./api";
const PdfPage = lazy(() => import("./PdfPage"));

export function SourceView({
  source,
  revision,
  historical,
  onReady,
}: {
  source: Source;
  revision: number;
  historical: boolean;
  onReady?: () => void;
}) {
  let url = "";
  try {
    url = sameOriginSource(source.url);
  } catch {
    /* Keep the cited quote visible if the URL is invalid. */
  }
  const page = source.page || 1;
  const anchor = source.anchors?.find(a => a.page === page && a.quote === source.quote);
  const method = source.method ?? anchor?.method;
  return (
    <section
      className="panel viewer"
      id="source-view"
      tabIndex={-1}
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
        {source.recordedSummary ? <p className="recorded-summary">
          <strong>Recorded summary</strong> {source.recordedSummary}
        </p> : <blockquote>{source.quote || "No verified excerpt is available for this source."}</blockquote>}
      </div>
      <div className="viewer-meta">
        <span>
          <FileText size={14} />
          Original document
        </span>
        <span>
          {historical ? "Pinned" : "Case"} R{revision} · cited p. {page}
        </span>
      </div>
      {url ? (
        <Suspense fallback={<p className="loading">Loading viewer…</p>}>
          <PdfPage url={url} page={page} label={source.label} onReady={onReady} quote={source.recordedSummary ? "" : source.quote} method={method} />
        </Suspense>
      ) : (
        <p className="empty-view">The original PDF address is unavailable.</p>
      )}
    </section>
  );
}
