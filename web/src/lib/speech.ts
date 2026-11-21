type RecognitionResult = { isFinal: boolean; 0: { transcript: string } };
type RecognitionEvent = { results: ArrayLike<RecognitionResult> };
type Recognition = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((event: RecognitionEvent) => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
};
export type RecognitionCtor = new () => Recognition;
export type OnEnd = (text: string, failure: string | null) => void;

const STOP_WAIT_MS = 2000;

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function recognitionCtor(w: any = window): RecognitionCtor | null {
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

/**
 * Push-to-talk: start() on the first tap, stop() on the second resolves with the transcript.
 * Android ends recognition by itself after a pause; then `onEnd` receives what was heard, and any error.
 */
export class SpeechInput {
  private rec: Recognition | null = null;
  private finalText = "";
  private interimText = "";
  private failure: string | null = null;
  private resolveStop: ((text: string) => void) | null = null;

  constructor(private readonly ctor: RecognitionCtor | null = recognitionCtor(), private readonly lang = "en-GB") {}

  get supported(): boolean {
    return this.ctor !== null;
  }

  private text(): string {
    const finals = this.finalText.trim();
    const interim = this.interimText.trim();
    // Android Chrome can repeat the final text at the start of the interim text: show it once.
    const joined = finals && interim.toLowerCase().startsWith(finals.toLowerCase()) ? interim : `${finals} ${interim}`;
    return joined.replace(/\s+/g, " ").trim();
  }

  start(onText: (text: string) => void, onEnd?: OnEnd): void {
    if (!this.ctor) throw new Error("speech recognition is not available");
    this.abort();
    this.finalText = "";
    this.interimText = "";
    this.failure = null;
    const rec = new this.ctor();
    rec.lang = this.lang;
    rec.interimResults = true;
    rec.continuous = true;
    rec.onresult = (event) => {
      if (this.rec !== rec) return; // a late result from an earlier recogniser
      let finals = "";
      let interim = "";
      for (let i = 0; i < event.results.length; i++) {
        const result = event.results[i];
        const piece = result[0].transcript;
        if (!result.isFinal) interim = interim ? `${interim} ${piece}` : piece;
        // Android Chrome can repeat earlier final text inside each new final result: keep the longer copy once.
        else if (finals && piece.trim().toLowerCase().startsWith(finals.trim().toLowerCase())) finals = piece;
        else finals = finals ? `${finals} ${piece}` : piece;
      }
      this.finalText = finals;
      this.interimText = interim;
      onText(this.text());
    };
    rec.onerror = (event) => {
      if (this.rec === rec) this.failure = event.error ?? "error";
    };
    rec.onend = () => {
      if (this.rec !== rec) return;
      const text = this.text();
      this.rec = null;
      if (this.resolveStop) {
        this.resolveStop(text);
        this.resolveStop = null;
      } else {
        onEnd?.(text, this.failure); // ended by itself: a pause on Android, or an error such as a blocked microphone
      }
    };
    this.rec = rec;
    rec.start();
  }

  stop(): Promise<string> {
    const rec = this.rec;
    if (!rec) return Promise.resolve(this.text());
    return new Promise((resolve) => {
      this.resolveStop = resolve;
      rec.stop();
      // Chrome does not always report the end: answer with what was heard after a short wait anyway.
      setTimeout(() => {
        if (this.resolveStop === resolve) {
          const text = this.text();
          this.abort();
          resolve(text);
        }
      }, STOP_WAIT_MS);
    });
  }

  abort(): void {
    const rec = this.rec;
    this.rec = null;
    this.resolveStop = null;
    rec?.abort();
  }
}
