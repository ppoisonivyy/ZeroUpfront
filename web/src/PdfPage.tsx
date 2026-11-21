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
  fixedPage?: boolean;
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
  fixedPage = false,
}: Props) {
  const frame = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [active, setActive] = useState(page);
  const [target, setTarget] = useState(String(page));
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
    const host = frame.current;
    if (!doc || !host || !width) return;
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
  }, [doc, active, width, label, onText, onReady]);
  function selectPage(value: number) {
    if (doc && Number.isInteger(value) && value >= 1 && value <= doc.numPages) {
      setActive(value);
      setTarget(String(value));
    }
  }
  return (
    <>
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
                  setActive(n);
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
      <div className="pdf-scroll">
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
