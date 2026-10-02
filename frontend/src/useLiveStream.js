import { useEffect, useRef, useState } from "react";
import { SOURCES } from "./sources";

const WINDOW_MIN = 60;
const FEED_MAX = 80;
const LAT_SAMPLES = 500;
const RESEED_MS = 60_000; // re-sync windowed aggregates so the 60-min window slides correctly
const API = import.meta.env.VITE_API_URL || "";

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

// Subscribe to one stream only: the server fans out just that source's events to us.
function wsUrl(source) {
  const env = import.meta.env.VITE_WS_URL;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const base = env || `${proto}://${location.host}/ws`;
  return `${base}?source=${encodeURIComponent(source)}`;
}

const getJSON = (path) =>
  fetch(`${API}${path}`).then((r) => {
    if (!r.ok) throw new Error(`${r.status} ${path}`);
    return r.json();
  });

// Ask the server which realtime transport it supports (WebSocket, or polling on serverless).
let transportPromise = null;
export const transport = () =>
  (transportPromise ||= getJSON("/api/config").catch(() => ({ realtime: "ws", wiki_pull: false })));

const dimKeysFor = (s) => {
  const cfg = SOURCES[s];
  return [...new Set(cfg.dims.map((d) => d.key).concat(cfg.shareKpi ? [cfg.shareKpi.dim] : []))];
};

/**
 * One WebSocket per selected source (re-opened on tab switch); state is kept for that source only.
 * Incoming frames are buffered in refs and committed to React state every 250 ms,
 * so a burst of thousands of events costs four renders per second, not thousands.
 */
