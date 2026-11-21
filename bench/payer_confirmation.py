"""Prospective local-only confirmation of payee and minor-currency-unit evidence."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from payer_challenge import ROOT, evaluate, server, temporary_database
from payer_challenge_cases.packets import edit_text, output, overlay
from payer_forms_us import specimens as us

GOLD = ROOT / "bench/payer_confirmation_cases/gold.json"
DIGEST = "e3beb6c0ad0a47832d82f0d876ea29756ef7d0fc390011a9c803e01509989360"
OUT = ROOT / ".local/payer-confirmation"


def cms(spec, blanks, meta):
    total = Decimal(spec["invoice_total"])
    ed_price = total - sum(row.amount for row in us.US_ROWS[:-1])
    rows = [*us.US_ROWS[:-1], replace(us.US_ROWS[-1], price=ed_price)]
    docs = us.supporting(meta, rows, False)
    writer = PdfWriter()
    writer.append(BytesIO(us.institutional(*blanks[:2], "aligned")))
    scale = 792 / 950
    claim_dollars, claim_cents = spec["form_total"].split(".")
    ed_dollars, ed_cents = f"{ed_price:.2f}".split(".")

    def change(x, y, old):
        if old in (us.US["encounter"], us.US["member"], us.US["facility"]):
            return {us.US[key]: meta[key] for key in ("encounter", "member", "facility")}[old]
        if old == "1325":
            return ed_dollars
        if old == "11285":
            return claim_dollars
        if old == "00":
            if abs(y - (792 - 576 * scale)) < .01:
                if abs(x - 570 * scale) < .01:
                    return claim_cents
                if abs(x - 649 * scale) < .01:
                    return spec["neighbor_cents"]
            if abs(x - 570 * scale) < .01 and abs(y - (792 - (293 + 4 * 12.88) * scale)) < .01:
                return ed_cents
        return None

    edit_text(writer.pages[0], change)
    docs["bill"] = us.joined(output(writer), docs["bill"])
    return docs


def second_election(blank, page):
    printed = PdfReader(BytesIO(blank)).pages[0]
    wanted = {"5A Requested Currency": "/Currency on Bills", "5B Reimbursement Type": "/Check"}
    points = []
    for pointer in printed["/Annots"]:
        a = pointer.get_object()
        parent = a["/Parent"].get_object() if "/Parent" in a else {}
        name = a.get("/T", parent.get("/T"))
        if name in wanted and wanted[name] in a.get("/AP", {}).get("/N", {}):
            x1, y1, x2, y2 = map(float, a["/Rect"])
            points.append((min(x1, x2) + 3, min(y1, y2) + 3))
    assert len(points) == 2

    def draw(c):
        c.setFont("Helvetica-Bold", 10)
        for x, y in points:
            c.drawString(x, y, "X")
    overlay(page, draw)


def fep(spec, blanks, meta):
    rows = us.TH_ROWS.copy()
    if "invoice_total" in spec:
        rows[1] = replace(rows[1], price=Decimal(rows[1].price) + Decimal(spec["invoice_total"]) - sum(r.amount for r in rows))
    supporting_meta = {**meta, "encounter": spec.get("other_encounter", meta["encounter"])}
    docs = us.supporting(supporting_meta, rows, True)
    docs["letter"] = us.rendered([("Synthetic prior correspondence", [
        f"Reference {meta['encounter']}. Payer reviews the discharge packet and member election.",
        "This training letter does not designate a provider or settle the final bill.",
    ])])
    writer = PdfWriter()
    baseline = "member_payee" if spec["kind"] == "member" else "aligned"
    writer.append(BytesIO(us.overseas(blanks[2], baseline)))
    id_chars = iter(meta["member"][1:])

    def change(x, y, old):
        if old.isdigit() and len(old) == 1 and 454 <= x <= 602 and 704 <= y <= 730:
            return next(id_chars)
        if old == us.TH["facility"]:
            return spec["assigned"]
        if old == "THB 158,050.00" and "form_total" in spec:
            return f"THB {Decimal(spec['form_total']):,.2f}"
        if old == "SYNTHETIC TEST ATTESTATION":
            return "K. Demo" if y > 80 else "J. Sample"
        return None

    edit_text(writer.pages[0], change)
    assert next(id_chars, None) is None
    if spec["kind"] == "member":
        overlay(writer.pages[1], lambda c: c.drawString(45, 35, "Training packet prepared at " + meta["facility"]))
    elif spec["kind"] == "contradictory":
        second_election(blanks[2], writer.pages[0])
    docs["records"] = us.joined(output(writer), docs["records"])
    return docs


def prepare(spec, blanks):
    template = us.US if spec["family"] == "cms" else us.TH
    meta = template | {key: spec[key] for key in ("facility", "member", "encounter")}
    docs = cms(spec, blanks, meta) if spec["family"] == "cms" else fep(spec, blanks, meta)
    target = OUT / spec["id"]
    target.mkdir(parents=True, exist_ok=True)
    for role, data in docs.items():
        (target / (role + ".pdf")).write_bytes(data)
    return spec, meta, docs


def grade(spec, observed):
    checks = {item["code"]: item for item in [*observed["checks"], *observed["findings"]]}
    kind, family = spec["kind"], spec["family"]
    target = {"other-provider": "fep_assignment_provider", "hospital": "fep_provider_assignment",
              "member": "fep_member_reimbursement", "unlinked-provider": "fep_assignment_provider_review",
              "contradictory": "fep_payee_review", "total-agrees": family + "_stated_total_agrees",
              "total-conflict": family + "_total_mismatch"}[kind]
    item = checks.get(target, {})
    cites = item.get("sources", [])
    message = item.get("message", "")
    role = "bill" if family == "cms" else "records"
    front = [c["quote"] for c in cites if c["role"] == role and c["page"] == 1]
    ok = bool(front)
    if kind.startswith("total"):
        amount = Decimal(spec["form_total"])
        total = f"{Decimal(spec['invoice_total']):,.2f}"
        if family == "cms":
            fields = spec["form_total"].split(".")
            ok = ok and all(field in front for field in fields)
        else:
            ok = ok and any(f"{amount:,.2f}" in q for q in front)
        page = 3 if family == "cms" else 1
        ok = ok and any(total in c["quote"] and c["role"] == "bill" and c["page"] == page for c in cites)
        if kind == "total-conflict":
            ok = ok and total in message and f"{amount:,.2f}" in message
        else:
            ok = ok and family + "_total_mismatch" not in checks
    elif kind == "other-provider":
        ok = (ok and spec["assigned"] in front and spec["assigned"] in message and spec["facility"] in message
              and any(spec["facility"] in c["quote"] and c["role"] in {"summary", "bill"} for c in cites))
    elif kind == "hospital":
        ok = ok and spec["facility"] in front and "fep_assignment_provider" not in checks
    elif kind == "member":
        ok = ok and "check" in message.casefold() and "fep_provider_assignment" not in checks
    else:
        ok = ok and not ({"fep_provider_assignment", "fep_member_reimbursement", "fep_assignment_provider"} & checks.keys())
        if kind == "unlinked-provider":
            ok = ok and spec["assigned"] in front
    return {"id": spec["id"], "kind": kind, "pass": bool(ok), "expected_code": target,
            "observed_codes": list(checks), "actual": item, "safe": observed["safe"], "originals_intact": observed["originals_intact"]}


def main():
    assert sha256(GOLD.read_bytes()).hexdigest() == DIGEST
    specs = json.loads(GOLD.read_text())["cases"]
    blanks = us.get_blanks(ROOT / ".local/us-payer")
    prepared = [prepare(spec, blanks) for spec in specs]
    with temporary_database() as dsn, server(dsn, False) as client, ThreadPoolExecutor(4) as pool:
        observed = list(pool.map(lambda item: evaluate(client, item), prepared))
    rows = [grade(s, r) for s, r in zip(specs, observed, strict=True)]
    report = {"manifest_sha256": DIGEST, "rows": rows, "observed": observed}
    (OUT / "observed.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    for row in rows:
        print(row["id"], "PASS" if row["pass"] else "FAIL", "held" if row["safe"] else "UNSAFE")
    if not all(r["safe"] and r["originals_intact"] for r in rows):
        raise SystemExit("An unverified confirmation case advanced or lost its original exhibits.")
    if not all(r["pass"] for r in rows):
        raise SystemExit("A frozen field or citation expectation failed. See .local/payer-confirmation/observed.json.")


if __name__ == "__main__":
    main()
