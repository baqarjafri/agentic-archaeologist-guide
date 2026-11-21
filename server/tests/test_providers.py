import asyncio
import base64
import json
from types import SimpleNamespace

import httpx
import pytest

from app.config import load_settings
import app.guide.llm as llm_module
from app.guide.llm import LLMError, OpenAICompatLLM, make_llm
from app.guide.socket import WARM_EVERY
from app.guide.tts import ElevenLabsTTS, GeminiTTS, POOL, SilentTTS, TTSError, make_tts


def mock_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_make_tts_picks_the_provider():
    assert isinstance(make_tts(load_settings({"TTS_PROVIDER": "silent"})), SilentTTS)
    assert isinstance(make_tts(load_settings({"TTS_PROVIDER": "gemini"})), GeminiTTS)
    with pytest.raises(ValueError):
        make_tts(load_settings({"TTS_PROVIDER": "nope"}))


class FakeCompletions:
    def __init__(self, pieces):
        self.pieces = pieces
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs

        async def chunks():
            for piece in self.pieces:
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=piece))])
            yield SimpleNamespace(choices=[])

        return chunks()


async def test_llm_streams_text_and_sends_reasoning_effort():
    completions = FakeCompletions(["Hello ", "there."])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    llm = OpenAICompatLLM("https://x/", "k", "gemini-3.5-flash-lite", reasoning_effort="minimal", client=client)
    assert [p async for p in llm.stream([{"role": "user", "content": "hi"}])] == ["Hello ", "there."]
    assert completions.kwargs["model"] == "gemini-3.5-flash-lite"
    assert completions.kwargs["stream"] is True
    assert completions.kwargs["reasoning_effort"] == "minimal"


def test_reasoning_effort_is_omitted_when_unset():
    llm = OpenAICompatLLM("https://x/", "k", "m", reasoning_effort=None, client=SimpleNamespace())
    assert "reasoning_effort" not in llm.request([])


async def test_make_llm_builds_without_a_key_and_fails_clearly_on_first_use():
    llm = make_llm(load_settings({}))
    with pytest.raises(LLMError, match="no language-model key"):
        [p async for p in llm.stream([{"role": "user", "content": "hi"}])]


async def test_an_empty_reply_is_an_error():
    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions([])))
    llm = OpenAICompatLLM("https://x/", "k", "m", client=client)
    with pytest.raises(LLMError, match="no text"):
        [p async for p in llm.stream([])]


async def test_stopping_early_closes_the_model_stream():
    closed = []

    class Completions:
        async def create(self, **kwargs):
            async def chunks():
                try:
                    for piece in ["One. ", "Two. ", "Three."]:
                        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=piece), finish_reason=None)])
                finally:
                    closed.append(True)
            return chunks()

    llm = OpenAICompatLLM("https://x/", "k", "m", client=SimpleNamespace(chat=SimpleNamespace(completions=Completions())))
    deltas = llm.stream([])
    assert await deltas.__anext__() == "One. "
    await deltas.aclose()
    assert closed == [True]


def test_make_tts_accepts_any_case_and_elevenlabs():
    assert isinstance(make_tts(load_settings({"TTS_PROVIDER": "Gemini"})), GeminiTTS)
    assert isinstance(make_tts(load_settings({"TTS_PROVIDER": "elevenlabs"})), ElevenLabsTTS)


async def test_a_model_that_never_starts_replying_is_an_error(monkeypatch):
    monkeypatch.setattr(llm_module, "START_TIMEOUT", 0.05)

    class Stuck:
        async def create(self, **kwargs):
            await asyncio.sleep(10)

    llm = OpenAICompatLLM("u", "k", "m", client=SimpleNamespace(chat=SimpleNamespace(completions=Stuck())))
    with pytest.raises(LLMError, match="did not start replying"):
        async for _ in llm.stream([]):
            pass


def test_make_llm_warns_when_the_key_is_missing(caplog):
    with caplog.at_level("WARNING", logger="app.llm"):
        make_llm(load_settings({}))
    assert "every turn will fail" in caplog.text


