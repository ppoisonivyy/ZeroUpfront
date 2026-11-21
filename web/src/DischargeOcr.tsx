import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Check, ExternalLink } from "lucide-react";
import { api, sameOriginSource } from "./api";
import { useStaffSession } from "./Auth";
import { claimPath, type DischargeClaim } from "./dischargeApi";

const PdfPage = lazy(() => import("./PdfPage"));
type ScanPage = {
  role: string;
  page: number;
  sha256: string;
  transcript_sha256: string;
  text: string;
  source_url: string;
};
type Review = { revision: number; eligible: boolean; pages: ScanPage[] };
const identity = (p: ScanPage) =>
  [p.role, p.page, p.sha256, p.transcript_sha256].join("/");

function CompareScan({
  item,
  filename,
  confirmed,
  onConfirm,
  disabled,
}: {
  item: ScanPage;
  filename: string;
  confirmed: boolean;
  onConfirm: (verified: boolean) => void;
  disabled: boolean;
}) {
  const [readable, setReadable] = useState(false);
  const markReady = useCallback(() => setReadable(true), []);
  let href = "";
  try {
    href = sameOriginSource(item.source_url);
  } catch {
    /* Protect against a stale or unsupported source address. */
  }
  return (
    <>
      <div className="workspace-grid ocr-compare">
        <section className="panel viewer">
          <div className="panel-heading">
            <h2>Original scan</h2>
            {href && (
              <a
                href={href + "#page=" + item.page}
                className="text-action"
                target="_blank"
                rel="noreferrer"
                onClick={markReady}
              >
                Open original PDF <ExternalLink size={14} />
              </a>
            )}
          </div>
          <div className="viewer-meta">
            <strong>{filename}</strong>
            <span>Physical page {item.page}</span>
          </div>
          {href ? (
            <Suspense
              fallback={<p className="loading">Loading scanned page…</p>}
            >
              <PdfPage
                url={href}
                page={item.page}
                label={filename}
                onReady={markReady}
                fixedPage
              />
            </Suspense>
          ) : (
            <p className="error-message" role="alert">
              The original page is unavailable. Reload the claim.
            </p>
          )}
        </section>
        <section className="panel">
          <div className="panel-heading">
            <h2>OCR transcript</h2>
            <span className="small">Page {item.page}</span>
          </div>
          <pre
            className="ocr-transcript"
            tabIndex={0}
            aria-label={
              "Transcribed text from " + filename + ", page " + item.page
            }
          >
            {item.text}
          </pre>
        </section>
      </div>
      <label className="check-field">
        <input
          type="checkbox"
          disabled={disabled || !readable || !item.text.trim()}
          checked={confirmed}
          onChange={(e) => onConfirm(e.target.checked)}
        />
        I compared the full transcript with {filename}, page {item.page}, and
        verified the text and amounts.
      </label>
    </>
  );
}
export default function DischargeOcr({
  claim,
  onSaved,
  onBack,
}: {
  claim: DischargeClaim;
  onSaved: () => void;
  onBack: () => void;
}) {
  const { actor } = useStaffSession();
  const [review, setReview] = useState<Review | null>(null),
    [confirmed, setConfirmed] = useState<Set<string>>(new Set()),
    [index, setIndex] = useState(0),
    [name, setName] = useState(actor || ""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const path = claimPath(claim.id);
  useEffect(() => {
    const controller = new AbortController();
    api(path + "/revisions/" + claim.revision + "/ocr-review", {
      signal: controller.signal,
    })
      .then((r) => r.json())
      .then((data) => {
        if (!controller.signal.aborted) setReview(data);
      })
      .catch((e) => {
        if (!controller.signal.aborted)
          setError(
            e instanceof Error
              ? e.message
              : "The OCR transcript could not be loaded.",
          );
      });
    return () => controller.abort();
  }, [path, claim.revision]);
  const eligible =
    !!review?.eligible &&
    review.revision === claim.revision &&
    review.pages.length > 0;
  const item = eligible ? review.pages[index] : null;
  const filename = (p: ScanPage) =>
    claim.sources.find((s) => s.role === p.role)?.label || p.role;
  const all = eligible && review.pages.every((p) => confirmed.has(identity(p)));
  async function save() {
    if (!all || busy || !name.trim()) return;
    setBusy(true);
    setError("");
    try {
      await api(path + "/verify-ocr", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "If-Match": '"' + claim.revision + '"',
        },
        body: JSON.stringify({
          reviewer: actor || name.trim(),
          pages: review.pages.map(
            ({ role, page, sha256, transcript_sha256 }) => ({
              role,
              page,
              sha256,
              transcript_sha256,
            }),
          ),
        }),
      });
      onSaved();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Verification could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <section>
      <div className="page-title">
        <div>
          <p className="section-label">Discharge claim · R{claim.revision}</p>
          <h1>Verify scanned pages</h1>
          <p>
            Compare each transcript with its original page before saving a
            verified revision.
          </p>
        </div>
      </div>
      {!review && !error && (
        <p role="status" className="loading">
          Loading revision-specific transcripts…
        </p>
      )}
      {review && !eligible && (
        <p role="status" className="history-warning">
          This revision cannot be cleared by OCR verification. Return to the
          packet to inspect the outstanding findings.
        </p>
      )}
      {item && review && (
        <>
          <div className="ocr-switch">
            <label className="stack-field">
              <span>Scanned page</span>
              <select
                value={index}
                disabled={busy}
                onChange={(e) => setIndex(Number(e.target.value))}
              >
                {review.pages.map((p, i) => (
                  <option key={identity(p)} value={i}>
                    {filename(p)} · p. {p.page}
                    {confirmed.has(identity(p)) ? " · Verified" : ""}
                  </option>
                ))}
              </select>
            </label>
            <span className="small" role="status">
              {confirmed.size} of {review.pages.length} verified
            </span>
          </div>
          <CompareScan
            key={identity(item)}
            item={item}
            filename={filename(item)}
            confirmed={confirmed.has(identity(item))}
            disabled={busy}
            onConfirm={(yes) =>
              setConfirmed((prev) => {
                const next = new Set(prev);
                if (yes) next.add(identity(item));
                else next.delete(identity(item));
                return next;
              })
            }
          />
          <div className="actions">
            {index > 0 && (
              <button
                type="button"
                disabled={busy}
                className="secondary"
                onClick={() => setIndex(index - 1)}
              >
                Previous scanned page
              </button>
            )}
            {index + 1 < review.pages.length && (
              <button
                type="button"
                disabled={busy}
                className="secondary"
                onClick={() => setIndex(index + 1)}
              >
                Next scanned page
              </button>
            )}
          </div>
          <label className="stack-field ocr-name">
            <span>OCR reviewer name</span>
            <input
              autoComplete="name"
              value={name}
              maxLength={100}
              readOnly={!!actor}
              disabled={busy}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
        </>
      )}
      {error && (
        <p className="error-message" role="alert">
          {error}
        </p>
      )}
      <div className="actions">
        {eligible && (
          <button
            className="primary"
            type="button"
            disabled={busy || !all || !name.trim()}
            onClick={() => void save()}
          >
            <Check size={16} />
            {busy ? "Saving…" : "Save verified revision"}
          </button>
        )}
        <button
          className="secondary"
          type="button"
          disabled={busy}
          onClick={onBack}
        >
          Back to claim
        </button>
      </div>
    </section>
  );
}
