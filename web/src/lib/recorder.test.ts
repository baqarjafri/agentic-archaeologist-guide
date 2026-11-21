import { expect, test } from "vitest";
import { SessionRecorder, fileName, pickType, type MediaRecorderLike, type RecorderDeps } from "./recorder";

class Node {
  connections: unknown[] = [];
  connect(node: unknown) { this.connections.push(node); }
  disconnect(node?: unknown) { this.connections = node === undefined ? [] : this.connections.filter((c) => c !== node); }
}

type FakeTrack = { kind: string; stopped: boolean; stop(): void; addEventListener(): void };
const track = (kind: string): FakeTrack => ({ kind, stopped: false, stop() { this.stopped = true; }, addEventListener() {} });
const stream = (tracks: FakeTrack[]) => ({
  getTracks: () => tracks,
  getVideoTracks: () => tracks.filter((t) => t.kind === "video"),
  getAudioTracks: () => tracks.filter((t) => t.kind === "audio"),
}) as unknown as MediaStream;

class FakeRecorder implements MediaRecorderLike {
  state = "inactive";
  ondataavailable: ((e: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  constructor(public stream: MediaStream, public mimeType: string) {}
  start() { this.state = "recording"; }
  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["frames"]) });
    this.onstop?.();
  }
}

function setup(over: Partial<RecorderDeps> = {}) {
  const destination = new Node();
  const mixTrack = track("audio");
  const tap = Object.assign(new Node(), { stream: stream([mixTrack]) });
  const micNode = new Node();
  const voiceOut = Object.assign(new Node(), { stream: stream([track("audio")]) });
  const voiceIn = new Node();
  const ctx = { destination, resume: async () => {}, createMediaStreamDestination: () => voiceOut };
  const mixer = {
    closed: false, resume: async () => {}, close: async () => { mixer.closed = true; },
    createMediaStreamDestination: () => tap,
    createMediaStreamSource: (s: MediaStream) => (s === voiceOut.stream ? voiceIn : micNode),
  };
  const voice = new Node();
  const pictureTrack = track("video");
  const micTrack = track("audio");
  const log = {
    display: [] as object[], cropped: [] as unknown[], saved: [] as { blob: Blob; name: string }[],
    recorders: [] as FakeRecorder[], states: [] as boolean[],
  };
  const frame = document.createElement("main");
  const deps: RecorderDeps = {
    getDisplayMedia: async (options) => { log.display.push(options); return stream([pictureTrack]); },
    getUserMedia: async () => stream([micTrack]),
    makeMixer: () => mixer as unknown as AudioContext,
    cropTo: async (_track, f) => { log.cropped.push(f); },
    makeStream: (tracks) => stream(tracks as unknown as FakeTrack[]),
    makeRecorder: (s, m) => { const r = new FakeRecorder(s, m); log.recorders.push(r); return r; },
    isTypeSupported: (t) => t === "video/mp4",
    save: (blob, name) => { log.saved.push({ blob, name }); },
    now: () => new Date(2026, 10, 21, 15, 4, 5),
    ...over,
  };
  const recorder = new SessionRecorder(ctx as unknown as AudioContext, voice as unknown as AudioNode, frame, deps,
    (on) => { log.states.push(on); });
  return { recorder, log, voice, voiceOut, voiceIn, mixer, micNode, tap, destination, pictureTrack, micTrack, mixTrack, frame };
}

test("pickType prefers MP4, then WebM, then the browser's default", () => {
  expect(pickType((t) => t.startsWith("video/mp4"))).toEqual({ mimeType: "video/mp4;codecs=avc1.42E01E,mp4a.40.2", ext: "mp4" });
  expect(pickType((t) => t === "video/webm")).toEqual({ mimeType: "video/webm", ext: "webm" });
  expect(pickType(() => false)).toEqual({ mimeType: "", ext: "webm" });
});

test("fileName stamps the start time", () => {
  expect(fileName(new Date(2026, 10, 21, 9, 3, 7), "mp4")).toBe("agentic-archaeologist-session-2026-11-21-090307.mp4");
});

test("records the current tab cropped to the phone frame, with the voice and the mic mixed into one track", async () => {
  const s = setup();
  await s.recorder.start();
  expect(s.log.display[0]).toMatchObject({ audio: false, preferCurrentTab: true });
  expect(s.log.cropped).toEqual([s.frame]);
  expect(s.voice.connections).toContain(s.voiceOut); // the voice crosses into the recording's own 48 kHz mix
  expect(s.voiceIn.connections).toEqual([s.tap]);
  expect(s.micNode.connections).toEqual([s.tap]); // the microphone goes to the recording only, never the speakers
  expect(s.destination.connections).toEqual([]);
  const r = s.log.recorders[0];
  expect(r.mimeType).toBe("video/mp4");
  expect(r.stream.getVideoTracks()).toEqual([s.pictureTrack]);
  expect(r.stream.getAudioTracks()).toEqual([s.mixTrack]);
  expect(r.state).toBe("recording");
  expect(s.recorder.recording).toBe(true);
  expect(s.log.states).toEqual([true]);
});

test("stopping saves the file and releases the tab, the mic and the voice tap", async () => {
  const s = setup();
  await s.recorder.start();
  await s.recorder.stop();
  expect(s.log.saved).toHaveLength(1);
  expect(s.log.saved[0].name).toBe("agentic-archaeologist-session-2026-11-21-150405.mp4");
  expect(s.log.saved[0].blob.size).toBeGreaterThan(0);
  expect(s.voice.connections).not.toContain(s.voiceOut);
  expect(s.micNode.connections).toEqual([]);
  expect(s.mixer.closed).toBe(true);
  expect(s.pictureTrack.stopped).toBe(true);
  expect(s.micTrack.stopped).toBe(true);
  expect(s.recorder.recording).toBe(false);
  expect(s.log.states).toEqual([true, false]);
});

test("toggle starts, then stops", async () => {
  const s = setup();
  await s.recorder.toggle();
  expect(s.recorder.recording).toBe(true);
  await s.recorder.toggle();
  expect(s.recorder.recording).toBe(false);
  expect(s.log.saved).toHaveLength(1);
});

test("if the microphone is refused, the shared tab is released and nothing records", async () => {
  const s = setup({ getUserMedia: async () => { throw new Error("NotAllowedError"); } });
  await expect(s.recorder.start()).rejects.toThrow("NotAllowedError");
  expect(s.pictureTrack.stopped).toBe(true);
  expect(s.recorder.recording).toBe(false);
  expect(s.log.recorders).toEqual([]);
});

test("if the recorder already stopped on its own, stopping releases everything instead of waiting forever", async () => {
  const s = setup();
  await s.recorder.start();
  s.log.recorders[0].state = "inactive"; // Chrome stops a MediaRecorder itself when its encoder fails
  await s.recorder.stop();
  expect(s.log.saved).toEqual([]); // nothing was recorded, so no empty file
  expect(s.pictureTrack.stopped).toBe(true);
  expect(s.micTrack.stopped).toBe(true);
  expect(s.recorder.recording).toBe(false);
});
