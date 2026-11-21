// Review probes for Task 23. Each test states the behaviour the demo needs; a red test is a confirmed bug.
import { StrictMode } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import App from "./App";
import type { PackView } from "./lib/api";
import { AudioQueue } from "./lib/audioQueue";
import { emptyMemory, recordVisit, markHeard, type VisitMemory } from "./lib/memory";
import type { ServerEvent } from "./lib/socket";
import type { GuideDeps, SocketHandlers, SpeechLike } from "./useGuide";

const piece = (id: string, title: string, parts: string[]) => ({
  id, title, meta: ["Somewhere · long ago", `Stone · ${id}`], record_url: "https://x", display_image: `/${id}.jpg`,
  parts: parts.map((t, i) => ({ title: t, passages: [`${id}#p${i + 1}`] })),
  passages: { [`${id}#p1`]: "First passage.", [`${id}#p2`]: "She was a goddess of fire." },
});
const pack: PackView = {
  id: "p", title: "t", credit: "Text and images: Glasgow Museums.",
  objects: [
    piece("13.181", "Head of Sekhmet", ["Who she is", "Where she stood"]),
    piece("28.37", "Lion's head", ["A temple guardian"]),
  ],
  relations: [{ key: "13.181|28.37", a: "13.181", b: "28.37", theme: "Protectors", passages: [] }],
};

// The real AudioQueue over a fake AudioContext: a clip plays until the test ends it.
class FakeSource {
  buffer: unknown = null;
  onended: (() => void) | null = null;
  stopped = false;
  connect() {}
  start(_at?: number) {}
  stop() { this.stopped = true; }
}
class FakeCtx {
  sources: FakeSource[] = [];
  destination = {};
  state = "running";
  currentTime = 0;
  createBuffer(_channels: number, length: number) {
    const data = new Float32Array(length);
    return { length, getChannelData: () => data } as unknown as AudioBuffer;
  }
  async resume() {}
  createBufferSource() {
    const s = new FakeSource();
    this.sources.push(s);
    return s as unknown as AudioBufferSourceNode;
  }
}

type Sent = { type: string; kind?: string; object_id?: string; question?: string | null; part_index?: number | null;
  visits?: { object_id: string }[]; connections_made?: string[] };

function harness(overrides: Partial<GuideDeps> = {}) {
  const sent: Sent[] = [];
  const sockets: { handlers: SocketHandlers; closed: boolean }[] = [];
  const saved: VisitMemory[] = [];
  const ctx = new FakeCtx();
  const speechCalls = { start: 0, abort: 0 };
  const endCallbacks: ((t: string, f: string | null) => void)[] = [];
  let stopText = "";
  let seeing = "13.181";
  let identifyCalls = 0;
  const speech: SpeechLike = {
    supported: true,
    start: (_onText, onEnd) => { speechCalls.start++; if (onEnd) endCallbacks.push(onEnd); },
    stop: async () => stopText,
    abort: () => { speechCalls.abort++; },
  };
  const deps: GuideDeps = {
    code: "", socketUrl: "ws://test/ws/session", scanEvery: 5, now: () => new Date(2026, 10, 26, 10, 38),
    fetchPack: async () => pack,
    identify: async () => {
      identifyCalls++;
      return { accepted: true, object_id: seeing, score: 0.8, candidates: [{ object_id: seeing, score: 0.8 }] };
    },
    startCamera: async () => null,
    stopCamera: () => {},
    captureFrame: async () => new Blob(["x"]),
    makeSocket: (_url, handlers) => {
      const s = { handlers, closed: false };
      sockets.push(s);
      return {
        connect() {}, send: (p) => { sent.push(p as Sent); }, cancel: () => { sent.push({ type: "cancel" }); },
        close: () => { s.closed = true; },
      };
    },
    makeAudio: (events) => new AudioQueue(ctx as unknown as AudioContext, events),
    speech,
    loadMemory: async () => emptyMemory(),
    saveMemory: async (m) => { saved.push(m); },
    ...overrides,
  };
  const live = () => sockets.at(-1)!.handlers;
  return {
    deps, sent, saved, ctx, speechCalls, sockets, endCallbacks,
    identifyCalls: () => identifyCalls,
    see: (id: string) => { seeing = id; },
    willHear: (text: string) => { stopText = text; },
    androidEnds: (text: string, failure: string | null = null) => act(() => endCallbacks.at(-1)!(text, failure)),
    emit: (e: ServerEvent) => act(() => { live().onEvent(e); }),
    audio: async (i: number) => {
      await act(async () => { live().onAudio(i, new ArrayBuffer(4800)); live().onAudio(i, null); }); // one 0.1 s chunk, then the end
    },
    endClip: () => act(() => { ctx.sources.at(-1)!.onended?.(); }),
    drop: () => act(() => { live().onStatus?.(false); }),
    reopen: () => act(() => { live().onStatus?.(true); }),
    turns: () => sent.filter((p) => p.type === "turn"),
    cancels: () => sent.filter((p) => p.type === "cancel").length,
    memory: () => saved.at(-1)!,
  };
}
type H = ReturnType<typeof harness>;

