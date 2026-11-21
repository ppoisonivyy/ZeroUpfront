import { lazy, Suspense, useRef, useState } from "react";
import { useStaffSession } from "./Auth";
import { api } from "./api";
import { AttachmentList } from "./Attachments";
import {
  claimPath,
  dischargeRoles,
  type DischargeClaim,
  type ClaimAction,
} from "./dischargeApi";

const actionTitles: Record<ClaimAction | string, string> = {
  approve: "Sign off packet",
  submission: "Record submission",
  reply: "Record written payer reply",
  supplement: "Prepare an insurer follow-up",
  payment: "Record payment received",
};
const PdfPage = lazy(() => import("./PdfPage"));
export function ClaimUpload({
  claim,
  prior,
  onSaved,
  onCancel,
  useSampleByDefault = false,
}: {
  claim?: DischargeClaim;
  prior?: string;
  onSaved: (c: DischargeClaim) => void;
  onCancel: () => void;
  useSampleByDefault?: boolean;
}) {
  const { hosted_ocr_enabled } = useStaffSession();
  const operation = useRef(crypto.randomUUID());
  const [useSample, setUseSample] = useState(
    useSampleByDefault && !!claim?.sample_bill_available,
  );
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  return (
    <section className="form-wrap">
      <div className="page-title">
        <div>
          <p className="section-label">Discharge claims</p>
          <h1>{claim ? "Correct the packet" : "Open a discharge claim"}</h1>
          <p>
            {claim
              ? "Choose each replacement file. The prior revision remains available in history."
              : "Collect the actual discharge exhibits and check them against the hospital’s final bill."}
          </p>
        </div>
      </div>
      <form
        className="panel form-body"
        onChange={() => {
          operation.current = crypto.randomUUID();
        }}
        onSubmit={async (e) => {
          e.preventDefault();
          if (busy) return;
          const body = new FormData(e.currentTarget);
          for (const role of Object.keys(dischargeRoles)) {
            const f = body.get(role);
            if (!(f instanceof File) || !f.name) body.delete(role);
          }
          if (useSample && claim?.sample_bill_available)
            body.set("sample_bill", "true");
          if (
            !useSample &&
            !Object.keys(dischargeRoles).some((k) => body.has(k))
          ) {
            setError("Select at least one source PDF.");
            return;
          }
          if (!body.get("prior_case_id")) body.delete("prior_case_id");
          setBusy(true);
          setError("");
          try {
            const res = await api(
              claim ? claimPath(claim.id) + "/documents" : "/api/discharge",
              {
                method: "POST",
                headers: claim
                  ? { "If-Match": '"' + claim.revision + '"' }
                  : { "Idempotency-Key": operation.current },
                body,
              },
            );
            onSaved(await res.json());
          } catch (err) {
            setError(
              err instanceof Error ? err.message : "The packet was not saved.",
            );
          } finally {
            setBusy(false);
          }
        }}
      >
        {!claim && (
          <fieldset disabled={busy} className="plain-fields">
            <legend>Discharged encounter</legend>
            <div className="input-grid">
              {[
                ["member", "Member reference", "text"],
                ["encounter", "Hospital encounter ID", "text"],
                ["procedure", "Actual procedure", "text"],
                ["insurer", "Insurer", "text"],
                ["facility", "Hospital facility", "text"],
                ["admission_date", "Actual admission date", "date"],
                ["discharge_date", "Actual discharge date", "date"],
              ].map(([key, label, type]) => (
                <label className="stack-field" key={key}>
                  <span>{label}</span>
                  <input name={key} type={type} required />
                </label>
              ))}
              <label className="stack-field">
                <span>Linked pre-arrival case (optional)</span>
                <input name="prior_case_id" defaultValue={prior || ""} />
              </label>
            </div>
          </fieldset>
        )}
        <fieldset disabled={busy} className="plain-fields">
          <legend>Original source PDFs</legend>
          <p className="hint">
            {claim
              ? "Upload one or more corrected exhibits together."
              : "Attach PDFs for the final itemized bill, discharge summary, written payer letter and supporting records. You can start with missing documents."}
          </p>
          {claim?.sample_bill_available && (
            <label className="check-field">
              <input
                type="checkbox"
                checked={useSample}
                onChange={(e) => setUseSample(e.target.checked)}
              />
              Use the corrected bill from this practice case.
            </label>
          )}
          {useSample && claim ? (
            <div className="attachment-preview">
              <div className="attachment-tools">
                <strong>Proposed corrected bill</strong>
                <a
                  href={claimPath(claim.id) + "/sample-bill"}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open original PDF
                </a>
              </div>
              <Suspense fallback={<p>Opening corrected bill…</p>}>
                <PdfPage
                  label="Proposed corrected bill"
                  url={claimPath(claim.id) + "/sample-bill"}
                />
              </Suspense>
            </div>
          ) : (
            Object.entries(dischargeRoles).map(([role, label]) => (
              <label className="upload-field" key={role}>
                <strong>{label} PDF</strong>
                <input name={role} type="file" accept="application/pdf,.pdf" />
              </label>
            ))
          )}
          {!useSample && hosted_ocr_enabled && (
            <label className="check-field">
              <input type="checkbox" name="ocr" value="true" />
              Allow OpenAI to process scanned pages of these exhibits if OCR is
              needed.
            </label>
          )}
          <label className="check-field">
            <input required name="confirmed" type="checkbox" value="true" />I
            verified the files belong to this discharge encounter.
          </label>
        </fieldset>
        {error && (
          <p role="alert" className="error-message">
            {error}
          </p>
        )}
        <div className="actions">
          <button className="primary" disabled={busy}>
            {busy
              ? "Checking exhibits…"
              : claim
                ? "Save corrected packet"
                : "Create discharge claim"}
          </button>
          <button
            type="button"
            className="secondary"
            onClick={onCancel}
            disabled={busy}
          >
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}
export function ClaimMutation({
  claim,
  action,
  pinned = false,
  onSaved,
  onCancel,
}: {
  claim: DischargeClaim;
  pinned?: boolean;
  action: ClaimAction | "approve";
  onSaved: () => void;
  onCancel: () => void;
}) {
  const { actor } = useStaffSession();
  const [outcome, setOutcome] = useState("query"),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const followUp = claim.payer_decision;
  const [draftDigest, setDraftDigest] = useState("");
  const [downloadedText, setDownloadedText] = useState("");
  const [fileOrigin, setFileOrigin] = useState<"external" | "workspace">("external");
  const payerReply = [...claim.events].reverse().find(event => event.kind === "reply");
  const [draft, setDraft] = useState(() => {
    const ref = payerReply?.data.reference || "the latest written decision";
    const request = claim.insurer_status === "query"
      ? "We are responding to your request for additional information."
      : "Please reconsider the written decision for this claim.";
    return `Regarding ${ref}:

${request}

Supporting evidence from claim revision R${claim.revision}: [list only the relevant documents and page numbers].

Please confirm receipt and the date we can expect your written response.`;
  });
  const needsOwner = action === "supplement" || (action === "reply" && ["query", "partial", "declined"].includes(outcome));
  const needsMoney =
    action === "payment" ||
    (action === "reply" && ["partial", "confirmed"].includes(outcome));
  async function downloadDraft() {
    if (busy || !payerReply) return;
    setBusy(true);
    setError("");
    try {
      const res = await api(claimPath(claim.id) + "/follow-up-draft", {
        method: "POST",
        headers: { "Content-Type": "application/json", "If-Match": '"' + claim.revision + '"' },
        body: JSON.stringify({ text: draft, payer_event_id: payerReply.id, workflow_version: claim.workflow_version }),
      });
      const digest = res.headers.get("X-Draft-SHA256");
      if (!digest) throw new Error("The downloaded response is missing its document reference.");
      const url = URL.createObjectURL(await res.blob());
      setDraftDigest(digest);
      setDownloadedText(draft);
      setFileOrigin("workspace");
      const link = document.createElement("a");
      link.href = url;
      link.download = claim.id + "-r" + claim.revision + "-reply-" + payerReply.id + ".pdf";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to download this correspondence.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="form-wrap">
      <div className="page-title">
        <div>
          <p className="section-label">Discharge claim · R{claim.revision}</p>
          <h1>{actionTitles[action]}</h1>
          <p>
            {claim.procedure} · {claim.member}
          </p>
        </div>
      </div>
      <form
        className="panel form-body"
        onSubmit={async (e) => {
          e.preventDefault();
          if (busy) return;
          const body = new FormData(e.currentTarget);
          const name = actor || String(body.get("actor") || "").trim();
          if (!name) return;
          const head = pinned
            ? Math.max(claim.revision, ...claim.history.map((h) => h.revision))
            : claim.revision;
          const headers = new Headers({
            "If-Match": '"' + head + '"',
          });
          if (pinned) body.set("target_revision", String(claim.revision));
          body.set("action", action);
          body.set("workflow_version", String(claim.workflow_version));
          body.set("actor", name);
          if (needsOwner) body.set("assign_follow_up", "true");
          if (action === "supplement" && payerReply) {
            body.set("payer_event_id", String(payerReply.id));
            if (fileOrigin === "workspace" && draftDigest) {
              if (draft !== downloadedText) {
                setError("The draft text changed. Download the edited response before attaching the exact PDF you sent.");
                return;
              }
              body.set("draft_sha256", draftDigest);
            }
          }
          if (action === "approve")
            headers.set("Content-Type", "application/json");
          setBusy(true);
          setError("");
          try {
            await api(
              claimPath(claim.id) +
                (action === "approve" ? "/approve" : "/workflow"),
              {
                method: "POST",
                headers,
                body:
                  action === "approve"
                    ? JSON.stringify({ reviewer: name })
                    : body,
              },
            );
            onSaved();
          } catch (err) {
            setError(
              err instanceof Error
                ? err.message
                : "The record could not be saved.",
            );
          } finally {
            setBusy(false);
          }
        }}
      >
        <fieldset className="plain-fields" disabled={busy}>
          <legend>
            {action === "approve"
              ? "Current revision"
              : action === "payment"
                ? "Hospital settlement record"
                : "Correspondence record"}
          </legend>
          {action === "approve" && (
            <>
              <AttachmentList packet={claim} />
              <label className="check-field">
                <input type="checkbox" required />I reviewed this discharge
                packet and its source pages.
              </label>
            </>
          )}
          {action === "supplement" && <>
            <label className="stack-field"><span>Editable follow-up draft</span>
              <textarea rows={7} maxLength={8000} value={draft} onChange={e => setDraft(e.target.value)} />
            </label>
            <button type="button" className="secondary" disabled={busy || !draft.trim()} onClick={() => void downloadDraft()}>Download edited response PDF</button>
            <p className="hint">Review the original payer decision and send the response through the approved payer channel. Attach the exact PDF you sent to record it here.</p>
          </>}
          {(action === "submission" || action === "supplement") && (
            <>
              <p className="hint">
                {action === "supplement"
                  ? "Record the packet already sent in response to the insurer’s latest written decision."
                  : "Record the claim already sent through the insurer’s usual channel."}
              </p>
              <label className="stack-field">
                <span>Submission channel</span>
                <input required name="channel" />
              </label>
            </>
          )}
          {action !== "approve" && (
            <label className="stack-field">
              <span>
                {action === "payment"
                  ? "Payment reference"
                  : action === "submission" || action === "supplement"
                    ? "Transmission reference"
                    : "Insurer reference"}
              </span>
              <input required name="reference" />
            </label>
          )}
          {action === "reply" && (
            <>
              <label className="stack-field">
                <span>Payer disposition</span>
                <select
                  name="outcome"
                  value={outcome}
                  onChange={(e) => setOutcome(e.target.value)}
                >
                  <option value="query">Query / more information</option>
                  <option value="partial">Partially confirmed</option>
                  <option value="confirmed">Confirmed</option>
                  <option value="declined">Declined</option>
                </select>
              </label>
              <label className="stack-field">
                <span>Written terms and conditions</span>
                <textarea name="terms" rows={3} required />
              </label>
              <label className="upload-field">
                <strong>Written payer reply PDF</strong>
                <input
                  type="file"
                  name="file"
                  accept="application/pdf,.pdf"
                  required
                />
              </label>
              <label className="check-field">
                <input type="checkbox" name="confirmed" value="true" required />
                I verified the reply belongs to this claim and submission.
              </label>
            </>
          )}
          {action === "supplement" && <>
            <label className="stack-field"><span>Source of sent PDF</span>
              <select name="file_origin" value={fileOrigin} onChange={e => setFileOrigin(e.target.value as "external" | "workspace")}>
                <option value="external">Prepared outside ZeroUpfront · staff-verified</option>
                <option value="workspace">Downloaded ZeroUpfront response · verify exact file</option>
              </select>
            </label>
            <label className="upload-field"><strong>Exact PDF sent to insurer</strong>
              <input type="file" name="file" accept="application/pdf,.pdf" required />
            </label>
            <label className="check-field"><input type="checkbox" name="confirmed" value="true" required />
              I verified the packet, recipient and transmission reference for this revision.
            </label>
          </>}
          {needsOwner && <div className="input-grid">
            <label className="stack-field"><span>Follow-up owner</span>
              <input name="owner" required maxLength={120} defaultValue={action === "supplement" ? followUp?.owner || actor || "" : actor || ""} />
            </label>
            <label className="stack-field"><span>Follow-up due</span>
              <input type="date" name="follow_up_date" required defaultValue={action === "supplement" ? followUp?.follow_up_date || "" : ""} />
            </label>
          </div>}
          {needsMoney && (
            <div className="input-grid">
              <label className="stack-field">
                <span>
                  {action === "payment"
                    ? "Amount received"
                    : "Amount in the written reply"}
                </span>
                <input
                  name="amount"
                  type="number"
                  min="0"
                  step="0.01"
                  required
                />
              </label>
              <label className="stack-field">
                <span>Currency code</span>
                <input
                  name="currency"
                  required
                  minLength={3}
                  maxLength={3}
                  pattern="[A-Za-z]{3}"
                />
              </label>
            </div>
          )}
          {action === "payment" && (
            <label className="stack-field">
              <span>Settlement notes</span>
              <textarea name="notes" required rows={2} />
            </label>
          )}
          <label className="stack-field">
            <span>
              {action === "approve" ? "Reviewer name" : "Recorded by"}
            </span>
            <input
              name="actor"
              autoComplete="name"
              defaultValue={actor || ""}
              readOnly={!!actor}
              required
            />
          </label>
        </fieldset>
        {error && (
          <p className="error-message" role="alert">
            {error}{" "}
            <button type="button" className="text-button" onClick={onSaved}>
              Reload claim
            </button>
          </p>
        )}
        <div className="actions">
          <button className="primary" disabled={busy}>
            {busy
              ? "Saving…"
              : action === "approve"
                ? "Mark packet reviewed"
                : "Save record"}
          </button>
          <button
            type="button"
            disabled={busy}
            className="secondary"
            onClick={onCancel}
          >
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}
