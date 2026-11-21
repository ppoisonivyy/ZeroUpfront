# ZeroUpfront

ZeroUpfront helps hospital staff catch missing evidence before an inpatient insurance request reaches the payer. A coordinator can open the exact policy clause, correct the packet and send the reviewed version to the insurer. At discharge, staff can trace a charge or payment discrepancy back to the original bill, clinical record or guarantee.

## Who uses each desk

Choose a hospital first. The example usernames below belong to that hospital. Each signs in to a different desk.

| Sign-in | What this person needs to know | What they can do |
| --- | --- | --- |
| **Hospital coordinator** · `coordinator` | “What is missing before I send this request?” | Inspect the patient’s evidence, correct the packet, review the insurer form, submit it and answer a payer question. This is the starting account for hackathon judges. |
| **Insurer reviewer** · `reviewer` | “What exactly did the hospital send our payer?” | Read the submitted revision and its original attachments. Ask the hospital a question tied to a document and physical page. The payer owns the coverage decision. |
| **Hospital finance** · `finance` | “How much did we actually receive, and what is outstanding?” | Read the payer amount, credits and balance for assigned discharge cases. The Pattaya example shows the difference between a remittance instruction and receipt of funds. |

The treating physician supplies the signed medical report. The patient receives treatment and hears the deposit decision from the hospital. Both participate without a demo login. Staff apply a valid written guarantee at admission and refer changed or missing terms back to the payer.

**Presenting the flow.** Allow about two minutes with two browser windows ready. Open Canal Bridge as `coordinator` in one and as `reviewer` in a private window. Show the missing evidence, correct it, pause at staff review, then submit and open the same revision in the insurer window. The handoff ends with a request awaiting a payer decision. If judges ask about settlement, allow another 30 seconds to open `finance` on the separate Pattaya case. These are presentation estimates. [Detailed walkthrough](docs/demo.md)

<a id="coordinator-workspace"></a>

## A case from hospital desk to insurer inbox

Amelia Morgan is a fictional patient at Canal Bridge Demo Hospital. Her knee arthroscopy estimate is **THB 128,000**, within her fictional Meridian Assist plan’s **THB 150,000** limit. The hospital still needs a signed medical report before it can submit her request.

**1. Find the missing signature.** On case **ZU-0248**, the coordinator opens physical page 12. The highlight marks the words requiring the treating physician’s signature, indication and planned procedure on the original policy.

![Amelia’s missing report beside the highlighted signature requirement on original policy page 12](docs/figures/amelia-rule.png)

**Try a handwritten report.** The bundled signed sample uses a known typed signature field. To try a scan, upload the two-page fictional report and inspect the treating physician’s signature area on physical page 2. The coordinator confirms the encounter, visible mark and page before the insurer form can be reviewed. A blank field should remain pending. An optional, hospital-approved OpenAI visual check can suggest a page for inspection. A visible mark alone cannot establish who signed it. [Marked scan (PDF)](fixtures/physician-reports/canal-bridge-marked.pdf) · [Blank comparison (PDF)](fixtures/physician-reports/canal-bridge-blank.pdf)

**2. Review the corrected request.** Attaching the bundled signed sample creates revision 2. Uploading a report from disk records separate revisions for receipt and staff confirmation. The coordinator previews the insurer form, checks the supporting PDFs and marks that revision reviewed before submitting it.

![Amelia’s corrected request in the hospital form review](docs/figures/amelia-request.png)

**3. See what reached the insurer.** A separately signed-in Meridian Assist reviewer can open the submitted revision and its attachments. The hospital queue now shows **Waiting for insurer**. The payer makes the coverage and payment decision.

![Meridian Assist’s insurer workspace showing Amelia’s submitted request](docs/figures/amelia-inbox.png)

The 30-second captioned recording follows this case in a disposable hospital workspace and ends with a live test on US and Thai payer forms. [Recording guide](demo/README.md) · [Captions](demo/captions.srt)

<a id="run-the-demo"></a>

## Try the app

