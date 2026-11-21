import { useEffect, useRef, useState } from "react";
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
  onPageChange?: (page: number) => void;
  fixedPage?: boolean;
  readable?: boolean;
};
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
  fixedPage = false,
  readable = false,
}: Props) {
  const frame = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [active, setActive] = useState(page);
  const [target, setTarget] = useState(String(page));
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
    let stopped = false;
    let rendering: RenderTask | undefined;
    const canvas = document.createElement("canvas");
    setStatus("Loading original page…");
    async function render() {
      const pdfPage = await documentProxy.getPage(active);
      if (stopped) return;
      const base = pdfPage.getViewport({ scale: 1 });
      const dpi = Math.min(window.devicePixelRatio || 1, 2);
      const viewport = pdfPage.getViewport({
        scale: (width * dpi) / base.width,
      });
      canvas.width = Math.max(1, Math.ceil(viewport.width));
      canvas.height = Math.max(1, Math.ceil(viewport.height));
      canvas.setAttribute("role", "img");
      canvas.setAttribute("aria-label", label + ", page " + active);
      rendering = pdfPage.render({ canvas, viewport });
      await rendering.promise;
      if (stopped) return;
      host!.replaceChildren(canvas);
      setStatus("");
      onReady?.();
      if (onText) {
        const content = await pdfPage.getTextContent().catch(() => null);
        if (!stopped && content)
          onText(
            content.items
              .map((item) => ("str" in item ? item.str : ""))
              .join(" "),
          );
      }
    }
    render().catch(() => {
      if (!stopped) setStatus(error);
    });
    return () => {
      stopped = true;
      rendering?.cancel();
      canvas.remove();
    };
  }, [doc, active, width, label, onText, onReady, readText]);
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
                if (n >= 1 && n <= doc.numPages && Number.isInteger(n)) {
                  setActive(n);
                  onPageChange?.(n);
                }
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
      <div className="pdf-scroll" hidden={readText}>
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
