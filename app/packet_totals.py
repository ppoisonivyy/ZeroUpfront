"""Conservative reconciliation of the two documented synthetic long-packet layouts."""
from datetime import datetime
from decimal import Decimal
import re


class Unresolved(ValueError):
    """The supplied evidence does not support a unique calculation."""


def one(pattern, text):
    matches = re.findall(pattern, text, flags=re.IGNORECASE)
    if len(matches) != 1:
        raise Unresolved("Missing or ambiguous financial evidence")
    return matches[0]


def clean(text):
    # Astra may transcribe tables with Markdown separators.
    return " ".join(text.translate(str.maketrans({"|": " ", "*": "", "\u00a0": " "})).split())


def amounts(text, label, columns):
    integer = r"((?:\d{1,3}(?:,\d{3})+|\d+))(?![\d,.])"
    # Keep the full row arity. An extra amount or decimal must go to review.
    captures = one(re.escape(label) + (r"\s+(?:THB\s+)?" + integer) * columns
                   + r"(?!\s+(?:THB\s+)?[-+]?\d)", text)
    if isinstance(captures, str):
        captures = (captures,)
    return tuple(int(n.replace(",", "")) for n in captures)


def check_packet_identity_and_chronology(pack, case):
    # Both supported forms repeat the case identifier on every physical page.
    ids = [one(r"\bCase ([\w-]+)\s*•", clean(page.text)) for page in case.pages]
    if len(set(ids)) != 1:
        raise Unresolved("Case identifiers differ across packet pages")
    timeline = clean(case.pages[1].text)
    heading = ("B. Clinical timeline" if pack == "th" else "B. Clinical and operational chronology")
    if heading not in timeline or not re.search(r"\b\d{1,2}:\d{2}\b", timeline):
        raise Unresolved("Dated clinical chronology is missing")


def th_amounts(policy, case):
    conditions = clean(policy.text)
    first, left, right = (clean(case.pages[i].text) for i in (0, 2, 3))
    schedule = one(r"•\s*([\w-]+) (\w+) / ([\w-]+)\.(?=\s|$)", first)
    if schedule != ("KM-26C", "Gold", "R9") or one(r"\bEdition ([\w-]+)\s*•", conditions) != "KM-26C":
        raise Unresolved("Member option, rider or edition needs review")
    facility, admission = one(r"Admission at facility ([\w-]+) on (\d+ \w+ \d{4})", first)
    rate, branch, start, end, year = one(
        r"Rider R9 increases the Gold room limit to THB ([\d,]+) per eligible night at facility "
        r"([\w-]+) for admissions from (\d+ \w+) through (\d+ \w+) (\d{4}) inclusive", conditions)
    date = lambda value: datetime.strptime(value, "%d %B %Y").date()
    if facility != branch or not date(f"{start} {year}") <= date(admission) <= date(f"{end} {year}"):
        raise Unresolved("Rider eligibility needs staff review")
    cap = int(rate.replace(",", ""))
    if "companion beds and meals remain member expenses" not in conditions.lower():
        raise Unresolved("Companion benefit needs confirmation")
    member, encounter = one(r"hospital number ([\w-]+)\s*•\s*encounter ([\w-]+)\s*•", first)
    for sheet, index in ((left, 1), (right, 2)):
        heading = one(r"Hospital statement ([\w-]+)\s*•\s*sheet (\d+) of (\d+)\b", sheet)
        if heading != ("R2", str(index), "2"):
            raise Unresolved("Statement revision or sheet number differs from the supported pair")
    printed = one(r"•\s*([\w-]+)\s*•\s*([\w-]+)\s*•\s*([A-Z]{3})\s*•\s*revision ([\w-]+)\.(?=\s|$)", left)
    linked = one(r"Supplement received \d+ \w+ for ([\w-]+) and ([\w-]+)\.(?=\s|$)", right)
    currency = one(r"All amounts are ([A-Z]{3})\.(?=\s|$)", right)
    revision = one(r"second sheet of the same ([\w-]+) statement\b", right)
    if printed != (member, encounter, "THB", "R2") or linked != (member, encounter):
        raise Unresolved("Statement identity, currency or printed revision differs from the current packet")
    if (currency, revision) != ("THB", "R2"):
        raise Unresolved("Supplement currency or revision differs from the current statement")
    sheets = [(left, ("Surgery and theatre", "Diagnostic services", "Room night 1")),
              (right, ("Room night 2", "Companion bed", "Implant and supplies"))]
    net_lines = {}
    sum_columns = [0, 0, 0]
    for index, (sheet, labels) in enumerate(sheets, 1):
        rows = [amounts(sheet, label, 3) for label in labels]
        if any(gross - discount != net for gross, discount, net in rows):
            raise Unresolved("A charge line does not reconcile")
        subtotal = tuple(map(sum, zip(*rows)))
        if subtotal != amounts(sheet, f"Page {index} subtotal", 3):
            raise Unresolved("Page subtotal does not reconcile")
        sum_columns = [a+b for a,b in zip(sum_columns, subtotal)]
        net_lines.update((label,row[2]) for label,row in zip(labels,rows))
    if tuple(sum_columns) != amounts(right, "Statement total", 3):
        raise Unresolved("Statement total does not reconcile")
    excess = sum(max(net_lines[k] - cap, 0) for k in ("Room night 1","Room night 2"))
    share = excess + net_lines["Companion bed"]
    return sum_columns[2], share, 0, sum_columns[2]-share, "staff_review"