With Python 3.12, uv, Node 24 with npm, and PostgreSQL’s `initdb` and `pg_ctl` installed, start the synthetic two-hospital demo. The case above runs without an API key.

```sh
npm --prefix web ci
npm --prefix web run build
uv run --locked python -m app.hospital_demo
```

Open the hospital directory and select **Canal Bridge**, then open **Pre-arrival cases** for Amelia. The first interactive launch prompts for separate passwords for `coordinator` (hospital coordinator) and `reviewer` (insurer) in each hospital. If the host has already set up the demo, use the credentials they provide privately. [Local directory](http://127.0.0.1:8040/) · [Accounts and password reset](docs/hospital-workspaces.md)

| Another case to try | What to look for |
| --- | --- |
| **VISIT-CB-001** · Discharge | Find the repeated pharmacy charge on bill page 2, apply the corrected bill and preview the reviewed export with its original attachments. [Earlier discharge walkthrough (MP4)](docs/figures/discharge-walkthrough.mp4?raw=1) |
| **VISIT-CB-FX** · Settlement | Inspect the guarantee, compare the dated ECB reference from Frankfurter with simulated bank offers, and reconcile a THB 238,700 receipt against a THB 239,000 guarantee. [Pattaya rehearsal](docs/demo.md#pattaya-fx-rehearsal) |

## Where OpenAI fits

OpenAI can transcribe scanned pages, read Thai or English guarantee wording about exchange fees, and give a second reading of supported payer forms with page citations. Staff can inspect the original PDF beside each finding. Python checks identifiers and amounts, and PostgreSQL keeps the reviewed revisions and sources in a separate database for each hospital. [Model evaluation](docs/payer-review-design.md) · [Architecture](docs/architecture.md)

## Human review after discharge

When a payer asks a question or declines a claim, the coordinator can record the follow-up owner, due date and the exact reply sent. A coordinator reviews the Thai/English patient statement before sharing it. New receipts trigger another review. Finance staff can read the balance for an assigned case. [Discharge follow-up guide](docs/demo.md#human-review-after-a-payer-reply)

## What we measured

| Test | Result |
| --- | --- |
| Synthetic AIA Thailand, US CMS-1450 and BCBS FEP claims on known form layouts | The current regression located **11/11** target issues on the correct page, with **6/6** exact changed-value citations, **0/45** false alerts on aligned fields and **14/14** unverified cases held. A fresh panel passed **8/8** payee and amount checks. [Holdout](docs/payer-holdout.md) · [Fresh panel](docs/payer-confirmation.md) |
| Two synthetic, image-only physician reports | In a live OpenAI check, the visual helper suggested page **2 of 2** for the example with a pen mark (7.3 s) and returned **uncertain** for the otherwise identical blank report (6.1 s). Staff confirmed the page in a separate browser test. These two examples demonstrate the workflow. |
| 10,000 synthetic inpatient encounters | All **760** timed HTTP requests passed. The restore recovered **11,040** revisions and **47,048** original PDF blobs. Median worklist render time was **0.82 seconds** on the test machine. [Database benchmark](docs/discharge-scale-benchmark.md) · [Browser measurements](docs/ux-redesign.md) |

Actual payer acceptance and hospital staff time savings have yet to be measured. [Scaling benchmarks](docs/scaling.md) · [Deployment](docs/deployment.md) · [Security and encryption](docs/security-and-encryption.md) · [Privacy by jurisdiction](docs/privacy-by-jurisdiction.md)

## Hackathon declaration

The team planned the workflow before the event. At the Bangkok kickoff on 21 November 2026 the repository held a README, demo outline, ignore rules and an empty app directory. During the hackathon the team built the evidence checks, revision history, hospital and insurer workspaces, reviewed exports, settlement rehearsal and synthetic test cases. The declaration identifies the public payer forms, supplied sample corpus, open-source components and OpenAI services used. [Build declaration and evidence](docs/hackathon-declaration.md) · [Third-party credits](THIRD_PARTY.md) · [Contributor setup](CONTRIBUTING.md)