const primary = () => document.querySelector("button.primary") as HTMLButtonElement;
const label = () => primary().textContent;
const press = async () => { await act(async () => { fireEvent.click(primary()); }); };
const tapCamera = () => fireEvent.click(document.querySelector("video.camera")!);
const pause = (ms: number) => act(() => new Promise((r) => setTimeout(r, ms)));

const started = (part: number | null, title: string | null, count: number, kind = "tell"): ServerEvent =>
  ({ type: "turn_started", kind, part_index: part, part_title: title, part_count: count });
const sentence = (index: number, text: string, citations: string[] = []): ServerEvent =>
  ({ type: "sentence", index, text, citations, show: [] });
const done = (sentences: number, kind = "tell", part: number | null = 0): ServerEvent =>
  ({ type: "turn_done", kind, part_index: part, sentences });

async function ready(f: H, title = "Head of Sekhmet", wrap = false) {
  render(wrap ? <StrictMode><App deps={f.deps} /></StrictMode> : <App deps={f.deps} />);
  await screen.findByRole("heading", { name: title });
  await waitFor(() => expect(primary().disabled).toBe(false));
}

/** Tell me, then the server tells part 0 of Sekhmet in one sentence that is still playing. */
async function telling(f: H) {
  await ready(f);
  await press();
  f.emit(started(0, "Who she is", 2));
  f.emit(sentence(0, "She was a goddess of fire.", ["13.181#p2"]));
  await f.audio(0);
  expect(label()).toBe("Ask");
}

/** Part 0 of Sekhmet told to the end. */
async function toldPartZero(f: H) {
  await telling(f);
  f.emit(done(1));
  f.endClip();
  await screen.findByRole("button", { name: /Carry on/ });
}

// ---------- Q1 stuck states ----------

test("Q1a: two quick taps on Tell me send one turn and no cancel", async () => {
  const f = harness();
  await ready(f);
  await press();
  await press();
  expect(f.turns()).toHaveLength(1);
  expect(f.cancels()).toBe(0);
  expect(label()).toBe("Thinking");
});

test("Q1c: Carry on is hidden during a turn and sends the next part once", async () => {
  const f = harness();
  await toldPartZero(f);
  fireEvent.click(screen.getByRole("button", { name: /Carry on/ }));
  expect(f.turns().at(-1)).toMatchObject({ kind: "carry_on", part_index: 1 });
  expect(screen.queryByRole("button", { name: /Carry on/ })).toBeNull();
  f.emit(started(1, "Where she stood", 2, "carry_on"));
  f.emit(sentence(0, "She stood in Thebes."));
  await f.audio(0);
  expect(screen.queryByRole("button", { name: /Carry on/ })).toBeNull();
});

test("Q1c': tapping the camera to stop the story still offers Carry on for the unheard part", async () => {
  const f = harness();
  await telling(f);
  tapCamera();
  expect(label()).toBe("Ask");
  expect(screen.queryByRole("button", { name: /Carry on/ })).not.toBeNull();
});

test("Q1d: a drop while listening keeps listening, and Send after the link returns asks the question", async () => {
  const f = harness();
  await telling(f);
  await press(); // Ask
  expect(label()).toBe("Send");
  f.drop();
  expect(label()).toBe("Send");
  f.reopen();
  f.willHear("Who carved her?");
  await press(); // Send
  expect(f.turns().at(-1)).toMatchObject({ kind: "ask", object_id: "13.181", question: "Who carved her?" });
  expect(label()).toBe("Thinking");
});

test("Q1e: Android ending recognition after the answer has begun does not start another turn", async () => {
  const f = harness();
  await telling(f);
  await press(); // Ask
  f.androidEnds("Who carved her?");
  expect(f.turns()).toHaveLength(2);
  f.emit(started(null, null, 2, "ask"));
  f.emit(sentence(0, "Nobody knows."));
  await f.audio(0);
  expect(label()).toBe("Ask");
  f.androidEnds("a late end from the same recogniser");
  expect(f.turns()).toHaveLength(2);
  expect(label()).toBe("Ask");
});

