import { expect, test } from "vitest";
import { AudioQueue } from "./audioQueue";

const RATE = 24000;

class FakeSource {
  buffer: unknown = null;
  onended: (() => void) | null = null;
  at = -1;
  stopped = false;
  connected: unknown = null;
  connect(node: unknown) { this.connected = node; }
  start(at: number) { this.at = at; }
  stop() { this.stopped = true; }
  end() { this.onended?.(); }
}

class FakeCtx {
  sources: FakeSource[] = [];
  destination = {};
  currentTime = 10;
  state = "running";
  resumed = 0;
  async resume() { this.resumed++; }
  createBuffer(_channels: number, length: number) {
    const data = new Float32Array(length);
    return { length, data, get silent() { return data.every((v) => v === 0); }, getChannelData: () => data };
  }
  createBufferSource() {
    const s = new FakeSource();
    this.sources.push(s);
    return s as unknown as AudioBufferSourceNode;
  }
}

/** `samples` 16-bit samples of one value: 7200 samples is 0.3 s at 24 kHz, the cushion. */
const pcm = (samples: number, value = 1000) => new Int16Array(samples).fill(value).buffer;

function setup() {
  const ctx = new FakeCtx();
  const started: number[] = [];
  let idle = 0;
  const queue = new AudioQueue(ctx as unknown as AudioContext, { onStart: (i) => started.push(i), onIdle: () => { idle++; } });
  return { ctx, queue, started, idle: () => idle };
}

test("plays sentences in order even when later audio arrives first", () => {
  const { ctx, queue, started } = setup();
  queue.begin();
  queue.push(1, pcm(2400));
  queue.end(1);
  expect(started).toEqual([]);
  queue.push(0, pcm(2400));
  queue.end(0);
  expect(started).toEqual([0]);
  ctx.sources[0].end();
  expect(started).toEqual([0, 1]);
});

test("a sentence waits for a 0.3 s cushion of audio before it starts", () => {
  const { queue, started } = setup();
  queue.begin();
  queue.push(0, pcm(3600));
  expect(started).toEqual([]);
  queue.push(0, pcm(3600));
  expect(started).toEqual([0]);
});

test("a short sentence starts at its end marker", () => {
  const { queue, started } = setup();
  queue.begin();
  queue.push(0, pcm(600));
  queue.end(0);
  expect(started).toEqual([0]);
});

test("audio that has arrived plays as one buffer, and later chunks follow with no gap", () => {
  const { ctx, queue } = setup();
  queue.begin();
  queue.push(0, pcm(2400));
  queue.push(0, pcm(4800));
  expect(ctx.sources.map((s) => s.at)).toEqual([10]);
  queue.push(0, pcm(2400));
  queue.end(0);
  expect(ctx.sources.map((s) => s.at)).toEqual([10, 10.3]);
});

test("a chunk that arrives late plays as soon as it can", () => {
  const { ctx, queue } = setup();
  queue.begin();
  queue.push(0, pcm(7200));
  ctx.currentTime = 10.5;
  queue.push(0, pcm(2400));
  expect(ctx.sources.map((s) => s.at)).toEqual([10, 10.5]);
});

test("the next sentence starts only when the last buffer of this one has played", () => {
  const { ctx, queue, started } = setup();
  queue.begin();
  queue.push(0, pcm(7200));
  queue.push(0, pcm(2400));
  queue.end(0);
  queue.push(1, pcm(2400));
  queue.end(1);
  ctx.sources[0].end();
  expect(started).toEqual([0]);
  ctx.sources[1].end();
  expect(started).toEqual([0, 1]);
});

test("a sentence with no voice keeps its caption up for a silent pause", () => {
  const { ctx, queue, started } = setup();
  queue.begin();
  queue.skip(0);
  queue.push(1, pcm(2400));
  queue.end(1);
  expect(started).toEqual([0]);
  expect(ctx.sources[0].buffer).toMatchObject({ length: 72000, silent: true });
  ctx.sources[0].end();
  expect(started).toEqual([0, 1]);
});

test("16-bit samples become audio between -1 and 1", () => {
  const { ctx, queue } = setup();
  queue.begin();
  queue.push(0, new Int16Array([16384, -32768, 0]).buffer);
  queue.end(0);
  expect(Array.from((ctx.sources[0].buffer as { data: Float32Array }).data)).toEqual([0.5, -1, 0]);
});

test("a frame with no samples is ignored", () => {
  const { ctx, queue, started } = setup();
  queue.begin();
  queue.push(0, new ArrayBuffer(1));
  queue.push(0, pcm(600));
  queue.end(0);
  expect(started).toEqual([0]);
  expect(ctx.sources).toHaveLength(1);
});

test("finish reports idle after the last sentence ends", () => {
  const { ctx, queue, idle } = setup();
  queue.begin();
  queue.push(0, pcm(2400));
  queue.end(0);
  queue.finish(1);
  expect(idle()).toBe(0);
  ctx.sources[0].end();
  expect(idle()).toBe(1);
});

