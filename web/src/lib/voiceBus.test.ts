import { expect, test } from "vitest";
import { resetVoiceBus, voiceBus } from "./voiceBus";

test("one context and one bus, and the bus goes to the speakers", () => {
  resetVoiceBus();
  let made = 0;
  const make = () => {
    made++;
    const bus = { connected: null as unknown, connect(node: unknown) { this.connected = node; } };
    return { destination: { name: "speakers" }, createGain: () => bus } as unknown as AudioContext;
  };
  const a = voiceBus(make);
  const b = voiceBus(make);
  expect(made).toBe(1);
  expect(b).toBe(a);
  expect((a.bus as unknown as { connected: unknown }).connected).toBe(a.ctx.destination);
  resetVoiceBus();
});