test("Q1f: a turn with no sentences does not mark the part heard and says so", async () => {
  const f = harness();
  await ready(f);
  await press();
  f.emit(started(0, "Who she is", 2));
  f.emit(done(0));
  const heard = f.memory().visits.find((v) => v.objectId === "13.181")!.heardParts;
  expect(heard).toEqual([]);
  expect(document.querySelector(".status")?.textContent ?? "").not.toBe("");
});

test("Q1g: when every voice fails, captions still show in turn and the part ends", async () => {
  const f = harness();
  await ready(f);
  await press();
  f.emit(started(0, "Who she is", 2));
  f.emit(sentence(0, "One."));
  f.emit({ type: "voice_failed", index: 0, message: "voice failed" });
  f.emit(sentence(1, "Two."));
  f.emit({ type: "voice_failed", index: 1, message: "voice failed" });
  f.emit(done(2));
  expect(screen.getByText("One.")).toBeTruthy();
  f.endClip();
  expect(screen.getByText("Two.")).toBeTruthy();
  f.endClip();
  expect(await screen.findByRole("button", { name: /Carry on/ })).toBeTruthy();
  expect(f.memory().visits[0].heardParts).toEqual([0]);
});

test("Q1h: a drop after turn_done lets the audio already received finish", async () => {
  const f = harness();
  await ready(f);
  await press();
  f.emit(started(0, "Who she is", 2));
  f.emit(sentence(0, "One."));
  f.emit(sentence(1, "Two."));
  await f.audio(0);
  await f.audio(1);
  f.emit(done(2)); // the server has nothing more to send
  f.drop(); // the link blips while sentence 0 plays
  expect(label()).toBe("Ask");
  f.endClip();
  expect(screen.getByText("Two.")).toBeTruthy();
  f.endClip();
  expect(f.memory().visits[0].heardParts).toEqual([0]);
});

test("Q1i: a late 'turn failed' from the cancelled turn does not kill the question that follows", async () => {
  const f = harness();
  await telling(f);
  await press(); // Ask: cancels the tell
  f.androidEnds("Who carved her?");
  f.emit({ type: "error", message: "turn failed" }); // the old turn failed just before the server read the cancel
  f.emit(started(null, null, 2, "ask"));
  f.emit(sentence(0, "Nobody knows."));
  await f.audio(0);
  f.emit(done(1, "ask", null));
  f.endClip();
  expect(screen.queryByText("The guide lost its thread. Please try again.")).toBeNull();
  expect(f.memory().exchanges["13.181"]).toEqual([{ question: "Who carved her?", answer: "Nobody knows." }]);
});

// ---------- Q2 memory ----------

test("Q2a: an interrupted part is not marked heard", async () => {
  const f = harness();
  await telling(f);
  tapCamera();
  expect(f.memory().visits[0].heardParts).toEqual([]);
});

test("Q2a': a part told to the end is marked heard", async () => {
  const f = harness();
  await toldPartZero(f);
  expect(f.memory().visits[0].heardParts).toEqual([0]);
});

test("Q2b: an exchange stores the question with the whole spoken answer", async () => {
  const f = harness();
  await toldPartZero(f);
  await press(); // Ask
  f.willHear("Who was she?");
  await press(); // Send
  f.emit(started(null, null, 2, "ask"));
  f.emit(sentence(0, "She was Sekhmet."));
  f.emit(sentence(1, "She guarded the king."));
  await f.audio(0);
  await f.audio(1);
  f.emit(done(2, "ask", null));
  f.endClip();
  f.endClip();
  expect(f.memory().exchanges["13.181"]).toEqual([{ question: "Who was she?", answer: "She was Sekhmet. She guarded the king." }]);
  expect(f.memory().visits[0].questions).toEqual(["Who was she?"]);
});

test("Q2c: a connection is remembered only when its turn finishes", async () => {
  const f = harness({ loadMemory: async () => recordVisit(emptyMemory(), "13.181", new Date(2026, 10, 26, 10, 31)) });
  f.see("28.37");
  await ready(f, "Lion's head");
  await press();
  f.emit(started(0, "A temple guardian", 1));
  f.emit({ type: "connection", key: "13.181|28.37", theme: "Protectors", other_object: "13.181", passages: [] });
  f.emit(sentence(0, "Both guarded temples."));
  await f.audio(0);
  tapCamera();
  expect(f.memory().connections).toEqual([]);
});

