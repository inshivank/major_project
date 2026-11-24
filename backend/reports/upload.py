"""Enforce request limits before multipart parsing/spooling."""

from anyio import fail_after
from python_multipart.exceptions import MultipartParseError
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse
from backend.config.settings import settings
from backend.reports.errors import ReportError


async def read_upload(request) -> tuple[bytes, bool]:
    try:
        with fail_after(settings.report_upload_timeout_seconds):
            async with request.form(
                max_files=1, max_fields=1, max_part_size=1024
            ) as form:
                if (
                    set(form) - {"file", "external_llm_consent"}
                    or len(form.getlist("file")) != 1
                    or len(form.getlist("external_llm_consent")) > 1
                ):
                    raise ReportError(
                        "invalid_form",
                        "Provide one file and an optional external_llm_consent boolean.",
                    )
                upload = form.get("file")
                if not isinstance(upload, UploadFile):
                    raise ReportError("missing_file", "A document file is required.")
                raw_consent = form.get("external_llm_consent", "false")
                if raw_consent not in ("true", "false"):
                    raise ReportError(
                        "invalid_consent", "external_llm_consent must be true or false."
                    )
                data = await upload.read(settings.report_max_upload_bytes + 1)
                if len(data) > settings.report_max_upload_bytes:
                    raise ReportError(
                        "file_too_large", "The document exceeds the upload limit.", 413
                    )
                # Filename and declared content type are deliberately ignored.
                return data, raw_consent == "true"
    except TimeoutError:
        raise ReportError(
            "upload_timeout", "Upload exceeded its time limit.", 408
        ) from None
    except (StarletteHTTPException, MultipartParseError):
        raise ReportError(
            "invalid_multipart", "Malformed multipart form or too many fields/files."
        ) from None


class ReportUploadLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") != "/reports/analyze":
            return await self.app(scope, receive, send)
        limit = settings.report_max_upload_bytes + 65536  # bounded multipart overhead
        headers = dict(scope.get("headers", []))
        try:
            length = int(headers.get(b"content-length", b"0"))
            if length < 0:
                raise ValueError
        except ValueError:
            return await JSONResponse(
                {
                    "detail": {
                        "code": "invalid_length",
                        "message": "Invalid request length.",
                    }
                },
                status_code=400,
            )(scope, receive, send)
        if length > limit:
            return await JSONResponse(
                {
                    "detail": {
                        "code": "file_too_large",
                        "message": "Upload exceeds the request limit.",
                    }
                },
                status_code=413,
            )(scope, receive, send)
        total = 0

        async def bounded_receive():
            nonlocal total
            message = await receive()
            total += len(message.get("body", b""))
            if total > limit:
                raise ReportError(
                    "file_too_large", "Upload exceeds the request limit.", 413
                )
            return message

        # Handled by the app's ReportError handler; multipart cleanup occurs in Starlette.
        await self.app(scope, bounded_receive, send)
