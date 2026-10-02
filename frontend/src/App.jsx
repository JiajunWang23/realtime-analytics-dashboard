import { useEffect, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { SOURCES, colorOf } from "./sources";
import { transport, useLiveStream } from "./useLiveStream";
import "./App.css";

const REPO = "https://github.com/JiajunWang23/realtime-analytics-dashboard";
const AUTHOR_SITE = "https://uiucwangjiajun.com";
const SOURCE = "wikipedia";
const fmt = (n) => (n == null ? "—" : Intl.NumberFormat("en-US").format(n));
const pct = (n) => (n == null ? "—" : `${Math.round(n * 100)}`);
const hhmm = (t) => new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

function useRealtimeMode() {
  const [mode, setMode] = useState(null);
  useEffect(() => { transport().then((c) => setMode(c.realtime)); }, []);
  return mode;
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

/** Label + value on one line, bar underneath. Text stays in text ink; the bar carries color. */
function BarList({ rows, colorFor, limit = 8 }) {
  const total = rows.reduce((a, r) => a + r.count, 0);
  const max = Math.max(1, ...rows.map((r) => r.count));
  if (!rows.length) return <div className="empty-small">Nothing yet in the last 60 minutes</div>;
  return (
    <ul className="barlist">
      {rows.slice(0, limit).map((r) => (
        <li key={r.key} title={`${r.label}: ${fmt(r.count)}`}>
          <div className="bl-row">
            <span className="bl-label">{r.label}</span>
            <span className="bl-value">
              {fmt(r.count)}
              <span className="bl-share">{total ? Math.round((100 * r.count) / total) : 0}%</span>
            </span>
          </div>
          <span className="bl-track">
            <span className="bl-bar" style={{ width: `${(100 * r.count) / max}%`, background: colorFor(r.key) }} />
          </span>
        </li>
      ))}
    </ul>
  );
}

function SeriesTooltip({ active, payload, source }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  const cfg = SOURCES[source];
  const rows = Object.entries(d.byType).sort((a, b) => b[1] - a[1]);
  return (
    <div className="tip">
      <div className="tip-head">{hhmm(d.t)} · {fmt(d.total)} total</div>
      {rows.map(([t, n]) => (
        <div key={t} className="tip-row">
          <span className="dot" style={{ background: colorOf(source, t) }} />
          <span>{cfg.typeLabels[t] || t}</span>
          <span className="num">{fmt(n)}</span>
        </div>
      ))}
    </div>
  );
}

function Pipeline({ mode, latency }) {
  const steps = [
    { n: 1, title: "Wikipedia's live feed", body: "Wikimedia publishes every change as a server-sent event stream." },
    { n: 2, title: "Ingest API", body: "Python + Flask validates each event and writes it in batches." },
    { n: 3, title: "PostgreSQL", body: "Raw events plus per-minute summaries, indexed so charts stay fast at 5M+ rows." },
    mode === "ws"
      ? { n: 4, title: "Redis → WebSocket", body: "Redis pub/sub fans each batch out to every server, which pushes it to open browsers." }
      : { n: 4, title: "Live updates", body: "This page asks for new events every second (this host doesn't allow WebSockets)." },
    { n: 5, title: "This page", body: `React renders it.${latency.p50 != null ? ` Right now that takes ~${Math.round(latency.p50)} ms end to end.` : ""}` },
  ];
  return (
    <ol className="pipeline">
      {steps.map((s) => (
        <li key={s.n}>
          <span className="step-n">{s.n}</span>
          <div>
            <div className="step-title">{s.title}</div>
            <div className="step-body">{s.body}</div>
          </div>
        </li>
      ))}
    </ol>
  );
}

export default function App() {
  const source = SOURCE;
  const mode = useRealtimeMode();
  const cfg = SOURCES[source];
  const { status, summary, series, breakdown, dims, feed, latency } = useLiveStream(source);

  const typeRows = Object.entries(breakdown)
    .map(([key, count]) => ({ key, label: cfg.typeLabels[key] || key, count }))
    .sort((a, b) => b.count - a.count);
  const dimRows = (d) =>
    Object.entries(dims[d.key] || {})
      .map(([key, count]) => ({ key, label: d.format ? d.format(key) : key, count }))
      .sort((a, b) => b.count - a.count);

  let share = null;
  if (cfg.shareKpi) {
    const rows = Object.entries(dims[cfg.shareKpi.dim] || {});
    const total = rows.reduce((a, [, n]) => a + n, 0);
    const hit = rows.find(([k]) => k === cfg.shareKpi.value)?.[1] || 0;
    share = total ? hit / total : null;
  }
  const isEmpty = summary && summary.events_today === 0 && !feed.length;

  return (
    <div className="viz-root">
      <header className="hero">
        <p className="eyebrow">Portfolio project by <a href={AUTHOR_SITE}>Jiajun Wang</a></p>
        <h1>Real-Time Analytics Dashboard</h1>
        <p className="lede">
          A live data pipeline you can watch working. Events stream in from the outside world, get stored and
          aggregated in a database, and show up on this page about a second later.
        </p>
        <div className="hero-links">
          <a className="btn" href={REPO} target="_blank" rel="noreferrer">View the code on GitHub</a>
          <a className="btn ghost" href="#how" onClick={(e) => { e.preventDefault(); document.getElementById("how")?.scrollIntoView({ behavior: "smooth" }); }}>
            How it works
          </a>
          <span className={`status status-${status}`} title="Connection to the live data">
            <span className="status-dot" />
            {status === "live" ? "Live" : status}
          </span>
        </div>
      </header>


      <section className="explain">
        <h2 className="headline">{cfg.headline}</h2>
        <p>{cfg.blurb}</p>
        {cfg.note && <p className="note">{cfg.note}</p>}
      </section>

      <section className="kpis">
        <Kpi label={cfg.kpis.today.label} value={fmt(summary?.events_today)} hint={cfg.kpis.today.hint(summary)} />
        <Kpi label={cfg.kpis.active.label} value={fmt(summary?.active_users_5m)} hint={cfg.kpis.active.hint()} />
        <Kpi label={cfg.kpis.uniqueToday.label} value={fmt(summary?.unique_users_today)} hint={cfg.kpis.uniqueToday.hint()} />
        {cfg.shareKpi && <Kpi label={cfg.shareKpi.label} value={pct(share)} unit="%" hint={cfg.shareKpi.hint} />}
        <Kpi label="Delay to this screen" value={latency.p50 == null ? "—" : Math.round(latency.p50)} unit="ms"
             hint={latency.p50 == null ? "measured as events arrive" : "from event stored to shown here (median)"} />
      </section>

      {isEmpty && <div className="empty-banner">{cfg.empty}</div>}

      <section className="grid">
        <div className="card wide">
          <h3>{cfg.chartTitle} <span className="sub">last hour, one point per completed minute</span></h3>
          <ResponsiveContainer width="100%" height={220}>
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
          <h3>What kind of activity <span className="sub">last 60 min</span></h3>
          <BarList rows={typeRows} colorFor={(t) => colorOf(source, t)} />
        </div>

        {cfg.dims.map((d) => (
          <div className="card" key={d.key}>
            <h3>{d.title} <span className="sub">last 60 min</span></h3>
            <BarList rows={dimRows(d)} colorFor={() => "var(--bar-neutral)"} />
          </div>
        ))}

        <div className="card feed-card wide">
          <h3>{cfg.feedTitle}</h3>
          <ul className="feed">
            {feed.map((e, i) => {
              const row = cfg.feedRow(e, cfg);
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

      <section className="how" id="how">
        <h2 className="headline">How it works</h2>
        <p>Every number on this page travels through the same five steps:</p>
        <Pipeline mode={mode} latency={latency} />
        <p className="stack">
          <strong>Built with</strong> Python · Flask · PostgreSQL · Redis · WebSocket · React · Docker · Kubernetes
          {mode === "poll" ? " · deployed here on Vercel + Neon Postgres" : ""}
        </p>
        <p className="note">
          The full version (Docker / Kubernetes) uses Redis pub/sub and WebSockets for sub-100 ms updates, and was
          load-tested at 1,000 concurrent viewers. Benchmarks and design notes are in the{" "}
          <a href={REPO} target="_blank" rel="noreferrer">README</a>.
        </p>
      </section>

      <footer>
        Built by <a href={AUTHOR_SITE}>Jiajun Wang</a> · <a href={REPO} target="_blank" rel="noreferrer">Source on GitHub</a>
      </footer>
    </div>
  );
}
