import { useEffect, useMemo, useRef, useState } from "react";
import {
  CaptionCard, ConnectionCard, MentionOverlay, ObjectCard, PrimaryButton, ResumeChip, RightRail, VisitTrail,
  type TrailItem,
} from "./components/OnCamera";
import { NotThisSheet, SourceSheet, VisitDrawer } from "./components/Overlays";
import { clockTime } from "./lib/memory";
import { demoCamera, type DemoControls } from "./lib/demo";
import { bindDemoKeys } from "./lib/demoKeys";
import { SessionRecorder, realRecorderDeps } from "./lib/recorder";
import { showTapAt, showTapOn } from "./lib/tapRipple";
import { voiceBus } from "./lib/voiceBus";
import { realDeps, useGuide, type GuideDeps } from "./useGuide";

const defaultDemo: DemoControls | null = demoCamera ? { next: demoCamera.next } : null;

function RecordingDot() {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  return <p className="rec-dot">REC {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}</p>;
}

export default function App({ deps, demo = defaultDemo }: { deps?: GuideDeps; demo?: DemoControls | null }) {
  const resolved = useMemo(() => deps ?? realDeps(), [deps]);
  const { view, videoRef, button, actions } = useGuide(resolved);
  const frameRef = useRef<HTMLElement>(null);
  const [recording, setRecording] = useState(false);
  const latest = useRef({ actions, button }); // the key handlers read the current actions and button state
  latest.current = { actions, button };

  useEffect(() => {
    const frame = frameRef.current;
    if (!demo || !frame) return;
    let recorder: SessionRecorder | null = null; // made on the first R, so the AudioContext starts from a key press
    const onPointer = (e: PointerEvent) => showTapAt(e.clientX, e.clientY, frame);
    frame.addEventListener("pointerdown", onPointer);
    const unbind = bindDemoKeys(window, {
      buttonState: () => latest.current.button,
      press: () => { void latest.current.actions.press(); },
      next: demo.next,
      close: () => latest.current.actions.closeOverlay(),
      tap: (selector) => showTapOn(frame.querySelector(selector), frame),
      record: () => {
        const { ctx, bus } = voiceBus();
        recorder ??= new SessionRecorder(ctx, bus, frame, realRecorderDeps(), setRecording);
        recorder.toggle().catch((error) => console.error("recording failed", error));
      },
    });
    return () => {
      unbind();
      frame.removeEventListener("pointerdown", onPointer);
      void recorder?.stop();
    };
  }, [demo]);
  const pack = view.pack;
  const find = (id: string | null) => (id && pack ? pack.objects.find((o) => o.id === id) ?? null : null);
  const seenAt = (id: string) => {
    const visit = view.memory.visits.find((v) => v.objectId === id);
    return visit ? clockTime(visit.firstSeen) : null;
  };

  const cardObject = find(view.candidate && view.candidate !== view.current ? view.candidate : view.current);
  const compact = cardObject !== null && cardObject.id === view.current;
  const trail: TrailItem[] = view.memory.visits.map((visit, i, all) => {
    const object = find(visit.objectId);
    const before = i > 0 ? all[i - 1].objectId : null;
    return {
      objectId: visit.objectId,
      title: object?.title ?? visit.objectId,
      image: object?.display_image ?? "",
      time: clockTime(visit.firstSeen),
      current: visit.objectId === view.current,
      linked: before !== null && view.memory.connections.includes([before, visit.objectId].sort().join("|")),
    };
  });
  const mention = find(view.mention);
  const earlier = view.connection ? find(view.connection.otherObject) : null;
  const here = find(view.current);

  return (
    <>
    <main ref={frameRef} className={demo ? "app demo" : "app"}>
      <video ref={videoRef} className="camera" playsInline muted onClick={actions.tapCamera} />
      <div className="camera-shade" />
      <VisitTrail items={trail} />
      {cardObject && (
        <ObjectCard object={cardObject} compact={compact} part={compact ? view.part : null} onNotThis={actions.openNotThis} />
      )}
      {pack && <RightRail visitCount={view.memory.visits.length} onVisit={actions.openVisit} onSources={actions.openSources} />}
      {earlier && here && view.connection ? (
        <ConnectionCard from={earlier} to={here} theme={view.connection.theme} seenAt={seenAt(earlier.id)} />
      ) : (
        mention && <MentionOverlay object={mention} seenAt={seenAt(mention.id)} onOpen={() => actions.openSource(`${mention.id}#p1`)} />
      )}
      <CaptionCard
        prev={view.prev} current={view.cur} question={view.question} typing={view.typing}
        onTyped={actions.submitQuestion} onCite={actions.openSource} pack={pack}
      >
        {view.resume && view.mode === "idle" && <ResumeChip part={view.resume} onPress={actions.carryOn} />}
      </CaptionCard>
      {view.status && <p className="status">{view.status}</p>}
      {!view.status && !cardObject && pack && <p className="status">Point the camera at a piece</p>}
      <PrimaryButton state={button} onPress={actions.press} disabled={button === "idle" && !view.candidate} />
      {pack && view.overlay === "visit" && (
        <VisitDrawer pack={pack} memory={view.memory} onClose={actions.closeOverlay} onForget={actions.forget}
          onForgetAll={actions.forgetAll} onExport={actions.exportVisit} />
      )}
      {pack && view.overlay === "source" && view.sourceId && (
        <SourceSheet pack={pack} citation={view.sourceId} onClose={actions.closeOverlay} />
      )}
      {pack && view.overlay === "notthis" && (
        <NotThisSheet pack={pack} candidates={view.candidates} onChoose={actions.choose} onClose={actions.closeOverlay} />
      )}
    </main>
    {demo && recording && <RecordingDot />}
    </>
  );
}
