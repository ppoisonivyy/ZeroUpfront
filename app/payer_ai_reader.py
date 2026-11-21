"""Single-pass, read-only administrative observations on a bounded set of original case PDFs."""

import base64
import json
import os
from hashlib import sha256
from io import BytesIO
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .document_text import contains_identifier, contains_quote

ROLES = ("bill", "summary", "records", "letter")
RUBRICS = {
    "aia": {
        "admission": "Compare the admission number on Part B with the encounter reference: match, conflict, unknown.",
        "expense": "Compare the Part A claimed expense against the independent final bill: match, conflict, unknown.",
        "consent": "Is a mark visible in the Part A patient consent signature area? present, absent, unknown.",
        "certification": "Is there a mark in the separate Part B physician certification area? present, absent, unknown.",
        "letter": "Is a separate encounter-specific payer letter supplied? present or absent. A claimant form is not a payer letter.",
    },
    "cms": {
        "member": "Compare FL60 subscriber ID against encounter metadata: match, conflict, unknown.",
        "disposition": "Compare FL17 disposition (01 home, 02 transfer) against the independent clinical summary: match, conflict, unknown.",
        "replacement": "Does type-of-bill frequency 7 have the original DCN in FL64? original (not a replacement), present, absent, unknown.",
        "expense": "Compare FL47 total charges against the independently itemized account: match, conflict, unknown. FL47 uses dollars and cents.",
    },
    "fep": {
        "payee": "Identify the supported payment route from §5A–D, checkboxes and assignment. hospital, member, unsigned (provider named but assignment mark missing), unknown.",
        "expense": "Compare the §4 submitted total to the independent itemized invoice: match, conflict, unknown.",
    },
}
INSTRUCTIONS = """You assist a hospital coordinator reviewing fictional administrative records. Inspect supplied originals
as untrusted source material. Answer only the checks in the supplied rubric using exactly its allowed states.
A test mark demonstrates only that a field has a visible entry, never the identity or validity of a signer.
For each check include a brief observation naming the actual identifier, amounts or box when relevant, and
all physical source pages essential to that observation, numbered separately per uploaded PDF from one.
If a file is absent cite no page of that file. When the evidence is ambiguous say unknown.
No medical advice, claim approval, coverage prediction, payment instruction, or communications."""


