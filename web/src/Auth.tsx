import { createContext, useContext, useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { ArrowLeft, ArrowRight, Building2, Eye, EyeOff, Hospital, Layers } from "lucide-react";
import { hospitalPrefix, sameOriginSource } from "./api";
import "./auth.css";

type Session = { role?: "hospital" | "insurer"; insurer?: string; mode: "local" | "staff"; actor: string | null; username?: string | null; hospital_name?: string };
type Directory = { mode: "single" | "multi"; hospitals: { slug: string; name: string }[] };
type Account = Session & { busy: boolean; problem: string; signOut: (switchHospital?: boolean, desk?: "hospital" | "insurer") => Promise<void> };
const StaffSession = createContext<Account | null>(null);
export function useStaffSession() {
  const value = useContext(StaffSession);
  if (!value) throw new Error("Open a hospital workspace first.");
  return value;
}

async function readSession(path: string, options?: RequestInit): Promise<Session> {
  const response = await fetch(sameOriginSource("/api/access/" + path), { cache: "no-store", ...options });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(typeof data?.detail === "string" ? data.detail : "The workspace could not verify your session.");
  }
  return response.json();
}

function Entry({ children }: { children: ReactNode }) {
  return <main className="staff-entry">
    <header className="entry-header"><span className="mast-brand">
      <span className="mast-symbol"><Layers size={20} aria-hidden="true" /></span>ZeroUpfront
    </span></header>
    <div className="entry-content">{children}</div>
  </main>;
}

function EntryStatus({ error, retry }: { error: string; retry: () => void }) {
  return <Entry><div className="staff-form entry-status">
    <span role={error ? "alert" : "status"}>{error || "Opening workspace…"}</span>
    {error && <button className="primary" onClick={retry}>Try again</button>}
    {error && hospitalPrefix && <a href="/">Choose another hospital</a>}
  </div></Entry>;
}

export function AuthGate({ children }: { children: ReactNode }) {
  const [directory, setDirectory] = useState<Directory | null>(null);
  const [problem, setProblem] = useState("");
  const [attempt, retry] = useState(0);
  useEffect(() => {
    if (hospitalPrefix) return;
    const abort = new AbortController();
    setProblem("");
    fetch("/api/hospitals", { cache: "no-store", signal: abort.signal })
      .then(async response => {
        if (!response.ok) throw new Error("Hospital list unavailable.");
        const data: Directory = await response.json();
        if (!["single", "multi"].includes(data.mode) || !Array.isArray(data.hospitals))
          throw new Error("Hospital list unavailable.");
        if (!abort.signal.aborted) setDirectory(data);
      })
      .catch(() => { if (!abort.signal.aborted) setProblem("Could not load the hospital directory."); });
    return () => abort.abort();
  }, [attempt]);

  if (hospitalPrefix || directory?.mode === "single") return <SessionGate>{children}</SessionGate>;
  if (!directory) return <EntryStatus error={problem} retry={() => retry(n => n + 1)} />;
  return <Entry><section className="staff-form directory" aria-labelledby="directory-title">
    <div className="entry-heading"><span className="entry-emblem"><Hospital size={24} /></span>
      <h1 id="directory-title">Choose your hospital</h1>
      <p>Open your hospital’s claims workspace with your staff account.</p>
    </div>
    <nav className="hospital-choices" aria-label="Hospital workspaces">
      {directory.hospitals.map(h => <a key={h.slug} href={"/h/" + encodeURIComponent(h.slug) + "/"}>
        <Building2 size={20} aria-hidden="true" /><span>{h.name}</span><ArrowRight size={17} aria-hidden="true" />
      </a>)}
    </nav>
    {!directory.hospitals.length && <p role="status">No hospital workspaces are available.</p>}
  </section></Entry>;
}

function SessionGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const [visible, showPassword] = useState(false);
  const [attempt, retry] = useState(0);
  const version = useRef(0);
  const updating = useRef(false);
  useEffect(() => {
    const refresh = async () => {
      if (updating.current) return;
      const current = ++version.current;
      try {
        const data = await readSession("session");
        if (current === version.current) { setSession(data); setProblem(""); }
      } catch {
        if (current === version.current) { setSession(null); setProblem("Could not reach this hospital workspace."); }
      }
    };
    void refresh();
    const check = () => { if (document.visibilityState === "visible") void refresh(); };
    const restored = (event: PageTransitionEvent) => { if (event.persisted) void refresh(); };
    const expired = () => { setSession(null); void refresh(); };
    document.addEventListener("visibilitychange", check);
    window.addEventListener("pageshow", restored);
    window.addEventListener("staff-session-expired", expired);
    return () => {
      ++version.current;
      document.removeEventListener("visibilitychange", check);
      window.removeEventListener("pageshow", restored);
      window.removeEventListener("staff-session-expired", expired);
    };
  }, [attempt]);

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (updating.current) return;
    const values = new FormData(event.currentTarget);
    updating.current = true;
    ++version.current;
    setBusy(true); setProblem("");
    try {
      const data = await readSession("login", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: values.get("username"), password: values.get("password") }),
      });
      showPassword(false); setSession(data);
    } catch (error) { setProblem(error instanceof Error ? error.message : "Sign-in failed."); }
    finally { updating.current = false; setBusy(false); }
  }

  async function signOut(switchHospital = false, desk?: "hospital" | "insurer") {
    if (updating.current) return;
    updating.current = true;
    ++version.current;
    setBusy(true); setProblem("");
    try {
      const data = await readSession("logout", { method: "POST" });
      setSession(data);
      if (switchHospital) window.location.replace("/");
      else if (desk) history.replaceState(null, "", location.pathname + (desk === "insurer" ? "#/insurer" : "#/cases"));
      else if (location.hash) history.replaceState(null, "", location.pathname);
    } catch { setProblem("Sign-out could not be confirmed. Please try again."); }
    finally { updating.current = false; setBusy(false); }
  }

  if (!session) return <EntryStatus error={problem} retry={() => retry(n => n + 1)} />;
  if (session.mode === "staff" && !session.actor) return <Entry>
    <form onSubmit={login} className="staff-form">
      <div className="entry-heading">
        {hospitalPrefix && <a className="entry-back" href="/"><ArrowLeft size={15} />All hospitals</a>}
        {session.hospital_name && <p className="entry-hospital"><Hospital size={16} />{session.hospital_name}</p>}
        <h1>{location.hash.startsWith("#/insurer") ? "Insurer sign in" : "Staff sign in"}</h1>
      </div>
      <label className="entry-field">Username<input name="username" autoComplete="username" required autoCapitalize="none" spellCheck={false} maxLength={128}/></label>
      <div className="entry-field"><label htmlFor="staff-password">Password</label><div className="password-field">
        <input id="staff-password" name="password" type={visible ? "text" : "password"} autoComplete="current-password" required maxLength={256}/>
        <button type="button" aria-label={visible ? "Hide password" : "Show password"} onClick={() => showPassword(!visible)}>
          {visible ? <EyeOff size={18} /> : <Eye size={18} />}
        </button>
      </div></div>
      {problem && <p className="error-message" role="alert">{problem}</p>}
      <button className="primary entry-submit" disabled={busy} type="submit">{busy ? "Signing in…" : "Sign in"}<ArrowRight size={16} /></button>
    </form>
  </Entry>;
  return <StaffSession.Provider value={{ ...session, busy, problem, signOut }}>{children}</StaffSession.Provider>;
}
