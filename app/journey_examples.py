"""Wholly fictional, reproducible hospital packets and payer letters for local rehearsals."""
from io import BytesIO
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas


POLICIES = Path(__file__).resolve().parents[1] / "fixtures" / "policies"
LOCAL_EXAMPLES = {"missing-estimate", "possible-exclusion", "partial-guarantee", "admission-mismatch"}
NAMES = {"policy": "policy.pdf", "plan": "plan.pdf", "estimate": "estimate.pdf"}


def pdf(lines, *, image=False, form=False):
    stream = BytesIO()
    canvas = Canvas(stream, invariant=1)
    canvas.setAuthor("ZeroUpfront synthetic rehearsal")
    canvas.setTitle("Fictional case exhibit")
    text = canvas.beginText(45, 765)
    for line in lines:
        text.textLine(line)
    canvas.drawText(text)
    if image:
        bitmap = Image.new("L", (120, 70), color=210)
        canvas.drawImage(ImageReader(bitmap), 45, 450, width=120, height=70)
    if form:
        canvas.acroForm.textfield(name="coverage_exception", value="Pending additional authorization", x=45, y=380)
    canvas.showPage()
    canvas.save()
    return stream.getvalue()


def exhibits(scenario="clean"):
    cosmetic = scenario in {"possible-exclusion", "unknown-indication"}
    policy_name, edition = ("mango", "MM-2026.1") if cosmetic else ("alder", "AT-2026.1")
    meta = dict(member="EXAMPLE-2402", insurer="Mango Meridian Cover" if cosmetic else "Alder Transit Cover",
                policy_edition=edition, procedure="Elective rhinoplasty" if cosmetic else "Wrist fracture fixation",
                admission_date="2026-12-11")
    identifiers = ["Member ID: " + meta["member"], "Policy edition: " + edition, "Encounter ID: EXAMPLE-VISIT-42"]
    purpose = "Solely cosmetic appearance; no reconstructive indication." if cosmetic else "Repair of an accidental fracture."
    if scenario == "unknown-indication":
        purpose = "Indication pending medical report."
    plan = ["Inpatient treatment plan", *identifiers, "Admission date: " + meta["admission_date"],
            "Planned procedure: " + meta["procedure"], "Purpose recorded by provider: " + purpose]
    if scenario == "inactive-plan":
        plan.append("Provider name: Example Hospital - cancelled policy")
    if scenario == "outpatient":
        plan[0] = "Treatment plan"
        plan.append("Care setting: Outpatient")
    if scenario == "conflicting-admission-date":
        plan.append("Admission date: 2026-12-12")
    if scenario == "conflicting-procedure":
        plan.append("Planned procedure: Different procedure")
    identity = {"wrong-member": ("EXAMPLE-2402", "EXAMPLE-24020"), "wrong-edition": (edition, edition + "-OLD"),
                "wrong-encounter": ("EXAMPLE-VISIT-42", "EXAMPLE-VISIT-424")}.get(scenario)
    if identity:
        identifiers = [line.replace(*identity) for line in identifiers]
    if scenario == "missing-member":
        identifiers = identifiers[1:]
    if scenario == "missing-edition":
        identifiers = [line for line in identifiers if not line.startswith("Policy edition:")]
    services, team, total = (180000, 30000, 210000) if scenario == "over-limit" else (52000, 30000, 82000)
    rows = [] if scenario == "missing-estimate" else [f"Hospital services: THB {services:,}", f"Operating team: THB {team:,}"]
    estimate = ["Cost estimate", *identifiers, *rows, f"Total estimated charges: THB {total:,}"]
    if scenario == "duplicate-total":
        estimate.append(estimate[-1])
    if scenario == "arithmetic-error":
        estimate[-1] = "Total estimated charges: THB 82,500"
    if scenario == "mixed-currency":
        estimate[-2] = estimate[-2].replace("THB", "USD")
    if scenario == "unsupported-currency":
        estimate = [line.replace("THB", "USD") for line in estimate]
    if scenario == "unreadable-scan":
        estimate = []
    unknown = scenario == "unknown-policy"
    policy = pdf(["Fictional hospital agreement", "Benefits and exceptions require individual payer confirmation."]) if unknown else (
        POLICIES / (policy_name + ".pdf")).read_bytes()
    docs = {"policy": policy, "plan": pdf(plan),
            "estimate": pdf(estimate, image=scenario in {"unreadable-scan", "mixed-scan"}, form=scenario == "form-field")}
    if scenario in {"reissued-policy", "embedded-rider"}:
        role = "policy" if scenario == "reissued-policy" else "plan"
        writer = PdfWriter(clone_from=PdfReader(BytesIO(docs[role])))
        writer.add_metadata({"/Title": "Supplemented fictional schedule"})
        if scenario == "embedded-rider":
            writer.add_attachment("rider.pdf", pdf(["Attached rider. Obtain mandatory additional review."]))
        stream = BytesIO()
        writer.write(stream)
        docs[role] = stream.getvalue()
    return meta, docs


def payer_reply(outcome, **updates):
    data = {"outcome": outcome, "reference": "DEMO-PAYER-829", "confirmed": True,
            "terms": {"query": "Please return the itemized surgical estimate.",
                      "denied": "The payer has declined this admission.",
                      "authorized": "Treatment is authorized. No payment guarantee has been issued.",
                      "partial": "The patient pays charges beyond the recorded amount.",
                      "guaranteed": "The inpatient procedure is guaranteed within the amount and validity shown."}[outcome]}
    if outcome in {"partial", "guaranteed"}:
        data.update(amount="60000" if outcome == "partial" else "82000", currency="THB",
                    facility="Canal Bridge Demo Hospital", covered_procedure="Wrist fracture fixation", covered_member="EXAMPLE-2402",
                    valid_from="2026-12-09", valid_until="2026-12-15",
                    patient_share="Amounts above the payer limit remain payable.")
    data.update(updates)
    lines = ["Synthetic demonstration. No actual insurance or clinical decision.",
             "Payer: Alder Transit Cover", "Member: EXAMPLE-2402", "Encounter ID: EXAMPLE-VISIT-42"]
    lines.extend(f"{key.replace('_', ' ')}: {value}" for key, value in data.items() if key != "confirmed")
    return data, pdf(lines)


def admission(**updates):
    data = dict(actual_procedure="Wrist fracture fixation", actual_member="EXAMPLE-2402",
                actual_admission_date="2026-12-11", actual_amount="82000", currency="THB",
                actual_facility="Canal Bridge Demo Hospital", letter_confirmed=True,
                notes="Coordinator compared the original payer letter with this admission.")
    return data | updates
