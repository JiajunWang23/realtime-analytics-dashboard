// Per-stream presentation config. Color follows the entity (event type) via a fixed slot,
// never its rank, so a type keeps its color as counts reorder.

// ---- human-readable names --------------------------------------------------------
const PROJECTS = [
  ["wiktionary", "Wiktionary"], ["wikisource", "Wikisource"], ["wikiquote", "Wikiquote"],
  ["wikibooks", "Wikibooks"], ["wikinews", "Wikinews"], ["wikivoyage", "Wikivoyage"],
  ["wikiversity", "Wikiversity"], ["wiki", "Wikipedia"],
];
const SPECIAL_WIKIS = {
  commonswiki: "Wikimedia Commons (media)", wikidatawiki: "Wikidata (structured data)",
  metawiki: "Meta-Wiki", specieswiki: "Wikispecies", mediawikiwiki: "MediaWiki.org",
  wikifunctionswiki: "Wikifunctions", incubatorwiki: "Wikimedia Incubator",
};
let langNames = null;
try { langNames = new Intl.DisplayNames(["en"], { type: "language" }); } catch { /* old browser */ }

/** "enwiktionary" -> "English Wiktionary", "zhwikisource" -> "Chinese Wikisource". */
export function wikiName(code) {
  if (!code) return "";
  if (SPECIAL_WIKIS[code]) return SPECIAL_WIKIS[code];
  for (const [suffix, project] of PROJECTS) {
    if (code.endsWith(suffix) && code.length > suffix.length) {
      const lang = code.slice(0, -suffix.length).replace(/_/g, "-");
      let name = lang;
      try { name = langNames?.of(lang) || lang; } catch { /* unknown code */ }
      return name === lang ? `${project} (${lang})` : `${name} ${project}`;
    }
  }
  return code;
}

const REFERRERS = {
  linkedin: "LinkedIn", github: "GitHub", google: "Google search", search: "Other search engines",
  x: "X / Twitter", handshake: "Handshake", direct: "Direct / bookmark",
};
const TARGETS = {
  github: "GitHub profile", linkedin: "LinkedIn profile", resume: "Résumé", email: "Email me",
  project: "A project page", external: "Other external link",
};

