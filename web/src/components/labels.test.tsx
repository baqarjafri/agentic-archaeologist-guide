import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { recordName, type PackView } from "../lib/api";
import { emptyMemory } from "../lib/memory";
import { CaptionCard } from "./OnCamera";
import { SourceSheet, VisitDrawer } from "./Overlays";

const object = {
  id: "487620", title: "House post", meta: ["a", "b"], record_url: "https://x", display_image: "/x.jpg", parts: [],
  passages: { "487620#p1": "A bear." },
};
const burrell: PackView = {
  id: "p", title: "t", credit: "c", relations: [],
  objects: [{ ...object, id: "13.181", passages: { "13.181#p1": "A head." } }],
};
const maa: PackView = {
  id: "m", title: "t", credit: "c", short_name: "MAA Cambridge", record_label: "MAA record", relations: [],
  objects: [{ ...object, accession: "1926.226" }],
};
const noop = () => {};

test("record names fall back to the Glasgow wording", () => {
  expect(recordName(burrell, "13.181")).toBe("Glasgow Museums record 13.181");
  expect(recordName(maa, "487620")).toBe("MAA record 1926.226");
});

test("the source sheet and the visit drawer use the pack's own names", () => {
  render(<SourceSheet pack={maa} citation="487620#p1" onClose={noop} />);
  expect(screen.getByText("MAA record 1926.226")).toBeTruthy();
  render(<VisitDrawer pack={maa} memory={emptyMemory()} onClose={noop} onForget={noop} onForgetAll={noop} onExport={noop} />);
  expect(screen.getByText(/MAA Cambridge/)).toBeTruthy();
});

test("the caption's sources use the pack's record label", () => {
  const caption = { text: "A bear.", citations: ["487620#p1"] };
  render(<CaptionCard pack={maa} prev={null} current={caption} question={null} typing={false} onTyped={noop} onCite={noop} />);
  expect(screen.getByText(/MAA record 1926.226/)).toBeTruthy();
});

test("without labels the pilot's wording is unchanged", () => {
  render(<VisitDrawer pack={burrell} memory={emptyMemory()} onClose={noop} onForget={noop} onForgetAll={noop} onExport={noop} />);
  expect(screen.getByText(/Burrell Collection/)).toBeTruthy();
  const caption = { text: "A head.", citations: ["13.181#p1"] };
  render(<CaptionCard prev={null} current={caption} question={null} typing={false} onTyped={noop} onCite={noop} />);
  expect(screen.getByText(/Glasgow Museums record 13.181/)).toBeTruthy();
});
