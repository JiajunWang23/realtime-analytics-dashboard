import { useEffect, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { SOURCES, colorOf } from "./sources";
import { useLiveStream } from "./useLiveStream";
import "./App.css";

const TAB_ORDER = ["wikipedia", "site", "demo"];
const fmt = (n) => (n == null ? "—" : Intl.NumberFormat("en-US").format(n));
const pct = (n) => (n == null ? "—" : `${Math.round(n * 100)}`);
const hhmm = (t) => new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

function useHashTab() {
  const read = () => {
    const h = location.hash.slice(1);
    return SOURCES[h] ? h : TAB_ORDER[0];
  };
  const [tab, setTab] = useState(read);
  useEffect(() => {
    const on = () => setTab(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return [tab, (t) => { location.hash = t; }];
}

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

/** Horizontal bar list: label · bar · value. Text stays in text ink; the bar carries color. */
function BarList({ rows, colorFor, limit = 8, showShare = true }) {
  const total = rows.reduce((a, r) => a + r.count, 0);
  const max = Math.max(1, ...rows.map((r) => r.count));
  if (!rows.length) return <div className="empty-small">No data in the last 60 min</div>;
  return (
    <ul className="barlist">
      {rows.slice(0, limit).map((r) => (
        <li key={r.label} title={`${r.label}: ${fmt(r.count)}`}>
          <div className="bl-row">
            <span className="bl-label">{r.label}</span>
            <span className="bl-value">
              {fmt(r.count)}
              {showShare && <span className="bl-share">{total ? Math.round((100 * r.count) / total) : 0}%</span>}
            </span>
          </div>
          <span className="bl-track">
            <span className="bl-bar" style={{ width: `${(100 * r.count) / max}%`, background: colorFor(r.label) }} />
          </span>
        </li>
      ))}
    </ul>
  );
}

function SeriesTooltip({ active, payload, source }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  const rows = Object.entries(d.byType).sort((a, b) => b[1] - a[1]);
  return (
    <div className="tip">
      <div className="tip-head">{hhmm(d.t)} · {fmt(d.total)} events</div>
      {rows.map(([t, n]) => (
        <div key={t} className="tip-row">
          <span className="dot" style={{ background: colorOf(source, t) }} />
          <span>{t}</span>
          <span className="num">{fmt(n)}</span>
        </div>
      ))}
    </div>
  );
}

export default function App() {
  const [source, setSource] = useHashTab();
  const cfg = SOURCES[source];
  const { status, summary, wsClients, series, breakdown, dims, feed, latency } = useLiveStream(source);

  const typeRows = Object.entries(breakdown)
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count);
  const dimRows = (key) =>
    Object.entries(dims[key] || {})
      .map(([label, count]) => ({ label, count }))
      .sort((a, b) => b.count - a.count);

  let share = null;
  if (cfg.shareKpi) {
    const rows = dimRows(cfg.shareKpi.dim);
    const total = rows.reduce((a, r) => a + r.count, 0);
    const hit = rows.find((r) => r.label === cfg.shareKpi.value)?.count || 0;
    share = total ? hit / total : null;
  }
  const isEmpty = summary && summary.events_today === 0 && !feed.length;

  return (
    <div className="viz-root">
      <header>
        <div className="title-block">
          <h1>Real-Time Analytics</h1>
          <span className={`status status-${status}`}>
            <span className="status-dot" />
            {status}
          </span>
        </div>
        <nav className="tabs" role="tablist">
          {TAB_ORDER.map((s) => (
            <button key={s} role="tab" aria-selected={s === source}
                    className={s === source ? "tab active" : "tab"} onClick={() => setSource(s)}>
              {SOURCES[s].label}
            </button>
          ))}
        </nav>
      </header>
      <p className="subtitle">{cfg.subtitle}</p>

      <section className="kpis">
        <Kpi label={cfg.kpis.today} value={fmt(summary?.events_today)}
             hint={`${fmt(summary?.events_last_minute)} in the last full minute`} />
        <Kpi label={cfg.kpis.active} value={fmt(summary?.active_users_5m)} hint={cfg.kpis.activeHint} />
        <Kpi label={cfg.kpis.uniqueToday} value={fmt(summary?.unique_users_today)} hint="HyperLogLog estimate" />
        {cfg.shareKpi ? (
          <Kpi label={cfg.shareKpi.label} value={pct(share)} unit="%" hint={cfg.shareKpi.hint} />
        ) : (
          <Kpi label={cfg.kpis.lastMin} value={fmt(summary?.events_last_minute)} unit="/min" />
        )}
        <Kpi label="Event → screen" value={latency.p50 == null ? "—" : Math.round(latency.p50)} unit="ms"
             hint={latency.p95 == null ? "p50 · waiting for events"
               : `p50 · p95 ${Math.round(latency.p95)} ms · ${fmt(wsClients)} viewer${wsClients === 1 ? "" : "s"}`} />
      </section>

      {isEmpty && <div className="empty-banner">{cfg.empty}</div>}

      <section className="grid">
        <div className="card wide">
          <h2>Events per minute <span className="sub">last 60 completed minutes</span></h2>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={series} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="t" tickFormatter={hhmm} stroke="var(--text-muted)" tickLine={false}
                     axisLine={{ stroke: "var(--grid)" }} minTickGap={40} fontSize={12} />
              <YAxis stroke="var(--text-muted)" tickLine={false} axisLine={false} width={52} fontSize={12}
                     allowDecimals={false} />
              <Tooltip content={<SeriesTooltip source={source} />}
                       cursor={{ stroke: "var(--text-muted)", strokeDasharray: "3 3" }} />
              <Line type="monotone" dataKey="total" stroke="var(--series-1)" strokeWidth={2} dot={false}
                    isAnimationActive={false} activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface-1)" }} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="card">
          <h2>By event type <span className="sub">last 60 min</span></h2>
          <BarList rows={typeRows} colorFor={(t) => colorOf(source, t)} />
        </div>

        {cfg.dims.map((d) => (
          <div className="card" key={d.key}>
            <h2>{d.title} <span className="sub">last 60 min</span></h2>
            <BarList rows={dimRows(d.key)} colorFor={() => "var(--bar-neutral)"} />
          </div>
        ))}

        <div className="card feed-card wide">
          <h2>Live feed</h2>
          <ul className="feed">
            {feed.map((e, i) => {
              const row = cfg.feedRow(e);
              return (
                <li key={`${e.ingested_at}-${i}`}>
                  <span className="dot" style={{ background: colorOf(source, e.type) }} />
                  <span className="feed-main">
                    {row.href ? <a href={row.href} target="_blank" rel="noreferrer">{row.main}</a> : row.main}
                  </span>
                  <span className="feed-sec">{row.secondary}</span>
                  <span className="feed-sec">{row.tertiary}</span>
                  <span className="feed-time">{new Date(e.occurred_at).toLocaleTimeString()}</span>
                </li>
              );
            })}
          </ul>
        </div>
      </section>
    </div>
  );
}
