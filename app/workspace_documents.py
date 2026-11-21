"""Evidence and printable preauthorization requests for the three bundled synthetic cases."""
import hashlib
import io
import json
import re
from datetime import date
from functools import lru_cache
from pathlib import Path
from unicodedata import normalize
from xml.sax.saxutils import escape

from pypdf import PdfWriter
from pypdf.generic import NameObject
import reportlab
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .check_fixtures import ROOT, precheck, read_fixture
from .document_text import contains_identifier, read_document
from .intake_documents import pdf_filename, policy_for_digest, replay_intake


# The bundled cases each have an independent, known encounter. A member/edition alone
# cannot associate a new PDF with an encounter, so uploaded bytes must match its exhibits.
CASE_INSURERS = {"Z001": "alder", "Z002": "alder", "Z003": "mango"}
SERVICE_ROW = re.compile(r"\b(Hospital services|Operating team|Supplies)\s*:?\s*THB\s+([\d,]+)\b")


def _trusted_estimates(case_id):
    if case_id not in CASE_INSURERS:
        raise ValueError("Unknown synthetic case.")
    names = ["estimate.pdf"]
    if case_id == "Z002":
        names += ["revised-estimate.pdf", "scanned-estimate.pdf"]
    folder = ROOT / "cases" / case_id
    return {hashlib.sha256((folder / name).read_bytes()).hexdigest(): folder / name for name in names}


def _check_identity(document, member, edition):
    if not all(contains_identifier(document.text, item) for item in (member, edition)):
        raise ValueError("The member or edition on the exhibit does not match the case.")
    members = re.findall(r"\bDEMO-[A-Z0-9.-]+", document.text, re.IGNORECASE)
    editions = re.findall(r"\b[A-Z]{2}-\d{4}\.[A-Z0-9.-]+", document.text, re.IGNORECASE)
    if set(members) != {member} or set(editions) != {edition}:
        raise ValueError("The exhibit has conflicting member or edition references.")


def _source(role, label, document, anchors):
    first = anchors[0]
    return {"role": role, "label": label, "sha256": document.sha256,
            "page": first["page"], "quote": first["quote"], "clause": first["clause"],
            "method": first["method"],
            "anchors": [{key: anchor[key] for key in ("page", "quote", "clause", "method")}
                        for anchor in anchors]}


def _rulebook(case_id):
    return json.loads((ROOT / "rulebooks.json").read_text())[CASE_INSURERS[case_id]]


