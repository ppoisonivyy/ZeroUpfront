import { createContext, useContext, useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import "./auth.css";

type Session = { mode: "local" | "staff"; actor: string | null; username?: string | null };
const StaffSession = createContext<Session>({ mode: "local", actor: null });
export const useStaffSession = () => useContext(StaffSession);

async function readSession(path: string, options?: RequestInit): Promise<Session> {
  const response = await fetch("/api/access/" + path, { cache: "no-store", ...options });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(typeof data?.detail === "string" ? data.detail : "The workspace could not verify your session.");
  }
  return response.json();
}

export function AuthGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  const [attempt, retry] = useState(0);

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const data = await readSession("session");
        if (active) { setSession(data); setProblem(""); }
      } catch {
        if (active) { setSession(null); setProblem("Could not reach the hospital workspace."); }
      }
    };
    void refresh();
    const check = () => { if (document.visibilityState === "visible") void refresh(); };
    document.addEventListener("visibilitychange", check);
    window.addEventListener("staff-session-expired", refresh);
    return () => {
      active = false;
      document.removeEventListener("visibilitychange", check);
      window.removeEventListener("staff-session-expired", refresh);
    };
  }, [attempt]);

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    setBusy(true); setProblem("");
    try {
      setSession(await readSession("login", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: values.get("username"), password: values.get("password") }),
      }));
    } catch (error) { setProblem(error instanceof Error ? error.message : "Sign-in failed."); }
    finally { setBusy(false); }
  }

  async function logout() {
    setBusy(true);
    try { setSession(await readSession("logout", { method: "POST" })); setProblem(""); }
    catch { setProblem("Sign-out could not be confirmed. Please try again."); }
    finally { setBusy(false); }
  }

  if (!session) return <main className="staff-entry"><div className="staff-form">
    <strong>ZeroUpfront</strong><p role="status">{problem || "Opening workspace…"}</p>
    {problem && <button onClick={() => retry(value => value + 1)}>Try again</button>}
  </div></main>;
  if (session.mode === "staff" && !session.actor) return <main className="staff-entry">
    <form onSubmit={login} className="staff-form">
      <strong>ZeroUpfront</strong><h1>Staff sign in</h1>
      <label>Username<input name="username" autoComplete="username" required autoCapitalize="none" maxLength={128}/></label>
      <label>Passphrase<input name="password" type="password" autoComplete="current-password" required maxLength={256}/></label>
      {problem && <p role="alert">{problem}</p>}
      <button disabled={busy} type="submit">{busy ? "Signing in…" : "Sign in"}</button>
    </form>
  </main>;
  return <StaffSession.Provider value={session}>
    {session.mode === "staff" && <div className="staff-account">
      {problem && <span role="alert">{problem}</span>}
      <span>{session.actor}</span><button disabled={busy} onClick={logout}>Sign out</button>
    </div>}
    {children}
  </StaffSession.Provider>;
}
