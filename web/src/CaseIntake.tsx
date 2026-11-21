import { useRef, useState } from "react";
import { FilePlus2, Files, ClipboardList } from "lucide-react";
import { api, type CaseDetail } from "./api";

export const intakeDocuments = [
  [
    "policy",
    "Insurance policy",
    "Include the applicable schedule and wording.",
  ],
  [
    "plan",
    "Treatment plan",
    "Include the member, planned procedure and admission date.",
  ],
  [
    "estimate",
    "Hospital estimate",
    "Use the itemized estimate issued for this encounter.",
  ],
] as const;

export function NewCase() {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const operation = useRef(crypto.randomUUID());
  return (
    <section className="intake form-wrap">
      <div className="page-title">
        <div>
          <p className="section-label">Pre-arrival coordination</p>
          <h1>Create a case</h1>
          <p>Start with the planned encounter and its three source PDFs.</p>
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
          setBusy(true);
          setError("");
          try {
            const created: CaseDetail = await (
              await api("/api/cases", {
                method: "POST",
                body,
                headers: { "Idempotency-Key": operation.current },
              })
            ).json();
            location.hash = "/cases/" + encodeURIComponent(created.id);
          } catch (err) {
            setError(
              err instanceof Error
                ? err.message
                : "Case creation failed. Check the documents and retry.",
            );
          } finally {
            setBusy(false);
          }
        }}
      >
        <fieldset disabled={busy} className="plain-fields">
          <legend>
            <ClipboardList size={18} />
            Planned encounter
          </legend>
          <div className="input-grid">
            {[
              ["member", "Member reference", "text"],
              ["admission_date", "Planned admission date", "date"],
              ["procedure", "Planned procedure", "text"],
              ["insurer", "Insurer", "text"],
              ["policy_edition", "Policy edition", "text"],
            ].map(([name, label, type]) => (
              <label className="stack-field" key={name}>
                <span>{label}</span>
                <input name={name} type={type} required />
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset disabled={busy} className="plain-fields">
          <legend>
            <Files size={18} />
            Source documents
          </legend>
          {intakeDocuments.map(([name, label, hint]) => (
            <label className="upload-field" key={name}>
              <strong>{label} PDF</strong>
              <small>{hint}</small>
              <input
                type="file"
                required
                accept="application/pdf,.pdf"
                name={name}
              />
            </label>
          ))}
          <label className="check-field">
            <input type="checkbox" name="ocr" value="true" />
            Allow OpenAI to process scanned pages of these files if OCR is
            needed.
          </label>
          <label className="check-field">
            <input type="checkbox" name="confirmed" value="true" required />I
            verified that these documents belong to the planned encounter and
            policy.
          </label>
        </fieldset>
        {error && (
          <p className="error-message" role="alert">
            {error}
          </p>
        )}
        <div className="actions">
          <button className="primary" disabled={busy}>
            <FilePlus2 size={17} />
            {busy ? "Checking source documents…" : "Create case"}
          </button>
          <a href="#/cases" className="secondary">
            Back to worklist
          </a>
        </div>
      </form>
    </section>
  );
}
