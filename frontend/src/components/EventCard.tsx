import type { Event } from "../lib/api";

function StarIcon({ filled }: { filled: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24"
         fill={filled ? "currentColor" : "none"} stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="12 2 15 9 22 9 17 14 19 21 12 17 5 21 7 14 2 9 9 9 12 2" />
    </svg>
  );
}

export default function EventCard({ e, starred = false, onToggleStar }: { e: Event; starred?: boolean; onToggleStar?: (id: string) => void }) {
  return (
    <div style={{ border: "1px solid #eee", borderRadius: 12, padding: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 style={{ margin: 0 }}>{e.headline}</h3>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span title="hotness">🔥 {e.hotness.toFixed(2)}</span>
          <button
            onClick={(ev) => { ev.stopPropagation(); onToggleStar?.(e.id); }}
            title={starred ? "Убрать из избранного" : "В избранное"}
            aria-label={starred ? "Unstar" : "Star"}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "4px 8px",
              border: "1px solid #eee",
              borderRadius: 8,
              background: starred ? "#fff7cc" : "#f7f7f7",
              cursor: "pointer"
            }}
          >
            <span style={{ color: starred ? "#eab308" : "#666" }}>
              <StarIcon filled={starred} />
            </span>
            <span style={{ fontSize: 12, color: "#555" }}>{starred ? "В избранном" : "В избранное"}</span>
          </button>
        </div>
      </div>
      <p style={{ margin: "8px 0 0 0" }}>{e.why_now ?? "Контекст уточняется..."}</p>
      <div style={{ marginTop: 8, fontSize: 12 }}>
        {e.sources.slice(0, 3).map((s, i) => (
          <a key={i} href={s.url} target="_blank" rel="noreferrer" style={{ marginRight: 12 }}>
            {new URL(s.url).host}
          </a>
        ))}
        {e.confirmed && (
          <span style={{ marginLeft: 8, padding: "2px 6px", background: "#e6ffed", borderRadius: 6 }}>
            confirmed
          </span>
        )}
      </div>
    </div>
  );
}