export const SOURCES = {
  wikipedia: {
    label: "Wikipedia, live",
    headline: "Every change being made to Wikipedia right now",
    blurb:
      "Wikipedia and its sister sites (Wiktionary, Wikidata, Commons, …) publish a public live feed " +
      "of every edit, new page, and category update, from anyone, in any language, about 30 per second. " +
      "This dashboard streams that feed in, stores and aggregates it, and shows what is happening at this moment.",
    note: "Data is pulled while someone has this page open, so quiet stretches on the chart are times nobody was watching.",
    typeSlots: { edit: 1, categorize: 2, new: 3, log: 4 },
    typeLabels: {
      edit: "Edits to existing pages", categorize: "Category updates", new: "New pages created",
      log: "Uploads, moves & admin actions",
    },
    kpis: {
      today: { label: "Changes today", hint: (s) => `${fmtN(s?.events_last_minute)} in the last minute` },
      active: { label: "People & bots editing now", hint: () => "distinct accounts, last 5 minutes" },
      uniqueToday: { label: "Distinct editors today", hint: () => "estimated with HyperLogLog" },
    },
    shareKpi: { dim: "bot", value: "bot", label: "Changes made by bots",
                hint: "automated accounts, last 60 min" },
    chartTitle: "Changes per minute",
    dims: [
      { key: "wiki", title: "Which sites are busiest", format: wikiName },
      { key: "bot", title: "Who is making the changes",
        format: (v) => (v === "bot" ? "Bots (automated accounts)" : "Humans") },
    ],
    feedTitle: "Latest changes (click a title to open the page)",
    feedRow: (e, cfg) => ({
      main: e.props?.title || "(untitled)",
      href: e.props?.url,
      secondary: wikiName(e.props?.wiki),
      tertiary: `${cfg.typeShort[e.type] || e.type}${e.props?.bot === "bot" ? " · bot" : ""}`,
    }),
    typeShort: { edit: "Edit", categorize: "Category", new: "New page", log: "Log action" },
    empty: "Connecting to the Wikipedia feed… the first changes usually appear within a few seconds.",
  },
  site: {
    label: "My portfolio site",
    headline: "Who is visiting uiucwangjiajun.com, and what they do",
    blurb:
      "A small tracking script on my personal website reports page views, which links visitors click " +
      "(GitHub, résumé, LinkedIn…), and where they came from, e.g. a LinkedIn post. It's the same " +
      "pipeline as the Wikipedia tab, fed by real visitors instead of a public feed.",
    note: "Privacy: no cookies, no IP addresses stored, Do Not Track respected, bots filtered out.",
    typeSlots: { page_view: 1, link_click: 2, engaged: 3 },
    typeLabels: {
      page_view: "Page views", link_click: "Link clicks", engaged: "Stayed 30s+ on a page",
    },
    kpis: {
      today: { label: "Interactions today", hint: (s) => `${fmtN(s?.events_last_minute)} in the last minute` },
      active: { label: "Visitors right now", hint: () => "distinct visitors, last 5 minutes" },
      uniqueToday: { label: "Visitors today", hint: () => "distinct visitors (estimated)" },
    },
    shareKpi: { dim: "ref_source", value: "linkedin", label: "Came from LinkedIn",
                hint: "share of activity, last 60 min" },
    chartTitle: "Interactions per minute",
    dims: [
      { key: "ref_source", title: "Where visitors come from", format: (v) => REFERRERS[v] || v },
      { key: "target", title: "What they click", format: (v) => TARGETS[v] || v },
      { key: "path", title: "Most viewed pages", format: (v) => (v === "/" ? "Home page" : v) },
    ],
    feedTitle: "Latest visitor activity",
    feedRow: (e) => ({
      main: e.type === "link_click" ? `Clicked: ${TARGETS[e.props?.target] || e.props?.target}`
        : e.type === "engaged" ? "Read for 30s+" : "Viewed a page",
      secondary: e.props?.path === "/" ? "Home page" : e.props?.path || "",
      tertiary: `from ${REFERRERS[e.props?.ref_source] || e.props?.ref_source || "direct"}`,
    }),
    empty: "No visitors yet today. Visit uiucwangjiajun.com in another tab and watch yourself appear here.",
  },
  demo: {
    label: "Load test",
    hidden: true, // only reachable via #demo: synthetic traffic used for benchmarks
    headline: "Synthetic traffic used for load testing",
    blurb: "Simulated e-commerce events from scripts/simulate.py, used to benchmark throughput and latency.",
    typeSlots: { page_view: 1, click: 2, add_to_cart: 3, purchase: 4, signup: 5, bench: 7, error: 8 },
    typeLabels: {},
    kpis: {
      today: { label: "Events today", hint: (s) => `${fmtN(s?.events_last_minute)} in the last minute` },
      active: { label: "Active users", hint: () => "last 5 minutes" },
      uniqueToday: { label: "Unique users today", hint: () => "HyperLogLog estimate" },
    },
    shareKpi: null,
    chartTitle: "Events per minute",
    dims: [{ key: "path", title: "Top pages" }],
    feedTitle: "Latest events",
    feedRow: (e) => ({ main: e.type, secondary: e.user_id, tertiary: e.props?.path || "" }),
    empty: "Run scripts/simulate.py to generate traffic.",
  },
};

function fmtN(n) {
  return n == null ? "—" : Intl.NumberFormat("en-US").format(n);
}

export const colorOf = (source, type) => {
  const slot = SOURCES[source]?.typeSlots[type];
  return slot ? `var(--series-${slot})` : "var(--series-other)";
};
