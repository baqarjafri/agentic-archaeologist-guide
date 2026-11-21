import { expect, test } from "vitest";
import { addExchange, addQuestion, emptyMemory, markHeard, recordVisit } from "./memory";
import { buildTurn, nextPart } from "./session";

test("nextPart skips parts already heard", () => {
  const m = markHeard(recordVisit(emptyMemory(), "13.181", new Date(2026, 10, 26, 10, 38)), "13.181", 0);
  expect(nextPart(m, "13.181", 4)).toBe(1);
  expect(nextPart(m, "28.37", 3)).toBe(0);
  const done = [1, 2, 3].reduce((acc, p) => markHeard(acc, "13.181", p), m);
  expect(nextPart(done, "13.181", 4)).toBeNull();
});

test("buildTurn sends the visit in the server's shape", () => {
  let m = recordVisit(emptyMemory(), "13.181", new Date(2026, 10, 26, 10, 38));
  m = addQuestion(m, "13.181", "Why a lion?");
  for (let i = 0; i < 5; i++) m = addExchange(m, "13.181", { question: `q${i}`, answer: `a${i}` });
  const turn = buildTurn(m, "ask", "13.181", { question: "Why a lion?" });
  expect(turn).toEqual({
    type: "turn", kind: "ask", object_id: "13.181", question: "Why a lion?", part_index: null,
    visits: [{ object_id: "13.181", time: "10:38", heard_parts: [], questions: ["Why a lion?"] }],
    recent: [{ question: "q2", answer: "a2" }, { question: "q3", answer: "a3" }, { question: "q4", answer: "a4" }],
    connections_made: [],
    profile: { motivation: "curious", depth: "short" },
  });
});
