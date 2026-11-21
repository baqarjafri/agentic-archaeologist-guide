"""WebSocket /ws/session: one connection per visit; each turn streams sentences and audio back."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from starlette.datastructures import State
from starlette.websockets import WebSocketDisconnected

from app.access import code_allowed
from app.guide.context import TurnRequest
from app.guide.turn import Send, run_turn

router = APIRouter()
log = logging.getLogger("app.socket")
WARM_EVERY = 60.0  # seconds: warm at most this often per process; shorter than the 120 s keep-alive, so a warm connection is always fresh


def warm_up(state: State) -> None:
    """Open the model and voice connections in the background, so the visitor's first turn is not the slow one."""
    now = time.monotonic()
    if now - getattr(state, "warmed_at", float("-inf")) < WARM_EVERY:
        return
    state.warmed_at = now

    async def run() -> None:
        for name, client in (("model", state.llm), ("voice", state.tts)):
            try:
                await client.warm()
            except Exception as exc:  # a failed warm-up only means the first turn is a little slower
                log.warning("warm-up of the %s failed: %s", name, exc)

    state.warming = asyncio.create_task(run())  # held on the state, so the task is not collected before it finishes


@router.websocket("/ws/session")
async def session(ws: WebSocket) -> None:
    state = ws.app.state
    await ws.accept()
    if not code_allowed(ws.query_params.get("code"), state.settings):
        await ws.close(code=4401)  # after accepting, so the phone sees why and stops reconnecting
        return
    warm_up(state)
    lock = asyncio.Lock()
    current: asyncio.Task | None = None
    live = 0  # the turn allowed to reach the phone; every cancel and new turn moves it on

    def sender(turn: int | None) -> Send:
        async def send(item: dict | bytes) -> None:
            async with lock:
                if turn is not None and turn != live:
                    return  # a superseded turn's late caption, audio or error: the phone has moved on
                if isinstance(item, (bytes, bytearray)):
                    await ws.send_bytes(bytes(item))
                else:
                    await ws.send_json(item)
        return send

    reply = sender(None)  # answers to the phone's own messages are never dropped

    async def guarded(req: TurnRequest, turn: int) -> None:
        send = sender(turn)
        try:
            await run_turn(req, state.pack, state.llm, state.tts, send,
                           strict=state.settings.strict_citations, respell=state.settings.respell_names)
        except (WebSocketDisconnect, WebSocketDisconnected):
            pass  # the phone left mid-turn; the receive loop ends the session
        except Exception:
            log.exception("turn failed")  # the details stay in the server log; the phone gets plain words
            with contextlib.suppress(Exception):
                await send({"type": "error", "message": "turn failed"})

    def cancel_current() -> None:
        nonlocal live
        live += 1  # from here on, anything the old turn still sends is dropped
        if current is not None and not current.done() and not current.cancelling():
            current.cancel()  # once only: a second cancel would cut short the model stream's close

    try:
        while True:
            try:
                message = await ws.receive_json()
            except (ValueError, KeyError, TypeError):  # a text frame that is not JSON, or a binary frame
                message = None
            if not isinstance(message, dict):
                await reply({"type": "error", "message": "invalid message"})
                continue
            if message.get("type") == "cancel":
                cancel_current()
                continue
            if message.get("type") != "turn":
                await reply({"type": "error", "message": "unknown message type"})
                continue
            try:
                req = TurnRequest.model_validate(message)
            except ValidationError:
                await reply({"type": "error", "message": "invalid turn"})
                continue
            if req.object_id not in state.pack.objects:
                await reply({"type": "error", "message": "unknown object"})
                continue
            cancel_current()
            current = asyncio.create_task(guarded(req, live))
    except (WebSocketDisconnect, WebSocketDisconnected):
        pass
    finally:  # however the session ends, stop the turn in flight
        cancel_current()
