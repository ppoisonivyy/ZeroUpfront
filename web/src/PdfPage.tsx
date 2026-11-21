import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type {
  PDFDocumentLoadingTask,
  PDFDocumentProxy,
  RenderTask,
} from "pdfjs-dist/types/src/display/api";

type Props = {
  url: string;
  page?: number;
  label: string;
  onText?: (text: string) => void;
  onReady?: () => void;
  openSequence?: number;
  onPageChange?: (page: number) => void;
  fixedPage?: boolean;
  readable?: boolean;
  quote?: string;
  method?: string;
};
const messages = {
  matched: "Exact passage highlighted on the original page.",
  absent: "Page only. The quoted text could not be located exactly on this page.",
  ambiguous: "Page only. The same passage appears more than once on this page.",
  unmapped: "Page only. A reliable text location is unavailable.",
  ocr: "Page only. The OCR transcript has no verified word locations.",
  "other-page": "This citation refers to a different page.",
  "no-quote": "Page only. No verbatim passage is attached to this citation.",
};
function showPassage(scroll: HTMLDivElement | null) {
  const mark = scroll?.querySelector(".pdf-quote-mark");
  if (!scroll || !mark) return;
  const current = scroll.getBoundingClientRect(), target = mark.getBoundingClientRect();
  scroll.scrollTop += target.top - current.top - 32;
  scroll.scrollLeft += target.left - current.left - 22;
}
export default function PdfPage(props: Props) {
  return <DocumentPage key={props.url + "#" + (props.page ?? 1)} {...props} />;
}
function DocumentPage({
  url,
  page = 1,
  label,
  onText,
  onReady,
  onPageChange,
  openSequence,
  fixedPage = false,
  readable = false,
  quote,
  method,
}: Props) {
  const frame = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [active, setActive] = useState(page);
  const [zoom, setZoom] = useState(1);
  const [citation, setCitation] = useState<keyof typeof messages | null>(null);
  const scroll = useRef<HTMLDivElement>(null);
  const [target, setTarget] = useState(String(page));
  // Reopening the same citation must restore its page without downloading the PDF again.
  useLayoutEffect(() => {
    setActive(page);
    setTarget(String(page));
    onPageChange?.(page);
  }, [openSequence, page, onPageChange]);
  const [readText, setReadText] = useState(() => readable && matchMedia("(max-width: 760px)").matches);
  const [extracted, setExtracted] = useState<{ page: number; text: string } | null>(null);
  const [status, setStatus] = useState("Loading original page…");
  const error =
    "The page preview is unavailable. Open the original PDF to review it.";
  useEffect(() => {
    if (!frame.current) return;
    const observer = new ResizeObserver(([item]) =>
      setWidth(Math.floor(item.contentRect.width)),
    );
    observer.observe(frame.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    let stopped = false;
    let task: PDFDocumentLoadingTask | undefined;
    async function load() {
      const { openPdf } = await import("./pdf");
      if (stopped) return;
      task = openPdf(url);
      const result = await task.promise;
      if (!stopped) setDoc(result);
    }
    load().catch(() => {
      if (!stopped) setStatus(error);
    });
    return () => {
      stopped = true;
      task?.destroy().catch(() => {});
    };
  }, [url]);
  useEffect(() => {
    if (!doc || !readText) return;
    let stopped = false;
    doc.getPage(active)
      .then(pdfPage => pdfPage.getTextContent())
      .then(content => {
        if (stopped) return;
        const text = content.items
          .map(item => "str" in item ? item.str + (item.hasEOL ? "\n" : " ") : "")
          .join("").trim();
        setExtracted({ page: active, text });
      })
      .catch(() => {
        if (!stopped) setExtracted({ page: active, text: "" });
      });
    return () => { stopped = true; };
  }, [doc, active, readText]);
  useEffect(() => {
    if (readText && extracted?.page === active && extracted.text) {
      onText?.(extracted.text);
      onReady?.();
    }
  }, [active, readText, extracted, onText, onReady]);
  useEffect(() => {
    const host = frame.current;
    if (readText || !doc || !host || !width) return;
    const documentProxy = doc;
    const controller = new AbortController();
    const { signal } = controller;
    let rendering: RenderTask | undefined;
    const canvas = document.createElement("canvas");
    const surface = document.createElement("div");
    surface.className = "pdf-surface";
    setCitation(null);
    setStatus("Loading original page…");
    async function render() {
      const pdfPage = await documentProxy.getPage(active);
      if (signal.aborted) return;
      const base = pdfPage.getViewport({ scale: 1 });
      const dpi = Math.min(window.devicePixelRatio || 1, 2);
      const cssViewport = pdfPage.getViewport({ scale: width * zoom / base.width });
      const viewport = pdfPage.getViewport({ scale: cssViewport.scale * dpi });
      canvas.width = Math.max(1, Math.ceil(viewport.width));
      canvas.height = Math.max(1, Math.ceil(viewport.height));
      canvas.setAttribute("role", "img");
      canvas.setAttribute("aria-label", label + ", page " + active);
      rendering = pdfPage.render({ canvas, viewport });
      await rendering.promise;
      if (signal.aborted) return;
      surface.style.width = cssViewport.width + "px";
      surface.style.height = cssViewport.height + "px";
      surface.append(canvas);
      host!.replaceChildren(surface);
      setStatus("");
      onReady?.();
      const isOcr = /ocr/i.test(method || "");
      const shouldLocate = !!quote?.trim() && active === page && !isOcr;
      if (quote !== undefined && !shouldLocate) {
        setCitation(active !== page ? "other-page" : isOcr ? "ocr" : "no-quote");
      }
      if (!shouldLocate && !onText) return;
      const content = await pdfPage.getTextContent().catch(() => null);
      if (signal.aborted) return;
      if (content && onText) onText(content.items.map(item => "str" in item ? item.str : "").join(" "));
      if (!shouldLocate) return;
      if (!content) { setCitation("unmapped"); return; }
      const { highlightPassage } = await import("./pdfHighlight");
      if (signal.aborted) return;
      const result = await highlightPassage(surface, cssViewport, content, quote!, signal).catch(() => "unmapped" as const);
      if (signal.aborted) return;
      setCitation(result);
      if (result === "matched") showPassage(scroll.current);
    }
    render().catch(() => {
      if (!signal.aborted) setStatus(error);
    });
    return () => {
      controller.abort();
      rendering?.cancel();
      surface.remove();
    };
  }, [doc, active, width, label, onText, onReady, readText, quote, method, page, zoom]);
  function selectPage(value: number) {
    if (doc && Number.isInteger(value) && value >= 1 && value <= doc.numPages) {
      setActive(value);
      onPageChange?.(value);
      setTarget(String(value));
    }
  }
  return (
    <>
      {readable && <div className="pdf-mode" role="group" aria-label="Document view">
        <button type="button" aria-pressed={readText} onClick={() => setReadText(true)}>Readable text</button>
        <button type="button" aria-pressed={!readText} onClick={() => setReadText(false)}>Original page</button>
      </div>}
      {doc && doc.numPages > 1 && !fixedPage && (
        <div className="pdf-pager">
          <button
            type="button"
            className="text-action"
            disabled={active <= 1}
            onClick={() => selectPage(active - 1)}
          >
            Previous
          </button>
          <label>
            Page{" "}
            <input
              type="number"
              min="1"
              max={doc.numPages}
              value={target}
              onChange={(e) => {
                setTarget(e.target.value);
                const n = Number(e.target.value);
                if (n >= 1 && n <= doc.numPages && Number.isInteger(n))
                  selectPage(n);
              }}
              onBlur={() => setTarget(String(active))}
            />{" "}
            of {doc.numPages}
          </label>
          <button
            type="button"
            className="text-action"
            disabled={active >= doc.numPages}
            onClick={() => selectPage(active + 1)}
          >
            Next
          </button>
        </div>
      )}
      {readText && <section className="pdf-readable" aria-label={label + ", page " + active + ", readable text"}>
        {extracted?.page === active ? extracted.text
          ? <p>{extracted.text}</p>
          : <p>Readable text is unavailable on this page. Select Original page to inspect the document image.</p>
          : <p role="status">{!doc && status === error ? error : "Loading page text…"}</p>}
      </section>}
      {!readText && quote !== undefined && !status && <div className="pdf-proof-tools">
        {citation && <p data-citation-status={citation} role="status">{messages[citation]}</p>}
        <div>
          {citation === "matched" && <button type="button" className="text-action" onClick={() => showPassage(scroll.current)}>Show passage</button>}
          {citation === "other-page" && <button type="button" className="text-action" onClick={() => selectPage(page)}>Return to cited page</button>}
          <button type="button" className="text-action" aria-label="Zoom out" disabled={zoom <= 1} onClick={() => setZoom(z => Math.max(1, z - 0.5))}>−</button>
          <span aria-label="Page zoom">{zoom * 100}%</span>
          <button type="button" className="text-action" aria-label="Zoom in" disabled={zoom >= 2.5} onClick={() => setZoom(z => Math.min(2.5, z + 0.5))}>+</button>
        </div>
      </div>}
      <div className="pdf-scroll" ref={scroll} hidden={readText}>
        {status && (
          <p className="pdf-message" role="status">
            {status}
          </p>
        )}
        <div className="pdf-page" ref={frame} />
      </div>
    </>
  );
}
