import { afterEach, expect, test, vi } from "vitest";
import { GuideSocket, parseFrame, type ServerEvent } from "./socket";

class FakeWebSocket {
  static made: FakeWebSocket[] = [];
  readyState = 0;
  binaryType = "blob";
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((m: { data: unknown }) => void) | null = null;
  onclose: ((e?: { code: number }) => void) | null = null;
  constructor(public url: string) { FakeWebSocket.made.push(this); }
  send(text: string) { this.sent.push(text); }
  close() { this.readyState = 3; this.onclose?.(); }
  open() { this.readyState = 1; this.onopen?.(); }
  refuse() { this.readyState = 3; this.onclose?.({ code: 4401 }); }
}

afterEach(() => { FakeWebSocket.made = []; vi.useRealTimers(); });

const make = (events: ServerEvent[], audio: [number, number][]) =>
  new GuideSocket("ws://x/ws/session", {
    onEvent: (e) => events.push(e),
    onAudio: (i, chunk) => audio.push([i, chunk ? chunk.byteLength : -1]),
  }, (url) => new FakeWebSocket(url) as unknown as WebSocket);

test("frames carry a sentence index, a kind and the audio", () => {
  const { index, chunk } = parseFrame(new Uint8Array([0, 0, 0, 7, 0, 9, 9, 9, 9]).buffer);
  expect(index).toBe(7);
  expect(chunk?.byteLength).toBe(4);
  expect(parseFrame(new Uint8Array([0, 0, 0, 7, 1]).buffer)).toEqual({ index: 7, chunk: null });
});

test("messages queue until open, then events and audio are routed", () => {
  const events: ServerEvent[] = [];
  const audio: [number, number][] = [];
  const socket = make(events, audio);
  socket.connect();
  socket.send({ type: "turn" });
  const ws = FakeWebSocket.made[0];
  expect(ws.sent).toEqual([]);
  ws.open();
  expect(ws.sent).toEqual(['{"type":"turn"}']);
  ws.onmessage?.({ data: '{"type":"turn_done","kind":"tell","part_index":0,"sentences":2}' });
  ws.onmessage?.({ data: new Uint8Array([0, 0, 0, 1, 0, 5, 5]).buffer });
  ws.onmessage?.({ data: new Uint8Array([0, 0, 0, 1, 1]).buffer });
  expect(events[0].type).toBe("turn_done");
  expect(audio).toEqual([[1, 2], [1, -1]]);
  socket.cancel();
  expect(ws.sent.at(-1)).toBe('{"type":"cancel"}');
});

test("an unexpected close reconnects; a deliberate close does not", () => {
  vi.useFakeTimers();
  const socket = make([], []);
  socket.connect();
  FakeWebSocket.made[0].open();
  FakeWebSocket.made[0].close();
  vi.advanceTimersByTime(1600);
  expect(FakeWebSocket.made).toHaveLength(2);
  socket.close();
  vi.advanceTimersByTime(1600);
  expect(FakeWebSocket.made).toHaveLength(2);
});

test("a refused access code is not retried", () => {
  vi.useFakeTimers();
  const socket = make([], []);
  socket.connect();
  FakeWebSocket.made[0].refuse();
  vi.advanceTimersByTime(1600);
  expect(FakeWebSocket.made).toHaveLength(1);
});

test("messages queued for a link that then fails are not sent later", () => {
  vi.useFakeTimers();
  const socket = make([], []);
  socket.connect();
  socket.send({ type: "turn" });
  FakeWebSocket.made[0].close(); // the attempt fails before it ever opens
  vi.advanceTimersByTime(1600);
  FakeWebSocket.made[1].open();
  expect(FakeWebSocket.made[1].sent).toEqual([]);
});

test("closing during the reconnect wait stays closed", () => {
  vi.useFakeTimers();
  const socket = make([], []);
  socket.connect();
  FakeWebSocket.made[0].close();
  socket.close();
  vi.advanceTimersByTime(1600);
  expect(FakeWebSocket.made).toHaveLength(1);
});
