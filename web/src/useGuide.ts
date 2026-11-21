import { useCallback, useEffect, useReducer, useRef } from "react";
import type { ButtonState, Caption, PartInfo } from "./components/OnCamera";
import { AudioQueue } from "./lib/audioQueue";
import {
  accessCode, fetchPack, identify, socketUrl, type Candidate, type IdentifyResult, type PackView,
} from "./lib/api";
import { captureFrame, startCamera, stopCamera } from "./lib/camera";
import {
  addConnection, addExchange, addQuestion, emptyMemory, exportMemory, forgetVisit, loadMemory, markHeard,
  recordVisit, saveMemory, type VisitMemory,
} from "./lib/memory";
import { buildTurn, nextPart, type TurnKind } from "./lib/session";
import { GuideSocket, type ServerEvent } from "./lib/socket";
import { SpeechInput } from "./lib/speech";
import { demoCamera } from "./lib/demo";
import { voiceBus } from "./lib/voiceBus";
import { Voter } from "./lib/voting";

export type SocketHandlers = {
  onEvent: (e: ServerEvent) => void;
  onAudio: (index: number, chunk: ArrayBuffer | null) => void;
  onStatus?: (open: boolean) => void;
};
export type SocketLike = { connect(): void; send(payload: object): void; cancel(): void; close(): void };
export type QueueEvents = { onStart: (index: number) => void; onIdle: () => void };
export type AudioLike = {
  begin(): void; push(index: number, chunk: ArrayBuffer): void; end(index: number): void;
  skip: (index: number) => void; finish: (total: number) => void; stop(): void; busy: boolean;
};
export type SpeechLike = {
  supported: boolean;
  start(onText: (t: string) => void, onEnd?: (text: string, failure: string | null) => void): void;
  stop(): Promise<string>;
  abort(): void;
};

export type GuideDeps = {
  code: string;
  socketUrl: string;
  scanEvery: number;
  now: () => Date;
  fetchPack: (code: string) => Promise<PackView>;
  identify: (frame: Blob, code: string) => Promise<IdentifyResult>;
  startCamera: (video: HTMLVideoElement) => Promise<MediaStream | null>;
  stopCamera: (stream: MediaStream | null) => void;
  captureFrame: (video: HTMLVideoElement) => Promise<Blob | null>;
  makeSocket: (url: string, handlers: SocketHandlers) => SocketLike;
  makeAudio: (events: QueueEvents) => AudioLike;
  speech: SpeechLike;
  loadMemory: () => Promise<VisitMemory>;
  saveMemory: (m: VisitMemory) => Promise<void>;
  /** How long to wait for the server's turn_started before giving up (default 30 s). */
  startTimeout?: number;
  /** How long a started turn may go without a word from the server before giving up (default 15 s). */
  quietTimeout?: number;
};

export function realDeps(): GuideDeps {
  const code = accessCode();
  return {
    code, socketUrl: socketUrl(code), scanEvery: 800, now: () => new Date(),
    fetchPack, identify,
    // In video mode (?demo=1) the prepared gallery tour stands in for the camera; recognition is unchanged.
    startCamera: demoCamera?.startCamera ?? startCamera,
    stopCamera: demoCamera?.stopCamera ?? stopCamera,
    captureFrame: (video) => captureFrame(video),
    makeSocket: (url, handlers) => new GuideSocket(url, handlers),
    makeAudio: (events) => {
      const { ctx, bus } = voiceBus();
      void ctx.resume();
      return new AudioQueue(ctx, events, bus);
    },
    speech: new SpeechInput(),
    loadMemory, saveMemory,
  };
}

type Mode = "idle" | "thinking" | "telling" | "listening";
type Sentence = { text: string; citations: string[]; show: string[] };
type Turn = {
  kind: TurnKind; objectId: string; question?: string; partIndex: number | null; connectionKey?: string;
  done?: boolean; // turn_done arrived: the server owes nothing more, so a dropped link cannot hurt this turn
};

