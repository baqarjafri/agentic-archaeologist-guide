import type { ReactNode } from "react";
import { recordName, type ObjectView, type PackView } from "../lib/api";

export type TrailItem = { objectId: string; title: string; image: string; time: string; current: boolean; linked: boolean };
export type PartInfo = { index: number; count: number; title: string };
export type Caption = { text: string; citations: string[] };
export type ButtonState = "idle" | "ready" | "speaking" | "listening" | "thinking";

const icon = { width: 20, height: 20, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.8,
  strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true };

export const HistoryIcon = () => (
  <svg {...icon}><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 3v5h5" /><path d="M12 7v5l3 2" /></svg>
);
export const BookIcon = () => (
  <svg {...icon}><path d="M2 5h7a3 3 0 0 1 3 3v12a2 2 0 0 0-2-2H2z" /><path d="M22 5h-7a3 3 0 0 0-3 3v12a2 2 0 0 1 2-2h8z" /></svg>
);
export const MicIcon = () => (
  <svg {...icon}><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0" /><path d="M12 18v3" /></svg>
);

export function VisitTrail({ items }: { items: TrailItem[] }) {
  if (items.length === 0) return null;
  return (
    <nav className="trail glass" aria-label="Your visit so far">
      {items.map((item, i) => (
        <span key={item.objectId} className={"trail-item" + (item.current ? " current" : "")}>
          {i > 0 && <i className={"trail-link" + (item.linked ? " linked" : "")} aria-hidden="true" />}
          <img src={item.image} alt="" />
          <span>{item.time}</span>
          <span className="sr-only">{item.title}</span>
        </span>
      ))}
    </nav>
  );
}

export function ObjectCard({ object, compact, part, onNotThis }: {
  object: ObjectView; compact: boolean; part: PartInfo | null; onNotThis: () => void;
}) {
  return (
    <section className={"object-card glass" + (compact ? " compact" : "")} aria-label={object.title}>
      <div className="row">
        <img src={object.display_image} alt="" />
        <div>
          <h2>{object.title}</h2>
          {compact && part && (
            <span className="part"><b>{part.index + 1} of {part.count}</b> {"·"} {part.title}</span>
          )}
        </div>
      </div>
      {compact && part && (
        <div className="segments" aria-hidden="true">
          {Array.from({ length: part.count }, (_, i) => <i key={i} className={i <= part.index ? "done" : ""} />)}
        </div>
      )}
      {!compact && (
        <>
          <p className="meta">{object.meta.map((line) => <span key={line}>{line}</span>)}</p>
          <button className="not-this" onClick={onNotThis}>Not this? <span aria-hidden="true">{"›"}</span></button>
        </>
      )}
    </section>
  );
}

export function RightRail({ visitCount, onVisit, onSources }: { visitCount: number; onVisit: () => void; onSources: () => void }) {
  return (
    <div className="rail">
      <button className="glass" onClick={onVisit} aria-label={`My visit, ${visitCount} pieces`}>
        <HistoryIcon />
        {visitCount > 0 && <span className="badge">{visitCount}</span>}
      </button>
      <button className="glass" onClick={onSources} aria-label="Sources">
        <BookIcon />
      </button>
    </div>
  );
}

export function numberCitations(captions: (Caption | null)[]): string[] {
  const ids: string[] = [];
  for (const caption of captions) for (const id of caption?.citations ?? []) if (!ids.includes(id)) ids.push(id);
  return ids;
}

export function CaptionCard({ prev, current, question, typing, onTyped, onCite, children, pack }: {
  prev: Caption | null; current: Caption | null; question: string | null; typing: boolean;
  onTyped: (text: string) => void; onCite: (id: string) => void; children?: ReactNode;
  pack?: PackView | null; // names the record each source comes from; without it, the pilot's Glasgow wording
}) {
  if (!prev && !current && question === null && !children) return null;
  const ids = numberCitations([prev, current]);
  const chips = (caption: Caption) =>
    caption.citations.map((id) => (
      <button key={id} className="cite" onClick={() => onCite(id)} aria-label={`Source ${ids.indexOf(id) + 1}`}>
        {ids.indexOf(id) + 1}
      </button>
    ));
  return (
    <section className="caption-card glass" aria-live="polite">
      {question !== null && (
        <p className="bubble">
          {typing ? (
            <input
              autoFocus
              placeholder="Type your question"
              aria-label="Your question"
              onKeyDown={(e) => { if (e.key === "Enter") onTyped((e.target as HTMLInputElement).value); }}
            />
          ) : (
            <>{"“"}{question}{"”"}</>
          )}
        </p>
      )}
      {prev && <p className="prev">{prev.text}{chips(prev)}</p>}
      {current && <p className="current">{current.text}{chips(current)}</p>}
      {ids.length > 0 && (
        <div className="sources">
          {ids.map((id, i) => <span key={id}>{i + 1} {pack ? recordName(pack, id.split("#")[0]) : `Glasgow Museums record ${id.split("#")[0]}`}</span>)}
        </div>
      )}
      {children}
    </section>
  );
}

export function MentionOverlay({ object, seenAt, onOpen }: { object: ObjectView; seenAt: string | null; onOpen: () => void }) {
  return (
    <button className="mention glass" onClick={onOpen} aria-label={`${object.title}, seen earlier`}>
      <img src={object.display_image} alt="" />
      <span>
        <strong>{object.title}</strong>
        {seenAt && <span>seen {seenAt}</span>}
      </span>
    </button>
  );
}

export function ConnectionCard({ from, to, theme, seenAt }: { from: ObjectView; to: ObjectView; theme: string; seenAt: string | null }) {
  return (
    <section className="connection glass" aria-label={`Linked to ${from.title}`}>
      <div className="pair">
        <img src={from.display_image} alt="" />
        <i aria-hidden="true" />
        <img src={to.display_image} alt="" />
      </div>
      <div>
        <em>{theme}</em>
        <span>Linked to {from.title}{seenAt ? ` · seen ${seenAt}` : ""}</span>
      </div>
    </section>
  );
}

const LABEL: Record<ButtonState, string> = {
  idle: "Tell me", ready: "Ask", speaking: "Ask", listening: "Send", thinking: "Thinking",
};

export function PrimaryButton({ state, onPress, disabled }: { state: ButtonState; onPress: () => void; disabled?: boolean }) {
  return (
    <button className={`primary glass ${state}`} onClick={onPress} disabled={disabled}>
      {(state === "ready" || state === "speaking" || state === "listening") && <MicIcon />}
      <span>{LABEL[state]}</span>
    </button>
  );
}

export function ResumeChip({ part, onPress }: { part: PartInfo; onPress: () => void }) {
  return (
    <button className="resume" onClick={onPress}>
      Carry on <small>{part.index + 1} of {part.count} {"·"} {part.title}</small>
    </button>
  );
}
