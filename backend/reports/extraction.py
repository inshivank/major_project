"""Content validation and bounded, page-attributed extraction using PyMuPDF/Tesseract."""

import io
import re
import time
import warnings
from PIL import Image, ImageOps, UnidentifiedImageError
import pymupdf as fitz
import pytesseract
from backend.config.settings import Settings, settings
from backend.reports.errors import ReportError
from backend.reports.isolation import run_isolated
from backend.schemas.report import Extraction, Segment


class LocalOCR:
    def __init__(self, config: Settings):
        self.config = config

    def read(self, image: Image.Image, timeout: float) -> str:
        if self.config.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = self.config.tesseract_cmd
        # EXIF orientation for camera photos, OSD for sufficiently text-heavy scans.
        image = ImageOps.exif_transpose(image).convert("RGB")
        started = time.monotonic()
        try:
            try:
                orientation = pytesseract.image_to_osd(
                    image,
                    output_type=pytesseract.Output.DICT,
                    timeout=max(0.1, min(timeout / 3, 5)),
                )
                if orientation.get("orientation_conf", 0) >= 5 and orientation.get(
                    "rotate"
                ):
                    image = image.rotate(-orientation["rotate"], expand=True)
            except (pytesseract.TesseractError, RuntimeError):
                pass  # OSD is unreliable on short reports; retain original orientation.
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise RuntimeError("OCR timeout")
            return pytesseract.image_to_string(
                ImageOps.autocontrast(ImageOps.grayscale(image)),
                config="--psm 6",
                timeout=remaining,
            )
        except pytesseract.TesseractNotFoundError:
            raise ReportError(
                "ocr_unavailable",
                "Install Tesseract and configure TESSERACT_CMD for scanned documents.",
                503,
            ) from None
        except (pytesseract.TesseractError, RuntimeError):
            raise ReportError(
                "ocr_failed",
                "OCR failed or exceeded its time limit; use a clearer scan.",
            ) from None


