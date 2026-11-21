import { useState } from "react";
import { BookOpenCheck, Plus, Trash2 } from "lucide-react";
import { useStaffSession } from "./Auth";
import { AttachmentList } from "./Attachments";
import {
  api,
  casePath,
  money,
  type CaseDetail,
  type Citation,
  type EvidenceCheck,
} from "./api";

const fieldDefinitions = [
  ["member", "Member reference", "plan"],
  ["admission_date", "Admission date", "plan"],
  ["procedure", "Planned procedure", "plan"],
  ["estimated_total_thb", "Estimated total (THB)", "estimate"],
] as const;
const citation = (role: string): Citation => ({ role, page: 1, quote: "" });
const newCheck = (): EvidenceCheck => ({
  requirement: "",
  result: "unclear",
  policy: citation("policy"),
  support: citation("plan"),
});
function CitationInput({
  value,
  roles,
  onChange,
  packet,
  required = false,
  label,
}: {
  value: Citation;
  roles: string[];
  onChange: (v: Citation) => void;
  packet: CaseDetail;
  required?: boolean;
  label: string;
}) {
  const known = packet.sources.find((s) => s.role === value.role);
  return (
    <fieldset className="cite-input">
      <legend>{label}</legend>
      <div className="input-grid">
        <label className="stack-field">
          <span>Source</span>
          <select
            value={value.role}
            onChange={(e) => onChange(citation(e.target.value))}
          >
            {roles.map((role) => (
              <option key={role} value={role}>
                {packet.sources.find((s) => s.role === role)?.label || role}
              </option>
            ))}
          </select>
        </label>
        <label className="stack-field">
          <span>Page</span>
          <input
            type="number"
            min="1"
            step="1"
            required={required || !!value.quote}
            value={value.page || ""}
            onChange={(e) =>
              onChange({ ...value, page: Number(e.target.value) })
            }
          />
        </label>
      </div>
      <label className="stack-field">
        <span>Exact source quote</span>
        <textarea
          rows={2}
          required={required}
          value={value.quote}
          onChange={(e) => onChange({ ...value, quote: e.target.value })}
        />
      </label>
      {(known?.anchors?.length ?? 0) > 0 && (
        <label className="stack-field">
          <span>Use a verified excerpt</span>
          <select
            value=""
            onChange={(e) => {
              if (e.target.value !== "") {
                const a = known!.anchors![Number(e.target.value)];
                onChange({ ...value, page: a.page, quote: a.quote });
              }
            }}
          >
            <option value="">Choose an excerpt…</option>
            {known!.anchors!.map((a, i) => (
              <option key={i} value={i}>
                p. {a.page} · {a.quote}
              </option>
            ))}
          </select>
        </label>
      )}
    </fieldset>
  );
}
export function EvidenceReview({
  packet,
  onBack,
  onSaved,
  onReload,
}: {
  packet: CaseDetail;
  onBack: () => void;
  onSaved: () => void;
  onReload: () => void;
}) {
  const session = useStaffSession();
  const [fields, setFields] = useState<Record<string, Citation>>(
    packet.manual_review?.fields || {},
  );
  const [checks, setChecks] = useState<EvidenceCheck[]>(
    packet.manual_review?.checks || [],
  );
  const [actor, setActor] = useState(session.actor || ""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const changeCheck = (i: number, change: Partial<EvidenceCheck>) =>
    setChecks((all) => all.map((c, n) => (n === i ? { ...c, ...change } : c)));
  return (
    <>
      <div className="page-title">
        <div>
          <p className="section-label">
            Case {packet.id} · R{packet.revision}
          </p>
          <h1>Review policy evidence</h1>
          <p>
            Verify case facts and payer requirements against the original pages.
          </p>
        </div>
      </div>
      <div className="workspace-grid">
        <form
          className="panel form-body"
          onSubmit={async (e) => {
            e.preventDefault();
            if (busy) return;
            setBusy(true);
            setError("");
            try {
              const chosen = Object.fromEntries(
                Object.entries(fields).filter(([, f]) => f.quote.trim()),
              );
              await api(casePath(packet.id) + "/evidence", {
                method: "POST",
                headers: {
                  "Content-Type": "application/json",
                  "If-Match": '"' + packet.revision + '"',
                },
                body: JSON.stringify({
                  fields: chosen,
                  checks,
                  actor: session.actor || actor.trim(),
                }),
              });
              onSaved();
            } catch (err) {
              setError(
                err instanceof Error
                  ? err.message
                  : "Evidence could not be verified.",
              );
            } finally {
              setBusy(false);
            }
          }}
        >
          <fieldset className="plain-fields" disabled={busy}>
            <legend>Case facts</legend>
            <p className="hint">
              Record the exact source wording for each fact you can verify.
            </p>
            {fieldDefinitions.map(([field, label, role]) => (
              <details className="evidence-field" key={field}>
                <summary>
                  {label}{" "}
                  <span>
                    {fields[field]?.quote
                      ? "Citation added"
                      : field === "estimated_total_thb"
                        ? money(packet.total)
                        : packet[field]}
                  </span>
                </summary>
                <CitationInput
                  packet={packet}
                  roles={[role]}
                  label={label + " citation"}
                  value={fields[field] || citation(role)}
                  onChange={(v) =>
                    setFields((prev) => ({ ...prev, [field]: v }))
                  }
                />
              </details>
            ))}
          </fieldset>
          <fieldset className="plain-fields" disabled={busy}>
            <legend>Policy requirements</legend>
            {checks.map((check, i) => (
              <div className="manual-check" key={i}>
                <div className="subhead">
                  <h3>Requirement {i + 1}</h3>
                  <button
                    type="button"
                    className="text-action"
                    onClick={() =>
                      setChecks((prev) => prev.filter((_, j) => j !== i))
                    }
                  >
                    <Trash2 size={14} />
                    Remove
                  </button>
                </div>
                <label className="stack-field">
                  <span>Requirement</span>
                  <input
                    required
                    value={check.requirement}
                    onChange={(e) =>
                      changeCheck(i, { requirement: e.target.value })
                    }
                  />
                </label>
                <label className="stack-field">
                  <span>Assessment</span>
                  <select
                    value={check.result}
                    onChange={(e) => changeCheck(i, { result: e.target.value })}
                  >
                    <option value="met">Met</option>
                    <option value="missing">Missing</option>
                    <option value="unclear">Unclear</option>
                    <option value="possible_exclusion">
                      Possible exclusion
                    </option>
                  </select>
                </label>
                <CitationInput
                  packet={packet}
                  required
                  value={check.policy}
                  roles={["policy"]}
                  label="Policy wording"
                  onChange={(v) => changeCheck(i, { policy: v })}
                />
                <CitationInput
                  packet={packet}
                  required
                  value={check.support}
                  roles={["plan", "estimate"]}
                  label="Supporting evidence"
                  onChange={(v) => changeCheck(i, { support: v })}
                />
              </div>
            ))}
            <button
              type="button"
              className="secondary"
              onClick={() => setChecks((prev) => [...prev, newCheck()])}
            >
              <Plus size={15} />
              Add requirement
            </button>
          </fieldset>
          <label className="stack-field">
            <span>Reviewer name</span>
            <input
              required
              value={actor}
              readOnly={!!session.actor}
              onChange={(e) => setActor(e.target.value)}
            />
          </label>
          {error && (
            <p className="error-message" role="alert">
              {error}{" "}
              <button className="text-button" type="button" onClick={onReload}>
                Reload case
              </button>
            </p>
          )}
          <div className="actions">
            <button
              className="primary"
              disabled={
                busy ||
                (!checks.length &&
                  !Object.values(fields).some((f) => f.quote.trim()))
              }
            >
              <BookOpenCheck size={16} />
              {busy ? "Verifying citations…" : "Save evidence review"}
            </button>
            <button
              className="secondary"
              type="button"
              disabled={busy}
              onClick={onBack}
            >
              Cancel
            </button>
          </div>
        </form>
        <aside className="panel form-body">
          <h2>Original source pages</h2>
          <AttachmentList packet={packet} />
        </aside>
      </div>
    </>
  );
}
