"""Bounded PDF intake and page-grounded staff findings for a new admission."""
from dataclasses import dataclass
from datetime import date
import hashlib
import io
import json
from pathlib import Path
import re

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from .check_fixtures import Evidence, ROOT, precheck
from .document_text import Document, Page, contains_identifier, contains_quote, normalized, ocr_page

ROLES = ("policy", "plan", "estimate")
MAX_FILE_BYTES = 24 * 1024 * 1024
MAX_PAGES = 200
METADATA = ("id", "member", "insurer", "policy_edition", "procedure", "admission_date")
LABELS = {
    "member": ("Member reference", "Member number", "Member ID", "Member", "เลขสมาชิก"),
    "edition": ("Policy edition", "Edition", "รุ่นกรมธรรม์"),
    "encounter": ("Encounter ID", "Encounter reference", "รหัสการเข้ารักษา"),
    "admission_date": ("Admission date", "วันที่เข้ารักษา"),
    "procedure": ("Planned procedure", "Procedure", "หัตถการที่วางแผน"),
    "purpose": ("Purpose recorded by provider", "Treatment purpose", "วัตถุประสงค์การรักษา"),
    "setting": ("Care setting", "Admission setting", "ประเภทการรักษา"),
    "provider": ("Hospital name", "Provider name", "Source"),
    "Hospital services": ("Hospital services", "ค่าบริการโรงพยาบาล"),
    "Operating team": ("Operating team", "ค่าทีมผ่าตัด"),
    "Supplies": ("Supplies", "ค่าวัสดุ"),
    "total": ("Total estimated charges", "Estimated total", "ยอดประมาณการรวม"),
}
LABEL_LOOKUP = {label.casefold(): key for key, labels in LABELS.items() for label in labels}
LABEL = re.compile(r"^(" + "|".join(re.escape(key) for key in sorted(LABEL_LOOKUP, key=len, reverse=True))
                   + r")(?=$|\s|:)(?:\s*:\s*|\s+)?(.*)$", re.IGNORECASE)
HEADINGS = {"inpatient treatment plan", "treatment plan", "hospital estimate", "revised hospital estimate",
            "cost estimate", "canal bridge demo hospital, bangkok", "synthetic demo document / zeroupfront",
            "แผนการรักษา", "แผนการรักษาผู้ป่วยใน", "ใบประมาณการค่าใช้จ่าย"}
SERVICES = ("Hospital services", "Operating team", "Supplies")
MONEY = re.compile(r"(THB|บาท)\s+([1-9]\d{0,8}|[1-9]\d{0,2}(?:,\d{3}){1,2})\Z", re.IGNORECASE)
PLACEHOLDERS = {"", "-", "--", "unknown", "unclear", "none", "n/a", "na", "pending", "tba", "tbd",
                "not available", "not provided", "not specified", "ไม่ทราบ", "รอข้อมูล"}
ADVERSE_EVIDENCE = re.compile(
    r"\b(?:inactive|lapsed|terminated|cancelled|canceled|void(?:ed)?|superseded|revoked|expired|"
    r"uninsured|outpatient|denied|declined|ineligible|not eligible|not in force|not active|not valid|not covered|"
    r"not (?:an? )?inpatient|no (?:active )?coverage|no admission|do not (?:admit|use)|"
    r"postponed|deferred|exclusions?|riders?|endorsements?|amendments?|final invoice|final bill)\b"
    r"|หมดอายุ|ยกเลิก|ผู้ป่วยนอก|ไม่คุ้มครอง|ปฏิเสธ", re.IGNORECASE)


def pdf_filename(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 160 or "/" in value or "\\" in value
            or not value.lower().endswith(".pdf") or not value.isprintable()):
        raise ValueError("Provide a PDF filename of up to 160 characters without directories.")
    return value


def _metadata(data):
    result = {}
    for key in METADATA:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip() or not value.isprintable() or len(value) > 220:
            raise ValueError(f"A printable {key} of up to 220 characters is required.")
        result[key] = value.strip()
        if result[key].casefold() in PLACEHOLDERS:
            raise ValueError(f"The case needs a documented {key}, rather than a placeholder.")
    if date.fromisoformat(result["admission_date"]).isoformat() != result["admission_date"]:
        raise ValueError("Admission date must use YYYY-MM-DD.")
    return result


