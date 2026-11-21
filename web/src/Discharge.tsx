import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Check,
  ChevronRight,
  ClipboardCheck,
  Download,
  FileText,
  History,
  Plus,
  ReceiptText,
} from "lucide-react";
import { useStaffSession } from "./Auth";
import { api, displayDate, type Source } from "./api";
import { AttachmentList } from "./Attachments";
import { SourceView } from "./SourceView";
import { RecordedEvent } from "./CaseWorkflow";
import { ClaimMutation, ClaimUpload } from "./DischargeForms";
import DischargeOcr from "./DischargeOcr";
import {
  claimPath,
  claimHref,
  claimStatus,
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
const examples: Record<string, string> = {
  aligned: "Aligned discharge packet",
  duplicate_line: "Duplicate bill line",
  over_cap: "Bill exceeds written cap",
  missing_records: "Missing supporting records",
  unapproved_procedure: "Unapproved procedure",
  total_mismatch: "Invoice totals disagree",
  orphan_credit: "Unmatched credit",
  share_mismatch: "Patient share differs",
  member_mismatch: "Member mismatch",
  stay_extension: "Stay exceeds recorded dates",
  late_reply: "Late payer reply",
  mixed_currency: "Mixed currencies",
  unreadable_summary: "Unreadable discharge summary",
};
function ClaimPill({ status }: { status: string }) {
  return (
    <span
      className={"pill " + (status === "needs_review" ? "warning" : "good")}
    >
      <i />
      {claimStatus(status)}
    </span>
  );
}
function DischargeList({
  rows,
  prior,
}: {
  rows: DischargeClaim[];
  prior?: string;
}) {
  const { mode } = useStaffSession();
  const [example, setExample] = useState("duplicate_line"),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [search, setSearch] = useState("");
  async function openExample(scenario: string) {
    setBusy(true);
    setError("");
    try {
      const c: DischargeClaim = await (
        await api("/api/discharge/examples/" + scenario, {
          method: "POST",
        })
      ).json();
      location.hash = claimHref(c.id);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Example could not be created.",
      );
    } finally {
      setBusy(false);
    }
  }
  const cases = rows.filter((c) =>
    [c.id, c.encounter, c.member, c.procedure, c.insurer].some((field) =>
      (field || "").toLowerCase().includes(search.trim().toLowerCase()),
    ),
  );
  return (
    <>
      <div className="page-title">
        <div>
          <p className="section-label">Hospital billing</p>
          <h1>Discharge claims</h1>
          <p>
            Reconcile final charges with the clinical record and the payer’s
            written terms.
          </p>
        </div>
        <div className="page-actions">
          {" "}
          <a
            className="primary"
            href={
              "#/discharge/new" +
              (prior ? "?case=" + encodeURIComponent(prior) : "")
            }
          >
            <Plus size={16} />
            Open a discharge claim
          </a>
          {mode === "local" && (
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => void openExample("duplicate_line")}
            >
              Try duplicate bill example
            </button>
          )}
        </div>
      </div>
      {mode === "local" && (
        <details className="examples">
          <summary>More discharge examples</summary>
          <p>
            Start a fresh local example with the original bill, clinical record
            and payer evidence.
          </p>
          <div className="actions">
            <label className="stack-field">
              <span>Example</span>
              <select
                value={example}
                onChange={(e) => setExample(e.target.value)}
              >
                {Object.entries(examples).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="secondary"
              disabled={busy}
              onClick={() => void openExample(example)}
            >
              {busy ? "Creating…" : "Open example"}
            </button>
          </div>
        </details>
      )}
      {error && (
        <p className="error-message" role="alert">
          {error}
        </p>
      )}
      <section className="panel">
        <div className="panel-heading">
          <h2>
            <ReceiptText size={17} />
            Discharged encounters
          </h2>
          <span className="small">
            {cases.length} {cases.length === 1 ? "claim" : "claims"}
          </span>
        </div>
        {!!rows.length && (
          <div className="worklist-filters">
            <label className="stack-field">
              <span>Find a claim</span>
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Claim, member or encounter"
              />
            </label>
          </div>
        )}
        {!cases.length && (
          <p className="empty-view">
            {rows.length
              ? "No claims match the search."
              : "No discharge claims yet."}
          </p>
        )}
        {cases.map((c) => (
          <a className="case-row" key={c.id} href={claimHref(c.id)}>
            <span className="file-icon">
              <ReceiptText size={17} />
            </span>
            <span className="row-detail">
              <strong>{c.procedure}</strong>
              <small>
                {c.encounter ? c.encounter + " · " : ""}
                {c.member} · {displayDate(c.discharge_date)}
              </small>
              <small>{claimPayerStatus(c.insurer_status || "not_sent")}</small>
            </span>
            <ClaimPill status={c.status} />
            <ChevronRight size={16} />
          </a>
        ))}
      </section>
    </>
  );
}
function ClaimDetail({
  claim,
  pinned,
  reload,
}: {
  claim: DischargeClaim;
  pinned: boolean;
  reload: () => void;
}) {
  const [panel, setPanel] = useState<Panel>("overview"),
    [selection, setSelection] = useState<Source | null>(null),
    [error, setError] = useState(""),
    [working, setWorking] = useState(false);
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
  const source =
    selection ||
    claim.sources.find((s) => s.role === "bill") ||
    claim.sources[0];
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
    if (matchMedia("(max-width:760px)").matches)
      document
        .getElementById("source-view")
        ?.scrollIntoView({ block: "start" });
  };
  if (panel === "ocr" && canVerifyOcr)
    return <DischargeOcr claim={claim} onSaved={saved} onBack={overview} />;
  if ((panel === "correct" || panel === "sample") && !pinned)
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
            <p className="section-label">Discharge claim · R{claim.revision}</p>
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
      <div className="page-title">
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
      <dl className="facts">
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
      </dl>
      <div className="workspace-grid">
        <section className="panel">
          <div className="panel-heading">
            <h2>
              <ClipboardCheck size={18} />
              Discharge review
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
                  The hospital can review the packet for submission. The insurer
                  determines the covered amount.
                </p>
              </div>
            ) : (
              <div className="discharge-findings">
                {claim.findings.map((f, i) => (
                  <article className="finding gap" key={f.code + "-" + i}>
                    <div className="finding-kicker">
                      {f.severity === "blocker"
                        ? "Blocking issue"
                        : "Needs review"}
                    </div>
                    <h3>{f.message}</h3>
                    <p>Next owner · {f.owner || "Hospital coordinator"}</p>
                    <div className="finding-sources">
                      {f.sources.map((a, n) => {
                        const exhibit = claim.sources.find(
                          (s) => s.role === a.role,
                        );
                        return exhibit ? (
                          <button
                            key={n}
                            className="text-action"
                            onClick={() =>
                              pick({ ...exhibit, page: a.page, quote: a.quote })
                            }
                          >
                            <FileText size={14} />
                            {exhibit.label} · p. {a.page}
                          </button>
                        ) : null;
                      })}
                    </div>
                  </article>
                ))}
              </div>
            )}
            <div className="subhead">
              <h3>Original exhibits</h3>
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
                    {s.label} · p. {s.page}
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
              {!pinned && (
                <button
                  className={
                    claim.status === "needs_review" ? "primary" : "secondary"
                  }
                  onClick={() => setPanel("correct")}
                >
                  Correct packet documents
                </button>
              )}
              {!pinned && claim.sample_bill_available && (
                <button className="primary" onClick={() => setPanel("sample")}>
                  Try corrected bill
                </button>
              )}
            </div>
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
              {claim.events.map((event, i) => (
                <RecordedEvent
                  key={event.id}
                  event={
                    typeof event.data.amount_minor === "number"
                      ? {
                          ...event,
                          data: Object.fromEntries(
                            Object.entries(event.data)
                              .filter(([k]) => k !== "currency")
                              .map(([k, v]) =>
                                k === "amount_minor"
                                  ? [
                                      "amount",
                                      minorMoney(
                                        Number(v),
                                        String(event.data.currency),
                                      ),
                                    ]
                                  : [k, v],
                              ),
                          ),
                        }
                      : event
                  }
                  index={i}
                />
              ))}
            </ol>
          ) : (
            <p className="hint">
              Record external submission after staff sign-off. A written payer
              response and an actual payment are separate records.
            </p>
          )}
          {claim.allowed_actions.some(canRecord) && (
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
    data?: DischargeClaim | DischargeClaim[];
    error?: string;
  }>({ key: "" });
  const url = id
      ? claimPath(id) + (revision ? "?revision=" + revision : "")
      : "/api/discharge",
    key = url + ":" + epoch;
  useEffect(() => {
    if (id === "new") return;
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
  return Array.isArray(loaded.data) ? (
    <DischargeList rows={loaded.data} prior={prior} />
  ) : (
    <ClaimDetail
      key={key}
      claim={loaded.data}
      reload={reload}
      pinned={!!revision}
    />
  );
}
