const API_URL = (import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
export type Source = { url: string; type: string; first_seen: string };
export type Draft = { title: string; lede: string; bullets: string[]; quote: string; attribution: string[] };
export type Event = {
  id:string; headline:string; hotness:number; why_now?:string; confirmed:boolean;
  sources: Source[]; draft?: Draft;
};

export async function fetchEvents(params: Record<string, string | number | boolean | undefined> = {}) {
  const qs = Object.entries(params).filter(([,v]) => v !== undefined && v !== "")
    .map(([k,v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join("&");
  const r = await fetch(`${API_URL}/events${qs ? "?" + qs : ""}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return (await r.json()) as Event[];
}

export async function fetchEvent(id: string, lang?: string) {
  const r = await fetch(`${API_URL}/events/${id}${lang ? `?lang=${lang}` : ""}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return (await r.json()) as Event;
}

export async function generateDraft(id: string, lang?: string) {
  const r = await fetch(`${API_URL}/events/${id}/generate${lang ? `?lang=${lang}` : ""}`, { method: "POST" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return (await r.json()) as Event;
}

// + ниже ваших существующих типов/функций
export type Health = {
  ok: boolean;
  events: number;
  sources: number;
  last_source: string | null;
};

export async function fetchHealth(): Promise<Health> {
  const r = await fetch(`${API_URL}/health`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}
