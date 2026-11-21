export type PartView = { title: string; passages: string[] };
export type ObjectView = {
  id: string;
  title: string;
  meta: string[];
  record_url: string;
  display_image: string;
  parts: PartView[];
  passages: Record<string, string>;
  accession?: string;
};
export type RelationView = { key: string; a: string; b: string; theme: string; passages: string[] };
export type PackView = {
  id: string; title: string; credit: string; objects: ObjectView[]; relations: RelationView[];
  short_name?: string; record_label?: string; // a pack that sets neither keeps the pilot's Glasgow wording
};

/** "Glasgow Museums record 13.181", or the pack's own label and accession number. */
export function recordName(pack: PackView, objectId: string): string {
  const object = pack.objects.find((o) => o.id === objectId);
  return `${pack.record_label ?? "Glasgow Museums record"} ${object?.accession ?? objectId}`;
}
export type Candidate = { object_id: string; score: number };
export type IdentifyResult = { accepted: boolean; object_id: string | null; score: number; candidates: Candidate[] };

const CODE_KEY = "aa-access-code";

export function accessCode(search: string = window.location.search, store?: Storage): string {
  const fromUrl = new URLSearchParams(search).get("code");
  try {
    const s = store ?? window.localStorage; // reading localStorage itself throws when the browser blocks storage
    if (fromUrl) s.setItem(CODE_KEY, fromUrl);
    return fromUrl ?? s.getItem(CODE_KEY) ?? "";
  } catch {
    return fromUrl ?? ""; // the code from the link still works for this visit
  }
}

export function withCode(path: string, code: string): string {
  if (!code) return path;
  return path + (path.includes("?") ? "&" : "?") + "code=" + encodeURIComponent(code);
}

export function socketUrl(code: string, location: Location = window.location): string {
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return withCode(`${scheme}//${location.host}/ws/session`, code);
}

export async function fetchPack(code: string): Promise<PackView> {
  const response = await fetch(withCode("/api/pack", code));
  if (!response.ok) throw new Error(`pack ${response.status}`);
  return response.json();
}

export async function identify(frame: Blob, code: string): Promise<IdentifyResult> {
  const body = new FormData();
  body.append("image", frame, "frame.jpg");
  const response = await fetch(withCode("/api/identify", code), { method: "POST", body });
  if (!response.ok) throw new Error(`identify ${response.status}`);
  return response.json();
}
