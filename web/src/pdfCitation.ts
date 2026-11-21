// Map a unique quoted passage back to the original PDF.js text items and UTF-16 offsets.
import type { TextItem } from "pdfjs-dist/types/src/display/api";

type Item = Pick<TextItem, "str" | "dir" | "transform" | "width" | "height" | "hasEOL">;
type Slice = { item: number; start: number; end: number };
type Result = { kind: "matched"; slices: Slice[] } | { kind: "absent" | "ambiguous" | "unmapped" };

function boundary(previous: Item, next: Item, lineStart: Item): "split" | "wrap" | "space" | "join" {
  const [a, b, , , x, y] = previous.transform;
  const [na, nb, , , nx, ny] = next.transform;
  const length = Math.hypot(a, b);
  const nextLength = Math.hypot(na, nb);
  if (!length || !nextLength || previous.dir !== "ltr" || next.dir !== "ltr") return "split";
  const ux = a / length, uy = b / length;
  if ((na * ux + nb * uy) / nextLength < 0.998) return "split";
  const em = Math.max(previous.height, next.height, 1);
  const along = (nx - x) * ux + (ny - y) * uy;
  const up = (ny - y) * ux - (nx - x) * uy;
  if (Math.abs(up) < 0.32 * em) {
    const gap = along - previous.width;
    if (previous.hasEOL || gap < -0.3 * em || gap > 1.4 * em) return "split";
    return gap > 0.13 * em ? "space" : "join";
  }
  const indent = (nx - lineStart.transform[4]) * ux + (ny - lineStart.transform[5]) * uy;
  // Join ordinary wrapped lines. A distant column, header, or block is a hard break.
  return up <= -0.5 * em && up >= -1.85 * em && Math.abs(indent) < 1.6 * em ? "wrap" : "split";
}

const word = /[\p{L}\p{M}\p{N}]/u;
const limit = 250_000;

export function locateCitation(items: Item[], rawQuote: string): Result {
  const quote = rawQuote.replace(/\s+/gu, " ").trim();
  if (!quote) return { kind: "absent" };
  if (items.length > 25_000 || items.reduce((n, item) => n + item.str.length, 0) > limit)
    return { kind: "unmapped" };
  let text = "", previous: Item | undefined, lineStart: Item | undefined;
  const itemAt: number[] = [], offsetAt: number[] = [];
  function append(value: string, item: number, offset: number) {
    if (value === " " && text.endsWith(" ")) return;
    text += value;
    itemAt.push(item);
    offsetAt.push(offset);
  }
  for (const [index, item] of items.entries()) {
    if (!item.str.trim()) {
      if (item.str) append(" ", -1, -1);
      continue;
    }
    if (previous && lineStart) {
      const edge = boundary(previous, item, lineStart);
      if (edge !== "join") append(edge === "split" ? "\u0000" : " ", -1, -1);
      if (edge === "split" || edge === "wrap") lineStart = item;
    } else lineStart = item;
    for (let offset = 0; offset < item.str.length; offset++) {
      const c = item.str[offset];
      append(/\s/u.test(c) ? " " : c, index, offset);
    }
    previous = item;
  }
  let match = -1;
  for (let pos = text.indexOf(quote); pos >= 0; pos = text.indexOf(quote, pos + 1)) {
    const before = text[pos - 1] ?? "", after = text[pos + quote.length] ?? "";
    if ((word.test(before) && word.test(quote[0])) || (word.test(after) && word.test(quote.at(-1)!))) continue;
    // A numeric excerpt must not match only part of a decimal or grouped amount.
    if ((/\d$/.test(quote) && /^[.,]\d/.test(text.slice(pos + quote.length, pos + quote.length + 2))) ||
        (/^\d/.test(quote) && /\d[.,]$/.test(text.slice(Math.max(0, pos - 2), pos)))) continue;
    if (match >= 0) return { kind: "ambiguous" };
    match = pos;
  }
  if (match < 0) return { kind: "absent" };
  const slices: Slice[] = [];
  for (let i = match; i < match + quote.length; i++) {
    if (itemAt[i] < 0) continue;
    const last = slices.at(-1);
    if (last?.item === itemAt[i]) last.end = offsetAt[i] + 1;
    else slices.push({ item: itemAt[i], start: offsetAt[i], end: offsetAt[i] + 1 });
  }
  return slices.length ? { kind: "matched", slices } : { kind: "unmapped" };
}
