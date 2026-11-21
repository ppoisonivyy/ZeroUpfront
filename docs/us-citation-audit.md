# Do the cited passages support each US policy answer?

The benchmark produced 72 outputs. Its original rubric tests whether an authentic quote falls on an accepted physical page. This review asks whether a coordinator who opens that quote lands on the rule that supports the reported value. It uses the same source edition and model outputs. [Official 2026 OPM brochure](https://www.opm.gov/healthcare-insurance/healthcare/plan-information/plans/pdf/2026/brochures/71-005.pdf) · [Original benchmark](us-policy-accuracy.md)

## Method

Each distinct combination of scenario, page and quotation was shown once in a list without model arm or question language. I compared the 45 unique anchors with the source layout, then mapped those judgments back to all 87 citation occurrences. The same reviewer had authored the source-based question set and knew of the two Thai retrieval failures. This was a post-run review by one project reviewer.

An anchor received credit for a field when the surrounding operative paragraph, bullet with subordinate bullets, or table row established the field's value for the correct option and population. A coordinator could use the section and column headers or read adjacent text within that rule. Another paragraph on the same page needed an anchor of its own. Quotation matching, exact typed values and answerability were checked separately. A scope-valid anchor can support several fields in one original benefit row. The benchmark prompt requested one short anchor per cited page, which limited evidence for multiple provisions on the same page.

| Condition | Correct, locally supported fields | Answerable scenarios with every field correct and locally supported |
| --- | ---: | ---: |
| Full policy, English | 31/35 | 12/16 |
| Full policy, Thai | 31/35 | 12/16 |
| Hybrid retrieval, English | 31/35 | 12/16 |
| Hybrid retrieval, Thai | 24/35 | 10/16 |

All four conditions had the same four incomplete explanations. The Thai retrieval arm also withheld the hearing-aid and therapy answers. Across the 87 occurrences, 78 pointed to a provision supporting at least one requested field. One pointed to a cross-reference, one to a continuation heading, and seven supplied background for an unknown individual amount. [Per-anchor and per-cell audit](../bench/us_citation_audit.json)

## Where page-level scoring hid a gap

- **Domestic penalty and overseas exemption.** Every output cited the domestic penalty on physical page 24. A separate exceptions bullet establishes whether an ordinary Bangkok admission needs precertification. Selecting the relevant page satisfied the frozen rubric even when the anchor covered only the domestic field. [Physical page 24](https://www.opm.gov/healthcare-insurance/healthcare/plan-information/plans/pdf/2026/brochures/71-005.pdf#page=24)
- **Catastrophic maximum.** On page 35 the threshold anchor targets the correct Standard, Self Only, Preferred provision. The failure concerned the other field. A later list specifies whether the precertification penalty accumulates. The same issue arose on page 60, where the speech-device allowance and the exclusion for ordinary computer equipment appear in separate blocks. [Page 35](https://www.opm.gov/healthcare-insurance/healthcare/plan-information/plans/pdf/2026/brochures/71-005.pdf#page=35) · [Page 60](https://www.opm.gov/healthcare-insurance/healthcare/plan-information/plans/pdf/2026/brochures/71-005.pdf#page=60)
- **Overseas pharmacy.** Each answer had the correct deductible and filing deadline. A single anchor landed in either the benefits paragraph or the claims-filing paragraph. Both are on the same page. [Page 132](https://www.opm.gov/healthcare-insurance/healthcare/plan-information/plans/pdf/2026/brochures/71-005.pdf#page=132)
- **Table rows and pointers.** The therapy row on page 81 groups both plan options' visit limits under one service; opening that row can substantiate both values. On the enrollment question, native extraction split several digits, but the original Basic Self Plus One row and employee biweekly column confirmed the returned values. The Thai retrieval failures cited page 56, which directs readers elsewhere for hearing-aid benefits and continues a therapy table without the visit limits. Those pointers explain why a search hit looked relevant; neither entails the requested values. [Page 81](https://www.opm.gov/healthcare-insurance/healthcare/plan-information/plans/pdf/2026/brochures/71-005.pdf#page=81) · [Rate table](https://www.opm.gov/healthcare-insurance/healthcare/plan-information/plans/pdf/2026/brochures/71-005.pdf#page=168) · [Page 56](https://www.opm.gov/healthcare-insurance/healthcare/plan-information/plans/pdf/2026/brochures/71-005.pdf#page=56)

## Unknown individual amounts

All eight outputs on the two unanswerable scenarios returned the expected unknown. Seven also cited a policy page. Page 131 describes a facility guarantee arrangement; it gives no individual guarantee amount. Page 35 describes a plan maximum; it gives no individual accumulated balance. These are germane explanations for requesting a case record. Empty gold page lists measure abstention and do not make the background citations spurious. No negative-case model output invented an amount.

Keep a source reference for each consequential field. Allow separate anchors on the same physical page and preserve table row, column and effective scope. These scores use a single reviewer, one edition and authored tasks. They establish where the original interface lost evidence granularity. They do not calibrate clinical, insurer or production accuracy.