class DocumentExtractor:
    def __init__(self, config: Settings = settings, ocr=None):
        self.config = config
        # Native diagnostics can contain fragments of untrusted document data.
        fitz.TOOLS.mupdf_display_errors(False)
        fitz.TOOLS.mupdf_display_warnings(False)
        self.ocr = ocr if ocr is not None else LocalOCR(config)

    def extract(self, data: bytes) -> Extraction:
        if not data:
            raise ReportError("empty_file", "The uploaded file is empty.")
        if len(data) > self.config.report_max_upload_bytes:
            raise ReportError(
                "file_too_large", "The document exceeds the upload limit.", 413
            )
        deadline = time.monotonic() + self.config.report_processing_timeout_seconds
        if data.startswith(b"%PDF-"):
            return self._pdf(data, deadline)
        if data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff"):
            return self._image(data, deadline)
        raise ReportError(
            "unsupported_file",
            "Only valid PDF, PNG, and JPEG content is supported.",
            415,
        )

    def _remaining(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ReportError(
                "processing_timeout",
                "Document processing exceeded its time limit.",
                504,
            )
        return min(remaining, self.config.report_ocr_timeout_seconds)

    def _ocr(self, image, page, deadline):
        text = self.ocr.read(image, timeout=self._remaining(deadline)).strip()
        if not text:
            raise ReportError(
                "empty_extraction", "No readable text could be extracted."
            )
        # OCR numbers cannot be trusted without verification, even if engine confidence is high.
        return Segment(page=page, text=text, method="ocr", uncertain=True)

    def _check_pixels(self, width, height):
        if (
            width <= 0
            or height <= 0
            or width * height > self.config.report_max_image_pixels
        ):
            raise ReportError(
                "image_too_large", "Image dimensions exceed the processing limit.", 413
            )

    def _image(self, data, deadline):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as image:
                    self._check_pixels(*image.size)
                    if (
                        image.format not in ("PNG", "JPEG")
                        or getattr(image, "n_frames", 1) != 1
                    ):
                        raise ReportError(
                            "unsupported_file",
                            "Animated or unsupported images are not accepted.",
                            415,
                        )
                    image.verify()
                with Image.open(io.BytesIO(data)) as image:
                    segment = self._ocr(image, 1, deadline)
        except (
            UnidentifiedImageError,
            OSError,
            SyntaxError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ):
            raise ReportError(
                "corrupt_image", "Image content is corrupt or unsafe."
            ) from None
        self._check_text(segment.text)
        return Extraction(
            segments=[segment],
            page_count=1,
            warnings=["OCR text requires verification against the original document."],
        )

    def _check_text(self, text):
        if len(text) > self.config.report_max_text_chars:
            raise ReportError(
                "text_limit", "Extracted text exceeds the processing limit.", 413
            )

    def _pdf(self, data, deadline):
        try:
            document = fitz.open(stream=data, filetype="pdf")
        except Exception:
            raise ReportError("corrupt_pdf", "The PDF cannot be opened.") from None
        with document:
            if (
                document.needs_pass
                or document.is_encrypted
                or (document.metadata or {}).get("encryption")
            ):
                raise ReportError("encrypted_pdf", "Encrypted PDFs are not supported.")
            if document.is_repaired:
                raise ReportError(
                    "corrupt_pdf", "Damaged PDFs that require repair are not accepted."
                )
            if not 1 <= len(document) <= self.config.report_max_pdf_pages:
                raise ReportError(
                    "page_limit", "PDF page count is outside the allowed limit.", 413
                )
            # Do not execute or retain embedded files, actions, or scripts.
            if document.embfile_count() or any(
                token in data
                for token in (b"/JavaScript", b"/JS", b"/Launch", b"/OpenAction")
            ):
                raise ReportError(
                    "unsafe_pdf",
                    "PDF attachments and active content are not supported.",
                )
            if document.xref_length() > 20000:
                raise ReportError(
                    "unsafe_pdf", "PDF object count exceeds the processing limit.", 413
                )
            for xref in range(1, document.xref_length()):
                self._remaining(deadline)
                obj = document.xref_object(xref)
                # Decode PDF name escapes before checking actions inside compressed object streams.

                obj = re.sub(r"#([0-9a-fA-F]{2})", lambda m: chr(int(m[1], 16)), obj)
                if re.search(
                    r"/(?:JavaScript|JS|Launch|OpenAction|AA|RichMedia|EmbeddedFile)\b",
                    obj,
                ):
                    raise ReportError(
                        "unsafe_pdf", "PDF active content is not supported."
                    )
            result = Extraction(page_count=len(document))
            total = 0
            for index, page in enumerate(document, 1):
                self._remaining(deadline)
                try:
                    # word coordinates reconstruct same-row table cells while retaining page origin.
                    words = page.get_text("words", sort=True)
                    rows = []
                    for word in words:
                        if not rows or abs(word[1] - rows[-1][0]) > 3:
                            rows.append((word[1], [word[4]]))
                        else:
                            rows[-1][1].append(word[4])
                    text = "\n".join(" ".join(row[1]) for row in rows).strip()
                    if text:
                        segment = Segment(page=index, text=text)
                    else:
                        self._check_pixels(
                            int(page.rect.width * 2), int(page.rect.height * 2)
                        )
                        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                        with Image.frombytes(
                            "RGB", [pixmap.width, pixmap.height], pixmap.samples
                        ) as image:
                            segment = self._ocr(image, index, deadline)
                        result.warnings.append(
                            f"Page {index}: OCR text requires verification."
                        )
                    total += len(segment.text)
                    if total > self.config.report_max_text_chars:
                        raise ReportError(
                            "text_limit",
                            "Extracted text exceeds the processing limit.",
                            413,
                        )
                    result.segments.append(segment)
                except ReportError as exc:
                    if exc.status_code in (413, 504):
                        raise
                    result.warnings.append(f"Page {index}: {exc.code}.")
                except Exception:
                    result.warnings.append(f"Page {index}: extraction_failed.")
            if not result.segments:
                code = (
                    "ocr_unavailable"
                    if any("ocr_unavailable" in w for w in result.warnings)
                    else "empty_extraction"
                )
                raise ReportError(
                    code,
                    "No readable pages were extracted. Check scan quality and OCR installation.",
                    503 if code == "ocr_unavailable" else 422,
                )
            return result


def _extract_document(data, config):
    return DocumentExtractor(config).extract(data).model_dump()


class IsolatedExtractor:
    def __init__(self, config: Settings = settings):
        self.config = config

    def extract(self, data: bytes) -> Extraction:
        result = run_isolated(
            _extract_document,
            (data, self.config),
            self.config.report_processing_timeout_seconds,
            self.config.report_worker_memory_mb,
        )
        return Extraction.model_validate(result)