def evaluate_estimate(case_id: str, raw: bytes, filename: str | None = None, *, ocr_client=None) -> dict:
    """Evaluate a case-bound fixture. Only an explicitly supplied client can read a known scan."""
    path = _trusted_estimates(case_id).get(hashlib.sha256(raw).hexdigest())
    if path is None:
        raise ValueError("Upload a bundled synthetic estimate for this case. This PDF has no verified encounter binding.")
    label = pdf_filename(path.name if filename is None else filename)
    if path.name == "scanned-estimate.pdf" and ocr_client is None:
        raise ValueError("This image-only estimate needs OCR. Use the digital demo estimate or an explicitly enabled OCR run.")

    policy = _rulebook(case_id)
    source = read_document(ROOT / "policies" / (CASE_INSURERS[case_id] + ".pdf"))
    plan = read_document(path.parent / "plan.pdf")
    estimate = read_document(path, ocr_client)
    member, edition = "DEMO-" + case_id, policy["version"]
    if not contains_identifier(source.text, edition):
        raise ValueError("Policy edition cannot be verified in the source schedule.")
    for exhibit in (plan, estimate):
        _check_identity(exhibit, member, edition)

    clause_refs = {clause: source.locate(quote, clause) for clause, quote in policy["clauses"].items()}
    plan_fields = re.findall(r"Admission date (\d{4}-\d{2}-\d{2}) Planned procedure (.+?) Purpose recorded by provider ", plan.text)
    if len(plan_fields) != 1:
        raise ValueError("A unique planned procedure and admission date are required.")
    admission_date, procedure = plan_fields[0]
    date.fromisoformat(admission_date)
    facts = read_fixture(plan, estimate)
    if facts.total_thb is None or facts.itemized is None:
        raise ValueError("A single verified THB total and reconciled service rows are required.")
    lines = [{"label": row[1], "amount": int(row[2].replace(",", ""))}
             for row in SERVICE_ROW.finditer(estimate.text)]
    if lines and (not facts.itemized or sum(row["amount"] for row in lines) != facts.total_thb
                  or any(row["amount"] <= 0 for row in lines)):
        raise ValueError("Service rows do not reconcile to the estimate.")
    if bool(lines) != facts.itemized:
        raise ValueError("The itemization could not be verified.")
    if path.name == "scanned-estimate.pdf":
        # This specific scan is an image copy of the original. OCR must independently
        # match the critical financial fields of its digital twin before publication.
        twin = read_fixture(plan, read_document(path.parent / "estimate.pdf"))
        if (facts.total_thb, facts.itemized) != (twin.total_thb, twin.itemized):
            raise ValueError("OCR disagrees with the verified synthetic source. Staff review is required.")
    outcome, clause = precheck(policy, facts)
    status = {"missing_evidence": "needs_itemization", "staff_review": "needs_review"}.get(outcome, outcome)
    reasons = {
        "needs_itemization": "The estimate gives a total only. Attach individual service prices to meet the policy requirement.",
        "possible_exclusion": "The provider records a solely cosmetic purpose. Refer the possible exclusion to the insurer.",
        "ready_for_review": "The source documents identify the planned admission and the service prices reconcile to the estimated total.",
        "needs_review": "The current evidence does not settle a required policy check. Staff review is required.",
    }
    primary = clause or next(iter(clause_refs))
    rule_anchors = [clause_refs[primary]] + [ref for key, ref in clause_refs.items() if key != primary]
    plan_anchors = [plan.locate("Planned procedure " + procedure),
                    plan.locate("Admission date " + admission_date),
                    plan.locate("Member " + member + " | " + edition)]
    if facts.purpose_quote:
        purpose = plan.locate("Purpose recorded by provider " + facts.purpose_quote)
        plan_anchors.insert(0 if status == "possible_exclusion" else len(plan_anchors), purpose)
    estimate_anchors = [estimate.locate(f"Total estimated charges THB {facts.total_thb:,}")]
    for row in lines:
        estimate_anchors.append(estimate.locate(f"{row['label']} THB {row['amount']:,}"))
    return {"id": case_id, "procedure": procedure, "insurer": policy["name"], "member": member,
            "admission_date": admission_date, "total": facts.total_thb, "status": status,
            "policy_edition": edition, "clause": clause, "reason": reasons[status], "lines": lines,
            "sources": [_source("policy", source.path.name, source, rule_anchors),
                        _source("estimate", label, estimate, estimate_anchors),
                        _source("plan", plan.path.name, plan, plan_anchors)]}


def seed_cases() -> list[dict]:
    return [evaluate_estimate(case_id, (ROOT / "cases" / case_id / "estimate.pdf").read_bytes())
            for case_id in CASE_INSURERS]


def _reviewed_snapshot(case, originals):
    revision = case.get("revision")
    reviewer = case.get("reviewer")
    if (case.get("status") != "staff_reviewed" or case.get("insurer_status") != "not_sent"
            or not isinstance(reviewer, str) or not reviewer.strip() or not reviewer.isprintable()
            or len(reviewer) > 120 or type(revision) is not int or revision < 1
            or case.get("reviewed_revision", revision) != revision):
        raise ValueError("Export requires an identified staff reviewer for the current unsent revision.")
    history = case.get("history") or []
    current = [entry for entry in history if entry.get("revision") == revision]
    if (len(current) != 1 or any(type(entry.get("revision")) is not int or entry["revision"] > revision
                                 for entry in history) or current[0].get("total") != case.get("total")
            or current[0].get("status") not in {"staff_reviewed", "ready_for_review"}):
        raise ValueError("The review does not match the active revision history.")
    sources = case.get("sources") or []
    by_role = {s.get("role"): s for s in sources}
    if len(sources) != 3 or set(by_role) != {"estimate", "policy", "plan"}:
        raise ValueError("The active source manifest is incomplete.")
    if set(originals) != set(by_role):
        raise ValueError("The saved source files do not match the active source manifest.")
    for role, data in originals.items():
        if not isinstance(data, bytes) or hashlib.sha256(data).hexdigest() != by_role[role].get("sha256"):
            raise ValueError(f"The saved {role} file does not match its reviewed digest.")
    if case.get("input_kind") == "intake":
        verified = replay_intake(case, originals)
    else:
        verified = evaluate_estimate(case["id"], originals["estimate"], by_role["estimate"]["label"])
    if verified["status"] != "ready_for_review" or any(case.get(key) != verified[key] for key in
            ("procedure", "insurer", "member", "admission_date", "total", "policy_edition", "lines", "clause")):
        raise ValueError("The current source evidence does not support the reviewed request.")
    for source in verified["sources"]:
        stored = by_role[source["role"]]
        if any(source[key] != stored.get(key) for key in ("label", "sha256", "quote", "page")):
            raise ValueError("The review evidence differs from the active source manifest.")
    return verified, revision, reviewer.strip()


