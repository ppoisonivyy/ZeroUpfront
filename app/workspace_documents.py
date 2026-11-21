"""Evidence and printable preauthorization requests for the three bundled synthetic cases."""
import hashlib
import io
import json
import re
from datetime import date
from unicodedata import normalize
from xml.sax.saxutils import escape

from pypdf import PdfWriter
from pypdf.generic import NameObject
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .check_fixtures import ROOT, precheck, read_fixture
from .document_text import contains_identifier, read_document


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


def _filename(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 160
            or "/" in value or "\\" in value or not value.lower().endswith(".pdf")
            or not value.isprintable()):
        raise ValueError("Provide a PDF filename of up to 160 characters without directories.")
    return value


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
    label = _filename(path.name if filename is None else filename)
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


def packet_bytes(case: dict, originals: dict[str, bytes]) -> bytes:
    """Build the reviewed request and gap report with the revision's three original PDFs embedded."""
    verified, revision, reviewer = _reviewed_snapshot(case, originals)
    policy = _rulebook(verified["id"])
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
        # Standard printable English forms. Preserve unsupported filename/name characters
        # as explicit Unicode escapes rather than silently substituting another character.
        visible = str(value).encode("cp1252", "backslashreplace").decode("cp1252")
        return Paragraph(escape(visible), styles[style])

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
        canvas.drawRightString(right, A4[1]-39, f"{verified['id']}  /  Revision {revision}")
        canvas.setStrokeColor(rule)
        canvas.line(x, 40, right, 40)
        canvas.drawString(x, 25, "Synthetic demonstration  /  Staff-reviewed request")
        canvas.drawRightString(right, 25, f"Page {doc.page}")

    fields = {"member_reference": ("Member reference", verified["member"]),
              "admission_date": ("Admission date", verified["admission_date"]),
              "procedure": ("Planned procedure", verified["procedure"]),
              "estimated_total_thb": ("Estimated treatment cost", f"THB {verified['total']:,}")}
    inpatient_plan = by_role["plan"]
    estimate = by_role["estimate"]
    schedule = by_role["policy"]
    story = [para("Preauthorization / GOP request", "title"),
             para(f"Prepared for {verified['insurer']} under policy edition {verified['policy_edition']}."),
             para("The hospital requests review of the planned inpatient treatment and a guarantee of payment for the itemized estimate."),
             para("Request details", "section"), table([fields[key] for key in policy["form_order"]]),
             para("Itemized hospital estimate", "section"),
             table([(row["label"], f"THB {row['amount']:,}") for row in verified["lines"]]),
             para("Coordinator review", "section"),
             table([("Staff reviewer", reviewer), ("Request revision", str(revision)),
                    ("Insurer status", "Unsent. Insurer decision pending.")]),
             PageBreak(), para("Gap report", "title"),
             para(f"Case {verified['id']} / Revision {revision}. The current exhibits satisfy the checked requirements of the synthetic policy."),
             para("Checks for this request", "section"),
             para(f"The plan records a member, admission date and procedure. The {len(verified['lines'])} current service prices sum to THB {verified['total']:,}, within the THB {policy['limit_thb']:,} per-case limit.")]
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
    story.extend([para("Outstanding decision", "section"),
                  para("The insurer must decide whether to issue a guarantee of payment and specify any authorized amount and conditions.")])
    pdf.build(story, onFirstPage=footer, onLaterPages=footer)
    buffer.seek(0)
    packet = PdfWriter(clone_from=buffer)
    for role, name in attachment_names.items():
        attachment = packet.add_attachment(name, originals[role])
        attachment.subtype = NameObject("/application/pdf")
    output = io.BytesIO()
    packet.write(output)
    return output.getvalue()