def sse(*chunks: bytes) -> str:
    """Gemini's streamed reply: one server-sent event per audio chunk."""
    events = []
    for chunk in chunks:
        part = {"inlineData": {"mimeType": "audio/L16;codec=pcm;rate=24000", "data": base64.b64encode(chunk).decode()}}
        events.append("data: " + json.dumps({"candidates": [{"content": {"parts": [part]}}]}) + "\r\n\r\n")
    return "".join(events)


def sse_response(*chunks: bytes) -> httpx.Response:
    return httpx.Response(200, text=sse(*chunks), headers={"content-type": "text/event-stream"})


async def collect(tts, text="x"):
    return [chunk async for chunk in tts.stream(text)]


async def test_gemini_tts_streams_the_documented_request():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["key"] = request.headers["x-goog-api-key"]
        seen["body"] = json.loads(request.content)
        return sse_response(b"\x01\x00\x02\x00", b"\x03\x00")

    tts = GeminiTTS("k", "gemini-3.8-flash-lite-tts", "Sulafat", client=mock_client(handler))
    assert await collect(tts, "Hello there.") == [b"\x01\x00\x02\x00", b"\x03\x00"]
    assert seen["url"] == ("https://generativelanguage.googleapis.com/v1beta/models/"
                           "gemini-3.8-flash-lite-tts:streamGenerateContent?alt=sse")
    assert seen["key"] == "k"
    assert seen["body"] == {
        "contents": [{"role": "user", "parts": [{"text": "Hello there."}]}],
        "generationConfig": {"responseModalities": ["AUDIO"],
                             "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Sulafat"}}}},
    }


async def test_gemini_tts_raises_on_http_errors():
    tts = GeminiTTS("k", "m", "v", client=mock_client(lambda r: httpx.Response(400, text="bad")))
    with pytest.raises(TTSError, match="400"):
        await collect(tts)


async def test_a_server_error_before_any_audio_is_retried_once():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503, text="busy") if len(calls) == 1 else sse_response(b"\x00\x00")

    assert await collect(GeminiTTS("k", "m", "v", client=mock_client(handler))) == [b"\x00\x00"]
    assert len(calls) == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429])
async def test_a_client_error_is_not_retried(status):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(status, text="refused")

    with pytest.raises(TTSError, match=str(status)):
        await collect(GeminiTTS("k", "m", "v", client=mock_client(handler)))
    assert len(calls) == 1


async def test_a_stream_that_breaks_after_audio_is_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, text=sse(b"\x01\x00") + "data: {not json\r\n\r\n")

    got = []
    with pytest.raises(ValueError):
        async for chunk in GeminiTTS("k", "m", "v", client=mock_client(handler)).stream("x"):
            got.append(chunk)
    assert got == [b"\x01\x00"] and len(calls) == 1


async def test_a_timeout_becomes_a_named_voice_error():
    def handler(request):
        raise httpx.ReadTimeout("", request=request)

    with pytest.raises(TTSError, match="ReadTimeout"):
        await collect(GeminiTTS("k", "m", "v", client=mock_client(handler)))


async def test_voice_streams_run_at_most_two_at_a_time():
    live, peak = 0, 0

    async def handler(request):
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.02)
        live -= 1
        return sse_response(b"\x00\x00")

    tts = GeminiTTS("k", "m", "v", client=mock_client(handler))
    await asyncio.gather(*(collect(tts) for _ in range(6)))
    assert peak == 2


async def test_gemini_warm_up_lists_one_model():
    seen = []

    def handler(request):
        seen.append((request.method, str(request.url), request.headers["x-goog-api-key"]))
        return httpx.Response(200, json={"models": []})

    await GeminiTTS("k", "m", "v", client=mock_client(handler)).warm()
    assert seen == [("GET", "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1", "k")]


async def test_elevenlabs_streams_pcm_in_whole_samples():
    seen = {}

    def handler(request):
        seen["url"] = request.url
        seen["key"] = request.headers["xi-api-key"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"\x01\x02\x03")

    tts = ElevenLabsTTS("k", "voice1", "eleven_flash_v2_5", client=mock_client(handler))
    assert await collect(tts, "Hi.") == [b"\x01\x02"]
    assert seen["url"].path == "/v1/text-to-speech/voice1/stream"
    assert seen["url"].params["output_format"] == "pcm_24000"
    assert seen["key"] == "k" and seen["body"] == {"text": "Hi.", "model_id": "eleven_flash_v2_5"}


