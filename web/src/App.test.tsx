import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test } from "vitest";
import App from "./App";
import type { PackView } from "./lib/api";
import { emptyMemory, recordVisit } from "./lib/memory";
import type { ServerEvent } from "./lib/socket";
import type { GuideDeps, QueueEvents, SocketHandlers } from "./useGuide";

const piece = (id: string, title: string, parts: string[]) => ({
  id, title, meta: ["Somewhere · long ago", `Stone · ${id}`], record_url: "https://x", display_image: `/${id}.jpg`,
  parts: parts.map((t, i) => ({ title: t, passages: [`${id}#p${i + 1}`] })),
  passages: { [`${id}#p1`]: "First passage.", [`${id}#p2`]: "She was a goddess of fire." },
});
const pack: PackView = {
  id: "p", title: "t", credit: "Text and images: Glasgow Museums.",
  objects: [piece("13.181", "Head of Sekhmet", ["Who she is", "Where she stood"]), piece("28.37", "Lion's head", ["A temple guardian"])],
  relations: [{ key: "13.181|28.37", a: "13.181", b: "28.37", theme: "Protectors", passages: [] }],
};

function fakeDeps(overrides: Partial<GuideDeps> = {}) {
  const sent: object[] = [];
  let handlers: SocketHandlers | null = null;
  const deps: GuideDeps = {
    code: "", socketUrl: "ws://test/ws/session", scanEvery: 5, now: () => new Date(2026, 10, 26, 10, 38),
    fetchPack: async () => pack,
    identify: async () => ({ accepted: true, object_id: "13.181", score: 0.8, candidates: [{ object_id: "13.181", score: 0.8 }] }),
    startCamera: async () => null,
    stopCamera: () => {},
    captureFrame: async () => new Blob(["x"]),
    makeSocket: (_url, h) => {
      handlers = h;
      return { connect() {}, send: (p) => { sent.push(p); }, cancel: () => { sent.push({ type: "cancel" }); }, close() {} };
    },
    makeAudio: (e: QueueEvents) => ({
      begin() {}, push: (i: number) => { e.onStart(i); }, end() {}, skip: (i: number) => e.onStart(i),
      finish: () => e.onIdle(), stop() {}, busy: false,
    }),
    speech: { supported: false, start() {}, stop: async () => "", abort() {} },
    loadMemory: async () => emptyMemory(),
    saveMemory: async () => {},
    ...overrides,
  };
  return {
    deps, sent,
    emit: (event: ServerEvent) => handlers!.onEvent(event),
    audioFrame: (index: number) => handlers!.onAudio(index, new ArrayBuffer(4)),
    drop: () => handlers!.onStatus?.(false),
  };
}

