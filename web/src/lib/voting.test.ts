import { expect, test } from "vitest";
import type { IdentifyResult } from "./api";
import { Voter } from "./voting";

const seen = (id: string | null): IdentifyResult => ({
  accepted: id !== null, object_id: id, score: id ? 0.8 : 0.2, candidates: [],
});

test("shows a piece once three of the last five frames agree", () => {
  const voter = new Voter();
  expect(voter.push(seen("13.181"))).toBeNull();
  expect(voter.push(seen(null))).toBeNull();
  expect(voter.push(seen("13.181"))).toBeNull();
  expect(voter.push(seen("13.181"))).toBe("13.181");
});

test("old frames roll off", () => {
  const voter = new Voter();
  ["13.181", "13.181", "13.181"].forEach((id) => voter.push(seen(id)));
  ["28.37", "28.37", "28.37"].forEach((id) => voter.push(seen(id)));
  expect(voter.push(seen(null))).toBe("28.37");
});

test("disagreement shows nothing", () => {
  const voter = new Voter();
  ["13.181", "28.37", "42.20", "13.181", "28.37"].forEach((id) => voter.push(seen(id)));
  expect(voter.push(seen("42.20"))).toBeNull();
});
