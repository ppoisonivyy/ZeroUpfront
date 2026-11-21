import { lazy, Suspense, useId, useState } from "react";
import { ChevronDown, ExternalLink, FileText, X } from "lucide-react";
import { sameOriginSource, type CaseDetail } from "./api";

const PdfPage = lazy(() => import("./PdfPage"));
const roles: Record<string, string> = {
  policy: "Policy schedule",
  plan: "Treatment plan",
  estimate: "Hospital estimate",
  bill: "Final itemized bill",
  summary: "Discharge summary",
  letter: "Payer letter",
  records: "Supporting records",
};

export function AttachmentList({
  packet,
}: {
  packet: Pick<CaseDetail, "revision" | "sources">;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [previewPage, setPreviewPage] = useState(1);
  const id = useId();
  return (
    <section className="attachments" aria-label="Request attachments">
      <h3>Preview attachments</h3>
      {packet.sources.map((source, index) => {
        const buttonId = id + "-attachment-" + index;
        const previewId = buttonId + "-preview";
        const open = selected === source.url;
        let href = "";
        try {
          href = sameOriginSource(source.url);
        } catch {
          /* The excerpt remains available. */
        }
        return (
          <div className="attachment" key={source.url}>
            <button
              id={buttonId}
              type="button"
              className="attachment-toggle"
              aria-controls={previewId}
              aria-expanded={open}
              onClick={() => {
                setPreviewPage(source.page || 1);
                setSelected(open ? null : source.url);
              }}
            >
              <span className="file-icon">
                <FileText size={17} />
              </span>
              <span className="row-detail">
                <strong>{source.label}</strong>
                <small>
                  {roles[source.role] || source.role} · R{packet.revision} · p.{" "}
                  {source.page}
                </small>
              </span>
              <ChevronDown size={17} />
            </button>
            <div
              hidden={!open}
              id={previewId}
              role="region"
              aria-labelledby={buttonId}
            >
              {open && (
                <div className="attachment-preview">
                  <div className="attachment-tools">
                    <span>Cited excerpt · page {source.page || 1}</span>
                    {href && (
                      <a
                        className="text-action"
                        href={href + "#page=" + previewPage}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Open original PDF <ExternalLink size={14} />
                      </a>
                    )}
                  </div>
                  <blockquote>{source.quote}</blockquote>
                  {href && (
                    <Suspense
                      fallback={<p className="loading">Loading PDF viewer…</p>}
                    >
                      <PdfPage
                        url={href}
                        page={source.page}
                        label={source.label}
                        onPageChange={setPreviewPage}
                      />
                    </Suspense>
                  )}
                  <button
                    className="text-action close-preview"
                    type="button"
                    onClick={() => {
                      setSelected(null);
                      document.getElementById(buttonId)?.focus();
                    }}
                  >
                    <X size={14} />
                    Close preview
                  </button>
                </div>
              )}
            </div>
          </div>
        );
      })}
    </section>
  );
}
