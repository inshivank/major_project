"""Environment-backed application configuration."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com"
    llm_model: str = "openai/gpt-oss-20b"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 2048
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 3

    corpus_dir: Path = PROJECT_ROOT / "data" / "corpus"
    chroma_dir: Path = PROJECT_ROOT / "data" / "chroma"
    collection_name: str = "corecare_medical"
    retrieval_top_k: int = 4
    chunk_size: int = 800
    chunk_overlap: int = 100

    session_max_turns: int = 20
    session_max_sessions: int = 20

    report_upload_timeout_seconds: float = Field(default=30, gt=0, le=300)
    report_max_upload_bytes: int = Field(
        default=10 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024
    )
    report_max_pdf_pages: int = Field(default=10, ge=1, le=100)
    report_max_image_pixels: int = Field(default=20_000_000, ge=10000, le=50_000_000)
    report_max_text_chars: int = Field(default=100_000, ge=1000, le=1_000_000)
    report_ocr_timeout_seconds: float = Field(default=15, gt=0, le=120)
    report_processing_timeout_seconds: float = Field(default=120, gt=0, le=600)
    report_max_concurrent: int = Field(default=2, ge=1, le=8)
    report_worker_memory_mb: int = Field(default=512, ge=128, le=4096)
    tesseract_cmd: str = ""

    disclaimer: str = (
        "This is AI-generated decision support for research and education. "
        "It is not a diagnosis or a prescription. Always consult a qualified "
        "clinician for medical advice."
    )


settings = Settings()
