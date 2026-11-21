import { useState } from "react";
import type { FormEvent } from "react";
import { AlertCircle } from "lucide-react";
import { api, casePath, RequestError } from "./api";
import type { CaseDetail } from "./api";
import { useStaffSession } from "./Auth";

const categories: Record<string, string> = {
  eligibility: "Active cover or member eligibility",
  network: "Hospital network or direct billing",
  consent: "Patient consent or authority to share",
  policy: "Missing policy schedule or rider",
  medical: "Medical information requested by payer",
  timing: "Deadline, urgent route or payer delay",
  billing: "Billing or patient responsibility",
  other: "Other case issue",
};
type Props = { packet: CaseDetail; pinned: boolean; onSaved: () => void; onReload: () => void };

export function OperationalHolds({ packet, pinned, onSaved, onReload }: Props) {
  const { actor } = useStaffSession();
  const holds = packet.open_holds ?? [];
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const [stale, setStale] = useState(false);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (editing === null || busy) return;
    const fields = new FormData(event.currentTarget);
    fields.set("workflow_version", String(packet.workflow_version ?? 0));
    fields.set("action", editing === "new" ? "hold" : "resolve_hold");
    if (typeof editing === "number") fields.set("hold_id", String(editing));
    if (actor) fields.set("actor", actor);
    setBusy(true); setProblem(""); setStale(false);
    try {
      await api(casePath(packet.id) + "/workflow", {
        method: "POST", headers: { "If-Match": '"' + packet.revision + '"' }, body: fields,
      });
      setEditing(null); onSaved();
    } catch (error) {
      setStale(error instanceof RequestError && [409, 412].includes(error.status));
      setProblem(error instanceof Error ? error.message : "Could not save the hold.");
    } finally { setBusy(false); }
  }
  function edit(value: typeof editing) { setEditing(value); setProblem(""); setStale(false); }
  if (pinned && !holds.length) return null;
  return <section className="panel workflow" aria-label="Case holds">
    <div className="panel-heading"><h2><AlertCircle size={18}/>Case holds</h2>
      {!pinned && editing === null && <button className="text-action" onClick={() => edit("new")}>Add a hold</button>}
    </div>
    <div className="form-body">
      {holds.length === 0 && editing === null && <p className="hint">No holds recorded. Add one if the payer or hospital needs to confirm something before release.</p>}
      {holds.map(hold => <div className="finding" key={hold.id}>
        <h3>{categories[hold.category] || hold.category}</h3><p>{hold.note}</p>
        <p className="hint">Opened by {hold.actor} on revision {hold.revision}</p>
        {!pinned && editing === null && <button className="text-action" onClick={() => edit(hold.id)}>Resolve hold</button>}
      </div>)}
      {editing !== null && !pinned && <form className="event-form" onSubmit={save} key={editing}>
        {editing === "new" && <label className="stack-field">Reason for hold<select name="category" required>
          {Object.entries(categories).map(([key, name]) => <option key={key} value={key}>{name}</option>)}
        </select></label>}
        <label className="stack-field">{editing === "new" ? "What needs confirmation, and who will follow up?" : "What resolved this issue? Include the source or reference."}
          <textarea name="notes" required rows={2} maxLength={2000}/></label>
        {!actor && <label className="stack-field">Recorded by<input name="actor" required maxLength={100}/></label>}
        {problem && <p className="error-message" role="alert">{problem} {stale && <button type="button" className="text-action" onClick={onReload}>Reload case</button>}</p>}
        <div className="actions"><button className="primary" disabled={busy}>{editing === "new" ? "Save hold" : "Record resolution"}</button>
          <button type="button" className="secondary" disabled={busy} onClick={() => edit(null)}>Cancel</button></div>
      </form>}
    </div>
  </section>;
}
