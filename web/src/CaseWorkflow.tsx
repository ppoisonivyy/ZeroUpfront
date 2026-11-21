import { lazy, Suspense, useState } from "react";
import {
  CalendarCheck,
  ChevronDown,
  ExternalLink,
  FileText,
  History,
  Inbox,
  Send,
  Wallet,
} from "lucide-react";
import { useStaffSession } from "./Auth";
import {
  api,
  casePath,
  displayDate,
  sameOriginSource,
  type CaseDetail,
  type WorkflowAction,
  type WorkflowEvent,
} from "./api";

const PdfPage = lazy(() => import("./PdfPage"));
const actions: Record<WorkflowAction, string> = {
  submission: "Record submission",
  reply: "Record insurer reply",
  supplement: "Record supplement sent",
  admission: "Compare admission",
  deposit: "Record deposit decision",
};
const eventNames: Record<string, string> = {
  submission: "Request submitted",
  reply: "Insurer replied",
  supplement: "Supplement sent",
  admission: "Admission compared",
  deposit: "Deposit decision recorded",
  hold: "Operational hold raised",
  resolve_hold: "Operational hold resolved",
  payment: "Payment recorded",
};
const payerStatuses: Record<string, string> = {
  not_sent: "Awaiting submission",
  submitted: "Awaiting insurer reply",
  query: "Insurer requested information",
  partial: "Partial guarantee",
  denied: "Insurer declined",
  authorized: "Treatment authorized",
  guaranteed: "Written guarantee",
  supplement_sent: "Supplement sent",
};
export const payerStatus = (s: string) =>
  payerStatuses[s] || s.replaceAll("_", " ");
