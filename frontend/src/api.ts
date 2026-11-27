import { z } from "zod";
const source = z.object({
  type: z.enum(["record", "reference", "model"]),
  title: z.string(),
  url: z.string().nullable().optional(),
  snippet: z.string().nullable().optional(),
});
const cited = z.object({
  text: z.string(),
  citation_ids: z.array(z.number().int().positive()),
});
const structured = z.object({
  mode: z.enum(["local", "llm_assisted", "fallback"]),
  overall_summary: z.string(),
  parameter_explanations: z.array(
    z.object({
      parameter_id: z.string(),
      what_it_measures: z.array(cited),
      range_explanation: z.string(),
      citation_ids: z.array(z.number().int().positive()),
    }),
  ),
  educational_context: z.array(cited),
  doctor_discussion_questions: z.array(z.string()),
  limitations: z.array(z.string()),
  medical_disclaimer: z.string(),
  urgent_care_guidance: z.string(),
  citation_ids: z.array(z.number().int().positive()),
});
export const reportSchema = z.object({
  agent: z.literal("medical_report"),
  status: z.enum(["completed", "partial"]),
  report_type: z.string(),
  metadata: z.object({
    page_count: z.number(),
    extracted_pages: z.array(z.number()),
  }),
  tests: z.array(
    z.object({
      parameter_id: z.string().nullable().optional(),
      name: z.string(),
      original_label: z.string(),
      value: z.string().nullable(),
      unit: z.string().nullable(),
      reference_range: z.string().nullable(),
      status: z.enum([
        "below_range",
        "within_range",
        "above_range",
        "indeterminate",
      ]),
      source_page: z.number(),
      uncertain: z.boolean(),
      warnings: z.array(z.string()),
    }),
  ),
  explanation: structured.nullable().optional(),
  summary: z.string(),
  warnings: z.array(z.string()),
  sources: z.array(source),
  disclaimer: z.string(),
  external_llm_used: z.boolean(),
});
export type Report = z.infer<typeof reportSchema>;
const limitsSchema = z.object({
  report_upload: z.object({
    max_bytes: z.number().positive(),
    formats: z.array(z.string()),
    timeout_seconds: z.number().positive(),
  }),
});
export type Limits = z.infer<typeof limitsSchema>["report_upload"];
const base = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
export async function getLimits(signal: AbortSignal): Promise<Limits> {
  const r = await fetch(`${base}/config`, {
    signal,
    credentials: "same-origin",
  });
  if (!r.ok)
    throw new Error(
      "Upload settings unavailable. Retry when the server is online.",
    );
  return limitsSchema.parse(await r.json()).report_upload;
}
export function validateFile(file: File, limits: Limits): string | null {
  if (
    !limits.formats.some((ext) => file.name.toLowerCase().endsWith("." + ext))
  )
    return "Choose a PDF, PNG, JPG or JPEG report.";
  if (!file.size) return "The file is empty.";
  if (file.size > limits.max_bytes)
    return `File exceeds ${(limits.max_bytes / 1048576).toFixed(0)} MB.`;
  return null;
}
const errors: Record<string, string> = {
  unsafe_pdf:
    "This PDF contains unsupported attachments or active content. Export a plain report instead.",
  encrypted_pdf: "Remove PDF password protection before uploading.",
  corrupt_pdf: "The PDF is damaged. Upload a fresh copy.",
  unsupported_file: "Choose a valid PDF, PNG or JPEG.",
  file_too_large: "The file exceeds the server limit.",
  empty_extraction: "No readable text was found. Try a clearer scan.",
  ocr_unavailable:
    "Scan recognition is unavailable. Try a selectable-text PDF.",
  ocr_failed: "Scan recognition failed. Try a sharper image.",
  processing_timeout: "Analysis timed out. Try fewer pages.",
  report_busy: "The analyzer is busy. Please retry shortly.",
  page_limit: "This PDF contains too many pages.",
  image_too_large: "Image dimensions exceed the server limit.",
  text_limit: "The report contains too much text.",
  corrupt_image: "This image cannot be read.",
  empty_file: "Choose a nonempty file.",
  upload_timeout: "Upload timed out. Please retry.",
};
export async function analyze(
  file: File,
  consent: boolean,
  limits: Limits,
  signal: AbortSignal,
): Promise<Report> {
  const form = new FormData();
  form.append("file", file);
  form.append("external_llm_consent", String(consent));
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal.addEventListener("abort", abort, { once: true });
  if (signal.aborted) controller.abort();
  let expired = false;
  const timer = setTimeout(
    () => {
      expired = true;
      controller.abort();
    },
    (limits.timeout_seconds + 15) * 1000,
  );
  try {
    const r = await fetch(`${base}/reports/analyze`, {
      method: "POST",
      body: form,
      signal: controller.signal,
      credentials: "same-origin",
    });
    if (!r.ok) {
      let code = "";
      try {
        code = (await r.json()).detail?.code || "";
      } catch {
        /* Do not expose response bodies. */
      }
      throw new Error(
        errors[code] ||
          (r.status === 401 || r.status === 403
            ? "Your session is unavailable or access was denied."
            : r.status >= 500
              ? "The analysis service is unavailable. Please retry."
              : "Upload could not be accepted. Choose another report."),
      );
    }
    const report = reportSchema.parse(await r.json());
    if (!consent && report.external_llm_used)
      throw new Error("Unexpected consent state. Results were withheld.");
    return report;
  } catch (e) {
    if (expired) throw new Error("Analysis timed out. Please retry.");
    if (e instanceof TypeError)
      throw new Error(
        "Cannot reach CoreCare. Check your connection and retry.",
      );
    if (e instanceof z.ZodError)
      throw new Error(
        "The server returned an unsupported response. Please retry.",
      );
    throw e;
  } finally {
    clearTimeout(timer);
    signal.removeEventListener("abort", abort);
  }
}
export function safeUrl(value?: string | null) {
  try {
    const u = new URL(value || "");
    return ["https:", "http:"].includes(u.protocol) ? u.href : undefined;
  } catch {
    return undefined;
  }
}
