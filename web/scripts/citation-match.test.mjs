import assert from "node:assert/strict";
import test from "node:test";
import { locateCitation } from "../src/pdfCitation.ts";

const item = (str, x = 20, y = 800, width = 120) =>
  ({ str, dir: "ltr", transform: [10, 0, 0, 10, x, y], width, height: 10, hasEOL: false });
test("matches the exact quoted characters, normalized whitespace, across wrapped lines", () => {
  const a = item("§4.2  A signed report"), b = item("is required for admission.", 20, 788);
  assert.deepEqual(locateCitation([a,b], "A signed  report is required"), {
    kind:"matched", slices:[{item:0,start:6,end:21},{item:1,start:0,end:11}]
  });
});
test("recognizes a word segmented by a change of font and Thai Unicode", () => {
  assert.equal(locateCitation([item("pre", 20, 800, 14), item("approval", 34)], "preapproval").kind, "matched");
  assert.equal(locateCitation([item("อัตราค่าห้อง")], "อัตราค่าห้อง").kind, "matched");
});
test("rejects mismatches, duplicate quotes and substrings of longer words", () => {
  assert.equal(locateCitation([item("not covered")], "fully covered").kind, "absent");
  assert.equal(locateCitation([item("not covered, not covered")], "not covered").kind, "ambiguous");
  assert.equal(locateCitation([item("unapproved")], "approved").kind, "absent");
  assert.equal(locateCitation([], "receipt").kind, "absent");
});
test("never joins adjacent columns, overlapping runs or distant paragraphs", () => {
  for (const next of [item("approved", 280), item("approved", 280, 788), item("approved",20,750), item("approved",24)]) {
    assert.equal(locateCitation([item("Claim",20,800,30),next], "Claim approved").kind, "absent");
  }
});
