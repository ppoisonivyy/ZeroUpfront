import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import {
  ExternalLink,
  FileUp,
  GitCompareArrows,
  ShieldCheck,
} from "lucide-react";
import type { CaseDetail, Charge } from "./api";
import { api, casePath, displayDate, money } from "./api";
import { AttachmentList } from "./Attachments";

const PdfPage = lazy(() => import("./PdfPage"));
type FormProps = {
  packet: CaseDetail;
  onSaved: () => void;
  onCancel: () => void;
  onStale: () => void;
};

function Problem({
  message,
  onStale,
}: {
  message: string;
  onStale: () => void;
}) {
  return (
    message && (
      <div className="error-message" role="alert">
        {message}{" "}
        <button className="text-button" type="button" onClick={onStale}>
          Reload case
        </button>
      </div>
    )
  );
}
function useSave({ packet, onSaved }: FormProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function save(endpoint: string, body: BodyInit, json = false) {
    setBusy(true);
    setError("");
    try {
      const headers = new Headers({ "If-Match": '"' + packet.revision + '"' });
      if (json) headers.set("Content-Type", "application/json");
      await api(casePath(packet.id) + endpoint, {
        method: "POST",
        headers,
        body,
      });
      onSaved();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "The change could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, save };
}
function useLocalPdf(file: File | null) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    if (!file) {
      setUrl("");
      return;
    }
    const next = URL.createObjectURL(file);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [file]);
  return url;
}
type Preview = { lines: Charge[]; total: number };
// Only the bundled, identifiable sample has this known layout. Uploaded PDFs stay unverified.
function readSample(text: string): Preview | null {
  const amountAfter = (label: string) => {
    const match = text.match(
      new RegExp(label + "\\s+THB\\s+([0-9,]+(?:\\.[0-9]+)?)", "i"),
    );
    return match ? Number(match[1].replaceAll(",", "")) : null;
  };
  const hospital = amountAfter("Hospital services"),
    team = amountAfter("Operating team"),
    total = amountAfter("Total estimated charges");
  if (
    hospital === null ||
    team === null ||
    total === null ||
    Math.abs(hospital + team - total) > 0.005
  )
    return null;
  return {
    lines: [
      { label: "Hospital services", amount: hospital },
      { label: "Operating team", amount: team },
    ],
    total,
  };
}
function Compare({
  packet,
  proposed,
}: {
  packet: CaseDetail;
  proposed: Preview;
}) {
  return (
    <div className="comparison">
      <div className="comparison-top">
        <GitCompareArrows size={18} />
        <h3>Estimate comparison</h3>
      </div>
      <table>
        <thead>
          <tr>
            <th scope="col">Charge</th>
            <th scope="col">R{packet.revision}</th>
            <th scope="col">Proposed</th>
          </tr>
        </thead>
        <tbody>
          {[
            ...new Set(
              [...packet.lines, ...proposed.lines].map((line) => line.label),
            ),
          ].map((label) => (
            <tr key={label}>
              <th scope="row">{label}</th>
              <td>
                {packet.lines.some((l) => l.label === label)
                  ? money(packet.lines.find((l) => l.label === label)!.amount)
                  : "Unlisted"}
              </td>
              <td>
                {proposed.lines.some((l) => l.label === label)
                  ? money(proposed.lines.find((l) => l.label === label)!.amount)
                  : "Unlisted"}
              </td>
            </tr>
          ))}
          <tr className="total-row">
            <th scope="row">Total estimate</th>
            <td>{money(packet.total)}</td>
            <td>{money(proposed.total)}</td>
          </tr>
        </tbody>
      </table>
      {packet.total === proposed.total && (
        <p className="comparison-note">Total unchanged.</p>
      )}
    </div>
  );
}
export function ReplaceEstimate(props: FormProps) {
  const { packet, onCancel, onStale } = props;
  const sampleAvailable = packet.id === "Z002";
  const [mode, setMode] = useState<"sample" | "upload">(
    sampleAvailable ? "sample" : "upload",
  );
  const [file, setFile] = useState<File | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [sample, setSample] = useState<Preview | null>(null);
  const sampleText = useCallback(
    (text: string) => setSample(readSample(text)),
    [],
  );
  const { save, busy, error } = useSave(props);
  const localUrl = useLocalPdf(file);
  const pdf =
    mode === "sample" ? casePath(packet.id) + "/sample-estimate" : localUrl;
  const title =
    mode === "sample"
      ? "Bundled revised estimate"
      : file?.name || "Uploaded estimate";
  const canSubmit = !busy && confirmed && (mode === "sample" || !!file);

  return (
    <section aria-labelledby="replace-title">
      <div className="page-title">
        <div>
          <p className="section-label">
            Case {packet.id} · Revision {packet.revision}
          </p>
          <h1 id="replace-title">Replace estimate</h1>
          <p>
            Compare the proposed PDF and confirm the encounter before attaching
            it.
          </p>
        </div>
      </div>
      <div className="workspace-grid">
        <form
          className="panel form-body"
          onSubmit={(event) => {
            event.preventDefault();
            if (!canSubmit) return;
            const data = new FormData();
            data.set("confirmed", "true");
            if (mode === "sample") data.set("sample", "true");
            else if (file) data.set("file", file);
            void save("/estimate", data);
          }}
        >
          <h2>Proposed estimate</h2>
          <fieldset className="option-set" disabled={busy}>
            <legend>Choose a source</legend>
            {sampleAvailable && (
              <label>
                <input
                  type="radio"
                  name="proposal"
                  checked={mode === "sample"}
                  onChange={() => {
                    setMode("sample");
                    setConfirmed(false);
                  }}
                />
                Bundled sample
              </label>
            )}
            <label>
              <input
                type="radio"
                name="proposal"
                checked={mode === "upload"}
                onChange={() => {
                  setMode("upload");
                  setConfirmed(false);
                }}
              />
              Upload demo PDF
            </label>
          </fieldset>
          {mode === "upload" && (
            <div className="field">
              <label htmlFor="file">Upload demo estimate PDF</label>
              <input
                id="file"
                type="file"
                accept="application/pdf,.pdf"
                disabled={busy}
                onChange={(event) => {
                  setFile(event.target.files?.[0] || null);
                  setConfirmed(false);
                }}
              />
              <p className="hint">
                Choose a supported synthetic estimate for this case. Personal
                patient files do not belong in this demo.
              </p>
            </div>
          )}
          {mode === "sample" && sample ? (
            <Compare packet={packet} proposed={sample} />
          ) : (
            <div className="compact-detail">
              <span>Current estimate</span>
              <strong>{money(packet.total)}</strong>
              <p>
                {mode === "sample"
                  ? "Open the proposed PDF to inspect its amounts."
                  : "The case service verifies the uploaded amounts when you attach the PDF."}
              </p>
            </div>
          )}
          <h3>Confirm the encounter</h3>
          <p className="body-copy">
            {packet.member} · {packet.procedure} ·{" "}
            {displayDate(packet.admission_date)}. Check the encounter against
            the case record. A member reference alone can match several
            admissions.
          </p>
          <label className="check-field">
            <input
              type="checkbox"
              checked={confirmed}
              disabled={busy || !pdf}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            I verified this estimate belongs to this encounter.
          </label>
          <Problem message={error} onStale={onStale} />
          <div className="actions">
            <button className="primary" disabled={!canSubmit}>
              <FileUp size={16} />
              {busy ? "Attaching…" : "Use revised estimate"}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={onCancel}
            >
              Cancel
            </button>
          </div>
        </form>
        <section className="panel viewer">
          <div className="panel-heading">
            <h2>Proposed source</h2>
            {pdf && (
              <a
                className="text-action"
                href={pdf + "#page=1"}
                target="_blank"
                rel="noreferrer"
              >
                Open PDF <ExternalLink size={14} />
              </a>
            )}
          </div>
          {pdf ? (
            <>
              <div className="viewer-meta">
                <strong>{title}</strong>
                <span>Page 1</span>
              </div>
              <Suspense fallback={<p className="loading">Loading viewer…</p>}>
                <PdfPage
                  key={pdf}
                  url={pdf}
                  label={title}
                  onText={mode === "sample" ? sampleText : undefined}
                />
              </Suspense>
            </>
          ) : (
            <p className="empty-view">
              Choose a demo PDF to inspect its original page.
            </p>
          )}
        </section>
      </div>
    </section>
  );
}
export function ApproveDraft(props: FormProps) {
  const { packet, onCancel, onStale } = props;
  const [name, setName] = useState("");
  const [checked, setChecked] = useState(false);
  const { save, busy, error } = useSave(props);
  return (
    <section className="form-wrap">
      <div className="page-title">
        <div>
          <p className="section-label">
            Case {packet.id} · Revision {packet.revision}
          </p>
          <h1>Review request draft</h1>
          <p>
            Pre-arrival request for a guarantee of payment from {packet.insurer}
            .
          </p>
        </div>
      </div>
      <form
        className="panel form-body"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim() && checked && !busy)
            void save(
              "/approve",
              JSON.stringify({ reviewer: name.trim() }),
              true,
            );
        }}
      >
        <h2>Draft request details</h2>
        <dl className="summary-list">
          {[
            ["Member reference", packet.member],
            ["Admission", displayDate(packet.admission_date)],
            ["Procedure", packet.procedure],
            ["Estimated charges", money(packet.total)],
            ["Policy edition", packet.policy_edition],
          ].map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
        <AttachmentList packet={packet} />
        <div className="field">
          <label htmlFor="reviewer">Reviewer name</label>
          <input
            id="reviewer"
            autoComplete="name"
            value={name}
            maxLength={100}
            required
            disabled={busy}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <label className="check-field">
          <input
            type="checkbox"
            checked={checked}
            disabled={busy}
            onChange={(e) => setChecked(e.target.checked)}
          />
          I reviewed this revision and its supporting documents.
        </label>
        <Problem message={error} onStale={onStale} />
        <div className="actions">
          <button
            className="primary"
            disabled={busy || !checked || !name.trim()}
          >
            <ShieldCheck size={16} />
            {busy ? "Saving review…" : "Mark draft reviewed"}
          </button>
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={onCancel}
          >
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}
