/*!
 * rta.js — tiny, privacy-friendly tracker for the Real-Time Analytics Dashboard.
 *
 * Add one line before </body> on the site:
 *   <script defer src="https://YOUR-DASHBOARD-HOST/rta.js"
 *           data-endpoint="https://YOUR-DASHBOARD-HOST/api/collect"></script>
 *
 * Sends:  page_view   on load and on SPA route changes
 *         link_click  on clicks to GitHub / LinkedIn / resume / email / projects / external
 *         engaged     once per page after 30s of the tab being visible
 * Each event carries ref_source (linkedin, github, google, ... or direct), resolved once
 * per session, so you can see e.g. how many visitors a LinkedIn post brings and what
 * they click next.
 *
 * Privacy: no cookies, no IP stored, no fingerprinting. A random visitor id lives in
 * localStorage. Do Not Track / Global Privacy Control are honoured.
 */
(function () {
  "use strict";
  var script = document.currentScript;
  var ENDPOINT = (script && script.getAttribute("data-endpoint")) || "/api/collect";
  var ENGAGED_MS = 30000;

  if (navigator.doNotTrack === "1" || window.doNotTrack === "1" || navigator.globalPrivacyControl ||
      navigator.webdriver) return;

  function rid() {
    return Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
  }
  function store(kind, key, make) {
    try {
      var s = window[kind], v = s.getItem(key);
      if (!v) { v = make(); s.setItem(key, v); }
      return v;
    } catch (e) { return make(); }        // storage blocked -> per-page id
  }

  var visitor = store("localStorage", "rta_vid", function () { return "v_" + rid(); });

  // Where did this session come from? Resolved on the first page, kept for the session.
  var refSource = store("sessionStorage", "rta_ref", function () {
    var q = new URLSearchParams(location.search);
    var utm = (q.get("utm_source") || q.get("ref") || "").toLowerCase();
    if (utm) return utm.slice(0, 40);
    var host = "";
    try { host = new URL(document.referrer).hostname.replace(/^www\./, ""); } catch (e) {}
    if (!host || host === location.hostname) return "direct";
    var known = [
      [/(^|\.)linkedin\.com$|^lnkd\.in$/, "linkedin"],
      [/(^|\.)github\.com$/, "github"],
      [/(^|\.)google\./, "google"],
      [/(^|\.)bing\.com$|duckduckgo\.com$/, "search"],
      [/^(t\.co|x\.com|twitter\.com)$/, "x"],
      [/(^|\.)handshake|joinhandshake\.com$/, "handshake"],
    ];
    for (var i = 0; i < known.length; i++) if (known[i][0].test(host)) return known[i][1];
    return host.slice(0, 40);
  });

  var queue = [], timer = null;
  function send(type, props) {
    queue.push({
      type: type,
      user_id: visitor,
      ts: Date.now(),
      props: Object.assign({ path: location.pathname, ref_source: refSource }, props || {}),
    });
    if (!timer) timer = setTimeout(flush, 1000);   // coalesce bursts into one beacon
  }
  function flush() {
    timer = null;
    if (!queue.length) return;
    var body = JSON.stringify({ events: queue.splice(0, 20) });
    // text/plain = "simple" CORS request: no preflight round trip
    var ok = navigator.sendBeacon && navigator.sendBeacon(ENDPOINT, new Blob([body], { type: "text/plain" }));
    if (!ok) {
      fetch(ENDPOINT, { method: "POST", body: body, keepalive: true, mode: "cors",
                        headers: { "Content-Type": "text/plain" } }).catch(function () {});
    }
    if (queue.length) timer = setTimeout(flush, 200);
  }

  // ---- page views (incl. SPA navigation) -------------------------------------
  var lastPath = null, engagedTimer = null, visibleSince = 0, visibleMs = 0;
  function pageView() {
    if (location.pathname === lastPath) return;
    lastPath = location.pathname;
    send("page_view", { title: document.title.slice(0, 120) });
    visibleMs = 0;
    visibleSince = document.visibilityState === "visible" ? Date.now() : 0;
    armEngaged();
  }
  function armEngaged() {
    clearTimeout(engagedTimer);
    if (!visibleSince) return;
    engagedTimer = setTimeout(function () { send("engaged", { seconds: 30 }); },
                              Math.max(0, ENGAGED_MS - visibleMs));
  }
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") {
      if (visibleSince) visibleMs += Date.now() - visibleSince;
      visibleSince = 0;
      clearTimeout(engagedTimer);
      flush();                                   // last chance before the tab goes away
    } else {
      visibleSince = Date.now();
      if (visibleMs < ENGAGED_MS) armEngaged();
    }
  });
  ["pushState", "replaceState"].forEach(function (fn) {
    var orig = history[fn];
    history[fn] = function () { var r = orig.apply(this, arguments); setTimeout(pageView, 0); return r; };
  });
  window.addEventListener("popstate", pageView);

  // ---- outbound / key link clicks ----------------------------------------------
  function classify(a) {
    var href = a.getAttribute("href") || "";
    if (/^mailto:/i.test(href)) return "email";
    var u;
    try { u = new URL(href, location.href); } catch (e) { return null; }
    var h = u.hostname.replace(/^www\./, "");
    if (/resume|cv/i.test(u.pathname) || /\.pdf$/i.test(u.pathname)) return "resume";
    if (/(^|\.)github\.com$/.test(h)) return "github";
    if (/(^|\.)linkedin\.com$/.test(h)) return "linkedin";
    if (h === location.hostname) return /project/i.test(u.pathname) ? "project" : null;
    return "external";
  }
  document.addEventListener("click", function (e) {
    var a = e.target && e.target.closest && e.target.closest("a[href]");
    if (!a) return;
    var target = classify(a);
    if (!target) return;
    send("link_click", {
      target: target,
      href: (a.href || "").slice(0, 200),
      text: (a.textContent || "").trim().slice(0, 60),
    });
    flush();                                     // navigation may unload the page
  }, true);

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", pageView);
  else pageView();
})();
