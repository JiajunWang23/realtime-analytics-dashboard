// Per-stream presentation config. Color follows the entity (event type) via a fixed slot,
// never its rank, so a type keeps its color as counts reorder.
export const SOURCES = {
  site: {
    label: "My Website",
    subtitle: "uiucwangjiajun.com · first-party tracker",
    typeSlots: { page_view: 1, link_click: 2, engaged: 3 },
    kpis: {
      today: "Page events today",
      lastMin: "Events last minute",
      active: "Visitors now",
      activeHint: "unique, last 5 min",
      uniqueToday: "Unique visitors today",
    },
    shareKpi: { dim: "ref_source", value: "linkedin", label: "From LinkedIn", hint: "share of events, last 60 min" },
    dims: [
      { key: "ref_source", title: "Where visitors come from" },
      { key: "target", title: "What they click" },
      { key: "path", title: "Top pages" },
    ],
    feedRow: (e) => ({
      main: e.type === "link_click" ? `clicked ${e.props?.target}` : e.type.replace("_", " "),
      secondary: e.props?.path || "",
      tertiary: `via ${e.props?.ref_source || "direct"}`,
    }),
    empty: "No visitors yet. Add the tracker snippet to your site to see live traffic here.",
  },
  wikipedia: {
    label: "Wikipedia Live",
    subtitle: "All Wikimedia projects · EventStreams recentchange",
    typeSlots: { edit: 1, categorize: 2, new: 3, log: 4 },
    kpis: {
      today: "Changes today",
      lastMin: "Changes last minute",
      active: "Active editors",
      activeHint: "unique, last 5 min",
      uniqueToday: "Unique editors today",
    },
    shareKpi: { dim: "bot", value: "bot", label: "Made by bots", hint: "share of changes, last 60 min" },
    dims: [
      { key: "wiki", title: "Most active wikis" },
      { key: "bot", title: "Bots vs humans" },
    ],
    feedRow: (e) => ({
      main: e.props?.title || "(untitled)",
      href: e.props?.url,
      secondary: e.props?.wiki || "",
      tertiary: `${e.type}${e.props?.bot === "bot" ? " · bot" : ""}`,
    }),
    empty: "Waiting for the Wikipedia connector…",
  },
  demo: {
    label: "Simulator",
    subtitle: "synthetic e-commerce traffic for load tests",
    typeSlots: { page_view: 1, click: 2, add_to_cart: 3, purchase: 4, signup: 5, bench: 7, error: 8 },
    kpis: {
      today: "Events today",
      lastMin: "Events last minute",
      active: "Active users",
      activeHint: "unique, last 5 min",
      uniqueToday: "Unique users today",
    },
    shareKpi: null,
    dims: [{ key: "path", title: "Top pages" }],
    feedRow: (e) => ({ main: e.type, secondary: e.user_id, tertiary: e.props?.page || "" }),
    empty: "Run scripts/simulate.py to generate traffic.",
  },
};

export const DIM_KEYS = [...new Set(Object.values(SOURCES).flatMap((s) => s.dims.map((d) => d.key)
  .concat(s.shareKpi ? [s.shareKpi.dim] : [])))];

export const colorOf = (source, type) => {
  const slot = SOURCES[source]?.typeSlots[type];
  return slot ? `var(--series-${slot})` : "var(--series-other)";
};