const eventLabels: Record<string, string> = {
  reference: "Reference",
  channel: "Submission channel",
  terms: "Letter terms",
  outcome: "Recorded outcome",
  amount: "Amount",
  currency: "Currency",
  actual_member: "Admitted member",
  actual_procedure: "Admitted procedure",
  actual_admission_date: "Actual admission date",
  notes: "Staff notes",
  match: "Encounter match",
  mismatches: "Mismatches",
  comparison: "Comparison",
};
function readable(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.map(readable).join(", ");
  if (typeof value === "object")
    return Object.entries(value)
      .map(
        ([k, v]) =>
          (eventLabels[k] || k.replaceAll("_", " ")) + ": " + readable(v),
      )
      .join(" · ");
  return String(value);
}
export function RecordedEvent({
  event,
  index,
}: {
  event: Omit<WorkflowEvent, "kind"> & { kind: string };
  index: number;
}) {
  const [open, setOpen] = useState(false);
  let url = "";
  try {
    if (event.source_url) url = sameOriginSource(event.source_url);
  } catch {
    /* Keep details if the stored link cannot be previewed. */
  }
  const instant = new Date(event.created_at);
  const when = Number.isNaN(instant.getTime())
    ? event.created_at
    : new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(instant);
  return (
    <li className="event-item">
      <div className="timeline-marker" aria-hidden="true" />
      <div className="event-content">
        <div className="event-top">
          <h3>{eventNames[event.kind] || event.kind}</h3>
          <time dateTime={event.created_at}>{when}</time>
        </div>
        <p className="event-actor">{event.actor}</p>
        <dl className="event-data">
          {Object.entries(event.data || {})
            .filter(
              ([, value]) =>
                value !== null && value !== "" && value !== undefined,
            )
            .map(([k, v]) => (
              <div key={k}>
                <dt>{eventLabels[k] || k.replaceAll("_", " ")}</dt>
                <dd>
                  {k === "outcome"
                    ? readable(v).replaceAll("_", " ")
                    : readable(v)}
                </dd>
              </div>
            ))}
        </dl>
        {url && (
          <div className="event-doc">
            <button
              type="button"
              className="text-action"
              aria-expanded={open}
              aria-controls={"event-pdf-" + index}
              onClick={() => setOpen(!open)}
            >
              <FileText size={16} />
              {event.filename || "Attached PDF"}
              <ChevronDown size={15} />
            </button>
            <div id={"event-pdf-" + index} hidden={!open}>
              {open && (
                <>
                  <a
                    href={url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-action"
                  >
                    Open original PDF <ExternalLink size={14} />
                  </a>
                  <Suspense fallback={<p>Opening file…</p>}>
                    <PdfPage
                      url={url}
                      label={event.filename || "Insurer correspondence"}
                    />
                  </Suspense>
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </li>
  );
}
function TextInput({
  label,
  name,
  type = "text",
  required = true,
}: {
  label: string;
  name: string;
  type?: string;
  required?: boolean;
}) {
  return (
    <label className="stack-field">
      <span>{label}</span>
      <input
        type={type}
        name={name}
        required={required}
        min={type === "number" ? 0 : undefined}
        step={type === "number" ? "0.01" : undefined}
      />
    </label>
  );
}
function Notes({
  label,
  name = "notes",
  required = true,
}: {
  label: string;
  name?: string;
  required?: boolean;
}) {
  return (
    <label className="stack-field">
      <span>{label}</span>
      <textarea rows={3} name={name} required={required} />
    </label>
  );
}
function EventForm({
  action,
  packet,
  pinned,
  onCancel,
  onSaved,
  onReload,
}: {
  action: WorkflowAction;
  packet: CaseDetail;
  pinned: boolean;
  onCancel: () => void;
  onSaved: () => void;
  onReload: () => void;
}) {
  const session = useStaffSession();
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [outcome, setOutcome] = useState(
    action === "reply" ? "query" : action === "deposit" ? "required" : "",
  );
  const needsAmount =
    (action === "reply" && ["partial", "guaranteed"].includes(outcome)) ||
    (action === "deposit" && ["required", "reduced"].includes(outcome));
  const showMoney =
    needsAmount || (action === "reply" && outcome === "authorized");
  return (
    <form
      className="event-form"
      onSubmit={async (e) => {
        e.preventDefault();
        if (busy) return;
        const body = new FormData(e.currentTarget);
        body.set("action", action);
        body.set("workflow_version", String(packet.workflow_version ?? 0));
        if (session.actor) body.set("actor", session.actor);
        for (const key of ["amount", "currency"])
          if (!body.get(key)) body.delete(key);
        if (pinned) body.set("target_revision", String(packet.revision));
        const head = Math.max(
          packet.revision,
          ...packet.history.map((h) => h.revision),
        );
        setBusy(true);
        setError("");
        try {
          await api(casePath(packet.id) + "/workflow", {
            method: "POST",
            headers: {
              "If-Match": '"' + (pinned ? head : packet.revision) + '"',
            },
            body,
          });
          onSaved();
        } catch (err) {
          setError(
            err instanceof Error
              ? err.message
              : "This event could not be recorded.",
          );
        } finally {
          setBusy(false);
        }
      }}
    >
      <fieldset className="plain-fields" disabled={busy}>
        <legend>{actions[action]}</legend>
        {action === "submission" && (
          <>
            <p className="hint">
              Record the request your team already sent to the insurer through
              its usual channel.
            </p>
            <div className="input-grid">
              <TextInput label="Submission reference" name="reference" />
              <TextInput label="Submission channel" name="channel" />
            </div>
          </>
        )}
        {action === "reply" && (
          <>
            <div className="input-grid">
              <label className="stack-field">
                <span>Insurer disposition</span>
                <select
                  name="outcome"
                  value={outcome}
                  onChange={(e) => setOutcome(e.target.value)}
                >
                  {Object.entries({
                    query: "Query / more information",
                    partial: "Partial guarantee",
                    denied: "Declined",
                    authorized: "Treatment authorized",
                    guaranteed: "Written guarantee",
                  }).map(([v, l]) => (
                    <option key={v} value={v}>
                      {l}
                    </option>
                  ))}
                </select>
              </label>
              <TextInput label="Insurer reference" name="reference" />
            </div>
            <Notes label="Terms from the insurer letter" name="terms" />
            <details className="letter-terms">
              <summary>Structured letter terms</summary>
              <p className="hint">
                Enter only terms stated by the insurer. Leave others blank.
              </p>
              <div className="input-grid">
                <TextInput
                  label="Covered member reference"
                  name="covered_member"
                  required={false}
                />
                <TextInput
                  label="Covered procedure"
                  name="covered_procedure"
                  required={false}
                />
                <TextInput
                  label="Covered facility"
                  name="facility"
                  required={false}
                />
                <TextInput
                  label="Valid from"
                  name="valid_from"
                  type="date"
                  required={false}
                />
                <TextInput
                  label="Valid until"
                  name="valid_until"
                  type="date"
                  required={false}
                />
              </div>
              <TextInput
                label="Patient share as written"
                name="patient_share"
                required={false}
              />
            </details>
            <label className="upload-field">
              <strong>Insurer letter PDF</strong>
              <input
                type="file"
                accept="application/pdf,.pdf"
                name="file"
                required
              />
            </label>
          </>
        )}
        {action === "supplement" && (
          <>
            <TextInput
              label="Supplement transmission reference"
              name="reference"
            />
            <Notes label="Information sent to the insurer" />
            <label className="upload-field">
              <strong>Supplementary document PDF</strong>
              <input
                type="file"
                accept="application/pdf,.pdf"
                name="file"
                required
              />
            </label>
          </>
        )}
        {action === "admission" && (
          <>
            <div className="finding neutral">
              <h3>Planned encounter</h3>
              <p>
                {packet.member} · {packet.procedure} ·{" "}
                {displayDate(packet.admission_date)}
              </p>
            </div>
            <div className="input-grid">
              <TextInput
                label="Admitted member reference"
                name="actual_member"
              />
              <TextInput
                label="Actual admission date"
                name="actual_admission_date"
                type="date"
              />
              <TextInput label="Admitted procedure" name="actual_procedure" />
              <TextInput
                label="Actual facility"
                name="actual_facility"
                required={false}
              />
              <TextInput
                label="Actual estimated charges"
                name="actual_amount"
                type="number"
                required={false}
              />
              <TextInput
                label="Actual currency code"
                name="currency"
                required={false}
              />
            </div>
            <Notes label="Admission checks and letter terms" />
            <label className="check-field">
              <input type="checkbox" name="letter_confirmed" value="true" />I
              checked the actual encounter against the attached insurer letter
              and its conditions.
            </label>
          </>
        )}
        {action === "deposit" && (
          <>
            <p className="hint">
              Record the hospital’s decision after checking the admitted
              encounter and the payer’s written terms.
            </p>
            <label className="stack-field">
              <span>Hospital decision</span>
              <select
                name="outcome"
                value={outcome}
                onChange={(e) => setOutcome(e.target.value)}
              >
                {Object.entries({
                  required: "Deposit required",
                  reduced: "Reduced deposit",
                  waived: "Deposit waived",
                  deferred: "Decision deferred",
                }).map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            <Notes label="Hospital rationale" />
          </>
        )}
        {showMoney && (
          <div className="input-grid">
            <TextInput
              label={
                action === "deposit" ? "Deposit amount" : "Amount in the letter"
              }
              type="number"
              name="amount"
              required={needsAmount}
            />
            <label className="stack-field">
              <span>Currency code</span>
              <input
                name="currency"
                required={needsAmount}
                pattern="[a-zA-Z]{3}"
                minLength={3}
                maxLength={3}
                placeholder="e.g. THB"
              />
            </label>
          </div>
        )}
        {(action === "reply" || action === "supplement") && (
          <label className="check-field">
            <input type="checkbox" name="confirmed" value="true" required />I
            verified that this document belongs to this encounter and
            submission.
          </label>
        )}
        <label className="stack-field">
          <span>Recorded by</span>
          <input
            name="actor"
            autoComplete="name"
            required
            readOnly={!!session.actor}
            defaultValue={session.actor || ""}
          />
        </label>
      </fieldset>
      {error && (
        <p className="error-message" role="alert">
          {error}{" "}
          <button type="button" className="text-button" onClick={onReload}>
            Reload case
          </button>
        </p>
      )}
      <div className="actions">
        <button className="primary" disabled={busy}>
          {busy ? "Saving…" : "Save record"}
        </button>
        <button
          className="secondary"
          type="button"
          disabled={busy}
          onClick={onCancel}
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
export function CaseWorkflow({
  packet,
  pinned,
  onSaved,
  onReload,
}: {
  packet: CaseDetail;
  pinned: boolean;
  onSaved: () => void;
  onReload: () => void;
}) {
  const [action, setAction] = useState<WorkflowAction | null>(null);
  const list = packet.events || [];
  const superseded = packet.history.some((h) => h.revision > packet.revision);
  const allowed = (packet.allowed_actions || [])
    .filter((a): a is WorkflowAction => Object.hasOwn(actions, a))
    .filter((a) => !pinned || (superseded && a === "reply"));
  const icons = {
    submission: Send,
    reply: Inbox,
    supplement: Send,
    admission: CalendarCheck,
    deposit: Wallet,
  };
  return (
    <section className="panel workflow" id="case-timeline">
      <div className="panel-heading">
        <h2>
          <History size={18} />
          Case timeline
        </h2>
        <span className="stage-label">
          {payerStatus(packet.insurer_status)}
        </span>
      </div>
      <div className="review-body">
        {packet.admission_check && (
          <div
            className={
              "admission-result finding " +
              (packet.admission_check.outcome === "matched" ? "pass" : "gap")
            }
          >
            <h3>
              {{
                matched: "Admission consistent with recorded terms",
                mismatch: "Admission discrepancy",
                needs_review: "Admission needs review",
                no_guarantee: "No applicable guarantee",
                partial_scope:
                  "Partial guarantee applies to the recorded scope",
              }[packet.admission_check.outcome] || "Admission comparison"}
            </h3>
            {[
              ...(packet.admission_check.differences || []),
              ...(packet.admission_check.uncertainties || []),
            ].map((d, i) => (
              <p key={i}>{d.replaceAll("_", " ")}</p>
            ))}
            {packet.deposit_decision && (
              <p>
                Hospital deposit decision · {packet.deposit_decision.outcome}
                {packet.deposit_decision.amount
                  ? " · " +
                    packet.deposit_decision.currency +
                    " " +
                    packet.deposit_decision.amount
                  : ""}
              </p>
            )}
          </div>
        )}
        {list.length ? (
          <ol className="timeline-list">
            {list.map((ev, i) => (
              <RecordedEvent key={ev.id} event={ev} index={i} />
            ))}
          </ol>
        ) : (
          <p className="body-copy">
            {packet.status === "staff_reviewed"
              ? "Staff review is complete. Record submission once your team sends the request."
              : "The timeline starts with a staff-reviewed request and a recorded submission."}
          </p>
        )}
        {pinned && allowed.length > 0 && (
          <p className="hint">
            Record a late insurer reply here only if it names this previously
            submitted revision.
          </p>
        )}
        {!action && allowed.length > 0 && (
          <div className="actions">
            {allowed.map((a, i) => {
              const Icon = icons[a];
              return (
                <button
                  className={i === 0 ? "primary" : "secondary"}
                  key={a}
                  onClick={() => setAction(a)}
                >
                  <Icon size={16} />
                  {actions[a]}
                </button>
              );
            })}
          </div>
        )}
        {action && allowed.includes(action) && (
          <EventForm
            key={action}
            action={action}
            packet={packet}
            pinned={pinned}
            onCancel={() => setAction(null)}
            onSaved={() => {
              setAction(null);
              onSaved();
            }}
            onReload={onReload}
          />
        )}
      </div>
    </section>
  );
}
