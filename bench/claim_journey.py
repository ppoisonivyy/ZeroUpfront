"""Generate fictional example packets and exercise the hospital preauthorization workflow over HTTP."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from io import BytesIO
import json
from pathlib import Path
import sys

from pypdf import PdfReader

from workspace_http import ROOT, server, temporary_database

sys.path.insert(0, str(ROOT))
from app.journey_examples import LOCAL_EXAMPLES, NAMES, admission, exhibits, payer_reply, pdf


INTAKE = {
    "clean": ("ready_for_review", "Have staff review the source pages before sending."),
    "wrong-member": ("HTTP 422", "Obtain the estimate issued for this member."),
    "missing-member": ("needs_review", "Ask the provider to identify the member on the exhibit."),
    "wrong-edition": ("HTTP 422", "Reconcile the edition on the estimate against the schedule."),
    "missing-edition": ("needs_review", "Supply the applicable edition and check its effective dates."),
    "wrong-encounter": ("HTTP 422", "Return the other encounter's estimate and request the correct visit."),
    "over-limit": ("needs_review", "Ask the payer to confirm excess charges or an exception."),
    "possible-exclusion": ("possible_exclusion", "Ask the payer about the documented cosmetic purpose."),
    "unknown-indication": ("needs_review", "Obtain the medical indication from the provider."),
    "missing-estimate": ("needs_itemization", "Supply priced services and check their sum."),
    "mixed-currency": ("needs_review", "Reconcile every amount in its stated currency."),
    "unsupported-currency": ("needs_review", "Have staff verify the source currency and applicable limit."),
    "duplicate-total": ("needs_review", "Clarify which total is authoritative."),
    "arithmetic-error": ("needs_review", "Obtain a corrected estimate whose service rows reconcile."),
    "unreadable-scan": ("needs_review", "Obtain a readable copy or opt in to OCR and verify the original."),
    "mixed-scan": ("needs_review", "Inspect the rendered page, including its image area."),
    "unknown-policy": ("needs_review", "Cite the applicable wording and prepare a clarification request."),
    "inactive-plan": ("needs_review", "Verify eligibility and effective status before proceeding."),
    "outpatient": ("needs_review", "Obtain the policy and clinical plan for the applicable care setting."),
    "conflicting-admission-date": ("HTTP 422", "Ask the provider to reconcile the two dates."),
    "conflicting-procedure": ("HTTP 422", "Confirm which procedure and services this admission covers."),
    "reissued-policy": ("needs_review", "Review the newly issued schedule and its exceptions."),
    "embedded-rider": ("needs_review", "Inspect the attached rider before applying the base schedule."),
    "form-field": ("needs_review", "Inspect the completed form fields before treating the estimate as verified."),
}


def documents(raw):
    return {role: (NAMES[role], content, "application/pdf") for role, content in raw.items()}


def create(client, name, headers=None):
    meta, raw = exhibits(name)
    return client.post("/api/cases", files=documents(raw), data=meta | {"confirmed": "true"}, headers=headers)


def event(client, path, revision, version, kind, fields, raw=None):
    data = {"action": kind, "workflow_version": version, "actor": "Rehearsal coordinator"} | fields
    return client.post(path + "/workflow", headers={"If-Match": f'"{revision}"'}, data=data,
                       files={"file": ("payer-correspondence.pdf", raw, "application/pdf")} if raw else None)


def observed(response, *keys):
    if not response.is_success:
        return f"HTTP {response.status_code}"
    value = response.json()
    for key in keys:
        value = value[key]
    return value


def observe(client):
    results = []

    def check(name, expected, result, remedy):
        results.append((name, str(expected), str(result), remedy))

    for name, (expected, remedy) in INTAKE.items():
        response = create(client, name)
        check(name, expected, observed(response, "status"), remedy)
        if response.is_success and expected != "ready_for_review":
            path = "/api/cases/" + response.json()["id"]
            guard = client.post(path + "/approve", json={"reviewer": "Rehearsal coordinator"}, headers={"If-Match": '"1"'})
            check(name + " approval guard", 409, guard.status_code, "Resolve the recorded findings first.")
    for name, expected in {"missing-estimate": "needs_itemization", "possible-exclusion": "possible_exclusion",
                           "partial-guarantee": "partial", "admission-mismatch": "mismatch"}.items():
        response = client.post("/api/examples/" + name)
        keys = ("admission_check", "outcome") if name == "admission-mismatch" else (
            ("insurer_status",) if name == "partial-guarantee" else ("status",))
        check("Worklist example " + name, expected, observed(response, *keys), "Inspect the timeline and original evidence.")
    key = {"Idempotency-Key": "claim-rehearsal"}
    with ThreadPoolExecutor(2) as pool:
        replay = list(pool.map(lambda _: create(client, "missing-estimate", key), range(2)))
    check("Concurrent intake replay", 1, len({r.json().get("id") for r in replay if r.status_code == 201})
          if all(r.status_code == 201 for r in replay) else 0, "Retry the unchanged packet with the same key.")
    check("Changed intake reuses a submitted key", 409, create(client, "clean", key).status_code,
          "Give the changed packet a new submission key.")
    path = "/api/cases/" + replay[0].json()["id"]
    _, raw = exhibits()

    def replace():
        return client.post(path + "/estimate", headers={"If-Match": '"1"'}, data={"confirmed": "true"},
                           files={"file": ("revised.pdf", raw["estimate"], "application/pdf")})

    with ThreadPoolExecutor(2) as pool:
        races = list(pool.map(lambda _: replace(), range(2)))
    check("Competing same-base replacements", [200, 412], sorted(r.status_code for r in races),
          "Reload the active revision before submitting a competing revision.")
    check("Superseded itemization evidence", "needs_itemization",
          observed(client.get(path, params={"revision": 1}), "status"), "Open revision history to inspect the original.")
    check("Corrected estimate, unchanged total", "ready_for_review", observed(client.get(path), "status"),
          "Review the added priced service rows.")
    check("Stale approval", 412, client.post(path + "/approve", headers={"If-Match": '"1"'},
          json={"reviewer": "Rehearsal coordinator"}).status_code, "Review the current revision.")
    check("Submission before staff review", 409, event(client, path, 2, 0, "submission",
          {"channel": "Portal", "reference": "DEMO-S"}).status_code, "Approve the reviewed current revision first.")
    approval = client.post(path + "/approve", headers={"If-Match": '"2"'}, json={"reviewer": "Rehearsal coordinator"})
    check("Approved but unsent", "not_sent", observed(approval, "insurer_status"), "Record submission only after an external send.")
    detail = client.get(path).json()
    packet = client.get(path + "/export?revision=2")
    matches = False
    if packet.is_success:
        attachments = PdfReader(BytesIO(packet.content)).attachments
        matches = len(attachments) == 3 and all(attachments[s["label"]] == [client.get(s["url"]).content] for s in detail["sources"])
    check("Exported originals match the revision", True, matches, "Compare all three embedded PDFs to the review sources.")
    reply, letter = payer_reply("query")
    check("Reply before submission", 409, event(client, path, 2, 0, "reply", reply, letter).status_code,
          "Associate the response with an actually submitted revision.")
    sent = event(client, path, 2, 0, "submission", {"channel": "Simulated portal", "reference": "DEMO-S"})
    check("Manual submission", "submitted", observed(sent, "insurer_status"), "Retain the actual transmission reference.")
    check("Duplicate stale submission", 409, event(client, path, 2, 0, "submission",
          {"channel": "Simulated portal", "reference": "DEMO-S"}).status_code, "Reload the recorded timeline.")
    check("Unattached payer assertion", 422, event(client, path, 2, 1, "reply", reply).status_code,
          "Attach the original letter and confirm its identity.")
    version = 1

    def record(name, kind, fields, raw_pdf, expected, keys, remedy):
        nonlocal version
        response = event(client, path, 2, version, kind, fields, raw_pdf)
        check(name, expected, observed(response, *keys), remedy)
        if response.is_success:
            version = response.json()["workflow_version"]
        return response

    record("Information requested", "reply", reply, letter, "query", ["insurer_status"], "Collect the requested exhibit.")
    record("Supplement attached to the query", "supplement", {"reference": "DEMO-S2", "confirmed": True,
           "notes": "Added a breakdown after the query."}, pdf(["Synthetic supplemental service breakdown."]),
           "supplement_sent", ["insurer_status"], "Keep the response and original documents together.")
    for outcome in ("denied", "authorized", "partial", "guaranteed"):
        fields, attached = payer_reply(outcome)
        record("Payer reply " + outcome, "reply", fields, attached, outcome, ["insurer_status"],
               "Review the actual written decision and its limitations.")
        comparison = {"denied": "no_guarantee", "authorized": "no_guarantee", "partial": "mismatch", "guaranteed": "matched"}[outcome]
        comparison_response = record(outcome + " admission comparison", "admission", admission(), None, comparison,
               ["admission_check", "outcome"], "Check the letter, admitted encounter and amount.")
        if outcome == "partial":
            check("Partial guarantee leaves an amount above the ceiling", "22000",
                  observed(comparison_response, "admission_check", "remaining_estimated_amount"),
                  "Confirm the remaining THB 22,000 and any deductible with finance.")
            record("Within a partial ceiling", "admission", admission(actual_amount="50000"), None,
                   "partial_scope", ["admission_check", "outcome"], "Check the excluded services and patient-share terms.")
        check(outcome + " creates no hospital waiver", None, observed(comparison_response, "deposit_decision"),
              "Hospital finance records its deposit decision independently.")
    for name, changes, difference in (
            ("Expired letter", {"actual_admission_date": "2026-12-18"}, "validity"),
            ("Admission before effective date", {"actual_admission_date": "2026-12-01"}, "validity"),
            ("Different planned day", {"actual_admission_date": "2026-12-12"}, "admission_date"),
            ("Procedure changed", {"actual_procedure": "Other procedure"}, "covered_procedure"),
            ("Facility changed", {"actual_facility": "Different hospital"}, "facility"),
            ("Price exceeds ceiling", {"actual_amount": "100000"}, "amount_or_currency"),
            ("Currency changed", {"currency": "USD"}, "amount_or_currency")):
        r = record(name, "admission", admission(**changes), None, "mismatch", ["admission_check", "outcome"],
                   "Seek an amended letter before relying on the previous terms.")
        check(name + " reason", True, r.is_success and difference in r.json()["admission_check"]["differences"],
              "Use this specific difference in the clarification.")
    record("Missing staff verification", "admission", admission(letter_confirmed=False), None, "needs_review",
           ["admission_check", "outcome"], "A coordinator verifies the actual letter conditions.")
    record("Confirmed admission", "admission", admission(), None, "matched", ["admission_check", "outcome"],
           "Route to hospital finance for its independent decision.")
    for outcome in ("waived", "required"):
        fields = {"outcome": outcome, "notes": "Synthetic hospital finance decision."}
        if outcome == "required":
            fields.update(amount="2000", currency="THB")
        record("Explicit hospital deposit " + outcome, "deposit", fields, None, outcome, ["deposit_decision", "outcome"],
               "Explain the hospital's recorded decision and retain its rationale.")
    for name, changes, expected, detail in (
            ("Letter omits member", {"covered_member": ""}, "needs_review", "covered_member"),
            ("Letter names another member", {"covered_member": "EXAMPLE-OTHER"}, "mismatch", "covered_member"),
            ("Letter omits patient share", {"patient_share": ""}, "needs_review", "patient_share"),
            ("Letter effective after admission", {"valid_from": "2026-12-12"}, "mismatch", "validity")):
        fields, attachment = payer_reply("guaranteed", **changes)
        record(name + " receipt", "reply", fields, attachment, "guaranteed", ["insurer_status"],
               "Keep the letter's actual contents and original document.")
        r = record(name + " comparison", "admission", admission(), None, expected, ["admission_check", "outcome"],
                   "Ask the payer to clarify the missing or inconsistent term.")
        reason_key = "uncertainties" if expected == "needs_review" else "differences"
        check(name + " reason", True, r.is_success and detail in r.json()["admission_check"][reason_key],
              "Verify the specific member, patient-share or effective-date field.")
    hold_path = "/api/cases/" + create(client, "clean").json()["id"]
    for i, category in enumerate(("consent", "eligibility", "network", "policy", "timing")):
        held = event(client, hold_path, 1, 2*i, "hold", {"category": category, "notes": "Await written verification."})
        check(category + " operational hold", 1, observed(held, "open_hold_count"),
              "Assign staff to obtain the missing evidence.")
        guard = client.post(hold_path + "/approve", headers={"If-Match": '"1"'}, json={"reviewer": "Test staff"})
        check(category + " guards approval", 409, guard.status_code, "Resolve the active hold before approval.")
        if held.is_success:
            resolved = event(client, hold_path, 1, 2*i + 1, "resolve_hold",
                             {"hold_id": held.json()["open_holds"][0]["id"], "notes": "Staff verified the source."})
            check(category + " recorded release", 0, observed(resolved, "open_hold_count"),
                  "Retain the staff resolution and audit trail.")
    return results


def report(rows):
    passed = sum(expected == actual for _, expected, actual, _ in rows)
    lines = ["# Synthetic claim journey results", "",
             f"On {date.today().isoformat()}, **{passed}/{len(rows)} checks passed** against a Uvicorn HTTP server and an isolated PostgreSQL database. The cases combine synthetic hospital exhibits with fictional policies. The payer responses and hospital decisions are simulated. This run used digital processing and held unreadable scans for review with cloud OCR disabled.", "",
             "Allianz lists the treatment details and estimated costs needed for preauthorization and separately describes patient shares, guarantees and settlement. Bangkok Hospital Phuket describes seeking an adjustment for changes in treatment or cost. CMS describes specific denial reasons for impacted US payers. These sources informed the scenarios. The fictional rulebooks supply their thresholds and exclusions. [Allianz preauthorization](https://www.allianzcare.com/en/support/healthcare-provider-resources/medical-provider-preauthorisation-process.html) · [Allianz direct settlement](https://www.allianzcare.com/en/healthcare-providers/direct-settlement-process.html) · [Bangkok Hospital Phuket](https://www.bangkokhospital.com/en/phuket/page/international-patient-services-bpk) · [CMS prior authorization](https://www.cms.gov/newsroom/fact-sheets/cms-interoperability-prior-authorization-final-rule-cms-0057-f)", "",
             "| Scenario | Expected | Observed | Coordinator action |", "| --- | --- | --- | --- |"]
    lines.extend(f"| {name} | {expected} | {actual} | {remedy} |" for name, expected, actual, remedy in rows)
    lines += ["", "## Reproduce", "",
              "Run the checks with PostgreSQL's `initdb` and `pg_ctl` on PATH. To produce example PDFs for manual upload, add `--write-examples /path/to/new-directory`. Each folder includes the three exhibits and case metadata. The payer examples include their fictional letter.", "",
              "```sh", "uv run --locked python bench/claim_journey.py", "```", "",
              "The run measures application behavior on planned admission and financial confirmation. It does not measure population accuracy, insurer turnaround, human time saved, final claim payment or adjudication of real benefits."]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-examples", type=Path, help="Create an unused directory of sample files and intake values.")
    parser.add_argument("--report", type=Path, help="Write the expected and observed results as Markdown.")
    args = parser.parse_args()
    if args.write_examples:
        args.write_examples.mkdir(parents=True, exist_ok=False)
        for scenario in sorted(set(INTAKE) | LOCAL_EXAMPLES):
            folder = args.write_examples / scenario
            folder.mkdir()
            meta, raw = exhibits(scenario)
            (folder / "case.json").write_text(json.dumps(meta, indent=2))
            for role, data in raw.items():
                (folder / NAMES[role]).write_bytes(data)
            if scenario in {"admission-mismatch", "partial-guarantee"}:
                fields, letter = payer_reply("partial" if scenario == "partial-guarantee" else "guaranteed")
                (folder / "synthetic-payer-letter.pdf").write_bytes(letter)
                (folder / "reply.json").write_text(json.dumps(fields, indent=2))
    with temporary_database() as dsn, server(dsn, False) as client:
        rows = observe(client)
    output = report(rows)
    if args.report:
        args.report.write_text(output)
    print(output)
    return int(any(expected != actual for _, expected, actual, _ in rows))


if __name__ == "__main__":
    raise SystemExit(main())
