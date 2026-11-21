import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.guide.llm import FakeLLM
from app.guide.tts import SilentTTS
from app.main import create_app
from tests.helpers import ColourEmbedder

TURN = {"type": "turn", "kind": "tell", "object_id": "1.1", "visits": [{"object_id": "1.1", "time": "10:38"}]}


def client_for(settings, chunks):
    return TestClient(create_app(settings, embedder=ColourEmbedder(), llm=FakeLLM(chunks), tts=SilentTTS()))


def test_a_turn_streams_events_then_audio(settings_for):
    client = client_for(settings_for(), ["Alpha was carved in stone. [1.1#p1]"])
    with client.websocket_connect("/ws/session") as ws:
        ws.send_json(TURN)
        assert ws.receive_json()["type"] == "turn_started"
        assert ws.receive_json() == {"type": "sentence", "index": 0, "text": "Alpha was carved in stone.",
                                     "citations": ["1.1#p1"], "show": []}
        chunk = ws.receive_bytes()
        assert chunk[:5] == b"\x00\x00\x00\x00\x00" and len(chunk) == 5 + 4800
        assert ws.receive_bytes() == b"\x00\x00\x00\x00\x01"
        assert ws.receive_json()["type"] == "turn_done"


def test_bad_messages_get_errors(settings_for):
    with client_for(settings_for(), []).websocket_connect("/ws/session") as ws:
        ws.send_text("not json")
        assert ws.receive_json() == {"type": "error", "message": "invalid message"}
        ws.send_bytes(b"\x00\x01")
        assert ws.receive_json() == {"type": "error", "message": "invalid message"}
        ws.send_json({"type": "dance"})
        assert ws.receive_json() == {"type": "error", "message": "unknown message type"}
        ws.send_json({"type": "turn", "kind": "tell"})
        assert ws.receive_json() == {"type": "error", "message": "invalid turn"}
        ws.send_json({"type": "turn", "kind": "tell", "object_id": "nope"})
        assert ws.receive_json() == {"type": "error", "message": "unknown object"}


def test_the_socket_requires_the_code(settings_for):
    client = client_for(settings_for(ACCESS_CODES="secret"), [])
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect("/ws/session") as ws:
            ws.receive_json()
    assert refused.value.code == 4401
    with client.websocket_connect("/ws/session?code=secret") as ws:
        ws.send_json({"type": "dance"})
        assert ws.receive_json()["type"] == "error"


class SlowCloseLLM:
    """The first reply stalls after one sentence; closing a stream takes a moment, as the real SDK's HTTP close does."""

    def __init__(self):
        self.calls = 0

    async def stream(self, messages):
        self.calls += 1
        first = self.calls == 1
        try:
            if first:
                yield "Alpha was carved in stone. [1.1#p1] I"
                await asyncio.sleep(10)
            else:
                yield "Beta guarded a temple. [2.2#p1]"
        finally:
            await asyncio.sleep(0.1)


class EchoTTS:
    """Speaks the sentence's own words back as the audio; the first piece's voice lands while its stream is closing."""

    async def stream(self, text):
        await asyncio.sleep(0.05 if text.startswith("Alpha") else 0.2)
        yield text.encode()

    async def warm(self):
        return None


def read(ws):
    m = ws.receive()
    return m["bytes"] if m.get("bytes") is not None else json.loads(m["text"])


def test_a_new_turn_silences_the_old_one(settings_for):
    app = create_app(settings_for(), embedder=ColourEmbedder(), llm=SlowCloseLLM(), tts=EchoTTS())
    with TestClient(app).websocket_connect("/ws/session") as ws:
        ws.send_json(TURN)
        assert read(ws)["type"] == "turn_started"
        assert read(ws)["text"] == "Alpha was carved in stone."
        ws.send_json({**TURN, "object_id": "2.2", "visits": []})  # the visitor moves on while Alpha's voice is still coming
        while not (isinstance(e := read(ws), dict) and e["type"] == "turn_started"):
            pass  # anything of the old turn may still arrive before the new turn starts, never after
        after = []
        while not (isinstance(e := read(ws), dict) and e["type"] == "turn_done"):
            after.append(e)
    assert [e["type"] if isinstance(e, dict) else "audio" for e in after] == ["sentence", "audio", "audio"]
    assert after[1] == b"\x00\x00\x00\x00\x00" + b"Beta guarded a temple."
    assert after[2] == b"\x00\x00\x00\x00\x01"


def test_cancel_through_the_socket_stops_the_turn(settings_for):
    llm = FakeLLM(["One. [1.1#p1] ", "Two. [1.1#p2] ", "Three. [1.1#p3]"], delay=0.1)
    app = create_app(settings_for(), embedder=ColourEmbedder(), llm=llm, tts=EchoTTS())
    with TestClient(app).websocket_connect("/ws/session") as ws:
        ws.send_json(TURN)
        assert read(ws)["type"] == "turn_started"
        ws.send_json({"type": "cancel"})
        ws.send_json({"type": "dance"})  # a marker: the turn was cancelled before its reply
        while read(ws) != {"type": "error", "message": "unknown message type"}:
            pass
        time.sleep(0.5)  # long enough for the whole reply had it not been cancelled
        ws.send_json({"type": "dance"})
        assert read(ws) == {"type": "error", "message": "unknown message type"}  # nothing of the turn in between


def test_a_failed_model_ends_the_turn_with_an_error(settings_for):
    class Broken:
        async def stream(self, messages):
            raise RuntimeError("provider down")
            yield  # pragma: no cover

    app = create_app(settings_for(), embedder=ColourEmbedder(), llm=Broken(), tts=EchoTTS())
    with TestClient(app).websocket_connect("/ws/session") as ws:
        ws.send_json(TURN)
        assert read(ws)["type"] == "turn_started"
        assert read(ws) == {"type": "error", "message": "turn failed"}


def test_new_sessions_warm_the_connections_at_most_every_five_minutes(settings_for):
    calls = []

    class WarmLLM(FakeLLM):
        async def warm(self):
            calls.append("model")

    class WarmTTS(SilentTTS):
        async def warm(self):
            calls.append("voice")

    client = TestClient(create_app(settings_for(), embedder=ColourEmbedder(), llm=WarmLLM([]), tts=WarmTTS()))
    for _ in range(2):
        with client.websocket_connect("/ws/session") as ws:
            ws.send_json({"type": "dance"})
            ws.receive_json()
    assert calls == ["model", "voice"]


def test_a_failed_warm_up_leaves_the_session_working(settings_for):
    class ColdLLM(FakeLLM):
        async def warm(self):
            raise RuntimeError("no network")

    app = create_app(settings_for(), embedder=ColourEmbedder(), llm=ColdLLM(["Alpha was carved in stone. [1.1#p1]"]),
                     tts=SilentTTS())
    with TestClient(app).websocket_connect("/ws/session") as ws:
        ws.send_json(TURN)
        assert ws.receive_json()["type"] == "turn_started"
        assert ws.receive_json()["type"] == "sentence"
