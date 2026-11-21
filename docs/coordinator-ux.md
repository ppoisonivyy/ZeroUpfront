# Coordinator workspace design review

Give the hospital coordinator one place to answer three questions. What holds up this request? Which source proves it? What can I do next? The proposed desktop workflow opens a case from the queue, keeps the original evidence beside the selected finding, and asks for staff approval of a particular revision. The mockup illustrates that workflow. The working research software is a CLI and database harness. Browser intake, authenticated review and insurer-format PDF export are application build work. [Application contracts](application-design.md)

## Walk through case Z002

| Screen | What the coordinator sees | Primary action |
| --- | --- | --- |
| Case queue | A row for Z002, Alder Transit Cover, with **Itemized estimate needed** and the time of its last change. Default to cases needing an action. Use a separate view for cases waiting on an insurer. | **Open case** |
| Review revision 1 | The hospital estimated **THB 82,000**. Its first page gives a total only. On the left, the finding identifies clause AT-2 in edition AT-2026.1 and its THB 50,000 itemization threshold. On the right, the coordinator can switch between the cited policy and estimate pages. | **Replace estimate** |
| Compare the replacement | Match the member and policy edition. The replacement omits an encounter identifier. Keep it pending until the coordinator confirms the treatment and date against the hospital record. | **Confirm encounter and use estimate** |
| Review revision 2 | Once the replacement is attached, show **Processing revision 2**. When verified, show the two added service rows, **THB 52,000 hospital services** and **THB 30,000 operating team**. The total remains THB 82,000. Mark AT-2 resolved, display **Ready for staff review**, and keep revision 1 accessible in History. | **Review and approve** |
| Approved revision | Identify the reviewer and revision associated with the request and gap report. Downloading a request leaves its submission status unchanged. Recording a submission and receiving an insurer letter are separate actions. | **Download request** |

The figures, itemization requirement and gap outcomes come from the synthetic Z002 exhibits. In a live test, the corrected result became current while the original OCR request was outstanding. The older callback went into history. A coordinator who still has revision 1 open should be taken to the changed estimate before approval. [Source exhibits and measured race](same-case-revision.md) · [Rulebook](../fixtures/rulebooks.json)

## Product patterns behind the design

| Reference | Documented behavior | Decision for ZeroUpfront |
| --- | --- | --- |
| Stedi | Its benefits view puts the result at the top, with payer errors immediately below. [Portal walkthrough](https://www.stedi.com/docs/healthcare/eligibility-portal-benefits-view) | Put the blocking finding and next action at the top of the case. Keep the remaining fields available below it. |
| Availity Essentials | Its authorization workflow handles submission, inquiries and supporting attachments. A participating payer shows coordinators how to locate and respond to requests for additional information in the dashboard. [Availity operations](https://essentials.availity.com/availity/help-open/oxy_ex-1/onb-implementation-docs/implementation_docs/prior_authorization_connectivity_hub/pas/c_core_operations.html) · [Payer walkthrough](https://www.superiorhealthplan.com/newsroom/new-availity-essentials-streamline-authorizations.html) | Keep a case and its supplement together. Name the missing exhibit and let the coordinator supply it from the finding. |
| ABBYY FlexiCapture | Its verification window brings together extracted data, the page image and recognition errors. [Verification window](https://help.abbyy.com/en-us/flexicapture/12/distributed_administrator/verification_doc_window/) | Selecting an amount, exclusion or deadline opens its own source. Preserve table headers, row labels and linked exceptions. |
| GitHub | Changed files return to the reviewer's attention after being marked viewed. [Reviewing changes](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/reviewing-proposed-changes-in-a-pull-request) | Show exactly which exhibits and findings changed. Tie approval and export to the revision examined. |
| Bumrungrad International Hospital | Its published Bangkok process distinguishes checking benefits, requesting preauthorization and obtaining the insurer's written guarantee. [Patient finance guidance](https://www.bumrungrad.com/en/medical-travel-guides/patient-finance-insurance-information) | Show **Staff approved**, **Request sent** and **Guarantee received** separately. Require the insurer letter and covered amount when recording a guarantee. |

## Technology choices that affect the screen

- Use React, TypeScript and Vite for the interactive workspace. Serve it with the FastAPI case API. A native HTML table with linked case identifiers is enough for the queue. Radix Dialog (MIT) supplies focus management for replacement and approval dialogs. [React's Vite guidance](https://react.dev/learn/build-a-react-app-from-scratch) · [W3C table pattern](https://www.w3.org/WAI/ARIA/apg/patterns/table/) · [Radix Dialog](https://www.radix-ui.com/primitives/docs/components/dialog)
- Use Mozilla PDF.js (Apache-2.0) for page navigation and zoom. Store the immutable document digest, physical page, quote and surrounding text. Only draw a precise highlight when a unique span or validated image coordinates support it. Otherwise show the original page and the excerpt together. [PDF.js viewer options](https://github.com/mozilla/pdf.js/wiki/Viewer-options) · [W3C text selectors](https://www.w3.org/TR/annotation-model/#text-quote-selector)
- Keep processing, approval and export on the server. PostgreSQL serializes revision changes. A stale browser receives HTTP 412 and opens the current revision. In our research run, field-specific verification located operative evidence for every field in 32/32 answerable outputs, compared with 24/32 for a single full-policy read. These were paired questions on one edition, reviewed by the project. Coordinator speed and usability still need measurement. [Revision guards](case-revision-guards.md) · [HTTP conditional writes](https://www.rfc-editor.org/rfc/rfc9110.html#name-if-match) · [Accuracy and timing](us-hybrid-decision.md)

## What to test with coordinators

Give a coordinator the same task on distinct, matched synthetic packets in a manual PDF workflow and the proposed workspace. Counterbalance the order. Measure time to a correct reviewable request, wrong values, unsupported citations, stale approvals and minutes of staff review. Count time spent waiting for an upload or model separately. The [pilot protocol](coordinator-pilot.md) defines the scoring. Before the demo, verify these interactions.

1. A coordinator can find Z002's blocker, open the governing clause and inspect the matching case page using a keyboard.
2. After replacement, they can explain why an unchanged total resolved the gap and identify both the current and previous estimate.
3. An approval attempted from the stale revision opens the current review. An unresolved encounter or unreadable amount keeps submission-ready export unavailable.
4. The coordinator can tell whether an insurer has issued a guarantee. The interface uses text labels for each state, and announces processing updates without moving keyboard focus. [W3C status-message guidance](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html)
