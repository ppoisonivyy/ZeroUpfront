import { useState, type FormEvent } from "react";
import { FileText, MessageSquare } from "lucide-react";
import type { Source } from "./api";

export type CitedQuestion = {
  sequence: number; source_role: string; page: number; question: string;
  asked_at: string; reply: string | null; replied_at: string | null;
};

export function handoffTime(value: string | null) {
  if (!value) return "Time unknown";
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Bangkok",
  }).format(new Date(value)) + " ICT";
}

type Props = {
  questions: CitedQuestion[]; sources: Source[]; revision: number; insurer: boolean; busy: boolean;
  inspect: (source: Source, trigger: HTMLButtonElement) => void;
  send: (suffix: string, payload: Record<string, unknown>) => Promise<boolean>;
};

export function PreclaimQuestions({ questions, sources, revision, insurer, busy, inspect, send }: Props) {
  const [asking, setAsking] = useState(false);
  const [role, setRole] = useState("estimate");
  const [page, setPage] = useState("1");
  const [text, setText] = useState("");
  const latest = questions.at(-1);
  const pending = latest && latest.reply === null;
  const replying = Boolean(!insurer && pending);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!text.trim() || busy) return;
    const saved = replying && latest
      ? await send("clarifications/" + latest.sequence + "/reply", { reply: text.trim() })
      : await send("clarifications", {
        question: text.trim(), source_role: role, page: Number(page), previous_sequence: latest?.sequence || 0,
      });
    if (saved) { setAsking(false); setText(""); }
  }

  function exchange(item: CitedQuestion) {
    const source = sources.find(s => s.role === item.source_role);
    return <div className="question-exchange" key={item.sequence}>
      <strong>Insurer question</strong><p>{item.question}</p>
      {source && <button type="button" className="text-action" onClick={e => inspect({ role: source.role, label: source.label,
        url: source.url, page: item.page, quote: "" }, e.currentTarget)}>
        <FileText size={15}/>{source.label} · R{revision} · p. {item.page}
      </button>}
      {item.reply !== null && <><strong>Hospital reply · {handoffTime(item.replied_at)}</strong><p>{item.reply}</p></>}
    </div>;
  }

  if (!insurer && !latest) return null;
  return <section aria-label="Packet clarification" className="preclaim-questions">
    {latest && exchange(latest)}
    {questions.length > 1 && <details><summary>Earlier questions ({questions.length - 1})</summary>
      {questions.slice(0, -1).map(exchange)}</details>}
    {insurer && !pending && !asking && <button className="secondary" onClick={() => setAsking(true)}>
      <MessageSquare size={16}/>Ask about this packet</button>}
    {(asking || replying) && <form onSubmit={submit}>
      {insurer && <div className="question-citation">
        <label>Document<select value={role} onChange={event => {
          setRole(event.target.value); setPage(String(sources.find(s => s.role === event.target.value)?.page || 1));
        }}>{sources.map(s => <option key={s.role} value={s.role}>{s.label}</option>)}</select></label>
        <label>Page<input required type="number" min={1} step={1} value={page} onChange={e => setPage(e.target.value)}/></label>
      </div>}
      <label>{replying ? "Answer the insurer’s question" : "What needs clarification?"}
        <textarea required rows={3} maxLength={replying ? 3000 : 1500} value={text} onChange={e => setText(e.target.value)}/>
      </label>
      <div className="preclaim-actions"><button className="primary" disabled={!text.trim() || busy}>
        {replying ? "Send reply to insurer" : "Send question to hospital"}</button>
        {insurer && <button type="button" className="secondary" onClick={() => { setAsking(false); setText(""); }}>Cancel</button>}
      </div>
    </form>}
  </section>;
}
