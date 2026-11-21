# ZeroUpfront synthetic training samples
14 training conversations and 7 held-out conversations. Each JSONL row contains system, user and assistant messages. The user message contains fictional text exhibits and the task. The assistant message is the expected JSON answer. For evaluation, supply only the first two messages to the model. Compare its answer with the third message.

## Source and scope
The shared Drive inventory contained 12 claim/billing files and 12 medical-record PDFs. Representative pages were inspected for layout: a Thai hospital registration sheet with HN and demographic fields, and a photographed inpatient statement with Thai line items, a subtotal, discounts, net charges and a page counter. The examples reproduce these structural features using invented values. No source patient text, identifier, image or individual case was imported. Thai clinical narratives are invented. Policy clauses, amounts, coverage labels and authorizations are mock teaching material derived from the project's fictional Lotus and River scenarios. No actual policy wording was verified. These are text examples for a document-reading model after text extraction. They do not train image recognition.

## Review
Billing: score the reported amounts, detail sum, reconciliation and nulls independently. A final statement alone does not prove payment. A missing page leaves reconciliation unresolved.
Records: match HN before linking clinical evidence. Separate medical history from the current plan, preserve Thai terminology, and leave absent codes unknown.
GOP: compare request status and THB amounts exactly. Verify each quoted clause against the cited exhibit and check whether it supports the adjustment. An IPD-ready draft still needs staff review and an insurer decision.
The evaluation cases use distinct IDs and amounts but share task templates and mock policies with training. Scores describe these fixtures only. Labels have been generated for the project and have not undergone hospital or insurer review.