test("Q2d: Forget everything while the guide speaks leaves nothing stored and no dead Carry on", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const f = harness({ loadMemory: async () => recordVisit(emptyMemory(), "13.181", new Date(2026, 10, 26, 10, 31)) });
  f.see("28.37");
  await ready(f, "Lion's head");
  await press();
  f.emit(started(0, "A temple guardian", 1));
  f.emit({ type: "connection", key: "13.181|28.37", theme: "Protectors", other_object: "13.181", passages: [] });
  f.emit(sentence(0, "Both guarded temples."));
  await f.audio(0);
  fireEvent.click(screen.getByRole("button", { name: /My visit/ }));
  fireEvent.click(screen.getByRole("button", { name: "Forget everything" }));
  f.emit(done(1, "tell", 0));
  f.endClip();
  const m = f.memory();
  const turnsBefore = f.turns().length;
  const chip = screen.queryByRole("button", { name: /Carry on/ });
  if (chip) fireEvent.click(chip);
  vi.restoreAllMocks();
  expect({ visits: m.visits, connections: m.connections, exchanges: m.exchanges }).toEqual({ visits: [], connections: [], exchanges: {} });
  expect(chip === null || f.turns().length > turnsBefore).toBe(true); // a Carry on chip that is shown must work
});

test("Q2e: forgetting a piece while its answer plays does not bring its exchange back", async () => {
  const f = harness();
  await toldPartZero(f);
  await press(); // Ask
  f.willHear("Who was she?");
  await press(); // Send
  f.emit(started(null, null, 2, "ask"));
  f.emit(sentence(0, "She was Sekhmet."));
  await f.audio(0);
  fireEvent.click(screen.getByRole("button", { name: /My visit/ }));
  fireEvent.click(screen.getByRole("button", { name: "Forget Head of Sekhmet" }));
  f.emit(done(1, "ask", null));
  f.endClip();
  expect(f.memory().exchanges["13.181"]).toBeUndefined();
});

// ---------- Q3 candidate ----------

test("Q3a: while Sekhmet's story plays, the camera turning to the lion does not swap the card under Ask", async () => {
  const f = harness();
  await telling(f);
  f.see("28.37");
  await pause(120);
  const lionShown = screen.queryByRole("heading", { name: "Lion's head" }) !== null;
  await press(); // Ask
  f.willHear("What is this?");
  await press(); // Send
  const target = f.turns().at(-1)!.object_id;
  // Either the card stays on Sekhmet, or the question goes to the piece on the card: never a mismatch.
  expect({ lionShown, target }).not.toEqual({ lionShown: true, target: "13.181" });
});

test("Q3b: a piece turned down with Not this? can come back once the visitor has moved on", async () => {
  const f = harness();
  f.see("28.37"); // Sekhmet misread as the lion
  await ready(f, "Lion's head");
  fireEvent.click(screen.getByRole("button", { name: /Not this\?/ }));
  fireEvent.click(screen.getByRole("button", { name: /Head of Sekhmet/ }));
  f.see("13.181"); // now read correctly
  await pause(80);
  await press(); // Tell me about Sekhmet
  f.emit(started(0, "Who she is", 2));
  f.emit(sentence(0, "She was a goddess of fire."));
  await f.audio(0);
  f.emit(done(1));
  f.endClip();
  f.see("28.37"); // the visitor walks to the real lion
  await pause(150);
  expect(screen.queryByRole("heading", { name: "Lion's head" })).not.toBeNull();
});

// ---------- Q4 React ----------

test("Q4a: the Android end callback captured at Ask sends with the latest memory", async () => {
  const before = markHeard(recordVisit(recordVisit(emptyMemory(), "28.37", new Date(2026, 10, 26, 10, 20)), "13.181",
    new Date(2026, 10, 26, 10, 31)), "13.181", 0);
  const f = harness({ loadMemory: async () => before });
  await ready(f);
  await press(); // Tell me: Sekhmet's part 0 is heard, so part 1 is asked for
  expect(f.turns().at(-1)).toMatchObject({ kind: "tell", part_index: 1 });
  f.emit(started(1, "Where she stood", 2));
  f.emit(sentence(0, "In Thebes."));
  await f.audio(0);
  f.emit(done(1, "tell", 1));
  f.endClip();
  await press(); // Ask: the end callback is captured in this render
  fireEvent.click(screen.getByRole("button", { name: /My visit/ }));
  fireEvent.click(screen.getByRole("button", { name: "Forget Lion's head" })); // memory changes after capture
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  f.androidEnds("Who carved her?");
  const turn = f.turns().at(-1)!;
  expect(turn).toMatchObject({ kind: "ask", object_id: "13.181" });
  expect(turn.visits!.map((v) => v.object_id)).toEqual(["13.181"]);
});