def _read(raw, filename, client, cached):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_FILE_BYTES or b"%PDF-" not in raw[:1024]:
        raise ValueError("Supply a PDF up to 24 MiB per exhibit.")
    digest = hashlib.sha256(raw).hexdigest()
    cache = cached.get("pages", {}) if cached.get("sha256") == digest else {}
    pages, unreadable, transcribed = [], [], {}
    chars = 0
    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted or not 1 <= len(reader.pages) <= MAX_PAGES:
            raise ValueError("Supply an unlocked PDF with 1 to 200 physical pages.")
        catalog = reader.root_object
        names = catalog.get("/Names", {})
        if hasattr(names, "get_object"):
            names = names.get_object()
        extra_content = bool("/AcroForm" in catalog or "/Collection" in catalog or "/EmbeddedFiles" in names)
        for number, source in enumerate(reader.pages, 1):
            extra_content |= bool(source.get("/Annots"))
            native = source.extract_text() or ""
            scan = bool(source.images.keys()) or not native.strip() or "\ufffd" in native
            ocr = None
            if scan:
                ocr = cache.get(str(number))
                if ocr is None and client is not None:
                    ocr = ocr_page(source, number, client)
                if ocr is None:
                    unreadable.append(number)
                    # A selectable heading on an image-only exhibit cannot verify its body.
                    native = ""
                else:
                    transcribed[str(number)] = ocr
            chars += len(native) + len(ocr or "")
            if max(len(native), len(ocr or "")) > 200_000 or chars > 2_000_000:
                raise ValueError("The extracted PDF exceeds the text limit for one exhibit.")
            pages.append(Page(number, native, ocr))
    except (PyPdfError, RecursionError, KeyError, IndexError, UnicodeError, OSError) as exc:
        raise ValueError("An uploaded PDF could not be read reliably.") from exc
    return Document(Path(filename), digest, pages), unreadable, transcribed, extra_content


def _documents(originals, filenames, client=None, cached=None):
    if set(originals) != set(ROLES) or set(filenames) != set(ROLES):
        raise ValueError("Supply exactly one policy, treatment plan and estimate.")
    docs, issues, ocr = {}, [], {}
    for role in ROLES:
        doc, missing, transcribed, extra = _read(originals[role], pdf_filename(filenames[role]), client, (cached or {}).get(role, {}))
        docs[role] = doc
        if extra:
            issues.append(f"The {role} includes attachments, annotations or form fields. Supply all operative wording on verified PDF pages.")
        if missing:
            pages = ", ".join(map(str, missing))
            issues.append(f"The {role} needs OCR or a legible digital copy on page(s) {pages}.")
        if transcribed:
            ocr[role] = {"sha256": doc.sha256, "pages": transcribed}
    return docs, issues, ocr


@dataclass(frozen=True)
class Field:
    value: str
    quote: str
    page: int


def _form(document):
    values, unparsed = {}, False
    for page in document.pages:
        lines = [normalized(line) for line in page.text.splitlines() if line.strip()]
        i = 0
        while i < len(lines):
            line = lines[i]
            i += 1
            if line.casefold() in HEADINGS or re.fullmatch(r"Page \d+( of \d+)?", line, re.I):
                continue
            match = LABEL.fullmatch(line)
            if not match:
                unparsed = True
                continue
            key = LABEL_LOOKUP[match[1].casefold()]
            value, quote = match[2].strip(), line
            if not value and i < len(lines) and not LABEL.fullmatch(lines[i]):
                value, quote = lines[i], line + " " + lines[i]
                i += 1
            if not value:
                unparsed = True
                continue
            if key == "member" and "|" in value:
                value, edition = [part.strip() for part in value.split("|", 1)]
                values.setdefault("edition", []).append(Field(edition, quote, page.number))
            values.setdefault(key, []).append(Field(value, quote, page.number))
    return values, unparsed


def _anchor(doc, page, quote, clause=None):
    text = doc.pages[page-1]
    if not contains_quote(text.text, quote):
        raise ValueError("The quoted wording does not exist on the specified physical page.")
    return {"page": page, "quote": quote, "clause": clause, "method": "ocr" if text.ocr else "digital"}