test("stop silences every scheduled buffer and ignores audio until the next turn", () => {
  const { ctx, queue, started } = setup();
  queue.begin();
  queue.push(0, pcm(7200));
  queue.push(0, pcm(2400));
  queue.stop();
  expect(ctx.sources.map((s) => s.stopped)).toEqual([true, true]);
  expect(queue.busy).toBe(false);
  queue.push(0, pcm(7200));
  queue.end(0);
  expect(ctx.sources).toHaveLength(2);
  queue.begin();
  queue.push(0, pcm(7200));
  expect(started).toEqual([0, 0]);
});

test("each new turn wakes audio that the phone suspended", () => {
  const { ctx, queue } = setup();
  queue.begin();
  queue.begin();
  expect(ctx.resumed).toBe(2);
});

test("audio suspended mid-sentence is woken as more arrives", () => {
  const { ctx, queue } = setup();
  queue.begin();
  queue.push(0, pcm(7200));
  ctx.state = "suspended";
  queue.push(0, pcm(2400));
  expect(ctx.resumed).toBe(2);
});

/** A context with a running clock: buffers end on time, and a suspended clock stands still, as in Chrome. */
type Src = { buffer: { length: number } | null; onended: (() => void) | null; at: number; stopped: boolean;
  connect(): void; start(at: number): void; stop(): void };
const ends = (s: Src) => s.at + s.buffer!.length / RATE;

class ClockCtx {
  currentTime = 0;
  state = "running";
  destination = {};
  resumed = 0;
  live: Src[] = [];
  played: [number, number][] = [];
  async resume() { this.resumed++; }
  createBuffer(_channels: number, length: number) {
    if (length <= 0) throw new DOMException("no frames", "NotSupportedError"); // as Chrome does
    const data = new Float32Array(length);
    return { length, getChannelData: () => data };
  }
  createBufferSource() {
    const ctx = this;
    const s: Src = {
      buffer: null, onended: null, at: -1, stopped: false, connect() {},
      start(at: number) { s.at = at; ctx.live.push(s); ctx.played.push([at, at + s.buffer!.length / RATE]); },
      stop() { s.stopped = true; },
    };
    return s;
  }
  /** Run the clock to `t`, ending each buffer at its end time. */
  advance(t: number) {
    for (;;) {
      if (this.state !== "running") return;
      const next = this.live.filter((s) => !s.stopped).sort((a, b) => ends(a) - ends(b))[0];
      if (!next || ends(next) > t) break;
      this.currentTime = ends(next);
      this.live = this.live.filter((s) => s !== next);
      next.onended?.();
    }
    this.currentTime = t;
  }
}

function clocked() {
  const ctx = new ClockCtx();
  let idle = 0;
  const queue = new AudioQueue(ctx as unknown as AudioContext, { onStart: () => {}, onIdle: () => { idle++; } });
  return { ctx, queue, idle: () => idle };
}

/** Silences between consecutive played buffers, in ms, ignoring joins under 1 ms. */
function gaps(played: [number, number][]): number[] {
  const sorted = [...played].sort((a, b) => a[0] - b[0]);
  const out: number[] = [];
  for (let i = 1; i < sorted.length; i++) {
    const gap = (sorted[i][0] - sorted[i - 1][1]) * 1000;
    if (gap > 1) out.push(gap);
  }
  return out;
}

test("a link slower than speech pauses a few times rather than stuttering", () => {
  const { ctx, queue, idle } = clocked();
  queue.begin();
  const chunk = 800; // 33 ms, Gemini's size
  const count = Math.round((5 * RATE) / chunk); // a 5 s sentence
  for (let k = 0; k < count; k++) {
    ctx.advance(1 + (k * chunk) / RATE / 0.8); // delivered at 0.8 times real time
    queue.push(0, pcm(chunk));
  }
  queue.end(0);
  queue.finish(1);
  ctx.advance(1000);
  expect(gaps(ctx.played).length).toBeLessThanOrEqual(3);
  expect(idle()).toBe(1);
});

test("audio that ran dry waits for a refill before playing on", () => {
  const { ctx, queue } = clocked();
  queue.begin();
  queue.push(0, pcm(7200)); // 0.3 s: starts
  ctx.advance(1); // it plays out, and the sentence is not over
  queue.push(0, pcm(800));
  expect(ctx.played).toHaveLength(1);
  queue.push(0, pcm(12000)); // 0.5 s more in hand
  expect(ctx.played).toHaveLength(2);
});

test("audio plays through the given output node, or straight to the speakers when none is given", () => {
  const plain = setup();
  plain.queue.begin();
  plain.queue.push(0, pcm(600));
  plain.queue.end(0);
  expect(plain.ctx.sources[0].connected).toBe(plain.ctx.destination);

  const ctx = new FakeCtx();
  const bus = { name: "bus" };
  const queue = new AudioQueue(ctx as unknown as AudioContext, { onStart: () => {}, onIdle: () => {} }, bus as unknown as AudioNode);
  queue.begin();
  queue.push(0, pcm(600));
  queue.end(0);
  expect(ctx.sources[0].connected).toBe(bus);
});
