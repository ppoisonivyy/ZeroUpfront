"""Compare discharge exhibits with an actual payer letter. Staff and payer actions live outside this checker."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
import hashlib
import io
import json
from pathlib import Path
import re

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import PageBreak, SimpleDocTemplate

from .document_text import normalized
from .finance import AMOUNT, money
from .intake_documents import PLACEHOLDERS, _read, pdf_filename
from .workspace_documents import _embed_originals, _paragraph

ROOT = Path(__file__).resolve().parents[1] / "fixtures/discharge"
TITLES = {"bill": "Final itemized hospital bill", "summary": "Inpatient discharge summary",
          "letter": "Payer preauthorization letter", "records": "Hospital supporting records"}
OWNERS = {"bill": "Hospital billing", "summary": "Clinical team", "letter": "Payer liaison", "records": "Medical records"}
COMMON = {"Member", "Encounter", "Facility", "Document ID"}
DATE_FIELDS = {"Admission date", "Discharge date"}
FIELDS = {"bill": DATE_FIELDS | {"Charge", "Credit", "Final bill total", "Recorded patient share"},
          "summary": DATE_FIELDS | {"Performed procedure", "Attending service", "Hospital course", "Disposition", "Follow-up", "Summary status"},
          "letter": {"Payer", "Letter status", "Issued on", "Valid from", "Valid through", "Authorized procedure",
                     "Authorized billed-charge ceiling", "Documented fixed patient share", "Final review"},
          "records": DATE_FIELDS | {"Procedure record", "Service evidence", "Credit evidence", "Record status", "Letter received on"}}
ADVERSE = re.compile(r"\b(?:expired|revoked|suspended|void(?:ed)?|withdrawn|inactive|excluded|denied|pending|"
                     r"not valid|not active|not covered|not authorized|rider|addendum|superseded|cancelled)\b", re.I)
MONEY = re.compile(rf"(THB|USD|EUR) ({AMOUNT})\Z")
REPEATABLE = {"Charge", "Credit", "Service evidence", "Credit evidence"}
ROLE_ORDER = ("bill", "summary", "letter", "records")
LETTER_KINDS = {"Payer preauthorization letter": ("Preauthorization", "preauthorization"),
                "Initial capped guarantee of payment": ("Initial capped guarantee", "initial_gop")}


@dataclass(frozen=True)
class Line:
    value: str
    ref: dict


class Review:
    def __init__(self):
        self.findings = {}
        self.checks = []

    def flag(self, code, owner, message, *refs, severity="blocker"):
        finding = self.findings.setdefault(code, {"code": code, "severity": severity, "owner": owner,
                                                 "message": message, "sources": []})
        for ref in refs:
            if ref and ref not in finding["sources"] and len(finding["sources"]) < 8:
                finding["sources"].append(ref)

    def checked(self, code, message, *refs):
        self.checks.append({"code": code, "message": message, "sources": [r for r in refs if r]})


def _iso(value):
    try:
        converted = date.fromisoformat(value)
        return converted if converted.isoformat() == value else None
    except (TypeError, ValueError):
        return None


def _meta(metadata):
    result = {}
    for key in ("id", "member", "encounter", "facility", "insurer", "procedure", "admission_date", "discharge_date"):
        value = metadata.get(key) or (metadata.get("encounter_id") if key == "encounter" else None)
        if (not isinstance(value, str) or not value.strip() or len(value) > 220
                or not value.isprintable() or value.strip().casefold() in PLACEHOLDERS):
            raise ValueError(f"Provide the discharge case {key}.")
        result[key] = value.strip()
    if (not _iso(result["admission_date"]) or not _iso(result["discharge_date"])
            or result["admission_date"] > result["discharge_date"]):
        raise ValueError("Provide the actual admission and discharge dates in chronological YYYY-MM-DD order.")
    result["as_of"] = metadata.get("as_of") or date.today().isoformat()
    if not _iso(result["as_of"]):
        raise ValueError("Use a YYYY-MM-DD review date.")
    return result


def _single(fields, role, name, review):
    entries = fields[role].get(name, [])
    if len(entries) != 1:
        context = entries[:2] if entries else fields[role].get("Document ID", [])[:1]
        review.flag("missing_or_ambiguous_field", OWNERS[role], f"Confirm the unique {name.lower()} on the {role}.",
                    *(entry.ref for entry in context))
        return None
    return entries[0]


def _extract(role, doc, meta, review):
    fields, anchors = defaultdict(list), []
    document_ids = set()
    for page in doc.pages:
        if not page.text.strip():
            continue
        text = [normalized(s) for s in page.text.splitlines() if s.strip()]
        page_refs = {}
        for line in text:
            excerpt = line if len(line) <= 650 else (line[:650].rsplit(" ", 1)[0] if " " in line[:650] else line[:649])
            ref = {"role": role, "page": page.number, "quote": excerpt,
                   "method": "ocr" if page.ocr else "digital"}
            if len(line) > 650:
                review.flag("unrecognized_layout", OWNERS[role], f"Inspect the unrecognized {role} layout.", ref)
                continue
            if len(anchors) < 180:
                anchors.append(ref)
            is_heading = line == TITLES[role] or (role == "letter" and line in LETTER_KINDS)
            if is_heading or line.startswith("Page "):
                page_refs.setdefault("heading" if is_heading else "pagination", []).append(ref)
                if role == "letter" and is_heading:
                    fields["_letter_heading"].append(Line(line, ref))
                continue
            if line == "Fictional discharge exhibit / ZeroUpfront":
                continue
            key, sep, value = line.partition(": ")
            if not sep or not value or key not in (FIELDS[role] | COMMON):
                review.flag("unrecognized_layout", OWNERS[role], f"Inspect additional or unrecognized wording in the {role}.", ref)
                continue
            if ADVERSE.search(value):
                review.flag("unsettled_document", OWNERS[role], "An exhibit records a limitation or unsettled status. Confirm the active terms.", ref)
            fields[key].append(Line(value, ref))
            if key in COMMON:
                page_refs.setdefault(key, []).append(ref)
            if key == "Document ID":
                document_ids.add(value)
        for key in ("heading", "pagination", *sorted(COMMON)):
            seen = page_refs.get(key, [])
            if len(seen) != 1:
                review.flag("page_identity", OWNERS[role], "A source page lacks an unambiguous role, exhibit ID, identity or page number.",
                            *(seen or [next((r for r in reversed(anchors) if r["page"] == page.number), None)]))
        for key, expected in (("pagination", f"Page {page.number} of {len(doc.pages)}"),
                              ("Member", "Member: " + meta["member"]), ("Encounter", "Encounter: " + meta["encounter"]),
                              ("Facility", "Facility: " + meta["facility"])):
            seen = page_refs.get(key, [])
            if any(ref["quote"] != expected for ref in seen):
                code = {"pagination": "page_order", "Member": "member_mismatch", "Encounter": "encounter_mismatch",
                        "Facility": "facility_mismatch"}[key]
                review.flag(code, OWNERS[role], f"The {role} page {key.lower()} does not match this discharge encounter.", *seen)
    if len(document_ids) > 1:
        review.flag("page_identity", OWNERS[role], "Pages identify different exhibits within one source file.",
                    *(line.ref for line in fields.get("Document ID", [])))
    for key, entries in fields.items():
        if key not in COMMON | REPEATABLE | {"_letter_heading"} and len(entries) > 1:
            review.flag("missing_or_ambiguous_field", OWNERS[role], f"Multiple {key.lower()} entries need clarification.", *(s.ref for s in entries[:2]))
    return fields, anchors


def _amount(value):
    match = MONEY.fullmatch(value)
    if not match:
        return None
    try:
        return match[1], int(money(match[2]) * 100)
    except ValueError:
        return None


def _amount_field(fields, role, name, review, units):
    entry = _single(fields, role, name, review)
    if not entry:
        return None, None
    value = _amount(entry.value)
    if value is None:
        review.flag("unsupported_amount", OWNERS[role], "Confirm the stated currency, precision and meaning of the source amount.", entry.ref)
        return None, entry.ref
    units.add(value[0])
    return value[1], entry.ref


def _financial(fields, meta, review):
    units = set()
    for role, keys in (("bill", ("Charge", "Credit", "Final bill total", "Recorded patient share")),
                       ("letter", ("Authorized billed-charge ceiling", "Documented fixed patient share"))):
        for key in keys:
            for entry in fields[role].get(key, []):
                units.update(re.findall(r"(?<![A-Z])([A-Z]{3})\s+(?=[+-]?\d)", entry.value))
                if "$" in entry.value:
                    units.add("unspecified dollar")
    total, bill_ref = _amount_field(fields, "bill", "Final bill total", review, units)
    bill_share, bill_share_ref = _amount_field(fields, "bill", "Recorded patient share", review, units)
    cap, cap_ref = _amount_field(fields, "letter", "Authorized billed-charge ceiling", review, units)
    letter_share, share_ref = _amount_field(fields, "letter", "Documented fixed patient share", review, units)
    if total == 0 or cap == 0:
        review.flag("zero_amount", OWNERS["bill"], "Confirm whether a positive claim or billed-charge ceiling exists.", bill_ref, cap_ref)
    charges, credits, fingerprints = {}, {}, {}
    gross = credit = 0
    amount_valid = True
    credited_per_charge = defaultdict(int)
    charge_dates = {}
    for key in ("Charge", "Credit"):
        for entry in fields["bill"].get(key, []):
            parts = [part.strip() for part in entry.value.split("|")]
            if len(parts) != (6 if key == "Charge" else 5):
                review.flag("unsupported_bill_row", OWNERS["bill"], "Verify the item ID, dated service, quantity and money columns on the bill.", entry.ref)
                amount_valid = False
                continue
            code = parts[0]
            index = charges if key == "Charge" else credits
            if not re.fullmatch(r"[A-Z0-9-]{2,32}", code):
                review.flag("invalid_line_id", OWNERS["bill"], "Ask billing to confirm the unreadable item identifier on this line.", entry.ref)
                amount_valid = False
                continue
            original = charges.get(code) or credits.get(code)
            if original:
                review.flag("duplicate_line", OWNERS["bill"],
                            f"Item {code} appears more than once. Ask billing whether both entries belong on the final invoice.",
                            original[1], entry.ref)
                amount_valid = False
                continue
            day = parts[1] if key == "Charge" else parts[2]
            if not _iso(day) or not meta["admission_date"] <= day <= meta["discharge_date"]:
                review.flag("service_date", OWNERS["bill"], "A dated charge or credit falls outside the recorded stay.", entry.ref)
            if key == "Charge":
                _, _, service, qty, unit, net = parts
                u, n = _amount(unit), _amount(net)
                if not u or not n or not re.fullmatch(r"[1-9]\d{0,5}", qty) or not service:
                    review.flag("unsupported_bill_row", OWNERS["bill"], "Confirm each service quantity, unit price and line total.", entry.ref)
                    amount_valid = False
                    continue
                units.update((u[0], n[0]))
                if int(qty) * u[1] != n[1]:
                    review.flag("unit_mismatch", OWNERS["bill"], "Quantity times unit price differs from the stated line total.", entry.ref)
                    amount_valid = False
                signature = (day, service.casefold(), qty, u, n)
                if signature in fingerprints:
                    review.flag("possible_duplicate", OWNERS["bill"], "Two item IDs describe the same dated service and price. Confirm whether both occurred.",
                                fingerprints[signature], entry.ref, severity="review")
                fingerprints[signature] = entry.ref
                index[code] = (service, entry.ref, n[1])
                charge_dates[code] = day
                gross += n[1]
            else:
                _, target, _, amount, reason = parts
                n = _amount(amount)
                if not n or not n[1] or not reason:
                    review.flag("unsupported_bill_row", OWNERS["bill"], "Verify the credit amount, target item and reason.", entry.ref)
                    amount_valid = False
                    continue
                units.add(n[0])
                if target not in charges:
                    review.flag("orphan_credit", OWNERS["bill"], "A credit references a charge absent from the itemized bill.", entry.ref)
                    amount_valid = False
                elif (credited_per_charge[target] + n[1]) > charges[target][2]:
                    review.flag("excess_credit", OWNERS["bill"], "Credits exceed their referenced charge.", charges[target][1], entry.ref)
                    amount_valid = False
                if target in charge_dates and day < charge_dates[target]:
                    review.flag("credit_before_charge", OWNERS["bill"],
                                f"Credit {code} predates its linked charge {target}. Ask billing to confirm both dates.",
                                charges[target][1], entry.ref)
                    amount_valid = False
                credited_per_charge[target] += n[1]
                index[code] = (reason, entry.ref, n[1])
                credit += n[1]
    if not charges:
        review.flag("missing_itemization", OWNERS["bill"], "Supply dated service rows for the final bill.", bill_ref)
        amount_valid = False
    for key, index in (("Service evidence", charges), ("Credit evidence", credits)):
        support = defaultdict(list)
        for row in fields["records"].get(key, []):
            parts = [part.strip() for part in row.value.split("|")]
            if len(parts) == 2:
                support[parts[0]].append((parts[1], row.ref))
            else:
                review.flag("missing_support", OWNERS["records"], "A supporting record has an unreadable service reference.", row.ref)
        for code, (description, row_ref, _) in index.items():
            rows = support.get(code, [])
            if [s[0] for s in rows] != [description]:
                review.flag("missing_support", OWNERS["records"], "A billed service or credit lacks one matching supporting record.",
                            row_ref, *(s[1] for s in rows))
        for code in set(support) - set(index):
            review.flag("unmatched_record", OWNERS["records"], "A supporting record references an item absent from the bill.",
                        *(s[1] for s in support[code]))
    if len(units) > 1:
        refs = [r for r in (bill_ref, cap_ref, bill_share_ref, share_ref) if r]
        for entry in fields["bill"].get("Charge", []):
            if any(unit in entry.value for unit in units if not bill_ref or unit not in bill_ref["quote"]):
                refs.append(entry.ref)
        review.flag("mixed_currency", "Hospital billing", "The exhibits state different currencies. Obtain comparable original terms or a documented conversion.", *refs)
        return None, None, None, None
    if amount_valid and total is not None:
        if total != gross - credit:
            review.flag("total_mismatch", OWNERS["bill"], "The final bill total differs from the service rows less the identified credits.", bill_ref,
                        *(entry.ref for entry in fields["bill"].get("Credit", [])))
        else:
            review.checked("total_reconciled", "Service rows and identified credits reconcile to the printed final bill total.", bill_ref)
    if total is not None and cap is not None and total > cap:
        review.flag("over_cap", OWNERS["letter"], "The final bill exceeds the letter's stated billed-charge ceiling. Request payer review.", bill_ref, cap_ref)
    if bill_share is not None and letter_share is not None and bill_share != letter_share:
        review.flag("share_mismatch", OWNERS["letter"], "The fixed patient share on the letter differs from the share recorded on the bill.", bill_share_ref, share_ref)
    if ((total is not None and bill_share is not None and bill_share > total)
            or (cap is not None and letter_share is not None and letter_share > cap)):
        review.flag("share_out_of_range", OWNERS["bill"], "Confirm the patient-share and amount scopes in the documents.", bill_ref, cap_ref, share_ref, bill_share_ref)
    return next(iter(units), None), total, cap, letter_share


def evaluate_discharge(metadata: dict, originals: dict[str, bytes], filenames: dict[str, str], *, ocr_client=None,
                       _saved_ocr=None) -> dict:
    """Screen original exhibits. An aligned packet is only ready for coordinator review."""
    meta = _meta(metadata)
    if not set(originals) <= set(ROLE_ORDER) or set(originals) != set(filenames):
        raise ValueError("Use bill, summary, letter and records roles, each with its own PDF filename.")
    review = Review()
    fields, sources = {role: {} for role in ROLE_ORDER}, []
    ocr_cache, ocr_pages = {}, []
    for role in ROLE_ORDER:
        if role not in originals:
            review.flag("missing_" + role, OWNERS[role], f"Obtain the missing {TITLES[role].lower()}.")
            continue
        doc, incomplete, transcribed, extra = _read(originals[role], pdf_filename(filenames[role]), ocr_client,
                                                   (_saved_ocr or {}).get(role, {}))
        fields[role], anchors = _extract(role, doc, meta, review)
        if incomplete:
            review.flag("unreadable_" + role, OWNERS[role], "Obtain a legible exhibit or opt in to OCR and check the original.",
                        *({"role": role, "page": p, "quote": "", "method": "unreadable"} for p in incomplete))
        if transcribed:
            ocr_cache[role] = {"sha256": doc.sha256, "pages": transcribed}
            for page_number, text in transcribed.items():
                ocr_pages.append({"role": role, "page": int(page_number), "sha256": doc.sha256,
                                  "transcript_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()})
            review.flag("verify_ocr", OWNERS[role], "Verify transcribed financial and clinical fields against the original scanned pages.",
                        *(r for r in anchors if r["method"] == "ocr"), severity="review")
        if extra:
            review.flag("unexamined_content", OWNERS[role], "The file includes attachments, forms or annotations. Verify all operative contents.")
        primary = next((a for a in anchors if a["quote"].startswith(
            {"bill": "Final bill total:", "summary": "Performed procedure:", "letter": "Authorized billed-charge ceiling:",
             "records": "Procedure record:"}[role])), None)
        primary = primary or (anchors[0] if anchors else {"page": 1, "quote": "", "method": "unreadable"})
        sources.append({**primary, "role": role, "label": doc.path.name, "sha256": doc.sha256, "anchors": anchors})
    for role in ("bill", "summary", "records"):
        if not fields[role]:
            continue
        for name, key in (("Admission date", "admission_date"), ("Discharge date", "discharge_date")):
            value = _single(fields, role, name, review)
            if value and value.value != meta[key]:
                review.flag("date_mismatch", OWNERS[role], f"The {role} {name.lower()} differs from the discharge encounter.", value.ref)
    if meta["discharge_date"] > meta["as_of"]:
        refs = [line.ref for line in fields["summary"].get("Discharge date", [])]
        review.flag("discharge_in_future", OWNERS["summary"],
                    "The recorded discharge is after the review date. Confirm the final dates before submitting.", *refs)
    proc_refs = []
    for role, key in (("letter", "Authorized procedure"), ("summary", "Performed procedure"), ("records", "Procedure record")):
        if fields[role]:
            value = _single(fields, role, key, review)
            if value:
                proc_refs.append(value)
    if any(v.value != meta["procedure"] for v in proc_refs):
        review.flag("unapproved_procedure", "Clinical team and payer liaison", "The performed, recorded or authorized procedure differs. Clarify any extension.",
                    *(v.ref for v in proc_refs))
    letter_kind = None
    if fields["letter"]:
        labels = {line.value for line in fields["letter"].get("_letter_heading", [])}
        state = _single(fields, "letter", "Letter status", review)
        if len(labels) == 1 and state and state.value == LETTER_KINDS[next(iter(labels))][0]:
            letter_kind = LETTER_KINDS[next(iter(labels))][1]
        else:
            review.flag("unsupported_terms", OWNERS["letter"], "Confirm whether the payer wrote a preauthorization, initial guarantee or final decision.",
                        state.ref if state else None)
        for key, expected in (("Payer", meta["insurer"]),
                              ("Final review", "Payer reviews the actual bill, summary and supporting records.")):
            entry = _single(fields, "letter", key, review)
            if entry and entry.value != expected:
                code = "payer_mismatch" if key == "Payer" else "unsupported_terms"
                review.flag(code, OWNERS["letter"], "Verify the actual payer, letter status and applicable terms.", entry.ref)
        dates = {}
        for name in ("Valid from", "Valid through", "Issued on"):
            entry = _single(fields, "letter", name, review)
            if entry and _iso(entry.value):
                dates[name] = entry
            elif entry:
                review.flag("invalid_letter_date", OWNERS["letter"], "Confirm the letter dates and their meaning.", entry.ref)
        if "Valid from" in dates and "Valid through" in dates and (
                dates["Valid from"].value > meta["admission_date"] or dates["Valid through"].value < meta["discharge_date"]):
            review.flag("stay_extension", OWNERS["letter"], "The actual stay extends outside the letter's written validity period.",
                        dates["Valid from"].ref, dates["Valid through"].ref, *(e.ref for e in fields["summary"].get("Discharge date", [])))
        issued = dates.get("Issued on")
        receipt = _single(fields, "records", "Letter received on", review) if fields["records"] else None
        if receipt and (not _iso(receipt.value) or (issued and receipt.value < issued.value)):
            review.flag("letter_chronology", OWNERS["letter"], "The documented receipt date needs confirmation against the letter's issue date.",
                        receipt.ref, issued.ref if issued else None)
        if ((receipt and _iso(receipt.value) and (receipt.value > meta["discharge_date"] or receipt.value > meta["as_of"]))
                or (issued and (issued.value > meta["admission_date"] or issued.value > meta["as_of"]))):
            review.flag("late_reply", OWNERS["letter"], "The timing of the payer letter requires confirmation. Record its applicability and any retrospective decision.",
                        receipt.ref if receipt else None, issued.ref if issued else None, severity="review")
    for role, key in (("summary", "Summary status"), ("records", "Record status")):
        if fields[role]:
            entry = _single(fields, role, key, review)
            if entry and entry.value != "Signed final":
                review.flag("not_final", OWNERS[role], "Obtain a signed final source exhibit.", entry.ref)
    # Free narrative may change the facts. Only the approved demonstration layout and
    # its neutral narrative statements can clear automatic screening.
    neutral = {"Attending service": "Orthopaedics", "Hospital course": "The patient received operative care following a wrist fracture.",
               "Disposition": "Discharged home", "Follow-up": "Outpatient clinic in one week."}
    if fields["summary"]:
        for key, expected in neutral.items():
            value = _single(fields, "summary", key, review)
            if value and value.value != expected:
                review.flag("clinical_review", OWNERS["summary"], "The discharge narrative needs a clinical read against the letter.", value.ref, severity="review")
    currency, total, cap, share = _financial(fields, meta, review)
    if any(code in review.findings for code in ("payer_mismatch", "unsupported_terms", "stay_extension", "unapproved_procedure")):
        cap, share = None, None
    if any(code in review.findings for code in ("member_mismatch", "encounter_mismatch", "facility_mismatch", "page_identity", "page_order")):
        currency, total, cap, share = None, None, None, None
    status = "needs_review" if review.findings else "ready_for_review"
    findings = list(review.findings.values())
    return {**meta, "input_kind": "discharge", "status": status, "currency": currency, "sources": sources, "letter_kind": letter_kind,
            "bill_total_minor": total, "source_reported_cap_minor": cap,
            "source_reported_patient_share_minor": share, "payable_minor": None,
            "ocr_pages": ocr_cache, "ocr_review_pages": ocr_pages,
            "insurer_decision": "unrecorded", "findings": findings, "checks": review.checks,
            "issues": [f["message"] for f in findings]}


def discharge_ocr_review_pages(case: dict) -> list[dict]:
    """Expose exact transcripts solely to the revision-bound staff verification endpoint."""
    result = []
    sources = {source["role"]: source for source in case.get("sources", [])}
    for item in case.get("ocr_review_pages", []):
        role, page = item["role"], item["page"]
        cached = case.get("ocr_pages", {}).get(role, {})
        text = cached.get("pages", {}).get(str(page))
        if (not isinstance(text, str) or cached.get("sha256") != item["sha256"]
                or sources.get(role, {}).get("sha256") != item["sha256"]
                or hashlib.sha256(text.encode("utf-8")).hexdigest() != item["transcript_sha256"]):
            raise ValueError("The scan or transcript differs from the page verification record.")
        result.append({**item, "text": text})
    return result


def _verified_ocr_evidence(result, reviewer, pages, source_revision):
    required = result.get("ocr_review_pages", [])
    if not required or {f["code"] for f in result["findings"]} != {"verify_ocr"}:
        raise ValueError("Only a complete packet whose sole open finding is OCR verification can be confirmed.")
    if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 120 or not reviewer.isprintable():
        raise ValueError("Record the named staff member who checked the original scan.")
    if type(source_revision) is not int or source_revision < 1:
        raise ValueError("The scan verification must identify its source revision.")
    if not isinstance(pages, list) or len(pages) != len(required):
        raise ValueError("Confirm every transcribed physical page exactly once.")
    supplied = {}
    for row in pages:
        if (not isinstance(row, dict) or set(row) != {"role", "page", "sha256", "transcript_sha256"}
                or row.get("role") not in ROLE_ORDER or type(row.get("page")) is not int):
            raise ValueError("Each confirmed page needs its role, physical page, file digest and transcript digest.")
        supplied[(row["role"], row["page"])] = row
    if len(supplied) != len(required) or any(supplied.get((r["role"], r["page"])) != r for r in required):
        raise ValueError("A verified page is missing, repeated, stale or has the wrong file or transcript digest.")
    record = {"reviewer": reviewer.strip(), "source_revision": source_revision, "pages": required}
    return {**result, "status": "ready_for_review", "issues": [], "findings": [], "ocr_attestation": record,
            "checks": [*result["checks"], {"code": "ocr_pages_confirmed", "message": "Staff compared each transcription with its original physical page.",
                                           "sources": required}]}


def confirm_discharge_ocr(case: dict, originals: dict[str, bytes], reviewer: str, pages: list[dict]) -> dict:
    """Recheck frozen originals and accept a bounded, named attestation for a new revision."""
    if case.get("status") != "needs_review" or {f["code"] for f in case.get("findings", [])} != {"verify_ocr"}:
        raise ValueError("This revision has open findings beyond OCR or has already been verified.")
    sources = {s["role"]: s for s in case.get("sources", [])}
    if (set(sources) != set(ROLE_ORDER) or set(originals) != set(ROLE_ORDER)
            or any(hashlib.sha256(originals[r]).hexdigest() != sources[r]["sha256"] for r in ROLE_ORDER)):
        raise ValueError("The original PDFs do not match this revision's sources.")
    discharge_ocr_review_pages(case)
    result = evaluate_discharge(case, originals, {r: sources[r]["label"] for r in ROLE_ORDER},
                                _saved_ocr=case.get("ocr_pages"))
    return _verified_ocr_evidence(result, reviewer, pages, case.get("revision"))


def load_discharge_fixture(scenario="aligned"):
    cases = json.loads((ROOT / "expected.json").read_text())
    if scenario not in cases:
        raise ValueError("Unknown discharge fixture.")
    definition = cases[scenario]
    files = {role: definition.get("exhibits", {}).get(role, role + ".pdf") for role in ROLE_ORDER}
    filenames = {role: name for role, name in files.items() if name}
    originals = {role: (ROOT / name).read_bytes() for role, name in filenames.items()}
    return ({"id": "D-FICTIONAL", "member": "EXAMPLE-2402", "encounter": "EXAMPLE-VISIT-42",
             "procedure": "Wrist fracture fixation", "insurer": "Alder Transit Cover", "facility": "Canal Bridge Demo Hospital",
             "admission_date": "2026-12-11", "discharge_date": "2026-12-13", "as_of": definition.get("as_of", "2026-12-13")}, originals, filenames)


def discharge_packet_bytes(case: dict, originals: dict[str, bytes]) -> bytes:
    """Render only the staff-reviewed active comparison; the insurer issues its own decision."""
    revision = case.get("revision")
    reviewer = case.get("reviewer")
    history = case.get("history", [])
    if (case.get("status") != "staff_reviewed" or type(revision) is not int or revision < 1
            or not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 120 or not reviewer.isprintable()
            or case.get("reviewed_revision", revision) != revision or not any(h.get("revision") == revision for h in history)
            or any(h.get("revision", 0) > revision for h in history)):
        raise ValueError("Review the current discharge revision before exporting its packet.")
    source_by_role = {s["role"]: s for s in case["sources"]}
    if set(source_by_role) != set(ROLE_ORDER) or set(originals) != set(ROLE_ORDER):
        raise ValueError("The discharge packet requires the current bill, summary, payer letter and supporting records.")
    if any(hashlib.sha256(originals[role]).hexdigest() != source_by_role[role]["sha256"] for role in ROLE_ORDER):
        raise ValueError("The saved PDF does not match this discharge revision.")
    names = {role: source_by_role[role]["label"] for role in ROLE_ORDER}
    result = evaluate_discharge(case, originals, names, _saved_ocr=case.get("ocr_pages"))
    attestation = case.get("ocr_attestation")
    if attestation:
        source_revision = attestation.get("source_revision")
        if type(source_revision) is not int or source_revision + 1 != revision:
            raise ValueError("The scan verification does not belong to this reviewed discharge revision.")
        result = _verified_ocr_evidence(result, attestation.get("reviewer"), attestation.get("pages"), source_revision)
    if result["status"] != "ready_for_review" or any(case.get(key) != result[key] for key in (
            "bill_total_minor", "currency", "source_reported_cap_minor", "source_reported_patient_share_minor", "payable_minor")):
        raise ValueError("The sources do not support a reviewed discharge packet.")
    body = ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=15, spaceAfter=5)
    title = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=22, leading=27, spaceAfter=13)
    heading = ParagraphStyle("section", fontName="Helvetica-Bold", fontSize=13, leading=18, spaceBefore=9, spaceAfter=4)
    story = [_paragraph("Discharge claim review", title), _paragraph(f"Case {case['id']} / Revision {revision}", body),
             _paragraph(f"Prepared for {case['insurer']} by {reviewer}. The hospital requests a final payer decision on the attached discharge exhibits.", body),
             _paragraph("Admission and discharge", heading),
             _paragraph(f"{case['facility']} / {case['member']} / {case['encounter']}", body),
             _paragraph(f"{case['procedure']} / {case['admission_date']} to {case['discharge_date']}", body),
             _paragraph("Documented amounts", heading)]
    for label, key in (("Final bill", "bill_total_minor"), ("Billed-charge ceiling stated in letter", "source_reported_cap_minor"),
                       ("Fixed patient share stated in letter", "source_reported_patient_share_minor")):
        amount = result[key]
        story.append(_paragraph(f"{label} / {result['currency']} {amount//100:,}.{amount%100:02}", body))
    story.extend([_paragraph("Source exhibits", heading), _paragraph("The original four PDFs are embedded in the attachments panel.", body)])
    used = set()
    verified_sources = {source["role"]: source for source in result["sources"]}
    for role in ROLE_ORDER:
        name = names[role]
        while name.casefold() in used:
            name = role + "-" + name
        used.add(name.casefold())
        names[role] = name
        source = verified_sources[role]
        story.append(_paragraph(f"{TITLES[role]} / {name}, p. {source['page']} / {source['quote']}", body))
    story.append(_paragraph("The payer determines the final payable amount after reviewing the submitted claim.", body))
    if attestation:
        story.extend([PageBreak(), _paragraph("Scan verification record", title),
                      _paragraph(f"Case {case['id']} / Reviewed claim revision {revision}", body),
                      _paragraph(f"{attestation['reviewer']} compared each transcription with the original page in source revision {attestation['source_revision']}.", body)])
        for page in result["ocr_attestation"]["pages"]:
            story.extend([_paragraph(f"{names[page['role']]} / physical page {page['page']}", heading),
                          _paragraph(f"Source PDF SHA-256 / {page['sha256']}", body),
                          _paragraph(f"Transcript SHA-256 / {page['transcript_sha256']}", body)])
    buffer = io.BytesIO()
    SimpleDocTemplate(buffer, pagesize=A4, leftMargin=50, rightMargin=50, topMargin=49, bottomMargin=49,
                      title="Discharge claim review", author="ZeroUpfront", invariant=1).build(story)
    return _embed_originals(buffer, originals, names)
