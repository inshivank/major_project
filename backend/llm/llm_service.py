"""Groq-backed LLM service with retries and JSON helpers."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Sequence
from typing import Any

from groq import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    Groq,
    InternalServerError,
    RateLimitError,
)

from backend.config.settings import settings

logger = logging.getLogger(__name__)

Message = dict[str, str]

RETRYABLE_ERRORS = (
    RateLimitError,
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
)


class LLMError(RuntimeError):
    """Safe provider failure; vendor bodies and credentials are never exposed."""

    def __init__(
        self,
        message: str,
        code: str = "llm_unavailable",
        status_code: int | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class LLMService:
    """Thin, testable wrapper around the Groq chat completions API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        client: Any | None = None,
        sleep=time.sleep,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.groq_api_key
        self.model = model or settings.llm_model
        self.base_url = base_url or settings.groq_base_url
        self.temperature = (
            settings.llm_temperature if temperature is None else temperature
        )
        self.max_tokens = max_tokens or settings.llm_max_tokens
        self.timeout = timeout or settings.llm_timeout_seconds
        self.max_retries = max(1, max_retries or settings.llm_max_retries)
        self._client = client
        self._sleep = sleep

    @property
    def available(self) -> bool:
        return bool(self.api_key) or self._client is not None

    @property
    def client(self) -> Any:
        if self._client is None:
            if not self.api_key:
                raise LLMError(
                    "GROQ_API_KEY is not configured. Add it to .env to enable "
                    "the LLM service."
                )
            # Groq 1.7 resources include /openai/v1 in their request paths.
            # Accept legacy OpenAI-style environment values without doubling that prefix.
            sdk_base_url = self.base_url.rstrip("/")
            if sdk_base_url.endswith("/openai/v1"):
                sdk_base_url = sdk_base_url[: -len("/openai/v1")]
            self._client = Groq(
                api_key=self.api_key,
                base_url=sdk_base_url,
                timeout=self.timeout,
                max_retries=0,
            )
        return self._client

    def complete(
        self,
        messages: Sequence[Message],
        temperature: float | None = None,
        max_tokens: int | None = None,
        deadline: float | None = None,
    ) -> str:
        payload = [dict(message) for message in messages]

        for attempt in range(1, self.max_retries + 1):
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                raise LLMError("LLM deadline exceeded.")
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=payload,
                    temperature=(
                        self.temperature if temperature is None else temperature
                    ),
                    max_tokens=max_tokens or self.max_tokens,
                    **(
                        {"reasoning_effort": "low", "include_reasoning": False}
                        if self.model.startswith("openai/gpt-oss-")
                        else {}
                    ),
                    **(
                        {"timeout": min(self.timeout, remaining)}
                        if remaining is not None
                        else {}
                    ),
                )
            except AuthenticationError as exc:
                raise LLMError(
                    "Groq authentication failed. Check GROQ_API_KEY.",
                    code="llm_authentication",
                    status_code=401,
                ) from exc
            except BadRequestError as exc:
                raise LLMError(
                    "Groq rejected the request.",
                    code="llm_bad_request",
                    status_code=400,
                ) from exc
            except RETRYABLE_ERRORS as exc:
                if attempt >= self.max_retries:
                    break
                delay = 2 ** (attempt - 1)
                logger.warning(
                    "Groq request failed (attempt %s/%s), retrying in %ss: %s",
                    attempt,
                    self.max_retries,
                    delay,
                    type(exc).__name__,
                )
                if deadline is not None and time.monotonic() + delay >= deadline:
                    raise LLMError("LLM deadline exceeded.") from None
                self._sleep(delay)
            except APIStatusError as exc:
                if exc.status_code == 404:
                    raise LLMError(
                        "Groq endpoint or model not found. Check GROQ_BASE_URL and LLM_MODEL.",
                        code="llm_not_found",
                        status_code=404,
                    ) from exc
                raise LLMError(
                    "Groq API request was rejected.",
                    code="llm_api_error",
                    status_code=exc.status_code,
                ) from exc
            else:
                if getattr(response.choices[0], "finish_reason", None) == "length":
                    raise LLMError(
                        "Groq completion exceeded its token budget. Increase LLM_MAX_TOKENS.",
                        code="llm_token_limit",
                    )
                content = response.choices[0].message.content
                if not content or not content.strip():
                    raise LLMError("Groq returned an empty response.")
                usage = getattr(response, "usage", None)
                logger.info(
                    "llm model=%s prompt_tokens=%s completion_tokens=%s",
                    self.model,
                    getattr(usage, "prompt_tokens", None),
                    getattr(usage, "completion_tokens", None),
                )
                return content.strip()

        raise LLMError(f"Groq request failed after {self.max_retries} attempts.")

    def complete_json(
        self,
        messages: Sequence[Message],
        max_tokens: int | None = None,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        budget = {"deadline": deadline} if deadline is not None else {}
        raw = self.complete(messages, temperature=0.0, max_tokens=max_tokens, **budget)
        try:
            return parse_json_object(raw)
        except ValueError:
            logger.info("LLM returned invalid JSON, requesting a repair.")

        repair = [
            *messages,
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": (
                    "Your previous reply was not valid JSON. Reply with the JSON "
                    "object only, with no prose and no markdown fences."
                ),
            },
        ]
        raw_retry = self.complete(
            repair, temperature=0.0, max_tokens=max_tokens, **budget
        )
        try:
            return parse_json_object(raw_retry)
        except ValueError as exc:
            raise LLMError("Groq did not return valid JSON.") from exc


def parse_json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object from an LLM response."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in response.")
    try:
        parsed = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON in response.") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Response JSON is not an object.")
    return parsed