test("Q4b: under StrictMode one socket stays open and the flow still works", async () => {
  const streams: number[] = [];
  let n = 0;
  const f = harness({
    startCamera: async () => ({ id: ++n }) as unknown as MediaStream,
    stopCamera: (s) => { if (s) streams.push((s as unknown as { id: number }).id); },
  });
  await ready(f, "Head of Sekhmet", true);
  expect(f.sockets.map((s) => s.closed)).toEqual([true, false]);
  expect(streams).toEqual([1]); // the first camera start was stopped, the second kept
  await press();
  expect(f.turns()).toHaveLength(1);
  f.emit(started(0, "Who she is", 2));
  f.emit(sentence(0, "She was a goddess of fire."));
  await f.audio(0);
  expect(screen.getByText("She was a goddess of fire.")).toBeTruthy();
  // A late close from the first (StrictMode) socket must not end the live turn.
  act(() => { f.sockets[0].handlers.onStatus?.(false); });
  expect(screen.queryByText("The connection dropped. Please try again.")).toBeNull();
  expect(f.ctx.sources.at(-1)!.stopped).toBe(false);
});

test("Q4c: unmounting mid-story stops the scanner and the voice", async () => {
  const f = harness();
  const view = render(<App deps={f.deps} />);
  await screen.findByRole("heading", { name: "Head of Sekhmet" });
  await waitFor(() => expect(primary().disabled).toBe(false));
  await press();
  f.emit(started(0, "Who she is", 2));
  f.emit(sentence(0, "She was a goddess of fire."));
  await f.audio(0);
  const playing = f.ctx.sources.at(-1)!;
  view.unmount();
  const calls = f.identifyCalls();
  await pause(60);
  expect(f.identifyCalls()).toBe(calls);
  expect(playing.stopped).toBe(true);
});

test("Q4c': unmounting while listening releases the microphone", async () => {
  const f = harness();
  const view = render(<App deps={f.deps} />);
  await screen.findByRole("heading", { name: "Head of Sekhmet" });
  await waitFor(() => expect(primary().disabled).toBe(false));
  await press();
  f.emit(started(0, "Who she is", 2));
  f.emit(sentence(0, "She was a goddess of fire."));
  await f.audio(0);
  await press(); // Ask → listening
  expect(label()).toBe("Send");
  const aborts = f.speechCalls.abort;
  view.unmount();
  expect(f.speechCalls.abort).toBeGreaterThan(aborts);
});

// ---------- proposed: a way out of "thinking" ----------

test("Q1b': tapping the camera while thinking cancels the request and offers Carry on", async () => {
  const f = harness();
  await ready(f);
  await press();
  expect(label()).toBe("Thinking");
  tapCamera();
  expect(f.cancels()).toBe(1);
  expect(label()).toBe("Ask");
  expect(screen.getByRole("button", { name: /Carry on/ })).toBeTruthy();
});

test("Q1b'': a request the server never starts gives up by itself", async () => {
  const f = harness({ startTimeout: 50 } as Partial<GuideDeps>);
  await ready(f);
  await press();
  await pause(120);
  expect(screen.getByText("The guide is taking too long. Please try again.")).toBeTruthy();
  expect(f.cancels()).toBe(1);
  expect(screen.getByRole("button", { name: /Carry on/ })).toBeTruthy();
});

test("a turn that goes quiet mid-story gives up and says so", async () => {
  const f = harness({ quietTimeout: 50 });
  await ready(f);
  await press();
  f.emit(started(0, "Who she is", 2));
  f.emit(sentence(0, "She was a goddess of fire.", ["13.181#p2"]));
  await f.audio(0);
  await pause(120);
  expect(screen.getByText("The connection went quiet. Please try again.")).toBeTruthy();
  expect(f.cancels()).toBe(1);
});

test("a finished turn does not count silence", async () => {
  const f = harness({ quietTimeout: 50 });
  await telling(f);
  f.emit(done(1));
  await pause(120);
  expect(screen.queryByText("The connection went quiet. Please try again.")).toBeNull();
});