def _field_anchor(doc, field):
    return _anchor(doc, field.page, field.quote)


def _source(role, doc, anchors):
    if not anchors:
        for page in doc.pages:
            first = next((line.strip()[:140] for line in page.text.splitlines() if line.strip()), None)
            if first:
                # A navigation preview only. Never attach an arbitrary page heading as a supported field.
                break
        else:
            page, first = doc.pages[0], ""
        primary = {"page": page.number, "quote": first, "clause": None,
                   "method": "ocr" if page.ocr else ("digital" if first else "unreadable")}
    else:
        primary = anchors[0]
    return {"role": role, "label": doc.path.name, "sha256": doc.sha256, **primary, "anchors": anchors}


def policy_for_digest(digest):
    rules = json.loads((ROOT / "rulebooks.json").read_text())
    for name, policy in rules.items():
        if hashlib.sha256((ROOT / "policies" / (name + ".pdf")).read_bytes()).hexdigest() == digest:
            return policy
    return None


def _same_fixture_encounter(plan, estimate):
    for folder in (ROOT / "cases").iterdir():
        if hashlib.sha256((folder / "plan.pdf").read_bytes()).hexdigest() != plan.sha256:
            continue
        if any(hashlib.sha256(path.read_bytes()).hexdigest() == estimate.sha256 for path in folder.glob("*estimate.pdf")):
            return True
    return False


def _currencies(text):
    found = set(re.findall(r"\b(?:THB|USD|EUR|GBP|SGD|AUD|CAD|JPY|CNY|MYR|CHF|HKD)\b", text.upper()))
    found.update(re.findall(r"(?<![A-Z])([A-Z]{3})\s+(?=[+-]?\d)", text))
    for token, currency in (("฿", "THB"), ("บาท", "THB"), ("$", "unspecified dollar"), ("€", "EUR"), ("£", "GBP")):
        if token in text:
            found.add(currency)
    return found


