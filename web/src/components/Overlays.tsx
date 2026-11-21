import { recordName, type Candidate, type ObjectView, type PackView } from "../lib/api";
import { clockTime, type VisitMemory } from "../lib/memory";

const LockIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
    <rect x="5" y="11" width="14" height="10" rx="2" />
    <path d="M8 11V7a4 4 0 0 1 8 0v4" />
  </svg>
);

export function suggestNext(pack: PackView, memory: VisitMemory): { object: ObjectView; theme: string } | null {
  const seen = new Set(memory.visits.map((v) => v.objectId));
  const last = memory.visits.at(-1)?.objectId;
  if (!last) return null;
  for (const relation of pack.relations) {
    const other = relation.a === last ? relation.b : relation.b === last ? relation.a : null;
    const object = other && !seen.has(other) ? pack.objects.find((o) => o.id === other) : undefined;
    if (object) return { object, theme: relation.theme };
  }
  return null;
}

function visitNote(heard: number, total: number, questions: number): string {
  const parts = `Heard ${heard} of ${total} part${total === 1 ? "" : "s"}`;
  if (questions === 0) return parts;
  return `${parts} · Asked ${questions === 1 ? "one question" : `${questions} questions`}`;
}

export function VisitDrawer({ pack, memory, onClose, onForget, onForgetAll, onExport }: {
  pack: PackView; memory: VisitMemory; onClose: () => void; onForget: (objectId: string) => void;
  onForgetAll: () => void; onExport: () => void;
}) {
  const byId = new Map(pack.objects.map((o) => [o.id, o]));
  const suggestion = suggestNext(pack, memory);
  return (
    <div className="drawer-scrim" onClick={onClose}>
      <aside className="drawer glass" role="dialog" aria-modal="true" aria-label="My visit" onClick={(e) => e.stopPropagation()}>
        <header>
          <div>
            <h2>My visit</h2>
            <p>{pack.short_name ?? "Burrell Collection"} {"·"} Today</p>
          </div>
          <button className="close" onClick={onClose} aria-label="Close">{"×"}</button>
        </header>
        <p className="saved"><LockIcon />Saved only on this phone</p>
        <ol className="timeline">
          {memory.visits.map((visit) => {
            const object = byId.get(visit.objectId);
            if (!object) return null;
            return (
              <li key={visit.objectId}>
                <time>{clockTime(visit.firstSeen)}</time>
                <img src={object.display_image} alt="" />
                <div>
                  <strong>{object.title}</strong>
                  <span>{visitNote(visit.heardParts.length, object.parts.length, visit.questions.length)}</span>
                </div>
                <button onClick={() => onForget(visit.objectId)} aria-label={`Forget ${object.title}`}>{"×"}</button>
              </li>
            );
          })}
        </ol>
        {suggestion && (
          <div className="suggest">
            <img src={suggestion.object.display_image} alt="" />
            <div>
              <small>{suggestion.theme}</small>
              <strong>{suggestion.object.title}</strong>
            </div>
          </div>
        )}
        <footer>
          <button onClick={onExport}>Export visit</button>
          <button onClick={onForgetAll}>Forget everything</button>
        </footer>
        <p className="credit">{pack.credit}</p>
      </aside>
    </div>
  );
}

export function SourceSheet({ pack, citation, onClose }: { pack: PackView; citation: string; onClose: () => void }) {
  const object = pack.objects.find((o) => o.id === citation.split("#")[0]);
  if (!object) return null;
  const entries = Object.entries(object.passages);
  const isSentence = (id: string) => /#p\d+$/.test(id); // description sentences; #date, #place and #materials are facts
  return (
    <div className="sheet-scrim" onClick={onClose}>
      <section className="sheet glass" role="dialog" aria-modal="true" aria-label={`Source: ${object.title}`} onClick={(e) => e.stopPropagation()}>
        <header>
          <div>
            <small>{recordName(pack, object.id)}</small>
            <h2>{object.title}</h2>
          </div>
          <button className="close" onClick={onClose} aria-label="Close">{"×"}</button>
        </header>
        <div className="quote">
          {entries.filter(([id]) => isSentence(id)).map(([id, text]) => (
            <span key={id} className={id === citation ? "hit" : ""}>{text} </span>
          ))}
        </div>
        <ul className="facts">
          {entries.filter(([id]) => !isSentence(id)).map(([id, text]) => (
            <li key={id} className={id === citation ? "hit" : ""}>{text}</li>
          ))}
        </ul>
        <a className="record-link" href={object.record_url} target="_blank" rel="noreferrer">View the record</a>
        <p className="credit">{pack.credit}</p>
      </section>
    </div>
  );
}

export function NotThisSheet({ pack, candidates, onChoose, onClose }: {
  pack: PackView; candidates: Candidate[]; onChoose: (objectId: string) => void; onClose: () => void;
}) {
  const listed = candidates
    .map((c) => pack.objects.find((o) => o.id === c.object_id))
    .filter((o): o is ObjectView => Boolean(o));
  const ordered = [...listed, ...pack.objects.filter((o) => !listed.includes(o))];
  return (
    <div className="sheet-scrim" onClick={onClose}>
      <section className="sheet glass" role="dialog" aria-modal="true" aria-label="Is it one of these?" onClick={(e) => e.stopPropagation()}>
        <header>
          <h2>Is it one of these?</h2>
          <button className="close" onClick={onClose} aria-label="Close">{"×"}</button>
        </header>
        <ul className="choices">
          {ordered.map((object, i) => (
            <li key={object.id}>
              <button onClick={() => onChoose(object.id)}>
                <img src={object.display_image} alt="" />
                <span>
                  <strong>{object.title}</strong>
                  <small>{object.meta[object.meta.length - 1]}</small>
                </span>
                {i === 0 && listed.length > 0 && <em>Best match</em>}
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
