import { clockTime, type VisitMemory } from "./memory";

export type TurnKind = "tell" | "ask" | "carry_on";
export type TurnPayload = {
  type: "turn";
  kind: TurnKind;
  object_id: string;
  question: string | null;
  part_index: number | null;
  visits: { object_id: string; time: string; heard_parts: number[]; questions: string[] }[];
  recent: { question: string; answer: string }[];
  connections_made: string[];
  profile: { motivation: string; depth: string };
};

export function nextPart(m: VisitMemory, objectId: string, partCount: number): number | null {
  const heard = new Set(m.visits.find((v) => v.objectId === objectId)?.heardParts ?? []);
  for (let i = 0; i < partCount; i++) if (!heard.has(i)) return i;
  return null;
}

export function buildTurn(
  m: VisitMemory,
  kind: TurnKind,
  objectId: string,
  opts: { question?: string; partIndex?: number | null } = {},
): TurnPayload {
  return {
    type: "turn",
    kind,
    object_id: objectId,
    question: opts.question ?? null,
    part_index: opts.partIndex ?? null,
    visits: m.visits.map((v) => ({
      object_id: v.objectId, time: clockTime(v.firstSeen), heard_parts: v.heardParts, questions: v.questions,
    })),
    recent: (m.exchanges[objectId] ?? []).slice(-3),
    connections_made: m.connections,
    profile: m.profile,
  };
}
