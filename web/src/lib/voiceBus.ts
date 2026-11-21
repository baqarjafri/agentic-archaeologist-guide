/**
 * One AudioContext for the guide's voice, and one bus the voice plays through. The bus goes to the speakers;
 * the demo recorder taps it too, so a recording hears exactly what the guide says.
 */
type VoiceBus = { ctx: AudioContext; bus: GainNode };

let shared: VoiceBus | null = null;

export function voiceBus(make: () => AudioContext = () => new AudioContext({ sampleRate: 24000 })): VoiceBus {
  if (!shared) {
    const ctx = make(); // the voice's own rate: chunks join without resampling seams
    const bus = ctx.createGain();
    bus.connect(ctx.destination);
    shared = { ctx, bus };
  }
  return shared;
}

/** For tests only. */
export function resetVoiceBus(): void {
  shared = null;
}