async def test_silent_tts_streams_a_tenth_of_a_second():
    assert await collect(SilentTTS()) == [b"\x00\x00" * 2400]


async def test_llm_warm_up_lists_models():
    listed = []

    class Models:
        async def list(self):
            listed.append(True)

    await OpenAICompatLLM("u", "k", "m", client=SimpleNamespace(models=Models())).warm()
    assert listed == [True]


@pytest.mark.parametrize("event", [{"error": {"code": 500, "message": "Internal"}},
                                   {"candidates": [{"finishReason": "OTHER", "index": 0}]}])
async def test_a_stream_with_no_audio_is_an_error_retried_once(event):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, text="data: " + json.dumps(event) + "\r\n\r\n")

    with pytest.raises(TTSError):
        await collect(GeminiTTS("k", "m", "v", client=mock_client(handler)))
    assert len(calls) == 2


async def test_an_error_event_after_audio_raises_without_a_retry():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, text=sse(b"\x01\x00") + 'data: {"error": {"code": 503, "message": "x"}}\r\n\r\n')

    got = []
    with pytest.raises(TTSError, match="503"):
        async for chunk in GeminiTTS("k", "m", "v", client=mock_client(handler)).stream("x"):
            got.append(chunk)
    assert got == [b"\x01\x00"] and len(calls) == 1


async def test_a_blocked_prompt_is_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, text='data: {"promptFeedback": {"blockReason": "SAFETY"}}\r\n\r\n')

    with pytest.raises(TTSError, match="SAFETY"):
        await collect(GeminiTTS("k", "m", "v", client=mock_client(handler)))
    assert len(calls) == 1


def test_the_warmed_connection_outlives_the_warm_up_interval():
    assert POOL.keepalive_expiry > WARM_EVERY


async def test_a_warm_up_with_a_bad_key_fails_loudly():
    with pytest.raises(httpx.HTTPStatusError):
        await GeminiTTS("k", "m", "v", client=mock_client(lambda r: httpx.Response(401))).warm()


def model_of(request):
    return request.url.path.split("/")[-1].split(":")[0]


async def test_a_model_at_its_minute_limit_hands_the_sentence_to_the_next():
    seen = []

    def handler(request):
        seen.append(model_of(request))
        if model_of(request) == "fast":
            return httpx.Response(429, json={"error": {"code": 429, "message": "quota"}})
        return sse_response(b"\x01\x00")

    tts = GeminiTTS("k", "fast", "v", client=mock_client(handler), fallbacks=("spare",))
    assert await collect(tts) == [b"\x01\x00"]
    assert await collect(tts) == [b"\x01\x00"]
    assert seen == ["fast", "spare", "spare"]  # a model that hit its limit rests for the rest of the minute


async def test_the_per_minute_count_spreads_sentences_across_models():
    seen = []

    def handler(request):
        seen.append(model_of(request))
        return sse_response(b"\x00\x00")

    tts = GeminiTTS("k", "fast", "v", client=mock_client(handler), fallbacks=("spare",), per_minute=2)
    for _ in range(4):
        await collect(tts)
    assert seen == ["fast", "fast", "spare", "spare"]
    with pytest.raises(TTSError, match="every voice model"):
        await collect(tts)
    assert len(seen) == 4  # nothing is sent once every model's minute is used up


def test_settings_list_the_fallback_voice_models():
    s = load_settings({})
    assert s.gemini_tts_fallbacks == ("gemini-3.8-flash-tts", "gemini-3.1-flash-tts-preview", "gemini-2.5-flash-preview-tts")
    assert s.gemini_tts_per_minute == 10
    assert load_settings({"GEMINI_TTS_FALLBACKS": " a , b ,", "GEMINI_TTS_PER_MINUTE": "5"}).gemini_tts_fallbacks == ("a", "b")