def us_amounts(policy, case):
    terms = clean(policy.text)
    header, sheet, supplier, rates = (clean(case.pages[i].text) for i in (0,2,3,4))
    schedule = one(r"•\s*([\w-]+) / ([\w-]+) / ([\w-]+)\s*•", header)
    if schedule != ("NQ-26B", "G2", "M7") or one(r"\bEdition ([\w-]+)\s*•", terms) != "NQ-26B":
        raise Unresolved("Member option, currency or edition needs review")
    if (one(r"All amounts in this table are ([A-Z]{3})\.", sheet) != "THB"
            or one(r"Charge Qty Net ([A-Z]{3})\b", sheet) != "THB"
            or one(r"settlement was requested in ([A-Z]{3})\.", rates) != "THB"):
        raise Unresolved("Estimate, net column or settlement currency differs")
    revision = one(r"Provider estimate, revision (\d+)\b", sheet)
    signed = one(r"Estimate [\w-]+-R(\d+), signed\b", sheet)
    current = one(r"Revision (\d+) is the current document\b", supplier)
    if revision != signed or revision != current:
        raise Unresolved("Estimate and current signed revision differ")
    if "No final supplier schedule is attached" not in supplier:
        raise Unresolved("Current supplier evidence needs review")
    rate = Decimal(one(r"records (\d+(?:\.\d+)?) THB per USD for the admission date", rates))
    usd = Decimal(one(r"The G2 cap is USD (\d+) each night", terms))
    if rate <= 0 or rate*usd != (rate*usd).to_integral_value():
        raise Unresolved("Rate or rounding needs staff review")
    labels = ("Surgical services","Theatre and anesthesia","Implant provisional allowance",
              "Room / first night","Room / second night","Ward diagnostics")
    rows = [amounts(sheet, label, 2) for label in labels]
    if any(quantity != 1 for quantity, _ in rows):
        raise Unresolved("Confirm quantity and net line amount")
    total, = amounts(sheet, "Reported estimate total", 1)
    if sum(row[1] for row in rows) != total:
        raise Unresolved("Estimate detail differs from current revision total")
    charges = dict(zip(labels,(row[1] for row in rows)))
    listed_currency, listed_amount = one(
        r"The ([A-Z]{3}) (\d{1,3}(?:,\d{3})+|\d+) line is a provisional allowance", supplier)
    if listed_currency != "THB" or int(listed_amount.replace(",", "")) != charges["Implant provisional allowance"]:
        raise Unresolved("Supplier and estimate allowance differ")
    cap = int(rate*usd)
    share = sum(max(charges[k]-cap, 0) for k in ("Room / first night","Room / second night"))
    return total, share, charges["Implant provisional allowance"], None, "supplier_schedule_pending"


def reconcile_packet(pack, policy, case):
    """Return verified whole THB or nulls on ambiguous/unsupported fixture evidence."""
    result = dict(estimated_total_thb=None, member_share_thb=None, pending_evidence_thb=None,
                  draft_request_thb=None, paid_to_date_thb=None, review_reason="unsupported_packet")
    try:
        if pack not in ("us","th") or len(case.pages) != 5:
            raise Unresolved("Unsupported layout or incomplete case")
        check_packet_identity_and_chronology(pack, case)
        calculate = th_amounts if pack == "th" else us_amounts
        total, share, pending, draft, reason = calculate(policy, case)
    except (Unresolved, ValueError) as exc:
        result["review_reason"] = str(exc)
        return result
    result.update(estimated_total_thb=total, member_share_thb=share, pending_evidence_thb=pending,
                  draft_request_thb=draft, review_reason=reason)
    return result