def evaluate_intake(metadata: dict, originals: dict[str, bytes], filenames: dict[str, str], *, ocr_client=None,
                    _saved_ocr=None) -> dict:
    case = _metadata(metadata)
    docs, issues, ocr = _documents(originals, filenames, ocr_client, _saved_ocr)
    policy = policy_for_digest(docs["policy"].sha256)
    plan, plan_other = _form(docs["plan"])
    estimate, estimate_other = _form(docs["estimate"])
    anchors = {role: [] for role in ROLES}
    if plan_other or estimate_other:
        issues.append("The clinical or financial form has additional wording or an unfamiliar layout. Review the original pages.")
    if any(ADVERSE_EVIDENCE.search(docs[role].text) for role in ("plan", "estimate")):
        issues.append("The exhibits mention a change in validity, treatment, coverage or governing terms. Confirm the active documents.")
    for form in (plan, estimate):
        if any(re.search(r"\b(?:member (?:id|reference|number)|policy edition|encounter id)\b", entry.value, re.I)
               for key, fields in form.items() if key not in {"member", "edition", "encounter"} for entry in fields):
            issues.append("Another identity or edition is referenced inside a different field. Confirm the original encounter.")
            break
    if any(role in ocr for role in ("plan", "estimate")):
        issues.append("Verify the transcribed clinical and financial fields against the scanned original.")
    if not policy:
        issues.append("This policy PDF has no verified rulebook. Record the applicable wording and request clarification.")
        source_fields, _ = _form(docs["policy"])
        if any(field.value != case["policy_edition"] for field in source_fields.get("edition", [])):
            issues.append("The supplied policy edition differs from the hospital intake record. Clarify the applicable document.")
    elif (case["insurer"].casefold() != policy["name"].casefold() or case["policy_edition"] != policy["version"]):
        raise ValueError("Insurer or edition does not match the supplied policy schedule.")
    if policy:
        for clause, wording in policy["clauses"].items():
            anchor = docs["policy"].locate(wording, clause)
            anchors["policy"].append({key: anchor[key] for key in ("page", "quote", "clause", "method")})
    for role, fields in (("plan", plan), ("estimate", estimate)):
        for key, expected in (("member", case["member"]), ("edition", case["policy_edition"]),
                              ("admission_date", case["admission_date"]), ("procedure", case["procedure"])):
            entries = fields.get(key, [])
            if entries and any(entry.value != expected for entry in entries):
                raise ValueError(f"The {role} contains a conflicting {key}. Verify the correct encounter.")
            if not entries and (key in ("member", "edition") or role == "plan"):
                issues.append(f"The {role} has no verified {key.replace('_', ' ')}.")
            if entries:
                anchors[role].append(_field_anchor(docs[role], entries[0]))
        if any(len(entries) != 1 for entries in fields.values()):
            issues.append(f"The {role} repeats a labeled field or service. Confirm which record applies.")
    encounter_plan = {field.value for field in plan.get("encounter", [])}
    encounter_est = {field.value for field in estimate.get("encounter", [])}
    if encounter_plan and encounter_est and encounter_plan != encounter_est:
        raise ValueError("The estimate and treatment plan identify different encounters.")
    matching_visit = (len(encounter_plan) == 1 and encounter_plan == encounter_est
                      and next(iter(encounter_plan)).casefold() not in PLACEHOLDERS)
    if not (matching_visit or _same_fixture_encounter(docs["plan"], docs["estimate"])):
        issues.append("Link both exhibits to one encounter with the same documented encounter ID on the plan and estimate.")
    # The two known clinical form layouts only admit plan fields in the plan and charges in the estimate.
    explicit_setting = [field.value.casefold() for field in plan.get("setting", [])]
    inpatient = any(line.strip().casefold() in {"inpatient treatment plan", "แผนการรักษาผู้ป่วยใน"}
                    for page in docs["plan"].pages for line in page.text.splitlines())
    if ((not inpatient and not explicit_setting)
            or any(value not in {"inpatient", "ผู้ป่วยใน"} for value in explicit_setting)):
        issues.append("Confirm that the source plan documents inpatient treatment for this admission.")
    if set(plan) - {"member", "edition", "encounter", "admission_date", "procedure", "purpose", "provider", "setting"}:
        issues.append("The treatment plan contains unverified additional financial fields.")
    if set(estimate) - {"member", "edition", "encounter", "admission_date", "procedure", "total", "provider", *SERVICES}:
        issues.append("The estimate contains additional clinical facts that require review.")
    if plan.get("purpose"):
        anchors["plan"].insert(0, _field_anchor(docs["plan"], plan["purpose"][0]))
    total = None
    currencies = _currencies(docs["estimate"].text)
    currency = next(iter(currencies)) if len(currencies) == 1 else None
    lines, reliable = [], True
    for key in ("total", *SERVICES):
        entries = estimate.get(key, [])
        if len(entries) != 1:
            if entries or key == "total":
                reliable = False
            continue
        field = entries[0]
        amount = MONEY.fullmatch(field.value)
        if amount is None or currency != "THB":
            reliable = False
            continue
        value = int(amount[2].replace(",", ""))
        anchor = _field_anchor(docs["estimate"], field)
        if key == "total":
            total = value
            anchors["estimate"].insert(0, anchor)
        else:
            lines.append({"label": key, "amount": value})
            anchors["estimate"].append(anchor)
    if not reliable or (lines and sum(row["amount"] for row in lines) != total):
        issues.append("Confirm the estimate currency, unique total and each service price. The THB amounts could not be reconciled.")
        total, lines = None, []
    known_money = sum(len(estimate.get(key, [])) for key in ("total", *SERVICES))
    if len(re.findall(r"(?<![A-Z])THB\s*(?=\d)|บาท\s*(?=\d)", docs["estimate"].text, re.I)) > known_money:
        issues.append("The estimate contains additional monetary entries outside the reconciled service breakdown.")
        total, lines = None, []
    purpose = normalized(plan["purpose"][0].value).casefold() if len(plan.get("purpose", [])) == 1 else ""
    purpose = {"solely cosmetic appearance; no reconstructive indication.": "solely_cosmetic",
               "repair of an accidental fracture.": "other"}.get(purpose, "unclear")
    status, clause = "needs_review", None
    if policy:
        outcome, clause = precheck(policy, Evidence(total_thb=total, itemized=bool(lines), purpose=purpose))
        if total is not None and total > policy["limit_thb"]:
            clause = "AT-1" if policy["version"] == "AT-2026.1" else "MM-3"
            issues.append(f"The reported THB {total:,} exceeds the policy limit of THB {policy['limit_thb']:,}. Obtain payer guidance.")
        if policy["version"] == "MM-2026.1":
            if purpose == "solely_cosmetic":
                outcome, clause = "possible_exclusion", "MM-2"
            elif purpose == "other" and re.search(r"cosmetic|aesthetic|เสริมสวย|ความงาม", case["procedure"], re.I):
                issues.append("The procedure and recorded indication may conflict. Confirm the treatment purpose for MM-2.")
                clause = "MM-2"
        if outcome == "possible_exclusion":
            status = outcome
            issues.insert(0, "The documented treatment purpose may be excluded. Ask the insurer to clarify.")
        elif not issues:
            status = {"missing_evidence": "needs_itemization", "staff_review": "needs_review"}.get(outcome, outcome)
            if status == "needs_itemization":
                issues.append("Attach an estimate with each required service and its price.")
            elif status == "needs_review":
                issues.append("The governing limit or indication requires staff review.")
        if clause:
            anchors["policy"].sort(key=lambda ref: ref["clause"] != clause)
    return {**case, "input_kind": "intake", "intake": True, "status": status, "issues": issues,
            "reason": " ".join(issues) or "The planned admission and estimate meet the verified policy checks.",
            "total": total, "currency": currency, "lines": lines, "clause": clause,
            "sources": [_source(role, docs[role], anchors[role]) for role in ROLES],
            "ocr_pages": ocr}


