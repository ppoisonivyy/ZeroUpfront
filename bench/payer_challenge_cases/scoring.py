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
PRINTED_FIELDS = {"aia-amount", "aia-encounter", "cms-member", "cms-total", "fep-provider", "fep-total"}
PRINTED = {"aia-th-cents": "87513.42", "aia-en-id-decoy": "AN-HO825", "cms-member": "HM0130891",
           "cms-cents": "12345.78", "fep-wrong-provider": "Saffron Bay Rehabilitation", "fep-cents": "158050.07"}


def location(spec, field):
    family = spec["family"]
    if family.startswith("aia"):
        return "records", (2 if family == "aia-th" else 1) + int(field in {"aia-encounter", "aia-clinician"})
    return ("bill" if family == "cms" else "records"), 1


def contains_value(text, value):
    """Match an entire printed amount, identifier or name without losing its punctuation."""
    if re.fullmatch(r"\d+\.\d{2}", value):
        whole, cents = value.split(".")
        grouped = f"{int(whole):,}"
        return bool(re.search(rf"(?<![\w.,])(?:{whole}|{grouped})\.{cents}(?!\w|[.,]\d)", text))
    pattern = r"\s+".join(re.escape(word) for word in value.split())
    return bool(re.search(rf"(?<![\w-]){pattern}(?![\w-])", text, flags=re.IGNORECASE))


def evaluate_field(entries, spec, field, pages, *, anomaly):
    role, page = (spec["role"], spec["page"]) if anomaly else location(spec, field)
    def on_expected_page(source):
        return (source["role"] == role and type(source["page"]) is int and source["page"] == page
                and page <= pages.get(role, 0) and source["quote"].strip())

    matches = [r for r in entries if r["code"] == TARGET[field]]
    item = matches[0] if matches else None
    citations = [c for c in (item or {}).get("sources", []) if on_expected_page(c)]
    other_codes = {r["code"] for r in entries}
    if anomaly:
        if len(matches) > 1:
            state = "duplicate-target"
        elif ((field == "aia-ink" and "aia_missing_consent" in other_codes)
              or (item and other_codes.intersection(CONFIRM.get(field, ())))):
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
    elif any(r["code"] in CONFIRM.get(field, ()) and any(on_expected_page(c) for c in r["sources"]) for r in entries):
        state = "affirmed"
    elif MANUAL.get(field) in other_codes:
        state = "manual-only"
    else:
        state = "no-targeted-alert"
    result = {"field": field, "state": state, "expected_role": role, "expected_page": page}
    if anomaly and field in PRINTED_FIELDS:
        value = PRINTED[spec["id"]]
        quotes = [c["quote"].strip() for c in citations]
        literal = any(contains_value(quote, value) for quote in quotes)
        if spec["family"] == "cms" and field == "cms-total":
            # FL47 stores whole dollars and cents in separate cells on the same page.
            whole, cents = value.split(".")
            literal |= any(left in (whole, f"{int(whole):,}") and right == cents
                           for left, right in zip(quotes, quotes[1:]))
        result["literal_in_form_citations"] = literal
        result["literal_in_message"] = bool(item and contains_value(item["message"], value))
    if item:
        result["actual"] = item
    return result


def score(specs, observations):
    expected_ids = {spec["id"] for spec in specs}
    counted = Counter(obs["id"] for obs in observations)
    issues = {key: sorted(ids) for key, ids in (
        ("missing", expected_ids - counted.keys()), ("unexpected", counted.keys() - expected_ids),
        ("duplicate", {key for key, n in counted.items() if n > 1}),
    ) if ids}
    if issues:
        details = ", ".join(f"{key} {', '.join(ids)}" for key, ids in issues.items())
        raise ValueError(f"Expected one HTTP observation per frozen case ({len(specs)} cases). Found {details}.")
    by_id = {obs["id"]: obs for obs in observations}
    rows = []
    for spec in specs:
        obs = by_id[spec["id"]]
        entries = [*obs["findings"], *obs["checks"]]
        required_safety = {"status": "needs_review", "payable_minor": None, "approve_http": 409,
                           "export_http": 409, "allowed_actions": []}
        observed_safety = obs["safety"]
        safe = obs["safe"] is True and all(key in observed_safety and observed_safety[key] == val
                                           for key, val in required_safety.items())
        # Every packet has these three attachments. AIA and FEP also include the admission letter.
        roles = {"bill", "summary", "records"}
        if spec["family"] != "cms":
            roles.add("letter")
        pages = obs["pages"]
        intact = (obs["originals_intact"] is True and set(pages) == roles
                  and all(type(n) is int and n > 0 for n in pages.values()))
        rows.append({"id": spec["id"], "safe": safe, "originals_intact": intact,
                     "original_documents": len(roles),
                     "target": evaluate_field(entries, spec, spec["need"], pages, anomaly=True) if "need" in spec else None,
                     "clear": [evaluate_field(entries, spec, field, pages, anomaly=False) for field in spec["clear"]]})
    targets = [row["target"] for row in rows if row["target"]]
    aligned = Counter(x["state"] for r in rows for x in r["clear"])
    return {"summary": {"cases": len(specs), "target_challenges": sum("need" in spec for spec in specs),
                        "targets": dict(Counter(t["state"] for t in targets)),
                        "aligned_field_challenges": sum(len(spec["clear"]) for spec in specs),
                        "aligned_fields": dict(aligned), "false_target_alerts": aligned["false-alert"],
                        "printed_values_exact_in_form_citations": sum(t.get("literal_in_form_citations", False) for t in targets),
                        "printed_values_exact_in_messages": sum(t.get("literal_in_message", False) for t in targets),
                        "printed_value_challenges": sum(spec.get("need") in PRINTED_FIELDS for spec in specs),
                        "unverified_cases_safely_held": sum(r["safe"] for r in rows),
                        "intact_originals": sum(r["originals_intact"] for r in rows),
                        "original_documents_in_fully_intact_cases": sum(r["original_documents"] for r in rows if r["originals_intact"]),
                        "original_documents_expected": sum(r["original_documents"] for r in rows)}, "rows": rows}


def regression_failures(rows):
    failures = []
    for row in rows:
        issues = []
        target = row["target"]
        if target:
            if target["state"] != "target-and-page":
                issues.append(f"{target['field']} {target['state']} (required {target['expected_role']} page {target['expected_page']})")
            if target.get("literal_in_form_citations") is False:
                issues.append("exact printed value missing from required form citation")
            if target.get("literal_in_message") is False:
                issues.append("exact printed value missing from message")
        issues.extend(f"false alert for {clear['field']}" for clear in row["clear"] if clear["state"] == "false-alert")
        if not row["safe"]:
            issues.append("hold, payable, actions, approval or export check failed")
        if not row["originals_intact"]:
            issues.append("original PDF check failed")
        if issues:
            failures.append({"id": row["id"], "issues": issues})
    return failures
