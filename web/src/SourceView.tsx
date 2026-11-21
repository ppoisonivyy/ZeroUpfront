import { lazy, Suspense, useState } from "react";
import { ArrowLeft, ExternalLink, FileText, ScanLine } from "lucide-react";
import { sameOriginSource, type Source } from "./api";
const PdfPage = lazy(() => import("./PdfPage"));

/** Remember the precise review control and its position while its source is open. */
export function useSourceNavigation() {
  const [origin, setOrigin] = useState<{ trigger: HTMLElement; top: number } | null>(null);

  function open(trigger?: HTMLButtonElement) {
    const control = trigger || document.activeElement;
    if (control instanceof HTMLElement && control !== document.body) {
      setOrigin({ trigger: control, top: control.getBoundingClientRect().top });
    }
    requestAnimationFrame(() => {
      const viewer = document.getElementById("source-view");
      if (!viewer) return;
      viewer.focus({ preventScroll: true });
      const top = viewer.getBoundingClientRect().top;
      if (top < 0 || top > window.innerHeight / 2) viewer.scrollIntoView({ block: "start" });
    });
  }

  function back() {
    if (origin?.trigger.isConnected) {
      origin.trigger.focus({ preventScroll: true });
      window.scrollBy({ top: origin.trigger.getBoundingClientRect().top - origin.top, behavior: "instant" });
    }
    setOrigin(null);
  }
  return { open, onReturn: origin?.trigger.isConnected ? back : undefined };
}

type Props = {
  source: Source;
  revision: number;
  historical: boolean;
  onReady?: () => void;
  onReturn?: () => void;
};

export function SourceView(props: Props) {
  return <SourcePanel key={props.source.url + "#" + props.source.page} {...props} />;
}

function SourcePanel({ source, revision, historical, onReady, onReturn }: Props) {
  let url = "";
  try {
    url = sameOriginSource(source.url);
  } catch {
    /* Keep the cited quote visible if the URL is invalid. */
  }
  const page = source.page || 1;
  const [viewedPage, setViewedPage] = useState(page);
  const anchor = source.anchors?.find(a => a.page === page && a.quote === source.quote);
  const method = source.method ?? anchor?.method;
  return (
    <section className="panel viewer" id="source-view" tabIndex={-1} aria-labelledby="source-title">
      <div className="panel-heading">
        <h2 id="source-title"><ScanLine size={18} />Source viewer</h2>
        {url && <a className="text-action" href={url + "#page=" + viewedPage} target="_blank" rel="noreferrer">
          Open PDF <ExternalLink size={14} />
        </a>}
      </div>
      {onReturn && <button type="button" className="text-action source-return" onClick={onReturn}>
        <ArrowLeft size={15} /> Back to review task
      </button>}
      <div className="citation" aria-live="polite">
        <div className="cite-label">{source.label} <span>· Cited page {page}</span></div>
        {source.recordedSummary ? <p className="recorded-summary">
          <strong>Recorded summary</strong> {source.recordedSummary}
        </p> : <blockquote>{source.quote || "No verified excerpt is available for this source."}</blockquote>}
      </div>
      <div className="viewer-meta">
        <span><FileText size={14} />Original document</span>
        <span>{historical ? "Pinned" : "Case"} R{revision} · viewing p. {viewedPage}</span>
      </div>
      {url ? (
        <Suspense fallback={<p className="loading">Loading viewer…</p>}>
          <PdfPage url={url} page={page} label={source.label} readable onReady={onReady} onPageChange={setViewedPage}
            quote={source.recordedSummary ? "" : source.quote} method={method} />
        </Suspense>
      ) : <p className="empty-view">The original PDF address is unavailable.</p>}
    </section>
  );
}
