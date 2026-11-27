import React from "react";
import { createRoot } from "react-dom/client";
import { ReportAnalyzer } from "./ReportAnalyzer";
import "./style.css";
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <main className="shell">
      <nav>
        <strong>✚ CoreCare</strong>
        <span>Healthcare workspace</span>
      </nav>
      <section className="intro">
        <p className="eyebrow">YOUR CARE, CONNECTED</p>
        <h1>
          A little clarity.
          <br />A more informed you.
        </h1>
        <p>
          Understand the information in your medical report, with context you
          can discuss with your healthcare professional.
        </p>
        <div className="workspace-card">
          <span className="agent-icon">↗</span>
          <div>
            <h2>Your report companion</h2>
            <p>
              Open Medical Report Analysis to get started. Your documents stay
              in this session until you clear them or leave the page.
            </p>
          </div>
        </div>
        <p className="muted">
          Educational support. Always review your results with a qualified
          clinician.
        </p>
      </section>
      <ReportAnalyzer />
    </main>
  </React.StrictMode>,
);
