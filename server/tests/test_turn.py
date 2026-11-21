import asyncio
import contextlib
import struct

from app.guide.context import TurnRequest
from app.guide.llm import FakeLLM
from app.guide.tts import SilentTTS
from app.guide.turn import run_turn
from app.packs import load_pack


class Recorder:
    def __init__(self):
        self.items = []

    async def __call__(self, item):
        self.items.append(item)

    @property
    def events(self):
        return [i for i in self.items if isinstance(i, dict)]

    @property
    def frames(self):
        return [i for i in self.items if isinstance(i, bytes)]


class SlowFirstTTS:
    """The first sentence's audio finishes last, to prove audio still goes out in sentence order."""

    def __init__(self):
        self.calls = 0

    async def stream(self, text):
        self.calls += 1
        await asyncio.sleep(0.05 if self.calls == 1 else 0.0)
        yield text[:4].encode()
        yield text[4:].encode()


def frames(rec):
    """Each binary frame as ((sentence index, kind), audio); kind 0 is audio, kind 1 is the end of the sentence."""
    return [(struct.unpack(">IB", f[:5]), f[5:]) for f in rec.frames]


def tell(object_id="2.2", **kw):
    base = {"kind": "tell", "object_id": object_id,
            "visits": [{"object_id": "1.1", "time": "10:31", "heard_parts": [0]}, {"object_id": object_id, "time": "10:44"}]}
    base.update(kw)
    return TurnRequest.model_validate(base)


async def test_turn_emits_connection_sentences_and_ordered_audio(test_pack):
    llm = FakeLLM(["You remember Alpha? Like Alpha, Beta was a protector. [1.1#p2][2.2#p1] ",
                   "It has red paint. [2.2#p2]"])
    rec = Recorder()
    await run_turn(tell(), load_pack(test_pack), llm, SlowFirstTTS(), rec)
    kinds = [e["type"] for e in rec.events]
    assert kinds[:2] == ["turn_started", "connection"] and kinds[-1] == "turn_done"
    assert rec.events[1] == {"type": "connection", "key": "1.1|2.2", "theme": "Guardians",
                             "other_object": "1.1", "passages": ["1.1#p2", "2.2#p1"]}
    sentences = [e for e in rec.events if e["type"] == "sentence"]
    assert [s["text"] for s in sentences] == ["You remember Alpha?", "Like Alpha, Beta was a protector.", "It has red paint."]
    assert sentences[1]["citations"] == ["1.1#p2", "2.2#p1"] and sentences[1]["show"] == ["1.1"]
    decoded = frames(rec)
    assert [head for head, _ in decoded] == [(0, 0), (0, 0), (0, 1), (1, 0), (1, 0), (1, 1), (2, 0), (2, 0), (2, 1)]
    assert b"".join(audio for (index, _), audio in decoded if index == 0) == b"You remember Alpha?"
    assert rec.events[0]["audio"] == "pcm_s16le_24000_mono"
    assert "remind them of the Alpha" in llm.last_messages[1]["content"]


async def test_invented_citations_are_dropped_and_not_spoken(test_pack):
    rec = Recorder()
    llm = FakeLLM(["Real. [1.1#p1] Invented. [1.1#p99]"])
    await run_turn(tell(object_id="1.1", visits=[]), load_pack(test_pack), llm, SilentTTS(), rec)
    assert [e["type"] for e in rec.events if e["type"] in ("sentence", "dropped")] == ["sentence", "dropped"]
    assert [head for head, _ in frames(rec)] == [(0, 0), (0, 1)]
    assert rec.events[-1] == {"type": "turn_done", "kind": "tell", "part_index": 0, "sentences": 1}


async def test_a_failed_voice_still_sends_the_caption(test_pack):
    class Broken:
        async def stream(self, text):
            raise RuntimeError("boom")
            yield b""  # pragma: no cover

    rec = Recorder()
    await run_turn(tell(object_id="1.1", visits=[]), load_pack(test_pack), FakeLLM(["Real. [1.1#p1]"]), Broken(), rec)
    assert any(e["type"] == "sentence" for e in rec.events)
    assert {"type": "voice_failed", "index": 0} == {k: v for k, v in next(e for e in rec.events if e["type"] == "voice_failed").items() if k != "message"}
    assert rec.frames == []


async def test_cancel_stops_the_turn(test_pack):
    rec = Recorder()
    llm = FakeLLM(["One. [1.1#p1] ", "Two. [1.1#p2] ", "Three. [1.1#p3]"], delay=0.05)
    task = asyncio.create_task(run_turn(tell(object_id="1.1", visits=[]), load_pack(test_pack), llm, SilentTTS(), rec))
    await asyncio.sleep(0.07)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert not any(e["type"] == "turn_done" for e in rec.events)


async def test_cancel_with_a_voice_pending_sends_nothing_more(test_pack):
    class SlowVoice:
        async def stream(self, text):
            await asyncio.sleep(0.3)
            yield b"late"

    rec = Recorder()
    llm = FakeLLM(["One. [1.1#p1] ", "Two. [1.1#p2] ", "Three. [1.1#p3]"], delay=0.05)
    task = asyncio.create_task(run_turn(tell(object_id="1.1", visits=[]), load_pack(test_pack), llm, SlowVoice(), rec))
    while not any(e["type"] == "sentence" for e in rec.events):
        await asyncio.sleep(0.01)
    task.cancel()  # "One." is on screen and its voice is still being made
    with contextlib.suppress(asyncio.CancelledError):
        await task
    sent = len(rec.items)
    await asyncio.sleep(0.4)  # past the moment the voice would have arrived
    assert len(rec.items) == sent
    assert rec.frames == [] and not any(e["type"] in ("voice_failed", "turn_done") for e in rec.events)


async def test_a_turn_voices_at_most_two_sentences_at_a_time(test_pack):
    class Counting:
        def __init__(self):
            self.live = 0
            self.peak = 0

        async def stream(self, text):
            self.live += 1
            self.peak = max(self.peak, self.live)
            await asyncio.sleep(0.02)
            self.live -= 1
            yield b"x"

    tts = Counting()
    rec = Recorder()
    llm = FakeLLM(["One. [1.1#p1] Two. [1.1#p2] Three. [1.1#p1] Four. [1.1#p2] Five. [1.1#p1]"])
    await run_turn(tell(object_id="1.1", visits=[]), load_pack(test_pack), llm, tts, rec)
    assert tts.peak == 2 and len(rec.frames) == 10


async def test_a_voice_that_fails_part_way_ends_where_it_got_to(test_pack):
    class Halting:
        async def stream(self, text):
            yield b"\x01\x00"
            raise RuntimeError("cut off")

    rec = Recorder()
    await run_turn(tell(object_id="1.1", visits=[]), load_pack(test_pack), FakeLLM(["Real. [1.1#p1]"]), Halting(), rec)
    assert [head for head, _ in frames(rec)] == [(0, 0), (0, 1)]
    assert not any(e["type"] == "voice_failed" for e in rec.events)
