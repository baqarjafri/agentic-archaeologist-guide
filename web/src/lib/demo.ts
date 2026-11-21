import { tourCamera, type TourCamera } from "./tour";

/** `?demo=1` turns on laptop video mode: footage as the camera, demo keys, the recorder. */
export function isDemo(search: string = window.location.search): boolean {
  return new URLSearchParams(search).get("demo") === "1";
}

/** What App needs from video mode. */
export type DemoControls = { next: () => void };

/** The tour that stands in for the camera in video mode; null otherwise. */
export const demoCamera: TourCamera | null = typeof window !== "undefined" && isDemo() ? tourCamera() : null;
