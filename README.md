# ZeroUpfront

ZeroUpfront helps hospital billing coordinators catch problems in an inpatient insurance claim before they send it to the payer. At discharge, someone has to reconcile what the hospital billed, what the clinical record supports, what the insurer authorized and who should receive payment. A repeated pharmacy charge or a payment assignment naming a different hospital can send staff back through the whole packet.

The workspace puts each discrepancy beside the original PDF page. A coordinator can inspect the evidence, request a correction, review the new revision and export the packet with its original attachments. Staff record external submission, the insurer’s written decision and actual payment separately. The insurer decides what it will pay. [Watch the walkthrough with visible clicks (MP4)](docs/figures/discharge-walkthrough.mp4?raw=1) · [View the animation (GIF)](docs/figures/discharge-walkthrough.gif) · [Follow the case through a simulated payment](docs/demo.md)

[![Play the discharge walkthrough. The coordinator inspects a repeated pharmacy charge on page 2 of the original synthetic bill.](docs/figures/discharge-walkthrough-preview.png)](docs/figures/discharge-walkthrough.gif)

<a id="coordinator-workspace"></a>

## Run the demo

For the **password-protected two-hospital demo**, build the client with the first two commands below, then run `uv run --locked python -m app.hospital_demo`. Choose the judge passwords when prompted and open the [hospital directory](http://127.0.0.1:8040/). In Canal Bridge, select **VISIT-CB-001** to inspect and correct a duplicate charge. Lakeside has its own accounts, claim history and original PDFs. [Full demo and hosting guide](docs/hospital-workspaces.md)


The local rehearsal uses fictional patient and billing data and works without an API key. From the repository root, with Python 3.12, uv, Node 24 with npm, and PostgreSQL’s `initdb` and `pg_ctl` on your PATH, run the following as a regular user.

```sh
npm --prefix web ci
npm --prefix web run build
uv run --locked python app/run_workspace.py
```

1. Open the [local discharge worklist](http://127.0.0.1:8038/) and choose **Try duplicate bill example**.
2. Open the finding. Page 2 shows the same pharmacy item twice. Choose **Try corrected bill**, inspect the replacement, confirm it belongs to the encounter and select **Save corrected packet**.
3. Choose **Review discharge packet**, review the attachments and select **Mark packet reviewed**. Open **Claim and attachments** to preview the originals or download the reviewed PDF. **Version history** still opens the first bill.

For the **Pattaya FX rehearsal**, open the Pattaya practice case from the discharge worklist. Inspect the insurer’s THB 239,000 guarantee, compare a simulated bank spot and forward, and reconcile the hospital’s THB 238,700 credit. The booked rate stays fixed. Finance can inspect each receiving-bank advice and find the insurer’s outstanding THB 300 in the worklist. [Rehearse the Pattaya case](docs/demo.md#pattaya-fx-rehearsal)

The hospital app uses the team’s forest-green workspace design. On desktop the original PDF and review action appear side by side. On a phone, tap a citation to jump to the page. The separate insurer handoff prototype uses fictional records saved in the browser. [Hospital and insurer design guide](docs/workspace-review/README.md)

## Where OpenAI fits

For supported scans, OpenAI transcribes the page so staff can compare the text with the original. An optional multimodal second read inspects Thai and US payer forms and returns observations with page citations. Python checks identifiers and amounts with explicit rules. The FastAPI service stores revisions in PostgreSQL, and the React workspace uses PDF.js to show the original page. Staff sign off on a specific revision. The second read cannot approve a claim or assign a payable amount. [Model evaluation and design](docs/payer-review-design.md)

## What we verified

The supported-format rehearsal runs from correction through review, export and simulated settlement. Separately, we filled published AIA Thailand, US CMS-1450 and Blue Cross Blue Shield Federal Employee Program forms with synthetic cases to test where screening should stop. On the **first blinded holdout**, the field readers identified **10 of 11** expected outcomes on the correct page. They missed a different named payee. After fixing that and a cents citation, a **fresh panel passed 8 of 8** payee and amount checks on its first run. All eight unverified claims stayed on hold. Actual payer acceptance and staff time savings remain unmeasured. [Blinded results](docs/payer-holdout.md) · [Fresh confirmation](docs/payer-confirmation.md)

A database rehearsal created **10,000 distinct synthetic inpatient encounters**, kept 11,040 revisions and restored 47,048 original PDF blobs. All 760 timed HTTP requests passed their checks. The hospital worklist now displays 25 claims at a time and searches the full database. On the same machine, the median time to render the queue fell from **1.72 seconds to 0.82 seconds** across five browser sessions per version. [Database benchmark and restore instructions](docs/discharge-scale-benchmark.md) · [Browser measurements and search tradeoff](docs/ux-redesign.md)

## Running across hospitals

Deploy the same release with a separate database and staff accounts per hospital. On the 10,000-claim test set, increasing the API from one to four processes raised reviewed PDF export throughput from **73 to 230 requests/s**. A separate test kept four workers fixed and raised the API CPU quota from one to four, moving throughput from **38 to 147 exports/s**. Worklist and search throughput stayed nearly flat as processes were added. [Scaling results, controls and reproduction](docs/scaling.md)

The HTTPS release test verified the database certificate and negotiated PostgreSQL TLS 1.3. Storage encryption, backup keys, access roles and approved overseas processing depend on the hospital’s deployment and agreements. The security audit and privacy guide distinguish tested controls from the controls a real patient-data pilot still needs. [Security audit and encryption](docs/security-and-encryption.md) · [Thailand, US and EU privacy rules](docs/privacy-by-jurisdiction.md)

## Reproducible Python installation

The Python runtime supports a standard pip installation. From the repository root on Python 3.12, run:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.txt
.venv/bin/python -m pip check
```

The requirements file pins direct and transitive runtime packages with SHA-256 artifact hashes and platform markers. CI regenerates it from `uv.lock` and checks a clean pip installation. The web client uses `npm ci` with its committed lockfile. [Python requirements](requirements.txt) · [Software and licenses](THIRD_PARTY.md)

## Hackathon build declaration

The team planned the insurance workflow before the event. At the 10:00 Bangkok kickoff on 21 November, the public repository contained a README, a demo outline, ignore rules and an empty application directory. Later commits added the coordinator worklist, revision history, field checks that cite original pages, reviewed export, and separate records for payer decisions and payments. [Pre-kickoff snapshot](https://github.com/aowngong/ZeroUpfront/tree/2bdede36e2df9f917025d415e4c8bc5b5e5c452c) · [Organizer agenda and FAQ](https://luma.com/39zve8ph)

The team built on open-source libraries, OpenAI services, public payer forms and a supplied sample corpus. The team added the claim workflow, reconciliation rules and synthetic cases that test them. [Full build declaration and evidence](docs/hackathon-declaration.md) · [Third-party credits](THIRD_PARTY.md)

One Codex-assisted fix began with a missing supporting page. The model correctly read two different member IDs but linked only the claim form. The resulting change also locates the hospital’s ID on the invoice for the same encounter. Replaying six saved responses from three synthetic packets verified both pages for the CMS member and AIA admission comparisons. [See the CMS finding in the app](docs/figures/cms-member-evidence.png) · [Code change](https://github.com/aowngong/ZeroUpfront/commit/b4d21f1334f96a03d87c93addf2d5188b2caca9b) · [Replay the evidence](bench/payer_citation_replay.py)

[Setup and contributor runbook](CONTRIBUTING.md) · [Staff deployment](docs/deployment.md) · [Open-source components, licenses, services and form sources](THIRD_PARTY.md)