export type GuideView = {
  pack: PackView | null;
  memory: VisitMemory;
  status: string | null;
  candidate: string | null;
  current: string | null;
  candidates: Candidate[];
  mode: Mode;
  part: PartInfo | null;
  resume: PartInfo | null;
  prev: Caption | null;
  cur: Caption | null;
  question: string | null;
  typing: boolean;
  mention: string | null;
  connection: { otherObject: string; theme: string } | null;
  overlay: "visit" | "source" | "notthis" | null;
  sourceId: string | null;
};

const initial: GuideView = {
  pack: null, memory: emptyMemory(), status: "Loading the guide", candidate: null, current: null, candidates: [],
  mode: "idle", part: null, resume: null, prev: null, cur: null, question: null, typing: false,
  mention: null, connection: null, overlay: null, sourceId: null,
};

type Action = { type: "set"; patch: Partial<GuideView> } | { type: "caption"; caption: Caption; mention: string | null };

function reducer(state: GuideView, action: Action): GuideView {
  if (action.type === "caption") {
    return { ...state, prev: state.cur, cur: action.caption, mention: action.mention, mode: "telling" };
  }
  return { ...state, ...action.patch };
}

export function buttonState(view: GuideView): ButtonState {
  if (view.mode === "listening") return "listening";
  if (view.mode === "thinking") return "thinking";
  if (view.mode === "telling") return "speaking";
  if (view.current && view.candidate === view.current) return "ready";
  return "idle";
}

function resumeFor(memory: VisitMemory, object: PackView["objects"][number] | undefined): PartInfo | null {
  if (!object) return null;
  const next = nextPart(memory, object.id, object.parts.length);
  return next !== null ? { index: next, count: object.parts.length, title: object.parts[next].title } : null;
}