def _attachment_names(by_role):
    # Keep stable policy and plan names when an uploaded estimate has the same name.
    names = {}
    seen = set()
    for role in ("policy", "plan", "estimate"):
        name = by_role[role]["label"]
        while normalize("NFC", name).casefold() in seen:
            name = f"{role}-{name}"
        names[role] = name
        seen.add(normalize("NFC", name).casefold())
    return names


@lru_cache(maxsize=1)
def _pdf_fonts():
    fonts = Path(reportlab.__file__).parent / "fonts"
    for name, path in (("PacketLatin", fonts / "Vera.ttf"), ("PacketLatinBold", fonts / "VeraBd.ttf"),
                       ("PacketThai", Path(__file__).parent / "fonts/NotoSansThai-Regular.ttf")):
        pdfmetrics.registerFont(TTFont(name, str(path), shapable=True))
    return pdfmetrics.getFont("PacketThai")


class _SourceParagraph(Paragraph):
    def draw(self):
        # Alternate Thai mark glyphs used for shaping have private-use glyph IDs.
        # Preserve the source Unicode for capable text readers and copy/search tools.
        original = getattr(self, "_source_text", self.getPlainText())
        actual = (b"\xfe\xff" + original.encode("utf-16be")).hex()
        self.canv.addLiteral(f"/Span << /ActualText <{actual}> >> BDC")
        super().draw()
        self.canv.addLiteral("EMC")


def _paragraph(value, style):
    value = str(value)
    if value.isascii():
        return Paragraph(escape(value), style)
    thai_font = _pdf_fonts()
    latin = "PacketLatinBold" if "Bold" in style.fontName else "PacketLatin"
    latin_font = pdfmetrics.getFont(latin)
    chunks = []
    for span in re.split(r"([\u0e00-\u0e7f]+)", value):
        if not span:
            continue
        thai = "\u0e00" <= span[0] <= "\u0e7f"
        font = thai_font if thai else latin_font
        if (thai and not font.shapable) or any(ord(char) not in font.face.charWidths for char in span):
            raise ValueError("A character in the source text cannot be rendered reliably in this PDF.")
        chunks.append(f'<font name="{font.fontName}">{escape(span)}</font>')
    shaped = ParagraphStyle("shaped", parent=style, fontName=latin, shaping=1, splitLongWords=1)
    paragraph = _SourceParagraph("".join(chunks), shaped)
    paragraph._source_text = value
    return paragraph


