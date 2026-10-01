import { useEffect, useRef, useState } from "react";

const WINDOW_MIN = 60;
const FEED_MAX = 80;
const LAT_SAMPLES = 500;

const minuteKey = (iso) => {
  const d = new Date(iso);
  d.setSeconds(0, 0);
  return d.getTime();
};

// Recharts freezes the data objects it is handed, so buckets are replaced, never mutated.
function bump(map, t, type, n) {
  const prev = map.get(t) || { t, total: 0, byType: {} };
  map.set(t, {
    t,
    total: prev.total + n,
    byType: { ...prev.byType, [type]: (prev.byType[type] || 0) + n },
  });
}

function wsUrl() {
  const env = import.meta.env.VITE_WS_URL;
  if (env) return env;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}/ws`;
}

/**
 * Seeds state from REST, then keeps it live over one WebSocket.
 * Incoming frames are buffered in refs and committed to React state every 250 ms,
 * so a burst of thousands of events costs four renders per second, not thousands.
 */
export function useLiveStream() {
  const [status, setStatus] = useState("connecting");
  const [summary, setSummary] = useState(null);
  const [series, setSeries] = useState([]);       // [{t, total, byType}]
  const [breakdown, setBreakdown] = useState({}); // type -> count (last 60 min)
  const [feed, setFeed] = useState([]);
  const [latency, setLatency] = useState({ p50: null, p95: null });

  const buf = useRef({ events: [], stats: null });
  const seriesMap = useRef(new Map());
  const counts = useRef({});
  const lat = useRef([]);

  // ---- initial load from REST -------------------------------------------
  useEffect(() => {
    const api = import.meta.env.VITE_API_URL || "";
    Promise.all([
      fetch(`${api}/api/stats/timeseries?minutes=${WINDOW_MIN}`).then((r) => r.json()),
      fetch(`${api}/api/stats/breakdown?minutes=${WINDOW_MIN}`).then((r) => r.json()),
      fetch(`${api}/api/events/recent?limit=${FEED_MAX}`).then((r) => r.json()),
      fetch(`${api}/api/stats/summary`).then((r) => r.json()),
    ])
      .then(([ts, bd, recent, sum]) => {
        for (const row of ts) {
          bump(seriesMap.current, minuteKey(row.bucket), row.type, row.count);
        }
        for (const row of bd) counts.current[row.event_type] = Number(row.count);
        setFeed(recent);
        setSummary(sum);
        commitSeries();
        setBreakdown({ ...counts.current });
      })
      .catch(() => {});
  }, []);

  function commitSeries() {
    const now = Date.now();
    const cutoff = now - WINDOW_MIN * 60_000;
    // fill gaps so quiet minutes render as zero rather than an interpolated line
    const out = [];
    const start = Math.floor(cutoff / 60_000) * 60_000;
    for (let t = start; t <= now; t += 60_000) {
      out.push(seriesMap.current.get(t) || { t, total: 0, byType: {} });
    }
    for (const k of seriesMap.current.keys()) if (k < start) seriesMap.current.delete(k);
    setSeries(out);
  }

  // ---- WebSocket with exponential back-off ------------------------------
  useEffect(() => {
    let ws;
    let retry = 0;
    let timer;
    let closed = false;

    const connect = () => {
      setStatus(retry ? "reconnecting" : "connecting");
      ws = new WebSocket(wsUrl());
      ws.onopen = () => {
        retry = 0;
        setStatus("live");
      };
      ws.onmessage = (m) => {
        const msg = JSON.parse(m.data);
        if (msg.kind === "events") buf.current.events.push(...msg.events);
        else if (msg.kind === "stats" || msg.kind === "hello") buf.current.stats = msg;
      };
      ws.onclose = () => {
        if (closed) return;
        setStatus("reconnecting");
        const delay = Math.min(30_000, 500 * 2 ** retry++) * (0.5 + Math.random());
        timer = setTimeout(connect, delay);
      };
      ws.onerror = () => ws.close();
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      ws && ws.close();
    };
  }, []);

  // ---- 250 ms commit loop -------------------------------------------------
  useEffect(() => {
    const id = setInterval(() => {
      const { events, stats } = buf.current;
      buf.current = { events: [], stats: null };
      if (stats) setSummary(stats);
      if (!events.length) return;

      const now = Date.now();
      for (const e of events) {
        bump(seriesMap.current, minuteKey(e.occurred_at), e.type, 1);
        counts.current[e.type] = (counts.current[e.type] || 0) + 1;
        if (e.ingested_at) lat.current.push(Math.max(0, now - e.ingested_at));
      }
      if (lat.current.length > LAT_SAMPLES) lat.current = lat.current.slice(-LAT_SAMPLES);
      const sorted = [...lat.current].sort((a, b) => a - b);
      const q = (p) => sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * p))];
      setLatency({ p50: q(0.5), p95: q(0.95) });

      commitSeries();
      setBreakdown({ ...counts.current });
      setFeed((f) => [...events.slice(-FEED_MAX).reverse(), ...f].slice(0, FEED_MAX));
    }, 250);
    return () => clearInterval(id);
  }, []);

  return { status, summary, series, breakdown, feed, latency };
}
