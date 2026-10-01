import {
  Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { useLiveStream } from "./useLiveStream";
import "./App.css";

// Color follows the entity (event type), never its rank: fixed slot per type.
const TYPE_SLOT = {
  page_view: 1, click: 2, add_to_cart: 3, purchase: 4, signup: 5, bench: 7, error: 8,
};
const colorOf = (t) => (TYPE_SLOT[t] ? `var(--series-${TYPE_SLOT[t]})` : "var(--series-other)");
const fmt = (n) => (n == null ? "—" : Intl.NumberFormat("en-US").format(n));
const hhmm = (t) => new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

function Kpi({ label, value, unit, hint }) {
  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">
        {value}
        {unit && <span className="kpi-unit">{unit}</span>}
      </div>
      {hint && <div className="kpi-hint">{hint}</div>}
    </div>
  );
}

function SeriesTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  const rows = Object.entries(d.byType).sort((a, b) => b[1] - a[1]);
  return (
    <div className="tip">
      <div className="tip-head">{hhmm(d.t)} · {fmt(d.total)} events</div>
      {rows.map(([t, n]) => (
        <div key={t} className="tip-row">
          <span className="dot" style={{ background: colorOf(t) }} />
          <span>{t}</span>
          <span className="num">{fmt(n)}</span>
        </div>
      ))}
    </div>
  );
}

export default function App() {
  const { status, summary, series, breakdown, feed, latency } = useLiveStream();
  const bars = Object.entries(breakdown)
    .map(([type, count]) => ({ type, count }))
    .sort((a, b) => b.count - a.count);

  return (
    <div className="viz-root">
      <header>
        <h1>Event Stream</h1>
        <span className={`status status-${status}`}>
          <span className="status-dot" />
          {status}
        </span>
      </header>

      <section className="kpis">
        <Kpi label="Events today" value={fmt(summary?.events_today)} />
        <Kpi label="Last full minute" value={fmt(summary?.events_last_minute)} unit="/min"
             hint={`${fmt(summary?.events_this_minute)} so far this minute`} />
        <Kpi label="Active users" value={fmt(summary?.active_users_5m)} hint="unique, last 5 min (HLL)" />
        <Kpi label="Ingest → screen" value={latency.p50 == null ? "—" : Math.round(latency.p50)} unit="ms"
             hint={latency.p95 == null ? "p50, waiting for events" : `p50 · p95 ${Math.round(latency.p95)} ms`} />
        <Kpi label="Live viewers" value={fmt(summary?.ws_clients)} hint="WebSocket connections, all pods" />
      </section>

      <section className="grid">
        <div className="card wide">
          <h2>Events per minute <span className="sub">last 60 min</span></h2>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={series} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="t" tickFormatter={hhmm} stroke="var(--text-muted)" tickLine={false}
                     axisLine={{ stroke: "var(--grid)" }} minTickGap={40} fontSize={12} />
              <YAxis stroke="var(--text-muted)" tickLine={false} axisLine={false} width={48} fontSize={12}
                     allowDecimals={false} />
              <Tooltip content={<SeriesTooltip />} cursor={{ stroke: "var(--text-muted)", strokeDasharray: "3 3" }} />
              <Line type="monotone" dataKey="total" stroke="var(--series-1)" strokeWidth={2} dot={false}
                    isAnimationActive={false} activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface-1)" }} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="card">
          <h2>By event type <span className="sub">last 60 min</span></h2>
          <ResponsiveContainer width="100%" height={Math.max(160, bars.length * 34)}>
            <BarChart data={bars} layout="vertical" margin={{ top: 0, right: 48, bottom: 0, left: 0 }}
                      barCategoryGap={6}>
              <XAxis type="number" hide />
              <YAxis type="category" dataKey="type" width={96} tickLine={false} axisLine={false}
                     stroke="var(--text-secondary)" fontSize={12} />
              <Tooltip cursor={{ fill: "var(--hover)" }} formatter={(v) => [fmt(v), "events"]}
                       contentStyle={{ background: "var(--surface-2)", border: "1px solid var(--grid)",
                                       borderRadius: 8, color: "var(--text-primary)" }} />
              <Bar dataKey="count" radius={[0, 4, 4, 0]} isAnimationActive={false}
                   label={{ position: "right", fill: "var(--text-secondary)", fontSize: 12,
                            formatter: fmt }}>
                {bars.map((b) => <Cell key={b.type} fill={colorOf(b.type)} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="card feed-card">
          <h2>Live feed</h2>
          <ul className="feed">
            {feed.map((e, i) => (
              <li key={`${e.ingested_at}-${i}`}>
                <span className="dot" style={{ background: colorOf(e.type) }} />
                <span className="feed-type">{e.type}</span>
                <span className="feed-user">{e.user_id}</span>
                <span className="feed-page">{e.props?.page || ""}</span>
                <span className="num">{e.value ? fmt(e.value) : ""}</span>
                <span className="feed-time">{new Date(e.occurred_at).toLocaleTimeString()}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </div>
  );
}
