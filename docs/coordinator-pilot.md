# Pilot for hospital insurance coordinators

**Primary question.** Can a coordinator reach a correct, source-supported disposition faster with ZeroUpfront? For a complete case, success is a staff-reviewed guarantee-of-payment (GOP) request for the active revision. For a blocked case, success is identifying the exact missing evidence and withholding the request. Only the insurer can issue the guarantee. Bangkok Hospital Phuket describes gathering the medical report and estimate, requesting insurer adjustments when circumstances change, and receiving the insurer's guarantee. [Hospital workflow](https://www.bangkokhospital.com/en/phuket/page/international-patient-services-bpk)

## Trial design

- Start with four coordinators, each reviewing six matched pairs of previously unseen synthetic cases. That yields 24 manual and 24 assisted reviews. Within each pair use **distinct cases** matched on policy complexity, document quality, language and expected disposition. Randomly assign one to each method. Balance manual-first and assisted-first sessions for each coordinator. Each person sees a case once.
- Include clean cases, missing estimates, incorrect encounters, conflicting riders, unreadable digits and corrections with unchanged totals. Mix English and Thai, digital and scanned input, and policy editions beyond the research benchmark. Use the same source material formats, permitted tools and request template in both arms. Give both groups practice on separate examples.
- Before the trial, an experienced insurance coordinator and a second qualified reviewer prepare the answer key from the source pages. Record permissible alternative clauses, required case exhibits, correct values and units, missing information and the intended action. Resolve disagreements before testing. Have an independent reviewer grade each anonymized deliverable against the key with study arm and timings hidden.
- Pin case revision, exhibit digests, policy edition and riders, application commit, extraction model, prompt, checker and template version. Record a coordinator's corrections and reasons. Keep the first attempt as well as the final disposition.

## Scorecard and proposed decision rules

| Measure | How to score it |
| --- | --- |
| Time to correct disposition | Start when the assigned packet becomes available. Stop when the coordinator submits a disposition that passes adjudication. Include time spent on corrections. Record active staff work separately from elapsed time and system waiting. Report correct requests and correct gap dispositions separately. Cases still incorrect at the agreed time limit count as unsuccessful and remain visible in both arm denominators. |
| Evidence and arithmetic | A material field passes only when its value, currency/unit, applicable option and revision are correct and its cited clause, exception, table row or case exhibit supports that value. Count unsupported fields, correct abstentions, unnecessary escalations and first-attempt corrections. |
| Critical false-ready | Count every packet presented as ready with a wrong encounter or revision, unsupported material amount, missing mandatory exhibit or unproven guarantee. Record whether staff caught it and whether it reached export. |
| Economics | Record billed API usage for every attempt, OCR, retries, hosting allocation and reviewer minutes per case. Record insurer response time separately from staff productivity. |

**Continue to a larger supervised pilot** if there are zero critical false-ready events in the assisted arm, at least as many first-attempt correct dispositions as manual review, and at least a 20% median within-pair reduction in elapsed time on correctly resolved pairs. For each such pair, divide manual minus assisted elapsed time by manual elapsed time. Report the number of timeouts and incomplete pairs beside that median. A critical event overrides any favorable average. Investigate it, add a regression test and repeat on fresh cases. These thresholds guide the next supervised pilot. A small sample cannot establish an insurer-wide error rate.

## Interpreting cost and speed

### Discharge and settlement

Extend the matched-case exercise with a revised guarantee, a queried extra night, a partial decision and a short beneficiary credit. Give the manual and assisted arms the same underlying evidence. Have a hospital coordinator, a payer representative and hospital finance independently grade the final disposition and patient explanation.

Record staff minutes spent checking sources, correcting, contacting the payer and reconciling. Report those minutes per correctly resolved case, together with the share of cases needing a follow-up or correction and the number of unresolved cases. Measure elapsed payer response time and time to the final bank credit separately. Record each premature closure, incorrect patient charge, wrong guarantee revision and unauthorized disclosure. A count of interface confirmations measures checkpoints. Staff time requires observing people doing the work.

On the seeded Pattaya path, the operator confirms one simulated trade and records two bank credits. Record whether the operator accurately explains why the insurer owes THB 300 and the patient owes THB 0 for FX. Include a lost booking response and an expired offer. Check that the operator retrieves the saved trade or requests a new offer without producing a duplicate booking.

### Policy review economics

The 168-page US experiment estimated **$1.27 per policy question** for two generation stages. Their paired time sums had a **12.5-second median**. All 70 substantive field assignments had source-localized support in a project AI audit of 16 answerable scenarios asked in two languages. Coordinator review, full-case cost, human time savings and payer outcomes remain unmeasured. [Benchmark and limitations](us-hybrid-decision.md)

At the Bank of Thailand's 20 November 2026 reference rate of THB 33.953/USD, $1.27 is about THB 43.12. A 2025 King Chulalongkorn Memorial Hospital posting offered THB 45,000–50,000/month for an experienced nurse handling private-insurance coverage checks. Assuming 160 paid hours/month, one comparable question breaks even on **8.3–9.2 net active staff minutes saved**. Three separately charged questions cost about THB 129 and require roughly **25–28 minutes** saved. This example uses one role's base salary and excludes benefits and non-model costs. Use the partner's loaded hourly rate and observed calls per case to calculate pilot economics. [Hospital posting](https://jobs.kcmh.or.th/uploads/announce/pos/POS680150.pdf) · [Bank of Thailand reference rate](https://app.bot.or.th/BTWS_STAT/statistics/ReportPage.aspx?language=eng&reportID=123)
