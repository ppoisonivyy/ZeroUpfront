import { useEffect, useRef, useState } from "react";
import type {
  PDFDocumentLoadingTask,
  RenderTask,
} from "pdfjs-dist/types/src/display/api";

type Props = {
  url: string;
  page?: number;
  label: string;
  onText?: (text: string) => void;
};

export default function PdfPage({ url, page = 1, label, onText }: Props) {
  const frame = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [status, setStatus] = useState("Loading original page…");
  useEffect(() => {
    if (!frame.current) return;
    const observer = new ResizeObserver(([entry]) =>
      setWidth(Math.floor(entry.contentRect.width)),
    );
    observer.observe(frame.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    const host = frame.current;
    if (!width || !host) return;
    let abandoned = false;
    let job: PDFDocumentLoadingTask | undefined;
    let rendering: RenderTask | undefined;
    const canvas = document.createElement("canvas");
    setStatus("Loading original page…");
    async function render() {
      const { openPdf } = await import("./pdf");
      if (abandoned) return;
      job = openPdf(url);
      const doc = await job.promise;
      const pdfPage = await doc.getPage(page);
      if (abandoned) return;
      const base = pdfPage.getViewport({ scale: 1 });
      const dpi = Math.min(window.devicePixelRatio || 1, 2);
      const viewport = pdfPage.getViewport({
        scale: (width * dpi) / base.width,
      });
      canvas.width = Math.max(1, Math.ceil(viewport.width));
      canvas.height = Math.max(1, Math.ceil(viewport.height));
      canvas.setAttribute("role", "img");
      canvas.setAttribute("aria-label", label + ", page " + page);
      rendering = pdfPage.render({ canvas, viewport });
      await rendering.promise;
      if (abandoned) return;
      host!.replaceChildren(canvas);
      setStatus("");
      if (onText) {
        const content = await pdfPage.getTextContent().catch(() => null);
        if (!abandoned && content)
          onText(
            content.items
              .map((item) => ("str" in item ? item.str : ""))
              .join(" "),
          );
      }
    }
    render().catch(() => {
      if (!abandoned)
        setStatus(
          "The page preview is unavailable. Open the original PDF to review it.",
        );
    });
    return () => {
      abandoned = true;
      rendering?.cancel();
      job?.destroy().catch(() => {});
      canvas.remove();
    };
  }, [url, page, width, label, onText]);
  return (
    <div className="pdf-scroll">
      {status && (
        <p className="pdf-message" role="status">
          {status}
        </p>
      )}
      <div className="pdf-page" ref={frame} />
    </div>
  );
}
