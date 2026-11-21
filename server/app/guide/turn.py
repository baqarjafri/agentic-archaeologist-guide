"""Run one guide turn: plan, prompt, stream, cut into sentences, check citations, and stream each sentence's voice in order."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import struct
from collections.abc import Awaitable, Callable
from typing import Any

from app.guide.context import TurnRequest, build_messages, context_ids, plan_turn
from app.guide.llm import LLMClient
from app.guide.speech import speech_text
from app.guide.stream import Sentence, SentenceStream
from app.guide.tts import AUDIO_FORMAT, TTSClient
from app.guide.validate import check, keep
from app.packs import Pack

Send = Callable[[Any], Awaitable[None]]
log = logging.getLogger("app.turn")
VOICE_AHEAD = 2  # voice requests one turn may have in flight: a long reply cannot crowd out other visitors, and a cancelled turn spends no more quota


CHUNK, END = 0, 1  # frame kinds: a piece of a sentence's audio, and the end of that sentence's audio
FAILED = object()  # put on a sentence's queue when its voice fails


def audio_frame(index: int, kind: int, audio: bytes = b"") -> bytes:
    """A binary frame: the sentence index (4 bytes, big-endian), the kind (1 byte), then raw PCM audio."""
    return struct.pack(">IB", index, kind) + audio


async def run_turn(req: TurnRequest, pack: Pack, llm: LLMClient, tts: TTSClient, send: Send,
                   *, strict: bool = False, respell: bool = False) -> None:
    plan = plan_turn(req, pack)
    allowed = context_ids(pack, plan)  # a citation the model was not shown this turn is dropped like an invented one
    await send({"type": "turn_started", "kind": req.kind, "part_index": plan.part_index,
                "part_title": plan.part_title, "part_count": plan.part_count, "audio": AUDIO_FORMAT})
    if plan.connection is not None:
        lp = plan.connection
        await send({"type": "connection", "key": lp.relation.key, "theme": lp.relation.theme,
                    "other_object": lp.other.id, "passages": list(lp.relation.passage_ids)})

    pronunciations = {word: spoken for o in pack.objects.values() for word, spoken in o.pronunciations.items()}
    queue: asyncio.Queue[tuple[int, asyncio.Queue] | None] = asyncio.Queue()
    voices: list[asyncio.Task] = []
    count = 0
    ahead = asyncio.Semaphore(VOICE_AHEAD)

    async def voice(text: str, chunks: asyncio.Queue) -> None:
        try:
            async with ahead, contextlib.aclosing(tts.stream(text)) as audio:
                async for chunk in audio:
                    if chunk:
                        await chunks.put(chunk)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # a failed voice must not stop the captions; details stay in the server log
            log.warning("voice failed for %r: %s", text[:40], exc)
            await chunks.put(FAILED)
            return
        await chunks.put(None)

    async def speak_in_order() -> None:
        while (item := await queue.get()) is not None:
            index, chunks = item
            spoken = False
            while (chunk := await chunks.get()) is not None and chunk is not FAILED:
                await send(audio_frame(index, CHUNK, chunk))
                spoken = True
            if spoken:
                await send(audio_frame(index, END))  # a voice that failed part-way ends where it got to
            else:
                await send({"type": "voice_failed", "index": index, "message": "voice failed"})

    async def emit(sentence: Sentence) -> None:
        nonlocal count
        checked = check(sentence, pack, req.object_id, allowed)
        ok, reason = keep(checked, strict)
        if not ok:
            await send({"type": "dropped", "text": checked.text, "reason": reason})
            return
        index = count
        count += 1
        chunks: asyncio.Queue = asyncio.Queue()
        # the voice starts before the caption is written, so a slow link does not delay it
        voices.append(asyncio.create_task(voice(speech_text(checked.text, pronunciations, respell), chunks)))
        await send({"type": "sentence", "index": index, "text": checked.text,
                    "citations": checked.citations, "show": checked.show})
        await queue.put((index, chunks))

    speaker = asyncio.create_task(speak_in_order())
    try:
        stream = SentenceStream()
        # aclosing closes the model's stream the moment the turn ends or is cancelled, so no tokens run on unheard
        async with contextlib.aclosing(llm.stream(build_messages(req, pack, plan))) as deltas:
            async for delta in deltas:
                for sentence in stream.feed(delta):
                    await emit(sentence)
        for sentence in stream.close():
            await emit(sentence)
        await queue.put(None)
        await speaker
        await send({"type": "turn_done", "kind": req.kind, "part_index": plan.part_index, "sentences": count})
    except BaseException:  # cancelled, or the model failed: stop the speaker and pending voices too
        speaker.cancel()
        for task in voices:
            task.cancel()
        raise
