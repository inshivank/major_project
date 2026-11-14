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
    groq_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "llama-3.3-70b-versatile"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 1024
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

    disclaimer: str = (
        "This is AI-generated decision support for research and education. "
        "It is not a diagnosis or a prescription. Always consult a qualified "
        "clinician for medical advice."
    )


settings = Settings()