export function useLiveStream(source) {
  const [status, setStatus] = useState("connecting");
  const [summaries, setSummaries] = useState(null);
  const [series, setSeries] = useState([]);       // [{t, total, byType}]
  const [breakdown, setBreakdown] = useState({}); // type -> count (last 60 min)
  const [dims, setDims] = useState({});           // key -> {value: count}
  const [feed, setFeed] = useState([]);
  const [latency, setLatency] = useState({ p50: null, p95: null });

  const sourceRef = useRef(source);
  const buf = useRef({ events: [], stats: null });
  const seriesMap = useRef(new Map());
  const counts = useRef({});
  const dimCounts = useRef({});
  const lat = useRef([]);

  function commitSeries() {
    // Only completed minutes are plotted: the in-progress minute would read as a sudden drop.
    const current = Math.floor(Date.now() / 60_000) * 60_000;
    const start = current - WINDOW_MIN * 60_000;
    const out = [];
    // fill gaps so quiet minutes render as zero rather than an interpolated line
    for (let t = start; t < current; t += 60_000) {
      out.push(seriesMap.current.get(t) || { t, total: 0, byType: {} });
    }
    for (const k of seriesMap.current.keys()) if (k < start) seriesMap.current.delete(k);
    setSeries(out);
  }

  // ---- (re)seed from REST whenever the source changes, and every minute -------
  useEffect(() => {
    sourceRef.current = source;
    let cancelled = false;
    seriesMap.current = new Map();
    counts.current = {};
    dimCounts.current = {};
    lat.current = [];
    buf.current.events = [];
    setFeed([]);
    setSeries([]);
    setBreakdown({});
    setDims({});
    setLatency({ p50: null, p95: null });

    const seedAggregates = () => {
      const keys = dimKeysFor(source);
      return Promise.all([
        getJSON(`/api/stats/breakdown?source=${source}&minutes=${WINDOW_MIN}`),
        ...keys.map((k) => getJSON(`/api/stats/dims?source=${source}&key=${k}&minutes=${WINDOW_MIN}&limit=50`)),
      ]).then(([bd, ...dimRows]) => {
        if (cancelled) return;
        counts.current = Object.fromEntries(bd.map((r) => [r.event_type, Number(r.count)]));
        dimCounts.current = Object.fromEntries(
          keys.map((k, i) => [k, Object.fromEntries(dimRows[i].map((r) => [r.value, r.count]))]),
        );
        setBreakdown({ ...counts.current });
        setDims(structuredClone(dimCounts.current));
      });
    };

    Promise.all([
      getJSON(`/api/stats/timeseries?source=${source}&minutes=${WINDOW_MIN}`),
      getJSON(`/api/events/recent?source=${source}&limit=${FEED_MAX}`),
      getJSON(`/api/stats/summary`),
      seedAggregates(),
    ])
      .then(([ts, recent, sum]) => {
        if (cancelled) return;
        for (const row of ts) bump(seriesMap.current, minuteKey(row.bucket), row.type, row.count);
        setFeed(recent);
        setSummaries(sum);
        commitSeries();
      })
      .catch(() => {});

    const id = setInterval(() => seedAggregates().catch(() => {}), RESEED_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [source]);

  // ---- realtime transport: WebSocket, or HTTP polling where WS isn't available ----
  useEffect(() => {
    let ws;
    let retry = 0;
    let timer;
    let closed = false;
    const onEvents = (events) => {
      const s = sourceRef.current;
      const now = Date.now(); // measure on arrival, not at the next 250 ms commit
      for (const e of events) {
        if (e.source !== s) continue;
        buf.current.events.push(e);
        if (e.ingested_at) lat.current.push(Math.max(0, now - e.ingested_at));
      }
    };

    const connectWs = () => {
      setStatus(retry ? "reconnecting" : "connecting");
      ws = new WebSocket(wsUrl(source));
      ws.onopen = () => {
        retry = 0;
        setStatus("live");
      };
      ws.onmessage = (m) => {
        const msg = JSON.parse(m.data);
        if (msg.kind === "events") onEvents(msg.events);
        else if (msg.kind === "stats" || msg.kind === "hello") buf.current.stats = msg;
      };
      ws.onclose = () => {
        if (closed) return;
        setStatus("reconnecting");
        const delay = Math.min(30_000, 500 * 2 ** retry++) * (0.5 + Math.random());
        timer = setTimeout(connectWs, delay);
      };
      ws.onerror = () => ws.close();
    };

    // Polling: new events every 1 s via a cursor, KPIs every 3 s. On serverless deploys the
    // Wikipedia stream is also pulled on demand while someone is watching (server-side lock
    // makes concurrent viewers share one pull).
    const startPolling = (cfg) => {
      let cursor = null;
      let ticks = 0;
      const pullWiki = () => {
        if (source === "wikipedia" && cfg.wiki_pull)
          fetch(`${API}/api/ingest/wikipedia?seconds=25`, { method: "POST" }).catch(() => {});
      };
      pullWiki();
      const wikiTimer = setInterval(pullWiki, 20_000);
      const poll = async () => {
        if (closed) return;
        try {
          const q = cursor == null ? "" : `&after=${cursor}`;
          const res = await getJSON(`/api/live?source=${source}${q}`);
          if (cursor != null) onEvents(res.events);
          cursor = res.cursor;
          if (ticks++ % 3 === 0) buf.current.stats = await getJSON(`/api/stats/summary`);
          setStatus("live");
          timer = setTimeout(poll, 1000);
        } catch {
          setStatus("reconnecting");
          timer = setTimeout(poll, Math.min(30_000, 1000 * 2 ** Math.min(retry++, 5)));
        }
      };
      poll();
      return () => clearInterval(wikiTimer);
    };

    let stopPolling = null;
    transport().then((cfg) => {
      if (closed) return;
      if (cfg.realtime === "poll") stopPolling = startPolling(cfg);
      else connectWs();
    });
    return () => {
      closed = true;
      clearTimeout(timer);
      stopPolling && stopPolling();
      ws && ws.close();
    };
  }, [source]);

  // ---- 250 ms commit loop -------------------------------------------------------
  useEffect(() => {
    const id = setInterval(() => {
      const { events, stats } = buf.current;
      buf.current = { events: [], stats: null };
      if (stats) setSummaries(stats);
      const s = sourceRef.current;
      const mine = events.filter((e) => e.source === s); // drop frames from before a tab switch
      if (!mine.length) return;

      const keys = dimKeysFor(s);
      for (const e of mine) {
        bump(seriesMap.current, minuteKey(e.occurred_at), e.type, 1);
        counts.current[e.type] = (counts.current[e.type] || 0) + 1;
        for (const k of keys) {
          const v = e.props?.[k];
          if (v == null || v === "") continue;
          const d = (dimCounts.current[k] ||= {});
          d[v] = (d[v] || 0) + 1;
        }
      }
      if (lat.current.length > LAT_SAMPLES) lat.current = lat.current.slice(-LAT_SAMPLES);
      const sorted = [...lat.current].sort((a, b) => a - b);
      const q = (p) => sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * p))];
      setLatency({ p50: q(0.5), p95: q(0.95) });

      commitSeries();
      setBreakdown({ ...counts.current });
      setDims(structuredClone(dimCounts.current));
      setFeed((f) => [...mine.slice(-FEED_MAX).reverse(), ...f].slice(0, FEED_MAX));
    }, 250);
    return () => clearInterval(id);
  }, []);

  const summary = summaries?.sources?.[source] || null;
  return { status, summary, wsClients: summaries?.ws_clients, series, breakdown, dims, feed, latency };
}
