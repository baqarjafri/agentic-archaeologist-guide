"""Voices that stream: Gemini TTS, ElevenLabs, or silence for tests and text-only runs.

Every voice yields raw PCM audio (16-bit little-endian, 24 kHz, mono) chunk by chunk, so the phone can start
playing a sentence while the rest of it is still being made.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from typing import Any, Protocol

import httpx

from app.config import Settings

log = logging.getLogger("app.tts")
AUDIO_FORMAT = "pcm_s16le_24000_mono"  # what every voice yields; the phone is told this in turn_started
TTS_TIMEOUT = httpx.Timeout(10.0, connect=3.0, read=5.0)  # first audio comes in under 1 s; a stalled stream must not hold back the turn for long
RETRY_STATUS = frozenset({500, 502, 503, 504})
MAX_PARALLEL = 2  # voice streams in flight per process, shared by all sessions; smooths bursts but does not cap requests per minute
POOL = httpx.Limits(max_keepalive_connections=MAX_PARALLEL, keepalive_expiry=120.0)  # keeps the warmed connection for the visitor's first turn
RPM_WINDOW = 60.0  # seconds: Gemini counts voice requests per model per minute


class TTSError(RuntimeError):
    def __init__(self, message: str, retry: bool = False, status: int | None = None) -> None:
        super().__init__(message)
        self.retry = retry
        self.status = status


class TTSClient(Protocol):
    def stream(self, text: str) -> AsyncIterator[bytes]: ...

    async def warm(self) -> None: ...


async def _check(response: httpx.Response, name: str) -> None:
    if response.status_code != 200:
        body = (await response.aread())[:200].decode("utf-8", "replace")
        raise TTSError(f"{name} {response.status_code}: {body}", retry=response.status_code in RETRY_STATUS,
                      status=response.status_code)


async def _sse_audio(client: httpx.AsyncClient, name: str, url: str, **kwargs: Any) -> AsyncIterator[bytes]:
    """The audio chunks in Gemini's server-sent events, as they arrive."""
    async with client.stream("POST", url, **kwargs) as response:
        await _check(response, name)
        audio, finish = False, None
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            event = json.loads(line[5:])
            if "error" in event:  # a failure after the 200 status arrives inside the stream
                error = event["error"]
                raise TTSError(f"{name} {error.get('code')}: {str(error.get('message', ''))[:200]}",
                               retry=error.get("code") in RETRY_STATUS, status=error.get("code"))
            finish = event.get("promptFeedback", {}).get("blockReason") or finish
            for candidate in event.get("candidates", []):
                finish = candidate.get("finishReason") or finish
                for part in candidate.get("content", {}).get("parts", []):
                    data = part.get("inlineData", {}).get("data")
                    if data:
                        audio = True
                        yield base64.b64decode(data)
        if not audio:  # nothing has been heard yet, so one more try costs the visitor nothing
            raise TTSError(f"{name} returned no audio (finish {finish})", retry=finish in (None, "STOP", "OTHER"))


async def _raw_audio(client: httpx.AsyncClient, name: str, url: str, **kwargs: Any) -> AsyncIterator[bytes]:
    """A raw PCM body in whole 16-bit samples, so the phone never splits a sample across two chunks."""
    async with client.stream("POST", url, **kwargs) as response:
        await _check(response, name)
        carry = b""
        async for chunk in response.aiter_bytes():
            data = carry + chunk
            cut = len(data) - len(data) % 2
            carry = data[cut:]
            if cut:
                yield data[:cut]


async def _with_one_retry(name: str, open_stream: Callable[[], AsyncIterator[bytes]]) -> AsyncIterator[bytes]:
    """Yield a stream, starting it once more if it fails before any audio; a 4xx (bad key, quota) is final."""
    for attempt in (1, 2):
        started = False
        try:
            async with contextlib.aclosing(open_stream()) as audio:  # closes the HTTP stream as soon as the consumer stops
                async for chunk in audio:
                    started = True
                    yield chunk
            return
        except TTSError as exc:
            if started or not exc.retry or attempt == 2:
                raise
            problem = str(exc)
        except httpx.TransportError as exc:  # a timeout's message is empty, so name its type
            if started or attempt == 2:
                raise TTSError(f"{name} {type(exc).__name__}") from exc
            problem = type(exc).__name__
        log.warning("%s attempt %d failed: %s", name, attempt, problem)
        await asyncio.sleep(0.3)


