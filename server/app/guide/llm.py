"""Language model clients: any OpenAI-compatible chat API (Gemini, Claude, Ollama, vLLM)."""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any, Protocol

import httpx

from app.config import Settings

log = logging.getLogger("app.llm")
START_TIMEOUT = 25.0  # seconds for the model to start replying, retries included; the SDK would otherwise honour a 429's Retry-After for up to two minutes


class LLMError(RuntimeError):
    """The model could not produce a reply: no key, no text, or the provider refused."""


class LLMClient(Protocol):
    def stream(self, messages: list[dict]) -> AsyncGenerator[str, None]: ...

    async def warm(self) -> None: ...


@contextlib.asynccontextmanager
async def _closing(response: Any) -> AsyncIterator[Any]:
    """Close the provider's stream however iteration stops, a cancelled turn included, so no tokens run on unheard."""
    try:
        yield response
    finally:
        close = getattr(response, "aclose", None) or getattr(response, "close", None)
        if close is not None:
            await close()


class OpenAICompatLLM:
    def __init__(self, base_url: str, api_key: str, model: str, reasoning_effort: str | None = None,
                 temperature: float | None = None, max_tokens: int = 900, client: Any = None) -> None:
        self._base_url, self._api_key, self._client = base_url, api_key, client
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.temperature = temperature  # Gemini 3.5 Flash-Lite ignores it and later models refuse it, so it is off by default
        self.max_tokens = max_tokens

    def _sdk(self) -> Any:
        """Built on first use, so a server with no key still starts; the first turn then fails with a clear reason."""
        if self._client is None:
            if not self._api_key:
                raise LLMError("no language-model key: set GEMINI_API_KEY or LLM_API_KEY")
            from openai import AsyncOpenAI, DefaultAsyncHttpxClient

            self._client = AsyncOpenAI(
                base_url=self._base_url, api_key=self._api_key, timeout=20.0, max_retries=1,
                http_client=DefaultAsyncHttpxClient(limits=httpx.Limits(  # keeps the warmed connection for the first turn
                    max_connections=1000, max_keepalive_connections=100, keepalive_expiry=120.0)))
        return self._client

    def request(self, messages: list[dict]) -> dict:
        body: dict = {"model": self.model, "messages": messages, "stream": True, "max_tokens": self.max_tokens}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        return body

    async def warm(self) -> None:
        """Open the connection before the first turn needs it; listing models is free."""
        await self._sdk().models.list()

    async def stream(self, messages: list[dict]) -> AsyncGenerator[str, None]:
        try:
            async with asyncio.timeout(START_TIMEOUT):
                response = await self._sdk().chat.completions.create(**self.request(messages))
        except TimeoutError:
            raise LLMError(f"the model did not start replying within {START_TIMEOUT:g} s") from None
        produced, finish = False, None
        async with _closing(response):
            async for chunk in response:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                finish = getattr(choice, "finish_reason", None) or finish
                if choice.delta and choice.delta.content:
                    produced = True
                    yield choice.delta.content
        if finish not in (None, "stop"):
            log.warning("model stopped early: finish_reason=%s", finish)
        if not produced:
            raise LLMError(f"the model returned no text (finish_reason={finish})")


class FakeLLM:
    """Test double: yields the given chunks (optionally slowly) and remembers the last messages."""

    def __init__(self, chunks: list[str], delay: float = 0.0) -> None:
        self.chunks = chunks
        self.delay = delay
        self.last_messages: list[dict] | None = None

    async def stream(self, messages: list[dict]) -> AsyncGenerator[str, None]:
        self.last_messages = messages
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield chunk

    async def warm(self) -> None:
        return None


def make_llm(settings: Settings) -> OpenAICompatLLM:
    if not settings.llm_api_key:
        log.warning("LLM_API_KEY/GEMINI_API_KEY is empty: every turn will fail until a key is set")
    return OpenAICompatLLM(settings.llm_base_url, settings.llm_api_key, settings.llm_model, settings.llm_reasoning_effort)