export function useGuide(deps: GuideDeps) {
  const [view, dispatch] = useReducer(reducer, initial);
  const set = useCallback((patch: Partial<GuideView>) => dispatch({ type: "set", patch }), []);
  const viewRef = useRef(view);
  viewRef.current = view;
  const videoRef = useRef<HTMLVideoElement>(null);
  const memoryRef = useRef<VisitMemory>(emptyMemory());
  const sentences = useRef(new Map<number, Sentence>());
  const audio = useRef<AudioLike | null>(null);
  const socket = useRef<SocketLike | null>(null);
  const turn = useRef<Turn | null>(null);
  // True from a cancel or a new turn request until the server's next turn_started: anything before it is from an old turn.
  const awaitingStart = useRef(false);
  const voter = useRef(new Voter());
  const lastCandidates = useRef<Candidate[]>([]);
  // The piece the visitor turned down with "Not this?": the camera may keep seeing it, so it cannot take the card back.
  const rejected = useRef<string | null>(null);
  const rejectedMisses = useRef(0); // frames in a row without the rejected piece: a full window means the visitor moved on
  const watchdog = useRef<ReturnType<typeof setTimeout> | null>(null);
  const quiet = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clearWatchdog = () => {
    if (watchdog.current) clearTimeout(watchdog.current);
    watchdog.current = null;
    if (quiet.current) clearTimeout(quiet.current);
    quiet.current = null;
  };
  /** The server said something about the live turn: restart the count of silence that abandons it. */
  const heard = () => {
    if (quiet.current) clearTimeout(quiet.current);
    quiet.current = null;
    const t = turn.current;
    if (!t || t.done || awaitingStart.current) return;
    quiet.current = setTimeout(() => {
      quiet.current = null;
      if (turn.current !== t || t.done) return;
      socket.current?.cancel();
      abandonTurn.current("The connection went quiet. Please try again.");
    }, deps.quietTimeout ?? 15_000);
  };

  const remember = useCallback((m: VisitMemory) => {
    memoryRef.current = m;
    set({ memory: m });
    void deps.saveMemory(m).catch(() => {}); // a phone that cannot store still guides
  }, [deps, set]);

  const finishTurn = useRef<() => void>(() => {});
  finishTurn.current = () => {
    const t = turn.current;
    const pack = viewRef.current.pack;
    turn.current = null;
    if (!t || !pack) {
      set({ mode: "idle" });
      return;
    }
    const object = pack.objects.find((o) => o.id === t.objectId);
    if (sentences.current.size === 0) { // every sentence was dropped: nothing was told, so nothing is remembered
      set({ mode: "idle", mention: null, connection: null, question: null, resume: resumeFor(memoryRef.current, object),
        status: "The guide had nothing to say. Please try again." });
      return;
    }
    let m = memoryRef.current;
    if ((t.kind === "tell" || t.kind === "carry_on") && t.partIndex !== null) m = markHeard(m, t.objectId, t.partIndex);
    if (t.connectionKey) m = addConnection(m, t.connectionKey);
    if (t.kind === "ask" && t.question) {
      const answer = [...sentences.current.values()].map((s) => s.text).join(" ");
      m = addExchange(m, t.objectId, { question: t.question, answer });
    }
    remember(m);
    set({ mode: "idle", mention: null, connection: null, question: null, resume: resumeFor(m, object) });
  };

  // The turn in flight cannot finish (the server reported an error, or the connection dropped): stop waiting.
  const abandonTurn = useRef<(message: string) => void>(() => {});
  abandonTurn.current = (message: string) => {
    const t = turn.current;
    const pack = viewRef.current.pack;
    turn.current = null;
    awaitingStart.current = true;
    clearWatchdog();
    audio.current?.stop();
    const object = t && pack ? pack.objects.find((o) => o.id === t.objectId) : undefined;
    set({
      mode: "idle", mention: null, connection: null, question: null, status: message,
      resume: resumeFor(memoryRef.current, object),
    });
  };

  const ensureAudio = useCallback((): AudioLike => {
    if (!audio.current) {
      audio.current = deps.makeAudio({
        onStart: (index) => {
          const s = sentences.current.get(index);
          if (s) dispatch({ type: "caption", caption: { text: s.text, citations: s.citations }, mention: s.show[0] ?? null });
        },
        onIdle: () => finishTurn.current(),
      });
    }
    return audio.current;
  }, [deps]);

  const onEvent = useRef<(e: ServerEvent) => void>(() => {});
  onEvent.current = (event: ServerEvent) => {
    if (event.type === "turn_started") awaitingStart.current = false;
    else if (awaitingStart.current && (event.type !== "error" || event.message === "turn failed")) return; // a late message from a cancelled turn
    switch (event.type) {
      case "turn_started":
        clearWatchdog();
        sentences.current.clear();
        if (turn.current) turn.current.partIndex = event.part_index;
        if (event.part_index !== null && event.part_title) {
          set({ part: { index: event.part_index, count: event.part_count, title: event.part_title } });
        }
        break;
      case "connection":
        // Remembered only when the turn finishes, so an interrupted connection is offered again next time.
        if (turn.current) turn.current.connectionKey = event.key;
        set({ connection: { otherObject: event.other_object, theme: event.theme } });
        break;
      case "sentence":
        sentences.current.set(event.index, { text: event.text, citations: event.citations, show: event.show });
        break;
      case "voice_failed":
        audio.current?.skip(event.index);
        break;
      case "turn_done":
        if (turn.current) turn.current.done = true;
        audio.current?.finish(event.sentences);
        break;
      case "error":
        if (turn.current) abandonTurn.current("The guide lost its thread. Please try again.");
        else set({ status: event.message });
        break;
      case "dropped":
        break;
    }
  };

  useEffect(() => {
    let alive = true;
    Promise.all([deps.fetchPack(deps.code), deps.loadMemory().catch(() => emptyMemory())])
      .then(([pack, memory]) => {
        if (!alive) return;
        memoryRef.current = memory;
        set({ pack, memory, status: null });
      })
      .catch(() => set({ status: "The guide could not load. Check the link and the connection." }));
    const s = deps.makeSocket(deps.socketUrl, {
      onEvent: (e) => {
        if (!alive) return; // a socket from an earlier mount must not touch this one's turn
        onEvent.current(e);
        heard();
      },
      onAudio: (index, chunk) => {
        if (!alive || awaitingStart.current) return; // a socket from an earlier mount, or audio from a cancelled turn
        if (chunk) audio.current?.push(index, chunk);
        else audio.current?.end(index);
        heard();
      },
      onStatus: (open) => {
        if (alive && !open && turn.current && !turn.current.done) abandonTurn.current("The connection dropped. Please try again.");
      },
    });
    s.connect();
    socket.current = s;
    return () => {
      alive = false;
      s.close();
    };
  }, [deps, set]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    let stream: MediaStream | null = null;
    let stopped = false;
    let busy = false;
    deps.startCamera(video)
      .then((s) => { if (stopped) deps.stopCamera(s); else stream = s; }) // React's development double start ends here
      .catch(() => { if (!stopped) set({ status: "Allow the camera so the guide can see the pieces." }); });
    const timer = setInterval(async () => {
      if (busy || stopped || !viewRef.current.pack) return;
      busy = true;
      try {
        const frame = await deps.captureFrame(video);
        if (frame) {
          const result = await deps.identify(frame, deps.code);
          if (result.candidates.length) lastCandidates.current = result.candidates;
          const stable = voter.current.push(result);
          if (rejected.current) {
            rejectedMisses.current = result.accepted && result.object_id === rejected.current ? 0 : rejectedMisses.current + 1;
            if (rejectedMisses.current >= 5) rejected.current = null;
          }
          // The card changes only between turns, so Ask never goes to a piece other than the one on the card.
          if (stable && viewRef.current.mode === "idle" && stable !== viewRef.current.candidate && stable !== rejected.current) {
            rejected.current = null;
            set({ candidate: stable });
          }
        }
      } catch {
        // a dropped frame: the next tick tries again
      } finally {
        busy = false;
      }
    }, deps.scanEvery);
    return () => {
      stopped = true;
      clearInterval(timer);
      deps.stopCamera(stream);
    };
  }, [deps, set]);

  useEffect(() => () => {
    clearWatchdog();
    deps.speech.abort();
    audio.current?.stop();
  }, [deps]);

  const stopSpeaking = () => {
    clearWatchdog();
    awaitingStart.current = true;
    audio.current?.stop();
    socket.current?.cancel();
    turn.current = null;
  };

  const sendTurn = (kind: TurnKind, objectId: string, opts: { question?: string; partIndex?: number | null }) => {
    awaitingStart.current = true;
    ensureAudio().begin();
    sentences.current.clear();
    turn.current = { kind, objectId, question: opts.question, partIndex: opts.partIndex ?? null };
    socket.current?.send(buildTurn(memoryRef.current, kind, objectId, opts));
    clearWatchdog();
    watchdog.current = setTimeout(() => {
      watchdog.current = null;
      if (!turn.current || !awaitingStart.current) return;
      socket.current?.cancel();
      abandonTurn.current("The guide is taking too long. Please try again.");
    }, deps.startTimeout ?? 30_000);
    set({ mode: "thinking", resume: null, mention: null, prev: null, cur: null, status: null });
  };

  const tellMe = () => {
    const v = viewRef.current;
    const id = v.candidate;
    const object = id && v.pack ? v.pack.objects.find((o) => o.id === id) : undefined;
    if (!id || !object) return;
    if (v.mode === "telling" || v.mode === "thinking") stopSpeaking();
    const m = recordVisit(memoryRef.current, id, deps.now());
    remember(m);
    set({ current: id, connection: null, question: null, typing: false, part: null });
    sendTurn("tell", id, { partIndex: nextPart(m, id, object.parts.length) });
  };

  const startListening = () => {
    if (viewRef.current.mode === "telling" || viewRef.current.mode === "thinking") stopSpeaking();
    ensureAudio();
    if (deps.speech.supported) {
      set({ mode: "listening", question: "", typing: false, mention: null, status: null });
      deps.speech.start((text) => set({ question: text }), (text, failure) => {
        if (viewRef.current.mode !== "listening") return;
        if (failure === "not-allowed" || failure === "service-not-allowed") {
          set({ mode: "idle", question: null, status: "Allow the microphone to ask a question." });
        } else if (!text.trim()) {
          set({ mode: "idle", question: null, status: "I did not catch that. Tap Ask to try again." });
        } else {
          submitQuestion(text); // Android stops listening after a pause: send what was heard
        }
      });
    } else {
      set({ mode: "listening", question: "", typing: true, mention: null });
    }
  };

  const submitQuestion = (text: string) => {
    const id = viewRef.current.current;
    const q = text.trim();
    if (!id || !q) {
      set({ mode: "idle", question: null, typing: false });
      return;
    }
    remember(addQuestion(memoryRef.current, id, q));
    set({ question: q, typing: false });
    sendTurn("ask", id, { question: q });
  };

  /** Stop whatever the guide is doing (speaking, waiting or listening) and return to idle. */
  const halt = () => {
    const mode = viewRef.current.mode;
    if (mode === "listening") deps.speech.abort();
    if (mode === "telling" || mode === "thinking" || turn.current) stopSpeaking();
    set({ mode: "idle", mention: null, connection: null, question: null, typing: false });
  };

  const press = async () => {
    const state = buttonState(viewRef.current);
    if (state === "idle") return tellMe();
    if (state === "ready" || state === "speaking") return startListening();
    if (state === "listening" && !viewRef.current.typing) submitQuestion(await deps.speech.stop());
  };

  const actions = {
    press,
    submitQuestion,
    carryOn: () => {
      const v = viewRef.current;
      if (v.current && v.resume) sendTurn("carry_on", v.current, { partIndex: v.resume.index });
    },
    tapCamera: () => {
      const v = viewRef.current;
      if (v.mode === "telling" || v.mode === "thinking") {
        halt();
        set({ resume: resumeFor(memoryRef.current, v.pack?.objects.find((o) => o.id === v.current)) });
      }
    },
    openVisit: () => set({ overlay: "visit" }),
    openSources: () => {
      const v = viewRef.current;
      const id = v.cur?.citations[0] ?? v.prev?.citations[0] ?? (v.current ? `${v.current}#p1` : null);
      if (id) set({ overlay: "source", sourceId: id });
    },
    openSource: (id: string) => set({ overlay: "source", sourceId: id }),
    openNotThis: () => set({ overlay: "notthis", candidates: lastCandidates.current }),
    closeOverlay: () => set({ overlay: null }),
    choose: (objectId: string) => {
      const previous = viewRef.current.candidate;
      rejected.current = previous && previous !== objectId ? previous : null;
      rejectedMisses.current = 0;
      voter.current.reset();
      set({ candidate: objectId, overlay: null });
    },
    forget: (objectId: string) => {
      const t = turn.current;
      if (t?.connectionKey?.split("|").includes(objectId)) t.connectionKey = undefined;
      if (viewRef.current.current === objectId) {
        if (viewRef.current.mode !== "idle") halt(); // its story or answer must not write it back
        set({ current: null, part: null, resume: null });
      }
      remember(forgetVisit(memoryRef.current, objectId));
    },
    forgetAll: () => {
      if (window.confirm("Forget your visit? This deletes everything stored on this phone.")) {
        if (viewRef.current.mode !== "idle") halt();
        remember(emptyMemory());
        set({ current: null, overlay: null, part: null, resume: null, prev: null, cur: null });
      }
    },
    exportVisit: () => {
      const url = URL.createObjectURL(exportMemory(memoryRef.current));
      const link = document.createElement("a");
      link.href = url;
      link.download = `my-visit-${new Date().toISOString().slice(0, 10)}.json`;
      link.click();
      URL.revokeObjectURL(url);
    },
  };

  return { view, videoRef, button: buttonState(view), actions };
}
