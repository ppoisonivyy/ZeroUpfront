# Walk a discharge claim through ZeroUpfront

A hospital coordinator is preparing the final claim for a fictional wrist-fracture admission. The payer letter sets a THB 90,000 ceiling. The hospital's bill states THB 87,500, and one pharmacy charge appears twice. Can you find the original entry, correct the packet, and see exactly what the hospital would send?

Start the local coordinator workspace, then open **Discharge claims**. The digital practice case includes all four source PDFs and runs without an API key. [Setup and local workspace link](../README.md#run-the-demo) · [Watch or pause the walkthrough (MP4)](figures/discharge-walkthrough.mp4?raw=1) · [View the animation (GIF)](figures/discharge-walkthrough.gif)

In the video, pause at **0:13** to read both THB 3,600 pharmacy lines on the original bill. At **0:29**, the corrected revision is ready for staff review. At **0:53**, the exported attachment shows the single remaining charge and the separate credit for returned supplies. [Still view of the coordinator workspace](figures/discharge-review.png)

## Try it as the hospital coordinator

| Step | What to do | What to look for |
| --- | --- | --- |
| 1. Find the charge | Choose **Try duplicate bill example**. On the new claim, open **Repeated invoice item** and select **Final itemized bill · p. 2**. | Revision R1 says **Needs investigation**. In the source viewer, invoice page 2 lists pharmacy item `MED01` for THB 3,600 twice. **Open PDF** opens the original at that page. |
| 2. Check billing's correction | Choose **Try corrected bill**. Preview the proposed PDF, confirm the files belong to this encounter, then choose **Save corrected packet**. | R2 says **Ready for staff review** and **No discrepancies recorded**. The final bill still states THB 87,500. To compare it with the earlier bill, choose **Version history**, open **R1**, then select **Open current claim** to return to R2. |
| 3. Sign off this revision | Choose **Review discharge packet**. Click an attachment to preview it. Tick the review confirmation, enter a reviewer name, and choose **Mark packet reviewed**. | The claim says **Staff reviewed**. The insurer disposition still says **Awaiting submission**. |
| 4. Inspect the export | Choose **Claim and attachments**. Click the bill filename to expand its inline preview. Choose **Open original PDF** to inspect it separately, or **Download reviewed claim** to save the reviewed packet. | The export identifies the case, revision and reviewer. Its PDF attachments panel contains the four original files for R2, including the corrected invoice. |

## Optional ending with a simulated payer decision

Use the same practice claim. Save the one-page fictional reply to your computer for step 2. It identifies member `EXAMPLE-2402`, encounter `EXAMPLE-VISIT-42`, and payer reference `REPLY-2`. [Download the fictional payer reply (PDF)](figures/demo-payer-reply.pdf?raw=1)

1. Choose **Back to claim**, then **Record claim submission**. Enter `Payer portal rehearsal` as the channel and `PORTAL-DC-42` as the reference. Enter the recorder's name and choose **Save record**. The insurer disposition changes to **Sent to insurer**.
2. Choose **Record payer reply**, enter `REPLY-2`, and select **Partially confirmed**. For the written terms, enter “We partially confirm THB 80,000 for this discharge claim.” Attach the downloaded PDF, confirm the encounter, and enter `80000` and `THB`. Enter the recorder's name and save. The decision amount appears alongside **No payment recorded**.
3. Choose **Record payment received**. Record `50000` in `THB`, reference `REMIT-1`, with a recorder name and a note such as “Simulated remittance.” Settlement shows **Partially paid**. Repeat with `30000` and `REMIT-2`. The two receipts total the payer's THB 80,000 decision, and settlement changes to **Paid**.

## Other ways to explore

The primary walkthrough uses a supported synthetic layout. The official Thai and US form rehearsals show how the workspace handles unfamiliar layouts, missing evidence and claims that still need manual review. The policy research tools separately exercise Thai and US pre-arrival packets, scans, retrieval, and page citations. [Thai form results](thai-payer-forms.md) · [US form results](us-payer-forms.md) · [Policy and fixture CLI commands](../CONTRIBUTING.md#optional-openai-workflows)

For a separate design walkthrough of pre-arrival coverage and the admission guarantee, try the [hospital and insurer prototype](workspace-review/README.md).
