import { useEffect, useState } from "react";
import { fetchEvents, fetchEvent, generateDraft, type Event } from "./lib/api";
import EventCard from "./components/EventCard";

type ConfirmState = "" | "true" | "false";
type Health = { ok: boolean; events: number; sources: number; last_source: string | null };

function Modal({
  open,
  onClose,
  children,
}: {
  open: boolean;
  onClose: () => void;
  children: any;
}) {
  if (!open) return null;
  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,.3)",
        display: "grid",
        placeItems: "center",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ background: "#fff", maxWidth: 900, width: "90%", borderRadius: 12, padding: 16 }}
      >
        {children}
      </div>
    </div>
  );
}

export default function App() {
  const [items, setItems] = useState<Event[]>([]);
  const [q, setQ] = useState(""); // поиск
  const [minHot, setMinHot] = useState(0.0); // фильтр hotness
  const [confirmed, setConfirmed] = useState<ConfirmState>("");
  const [types, setTypes] = useState<string[]>(["regulator", "news"]);
  const [selId, setSelId] = useState<string | null>(null);
  const [selEvent, setSelEvent] = useState<Event | null>(null);
  const [loading, setLoading] = useState(false);
  const [auto, setAuto] = useState(true); // автообновление
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);

  // Закладки
  const [starred, setStarred] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem("starred") || "[]");
    } catch {
      return [];
    }
  });
  const [onlyStarred, setOnlyStarred] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    const params = {
      q: q || undefined,
      min_hotness: minHot || undefined,
      confirmed: confirmed === "" ? undefined : confirmed,
      types: types.length ? types.join(",") : undefined,
      limit: 50,
    };
    try {
      const data = await fetchEvents(params);
      setItems(data);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!auto) return;
    const t = setInterval(load, 60_000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auto, q, minHot, confirmed, types]);

  // health пуллинг
  useEffect(() => {
    let cancelled = false;
    async function loadHealth() {
      try {
        const r = await fetch("http://127.0.0.1:8000/health");
        if (!r.ok) return;
        const h = (await r.json()) as Health;
        if (!cancelled) setHealth(h);
      } catch {}
    }
    loadHealth();
    const t = setInterval(loadHealth, 60_000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  // открыть карточку
  const onOpen = async (id: string) => {
    setSelId(id);
    const full = await fetchEvent(id);
    setSelEvent(full);
  };

  function toggleStar(id: string) {
    setStarred((prev) => {
      const next = prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id];
      localStorage.setItem("starred", JSON.stringify(next));
      return next;
    });
  }

  const copyDraft = () => {
    if (!selEvent?.draft) return;
    const d = selEvent.draft;
    const md = `# ${d.title}\n\n${d.lede}\n\n- ${d.bullets.join("\n- ")}\n\n${
      d.quote ? `> ${d.quote}\n\n` : ""
    }${d.attribution.join("\n")}\n`;
    navigator.clipboard.writeText(md);
    alert("Черновик скопирован в буфер.");
  };

  const generate = async () => {
    if (!selId) return;
    const updated = await generateDraft(selId);
    setSelEvent(updated);
    setItems((prev) => prev.map((x) => (x.id === updated.id ? updated : x)));
  };

  const toolbar = (
    <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", marginBottom: 16 }}>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Поиск по заголовку"
        style={{ padding: 8, borderRadius: 8, border: "1px solid #ddd", flex: "1 1 260px" }}
      />
      <label>
        min hotness
        <input
          type="number"
          step="0.01"
          min={0}
          max={1}
          value={minHot}
          onChange={(e) => setMinHot(Number(e.target.value))}
          style={{ marginLeft: 8, width: 80 }}
        />
      </label>
      <select value={confirmed} onChange={(e) => setConfirmed(e.target.value as ConfirmState)} style={{ padding: 8, borderRadius: 8 }}>
        <option value="">all</option>
        <option value="true">confirmed</option>
        <option value="false">pending</option>
      </select>
      <label style={{ fontSize: 12 }}>
        <input type="checkbox" checked={onlyStarred} onChange={(e) => setOnlyStarred(e.target.checked)} /> только избранное
      </label>
      <div style={{ display: "flex", gap: 8 }}>
        {["regulator", "ir", "news", "exchange", "aggregator"].map((t) => (
          <label key={t} style={{ fontSize: 12 }}>
            <input
              type="checkbox"
              checked={types.includes(t)}
              onChange={() => {
                setTypes((v) => (v.includes(t) ? v.filter((x) => x !== t) : [...v, t]));
              }}
            />{" "}
            {t}
          </label>
        ))}
      </div>
      <button onClick={load} style={{ padding: "8px 12px", borderRadius: 8 }}>
        Применить
      </button>
      <label style={{ fontSize: 12 }}>
        <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> автообновление
      </label>
    </div>
  );

  const list = onlyStarred ? items.filter((i) => starred.includes(i.id)) : items;

  return (
    <div style={{ maxWidth: 980, margin: "24px auto", padding: "0 16px" }}>
      <h1>Fin News Hot</h1>
      {health && (
        <div
          style={{
            display: "flex",
            gap: 12,
            alignItems: "center",
            marginTop: 8,
            marginBottom: 8,
            fontSize: 12,
            color: "#666",
          }}
        >
          <span style={{ padding: "2px 8px", border: "1px solid #eee", borderRadius: 999 }}>
            events: <b>{health.events}</b>
          </span>
          <span style={{ padding: "2px 8px", border: "1px solid #eee", borderRadius: 999 }}>
            sources: <b>{health.sources}</b>
          </span>
          <span style={{ padding: "2px 8px", border: "1px solid #eee", borderRadius: 999 }}>
            last: {health.last_source ? new Date(health.last_source).toLocaleString() : "—"}
          </span>
        </div>
      )}
      {toolbar}
      <div style={{ display: "grid", gap: 12 }}>
        {list.map((e) => (
          <div key={e.id} onClick={() => onOpen(e.id)} style={{ cursor: "pointer" }}>
            <EventCard e={e} starred={starred.includes(e.id)} onToggleStar={toggleStar} />
          </div>
        ))}
        {!loading && list.length === 0 && <div>Ничего не найдено под фильтры.</div>}
      </div>
      {loading && <div>Загружаю…</div>}
      {error && <div style={{ color: "crimson" }}>Ошибка: {error}</div>}

      <Modal
        open={!!selId}
        onClose={() => {
          setSelId(null);
          setSelEvent(null);
        }}
      >
        {selEvent ? (
          <div>
            <h2 style={{ marginTop: 0 }}>{selEvent.headline}</h2>
            <p style={{ marginTop: 12 }}>{selEvent.why_now ?? "Why now появится после генерации."}</p>
            {selEvent.draft && (
              <div style={{ background: "#fafafa", border: "1px solid #eee", borderRadius: 8, padding: 12, marginTop: 8 }}>
                <b>{selEvent.draft.title}</b>
                <p>{selEvent.draft.lede}</p>
                <ul>{selEvent.draft.bullets.map((b, i) => <li key={i}>{b}</li>)}</ul>
                {selEvent.draft.quote && <blockquote>{selEvent.draft.quote}</blockquote>}
                <div style={{ fontSize: 12 }}>{selEvent.draft.attribution.join(" • ")}</div>
              </div>
            )}
            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <button onClick={generate} style={{ padding: "8px 12px", borderRadius: 8 }}>
                Сгенерировать
              </button>
              <button onClick={copyDraft} disabled={!selEvent?.draft} style={{ padding: "8px 12px", borderRadius: 8 }}>
                Копировать черновик
              </button>
              <button
                onClick={() => {
                  setSelId(null);
                  setSelEvent(null);
                }}
                style={{ padding: "8px 12px", borderRadius: 8 }}
              >
                Закрыть
              </button>
            </div>
            <div style={{ marginTop: 12, fontSize: 12 }}>
              Источники:{" "}
              {selEvent.sources.map((s, i) => (
                <a key={i} href={s.url} target="_blank" rel="noreferrer" style={{ marginRight: 12 }}>
                  {new URL(s.url).host}
                </a>
              ))}
            </div>
          </div>
        ) : (
          <div>Загрузка…</div>
        )}
      </Modal>
    </div>
  );
}