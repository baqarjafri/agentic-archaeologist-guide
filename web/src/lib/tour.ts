/**
 * Laptop demos: prepared gallery footage plays as the camera view. A tour is one video of walks and hovers;
 * a hover is a ping-pong loop (forwards, then reversed) made by server/scripts/make_tour.py, so jumping from its
 * last frame back to its first is invisible. The footage hovers on a piece for as long as the conversation lasts.
 */
export type Segment = { kind: "walk" | "hover"; start: number; end: number; piece?: string };
export type Tour = { video: string; segments: Segment[] };

/** The parts of a <video> the player uses, so tests can drive it with a fake. */
export type VideoLike = {
  src: string;
  currentTime: number;
  muted: boolean;
  loop: boolean;
  play(): Promise<void>;
  pause(): void;
  setAttribute(name: string, value: string): void;
  removeAttribute(name: string): void;
  load(): void;
};

const EDGE = 1 / 30; // one frame at 30 fps: a segment ends when the next frame would pass its end

export class TourPlayer {
  private index = 0;
  private stopped = false;

  constructor(private readonly video: VideoLike, private readonly tour: Tour, private readonly base: string) {}

  get segment(): Segment {
    return this.tour.segments[this.index];
  }

  async start(): Promise<void> {
    if (!this.tour.segments.length) throw new Error("the tour has no segments");
    this.video.muted = true;
    this.video.loop = false;
    this.video.setAttribute("playsinline", "true");
    this.video.src = `${this.base}/${this.tour.video}`;
    this.index = 0;
    this.video.currentTime = this.tour.segments[0].start;
    await this.video.play();
  }

  /** Called for every presented frame with that frame's media time. */
  tick(time: number): void {
    if (this.stopped) return;
    const seg = this.segment;
    if (time < seg.end - EDGE) return;
    if (seg.kind === "hover") {
      this.video.currentTime = seg.start;
      return;
    }
    if (this.index === this.tour.segments.length - 1) {
      this.video.pause(); // a final walk ends on its last frame
      return;
    }
    this.index += 1;
    const next = this.segment;
    if (Math.abs(next.start - seg.end) > EDGE) this.video.currentTime = next.start;
  }

  /** → : in a hover, walk on; in a walk, jump to the next hover. The last hover stays. */
  next(): void {
    const segments = this.tour.segments;
    const target = this.segment.kind === "hover"
      ? (this.index + 1 < segments.length ? this.index + 1 : -1)
      : segments.findIndex((s, i) => i > this.index && s.kind === "hover");
    if (target < 0) return;
    this.index = target;
    this.video.currentTime = segments[target].start;
    void this.video.play().catch(() => {});
  }

  stop(): void {
    this.stopped = true;
    this.video.pause();
    this.video.removeAttribute("src");
    this.video.load();
  }
}

type FrameMeta = { mediaTime: number };
type FrameVideo = HTMLVideoElement & {
  requestVideoFrameCallback?: (callback: (now: number, meta: FrameMeta) => void) => number;
};

/** Calls `onFrame` with each presented frame's time; falls back to timeupdate where the frame callback is missing. */
export function watchFrames(video: HTMLVideoElement, onFrame: (time: number) => void): () => void {
  const v = video as FrameVideo;
  let live = true;
  if (typeof v.requestVideoFrameCallback === "function") {
    const loop = (_now: number, meta: FrameMeta) => {
      if (!live) return;
      onFrame(meta.mediaTime);
      v.requestVideoFrameCallback!(loop);
    };
    v.requestVideoFrameCallback(loop);
    return () => { live = false; };
  }
  const handler = () => onFrame(video.currentTime);
  video.addEventListener("timeupdate", handler);
  return () => {
    live = false;
    video.removeEventListener("timeupdate", handler);
  };
}

export type TourCamera = {
  startCamera: (video: HTMLVideoElement) => Promise<MediaStream | null>;
  stopCamera: (stream: MediaStream | null) => void;
  next: () => void;
};

async function fetchTour(url: string): Promise<Tour> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  return (await response.json()) as Tour;
}

/**
 * The guide's camera slots, filled by the tour. startCamera returns a token in place of a MediaStream; stopCamera
 * stops only the tour that token started, because useGuide stops a start whose effect was already cleaned up.
 */
export function tourCamera(base = "/demo-media", load: (url: string) => Promise<Tour> = fetchTour): TourCamera {
  let generation = 0;
  let current: { player: TourPlayer; unwatch: () => void; token: MediaStream } | null = null;
  const halt = () => {
    current?.unwatch();
    current?.player.stop();
    current = null;
  };
  return {
    startCamera: async (video) => {
      const mine = ++generation;
      const tour = await load(`${base}/tour.json`);
      if (mine !== generation) return null; // a newer start replaced this one
      halt();
      const player = new TourPlayer(video, tour, base);
      const token = {} as MediaStream;
      current = { player, unwatch: watchFrames(video, (t) => player.tick(t)), token };
      await player.start();
      return token;
    },
    stopCamera: (stream) => {
      if (current && stream !== null && stream === current.token) halt();
    },
    next: () => current?.player.next(),
  };
}
