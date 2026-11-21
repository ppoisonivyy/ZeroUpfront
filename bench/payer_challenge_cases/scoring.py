"""Map the public API vocabulary onto the independently frozen assertions."""
from collections import Counter
import re

# Some target observations are a verified routing choice or request for a human check.
# A general payee review cannot substitute for an asserted provider-name mismatch.
TARGET = {
    "aia-amount": "aia_amount_mismatch", "aia-encounter": "aia_admission_mismatch",
    "aia-patient": "aia_missing_consent", "aia-clinician": "aia_missing_certification",
    "aia-ink": "aia_signature_review", "cms-member": "cms_member_mismatch",
    "cms-identity-unverified": "cms_member_review", "cms-total": "cms_total_mismatch",
    "cms-reference": "cms_original_claim_reference", "cms-disposition": "cms_disposition_mismatch",
    "fep-provider": "fep_assignment_provider", "fep-signature": "fep_assignment_signature",
    "fep-member-route": "fep_member_reimbursement", "fep-total": "fep_total_mismatch",
}
CONFIRM = {
    "aia-amount": {"aia_amount_matches"}, "aia-encounter": {"aia_admission_matches"},
    "cms-member": {"cms_insured_id_agrees"}, "cms-disposition": {"cms_disposition_agrees"},
    "cms-reference": {"cms_initial_claim_type", "cms_original_reference_present"}, "cms-total": {"cms_stated_total_agrees"},
    "fep-provider": {"fep_provider_assignment"}, "fep-signature": {"fep_provider_assignment"},
    "fep-total": {"fep_stated_total_agrees"},
}
MANUAL = {
    "aia-patient": "aia_signature_review", "aia-clinician": "aia_signature_review",
    "aia-amount": "aia_amount_review", "aia-encounter": "aia_admission_review",
    "cms-member": "cms_member_review", "cms-total": "cms_amount_review",
    "fep-total": "fep_amount_review", "fep-provider": "fep_payee_review",
}
# Six defect cases contain an independently specified positive printed value.
PRINTED = {"aia-th-cents": "87513.42", "aia-en-id-decoy": "AN-HO825", "cms-member": "HM0130891",
           "cms-cents": "12345.78", "fep-wrong-provider": "Saffron Bay Rehabilitation", "fep-cents": "158050.07"}


def location(spec, field):
    family = spec["family"]
    if family.startswith("aia"):
        return "records", (2 if family == "aia-th" else 1) + int(field in {"aia-encounter", "aia-clinician"})
    return ("bill" if family == "cms" else "records"), 1


def normalized(text):
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def evaluate_field(entries, spec, field, *, anomaly):
    role, page = (spec["role"], spec["page"]) if anomaly else location(spec, field)
    item = next((r for r in entries if r["code"] == TARGET[field]), None)
    citations = [c for c in (item or {}).get("sources", []) if c["role"] == role and c["page"] == page]
    other_codes = {r["code"] for r in entries}
    if anomaly:
        if field == "aia-ink" and "aia_missing_consent" in other_codes:
            state = "contradiction"
        elif item and citations:
            state = "target-and-page"
        elif item:
            state = "wrong-page"
        elif MANUAL.get(field) in other_codes:
            state = "manual-only"
        else:
            state = "missed"
    elif item:
        state = "false-alert"
    elif any(r["code"] in CONFIRM.get(field, ()) and any(c["role"] == role and c["page"] == page for c in r["sources"]) for r in entries):
        state = "affirmed"
    elif MANUAL.get(field) in other_codes:
        state = "manual-only"
    else:
        state = "no-targeted-alert"
    result = {"field": field, "state": state, "expected_role": role, "expected_page": page}
    value = PRINTED.get(spec["id"]) if anomaly else None
    if value:
        # FL47 has separate dollar/cents cells. In-order literal excerpts from both cells are sufficient.
        fragments = [normalized(c["quote"]) for c in citations]
        result["literal_in_form_citations"] = normalized(value) in "".join(fragments)
        result["literal_in_message"] = bool(item and normalized(value) in normalized(item["message"]))
    if item:
        result["actual"] = item
    return result


def score(specs, observations):
    by_id = {obs["id"]: obs for obs in observations}
    rows = []
    for spec in specs:
        obs = by_id[spec["id"]]
        entries = [*obs["findings"], *obs["checks"]]
        rows.append({"id": spec["id"], "safe": obs["safe"], "originals_intact": obs["originals_intact"],
                     "target": evaluate_field(entries, spec, spec["need"], anomaly=True) if "need" in spec else None,
                     "clear": [evaluate_field(entries, spec, field, anomaly=False) for field in spec["clear"]]})
    targets = [row["target"] for row in rows if row["target"]]
    return {"summary": {"cases": len(rows), "targets": dict(Counter(t["state"] for t in targets)),
                        "aligned_fields": dict(Counter(x["state"] for r in rows for x in r["clear"])),
                        "printed_values_exact_in_form_citations": sum(t.get("literal_in_form_citations", False) for t in targets),
                        "printed_values_exact_in_messages": sum(t.get("literal_in_message", False) for t in targets),
                        "printed_value_challenges": sum("literal_in_form_citations" in t for t in targets),
                        "unverified_cases_safely_held": sum(r["safe"] for r in rows),
                        "intact_originals": sum(r["originals_intact"] for r in rows)}, "rows": rows}
