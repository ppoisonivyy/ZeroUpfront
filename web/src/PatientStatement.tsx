import { useState } from "react";
import { api } from "./api";
import { useStaffSession } from "./Auth";
import { claimPath, minorMoney, type DischargeClaim, type PatientStatementFacts } from "./dischargeApi";

const dispositions: Record<string, [string, string]> = {
  not_sent: ["Awaiting submission", "รอส่งคำขอ"],
  submitted: ["Awaiting written decision", "รอผลการพิจารณาเป็นลายลักษณ์อักษร"],
  query: ["Insurer requested more information", "บริษัทประกันขอข้อมูลเพิ่มเติม"],
  partial: ["Insurer approved part of the claim", "บริษัทประกันอนุมัติบางส่วน"],
  confirmed: ["Insurer confirmed the claim", "บริษัทประกันยืนยันการอนุมัติ"],
  declined: ["Insurer declined the claim", "บริษัทประกันปฏิเสธการอนุมัติ"],
  supplement_sent: ["Query answered, awaiting insurer", "ส่งข้อมูลเพิ่มเติมแล้ว รอคำตอบจากบริษัทประกัน"],
  appeal_sent: ["Appeal sent, awaiting insurer", "ยื่นอุทธรณ์แล้ว รอคำตอบจากบริษัทประกัน"],
};
type Row = { en: string; th: string; value: string; thaiValue?: string };
function rowsFor(facts: PatientStatementFacts): Row[] {
  const status = dispositions[facts.insurer_status];
  const pending = "Awaiting verification";
  const thaiPending = "รอตรวจสอบ";
  const amount = (en: string, th: string, n: number | null, currency: string | null): Row =>
    n == null || !currency ? { en, th, value: pending, thaiValue: thaiPending } : { en, th, value: minorMoney(n, currency) };
  const rows = [
    { en: "Hospital", th: "โรงพยาบาล", value: facts.hospital },
    { en: "Case reference", th: "เลขอ้างอิงเคส", value: facts.case_id },
    { en: "Packet revision", th: "ฉบับที่ของเอกสาร", value: String(facts.revision) },
    { en: "Status with insurer", th: "สถานะการประสานงานกับบริษัทประกัน", value: status?.[0] || pending, thaiValue: status?.[1] || thaiPending },
    amount("Approved by insurer", "ยอดที่บริษัทประกันอนุมัติ", facts.approved_minor, facts.approved_currency),
    amount("Patient share stated in the packet", "ส่วนที่ระบุให้ผู้ป่วยรับผิดชอบตามเอกสาร", facts.patient_share_minor, facts.currency),
  ];
  if (facts.patient_fx_minor !== null) rows.push(amount("Your FX charge", "ค่าใช้จ่ายจากอัตราแลกเปลี่ยนที่ผู้ป่วยรับผิดชอบ", facts.patient_fx_minor, "THB"));
  if (facts.insurer_outstanding_minor !== null) rows.push(amount("Still owed by the insurer to the hospital", "ยอดที่บริษัทประกันยังค้างชำระโรงพยาบาล", facts.insurer_outstanding_minor, "THB"));
  rows.push({ en: "Deposit paid", th: "เงินมัดจำที่ชำระแล้ว", value: pending, thaiValue: thaiPending },
    { en: "Disputed or pending charges", th: "ค่าใช้จ่ายที่โต้แย้งหรือรอการยืนยัน", value: pending, thaiValue: thaiPending });
  return rows;
}

