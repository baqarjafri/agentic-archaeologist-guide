/**
 * Laptop demos: records the phone frame (the current tab, cropped with Region Capture) with one audio track that
 * mixes the guide's voice, tapped from the voice bus, and the presenter's microphone. The microphone goes to the
 * recording only, never to the speakers, so the presenter hears only the guide (wear headphones).
 */
export type MediaRecorderLike = {
  state: string;
  ondataavailable: ((e: { data: Blob }) => void) | null;
  onstop: (() => void) | null;
  start(timeslice?: number): void;
  stop(): void;
};

export type RecorderDeps = {
  getDisplayMedia: (options: object) => Promise<MediaStream>;
  getUserMedia: (constraints: MediaStreamConstraints) => Promise<MediaStream>;
  /** The recording's own 48 kHz mix: Chrome's AAC encoder refuses the voice bus's 24 kHz. */
  makeMixer: () => AudioContext;
  cropTo: (track: MediaStreamTrack, frame: Element) => Promise<void>;
  makeStream: (tracks: MediaStreamTrack[]) => MediaStream;
  makeRecorder: (stream: MediaStream, mimeType: string) => MediaRecorderLike;
  isTypeSupported: (mimeType: string) => boolean;
  save: (blob: Blob, name: string) => void;
  now: () => Date;
};

const TYPES: [string, string][] = [
  ["video/mp4;codecs=avc1.42E01E,mp4a.40.2", "mp4"], // plays in PowerPoint
  ["video/mp4", "mp4"],
  ["video/webm;codecs=vp9,opus", "webm"],
  ["video/webm", "webm"],
];

export function pickType(isTypeSupported: (mimeType: string) => boolean): { mimeType: string; ext: string } {
  for (const [mimeType, ext] of TYPES) if (isTypeSupported(mimeType)) return { mimeType, ext };
  return { mimeType: "", ext: "webm" };
}

export function fileName(at: Date, ext: string): string {
  const p = (n: number) => String(n).padStart(2, "0");
  const stamp = `${at.getFullYear()}-${p(at.getMonth() + 1)}-${p(at.getDate())}-${p(at.getHours())}${p(at.getMinutes())}${p(at.getSeconds())}`;
  return `agentic-archaeologist-session-${stamp}.${ext}`;
}

type Session = {
  recorder: MediaRecorderLike;
  picture: MediaStream;
  mic: MediaStream;
  micSource: AudioNode;
  voiceOut: MediaStreamAudioDestinationNode;
  mixer: AudioContext;
  chunks: Blob[];
  type: { mimeType: string; ext: string };
  startedAt: Date;
};

export class SessionRecorder {
  private session: Session | null = null;
  private stopping: Promise<void> | null = null;

  constructor(
    private readonly ctx: AudioContext,
    private readonly voice: AudioNode,
    private readonly frame: Element,
    private readonly deps: RecorderDeps,
    private readonly onChange: (recording: boolean) => void = () => {},
  ) {}

  get recording(): boolean {
    return this.session !== null;
  }

  toggle(): Promise<void> {
    return this.recording ? this.stop() : this.start();
  }

  async start(): Promise<void> {
    if (this.session) return;
    void this.ctx.resume();
    const picture = await this.deps.getDisplayMedia({
      video: { frameRate: 30 }, audio: false, preferCurrentTab: true, selfBrowserSurface: "include",
    });
    const [video] = picture.getVideoTracks();
    try {
      await this.deps.cropTo(video, this.frame);
      const mic = await this.deps.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      // The voice leaves its 24 kHz context as a stream and is resampled into the 48 kHz mix, with the mic.
      const voiceOut = this.ctx.createMediaStreamDestination();
      this.voice.connect(voiceOut);
      const mixer = this.deps.makeMixer();
      void mixer.resume();
      const tap = mixer.createMediaStreamDestination();
      mixer.createMediaStreamSource(voiceOut.stream).connect(tap);
      const micSource = mixer.createMediaStreamSource(mic);
      micSource.connect(tap); // to the recording only
      const stream = this.deps.makeStream([video, ...tap.stream.getAudioTracks()]);
      const type = pickType(this.deps.isTypeSupported);
      const recorder = this.deps.makeRecorder(stream, type.mimeType);
      const chunks: Blob[] = [];
      recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
      this.session = { recorder, picture, mic, micSource, voiceOut, mixer, chunks, type, startedAt: this.deps.now() };
      video.addEventListener("ended", () => { void this.stop(); }); // Chrome's own "Stop sharing" button
      recorder.start(1000);
      this.onChange(true);
    } catch (error) {
      picture.getTracks().forEach((t) => t.stop());
      throw error;
    }
  }

  stop(): Promise<void> {
    const s = this.session;
    if (!s) return this.stopping ?? Promise.resolve();
    this.session = null;
    this.stopping = new Promise<void>((resolve) => {
      const finish = () => {
        if (s.chunks.length) {
          this.deps.save(new Blob(s.chunks, { type: s.type.mimeType || "video/webm" }), fileName(s.startedAt, s.type.ext));
        }
        this.voice.disconnect(s.voiceOut);
        s.micSource.disconnect();
        void s.mixer.close();
        s.mic.getTracks().forEach((t) => t.stop());
        s.picture.getTracks().forEach((t) => t.stop());
        this.stopping = null;
        this.onChange(false);
        resolve();
      };
      if (s.recorder.state === "inactive") {
        finish(); // it already stopped on its own (an encoder error): no stop event will come
        return;
      }
      s.recorder.onstop = finish;
      s.recorder.stop();
    });
    return this.stopping;
  }
}

type CropTargetApi = { fromElement(element: Element): Promise<unknown> };

export function realRecorderDeps(): RecorderDeps {
  return {
    getDisplayMedia: (options) => navigator.mediaDevices.getDisplayMedia(options as DisplayMediaStreamOptions),
    getUserMedia: (constraints) => navigator.mediaDevices.getUserMedia(constraints),
    makeMixer: () => new AudioContext({ sampleRate: 48000 }),
    cropTo: async (track, frame) => {
      const CropTarget = (window as unknown as { CropTarget?: CropTargetApi }).CropTarget;
      const cropTo = (track as unknown as { cropTo?: (target: unknown) => Promise<void> }).cropTo;
      if (!CropTarget || !cropTo) return; // no Region Capture: the whole tab is recorded
      await cropTo.call(track, await CropTarget.fromElement(frame));
      // Chrome sends no cropped frames until something inside the frame repaints after cropTo, and the footage
      // alone does not count. One black pixel in the corner the rounded frame clips, for two frames, never shows.
      const pixel = document.createElement("span");
      pixel.style.cssText = "position:absolute;left:0;top:0;width:1px;height:1px;background:#000";
      frame.appendChild(pixel);
      requestAnimationFrame(() => requestAnimationFrame(() => pixel.remove()));
    },
    makeStream: (tracks) => new MediaStream(tracks),
    makeRecorder: (stream, mimeType) =>
      new MediaRecorder(stream, mimeType ? { mimeType, videoBitsPerSecond: 8_000_000 } : undefined) as unknown as MediaRecorderLike,
    isTypeSupported: (mimeType) => typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(mimeType),
    save: (blob, name) => {
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = name;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    },
    now: () => new Date(),
  };
}
