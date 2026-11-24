"""Generate clearly labelled synthetic reports and inert PDF security fixtures."""

from __future__ import annotations
import argparse
import io
import os
from pathlib import Path
import pymupdf as fitz
from PIL import Image, ImageDraw, ImageFont

ROWS = (
    ("Hemoglobin", "10.0", "g/dL", "12.0-16.0 g/dL"),
    ("WBC", "12000", "cells/uL", "4000-11000 cells/uL"),
    ("Platelet Count", "250000", "cells/uL", "150000-450000 cells/uL"),
)
TEXT = "SYNTHETIC TEST DATA - NOT A PATIENT RECORD\n\n" + "\n".join(
    " ".join(row) for row in ROWS
)
TOKENS = "/JavaScript /JS /Launch /OpenAction /AA /RichMedia /EmbeddedFile"


def _document():
    document = fitz.open()
    document.new_page().insert_text((35, 55), TEXT, fontsize=11)
    return document


def _escaped_pdf():
    # Correct classic xref offsets preserve literal escaped name bytes in the fixture.
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R /Synthetic 4 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>",
        b"<< /S /J#61vaScript /J#53 (void\\(0\\);) >>",
    ]
    data = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    start = len(data)
    data.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010} 00000 n \n".encode())
    data.extend(
        f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    )
    return bytes(data)


def build_fixtures() -> dict[str, bytes]:
    fixtures = {}
    with _document() as doc:
        fixtures["cbc_text.pdf"] = doc.tobytes()
        doc.set_metadata(
            {
                "title": "Synthetic " + TOKENS,
                "subject": "Harmless metadata; never executable",
            }
        )
        fixtures["safe_keyword_metadata.pdf"] = doc.tobytes()
    with _document() as doc:
        doc.update_stream(
            doc[0].get_contents()[0],
            b"BT /helv 12 Tf 35 55 Td (/JavaScript /JS /Launch /OpenAction) Tj ET\n",
            compress=False,
        )
        fixtures["safe_keyword_text.pdf"] = doc.tobytes()
    with _document() as doc:
        doc.xref_set_key(
            doc.pdf_catalog(), "JS-Documentation", "(Synthetic unknown metadata key)"
        )
        fixtures["safe_name_prefix.pdf"] = doc.tobytes()
    with _document() as doc:
        doc.xref_set_key(
            doc.pdf_catalog(),
            "SyntheticNote",
            "(Nested \\(example\\) /JS and /JavaScript)",
        )
        fixtures["safe_nested_string.pdf"] = doc.tobytes()
    with _document() as doc:
        doc.xref_set_key(
            doc.pdf_catalog(),
            "SyntheticNote",
            "<" + ("Harmless " + TOKENS).encode().hex() + ">",
        )
        fixtures["safe_hex_string.pdf"] = doc.tobytes()
    font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf"
    font = (
        ImageFont.truetype(str(font_path), 40)
        if font_path.exists()
        else ImageFont.load_default(size=40)
    )
    with Image.new("RGB", (2200, 600), "white") as image:
        ImageDraw.Draw(image).multiline_text(
            (45, 45), TEXT, font=font, fill="black", spacing=25
        )
        for extension, format in [("png", "PNG"), ("jpg", "JPEG")]:
            buffer = io.BytesIO()
            image.save(
                buffer,
                format=format,
                **({"quality": 95, "subsampling": 0} if format == "JPEG" else {}),
            )
            fixtures["cbc." + extension] = buffer.getvalue()
    with fitz.open() as doc:
        page = doc.new_page(width=1100, height=300)
        page.insert_image(page.rect, stream=fixtures["cbc.png"])
        fixtures["cbc_scanned.pdf"] = doc.tobytes(deflate=True)
    with _document() as doc:
        doc.embfile_add("synthetic.txt", b"SYNTHETIC INERT TEST DATA")
        fixtures["unsafe_attachment.pdf"] = doc.tobytes()
    entries = {
        "javascript": ("SyntheticAction", "<< /S /JavaScript /JS (void\\(0\\);) >>"),
        "launch": (
            "SyntheticAction",
            "<< /S /Launch /F (SYNTHETIC_DO_NOT_EXECUTE.bin) >>",
        ),
        "automatic": ("OpenAction", "[4 0 R /Fit]"),
        "additional": ("AA", "<< /O << /S /JavaScript /JS (void\\(0\\);) >> >>"),
        "rich_media": ("Synthetic", "<< /Subtype /RichMedia >>"),
        "embedded_object": ("Synthetic", "<< /Type /EmbeddedFile >>"),
    }
    for name, (key, value) in entries.items():
        with _document() as doc:
            doc.xref_set_key(doc.pdf_catalog(), key, value)
            fixtures["unsafe_" + name + ".pdf"] = doc.tobytes()
    fixtures["unsafe_escaped.pdf"] = _escaped_pdf()
    with fitz.open(stream=_escaped_pdf(), filetype="pdf") as doc:
        fixtures["unsafe_compressed.pdf"] = doc.tobytes(use_objstms=1, deflate=True)
    with _document() as doc:
        fixtures["encrypted.pdf"] = doc.tobytes(
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="synthetic-owner",
            user_pw="synthetic-test",
        )
    fixtures["corrupt.pdf"] = b"%PDF-1.7\nSYNTHETIC CORRUPT TEST DATA"
    fixtures["unsupported.txt"] = (
        b"SYNTHETIC TEST DATA: this is not a medical document."
    )
    return fixtures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("tests/fixtures/reports"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    fixtures = build_fixtures()
    for name, data in fixtures.items():
        (args.output / name).write_bytes(data)
    print(
        f"Generated {len(fixtures)} synthetic-only fixtures in {args.output.resolve()}"
    )


if __name__ == "__main__":
    main()
