"""Rebuild all fictional source PDFs and machine-readable insurer rules."""
import json
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parent
POLICIES = {
    "alder": {
        "name": "Alder Transit Cover", "version": "AT-2026.1", "currency": "THB",
        "limit_thb": 180000, "itemization_from_thb": 50000,
        "clauses": {
            "AT-1": "Inpatient treatment estimates up to THB 180,000 per case may be submitted for pre-check.",
            "AT-2": "For an estimate of THB 50,000 or more, attach a breakdown with each service and its price.",
            "AT-3": "Attach the planned procedure, admission date and member reference to every request.",
        },
        "form_order": ["member_reference", "admission_date", "procedure", "estimated_total_thb"],
    },
    "mango": {
        "name": "Mango Meridian Cover", "version": "MM-2026.1", "currency": "THB",
        "limit_thb": 220000, "excluded_purpose": "solely cosmetic",
        "clauses": {
            "MM-1": "Submit the planned procedure, member reference, admission date and itemized estimate.",
            "MM-2": "Procedures performed solely for cosmetic appearance are excluded.",
            "MM-3": "The inpatient estimate limit is THB 220,000 per case.",
        },
        "form_order": ["procedure", "estimated_total_thb", "admission_date", "member_reference"],
    },
}


def pdf(path, issuer, title, reference, sections):
    path.parent.mkdir(parents=True, exist_ok=True)
    styles = {
        "label": ParagraphStyle("label", fontName="Helvetica-Bold", fontSize=10, leading=15, textColor="#17635F"),
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=26, leading=32, textColor="#152E3C"),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=12, leading=19, textColor="#233944"),
    }
    def line(value, style="body"):
        return Paragraph(escape(value), styles[style])

    story = [line(issuer.upper(), "label"), Spacer(1, 8), line(title, "title"),
             line(reference), Spacer(1, 24)]
    for label, content in sections:
        story.extend([line(label, "label"), line(content), Spacer(1, 12)])

    def footer(canvas, doc):
        canvas.setFillColor(colors.HexColor("#46616C"))
        canvas.setFont("Helvetica", 9)
        canvas.drawString(22*mm, 17*mm, "SYNTHETIC DEMO DOCUMENT  /  ZeroUpfront")
        canvas.drawRightString(188*mm, 17*mm, f"Page {doc.page}")

    SimpleDocTemplate(str(path), pagesize=A4, invariant=1, title=title, author="ZeroUpfront",
                      leftMargin=22*mm, rightMargin=22*mm, topMargin=25*mm).build(story, onFirstPage=footer)


def packet(case_id, insurer, procedure, purpose, charges, itemized=True):
    folder = ROOT / "cases" / case_id
    ref = f"Member DEMO-{case_id}  |  {POLICIES[insurer]['version']}"
    hospital = "Canal Bridge Demo Hospital, Bangkok"
    pdf(folder / "plan.pdf", hospital, "Inpatient treatment plan", ref, [
        ("Admission date", "2026-11-25"), ("Planned procedure", procedure),
        ("Purpose recorded by provider", purpose), ("Source", "International Patient Department")])
    items = [(name, f"THB {value:,}") for name, value in charges]
    total = ("Total estimated charges", f"THB {sum(value for _, value in charges):,}")
    pdf(folder / "estimate.pdf", hospital, "Hospital estimate", ref, (items if itemized else []) + [total])
    if not itemized:
        pdf(folder / "revised-estimate.pdf", hospital, "Revised hospital estimate", ref, items + [total])


if __name__ == "__main__":
    for key, policy in POLICIES.items():
        pdf(ROOT / "policies" / f"{key}.pdf", policy["name"], "Inpatient policy schedule",
            policy["version"] + "  |  Fictional insurer wording", policy["clauses"].items())
    (ROOT / "rulebooks.json").write_text(json.dumps(POLICIES, indent=2) + "\n")
    packet("Z001", "alder", "Knee fracture fixation", "Repair of an accidental fracture.",
           [("Hospital services", 65000), ("Operating team", 45000), ("Supplies", 10000)])
    packet("Z002", "alder", "Wrist fracture fixation", "Repair of an accidental fracture.",
           [("Hospital services", 52000), ("Operating team", 30000)], itemized=False)
    packet("Z003", "mango", "Elective cosmetic rhinoplasty", "Solely cosmetic appearance; no reconstructive indication.",
           [("Hospital services", 50000), ("Operating team", 45000)])