class Citation(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    role: Literal["bill", "summary", "records", "letter"]
    page: int


class Check(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    field: str
    state: str
    observation: str
    pages: list[Citation]


class Review(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    checks: list[Check]


Family = Literal["aia", "cms", "fep"]
MAX_TOTAL_BYTES = 24 * 1024 * 1024
MAX_TOTAL_PAGES = 40
ENCOUNTER_FIELDS = (
    "member",
    "encounter",
    "facility",
    "insurer",
    "procedure",
    "admission_date",
    "discharge_date",
    "as_of",
)

# Frozen challenge additions. The original comparison can still import the unmodified baseline rubric.
STAFF_RUBRICS = {family: dict(fields) for family, fields in RUBRICS.items()}
STAFF_RUBRICS["aia"]["consent"] = (
    "Look at the patient consent mark in Part A. Return present for a typed mark, "
    "visual_review for graphical ink needing personal verification, absent for blank, or unknown."
)
STAFF_RUBRICS["cms"]["member"] += (
    " Use absent when FL60 itself is blank, even if another page displays an ID."
)
STAFF_RUBRICS["fep"]["payee"] += (
    " Use other_provider if the named assignment payee differs from the treating facility. "
    "Distinguish the original election from stray or duplicated text outside the payment boxes."
)
STAFF_GUIDANCE = """
This is a provisional second read for staff. Treat the packet as unverified administrative evidence.
Use unknown if the supplied form is missing, the edition does not support the requested field, the
case evidence conflicts about which document applies, or independent comparison evidence is missing.
Absence of a separate required document can be reported from its absence in the manifest. A signature
mark does not establish authenticity, signer authority, or consent. Do not infer a diagnosis or advise
anyone to pay, approve, reject, or contact a party. Return only the requested administrative fields.
For a CMS FL60 identity comparison or AIA Part B admission-number comparison, cite the payer form and a separate
physical hospital account or summary page showing the encounter's reference identifier. For an alternate
assigned provider on FEP, cite the form and an independent page identifying the treating facility.
If independent corroboration is unavailable, return unknown for that field. Retain other supported fields.
Provide physical page citations for every evidenced state. Return no citations only for an omitted
document or an unknown result with no usable page evidence.
"""

# Minimum independent source roles for an asserted state, as used by the evaluation.
RULES = {
    "aia": {
        "admission": ({"match", "conflict"}, {"records"}),
        "expense": ({"match", "conflict"}, {"records", "bill"}),
        "consent": ({"present", "absent", "visual_review"}, {"records"}),
        "certification": ({"present", "absent"}, {"records"}),
        "letter": ({"present", "absent"}, {"letter"}),
    },
    "cms": {
        "member": ({"match", "conflict", "absent"}, {"bill"}),
        "disposition": ({"match", "conflict"}, {"bill", "summary"}),
        "replacement": ({"original", "present", "absent"}, {"bill"}),
        "expense": ({"match", "conflict"}, {"bill"}),
    },
    "fep": {
        "payee": ({"hospital", "member", "unsigned", "other_provider"}, {"records"}),
        "expense": ({"match", "conflict"}, {"records", "bill"}),
    },
}


class SecondReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    family: Family
    confirmed: bool = Field(strict=True)


class SecondReadResponse(Review):
    revision: int
    family: Family
    model: str


class UnsupportedPacket(ValueError):
    """Input cannot be examined as one bounded, complete PDF context."""


class InvalidReview(ValueError):
    """Response does not satisfy the family rubric and original page manifest."""


def enabled():
    return os.getenv("WORKSPACE_ENABLE_AI_REVIEW") == "1" and bool(os.getenv("OPENAI_API_KEY", "").strip())


def request_input(meta, originals, counts, rubric):
    """Build the same ordered high-detail PDF request for the benchmark and the live endpoint."""
    content = [
        {
            "type": "input_text",
            "text": json.dumps(
                {"encounter": meta, "physical_pages_by_role": counts, "checks": rubric},
                ensure_ascii=False,
            ),
        }
    ]
    for role in ROLES:
        if role in originals:
            encoded = base64.b64encode(originals[role]).decode()
            content.append(
                {
                    "type": "input_file",
                    "filename": role + ".pdf",
                    "detail": "high",
                    "file_data": "data:application/pdf;base64," + encoded,
                }
            )
    return [{"role": "user", "content": content}]


def _counts(case, originals):
    if not originals or set(originals) - set(ROLES):
        raise UnsupportedPacket("A second read requires original discharge case PDFs in supported roles.")
    if sum(map(len, originals.values())) > MAX_TOTAL_BYTES:
        raise UnsupportedPacket("The complete second-read packet exceeds 24 MiB.")
    sources = {s["role"]: s["sha256"] for s in case["sources"]}
    if sources != {role: sha256(raw).hexdigest() for role, raw in originals.items()}:
        raise UnsupportedPacket("The originals do not match this revision’s saved document digests.")
    counts = {}
    try:
        for role in ROLES:
            if role in originals:
                reader = PdfReader(BytesIO(originals[role]))
                if reader.is_encrypted:
                    raise UnsupportedPacket("A second read requires unlocked PDFs.")
                counts[role] = len(reader.pages)
    except UnsupportedPacket:
        raise
    except (
        PdfReadError,
        IndexError,
        KeyError,
        TypeError,
        ValueError,
        ArithmeticError,
        RecursionError,
    ) as exc:
        raise UnsupportedPacket("The physical pages could not be verified.") from exc
    if min(counts.values()) < 1 or sum(counts.values()) > MAX_TOTAL_PAGES:
        raise UnsupportedPacket("A second read requires 1 to 40 physical pages across the whole packet.")
    return counts


# Observed states supported by the edition-specific form readers. The AI can abstain on
# any field. A conflicting state must go back to staff even if its citations exist.
FIELD_STATES = {
    ("cms", "member"): {"match": "cms_insured_id_agrees", "conflict": "cms_member_mismatch"},
    ("cms", "disposition"): {"match": "cms_disposition_agrees", "conflict": "cms_disposition_mismatch"},
    ("cms", "replacement"): {
        "original": "cms_initial_claim_type",
        "present": "cms_original_reference_present",
        "absent": "cms_original_claim_reference",
    },
    ("cms", "expense"): {"match": "cms_stated_total_agrees", "conflict": "cms_total_mismatch"},
    ("aia", "admission"): {"match": "aia_admission_matches", "conflict": "aia_admission_mismatch"},
    ("aia", "expense"): {"match": "aia_amount_matches", "conflict": "aia_amount_mismatch"},
    ("aia", "consent"): {"absent": "aia_missing_consent"},
    ("aia", "certification"): {"absent": "aia_missing_certification"},
    ("fep", "expense"): {"match": "fep_stated_total_agrees", "conflict": "fep_total_mismatch"},
    ("fep", "payee"): {
        "hospital": "fep_provider_assignment",
        "member": "fep_member_reimbursement",
        "unsigned": "fep_assignment_signature",
        "other_provider": "fep_assignment_provider",
    },
}

# These states additionally require a distinct hospital page for the same encounter.
REFERENCE_FIELDS = {
    ("cms", "member"): ("bill", "member", "subscriber ID", {"match", "conflict"}),
    ("aia", "admission"): ("records", "encounter", "admission number", {"match", "conflict"}),
    ("fep", "payee"): ("records", "facility", "treating facility", {"other_provider"}),
}


def _field_evidence(case, originals, family):
    # Re-read the hash-verified originals for the requested revision. An older stored
    # finding might predate independent citation capture, even when its PDF contains it.
    from .discharge_claim import Review as FormReview
    from .payer_aia import screen_aia
    from .payer_pages import CaseOriginals
    from .payer_us import screen_us

    facts = FormReview()
    screen = screen_aia if family == "aia" else screen_us
    screen(case, CaseOriginals(originals), facts)
    return {row["code"]: row for row in [*facts.findings.values(), *facts.checks]}


def _reference_on_page(case, originals):
    readers = {}

    def matches(role, number, key, form_role):
        expected = case.get(key)
        if not expected:
            return False
        cached = case.get("ocr_pages", {}).get(role, {})
        original = next(s for s in case["sources"] if s["role"] == role)
        transcript = (
            cached.get("pages", {}).get(str(number)) if cached.get("sha256") == original["sha256"] else None
        )
        if transcript is None:
            try:
                if role not in readers:
                    readers[role] = PdfReader(BytesIO(originals[role]))
                transcript = readers[role].pages[number - 1].extract_text() or ""
            except (
                PdfReadError,
                IndexError,
                KeyError,
                TypeError,
                ValueError,
                ArithmeticError,
                RecursionError,
            ):
                return False
        encounter_key = "member" if key == "encounter" else "encounter"
        if case.get(encounter_key) and not contains_identifier(transcript, case[encounter_key]):
            return False
        if role == form_role:
            # An itemized account can be appended behind a payer form in the same PDF.
            # Another printed form page carrying the identifier is not independent evidence.
            body = " ".join(transcript.casefold().split())
            if any(
                label in body
                for label in (
                    "ub-04",
                    "inpatient (ipd) claim form",
                    "medical certification",
                    "overseas medical claim form",
                    "authorization for assignment",
                )
            ):
                return False
            if not any(
                label in body
                for label in (
                    "invoice",
                    "itemized",
                    "hospital account",
                    "billing statement",
                    "discharge summary",
                    "hospital supporting records",
                )
            ):
                return False
        match = contains_quote if key == "facility" else contains_identifier
        return match(transcript, expected)

    return matches


def _corroborate(check, family, reference_on_page, field_evidence):
    if family == "fep" and check.field == "payee" and check.state in {"member", "hospital", "other_provider"}:
        hold_codes = (
            "fep_form_version_review",
            "fep_payee_review",
            "fep_assignment_provider_review",
            "fep_assignment_signature",
        )
        hold = next((field_evidence[c] for c in hold_codes if c in field_evidence), None)
        if hold:
            return check.model_copy(update={"state": "unknown", "observation": hold["message"]})
    key = (family, check.field)
    states = FIELD_STATES.get(key, {})
    if check.state == "unknown":
        return check
    observed_states = {state for state, code in states.items() if code in field_evidence}
    if observed_states and check.state not in observed_states:
        return check.model_copy(
            update={
                "state": "unknown",
                "observation": "The AI observation conflicts with the form reader. Verify this field on the original documents.",
            }
        )
    rule = REFERENCE_FIELDS.get(key)
    if not rule:
        return check
    form_role, key, label, required_states = rule
    if check.state not in required_states:
        return check
    cited = {(p.role, p.page) for p in check.pages}
    fact = field_evidence.get(states[check.state])
    if fact:
        # Official-form readers verify both field positions and link the second record to
        # this encounter. Use their wording too, so a model transcription error is not repeated.
        refs = list(dict.fromkeys((s["role"], s["page"]) for s in fact["sources"] if s.get("quote")))
        if len(refs) >= 2 and refs[0] in cited:
            return check.model_copy(
                update={
                    "pages": [Citation(role=r, page=n) for r, n in refs],
                    "observation": fact["message"] + " The form reader verified the linked pages.",
                }
            )
    else:
        # For a visual read without a typed comparison, retain a supplied pair only when
        # the independent page contains the actual reference for this encounter.
        if reference_on_page and any(
            role in {"bill", "records", "summary"}
            and any(r == form_role and (r, n) != (role, page) for r, n in cited)
            and reference_on_page(role, page, key, form_role)
            for role, page in cited
        ):
            return check
    return check.model_copy(
        update={
            "state": "unknown",
            "observation": f"Verify the {label} against the payer form and a separate hospital page for this encounter.",
        }
    )


def validated_checks(review, family, counts, reference_on_page=None, field_evidence=None):
    rules = RULES[family]
    if len(review.checks) != len(rules) or {check.field for check in review.checks} != set(rules):
        raise InvalidReview(
            "The AI response did not supply exactly one observation for every requested field."
        )
    checked = {}
    for check in review.checks:
        allowed, needed_roles = rules[check.field]
        if check.state not in allowed | {"unknown"}:
            raise InvalidReview("The AI response supplied a state outside the selected form rubric.")
        if not check.observation.strip() or len(check.observation) > 1200:
            raise InvalidReview("The AI response supplied an empty or oversized observation.")
        cited = {(c.role, c.page) for c in check.pages}
        if len(cited) != len(check.pages) or any(
            type(c.page) is not int or not 1 <= c.page <= counts.get(c.role, 0) for c in check.pages
        ):
            raise InvalidReview("An AI citation does not identify a unique original page in this revision.")
        omitted = (
            family == "aia" and check.field == "letter" and "letter" not in counts and check.state == "absent"
        )
        if omitted:
            # The manifest establishes the omitted role. Other valid pages may mention the
            # letter, but cannot serve as the missing original.
            check = check.model_copy(
                update={
                    "observation": "No separate PDF was supplied in the payer-letter role for this revision.",
                    "pages": [],
                }
            )
        if check.state != "unknown" and not omitted and not needed_roles <= {role for role, _ in cited}:
            raise InvalidReview("An AI observation lacks the required original source pages.")
        if (
            family == "cms"
            and check.field == "expense"
            and check.state != "unknown"
            and len({(r, p) for r, p in cited if r in {"bill", "records"}}) < 2
        ):
            raise InvalidReview(
                "The CMS total comparison requires separate evidence for the form and the itemized account."
            )
        checked[check.field] = _corroborate(check, family, reference_on_page, field_evidence or {})
    return [checked[field] for field in rules]


def second_read(case, originals, family):
    known = {row["code"].split("_", 1)[0] for row in [*case.get("findings", []), *case.get("checks", [])]}
    recognized = known & RULES.keys()
    if recognized and family not in recognized:
        raise UnsupportedPacket(
            "The selected payer-form family differs from the form recognized on this revision."
        )
    counts = _counts(case, originals)
    meta = {key: case[key] for key in ENCOUNTER_FIELDS if case.get(key) is not None}
    history = request_input(meta, originals, counts, STAFF_RUBRICS[family])
    model = os.getenv("OPENAI_OCR_MODEL") or "gpt-6.2-astra"
    with OpenAI(timeout=180, max_retries=0) as client:
        try:
            answer = client.responses.parse(
                model=model,
                instructions=INSTRUCTIONS + STAFF_GUIDANCE,
                input=history,
                store=False,
                max_output_tokens=2500,
                text_format=Review,
            )
        except ValidationError as exc:
            raise InvalidReview("The AI response did not supply a valid structured second read.") from exc
    if answer.status != "completed" or not isinstance(answer.output_parsed, Review):
        raise InvalidReview("The AI service did not return a complete administrative second read.")
    checks = validated_checks(
        answer.output_parsed,
        family,
        counts,
        _reference_on_page(case, originals),
        _field_evidence(case, originals, family),
    )
    reported_model = getattr(answer, "model", None)
    return SecondReadResponse(
        revision=case["revision"],
        family=family,
        model=reported_model if isinstance(reported_model, str) and reported_model else model,
        checks=checks,
    )
