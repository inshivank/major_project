import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReportPresentation } from "./ReportPresentation";
import { rangeGeometry } from "./rangeGeometry";
import type { Report } from "./api";
const parameter = {
  name: "Hemoglobin",
  parameter_id: "parameter-1",
  original_label: "Hb",
  value: "10",
  unit: "g/dL",
  reference_range: "12-16 g/dL",
  status: "below_range" as const,
  source_page: 1,
  uncertain: false,
  warnings: [],
};
const report: Report = {
  agent: "medical_report",
  status: "partial",
  report_type: "CBC",
  metadata: { page_count: 1, extracted_pages: [1] },
  tests: [parameter],
  summary: "Legacy text should not appear",
  warnings: [],
  sources: [
    { type: "record", title: "Uploaded report" },
    {
      type: "reference",
      title: "Verified test reference",
      url: "https://example.org",
      snippet: "Synthetic verified evidence.",
    },
  ],
  disclaimer: "Legacy disclaimer",
  external_llm_used: false,
  explanation: {
    mode: "local",
    overall_summary: "One parameter analyzed.",
    parameter_explanations: [
      {
        parameter_id: "parameter-1",
        range_explanation: "Below the range stated in the report.",
        what_it_measures: [
          { text: "Synthetic verified evidence.", citation_ids: [2, 999] },
        ],
        citation_ids: [1],
      },
    ],
    educational_context: [],
    doctor_discussion_questions: ["Does this need repeat testing?"],
    limitations: ["Results need verification."],
    medical_disclaimer: "Educational only; not a diagnosis.",
    urgent_care_guidance: "Contact emergency services for severe symptoms.",
    citation_ids: [1, 2],
  },
};
it("renders structured cards, questions and a single consolidated safety section", () => {
  render(<ReportPresentation report={report} onReset={() => {}} />);
  expect(screen.getByText("Understanding Your Report")).toBeInTheDocument();
  expect(screen.getByText("Hemoglobin")).toBeInTheDocument();
  expect(
    screen.getByText("Does this need repeat testing?"),
  ).toBeInTheDocument();
  expect(screen.getByText("Important Medical Information")).toBeInTheDocument();
  expect(
    screen.queryByText("Legacy text should not appear"),
  ).not.toBeInTheDocument();
  expect(screen.queryByText("[999]")).not.toBeInTheDocument();
  expect(screen.getByRole("img")).toHaveAccessibleName(/Reported value 10/);
});
it("expands the actual referenced source", async () => {
  render(<ReportPresentation report={report} onReset={() => {}} />);
  await userEvent.click(screen.getByRole("link", { name: "Inspect source 2" }));
  expect(
    screen.getByText("[2] Verified test reference").closest("details"),
  ).toHaveAttribute("open");
});
it("positions marker from the numeric domain and actual range", () => {
  const g = rangeGeometry(parameter)!;
  expect(g.marker).toBeLessThan(g.lowPosition);
  expect(g.lowPosition).toBeLessThan(g.highPosition);
  const middle = rangeGeometry({
    ...parameter,
    value: "14",
    status: "within_range",
  })!;
  expect(middle.marker).toBe(50);
  const extreme = rangeGeometry({
    ...parameter,
    value: "1000",
    status: "above_range",
  })!;
  expect(extreme.marker).toBeGreaterThan(extreme.highPosition);
  expect(extreme.marker).toBeLessThan(100);
});
it.each([
  { reference_range: null },
  { reference_range: "<16" },
  { unit: null },
  { reference_range: "12-16 mg/dL" },
  { value: "positive" },
  { uncertain: true },
  { status: "indeterminate" as const },
])("uses textual fallback for unsafe numeric comparisons %j", (override) => {
  expect(rangeGeometry({ ...parameter, ...override })).toBeNull();
});
it("sorts out-of-range cards before within and indeterminate", () => {
  render(
    <ReportPresentation
      report={{
        ...report,
        tests: [
          { ...parameter, name: "Within", status: "within_range" },
          { ...parameter, name: "Unknown", status: "indeterminate" },
          parameter,
        ],
      }}
      onReset={() => {}}
    />,
  );
  expect(
    screen.getAllByRole("heading", { level: 4 }).map((h) => h.textContent),
  ).toEqual(["Hemoglobin", "Within", "Unknown"]);
});
