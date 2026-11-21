# Discharge worklist and evidence review

A hospital coordinator can open an encounter, see what holds the packet, inspect the cited page, and record a corrected revision. The workspace gives staff review, payer correspondence and payment separate labels. A reviewed packet can still be awaiting submission.

## Where the interaction patterns came from

| Product | Observed pattern | Choice in ZeroUpfront |
| --- | --- | --- |
| Availity Essentials Pro | Detailed claim statuses and clearinghouse edits return to the hospital billing workqueue. | The encounter row shows the hospital’s review status and the payer’s disposition separately. The same record carries the corrected packet and correspondence. [Availity’s Epic integration, page 2](https://www.availity.com/wp-content/uploads/2024/05/Essentials-Pro-Epic-Integration-Flyer.pdf) |
| Linear | A dedicated triage inbox lets a team inspect work before advancing it. | The queue opens with actual claims. Staff can filter by action or find an encounter directly. Discrepancies and payer queries sort first, then packets awaiting staff review. Within each group the oldest discharge sorts first. [Linear triage](https://linear.app/docs/triage) |
| Stripe Dashboard | Selecting a dispute opens its reason, available actions and relevant evidence. | Selecting a claim opens the first cited finding directly on its PDF page. A correction creates a new revision, and the reviewer can reopen the previous packet. [Stripe dispute review](https://docs.stripe.com/disputes/responding) |
| NHS | Task lists place completion status alongside links. The design system assigns color to defined jobs and pairs it with accessible text. | Each row includes a named status. A warning shows the issue, responsible team and page to inspect. The same controls reflow for phone screens. [NHS task lists](https://service-manual.nhs.uk/design-system/components/task-list) · [NHS color guidance](https://service-manual.nhs.uk/design-system/styles/colour) |

These are documented product patterns. Coordinator preference and time saved still need a usability study with hospital staff. The pilot protocol defines tasks and measurements. [Coordinator pilot](coordinator-pilot.md)

## Decisions that affect a reviewer

- **Money and authority.** The detail view names the final bill total, cap printed in the payer letter and stated patient share. Missing figures read **Unverified**. Hospital approval, insurer decisions and recorded payments each have an explicit action.
- **An unfamiliar form.** A manual review prompt links to the original page. It calls out the encounter, amounts and signatures required by the payer. It explains that uploading the same unsupported layout leaves the hold open. An unreadable source prompts the coordinator to request a legible copy or check the scanned pages. Intake names the four accepted document roles.
- **Rehearsal access.** The local queue offers a duplicate-line example and additional selectable scenarios. The case list, counts and search results come from the workspace database. A new workspace can legitimately have an empty queue.
- **Components.** Existing React components handle application state, Lucide supplies functional icons, self-hosted Inter provides typography, and PDF.js renders the original evidence. Findings use the browser’s disclosure control. There is no new runtime dependency. The rail, layout and mark are original. [Component inventory](release-components.md)
- **Color.** The navy rail marks navigation, blue indicates an action, amber identifies work to investigate and green marks staff review. Calculated WCAG foreground/background contrast is 14.07∶1 for body text on white, 7.34∶1 for white on the primary blue, 6.04∶1 for the amber status and 6.21∶1 for the green status. Contrast measures legibility. Preference requires separate evidence. [Palette research and pilot](workspace-colors.md) · [WCAG contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)

## Browser checks

A production build served from an isolated local PostgreSQL workspace passed the following Chromium checks with synthetic data on 21 November 2026.

| What was exercised | Observed result |
| --- | --- |
| Filter claims, search for an unknown encounter, clear filters | Counts matched the rendered rows. Clearing restored the previous full list. |
| Open the duplicate-bill example, inspect its citation | The original bill opened directly to physical page 2. The source excerpt matched the selected finding. |
| Preview the correction, save R2, record staff review | The reviewed R2 allowed both an inline attachment preview and a PDF download. The historical R1 still displayed its duplicate-line finding. |
| Open an image-only Thai form page and an unsupported digital payer form | Both claims stayed on hold. Each displayed manual guidance and opened the original PDF. Neither exposed the staff-approval action. |
| Render the queue and claim at 320 and 390 CSS pixels | Neither produced horizontal page overflow. Selecting a citation focused and scrolled to the source. The pre-arrival worklist remained reachable. |

The checks cover browser behavior using synthetic cases and form specimens. They do not measure clinical accuracy, real payer acceptance, staff preference or end-to-end claims handling time.