def packet_bytes(case: dict, originals: dict[str, bytes]) -> bytes:
    """Build the reviewed request and gap report with the revision's three original PDFs embedded."""
    verified, revision, reviewer = _reviewed_snapshot(case, originals)
    policy = policy_for_digest(hashlib.sha256(originals["policy"]).hexdigest())
    if not policy:
        raise ValueError("The request has no verified policy mapping.")
    by_role = {source["role"]: source for source in verified["sources"]}
    attachment_names = _attachment_names(by_role)
    buffer = io.BytesIO()
    pdf = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=46, rightMargin=46, topMargin=62,
                            bottomMargin=53, author="ZeroUpfront", invariant=1,
                            title=f"Preauthorization / GOP request - {verified['id']} r{revision}")
    navy = colors.HexColor("#172E37")
    teal = colors.HexColor("#216661")
    rule = colors.HexColor("#C9D7D8")
    styles = {
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=23, leading=28, textColor=navy, spaceAfter=7),
        "section": ParagraphStyle("section", fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=teal, spaceBefore=10, spaceAfter=6),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=14, textColor=navy, spaceAfter=3),
        "label": ParagraphStyle("label", fontName="Helvetica-Bold", fontSize=9, leading=13, textColor=navy),
    }

    def para(value, style="body"):
        return _paragraph(value, styles[style])

    def table(rows):
        result = Table([[para(left, "label"), para(right)] for left, right in rows],
                       colWidths=[135, pdf.width-147], hAlign="LEFT")
        result.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                    ("LINEBELOW", (0, 0), (-1, -1), 0.5, rule),
                                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        return result

    def footer(canvas, doc):
        x, right = 52, A4[0]-52
        canvas.setFillColor(teal)
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawString(x, A4[1]-39, "ZeroUpfront")
        canvas.setFillColor(navy)
        canvas.setFont("Helvetica", 9)
        header = para(f"{verified['id']}  /  Revision {revision}")
        header.wrapOn(canvas, right-x-100, 40)
        header.drawOn(canvas, right-min(header.minWidth()+90, right-x-100), A4[1]-44)
        canvas.setStrokeColor(rule)
        canvas.line(x, 40, right, 40)
        canvas.drawString(x, 25, "Staff-reviewed preauthorization request")
        canvas.drawRightString(right, 25, f"Page {doc.page}")

    fields = {"member_reference": ("Member reference", verified["member"]),
              "admission_date": ("Admission date", verified["admission_date"]),
              "procedure": ("Planned procedure", verified["procedure"]),
              "estimated_total_thb": ("Estimated treatment cost", f"THB {verified['total']:,}")}
    inpatient_plan = by_role["plan"]
    estimate = by_role["estimate"]
    schedule = by_role["policy"]
    if verified["lines"]:
        breakdown = table([(row["label"], f"THB {row['amount']:,}") for row in verified["lines"]])
        financial_check = f"The {len(verified['lines'])} current service prices sum to THB {verified['total']:,}."
    else:
        breakdown = para("The estimate states a total only. Itemization falls below this policy edition's threshold.")
        financial_check = f"The current total is THB {verified['total']:,}."
    story = [para("Preauthorization / GOP request", "title"),
             para(f"Prepared for {verified['insurer']} under policy edition {verified['policy_edition']}."),
             para("The hospital requests review of the planned inpatient treatment and a guarantee of payment for the current estimate."),
             para("Request details", "section"), table([fields[key] for key in policy["form_order"]]),
             para("Hospital estimate", "section"), breakdown,
             para("Coordinator review", "section"),
             table([("Staff reviewer", reviewer), ("Request revision", str(revision)),
                    ("Insurer status", "Unsent. Insurer decision pending.")]),
             PageBreak(), para("Gap report", "title"),
             para(f"Case {verified['id']} / Revision {revision}. The current exhibits satisfy the checked requirements of the verified policy schedule."),
             para("Checks for this request", "section"),
             para(f"The plan records a member, admission date and procedure. {financial_check} The per-case limit is THB {policy['limit_thb']:,}.")]
    if any(event["revision"] < revision and event.get("status") == "needs_itemization"
           for event in case["history"]):
        story.append(para("The earlier estimate lacked service prices. The current itemized estimate resolves that gap."))
    story.append(para("Current exhibits", "section"))
    story.append(para("The three original PDFs are embedded in this packet. Open the attachments panel to view them."))
    for display, source in (("Treatment plan", inpatient_plan), ("Hospital estimate", estimate), ("Policy schedule", schedule)):
        story.append(para(f"{display} - {source['label']}, p. {source['page']} ({source['method']})", "label"))
        attached_name = attachment_names[source["role"]]
        if attached_name != source["label"]:
            story.append(para(f"Embedded as {attached_name}"))
        if source is not schedule:
            for ref in source["anchors"]:
                story.append(para(f"p. {ref['page']}  |  {ref['quote']}"))
        story.append(Spacer(1, 4))
    story.append(para("Governing clauses", "section"))
    for ref in schedule["anchors"]:
        story.append(para(f"{ref['clause']}  |  p. {ref['page']}  |  {ref['quote']}"))
    if verified.get("manual_review"):
        story.append(para("Policy checks confirmed by staff", "section"))
        for finding in verified["manual_review"]["checks"]:
            policy_ref, support = finding["policy"], finding["support"]
            story.append(para(f"{finding['requirement']} - {finding['result']}. "
                              f"{attachment_names['policy']} p. {policy_ref['page']} / "
                              f"{attachment_names[support['role']]} p. {support['page']}: {support['quote']}"))
    story.extend([para("Outstanding decision", "section"),
                  para("The insurer must decide whether to issue a guarantee of payment and specify any authorized amount and conditions.")])
    pdf.build(story, onFirstPage=footer, onLaterPages=footer)
    return _embed_originals(buffer, originals, attachment_names)


