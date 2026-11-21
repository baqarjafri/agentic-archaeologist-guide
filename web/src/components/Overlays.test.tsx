import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import type { ObjectView, PackView } from "../lib/api";
import { addQuestion, emptyMemory, markHeard, recordVisit } from "../lib/memory";
import { NotThisSheet, SourceSheet, VisitDrawer } from "./Overlays";

const piece = (id: string, title: string): ObjectView => ({
  id, title, meta: ["Somewhere · long ago", `Stone · ${id}`], record_url: "https://x", display_image: `/${id}.jpg`,
  parts: [{ title: "Who she is", passages: [`${id}#p1`] }],
  passages: {
    [`${id}#p1`]: "Granodiorite head in the form of a lioness.", [`${id}#p2`]: "She was the goddess of fire.",
    [`${id}#place`]: "Place: Egypt, Thebes",
  },
});
const pack: PackView = {
  id: "p", title: "t", credit: "Text and images: Glasgow Museums.",
  objects: [piece("13.181", "Head of Sekhmet"), piece("28.37", "Lion's head"), piece("13.257", "Coffin panel of Djedmut")],
  relations: [
    { key: "13.181|28.37", a: "13.181", b: "28.37", theme: "Protectors", passages: [] },
    { key: "13.181|13.257", a: "13.181", b: "13.257", theme: "From Thebes", passages: [] },
  ],
};

test("the drawer lists the visit and suggests a linked piece not yet seen", () => {
  let m = recordVisit(emptyMemory(), "13.181", new Date(2026, 10, 26, 10, 38));
  m = markHeard(m, "13.181", 0);
  m = addQuestion(m, "13.181", "Why a lion?");
  const onForget = vi.fn();
  render(<VisitDrawer pack={pack} memory={m} onClose={() => {}} onForget={onForget} onForgetAll={() => {}} onExport={() => {}} />);
  expect(screen.getByText("Heard 1 of 1 part · Asked one question")).toBeTruthy();
  expect(screen.getByText("Saved only on this phone")).toBeTruthy();
  expect(screen.getByText("Protectors")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Forget Head of Sekhmet" }));
  expect(onForget).toHaveBeenCalledWith("13.181");
});

test("the source sheet highlights the cited passage and links to the record", () => {
  const { rerender } = render(<SourceSheet pack={pack} citation="13.181#p1" onClose={() => {}} />);
  expect(screen.getByText(/Granodiorite head/).className).toBe("hit");
  expect(screen.getByText(/goddess of fire/).className).toBe("");
  expect(screen.getByText("Place: Egypt, Thebes").tagName).toBe("LI");
  expect(screen.getByRole("link", { name: "View the record" }).getAttribute("href")).toBe("https://x");
  rerender(<SourceSheet pack={pack} citation="13.181#place" onClose={() => {}} />);
  expect(screen.getByText("Place: Egypt, Thebes").className).toBe("hit");
});

test("Not this? lists the best match first and lets the visitor choose", () => {
  const onChoose = vi.fn();
  render(<NotThisSheet pack={pack} candidates={[{ object_id: "28.37", score: 0.5 }]} onChoose={onChoose} onClose={() => {}} />);
  const choices = screen.getAllByRole("button").filter((b) => b.className !== "close");
  expect(choices[0].textContent).toContain("Lion's head");
  expect(screen.getByText("Best match")).toBeTruthy();
  fireEvent.click(choices[1]);
  expect(onChoose).toHaveBeenCalledWith("13.181");
});
