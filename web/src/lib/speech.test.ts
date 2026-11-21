import { expect, test } from "vitest";
import { recognitionCtor, SpeechInput } from "./speech";

type Part = [string, boolean];

class FakeRecognition {
  static last: FakeRecognition;
  lang = "";
  interimResults = false;
  continuous = false;
  onresult: ((e: unknown) => void) | null = null;
  onerror: ((e: unknown) => void) | null = null;
  onend: (() => void) | null = null;
  started = false;
  constructor() { FakeRecognition.last = this; }
  start() { this.started = true; }
  stop() { this.onend?.(); }
  abort() {}
  emit(parts: Part[]) {
    this.onresult?.({ results: parts.map(([t, f]) => Object.assign([{ transcript: t }], { isFinal: f })) });
  }
}

test("finds the browser's recognition constructor", () => {
  expect(recognitionCtor({ webkitSpeechRecognition: FakeRecognition })).toBe(FakeRecognition);
  expect(recognitionCtor({})).toBeNull();
});

test("streams a live transcript and returns the final text on stop", async () => {
  const input = new SpeechInput(FakeRecognition as never);
  const seen: string[] = [];
  input.start((text) => seen.push(text));
  const rec = FakeRecognition.last;
  expect(rec.started && rec.lang === "en-GB" && rec.interimResults).toBe(true);
  rec.emit([["what is that", false]]);
  rec.emit([["What is that slot", true], [" on her head", false]]);
  expect(seen).toEqual(["what is that", "What is that slot on her head"]);
  expect(await input.stop()).toBe("What is that slot on her head");
});

test("reports when recognition is unavailable", () => {
  expect(new SpeechInput(null).supported).toBe(false);
});

test("text that Android repeats inside each new result is kept once", async () => {
  const input = new SpeechInput(FakeRecognition as never);
  input.start(() => {});
  const rec = FakeRecognition.last;
  rec.emit([["what is that", true], ["what is that slot on her head", true], ["what is that slot on her head for", false]]);
  expect(await input.stop()).toBe("what is that slot on her head for");
});

test("recognition that ends by itself hands over what was heard", () => {
  const input = new SpeechInput(FakeRecognition as never);
  const ended: [string, string | null][] = [];
  input.start(() => {}, (text, failure) => ended.push([text, failure]));
  const rec = FakeRecognition.last;
  rec.emit([["What is that slot", true]]);
  rec.onend?.();
  expect(ended).toEqual([["What is that slot", null]]);
});

test("a blocked microphone is reported when recognition ends", () => {
  const input = new SpeechInput(FakeRecognition as never);
  const ended: [string, string | null][] = [];
  input.start(() => {}, (text, failure) => ended.push([text, failure]));
  FakeRecognition.last.onerror?.({ error: "not-allowed" });
  FakeRecognition.last.onend?.();
  expect(ended).toEqual([["", "not-allowed"]]);
});