async function tapTellMe(f: ReturnType<typeof fakeDeps>) {
  render(<App deps={f.deps} />);
  await screen.findByRole("heading", { name: "Head of Sekhmet" });
  const tellMe = screen.getByRole("button", { name: "Tell me" });
  await waitFor(() => expect((tellMe as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(tellMe);
}

test("recognise, tell, hear a cited sentence, then get the Carry on offer", async () => {
  const f = fakeDeps();
  render(<App deps={f.deps} />);
  await screen.findByRole("heading", { name: "Head of Sekhmet" });
  const tellMe = screen.getByRole("button", { name: "Tell me" });
  await waitFor(() => expect((tellMe as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(tellMe);
  expect(f.sent.at(-1)).toMatchObject({ type: "turn", kind: "tell", object_id: "13.181", part_index: 0 });
  act(() => {
    f.emit({ type: "turn_started", kind: "tell", part_index: 0, part_title: "Who she is", part_count: 2 });
    f.emit({ type: "sentence", index: 0, text: "She was a goddess of fire.", citations: ["13.181#p2"], show: [] });
    f.audioFrame(0);
  });
  expect(await screen.findByText("She was a goddess of fire.")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Ask" })).toBeTruthy();
  act(() => { f.emit({ type: "turn_done", kind: "tell", part_index: 0, sentences: 1 }); });
  expect(await screen.findByRole("button", { name: /Carry on/ })).toBeTruthy();
});

test("a connection shows the earlier piece beside the new one", async () => {
  const f = fakeDeps({
    identify: async () => ({ accepted: true, object_id: "28.37", score: 0.8, candidates: [] }),
    loadMemory: async () => recordVisit(emptyMemory(), "13.181", new Date(2026, 10, 26, 10, 31)),
  });
  render(<App deps={f.deps} />);
  await screen.findByRole("heading", { name: "Lion's head" });
  const tellMe = screen.getByRole("button", { name: "Tell me" });
  await waitFor(() => expect((tellMe as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(tellMe);
  act(() => {
    f.emit({ type: "turn_started", kind: "tell", part_index: 0, part_title: "A temple guardian", part_count: 1 });
    f.emit({ type: "connection", key: "13.181|28.37", theme: "Protectors", other_object: "13.181", passages: [] });
  });
  expect(await screen.findByText("Protectors")).toBeTruthy();
  expect(screen.getByText("Linked to Head of Sekhmet · seen 10:31")).toBeTruthy();
});

test("late audio and messages from an interrupted turn are ignored", async () => {
  const f = fakeDeps();
  await tapTellMe(f);
  act(() => {
    f.emit({ type: "turn_started", kind: "tell", part_index: 0, part_title: "Who she is", part_count: 2 });
    f.emit({ type: "sentence", index: 0, text: "She was a goddess of fire.", citations: ["13.181#p2"], show: [] });
    f.audioFrame(0);
  });
  fireEvent.click(await screen.findByRole("button", { name: "Ask" }));
  expect(f.sent.at(-1)).toEqual({ type: "cancel" });
  act(() => {
    f.emit({ type: "sentence", index: 1, text: "A late sentence from the old turn.", citations: [], show: [] });
    f.audioFrame(1);
    f.emit({ type: "turn_done", kind: "tell", part_index: 0, sentences: 2 });
  });
  expect(screen.queryByText("A late sentence from the old turn.")).toBeNull();
  expect(screen.getByRole("button", { name: "Send" })).toBeTruthy();
});

test("a failed turn ends the wait and offers to carry on", async () => {
  const f = fakeDeps();
  await tapTellMe(f);
  act(() => { f.emit({ type: "error", message: "turn failed: boom" }); });
  expect(await screen.findByText("The guide lost its thread. Please try again.")).toBeTruthy();
  expect(screen.getByRole("button", { name: /Carry on/ })).toBeTruthy();
});

test("a dropped connection during a turn ends the wait", async () => {
  const f = fakeDeps();
  await tapTellMe(f);
  act(() => { f.drop(); });
  expect(await screen.findByText("The connection dropped. Please try again.")).toBeTruthy();
  expect(screen.getByRole("button", { name: /Carry on/ })).toBeTruthy();
});

test("a piece chosen with Not this? stays chosen while the camera still sees the other", async () => {
  const f = fakeDeps();
  render(<App deps={f.deps} />);
  await screen.findByRole("heading", { name: "Head of Sekhmet" });
  fireEvent.click(screen.getByRole("button", { name: /Not this\?/ }));
  fireEvent.click(screen.getByRole("button", { name: /Lion's head/ }));
  await act(() => new Promise((resolve) => setTimeout(resolve, 60)));
  expect(screen.getByRole("heading", { name: "Lion's head" })).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "Head of Sekhmet" })).toBeNull();
});

test("a question is sent when the phone stops listening by itself", async () => {
  let ended: ((text: string, failure: string | null) => void) | undefined;
  const f = fakeDeps({ speech: { supported: true, start: (_onText, onEnd) => { ended = onEnd; }, stop: async () => "", abort() {} } });
  await tapTellMe(f);
  act(() => {
    f.emit({ type: "turn_started", kind: "tell", part_index: 0, part_title: "Who she is", part_count: 2 });
    f.emit({ type: "sentence", index: 0, text: "She was a goddess of fire.", citations: ["13.181#p2"], show: [] });
    f.audioFrame(0);
  });
  fireEvent.click(await screen.findByRole("button", { name: "Ask" }));
  act(() => ended!("What was the slot for?", null));
  expect(f.sent.at(-1)).toMatchObject({ type: "turn", kind: "ask", object_id: "13.181", question: "What was the slot for?" });
});

test("the guide still works when the phone cannot store the visit", async () => {
  const f = fakeDeps({
    loadMemory: async () => { throw new Error("blocked"); },
    saveMemory: async () => { throw new Error("blocked"); },
  });
  await tapTellMe(f);
  expect(f.sent.at(-1)).toMatchObject({ type: "turn", kind: "tell", object_id: "13.181" });
});

test("in demo mode the app is a phone frame, and → walks the tour on", async () => {
  const f = fakeDeps();
  let walked = 0;
  const { container } = render(<App deps={f.deps} demo={{ next: () => { walked++; } }} />);
  await screen.findByRole("heading", { name: "Head of Sekhmet" });
  expect(container.querySelector("main")?.classList.contains("demo")).toBe(true);
  fireEvent.keyDown(window, { code: "ArrowRight" });
  expect(walked).toBe(1);
});

test("outside demo mode the frame is the whole screen and the demo keys do nothing", async () => {
  const f = fakeDeps();
  const { container } = render(<App deps={f.deps} demo={null} />);
  await screen.findByRole("heading", { name: "Head of Sekhmet" });
  expect(container.querySelector("main")?.classList.contains("demo")).toBe(false);
  fireEvent.keyDown(window, { code: "ArrowRight" });
  fireEvent.keyDown(window, { code: "KeyR" });
  expect(container.querySelector(".rec-dot")).toBeNull();
});
