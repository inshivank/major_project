import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReportAnalyzer } from "./ReportAnalyzer";
import { analyze, safeUrl, validateFile } from "./api";
const limits = {
  max_bytes: 10485760,
  formats: ["pdf", "png", "jpg", "jpeg"],
  timeout_seconds: 150,
};
const report = {
  agent: "medical_report",
  status: "partial",
  report_type: "CBC",
  metadata: { page_count: 1, extracted_pages: [1] },
  tests: [
    {
      name: "Hemoglobin",
      original_label: "Hb",
      value: "10",
      unit: "g/dL",
      reference_range: "12-16",
      status: "below_range",
      source_page: 1,
      uncertain: false,
      warnings: [],
    },
  ],
  summary: "Synthetic local summary [1]",
  warnings: ["Consent absent"],
  sources: [{ type: "record", title: "Uploaded report, page 1" }],
  disclaimer: "Educational only",
  external_llm_used: false,
};
function response(data: unknown, status = 200) {
  return { ok: status === 200, status, json: async () => data } as Response;
}
function mockApi() {
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (url) =>
      String(url).endsWith("/config")
        ? response({ report_upload: limits })
        : response(report),
    );
}
async function open() {
  const user = userEvent.setup();
  await user.click(
    screen.getByRole("button", { name: /Medical Report Analysis/ }),
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Browse file" })).toBeEnabled(),
  );
  return user;
}
it("opens, closes, restores focus and reopens retained selection", async () => {
  mockApi();
  render(<ReportAnalyzer />);
  const user = await open();
  await user.upload(
    screen.getByLabelText("Medical report file"),
    new File(["synthetic"], "cbc.pdf", { type: "application/pdf" }),
  );
  await user.click(screen.getByLabelText("Close Medical Report Analysis"));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: /Medical Report Analysis/ }),
  ).toHaveFocus();
  await open();
  expect(screen.getByText("cbc.pdf")).toBeInTheDocument();
});
it("minimizes and handles Escape", async () => {
  mockApi();
  render(<ReportAnalyzer />);
  const user = await open();
  await user.click(screen.getByLabelText("Minimize Medical Report Analysis"));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await open();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
it("sends exact multipart fields and renders low result, summary, citations and reset", async () => {
  const fetcher = mockApi();
  render(<ReportAnalyzer />);
  const user = await open();
  await user.upload(
    screen.getByLabelText("Medical report file"),
    new File(["synthetic"], "cbc.pdf", { type: "application/pdf" }),
  );
  await user.click(screen.getByRole("button", { name: "Analyze Report →" }));
  await screen.findByText("Hemoglobin");
  const request = fetcher.mock.calls.find(([url]) =>
    String(url).endsWith("/reports/analyze"),
  )!;
  const form = request[1]?.body as FormData;
  expect(form.get("external_llm_consent")).toBe("false");
  expect(form.get("file")).toBeInstanceOf(File);
  expect(new Headers(request[1]?.headers).has("Content-Type")).toBe(false);
  expect(screen.getByText("Below stated range")).toBeInTheDocument();
  expect(screen.getByText("Local analysis summary")).toBeInTheDocument();
  expect(screen.getByText("[1] Uploaded report, page 1")).toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: "Analyze another report" }),
  );
  expect(screen.queryByText("Hemoglobin")).not.toBeInTheDocument();
  expect(screen.getByRole("checkbox")).not.toBeChecked();
});
it("requires explicit opt-in and displays safe server errors", async () => {
  const fetcher = mockApi();
  fetcher.mockImplementation(async (url) =>
    String(url).endsWith("/config")
      ? response({ report_upload: limits })
      : response(
          { detail: { code: "unsafe_pdf", message: "private traceback" } },
          422,
        ),
  );
  render(<ReportAnalyzer />);
  const user = await open();
  await user.upload(
    screen.getByLabelText("Medical report file"),
    new File(["x"], "cbc.pdf"),
  );
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "Analyze Report →" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "unsupported attachments",
  );
  expect(screen.queryByText("private traceback")).not.toBeInTheDocument();
  const request = fetcher.mock.calls.find(([url]) =>
    String(url).endsWith("/reports/analyze"),
  )!;
  expect((request[1]?.body as FormData).get("external_llm_consent")).toBe(
    "true",
  );
});
it("blocks duplicate requests and retains loading while minimized", async () => {
  const fetcher = mockApi();
  fetcher.mockImplementation(async (url) =>
    String(url).endsWith("/config")
      ? response({ report_upload: limits })
      : new Promise(() => {}),
  );
  render(<ReportAnalyzer />);
  const user = await open();
  await user.upload(
    screen.getByLabelText("Medical report file"),
    new File(["x"], "cbc.pdf"),
  );
  await user.dblClick(screen.getByRole("button", { name: "Analyze Report →" }));
  expect(
    screen.getByRole("button", { name: "Analyzing report…" }),
  ).toBeDisabled();
  expect(
    fetcher.mock.calls.filter(([url]) =>
      String(url).endsWith("/reports/analyze"),
    ),
  ).toHaveLength(1);
  await user.click(screen.getByLabelText("Minimize Medical Report Analysis"));
  await user.click(
    screen.getByRole("button", { name: /Medical Report Analysis/ }),
  );
  expect(screen.getByRole("button", { name: "Browse file" })).toBeDisabled();
  expect(screen.getByText("Understanding your report")).toBeInTheDocument();
});
it("rejects dropped invalid files", async () => {
  mockApi();
  render(<ReportAnalyzer />);
  await open();
  fireEvent.drop(screen.getByText("Drop your report here").parentElement!, {
    dataTransfer: { files: [new File(["x"], "bad.exe")] },
  });
  expect(screen.getByRole("alert")).toHaveTextContent("Choose a PDF");
});
it("clears sensitive state on session identity change", async () => {
  mockApi();
  const view = render(<ReportAnalyzer sessionKey="one" />);
  const user = await open();
  await user.upload(
    screen.getByLabelText("Medical report file"),
    new File(["x"], "cbc.pdf"),
  );
  view.rerender(<ReportAnalyzer sessionKey="two" />);
  expect(screen.queryByText("cbc.pdf")).not.toBeInTheDocument();
});
it("enforces size and extension and rejects dangerous links", () => {
  expect(validateFile(new File(["x"], "x.exe"), limits)).toBeTruthy();
  expect(
    validateFile(new File(["xx"], "x.pdf"), { ...limits, max_bytes: 1 }),
  ).toBeTruthy();
  expect(validateFile(new File(["x"], "x.JPEG"), limits)).toBeNull();
  expect(safeUrl("javascript:alert(1)")).toBeUndefined();
});
it("rejects unexpected consent-enabled response", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    response({ ...report, external_llm_used: true }),
  );
  await expect(
    analyze(
      new File(["x"], "x.pdf"),
      false,
      limits,
      new AbortController().signal,
    ),
  ).rejects.toThrow("Unexpected consent state");
});
it("handles Escape after results are cleared", async () => {
  mockApi();
  render(<ReportAnalyzer />);
  const user = await open();
  await user.upload(
    screen.getByLabelText("Medical report file"),
    new File(["x"], "cbc.pdf"),
  );
  await user.click(screen.getByRole("button", { name: "Analyze Report →" }));
  await screen.findByText("Hemoglobin");
  await user.click(
    screen.getByRole("button", { name: "Analyze another report" }),
  );
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: /Medical Report Analysis/ }),
  ).toHaveFocus();
});
it("renders high, within-range, unknown statuses and real returned reference links", async () => {
  const fetcher = mockApi();
  fetcher.mockImplementation(async (url) =>
    String(url).endsWith("/config")
      ? response({ report_upload: limits })
      : response({
          ...report,
          external_llm_used: true,
          summary: "Synthetic public explanation [2]",
          tests: ["above_range", "within_range", "indeterminate"].map(
            (status, i) => ({
              ...report.tests[0],
              name: "Synthetic parameter " + i,
              status,
            }),
          ),
          sources: [
            ...report.sources,
            {
              type: "reference",
              title: "Synthetic reference",
              url: "https://example.org/source",
              snippet: "Synthetic evidence.",
            },
          ],
        }),
  );
  render(<ReportAnalyzer />);
  const user = await open();
  await user.upload(
    screen.getByLabelText("Medical report file"),
    new File(["x"], "cbc.pdf"),
  );
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "Analyze Report →" }));
  await screen.findByText("AI-assisted educational explanation");
  expect(screen.getByText("Above stated range")).toBeInTheDocument();
  expect(screen.getByText("Within stated range")).toBeInTheDocument();
  expect(screen.getAllByText("Indeterminate").length).toBeGreaterThan(0);
  await user.click(screen.getByText("Sources & citations (2)"));
  await user.click(screen.getByText("[2] Synthetic reference"));
  expect(screen.getByRole("link", { name: "Open source ↗" })).toHaveAttribute(
    "href",
    "https://example.org/source",
  );
});
it("maximizes, restores on Escape and preserves previous mode when minimized", async () => {
  mockApi();
  render(<ReportAnalyzer />);
  const user = await open();
  await user.click(screen.getByLabelText("Maximize Medical Report Analysis"));
  expect(screen.getByRole("dialog")).toHaveAttribute("aria-modal", "true");
  expect(document.body.style.overflow).toBe("hidden");
  await user.click(screen.getByLabelText("Minimize Medical Report Analysis"));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(document.body.style.overflow).not.toBe("hidden");
  await user.click(
    screen.getByRole("button", { name: "Medical Report Analysis" }),
  );
  expect(
    screen.getByLabelText("Restore Medical Report Analysis"),
  ).toBeInTheDocument();
  await user.keyboard("{Escape}");
  expect(screen.getByRole("dialog")).toHaveAttribute("aria-modal", "false");
  expect(document.body.style.overflow).not.toBe("hidden");
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
it("keeps file, consent and pending request across display modes without resubmitting", async () => {
  const fetcher = mockApi();
  let finish!: (value: Response) => void;
  fetcher.mockImplementation(async (url) =>
    String(url).endsWith("/config")
      ? response({ report_upload: limits })
      : new Promise((resolve) => {
          finish = resolve;
        }),
  );
  render(<ReportAnalyzer />);
  const user = await open();
  await user.upload(
    screen.getByLabelText("Medical report file"),
    new File(["x"], "cbc.pdf"),
  );
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "Analyze Report →" }));
  await user.click(screen.getByLabelText("Maximize Medical Report Analysis"));
  await user.click(screen.getByLabelText("Minimize Medical Report Analysis"));
  await user.click(
    screen.getByRole("button", { name: "Medical Report Analysis" }),
  );
  expect(screen.getByText("cbc.pdf")).toBeInTheDocument();
  expect(screen.getByRole("checkbox")).toBeChecked();
  expect(
    screen.getByRole("button", { name: "Analyzing report…" }),
  ).toBeDisabled();
  finish(response(report));
  await screen.findByText("Hemoglobin");
  await user.click(screen.getByLabelText("Restore Medical Report Analysis"));
  await user.click(screen.getByLabelText("Maximize Medical Report Analysis"));
  expect(screen.getByText("Hemoglobin")).toBeInTheDocument();
  expect(
    fetcher.mock.calls.filter(([url]) =>
      String(url).endsWith("/reports/analyze"),
    ),
  ).toHaveLength(1);
});
it("makes host content inert only while maximized and cleans up on unmount", async () => {
  mockApi();
  const view = render(
    <div>
      <button>Host action</button>
      <ReportAnalyzer />
    </div>,
  );
  const user = await open();
  await user.click(screen.getByLabelText("Maximize Medical Report Analysis"));
  expect(screen.getByRole("button", { name: "Host action" }).inert).toBe(true);
  await user.click(screen.getByLabelText("Restore Medical Report Analysis"));
  expect(screen.getByRole("button", { name: "Host action" }).inert).toBe(false);
  await user.click(screen.getByLabelText("Maximize Medical Report Analysis"));
  view.unmount();
  expect(document.body.style.overflow).not.toBe("hidden");
});
