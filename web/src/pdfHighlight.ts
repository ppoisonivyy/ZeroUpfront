import { TextLayer } from "pdfjs-dist";
import type { PDFPageProxy, TextContent, TextItem } from "pdfjs-dist/types/src/display/api";
import { locateCitation } from "./pdfCitation";

type State = "matched" | "absent" | "ambiguous" | "unmapped";
export async function highlightPassage(
  surface: HTMLDivElement, viewport: ReturnType<PDFPageProxy["getViewport"]>,
  content: TextContent, quote: string, signal: AbortSignal,
): Promise<State> {
  const items = content.items.filter((item): item is TextItem => "str" in item);
  const match = locateCitation(items, quote);
  if (match.kind !== "matched") return match.kind;
  // Axis-aligned rectangles cannot describe obliquely rotated individual glyphs.
  if (match.slices.some(({ item }) => {
    const [a,b,c,d] = items[item].transform;
    return Math.min(Math.abs(a),Math.abs(b)) > 0.01 * Math.hypot(a,b) ||
      Math.min(Math.abs(c),Math.abs(d)) > 0.01 * Math.hypot(c,d);
  })) return "unmapped";
  const layer = document.createElement("div");
  layer.className = "pdf-citation-text";
  layer.setAttribute("aria-hidden", "true");
  const scale = viewport.scale * viewport.userUnit;
  layer.style.setProperty("--total-scale-factor", String(scale));
  surface.append(layer);
  const textLayer = new TextLayer({ container: layer, viewport, textContentSource: content });
  // TextLayer positions spans in the unrotated crop box, then rotates the layer.
  const [x0, y0, x1, y1] = viewport.viewBox;
  layer.style.width = (x1 - x0) * scale + "px";
  layer.style.height = (y1 - y0) * scale + "px";
  const cancel = () => textLayer.cancel();
  signal.addEventListener("abort", cancel, { once: true });
  try {
    await textLayer.render();
    if (signal.aborted || !surface.isConnected) return "unmapped";
    const bounds = surface.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return "unmapped";
    const marks = document.createDocumentFragment();
    for (const slice of match.slices) {
      const run = textLayer.textDivs[slice.item];
      const text = run?.firstChild;
      if (!text || text.nodeType !== Node.TEXT_NODE || text.textContent !== items[slice.item].str)
        return "unmapped";
      const range = document.createRange();
      range.setStart(text, slice.start);
      range.setEnd(text, slice.end);
      const rects = Array.from(range.getClientRects()).filter(r => r.width > 0 && r.height > 0);
      if (!rects.length) return "unmapped";
      for (const rect of rects) {
        const left = Math.max(bounds.left, rect.left), top = Math.max(bounds.top, rect.top);
        const right = Math.min(bounds.right, rect.right), bottom = Math.min(bounds.bottom, rect.bottom);
        if (right <= left || bottom <= top) return "unmapped";
        const mark = document.createElement("span");
        mark.className = "pdf-quote-mark";
        mark.setAttribute("aria-hidden", "true");
        mark.style.left = (left - bounds.left) / bounds.width * 100 + "%";
        mark.style.top = (top - bounds.top) / bounds.height * 100 + "%";
        mark.style.width = (right - left) / bounds.width * 100 + "%";
        mark.style.height = (bottom - top) / bounds.height * 100 + "%";
        marks.append(mark);
      }
    }
    surface.append(marks);
    return "matched";
  } finally {
    signal.removeEventListener("abort", cancel);
    layer.remove();
  }
}
