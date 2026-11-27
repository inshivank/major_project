import { useId } from "react";
import type { Report } from "./api";
import { safeUrl } from "./api";
import { rangeGeometry } from "./rangeGeometry";
const labels = {
  within_range: "Within stated range",
  below_range: "Below stated range",
  above_range: "Above stated range",
  indeterminate: "Indeterminate",
};
export function ReportPresentation({
  report,
  filename,
  onReset,
}: {
  report: Report;
  filename?: string;
  onReset: () => void;
}) {
  const scope = useId().replace(/:/g, "");
  const explanation = report.explanation!;
  const citations = (ids: number[]) =>
    [...new Set(ids)]
      .filter(
        (id) => Number.isInteger(id) && id > 0 && id <= report.sources.length,
      )
      .map((id) => (
        <a
          className="citation"
          href={`#${scope}-source-${id}`}
          key={id}
          aria-label={`Inspect source ${id}`}
          onClick={() => {
            const element = document.getElementById(
              `${scope}-source-${id}`,
            ) as HTMLDetailsElement | null;
            if (element) {
              element.open = true;
              let parent = element.parentElement;
              while (parent) {
                if (parent instanceof HTMLDetailsElement) parent.open = true;
                parent = parent.parentElement;
              }
              element.focus();
            }
          }}
        >
          [{id}]
        </a>
      ));
  const rank = {
    below_range: 0,
    above_range: 0,
    within_range: 1,
    indeterminate: 2,
  };
  const tests = report.tests
    .map((test, index) => ({ test, index }))
    .sort(
      (a, b) => rank[a.test.status] - rank[b.test.status] || a.index - b.index,
    );
  return (
    <div className="structured-report">
      <section className="understanding">
        <p className="eyebrow">
          {explanation.mode === "llm_assisted"
            ? "AI-ASSISTED • VERIFIED SOURCES"
            : explanation.mode === "fallback"
              ? "LOCAL FALLBACK • AI EXPLANATION UNAVAILABLE"
              : "LOCAL REPORT ANALYSIS"}
        </p>
        <h3>Understanding Your Report</h3>
        <strong>{report.report_type}</strong>
        <p className="report-filename">{filename}</p>
        <p>{explanation.overall_summary}</p>
        <div className="stats">
          {[
            ["Parameters", report.tests.length],
            [
              "Within range",
              report.tests.filter((t) => t.status === "within_range").length,
            ],
            [
              "Outside range",
              report.tests.filter((t) =>
                ["below_range", "above_range"].includes(t.status),
              ).length,
            ],
            [
              "Indeterminate",
              report.tests.filter((t) => t.status === "indeterminate").length,
            ],
          ].map(([label, count]) => (
            <div key={label}>
              <strong>{count}</strong>
              {label}
            </div>
          ))}
        </div>
      </section>
      <div className="results-grid">
        <section className="results-parameters">
          <h3>Your Medical Parameters</h3>
          <p className="muted">
            Outside-range results appear first. Colors show range status, not
            clinical severity.
          </p>
          {tests.length === 0 && <p>No supported parameters were extracted.</p>}
          {tests.map(({ test, index }) => {
            const detail = explanation.parameter_explanations.find(
              (p) =>
                p.parameter_id ===
                (test.parameter_id ?? `parameter-${index + 1}`),
            );
            const geometry = rangeGeometry(test);
            return (
              <article className="parameter-card" key={index}>
                <header>
                  <h4>{test.name}</h4>
                  <span className={`badge ${test.status}`}>
                    {labels[test.status]}
                  </span>
                </header>
                <p className="parameter-value">
                  {test.value ?? "Unavailable"}{" "}
                  <small>{test.unit ?? "Unit not stated"}</small>
                </p>
                <p>
                  Reference range:{" "}
                  <strong>{test.reference_range ?? "Not stated"}</strong> · Page{" "}
                  {test.source_page}
                  {detail && citations(detail.citation_ids)}
                </p>
                {geometry ? (
                  <div
                    className="range-figure"
                    role="img"
                    aria-label={`Reported value ${test.value} ${test.unit}; range ${test.reference_range}; ${labels[test.status]}`}
                  >
                    <div
                      className="range-track"
                      style={{
                        background: `linear-gradient(to right,#fbe4b8 0% ${geometry.lowPosition}%,#ccebdc ${geometry.lowPosition}% ${geometry.highPosition}%,#f2cccc ${geometry.highPosition}% 100%)`,
                      }}
                    >
                      <span
                        className="range-marker"
                        style={{ left: `${geometry.marker}%` }}
                      />
                    </div>
                    <div className="range-boundaries">
                      <span style={{ left: `${geometry.lowPosition}%` }}>
                        {geometry.low}
                      </span>
                      <span style={{ left: `${geometry.highPosition}%` }}>
                        {geometry.high}
                      </span>
                    </div>
                    <div className="range-legend">
                      <span>Below range</span>
                      <span>Within range</span>
                      <span>Above range</span>
                    </div>
                  </div>
                ) : (
                  <p className="muted">
                    Range shown as reported; a two-sided numeric indicator is
                    unavailable.
                  </p>
                )}
                <details open>
                  <summary>What does this parameter measure?</summary>
                  {detail?.what_it_measures.length ? (
                    detail.what_it_measures.map((claim, i) => (
                      <p key={i}>
                        {claim.text} {citations(claim.citation_ids)}
                      </p>
                    ))
                  ) : (
                    <p>
                      Verified educational context is unavailable for this
                      parameter.
                    </p>
                  )}
                </details>
                <details open>
                  <summary>What does your result mean?</summary>
                  <p>
                    {detail?.range_explanation ??
                      "Review the stated range status with a healthcare professional."}
                  </p>
                </details>
                {test.uncertain && (
                  <p className="warning">
                    Uncertain extraction: verify against the original report.
                  </p>
                )}
                {test.warnings.map((w, i) => (
                  <p className="warning" key={i}>
                    {w}
                  </p>
                ))}
              </article>
            );
          })}
        </section>
        <aside className="results-explanation">
          {explanation.educational_context.length > 0 && (
            <section className="explanation-section">
              <h3>About These Tests</h3>
              {explanation.educational_context.map((claim, i) => (
                <p key={i}>
                  {claim.text} {citations(claim.citation_ids)}
                </p>
              ))}
            </section>
          )}
          <section className="explanation-section">
            <h3>Questions to Discuss With Your Doctor</h3>
            <ol>
              {explanation.doctor_discussion_questions.map((q, i) => (
                <li key={i}>{q}</li>
              ))}
            </ol>
          </section>
          <details className="explanation-section" open>
            <summary>References and Sources ({report.sources.length})</summary>
            {report.sources.map((source, i) => (
              <details
                id={`${scope}-source-${i + 1}`}
                tabIndex={-1}
                className="source"
                key={i}
              >
                <summary>
                  [{i + 1}] {source.title}
                </summary>
                <small>
                  {source.type === "record"
                    ? "Uploaded medical report"
                    : "External knowledge source"}
                </small>
                {source.snippet && <p>{source.snippet}</p>}
                {safeUrl(source.url) && (
                  <a
                    href={safeUrl(source.url)}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Open source ↗
                  </a>
                )}
              </details>
            ))}
          </details>
          <section className="explanation-section medical-info">
            <h3>Important Medical Information</h3>
            <p>{explanation.medical_disclaimer}</p>
            <ul>
              {[
                ...new Set([...explanation.limitations, ...report.warnings]),
              ].map((text, i) => (
                <li key={i}>{text}</li>
              ))}
            </ul>
          </section>
          <section className="explanation-section">
            <h3>When to Seek Urgent Help</h3>
            <p>{explanation.urgent_care_guidance}</p>
          </section>
        </aside>
      </div>
      <button className="primary" onClick={onReset}>
        Analyze another report
      </button>
    </div>
  );
}
