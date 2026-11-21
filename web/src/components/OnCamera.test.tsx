import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import type { ObjectView } from "../lib/api";
import { CaptionCard, ConnectionCard, MentionOverlay, ObjectCard, PrimaryButton, VisitTrail } from "./OnCamera";

const sekhmet: ObjectView = {
  id: "13.181", title: "Head of Sekhmet", meta: ["Egypt · about 1390–1352 BC", "Granodiorite · 13.181"],
  record_url: "https://x", display_image: "/s.jpg", parts: [{ title: "Who she is", passages: ["13.181#p1"] }],
  passages: { "13.181#p1": "Granodiorite head in the form of a lioness." },
};
const lion: ObjectView = { ...sekhmet, id: "28.37", title: "Lion's head", display_image: "/l.jpg" };

test("the primary button names its action and reports presses", () => {
  const onPress = vi.fn();
  const { rerender } = render(<PrimaryButton state="idle" onPress={onPress} />);
  fireEvent.click(screen.getByRole("button", { name: "Tell me" }));
  expect(onPress).toHaveBeenCalledOnce();
  rerender(<PrimaryButton state="speaking" onPress={onPress} />);
  expect(screen.getByRole("button", { name: "Ask" })).toBeTruthy();
  rerender(<PrimaryButton state="listening" onPress={onPress} />);
  expect(screen.getByRole("button", { name: "Send" })).toBeTruthy();
});

test("captions number their sources and open them", () => {
  const onCite = vi.fn();
  render(
    <CaptionCard
      prev={{ text: "Earlier line.", citations: ["13.181#p1"] }}
      current={{ text: "Like Sekhmet, it protected.", citations: ["13.181#p8", "28.37#p1"] }}
      question={null} typing={false} onTyped={() => {}} onCite={onCite}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Source 3" }));
  expect(onCite).toHaveBeenCalledWith("28.37#p1");
  expect(screen.getByText("3 Glasgow Museums record 28.37")).toBeTruthy();
});

test("the compact card shows the story part", () => {
  render(<ObjectCard object={sekhmet} compact part={{ index: 1, count: 4, title: "Where she stood" }} onNotThis={() => {}} />);
  expect(screen.getByText("2 of 4")).toBeTruthy();
  expect(screen.getByText(/Where she stood/)).toBeTruthy();
});

test("the expanded card offers Not this?", () => {
  const onNotThis = vi.fn();
  render(<ObjectCard object={sekhmet} compact={false} part={null} onNotThis={onNotThis} />);
  fireEvent.click(screen.getByRole("button", { name: /Not this\?/ }));
  expect(onNotThis).toHaveBeenCalled();
});

test("mention and connection cards name the earlier piece", () => {
  render(
    <>
      <MentionOverlay object={sekhmet} seenAt="10:38" onOpen={() => {}} />
      <ConnectionCard from={sekhmet} to={lion} theme="Protectors" seenAt="10:38" />
    </>,
  );
  expect(screen.getByText("seen 10:38")).toBeTruthy();
  expect(screen.getByText("Protectors")).toBeTruthy();
  expect(screen.getByText("Linked to Head of Sekhmet · seen 10:38")).toBeTruthy();
});

test("the trail marks the current piece", () => {
  render(
    <VisitTrail items={[
      { objectId: "42.20", title: "Warwick Vase", image: "/w.jpg", time: "10:31", current: false, linked: false },
      { objectId: "13.181", title: "Head of Sekhmet", image: "/s.jpg", time: "10:38", current: true, linked: false },
    ]} />,
  );
  expect(screen.getByText("10:38").closest(".trail-item")?.className).toContain("current");
});
