import type { ButtonState } from "../components/OnCamera";

export type DemoKeyHandlers = {
  buttonState: () => ButtonState;
  press: () => void;
  next: () => void;
  record: () => void;
  close: () => void;
  /** Show a finger tap on the element matching this selector. */
  tap: (selector: string) => void;
};

const TYPING = new Set(["INPUT", "TEXTAREA"]);

/**
 * Laptop demo keys: Enter taps the main button, holding Space asks a question (press to listen, release to send),
 * → walks on, R starts or stops recording, Esc closes a sheet. Returns a function that removes them.
 */
export function bindDemoKeys(target: Window, h: DemoKeyHandlers): () => void {
  let holding = false;
  const down = (e: KeyboardEvent) => {
    if (e.target instanceof HTMLElement && TYPING.has(e.target.tagName)) return; // typing a question by hand
    if (e.code === "Space") e.preventDefault(); // never scroll or click a focused button
    if (e.repeat) return;
    switch (e.code) {
      case "Space": {
        const state = h.buttonState();
        if (state === "ready" || state === "speaking") {
          holding = true;
          h.tap(".primary");
          h.press();
        }
        return;
      }
      case "Enter":
        e.preventDefault(); // a focused button would otherwise click too
        h.tap(".primary");
        h.press();
        return;
      case "ArrowRight":
        e.preventDefault();
        h.next();
        return;
      case "KeyR":
        e.preventDefault();
        h.record();
        return;
      case "Escape":
        h.close();
        return;
    }
  };
  const up = (e: KeyboardEvent) => {
    if (e.code !== "Space") return;
    e.preventDefault();
    if (!holding) return;
    holding = false;
    if (h.buttonState() === "listening") {
      h.tap(".primary");
      h.press();
    }
  };
  target.addEventListener("keydown", down);
  target.addEventListener("keyup", up);
  return () => {
    target.removeEventListener("keydown", down);
    target.removeEventListener("keyup", up);
  };
}
