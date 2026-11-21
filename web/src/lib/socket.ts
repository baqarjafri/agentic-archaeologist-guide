export type ServerEvent =
  | { type: "turn_started"; kind: string; part_index: number | null; part_title: string | null; part_count: number; audio?: string }
  | { type: "connection"; key: string; theme: string; other_object: string; passages: string[] }
  | { type: "sentence"; index: number; text: string; citations: string[]; show: string[] }
  | { type: "dropped"; text: string; reason: string }
  | { type: "voice_failed"; index: number; message: string }
  | { type: "turn_done"; kind: string; part_index: number | null; sentences: number }
  | { type: "error"; message: string };

type Handlers = {
  onEvent: (event: ServerEvent) => void;
  /** A piece of a sentence's audio, or null once that sentence's audio is complete. */
  onAudio: (index: number, chunk: ArrayBuffer | null) => void;
  onStatus?: (open: boolean) => void;
};

const OPEN = 1;
const END = 1;
const RETRY_MS = 1500;

/** A binary frame: the sentence index (4 bytes, big-endian), the kind (1 byte: 0 audio, 1 end), then 16-bit PCM. */
export function parseFrame(data: ArrayBuffer): { index: number; chunk: ArrayBuffer | null } {
  const view = new DataView(data);
  return { index: view.getUint32(0, false), chunk: view.getUint8(4) === END ? null : data.slice(5) };
}

export class GuideSocket {
  private ws: WebSocket | null = null;
  private closed = false;
  private pending: string[] = [];
  private retry: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private readonly url: string,
    private readonly handlers: Handlers,
    private readonly factory: (url: string) => WebSocket = (u) => new WebSocket(u),
  ) {}

  connect(): void {
    this.closed = false;
    const ws = this.factory(this.url);
    ws.binaryType = "arraybuffer";
    ws.onopen = () => {
      this.handlers.onStatus?.(true);
      this.pending.splice(0).forEach((text) => ws.send(text));
    };
    ws.onmessage = (message) => {
      if (typeof message.data === "string") {
        this.handlers.onEvent(JSON.parse(message.data) as ServerEvent);
      } else {
        const { index, chunk } = parseFrame(message.data as ArrayBuffer);
        this.handlers.onAudio(index, chunk);
      }
    };
    ws.onclose = (event) => {
      this.pending = []; // the app gives up on a turn when the link drops, so its queued messages must not replay later
      this.handlers.onStatus?.(false);
      // 4401: the server refused the access code, so trying again cannot help
      if (!this.closed && event?.code !== 4401) {
        this.retry = setTimeout(() => {
          if (!this.closed) this.connect();
        }, RETRY_MS);
      }
    };
    this.ws = ws;
  }

  send(payload: object): void {
    const text = JSON.stringify(payload);
    if (this.ws && this.ws.readyState === OPEN) this.ws.send(text);
    else this.pending.push(text);
  }

  cancel(): void {
    this.send({ type: "cancel" });
  }

  close(): void {
    this.closed = true;
    if (this.retry) clearTimeout(this.retry);
    this.ws?.close();
  }
}
