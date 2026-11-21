import { del, get, set } from "idb-keyval";

export type Exchange = { question: string; answer: string };
export type Visit = { objectId: string; firstSeen: string; heardParts: number[]; questions: string[] };
export type Profile = { motivation: string; depth: "short" | "medium" | "long" };
export type VisitMemory = {
  version: 1;
  visits: Visit[];
  connections: string[];
  exchanges: Record<string, Exchange[]>;
  profile: Profile;
};

const KEY = "visit-memory-v1";
const MAX_EXCHANGES = 6;

export const emptyMemory = (): VisitMemory => ({
  version: 1, visits: [], connections: [], exchanges: {}, profile: { motivation: "curious", depth: "short" },
});

function updateVisit(m: VisitMemory, objectId: string, change: (v: Visit) => Visit): VisitMemory {
  return { ...m, visits: m.visits.map((v) => (v.objectId === objectId ? change(v) : v)) };
}

export function recordVisit(m: VisitMemory, objectId: string, now: Date): VisitMemory {
  if (m.visits.some((v) => v.objectId === objectId)) return m;
  return { ...m, visits: [...m.visits, { objectId, firstSeen: now.toISOString(), heardParts: [], questions: [] }] };
}

export function markHeard(m: VisitMemory, objectId: string, part: number): VisitMemory {
  return updateVisit(m, objectId, (v) => ({
    ...v, heardParts: Array.from(new Set([...v.heardParts, part])).sort((a, b) => a - b),
  }));
}

export function addQuestion(m: VisitMemory, objectId: string, question: string): VisitMemory {
  return updateVisit(m, objectId, (v) => ({ ...v, questions: [...v.questions, question] }));
}

export function addExchange(m: VisitMemory, objectId: string, exchange: Exchange): VisitMemory {
  const list = [...(m.exchanges[objectId] ?? []), exchange].slice(-MAX_EXCHANGES);
  return { ...m, exchanges: { ...m.exchanges, [objectId]: list } };
}

export function addConnection(m: VisitMemory, key: string): VisitMemory {
  return m.connections.includes(key) ? m : { ...m, connections: [...m.connections, key] };
}

export function forgetVisit(m: VisitMemory, objectId: string): VisitMemory {
  const exchanges = { ...m.exchanges };
  delete exchanges[objectId];
  return {
    ...m,
    visits: m.visits.filter((v) => v.objectId !== objectId),
    exchanges,
    connections: m.connections.filter((key) => !key.split("|").includes(objectId)),
  };
}

export async function loadMemory(): Promise<VisitMemory> {
  try {
    const stored = await get<VisitMemory>(KEY);
    return stored?.version === 1 ? stored : emptyMemory();
  } catch {
    return emptyMemory(); // storage blocked or broken: the visit still works, unremembered
  }
}

export async function saveMemory(m: VisitMemory): Promise<void> {
  try {
    await set(KEY, m);
  } catch {
    // storage blocked or full: the visit carries on, but will not survive a reload
  }
}

export async function clearMemory(): Promise<void> {
  await del(KEY);
}

export function exportMemory(m: VisitMemory): Blob {
  return new Blob([JSON.stringify(m, null, 2)], { type: "application/json" });
}

export function clockTime(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
