import { expect, test } from "vitest";
import {
  addConnection, addExchange, addQuestion, clockTime, emptyMemory, forgetVisit,
  loadMemory, markHeard, recordVisit, saveMemory,
} from "./memory";

const at = (h: number, m: number) => new Date(2026, 10, 26, h, m);

test("a visit is recorded once, with the time first seen", () => {
  let m = recordVisit(emptyMemory(), "13.181", at(10, 38));
  m = recordVisit(m, "13.181", at(10, 50));
  expect(m.visits).toHaveLength(1);
  expect(clockTime(m.visits[0].firstSeen)).toBe("10:38");
});

test("heard parts, questions, exchanges and connections accumulate", () => {
  let m = recordVisit(emptyMemory(), "13.181", at(10, 38));
  m = markHeard(m, "13.181", 1);
  m = markHeard(m, "13.181", 0);
  m = markHeard(m, "13.181", 1);
  m = addQuestion(m, "13.181", "What is the slot for?");
  m = addExchange(m, "13.181", { question: "What is the slot for?", answer: "A sun disc." });
  m = addConnection(m, "13.181|28.37");
  m = addConnection(m, "13.181|28.37");
  expect(m.visits[0].heardParts).toEqual([0, 1]);
  expect(m.visits[0].questions).toEqual(["What is the slot for?"]);
  expect(m.exchanges["13.181"]).toHaveLength(1);
  expect(m.connections).toEqual(["13.181|28.37"]);
});

test("forgetting a visit removes its questions, exchanges and connections", () => {
  let m = recordVisit(emptyMemory(), "13.181", at(10, 38));
  m = recordVisit(m, "28.37", at(10, 44));
  m = addExchange(m, "13.181", { question: "q", answer: "a" });
  m = addConnection(m, "13.181|28.37");
  m = forgetVisit(m, "13.181");
  expect(m.visits.map((v) => v.objectId)).toEqual(["28.37"]);
  expect(m.exchanges["13.181"]).toBeUndefined();
  expect(m.connections).toEqual([]);
});

test("memory survives a save and a load", async () => {
  const m = markHeard(recordVisit(emptyMemory(), "42.20", at(10, 31)), "42.20", 0);
  await saveMemory(m);
  expect(await loadMemory()).toEqual(m);
});
