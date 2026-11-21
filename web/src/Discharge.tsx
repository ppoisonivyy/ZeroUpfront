import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Check,
  ChevronRight,
  ClipboardCheck,
  Download,
  FileText,
  History,
} from "lucide-react";
import { ClaimFindings } from "./ClaimFindings";
import { ClaimPill, DischargeList } from "./DischargeQueue";
import { api, displayDate, RequestError, type Source } from "./api";
import { AttachmentList } from "./Attachments";
import { SourceView } from "./SourceView";
import { RecordedEvent } from "./CaseWorkflow";
import { ClaimMutation, ClaimUpload } from "./DischargeForms";
import DischargeOcr from "./DischargeOcr";
import { GuaranteeFees } from "./GuaranteeFees";
import { PattayaSettlement } from "./PattayaSettlement";
import { useStaffSession } from "./Auth";
import { PayerSecondRead } from "./PayerSecondRead";
import {
  claimPath,
  claimHref,
  claimPayerStatus,
  dischargeRoles,
  minorMoney,
  type DischargeClaim,
  type ClaimAction,
} from "./dischargeApi";

type Panel =
  | "overview"
  | "correct"
  | "sample"
  | "approve"
  | "history"
  | "export"
  | "ocr"
  | ClaimAction;
function ClaimDetail({
  claim,
  pinned,
  reload,
  onUpdated,
}: {
  claim: DischargeClaim;
  pinned: boolean;
  reload: () => void;
  onUpdated: (next: DischargeClaim) => void;
}) {
  const { mode } = useStaffSession();
  const pattayaExample = claim.example_scenario === "pattaya_fx";
  const showPattaya = !pinned && pattayaExample && (mode === "local" || !!claim.staff_practice_hospital);
  const [panel, setPanel] = useState<Panel>("overview"),
    [selection, setSelection] = useState<Source | null>(null),
    [error, setError] = useState(""),
    [working, setWorking] = useState(false);
  const [recheckMessage, setRecheckMessage] = useState("");
  const [recheckError, setRecheckError] = useState<Error | null>(null);
  const downloadUrl = useRef("");
  useEffect(
    () => () => {
      if (downloadUrl.current) URL.revokeObjectURL(downloadUrl.current);
    },
    [],
  );
  const superseded = claim.history.some((h) => h.revision > claim.revision);
  const canRecord = (a: string) =>
    !pinned || (superseded && ["payment", "reply"].includes(a));
  const overview = () => setPanel("overview");
  const saved = () => {
    overview();
    reload();
  };
  async function recheck() {
    if (working) return;
    setWorking(true);
    setRecheckMessage("");
    setRecheckError(null);
    try {
      const response = await api(claimPath(claim.id) + "/recheck", {
        method: "POST",
        headers: { "If-Match": `"${claim.revision}"` },
      });
      const next: DischargeClaim = await response.json();
      setSelection(null);
      onUpdated(next);
      setRecheckMessage(next.revision === claim.revision
        ? `Rechecked the originals. Findings and checks are unchanged in R${next.revision}.`
        : `Rechecked the originals. Updated findings and checks are saved in R${next.revision}.`);
    } catch (e) {
      setRecheckError(e instanceof Error ? e : new Error("The originals could not be rechecked."));
    } finally {
      setWorking(false);
    }
  }
  function priority(finding: (typeof claim.findings)[number]) {
    const formSpecific = /^(aia|cms|fep)_/.test(finding.code);
    return (formSpecific ? 2 : 0) + Number(finding.severity === "blocker");
  }
  const findings = [...claim.findings].sort((a, b) => priority(b) - priority(a));
  const formChecks = (claim.checks || []).filter(check => /^(aia|cms|fep)_/.test(check.code));
  const firstCitation = findings.flatMap(f => f.sources).find(cite =>
    claim.sources.some(item => item.role === cite.role));
  const citedFile = firstCitation && claim.sources.find(item => item.role === firstCitation.role);
  const source = selection || (firstCitation && citedFile
    ? { ...citedFile, page: firstCitation.page, quote: firstCitation.quote }
    : claim.sources.find(item => item.role === "bill") || claim.sources[0]);
  const actionable =
    claim.status === "ready_for_review" ||
    claim.status === "ready_for_staff_review";
  const canVerifyOcr =
    !pinned &&
    claim.ocr_review_available === true &&
    claim.status === "needs_review" &&
    claim.findings.length > 0 &&
    claim.findings.every((f) => f.code === "verify_ocr");
  const pick = (s: Source) => {
    setSelection(s);
    if (matchMedia("(max-width:760px)").matches) {
      const viewer = document.getElementById("source-view");
      viewer?.focus({ preventScroll: true });
      viewer?.scrollIntoView({ block: "start" });
    }
  };
  const openLetter = (letter: Source) => {
    setSelection(letter);
    const viewer = document.getElementById("source-view");
    viewer?.focus({ preventScroll: true });
    viewer?.scrollIntoView({ block: "start" });
  };
  if (panel === "ocr" && canVerifyOcr)
    return <DischargeOcr claim={claim} onSaved={saved} onBack={overview} />;
  if ((panel === "correct" || panel === "sample") && !pinned && !pattayaExample)
    return (
      <ClaimUpload
        claim={claim}
        useSampleByDefault={panel === "sample"}
        onSaved={saved}
        onCancel={overview}
      />
    );
  if (
    ["submission", "reply", "payment", "approve"].includes(panel) &&
    canRecord(panel)
  )
    return (
      <ClaimMutation
        claim={claim}
        pinned={pinned}
        action={panel as ClaimAction | "approve"}
        onSaved={saved}
        onCancel={overview}
      />
    );
  if (panel === "history")
    return (
      <div className="form-wrap">
        <div className="page-title">
          <div>
            <p className="section-label">Discharge claim</p>
            <h1>Claim revision history</h1>
            <p>
              {claim.encounter} · {claim.procedure}
            </p>
          </div>
        </div>
        <div className="panel">
          {[...claim.history]
            .sort((a, b) => b.revision - a.revision)
            .map((h) => (
              <a
                className="case-row"
                key={h.revision}
                href={claimHref(claim.id, h.revision)}
                onClick={overview}
              >
                <span className="case-code">R{h.revision}</span>
                <span className="row-detail">Inspect original documents</span>
                <ClaimPill status={h.status} />
                <ChevronRight size={16} />
              </a>
            ))}
        </div>
        <button className="secondary back-action" onClick={overview}>
          <ArrowLeft size={15} />
          Back to claim
        </button>
      </div>
    );
  if (panel === "export")
    return (
      <section className="form-wrap">
        <div className="page-title">
          <div>
            <p className="section-label">Discharge claim <span className="revision-chip">R{claim.revision}</span></p>
            <h1>Claim and attachments</h1>
            <p>
              {claim.encounter} · {claim.procedure}
            </p>
          </div>
        </div>
        <div className="panel form-body">
          <h2>Claim packet</h2>
          <AttachmentList packet={claim} />
          {claim.reviewer && (
            <p className="hint">Staff reviewer · {claim.reviewer}</p>
          )}

          <div className="actions">
            {!pinned && claim.status === "staff_reviewed" && (
              <button
                className="primary"
                disabled={working}
                onClick={async () => {
                  setError("");
                  setWorking(true);
                  try {
                    const res = await api(
                      claimPath(claim.id) +
                        "/export?revision=" +
                        claim.revision,
                    );
                    if (
                      !res.headers
                        .get("content-type")
                        ?.includes("application/pdf")
                    )
                      throw new Error(
                        "The reviewed PDF could not be generated.",
                      );
                    if (downloadUrl.current)
                      URL.revokeObjectURL(downloadUrl.current);
                    downloadUrl.current = URL.createObjectURL(await res.blob());
                    const a = document.createElement("a");
                    a.href = downloadUrl.current;
                    a.download =
                      claim.id + "-discharge-R" + claim.revision + ".pdf";
                    document.body.append(a);
                    a.click();
                    a.remove();
                  } catch (e) {
                    setError(
                      e instanceof Error ? e.message : "Claim PDF unavailable.",
                    );
                  } finally {
                    setWorking(false);
                  }
                }}
              >
                <Download size={15} />
                {working ? "Preparing…" : "Download reviewed claim"}
              </button>
            )}
            <button className="secondary" onClick={overview}>
              Back to claim
            </button>
          </div>
        </div>
      </section>
    );
  return (
    <>
      <div className="page-title case-jacket">
        <div>
          <p className="section-label">Discharge claim · R{claim.revision}</p>
          <h1>{claim.procedure}</h1>
          <p>
            {claim.encounter} · {claim.member} · Discharged{" "}
            {displayDate(claim.discharge_date)}
          </p>
        </div>
        <ClaimPill status={claim.status} />
      </div>
      {claim.prior_case_id && (
        <p className="prior-link">
          <a href={"#/cases/" + encodeURIComponent(claim.prior_case_id)}>
            View linked pre-arrival case
          </a>
        </p>
      )}
      {pinned && (
        <p className="history-warning">
          Viewing claim revision R{claim.revision}.{" "}
          <a href={claimHref(claim.id)}>Open current claim</a>
        </p>
      )}
      {!pinned && !superseded && !pattayaExample && <GuaranteeFees claim={claim} openLetter={openLetter} />}
      {showPattaya ? (
        <PattayaSettlement claim={claim} onUpdated={onUpdated} reload={reload} openLetter={openLetter} />
      ) : <dl className="facts claim-facts">
        <div>
          <dt>Final bill total</dt>
          <dd>{minorMoney(claim.bill_total_minor, claim.currency)}</dd>
        </div>
        <div>
          <dt>Cap in payer letter</dt>
          <dd>{minorMoney(claim.source_reported_cap_minor, claim.currency)}</dd>
        </div>
        <div>
          <dt>Stated patient share</dt>
          <dd>
            {minorMoney(
              claim.source_reported_patient_share_minor,
              claim.currency,
            )}
          </dd>
        </div>
        <div>
          <dt>Insurer disposition</dt>
          <dd>{claimPayerStatus(claim.insurer_status || "not_sent")}</dd>
        </div>
      </dl>}
      <div className="workspace-grid discharge-layout">
        <section className="panel">
          <div className="panel-heading">
            <h2>
              <ClipboardCheck size={18} />
              Discharge review
              {claim.findings.length > 0 && <span className="quantity">{claim.findings.length}</span>}
            </h2>
            <button className="text-action" onClick={() => setPanel("history")}>
              <History size={15} />
              Version history
            </button>
          </div>
          <div className="review-body">
            {claim.findings.length === 0 ? (
              <div className="finding pass">
                <h3>
                  <Check size={16} /> No discrepancies recorded
                </h3>
                <p>
                  {claim.status === "staff_reviewed" ? `Reviewed by ${claim.reviewer || "hospital staff"}.` : "Check the original documents, then record the staff review."}
                </p>
              </div>
            ) : (
              <ClaimFindings findings={findings} sources={claim.sources} pick={pick} />
            )}
            {formChecks.length > 0 && <section className="payer-fields" aria-label="Fields read from the payer form">
              <h3>Fields read from the payer form</h3>
              {formChecks.map(check => <div key={check.code}>
                <p>{check.message}</p>
                <div className="evidence-cites">{check.sources.map((cite, i) => {
                  const file = claim.sources.find(source => source.role === cite.role);
                  if (!file) return null;
                  return <button key={i} type="button" onClick={() => pick({...file, page: cite.page, quote: cite.quote})}>
                    {dischargeRoles[cite.role as keyof typeof dischargeRoles]} · p. {cite.page}
                  </button>;
                })}</div>
              </div>)}
            </section>}
            <div className="actions">
              {canVerifyOcr && (
                <button className="primary" onClick={() => setPanel("ocr")}>
                  Verify scanned pages
                </button>
              )}
              {actionable && !pinned && (
                <button className="primary" onClick={() => setPanel("approve")}>
                  Review discharge packet
                </button>
              )}
              {(claim.status === "staff_reviewed" || pinned) && (
                <button
                  className="secondary"
                  onClick={() => setPanel("export")}
                >
                  Claim and attachments
                </button>
              )}
              {!pinned && !pattayaExample && (
                <button
                  className={
                    claim.status === "needs_review" && !claim.sample_bill_available && !canVerifyOcr ? "primary" : "secondary"
                  }
                  onClick={() => setPanel("correct")}
                >
                  Correct packet documents
                </button>
              )}
              {!pinned && claim.status === "needs_review" && (
                <button className="secondary" disabled={working} onClick={recheck}>
                  {working ? "Rechecking originals…" : "Recheck original documents"}
                </button>
              )}
              {!pinned && claim.sample_bill_available && (
                <button className="primary" onClick={() => setPanel("sample")}>
                  Try corrected bill
                </button>
              )}
            </div>
            {recheckMessage && <p role="status" className="notice">{recheckMessage}</p>}
            {recheckError && <p role="alert" className="notice">
              {recheckError.message}{" "}
              {recheckError instanceof RequestError && recheckError.status === 412 && (
                <button className="text-action" onClick={reload}>Reload current revision</button>
              )}
            </p>}
            {claim.ai_review_enabled && !pinned && claim.status === "needs_review" &&
              <PayerSecondRead key={claim.id + claim.revision} claim={claim} pick={pick} />}
            <div className="subhead documents-head">
              <h3>Source documents</h3>
              <span>{claim.sources.length} sources</span>
            </div>
            {claim.sources.map((s) => (
              <button
                key={s.role}
                className={
                  "source-row " + (s.role === source?.role ? "chosen" : "")
                }
                onClick={() => pick(s)}
                aria-pressed={s.role === source?.role}
              >
                <span className="file-icon">
                  <FileText size={16} />
                </span>
                <span className="row-detail">
                  <strong>
                    {dischargeRoles[s.role as keyof typeof dischargeRoles] ||
                      s.role}
                  </strong>
                  <small>
                    {s.label}
                  </small>
                </span>
                <ChevronRight size={15} />
              </button>
            ))}
            {claim.ocr_attestation && (
              <p className="notice">
                <Check size={15} />
                Scan verification recorded
                {claim.ocr_attestation.reviewer || claim.ocr_attestation.actor
                  ? " by " +
                    (claim.ocr_attestation.reviewer ||
                      claim.ocr_attestation.actor)
                  : ""}{" "}
                for this revision.
              </p>
            )}

          </div>
        </section>
        {source && (
          <SourceView
            source={source}
            revision={claim.revision}
            historical={pinned}
          />
        )}
      </div>
      <section className="panel workflow">
        <div className="panel-heading">
          <h2>
            <History size={17} />
            Payer correspondence and settlement
          </h2>
          <span className="small">Revision {claim.revision}</span>
        </div>
        <div className="review-body">
          {Object.entries(claim.case_paid_by_currency || {}).some(
            ([currency, amount]) =>
              amount !== (claim.paid_by_currency || {})[currency],
          ) && (
            <p className="history-warning">
              Payments across all claim revisions ·{" "}
              {Object.entries(claim.case_paid_by_currency || {})
                .map(([code, amount]) => minorMoney(amount, code))
                .join(" · ")}
              . Review prior revisions to reconcile them.
            </p>
          )}
          {claim.payer_decision ||
          Object.keys(claim.paid_by_currency || {}).length > 0 ? (
            <dl className="settlement-summary">
              <div>
                <dt>Amount in payer decision</dt>
                <dd>
                  {minorMoney(
                    claim.payer_decision?.amount_minor,
                    claim.payer_decision?.currency,
                  )}
                </dd>
              </div>
              <div>
                <dt>Payments received</dt>
                <dd>
                  {Object.entries(claim.paid_by_currency || {})
                    .map(([currency, amount]) => minorMoney(amount, currency))
                    .join(" · ") || "None recorded"}
                </dd>
              </div>
              <div>
                <dt>Settlement status</dt>
                <dd>
                  {{
                    unpaid: "No payment recorded",
                    partially_paid: "Partially paid",
                    paid: "Paid",
                    reconciliation_required: "Reconciliation required",
                  }[claim.settlement_status] || claim.settlement_status}
                </dd>
              </div>
            </dl>
          ) : null}
          {claim.events.length ? (
            <ol className="timeline-list">
              {claim.events.map((event, i) => {
                const data = { ...event.data };
                if (typeof data.amount_minor === "number") {
                  data.amount = minorMoney(data.amount_minor, String(data.currency));
                  delete data.amount_minor;
                  delete data.currency;
                }
                if (event.kind === "fx_booking" && typeof data.usd_minor === "number") {
                  data.funding_cost = minorMoney(data.usd_minor, "USD");
                  delete data.usd_minor;
                }
                return <RecordedEvent key={event.id} event={{ ...event, data }} index={i} />;
              })}
            </ol>
          ) : (
            <p className="hint">
              Record external submission after staff sign-off. A written payer
              response and an actual payment are separate records.
            </p>
          )}
          {!pattayaExample && claim.allowed_actions.some(canRecord) && (
            <div className="actions">
              {claim.allowed_actions
                .filter(
                  (a) =>
                    canRecord(a) &&
                    ["submission", "reply", "payment"].includes(a),
                )
                .map((a, i) => (
                  <button
                    className={i === 0 ? "primary" : "secondary"}
                    key={a}
                    onClick={() => setPanel(a)}
                  >
                    {
                      {
                        submission: "Record claim submission",
                        reply: "Record payer reply",
                        payment: "Record payment received",
                      }[a]
                    }
                  </button>
                ))}
            </div>
          )}
        </div>
      </section>
    </>
  );
}
export function Discharge({
  id,
  prior,
  revision,
}: {
  id?: string;
  prior?: string;
  revision?: number;
}) {
  const [epoch, setEpoch] = useState(0);
  const [loaded, setLoaded] = useState<{
    key: string;
    data?: DischargeClaim;
    error?: string;
  }>({ key: "" });
  const url = id
      ? claimPath(id) + (revision ? "?revision=" + revision : "")
      : "",
    key = url + ":" + epoch;
  useEffect(() => {
    if (!id || id === "new") return;
    const abort = new AbortController();
    api(url, { signal: abort.signal })
      .then((res) => res.json())
      .then((data) => {
        if (!abort.signal.aborted) setLoaded({ key, data });
      })
      .catch((e) => {
        if (!abort.signal.aborted)
          setLoaded({
            key,
            error:
              e instanceof Error ? e.message : "Claims could not be loaded.",
          });
      });
    return () => abort.abort();
  }, [url, key, id]);
  const reload = () => setEpoch((n) => n + 1);
  if (!id) return <DischargeList prior={prior} />;
  if (id === "new")
    return (
      <ClaimUpload
        prior={prior}
        onSaved={(c) => {
          location.hash = claimHref(c.id);
        }}
        onCancel={() => {
          location.hash = "/discharge";
        }}
      />
    );
  if (loaded.key !== key || !loaded.data)
    return (
      <div
        className="state-box"
        role={loaded.key === key && loaded.error ? "alert" : "status"}
      >
        {loaded.key === key && loaded.error ? (
          <>
            <p>{loaded.error}</p>
            <button className="secondary" onClick={reload}>
              Try again
            </button>
          </>
        ) : (
          <p>Loading discharge records…</p>
        )}
      </div>
    );
  return (
    <ClaimDetail
      key={key}
      claim={loaded.data}
      onUpdated={(next) => setLoaded((current) => current.key === key ? { key, data: next } : current)}
      reload={reload}
      pinned={!!revision}
    />
  );
}