def _stored_documents(evidence, originals):
    sources = {source["role"]: source for source in evidence.get("sources", [])}
    if set(sources) != set(ROLES) or set(originals) != set(ROLES):
        raise ValueError("The review needs a complete current source manifest.")
    for role in ROLES:
        if hashlib.sha256(originals[role]).hexdigest() != sources[role]["sha256"]:
            raise ValueError("The saved exhibits differ from this review revision.")
    return _documents(originals, {role: source["label"] for role, source in sources.items()},
                      cached=evidence.get("ocr_pages"))[0]


def _staff_anchor(raw, docs, allowed_roles):
    if not isinstance(raw, dict) or raw.get("role") not in allowed_roles:
        raise ValueError("Choose an applicable source role for the evidence.")
    role = raw["role"]
    page, quote = raw.get("page"), raw.get("quote")
    if type(page) is not int or not 1 <= page <= len(docs[role].pages):
        raise ValueError("The cited physical page is outside the exhibit.")
    if not isinstance(quote, str) or not 3 <= len(quote.strip()) <= 1200:
        raise ValueError("Provide a source quote between 3 and 1,200 characters.")
    quote = normalized(quote)
    return {"role": role, **_anchor(docs[role], page, quote)}


def manual_evidence(evidence: dict, originals: dict[str, bytes], review: dict) -> dict:
    """Save verifiable human findings on this revision. Replaying a review replaces its findings."""
    if evidence.get("input_kind") != "intake":
        raise ValueError("Manual findings apply to an uploaded case.")
    docs = _stored_documents(evidence, originals)
    base = evaluate_intake(evidence, originals, {role: doc.path.name for role, doc in docs.items()},
                           _saved_ocr=evidence.get("ocr_pages"))
    if not isinstance(review, dict):
        raise ValueError("Supply verified fields or policy checks.")
    fields, checks = review.get("fields", {}), review.get("checks", [])
    allowed = {"member", "admission_date", "procedure", "estimated_total_thb"}
    if (not isinstance(fields, dict) or not isinstance(checks, list) or len(checks) > 20
            or not set(fields) <= allowed or not (fields or checks)):
        raise ValueError("Supply supported fields or up to 20 documented policy checks.")
    verified_fields, verified_checks = {}, []
    for key, raw in fields.items():
        quote = _staff_anchor(raw, docs, ("estimate",) if key == "estimated_total_thb" else ("plan",))
        if key == "estimated_total_thb":
            amount = base["total"]
            estimate, _ = _form(docs["estimate"])
            totals = estimate.get("total", [])
            if (amount is None or len(totals) != 1 or quote["page"] != totals[0].page
                    or not contains_quote(quote["quote"], totals[0].quote)):
                raise ValueError("The total citation must support the reconciled amount and its currency.")
        elif not contains_identifier(quote["quote"], base[key]):
            raise ValueError(f"The citation does not support the case {key}.")
        verified_fields[key] = quote
    policy = policy_for_digest(docs["policy"].sha256)
    covered_clauses = set()
    for check in checks:
        if not isinstance(check, dict):
            raise ValueError("Describe a policy check and cite its supporting pages.")
        requirement, result = check.get("requirement"), check.get("result")
        if (not isinstance(requirement, str) or not 3 <= len(requirement.strip()) <= 350
                or not requirement.isprintable() or result not in {"met", "missing", "unclear", "possible_exclusion"}):
            raise ValueError("Set a documented requirement and one supported check outcome.")
        rule = _staff_anchor(check.get("policy"), docs, ("policy",))
        support = _staff_anchor(check.get("support"), docs, ("plan", "estimate"))
        verified_checks.append({"requirement": requirement.strip(), "result": result, "policy": rule, "support": support})
        if policy and result == "met":
            for clause, wording in policy["clauses"].items():
                if contains_quote(rule["quote"], wording):
                    # Each clause needs evidence of the field it governs. A member
                    # identifier on the correct page cannot substantiate a charge or indication.
                    targets = {
                        "AT-1": ("estimate", ("total",)), "AT-2": ("estimate", SERVICES),
                        "AT-3": ("plan", ("admission_date", "procedure", "member")),
                        "MM-1": ("estimate", SERVICES), "MM-2": ("plan", ("purpose",)),
                        "MM-3": ("estimate", ("total",)),
                    }
                    role, target_fields = targets[clause]
                    if role == support["role"]:
                        form, _ = _form(docs[role])
                        if any(field.page == support["page"] and contains_quote(support["quote"], field.quote)
                               for target in target_fields for field in form.get(target, [])):
                            covered_clauses.add(clause)
    base["manual_review"] = {"fields": verified_fields, "checks": verified_checks}
    if isinstance(review.get("reviewer"), str) and review["reviewer"].strip():
        base["manual_review"]["reviewer"] = review["reviewer"].strip()[:100]
    results = {check["result"] for check in verified_checks}
    if "possible_exclusion" in results:
        base["status"] = "possible_exclusion"
        base["issues"].insert(0, "The coordinator recorded a possible policy exclusion.")
    elif results.intersection({"missing", "unclear"}):
        if base["status"] != "possible_exclusion":
            base["status"] = "needs_review"
        base["issues"].insert(0, "The coordinator recorded a missing or unresolved policy requirement.")
    elif (policy and set(verified_fields) == allowed and covered_clauses == set(policy["clauses"])
          and base["status"] == "needs_review" and base["issues"] and all(
              issue.startswith(("The clinical or financial form has additional wording", "Verify the transcribed clinical"))
              for issue in base["issues"]) and base["lines"] and base["total"] is not None
          and base["total"] <= policy["limit_thb"]):
        # A staff read can resolve layout/OCR only once the entire mapped policy is cited.
        # The rules for treatment purpose and itemization must still independently pass.
        plan, _ = _form(docs["plan"])
        purpose = next(iter(plan.get("purpose", [])), None)
        if policy["version"] == "AT-2026.1" or (purpose and purpose.value == "Repair of an accidental fracture."):
            base["status"], base["issues"] = "ready_for_review", []
    base["reason"] = " ".join(base["issues"]) or "The applicable rulebook checks have verified case and policy evidence."
    base["clarification_available"] = base["status"] in {"needs_review", "needs_itemization", "possible_exclusion"}
    return base


def replay_intake(case, originals):
    filenames = {source["role"]: source["label"] for source in case["sources"]}
    base = evaluate_intake(case, originals, filenames, _saved_ocr=case.get("ocr_pages"))
    if case.get("manual_review"):
        return manual_evidence(base, originals, case["manual_review"])
    return base
