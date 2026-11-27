import { ReportPresentation } from "./ReportPresentation";
import { useEffect, useRef, useState } from "react";
import {
  analyze,
  getLimits,
  safeUrl,
  validateFile,
  type Limits,
  type Report,
} from "./api";
const labels = {
  within_range: "Within stated range",
  below_range: "Below stated range",
  above_range: "Above stated range",
  indeterminate: "Indeterminate",
};
export function ReportAnalyzer({
  sessionKey = "anonymous",
}: {
  sessionKey?: string;
}) {
  const [open, setOpen] = useState(false),
    [maximized, setMaximized] = useState(false),
    [file, setFile] = useState<File | null>(null),
    [consent, setConsent] = useState(false),
    [result, setResult] = useState<Report | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [limits, setLimits] = useState<Limits | null>(null),
    [settingsError, setSettingsError] = useState(""),
    [reload, setReload] = useState(0),
    [drag, setDrag] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null),
    panel = useRef<HTMLElement>(null),
    input = useRef<HTMLInputElement>(null),
    request = useRef<AbortController | null>(null),
    locked = useRef(false),
    wasOpen = useRef(false);
  function reset() {
    request.current?.abort();
    request.current = null;
    locked.current = false;
    setBusy(false);
    setFile(null);
    setResult(null);
    setError("");
    setConsent(false);
    panel.current?.focus();
    if (input.current) input.current.value = "";
  }
  useEffect(() => {
    reset();
    return () => request.current?.abort();
  }, [sessionKey]);
  useEffect(() => {
    const c = new AbortController();
    getLimits(c.signal)
      .then(setLimits)
      .catch(() => {
        if (!c.signal.aborted)
          setSettingsError(
            "Upload settings unavailable. Check that CoreCare is running.",
          );
      });
    return () => c.abort();
  }, [reload]);
  function hide() {
    const finish = () => {
      setOpen(false);
      trigger.current?.focus();
    };
    if (
      panel.current?.animate &&
      !window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ) {
      void panel.current
        .animate(
          [
            { opacity: 1, transform: "translateY(0)" },
            { opacity: 0, transform: "translateY(10px)" },
          ],
          { duration: 140, easing: "ease-in" },
        )
        .finished.then(finish, finish);
    } else finish();
  }
  useEffect(() => {
    if (open) panel.current?.focus();
    else if (wasOpen.current) trigger.current?.focus();
    wasOpen.current = open;
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        escapeWindow();
      }
    };
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, [open, maximized]);

  useEffect(() => {
    if (!open || !maximized) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const siblings: HTMLElement[] = [];
    let node: HTMLElement | null = panel.current;
    while (node?.parentElement && node.parentElement !== document.body) {
      for (const sibling of node.parentElement.children) {
        if (
          sibling !== node &&
          sibling instanceof HTMLElement &&
          !sibling.inert
        ) {
          sibling.inert = true;
          siblings.push(sibling);
        }
      }
      node = node.parentElement;
    }
    return () => {
      document.body.style.overflow = previous;
      siblings.forEach((el) => (el.inert = false));
    };
  }, [open, maximized]);
  function escapeWindow() {
    if (maximized) {
      setMaximized(false);
      panel.current?.focus();
    } else hide();
  }

  function choose(f?: File) {
    if (!f || busy || !limits) return;
    const problem = validateFile(f, limits);
    setError(problem || "");
    if (!problem) {
      setFile(f);
      setResult(null);
    }
  }
  async function submit() {
    if (!file || !limits || locked.current) return;
    locked.current = true;
    const c = new AbortController();
    request.current = c;
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const data = await analyze(file, consent, limits, c.signal);
      if (request.current === c && !c.signal.aborted) setResult(data);
    } catch (e) {
      if (request.current === c && !c.signal.aborted)
        setError(
          e instanceof Error ? e.message : "Analysis failed. Please retry.",
        );
    } finally {
      if (request.current === c) {
        setBusy(false);
        locked.current = false;
        request.current = null;
      }
    }
  }
  function keys(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      escapeWindow();
    }
    if (e.key === "Tab") {
      const elements = panel.current?.querySelectorAll<HTMLElement>(
        "button:not(:disabled),input:not(:disabled),a[href],summary",
      );
      if (!elements?.length) return;
      const first = elements[0],
        last = elements[elements.length - 1];
      if (
        e.shiftKey &&
        (document.activeElement === first ||
          document.activeElement === panel.current)
      ) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }
  const low =
      result?.tests.filter((t) => t.status === "below_range").length || 0,
    high = result?.tests.filter((t) => t.status === "above_range").length || 0;
  return (
    <>
      <button
        ref={trigger}
        className="launcher"
        aria-expanded={open}
        aria-controls="report-panel"
        onClick={() => setOpen(!open)}
      >
        <span aria-hidden="true">✚</span> Medical Report Analysis{" "}
        {busy && <span className="tiny-spinner" />}
      </button>
      {open && maximized && (
        <div className="agent-backdrop" aria-hidden="true" />
      )}
      {open && (
        <section
          id="report-panel"
          ref={panel}
          tabIndex={-1}
          role="dialog"
          aria-modal={maximized}
          aria-labelledby="report-title"
          className={`agent-panel ${maximized ? "maximized" : ""}`}
          onKeyDown={keys}
        >
          <header className="agent-header">
            <span className="agent-icon" aria-hidden="true">
              ✚
            </span>
            <div>
              <h2 id="report-title">Medical Report Analysis</h2>
              <p>CoreCare Medical Agent</p>
            </div>
            <button
              aria-label="Minimize Medical Report Analysis"
              title="Minimize"
              onClick={hide}
            >
              −
            </button>
            <button
              aria-label={
                maximized
                  ? "Restore Medical Report Analysis"
                  : "Maximize Medical Report Analysis"
              }
              title={maximized ? "Restore" : "Maximize"}
              onClick={() => setMaximized((value) => !value)}
            >
              <svg
                aria-hidden="true"
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.7"
              >
                {maximized ? (
                  <>
                    <path d="M8 3v5H3M16 21v-5h5M8 8 2 2m14 14 6 6" />
                  </>
                ) : (
                  <>
                    <path d="M8 3H3v5m13 13h5v-5M3 3l6 6m12 12-6-6" />
                  </>
                )}
              </svg>
            </button>
            <button
              aria-label="Close Medical Report Analysis"
              title="Close"
              onClick={hide}
            >
              ×
            </button>
          </header>
          <div className="agent-body">
            <p className="eyebrow">YOUR RESULTS, EXPLAINED</p>
            <p>
              Hello! Welcome to Medical Report Analysis. Upload your medical
              report, and I'll help you understand your test results, identify
              abnormal values, and provide clear explanations.
            </p>
            {settingsError && !limits && (
              <div role="alert">
                {settingsError}
                <button
                  onClick={() => {
                    setSettingsError("");
                    setReload((n) => n + 1);
                  }}
                >
                  Retry settings
                </button>
              </div>
            )}
            {!result && (
              <>
                <div
                  className={`drop-zone ${drag ? "dragging" : ""}`}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDrag(true);
                  }}
                  onDragLeave={() => setDrag(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setDrag(false);
                    if (e.dataTransfer.files.length !== 1)
                      setError("Choose one report at a time.");
                    else choose(e.dataTransfer.files[0]);
                  }}
                >
                  <span className="upload-icon" aria-hidden="true">
                    ↥
                  </span>
                  <strong>Drop your report here</strong>
                  <span>or choose a file from your device</span>
                  <button
                    disabled={busy || !limits}
                    onClick={() => input.current?.click()}
                  >
                    Browse file
                  </button>
                  <input
                    ref={input}
                    aria-label="Medical report file"
                    type="file"
                    hidden
                    accept={limits?.formats.map((f) => "." + f).join(",")}
                    onChange={(e) => choose(e.target.files?.[0])}
                  />
                  <small>
                    {limits
                      ? `${limits.formats.join(", ").toUpperCase()} · Up to ${(limits.max_bytes / 1048576).toFixed(0)} MB`
                      : "Loading upload limits…"}
                  </small>
                </div>
                {file && (
                  <div className="selected-file">
                    <div>
                      <strong>{file.name}</strong>
                      <small>
                        {(file.size / 1024).toFixed(1)} KB · Ready for local
                        analysis
                      </small>
                    </div>
                    <button
                      aria-label="Remove selected file"
                      disabled={busy}
                      onClick={reset}
                    >
                      ×
                    </button>
                  </div>
                )}
                <label className="consent">
                  <input
                    type="checkbox"
                    checked={consent}
                    disabled={busy}
                    onChange={(e) => setConsent(e.target.checked)}
                  />
                  <span>
                    Include AI-generated explanations
                    <small>
                      Optional: consent to sending test names and comparison
                      statuses to Groq. Basic extraction stays local;
                      identifiers and report text are not sent.
                    </small>
                  </span>
                </label>
                <button
                  className="primary"
                  disabled={!file || !limits || busy}
                  onClick={submit}
                >
                  {busy ? "Analyzing report…" : "Analyze Report →"}
                </button>
              </>
            )}
            <div aria-live="polite" role="status">
              {result && (
                <span className="sr-only">
                  Analysis returned with {result.tests.length} parameters.
                  Review results and warnings.
                </span>
              )}
              {busy && (
                <div className="loading">
                  <span className="spinner" />
                  <strong>Understanding your report</strong>
                  <p>
                    Validation, extraction, range comparison and, with consent,
                    AI explanation may take a little time. You can minimize this
                    panel.
                  </p>
                </div>
              )}
            </div>
            {error && (
              <div role="alert" className="error">
                {error}
                <p>Retry analysis or choose a different report.</p>
              </div>
            )}
            {result?.explanation && (
              <ReportPresentation
                report={result}
                filename={file?.name}
                onReset={reset}
              />
            )}
            {result && !result.explanation && (
              <div className="results-grid">
                <div className="results-parameters">
                  <div className="result-banner">
                    <span>✓ Analysis returned</span>
                    <strong>{result.report_type}</strong>
                    <small>
                      {file?.name} · {result.metadata.page_count} page(s) ·{" "}
                      {result.status === "partial"
                        ? "Partial result — review warnings"
                        : "Completed"}
                    </small>
                  </div>
                  <div className="stats">
                    <div>
                      <strong>{result.tests.length}</strong>Parameters
                    </div>
                    <div>
                      <strong>
                        {
                          result.tests.filter(
                            (t) => t.status === "within_range",
                          ).length
                        }
                      </strong>
                      Within range
                    </div>
                    <div>
                      <strong>{low + high}</strong>Outside range
                    </div>
                    <div>
                      <strong>
                        {
                          result.tests.filter(
                            (t) => t.status === "indeterminate",
                          ).length
                        }
                      </strong>
                      Indeterminate
                    </div>
                  </div>
                  <details open>
                    <summary>Medical parameters</summary>
                    {result.tests.length === 0 && (
                      <p>No supported measurements were extracted.</p>
                    )}
                    {result.tests.map((t, i) => (
                      <article className="measurement" key={i}>
                        <div>
                          <strong>{t.name}</strong>
                          <span className={`badge ${t.status}`}>
                            {labels[t.status]}
                          </span>
                        </div>
                        <p className="value">
                          {t.value ?? "Unavailable"}{" "}
                          <small>{t.unit ?? "Unit not stated"}</small>
                        </p>
                        <small>
                          Report range: {t.reference_range ?? "Not stated"} ·
                          Page {t.source_page}
                        </small>
                        {t.uncertain && (
                          <p>
                            Uncertain extraction: verify against the original.
                          </p>
                        )}
                        {t.warnings.map((w, j) => (
                          <p className="warning" key={j}>
                            {w}
                          </p>
                        ))}
                      </article>
                    ))}
                  </details>
                </div>
                <div className="results-explanation">
                  <details open>
                    <summary>
                      {result.external_llm_used
                        ? "AI-assisted educational explanation"
                        : "Local analysis summary"}
                    </summary>
                    <p className="summary-text">{result.summary}</p>
                  </details>
                  {result.warnings.length > 0 && (
                    <details open>
                      <summary>Limitations & warnings</summary>
                      <ul>
                        {result.warnings.map((w, i) => (
                          <li key={i}>{w}</li>
                        ))}
                      </ul>
                    </details>
                  )}
                  <details>
                    <summary>
                      Sources & citations ({result.sources.length})
                    </summary>
                    {result.sources.map((s, i) => (
                      <details className="source" key={i}>
                        <summary>
                          [{i + 1}] {s.title}
                        </summary>
                        <small>
                          {s.type === "record"
                            ? "Uploaded report"
                            : s.type === "reference"
                              ? "Medical knowledge source"
                              : "Model source"}
                        </small>
                        {s.snippet && <p>{s.snippet}</p>}
                        {safeUrl(s.url) && (
                          <a
                            href={safeUrl(s.url)}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            Open source ↗
                          </a>
                        )}
                      </details>
                    ))}
                  </details>
                  <p className="disclaimer">{result.disclaimer}</p>
                </div>
                <button className="primary results-reset" onClick={reset}>
                  Analyze another report
                </button>
              </div>
            )}
            {(file || result || busy) && (
              <button className="clear" onClick={reset}>
                Clear current report and results
              </button>
            )}
            {!result?.explanation && (
              <footer>
                This analysis is AI-assisted and intended for informational
                purposes only. It does not provide a medical diagnosis or
                replace consultation with a qualified healthcare professional.
              </footer>
            )}
          </div>
          <div className="privacy">
            ♧ Private by design · No browser storage
          </div>
        </section>
      )}
    </>
  );
}