function downloadCopy(rows: Row[], reviewed: PatientStatementFacts) {
  const copy = [
    "Patient financial update", ...rows.map(r => r.en + ": " + r.value),
    "", "สรุปสถานะค่าใช้จ่ายสำหรับผู้ป่วย", ...rows.map(r => r.th + ": " + (r.thaiValue || r.value)),
  ];
  const url = URL.createObjectURL(new Blob(["\uFEFF" + copy.join("\n") + "\n"], { type: "text/plain;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  const safePart = (value: string) => value.replace(/[^\p{L}\p{N}_-]+/gu, "-").slice(0, 80);
  a.download = `financial-update-${safePart(reviewed.hospital)}-${safePart(reviewed.case_id)}-r${reviewed.revision}.txt`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function PatientStatement({ claim, facts, onUpdated, reload }: {
  claim: DischargeClaim; facts: PatientStatementFacts; onUpdated: (c: DischargeClaim) => void; reload: () => void;
}) {
  const { actor } = useStaffSession();
  const [editing, setEditing] = useState(false);
  const [thai, setThai] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const reviewed = claim.reviewed_patient_statement;
  const rows = rowsFor(reviewed && !editing ? reviewed : facts);
  if (reviewed && !editing) {
    rows.push({ en: "Hospital billing contact", th: "ช่องทางติดต่อฝ่ายการเงินของโรงพยาบาล", value: reviewed.contact },
      { en: "Next update", th: "วันที่แจ้งความคืบหน้าครั้งถัดไป", value: reviewed.next_update },
      { en: "Review time", th: "วันและเวลาที่ตรวจสอบ", value: reviewed.reviewed_at });
  }
  return <section className="panel workflow">
    <div className="panel-heading"><h2>Patient financial update</h2></div>
    <div className="review-body">
      {!editing && !reviewed ? <>
        <p>Review the amounts, add a billing contact and set the next update before preparing a Thai and English copy.</p>
        <button type="button" className="secondary" onClick={() => setEditing(true)}>Review patient update</button>
      </> : <>
        <p>{reviewed && !editing ? "Reviewed by " + reviewed.reviewer + " · R" + claim.revision : "Draft for staff review · R" + claim.revision}</p>
        <div className="actions" aria-label="Preview language">
          <button type="button" aria-pressed={!thai} className="secondary" onClick={() => setThai(false)}>English</button>
          <button type="button" aria-pressed={thai} className="secondary" lang="th" onClick={() => setThai(true)}>ไทย</button>
        </div>
        <dl className="settlement-summary" lang={thai ? "th" : "en"}>{rows.map(row =>
          <div key={row.en}><dt>{thai ? row.th : row.en}</dt><dd>{thai ? row.thaiValue || row.value : row.value}</dd></div>
        )}</dl>
        {reviewed && !editing ? <div className="actions">
          <button type="button" className="primary" disabled={busy} onClick={async () => {
            setBusy(true);
            setError("");
            try {
              const response = await api(claimPath(claim.id));
              const current: DischargeClaim = await response.json();
              if (current.revision !== claim.revision || current.workflow_version !== claim.workflow_version || !current.reviewed_patient_statement) {
                setError("The case changed. Reload and review the current financial update before downloading.");
                return;
              }
              downloadCopy(rows, reviewed);
            } catch (err) {
              setError(err instanceof Error ? err.message : "Unable to verify the current update.");
            } finally {
              setBusy(false);
            }
          }}>Download reviewed bilingual copy</button>
          <button type="button" className="secondary" onClick={() => setEditing(true)}>Update contact or date</button>
        </div> : <form onSubmit={async e => {
          e.preventDefault();
          if (busy) return;
          const body = new FormData(e.currentTarget);
          body.set("action", "patient_statement");
          body.set("workflow_version", String(claim.workflow_version));
          setBusy(true);
          setError("");
          try {
            const res = await api(claimPath(claim.id) + "/workflow", {
              method: "POST", headers: { "If-Match": '"' + claim.revision + '"' }, body,
            });
            onUpdated(await res.json());
          } catch (err) {
            setError(err instanceof Error ? err.message : "Unable to save the review.");
          } finally {
            setBusy(false);
          }
        }}>
          <fieldset className="plain-fields" disabled={busy}>
            <label className="stack-field"><span>Public hospital billing contact for the patient</span>
              <input name="contact" maxLength={120} required defaultValue={reviewed ? reviewed.contact : ""} />
            </label>
            <label className="stack-field"><span>Next update for the patient</span>
              <input type="date" name="next_update" required defaultValue={reviewed ? reviewed.next_update : ""} />
            </label>
            <label className="stack-field"><span>Reviewed by</span>
              <input name="actor" required defaultValue={actor || ""} readOnly={!!actor} />
            </label>
            <label className="check-field"><input type="checkbox" name="confirmed" value="true" required />
              I checked the amounts against the current documents and reviewed the contact and date for the patient.
            </label>
          </fieldset>
          <div className="actions"><button className="primary" disabled={busy}>Save reviewed update</button>
            <button type="button" className="secondary" disabled={busy} onClick={() => setEditing(false)}>Cancel</button>
          </div>
        </form>}
      </>}
      {error && <p role="alert" className="error-message">{error} <button type="button" className="text-action" onClick={reload}>Reload claim</button></p>}
    </div>
  </section>;
}
