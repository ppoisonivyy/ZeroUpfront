# ZeroUpfront

ZeroUpfront helps hospital staff prepare an inpatient insurance request and trace each claim back to its documents. Before admission, a coordinator sees which policy requirement is missing and can send the reviewed revision to the insurer’s desk. At discharge, the coordinator reconciles the final bill, clinical record and authorization before recording the payer’s decision and payment.

The workspace puts each discrepancy beside the original PDF page. A coordinator can inspect the evidence, request a correction, review the new revision and export the packet with its original attachments. Staff record external submission, the insurer’s written decision and actual payment separately. The insurer decides what it will pay. [Watch the walkthrough with visible clicks (MP4)](docs/figures/discharge-walkthrough.mp4?raw=1) · [View the animation (GIF)](docs/figures/discharge-walkthrough.gif) · [Follow the case through a simulated payment](docs/demo.md)

[![Play the discharge walkthrough. The coordinator inspects a repeated pharmacy charge on page 2 of the original synthetic bill.](docs/figures/discharge-walkthrough-preview.png)](docs/figures/discharge-walkthrough.gif)

<a id="coordinator-workspace"></a>

## Run the demo

The two-hospital demo uses synthetic patients and runs without an API key. From the repository root, with Python 3.12, uv, Node 24 with npm, and PostgreSQL’s `initdb` and `pg_ctl` on your PATH, run the following as a regular user.

```sh
npm --prefix web ci
npm --prefix web run build
uv run --locked python -m app.hospital_demo
```

On the first interactive launch, choose passwords for `judge` (hospital coordinator) and `reviewer` (Meridian Assist insurer) for each hospital. For an existing demo, the host supplies these credentials privately. Open the [hospital directory](http://127.0.0.1:8040/). [Account setup and password reset](docs/hospital-workspaces.md)

### Try the hospital-to-insurer handoff

1. Sign in to Canal Bridge as `judge`. Open **Amelia Morgan · ZU-0248**. Her THB 128,000 knee arthroscopy estimate is within the fictional plan’s limit, but the medical report lacks a signature. **View cited clause** opens the requirement on the original policy page.
2. Attach the signed sample report, then choose **Review insurer form**. Inspect the draft and sources, select **Mark draft reviewed**, then **Submit to insurer desk**.
3. Choose **Switch to insurer desk** in the workspace menu and sign in as `reviewer`. The Meridian Assist inbox holds the submitted revision and its PDFs. Back at the hospital desk, Amelia appears under **Waiting for insurer**. Payment approval remains the payer’s decision.

The 30-second captioned film follows this handoff in a disposable copy of the staffed app and closes with a live payer-form regression. The recorder generates an MP4 locally. [Reproduce the film](demo/README.md) · [Read the captions](demo/captions.srt)

### Try discharge and payment

In the staffed Canal Bridge workspace, select **VISIT-CB-001** to inspect and correct a duplicate charge. Lakeside has its own accounts, claim history and original PDFs. A single-workspace rehearsal is also available. With the client built, run `uv run --locked python app/run_workspace.py`.

1. Open the [local discharge worklist](http://127.0.0.1:8038/) and choose **Try duplicate bill example**.
2. Open the finding. Page 2 shows the same pharmacy item twice. Choose **Try corrected bill**, inspect the replacement, confirm it belongs to the encounter and select **Save corrected packet**.
3. Choose **Review discharge packet**, review the attachments and select **Mark packet reviewed**. Open **Claim and attachments** to preview the originals or download the reviewed PDF. **Version history** still opens the first bill.

For the **Pattaya FX rehearsal**, sign in to Canal Bridge and open **VISIT-CB-FX**. Compare the ECB’s dated USD/THB reference from Frankfurter with the two simulated bank offers. Open the original guarantee or choose **Read fee terms with OpenAI** for page-cited Thai or English evidence. Record the THB 238,700 receipt against the THB 239,000 guarantee and follow the THB 300 balance through settlement. [Pattaya walkthrough](docs/demo.md#pattaya-fx-rehearsal)

The hospital app uses the team’s forest-green workspace design. On desktop the original PDF and review action appear side by side. On a phone, tap a citation to jump to the page. The two-hospital app stores submitted revisions in PostgreSQL. Its earlier browser-only prototype documents the original handoff design. [Hospital and insurer design study](docs/workspace-review/README.md)

## Where OpenAI fits

For supported scans, OpenAI transcribes the page so staff can compare the text with the original. An optional multimodal second read inspects Thai and US payer forms and returns observations with page citations. Python checks identifiers and amounts with explicit rules. The FastAPI service stores revisions in PostgreSQL, and the React workspace uses PDF.js to show the original page. Staff sign off on a specific revision. The second read cannot approve a claim or assign a payable amount. [Model evaluation and design](docs/payer-review-design.md)

## What we verified

The supported-format rehearsal runs from correction through review, export and simulated settlement. Separately, we filled published AIA Thailand, US CMS-1450 and Blue Cross Blue Shield Federal Employee Program forms with synthetic cases to test where screening should stop. On the **first blinded holdout**, the field readers identified **10 of 11** expected outcomes on the correct page. They missed a different named payee. The recorder replays the same frozen cases on known form layouts. The current app located **11 of 11** target findings on the correct page, cited **6 of 6** changed printed values exactly, raised **0 of 45** false target alerts on aligned fields and held all **14 of 14** unverified claims. After fixing the payee and cents citation, a **fresh panel passed 8 of 8** payee and amount checks on its first run. All eight unverified claims stayed on hold. Actual payer acceptance and staff time savings remain unmeasured. [Blinded results](docs/payer-holdout.md) · [Fresh confirmation](docs/payer-confirmation.md)

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