class GeminiTTS:
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse"
    MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1"

    def __init__(self, api_key: str, model: str, voice: str, client: httpx.AsyncClient | None = None,
                 fallbacks: tuple[str, ...] = (), per_minute: int = 10) -> None:
        self.api_key, self.model, self.voice = api_key, model, voice
        self.models = (model, *[m for m in fallbacks if m != model])  # best first; each has its own per-minute quota
        self.per_minute = per_minute
        self._sent: dict[str, deque[float]] = {m: deque() for m in self.models}  # request times in the last minute
        self._client = client or httpx.AsyncClient(timeout=TTS_TIMEOUT, limits=POOL)
        self._slots = asyncio.Semaphore(MAX_PARALLEL)

    def body(self, text: str) -> dict:
        # The plain sentence only: these models read a style instruction aloud and refuse a system instruction (10 Oct 2026).
        return {
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": self.voice}}}},
        }

    def _free(self) -> list[str]:
        """The models with room left in this minute's quota, best first."""
        now = time.monotonic()
        free = []
        for model in self.models:
            sent = self._sent[model]
            while sent and now - sent[0] >= RPM_WINDOW:
                sent.popleft()
            if len(sent) < self.per_minute:
                free.append(model)
        return free

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        async with self._slots:
            for model in self._free():
                self._sent[model].append(time.monotonic())
                opener = lambda m=model: _sse_audio(self._client, "Gemini TTS", self.URL.format(model=m),  # noqa: E731
                                                    headers={"x-goog-api-key": self.api_key}, json=self.body(text))
                started = False
                try:
                    async with contextlib.aclosing(_with_one_retry("Gemini TTS", opener)) as audio:
                        async for chunk in audio:
                            started = True
                            yield chunk
                    return
                except TTSError as exc:
                    if exc.status != 429 or started:
                        raise
                    self._sent[model].extend([time.monotonic()] * self.per_minute)  # rest it for the rest of the minute
                    log.warning("Gemini TTS %s is at its per-minute limit; voicing with the next model", model)
            raise TTSError("Gemini TTS 429: every voice model is at its per-minute limit", status=429)

    async def warm(self) -> None:
        """Open the connection before the first sentence needs it; listing a model is free."""
        (await self._client.get(self.MODELS_URL, headers={"x-goog-api-key": self.api_key})).raise_for_status()


class ElevenLabsTTS:
    URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
    MODELS_URL = "https://api.elevenlabs.io/v1/models"

    def __init__(self, api_key: str, voice_id: str, model: str, client: httpx.AsyncClient | None = None) -> None:
        self.api_key, self.voice_id, self.model = api_key, voice_id, model
        self._client = client or httpx.AsyncClient(timeout=TTS_TIMEOUT, limits=POOL)
        self._slots = asyncio.Semaphore(MAX_PARALLEL)

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        async with self._slots:
            opener = lambda: _raw_audio(self._client, "ElevenLabs", self.URL.format(voice_id=self.voice_id),  # noqa: E731
                                        params={"output_format": "pcm_24000"}, headers={"xi-api-key": self.api_key},
                                        json={"text": text, "model_id": self.model})
            async with contextlib.aclosing(_with_one_retry("ElevenLabs", opener)) as audio:
                async for chunk in audio:
                    yield chunk

    async def warm(self) -> None:
        (await self._client.get(self.MODELS_URL, headers={"xi-api-key": self.api_key})).raise_for_status()


class SilentTTS:
    async def stream(self, text: str) -> AsyncIterator[bytes]:
        yield b"\x00\x00" * 2400  # 0.1 s of silence

    async def warm(self) -> None:
        return None


def make_tts(settings: Settings) -> TTSClient:
    provider = settings.tts_provider.lower()
    keys = {"gemini": settings.gemini_api_key, "elevenlabs": settings.elevenlabs_api_key}
    if provider in keys and not keys[provider]:
        log.warning("TTS_PROVIDER=%s has no API key: every sentence will be captioned without a voice", provider)
    if provider == "gemini":
        return GeminiTTS(settings.gemini_api_key, settings.gemini_tts_model, settings.gemini_tts_voice,
                         fallbacks=settings.gemini_tts_fallbacks, per_minute=settings.gemini_tts_per_minute)
    if provider == "elevenlabs":
        return ElevenLabsTTS(settings.elevenlabs_api_key, settings.elevenlabs_voice_id, settings.elevenlabs_model)
    if provider == "silent":
        return SilentTTS()
    raise ValueError(f"unknown TTS_PROVIDER {settings.tts_provider!r}")
