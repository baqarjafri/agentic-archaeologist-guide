import type { IdentifyResult } from "./api";

/** Shows a piece only when `need` of the last `size` frames agree on it. */
export class Voter {
  private recent: (string | null)[] = [];

  constructor(private readonly size = 5, private readonly need = 3) {}

  push(result: IdentifyResult): string | null {
    this.recent.push(result.accepted ? result.object_id : null);
    if (this.recent.length > this.size) this.recent.shift();
    const counts = new Map<string, number>();
    for (const id of this.recent) if (id) counts.set(id, (counts.get(id) ?? 0) + 1);
    let best: string | null = null;
    let bestCount = 0;
    for (const [id, n] of counts) {
      if (n > bestCount) {
        best = id;
        bestCount = n;
      }
    }
    return bestCount >= this.need ? best : null;
  }

  reset(): void {
    this.recent = [];
  }
}
