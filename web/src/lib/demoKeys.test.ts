import { afterEach, expect, test } from "vitest";
import type { ButtonState } from "../components/OnCamera";
import { bindDemoKeys } from "./demoKeys";

let unbind: (() => void) | null = null;
afterEach(() => { unbind?.(); unbind = null; document.body.innerHTML = ""; });

function setup(initial: ButtonState) {
  let state = initial;
  const calls: string[] = [];
  unbind = bindDemoKeys(window, {
    buttonState: () => state,
    press: () => {
      calls.push("press");
      if (state === "ready" || state === "speaking") state = "listening";
      else if (state === "listening") state = "thinking";
    },
    next: () => calls.push("next"),
    record: () => calls.push("record"),
    close: () => calls.push("close"),
    tap: (selector) => calls.push(`tap ${selector}`),
  });
  const key = (type: "keydown" | "keyup", code: string, repeat = false) =>
    window.dispatchEvent(new KeyboardEvent(type, { code, repeat, cancelable: true }));
  return { calls, key };
}

test("holding Space asks: one press on the way down, one on the way up, repeats ignored", () => {
  const { calls, key } = setup("ready");
  key("keydown", "Space");
  key("keydown", "Space", true);
  key("keydown", "Space", true);
  key("keyup", "Space");
  expect(calls).toEqual(["tap .primary", "press", "tap .primary", "press"]);
});

test("Space does nothing while the main button cannot listen", () => {
  const { calls, key } = setup("idle");
  key("keydown", "Space");
  key("keyup", "Space");
  expect(calls).toEqual([]);
});

test("Enter presses, → walks on, R records, Esc closes", () => {
  const { calls, key } = setup("idle");
  key("keydown", "Enter");
  key("keydown", "ArrowRight");
  key("keydown", "KeyR");
  key("keydown", "Escape");
  expect(calls).toEqual(["tap .primary", "press", "next", "record", "close"]);
});

test("keys typed into a text box are left alone", () => {
  const { calls } = setup("ready");
  const input = document.createElement("input");
  document.body.appendChild(input);
  input.dispatchEvent(new KeyboardEvent("keydown", { code: "KeyR", bubbles: true }));
  expect(calls).toEqual([]);
});

test("unbinding removes the keys", () => {
  const { calls, key } = setup("ready");
  unbind?.();
  unbind = null;
  key("keydown", "ArrowRight");
  expect(calls).toEqual([]);
});
