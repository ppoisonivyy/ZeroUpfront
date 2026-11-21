// The actual benchmark runs in a local POSIX PTY. Only its output goes to the recorded tab.
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { StringDecoder } from "node:string_decoder";
import type { Page } from "@playwright/test";

interface BrowserTerminal {
  open: (element: HTMLElement) => void;
  write: (data: string, complete: () => void) => void;
}

type TerminalWindow = Window & {
  Terminal: new (options: Record<string, unknown>) => BrowserTerminal;
  holdoutTerminal?: BrowserTerminal;
};

const requireRecorder = createRequire(join(process.cwd(), "package.json"));
const command = "exec uv run --locked python demo/holdout.py";
const bridge = [
  "import errno, os, pty, sys",
  "pid, master = pty.fork()",
  "if pid == 0: os.execl('/bin/sh', 'sh', '-xc', sys.argv[1])",
  "while True:",
  "    try: data = os.read(master, 8192)",
  "    except OSError as exc:",
  "        if exc.errno == errno.EIO: break",
  "        raise",
  "    if not data: break",
  "    sys.stdout.buffer.write(data); sys.stdout.buffer.flush()",
  "os.close(master)",
  "raise SystemExit(os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1]))",
].join("\n");

export async function showHoldout(
  page: Page,
  hold = (ms: number) => page.waitForTimeout(ms),
) {
  const library = requireRecorder.resolve("@xterm/xterm");
  await page.addScriptTag({ path: library });
  await page.addStyleTag({ path: join(dirname(library), "../css/xterm.css") });
  await page.evaluate(async () => {
    const layer = document.createElement("section");
    layer.id = "holdout-terminal";
    layer.setAttribute("aria-label", "Live payer-form regression terminal");
    Object.assign(layer.style, {
      position: "fixed",
      inset: "0",
      zIndex: "9000",
      padding: "10vh 6vw 0",
      background: "#101a1e",
      boxSizing: "border-box",
      overflow: "hidden",
    });
    document.body.append(layer);
    const terminalWindow = window as TerminalWindow;
    const fontSize = Math.max(14, Math.min(32, Math.floor(innerWidth / 65)));
    const terminal = new terminalWindow.Terminal({
      cols: Math.floor((innerWidth * 0.88) / (fontSize * 0.62)),
      rows: Math.floor((innerHeight * 0.76) / (fontSize * 1.4)),
      fontSize,
      fontFamily: "Menlo, Consolas, monospace",
      lineHeight: 1.34,
      theme: {
        background: "#101a1e",
        foreground: "#f1f5ef",
        cursor: "#91e4bb",
      },
      cursorBlink: false,
      disableStdin: true,
      scrollback: 100,
    });
    terminal.open(layer);
    terminalWindow.holdoutTerminal = terminal;
    await document.fonts.ready;
  });

  const child = spawn("python3", ["-u", "-c", bridge, command], {
    cwd: process.cwd(),
    stdio: ["pipe", "pipe", "pipe"],
    env: {
      PATH: process.env.PATH,
      HOME: process.env.HOME,
      LANG: "en_US.UTF-8",
      TERM: "xterm-256color",
      PS4: "ZeroUpfront $ ",
      UV_NO_PROGRESS: "1",
    },
  });
  let rendered = Promise.resolve();
  let output = "";

  const decoder = new StringDecoder("utf8");
  const append = (chunk: string) => {
    if (!chunk) return;
    output += chunk;
    rendered = rendered.then(() =>
      page.evaluate(
        (text) =>
          new Promise<void>((done) =>
            (window as TerminalWindow).holdoutTerminal!.write(text, done),
          ),
        chunk,
      ),
    );
  };
  child.stdout.on("data", (chunk: Buffer) => append(decoder.write(chunk)));
  child.stderr.on("data", (chunk: Buffer) => append(chunk.toString("utf8")));
  // The shell traces its actual fixed command. Browser keystrokes are never forwarded.
  const timeout = setTimeout(() => {
    child.kill("SIGTERM");
  }, 90_000);
  try {
    const status = await new Promise<number | null>((resolve, reject) => {
      child.once("error", reject);
      child.once("close", resolve);
    });
    append(decoder.end());
    await rendered;
    if (
      status !== 0 ||
      !output.includes("Regression gate:") ||
      !output.includes("PASS")
    ) {
      throw new Error(
        "The recorded payer-form regression did not pass. Inspect the terminal output.",
      );
    }
    await hold(1800);
  } finally {
    clearTimeout(timeout);
    child.stdin.destroy();
    if (child.exitCode === null && child.signalCode === null) child.kill();
  }
}
