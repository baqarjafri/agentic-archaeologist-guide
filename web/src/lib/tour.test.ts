import { expect, test } from "vitest";
import { TourPlayer, tourCamera, type Tour, type VideoLike } from "./tour";

class FakeVideo implements VideoLike {
  src = "";
  currentTime = 0;
  muted = false;
  loop = true;
  playing = false;
  attrs: Record<string, string> = {};
  listeners: Record<string, (() => void)[]> = {};
  async play() { this.playing = true; }
  pause() { this.playing = false; }
  setAttribute(name: string, value: string) { this.attrs[name] = value; }
  removeAttribute(name: string) { delete this.attrs[name]; if (name === "src") this.src = ""; }
  load() {}
  addEventListener(type: string, fn: () => void) { (this.listeners[type] ??= []).push(fn); }
  removeEventListener(type: string, fn: () => void) { this.listeners[type] = (this.listeners[type] ?? []).filter((f) => f !== fn); }
}

const tour: Tour = {
  video: "tour.mp4",
  segments: [
    { kind: "walk", start: 0, end: 4 },
    { kind: "hover", start: 4, end: 10, piece: "487620" },
    { kind: "walk", start: 10, end: 15 },
    { kind: "hover", start: 15, end: 21, piece: "495875" },
  ],
};

async function started(t: Tour = tour) {
  const video = new FakeVideo();
  const player = new TourPlayer(video, t, "/demo-media");
  await player.start();
  return { video, player };
}

test("start plays the tour muted, inline, from the first segment", async () => {
  const { video, player } = await started();
  expect(video.src).toBe("/demo-media/tour.mp4");
  expect(video.muted).toBe(true);
  expect(video.loop).toBe(false);
  expect(video.attrs.playsinline).toBe("true");
  expect(video.playing).toBe(true);
  expect(player.segment).toEqual(tour.segments[0]);
});

test("a walk runs on into the hover that follows it without a seek", async () => {
  const { video, player } = await started();
  player.tick(2);
  expect(player.segment).toEqual(tour.segments[0]);
  player.tick(3.99);
  expect(player.segment).toEqual(tour.segments[1]);
  expect(video.currentTime).toBe(0); // contiguous in the file: the player never seeks
});

test("a gap between segments is crossed with a seek", async () => {
  const { video, player } = await started({
    video: "t.mp4",
    segments: [{ kind: "walk", start: 0, end: 4 }, { kind: "hover", start: 6, end: 9, piece: "x" }],
  });
  player.tick(3.99);
  expect(video.currentTime).toBe(6);
});

test("a hover loops back to its start on its last frame, for as long as it lasts", async () => {
  const { video, player } = await started();
  player.tick(3.99);
  player.tick(9.99);
  expect(video.currentTime).toBe(4);
  expect(player.segment).toEqual(tour.segments[1]);
  player.tick(9.99);
  expect(video.currentTime).toBe(4);
});

test("→ in a walk jumps to the next hover, and in a hover walks on", async () => {
  const { video, player } = await started();
  player.next();
  expect(player.segment).toEqual(tour.segments[1]);
  expect(video.currentTime).toBe(4);
  player.next();
  expect(player.segment).toEqual(tour.segments[2]);
  expect(video.currentTime).toBe(10);
});

test("the last hover keeps hovering, and → there does nothing", async () => {
  const { video, player } = await started();
  player.next();
  player.next();
  player.next();
  expect(player.segment).toEqual(tour.segments[3]);
  player.next();
  expect(player.segment).toEqual(tour.segments[3]);
  player.tick(20.99);
  expect(video.currentTime).toBe(15);
});

test("a final walk stops on its last frame", async () => {
  const { video, player } = await started({ video: "t.mp4", segments: [{ kind: "walk", start: 0, end: 3 }] });
  player.tick(2.99);
  expect(video.playing).toBe(false);
});

test("stop pauses and drops the footage", async () => {
  const { video, player } = await started();
  player.stop();
  expect(video.playing).toBe(false);
  expect(video.src).toBe("");
});

test("tourCamera: a stale start never replaces a newer one, and only its own token stops it", async () => {
  const release: ((t: Tour) => void)[] = [];
  const camera = tourCamera("/m", () => new Promise<Tour>((resolve) => release.push(resolve)));
  const video = new FakeVideo() as unknown as HTMLVideoElement;
  const first = camera.startCamera(video);
  const second = camera.startCamera(video);
  release[1](tour);
  const newer = await second;
  release[0](tour);
  const stale = await first;
  expect(stale).toBeNull();
  expect(newer).not.toBeNull();
  camera.stopCamera(stale); // what useGuide does for a start whose effect was cleaned up
  expect((video as unknown as FakeVideo).playing).toBe(true);
  camera.next();
  expect((video as unknown as FakeVideo).currentTime).toBe(4);
  camera.stopCamera(newer);
  expect((video as unknown as FakeVideo).playing).toBe(false);
});

test("tourCamera drives the player from timeupdate when requestVideoFrameCallback is missing", async () => {
  const camera = tourCamera("/m", async () => tour);
  const video = new FakeVideo();
  await camera.startCamera(video as unknown as HTMLVideoElement);
  camera.next();
  video.currentTime = 9.99;
  video.listeners.timeupdate.forEach((fn) => fn());
  expect(video.currentTime).toBe(4);
});
