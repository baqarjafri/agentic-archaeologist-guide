type QueueEvents = { onStart: (index: number) => void; onIdle: () => void };
type Clip = { chunks: Float32Array[]; seconds: number; ended: boolean };

const RATE = 24000; // the server streams 16-bit mono PCM at 24 kHz
const CUSHION_SECONDS = 0.3; // a sentence starts once this much of it has arrived: rides out a 0.3 s stall on the phone's link
const REFILL_SECONDS = 0.5; // audio that ran dry mid-sentence waits for this much again, so a slow link pauses rather than stutters
const HOLD_SECONDS = 3; // a caption with no voice stays up this long, so it can be read

function concat(parts: Float32Array[]): Float32Array {
  if (parts.length === 1) return parts[0];
  const out = new Float32Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) {
    out.set(p, at);
    at += p.length;
  }
  return out;
}

/** 16-bit little-endian PCM (every Chrome on Android is little-endian) as samples between -1 and 1.
 *  The chunk must start on an even byte: `parseFrame` copies it out of the frame, so it does. */
function toSamples(chunk: ArrayBuffer): Float32Array {
  const pcm = new Int16Array(chunk, 0, chunk.byteLength >> 1);
  const samples = new Float32Array(pcm.length);
  for (let i = 0; i < pcm.length; i++) samples[i] = pcm[i] / 32768;
  return samples;
}

/**
 * Plays each sentence's streamed audio in sentence order; stop() silences at once.
 * Audio plays without gaps while the link keeps up; if it falls behind, the sentence pauses to refill rather than stutter.
 */
export class AudioQueue {
  private clips = new Map<number, Clip>();
  private current = 0;
  private started = false;
  private sources: AudioBufferSourceNode[] = [];
  private nextStart = 0;
  private total: number | null = null;
  private stopped = false;
  private starved = false; // this sentence's audio ran dry: wait for REFILL_SECONDS before playing on

  /** `output` is where the voice goes: the speakers unless given (the demo recorder taps a shared bus). */
  constructor(
    private readonly ctx: AudioContext,
    private readonly events: QueueEvents,
    private readonly output: AudioNode = ctx.destination,
  ) {}

  get busy(): boolean {
    return this.started;
  }

  /** Start a new turn. */
  begin(): void {
    // Android suspends audio when the screen sleeps; a turn always starts from a tap, so the browser lets it resume.
    void this.ctx.resume().catch(() => {});
    this.stop();
    this.stopped = false;
    this.current = 0;
    this.total = null;
  }

  /** A piece of sentence `index`'s audio: 16-bit PCM. */
  push(index: number, chunk: ArrayBuffer): void {
    if (this.stopped) return;
    const samples = toSamples(chunk);
    if (!samples.length) return; // Chrome cannot make a buffer of no samples
    const clip = this.clip(index);
    clip.chunks.push(samples);
    clip.seconds += samples.length / RATE;
    this.pump();
  }

  /** Sentence `index`'s audio is complete. */
  end(index: number): void {
    if (this.stopped) return;
    this.clip(index).ended = true;
    this.pump();
  }

  /** The server could not voice this sentence: hold its caption for a silent pause, then move on. */
  skip(index: number): void {
    if (this.stopped) return;
    const clip = this.clip(index);
    clip.chunks.push(new Float32Array(Math.round(RATE * HOLD_SECONDS)));
    clip.seconds += HOLD_SECONDS;
    clip.ended = true;
    this.pump();
  }

  /** The turn produced `total` sentences; report idle after the last one ends. */
  finish(total: number): void {
    this.total = total;
    this.pump();
  }

  stop(): void {
    this.stopped = true;
    this.clips.clear();
    for (const source of this.sources) {
      source.onended = null;
      try {
        source.stop();
      } catch {
        // already stopped
      }
    }
    this.sources = [];
    this.started = false;
    this.starved = false;
  }

  private clip(index: number): Clip {
    let clip = this.clips.get(index);
    if (!clip) {
      clip = { chunks: [], seconds: 0, ended: false };
      this.clips.set(index, clip);
    }
    return clip;
  }

  private pump(): void {
    if (this.stopped) return;
    // Android suspends audio when the screen sleeps, even mid-sentence; a suspended clock never ends a sentence.
    if (this.ctx.state === "suspended") void this.ctx.resume().catch(() => {});
    for (;;) {
      const clip = this.clips.get(this.current);
      if (!clip) break;
      if (!this.started || this.starved) {
        if (!clip.ended && clip.seconds < (this.started ? REFILL_SECONDS : CUSHION_SECONDS)) break;
        if (!this.started) {
          this.started = true;
          this.events.onStart(this.current);
        }
        this.starved = false;
        this.nextStart = this.ctx.currentTime;
      }
      if (clip.chunks.length) this.schedule(concat(clip.chunks.splice(0))); // what has arrived plays as one buffer
      clip.seconds = 0; // from here, seconds counts audio not yet scheduled
      if (!clip.ended || this.sources.length) break; // more audio to come, or the last buffer is still playing
      this.clips.delete(this.current);
      this.current++;
      this.started = false;
    }
    if (!this.started && this.total !== null && this.current >= this.total) {
      this.total = null;
      this.events.onIdle();
    }
  }

  private schedule(samples: Float32Array): void {
    const buffer = this.ctx.createBuffer(1, samples.length, RATE);
    buffer.getChannelData(0).set(samples);
    const source = this.ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(this.output);
    const at = Math.max(this.ctx.currentTime, this.nextStart);
    source.start(at);
    this.nextStart = at + samples.length / RATE;
    this.sources.push(source);
    source.onended = () => {
      this.sources = this.sources.filter((s) => s !== source);
      if (!this.sources.length) {
        this.starved = this.started; // everything scheduled has played: if the sentence is not over, it ran dry
        this.pump();
      }
    };
  }
}