def _embed_originals(buffer, originals, attachment_names):
    buffer.seek(0)
    packet = PdfWriter(clone_from=buffer)
    for role, name in attachment_names.items():
        attachment = packet.add_attachment(name, originals[role])
        attachment.subtype = NameObject("/application/pdf")
    output = io.BytesIO()
    packet.write(output)
    return output.getvalue()


def clarification_bytes(case: dict, originals: dict[str, bytes]) -> bytes:
    """Print the unresolved questions and their verified source quotes for the current intake."""
    revision = case.get("revision")
    if (case.get("input_kind") != "intake" or not case.get("manual_review") or type(revision) is not int
            or revision < 1 or case.get("status") not in {"needs_review", "needs_itemization", "possible_exclusion"}
            or not any(h.get("revision") == revision for h in case.get("history", []))
            or any(h.get("revision", 0) > revision for h in case.get("history", []))):
        raise ValueError("Record evidence on the current unresolved revision before preparing a clarification request.")
    verified = replay_intake(case, originals)
    source_by_role = {s["role"]: s for s in verified["sources"]}
    saved_digests = {s["role"]: s["sha256"] for s in case["sources"]}
    if (not verified.get("clarification_available") or verified["status"] != case["status"] or
            {s["role"]: s["sha256"] for s in verified["sources"]} != saved_digests):
        raise ValueError("The current sources no longer support this clarification request.")
    body = ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=15, spaceAfter=4)
    title = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=23, leading=28, spaceAfter=13)
    heading = ParagraphStyle("heading", fontName="Helvetica-Bold", fontSize=13, leading=17, spaceBefore=9, spaceAfter=4)
    story = [_paragraph("Insurance clarification request", title),
             _paragraph(f"Case {case['id']} / Revision {revision}", body),
             _paragraph("Please clarify the open insurance questions before the hospital prepares a payment guarantee request. Coverage and payment remain unconfirmed.", body),
             _paragraph("Hospital intake details", heading),
             _paragraph(f"Member {case['member']} / {case['insurer']} / {case['policy_edition']}", body),
             _paragraph(f"Planned admission {case['admission_date']} / {case['procedure']}", body),
             _paragraph("Open questions", heading)]
    for issue in verified["issues"]:
        story.append(_paragraph(issue, body))
    names = _attachment_names(source_by_role)
    def citation(ref):
        return _paragraph(f"{names[ref['role']]} / p. {ref['page']} ({ref['method']}) - {ref['quote']}", body)
    manual = verified["manual_review"]
    for check in manual["checks"]:
        story.extend([_paragraph(check["requirement"], heading),
                      _paragraph(f"Staff finding: {check['result'].replace('_', ' ')}", body),
                      citation(check["policy"]), citation(check["support"])])
    if manual["fields"]:
        story.append(_paragraph("Fields checked by staff", heading))
        for key, ref in manual["fields"].items():
            story.extend([_paragraph(key.replace("_", " "), body), citation(ref)])
    story.extend([_paragraph("Original exhibits", heading),
                  _paragraph("The policy, treatment plan and current estimate are embedded. Open the attachments panel to inspect them.", body)])
    stream = io.BytesIO()
    SimpleDocTemplate(stream, pagesize=A4, title="Insurance clarification request", author="ZeroUpfront",
                      leftMargin=50, rightMargin=50, topMargin=48, bottomMargin=48, invariant=1).build(story)
    return _embed_originals(stream, originals, names)
