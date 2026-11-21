"use strict";

const pages = [...document.querySelectorAll(".view-navigation button")];
const pagePanels = { history: byId("history-workspace"), explorer: byId("workspace"),
  profile: byId("profile-workspace"), planner: byId("planner-workspace") };
const dayText = (value) => value ? new Date(`${value}T12:00:00Z`).toLocaleDateString("en-CA", {
  month: "short", day: "numeric", year: "numeric", timeZone: "UTC",
}) : "—";
const activityLabel = (entry) => entry.date ? `${entry.name} · ${dayText(entry.date)}` : entry.name;
const sportText = (value) => value === "cycling" ? "Cycling" : "Running";
const compactTime = (seconds) => seconds == null ? "—" : seconds >= 3600
  ? `${Math.floor(Math.round(seconds / 60) / 60)} h ${Math.round(seconds / 60) % 60} min` : clock(seconds);
let agenda;
let currentId;
let renderRevision = 0;
let historySort = { key: "date", direction: -1 };
let historySport = "all";
const detailCache = new Map();
let peerObserver;

function pageTitle(name, description, label) {
  const intro = html("section", "intro portfolio-intro");
  const copy = html("div");
  if (label) copy.append(html("p", "section-label", label));
  copy.append(html("h1", null, name), html("p", null, description));
  intro.append(copy);
  return intro;
}

function semanticLabel(state, prefix = "") {
  const label = html("span", "semantic-label", `${prefix}${state.label}`);
  label.dataset.tone = state.tone;
  label.dataset.category = state.category;
  if (state.limitation) label.title = state.limitation;
  return label;
}

function takeawayCard(takeaway) {
  const card = html("section", "key-takeaway");
  card.append(html("h2", null, "Key takeaway"), html("p", null, takeaway.text));
  if (takeaway.states?.length) {
    const tags = html("div", "semantic-strip");
    const visible = takeaway.states.filter((state) => state.sufficiency !== "insufficient");
    if (visible.length < 3) {
      const missing = takeaway.states.find((state) => state.sufficiency === "insufficient" && state.metric === "workout");
      if (missing) visible.push(missing);
    }
    tags.append(...visible.slice(0, 3).map((state) => semanticLabel(state)));
    if (tags.childElementCount) card.append(tags);
  }
  if (takeaway.facts.length) {
    const evidence = html("details");
    const facts = html("dl");
    for (const [name, value] of takeaway.facts) facts.append(html("dt", null, name), html("dd", null, value));
    evidence.append(html("summary", null, "Show the evidence"), facts);
    card.append(evidence);
  }
  return card;
}

function navigatePage(page, id) {
  const next = `#${page}${id ? `/${encodeURIComponent(id)}` : ""}`;
  if (location.hash === next) renderPage();
  else location.hash = next;
}

function fetchDetail(id) {
  if (!detailCache.has(id)) {
    const request = fetch(`/api/activities/${encodeURIComponent(id)}`).then((response) => {
      if (!response.ok) throw new Error("Selected activity unavailable");
      return response.json();
    }).catch((error) => { detailCache.delete(id); throw error; });
    detailCache.set(id, request);
    if (detailCache.size > 6) detailCache.delete(detailCache.keys().next().value);
  }
  return detailCache.get(id);
}

function renderHistory() {
  const holder = pagePanels.history;
  const rows = agenda.history;
  const runs = rows.filter((r) => r.sport === "running");
  const rides = rows.length - runs.length;
  const comparable = runs.filter((r) => r.distance_m >= 5500 && r.distance_m <= 6500).length;
  const mixedReview = recordedReview && agenda.metadata.cycling_full_route === true;
  const intro = pageTitle("Activity History", recordedReview
    ? mixedReview ? "Running metrics describe protected route sections; the cycling ride is complete. Dates are withheld."
      : "Metrics describe retained route sections. Full-activity totals and dates are withheld."
    : "Browse recorded routes, compare running efforts and inspect ride conditions.",
    mixedReview ? "Private recorded review" : recordedReview ? "Recorded route privacy review"
      : privatePreview ? "Private local review" : "Fictional demonstration");
  const stats = html("div", "history-overview");
  for (const [label, figure] of [["Activities", rows.length],
    recordedReview ? ["Recorded runs", runs.length] : ["Runs near 6 km", comparable], ["Cycling rides", rides]]) {
    const card = html("div", "history-stat");
    card.append(html("span", null, label), html("strong", null, figure));
    stats.append(card);
  }
  const tableCard = comparisonCard("Activities", "Select an activity to open its route and sensor timeline.");
  const filters = html("div", "segmented small");
  filters.setAttribute("role", "group");
  filters.setAttribute("aria-label", "Filter activities by sport");
  for (const [key, label] of [["all", "All"], ["running", "Running"], ["cycling", "Cycling"]]) {
    const button = html("button", null, label);
    button.type = "button";
    button.setAttribute("aria-pressed", String(historySport === key));
    button.onclick = () => { historySport = key; renderHistory(); pagePanels.history.querySelector(`[aria-label="Filter activities by sport"] button:nth-child(${key === "all" ? 1 : key === "running" ? 2 : 3})`).focus(); };
    filters.append(button);
  }
  tableCard.querySelector(".panel-heading").append(filters);
  const columns = [
    [recordedReview ? "name" : "date", recordedReview ? "Activity" : "Activity / date"], ["sport", "Sport"],
    ["distance_m", recordedReview && !mixedReview ? "Visible distance" : "Distance"],
    ["speed_kmh", "Pace / speed"], ["duration_s", "Timer time"], ["heart_bpm", "Heart rate"], ["ascent_m", "Ascent"],
  ];
  const wrap = html("div", "history-table-wrap");
  const table = html("table", "history-table");
  const head = html("thead");
  const labels = html("tr");
  for (const [key, label] of columns) {
    const th = html("th");
    th.scope = "col";
    const sorted = historySort.key === key;
    if (sorted) th.setAttribute("aria-sort", historySort.direction === 1 ? "ascending" : "descending");
    const button = html("button", null, label);
    button.type = "button";
    button.dataset.sort = key;
    if (sorted) button.append(html("span", "sort-indicator", historySort.direction === 1 ? " ↑" : " ↓"));
    button.onclick = () => {
      historySort = { key, direction: sorted ? -historySort.direction : key === "sport" ? 1 : -1 };
      renderHistory();
      pagePanels.history.querySelector(`[data-sort="${key}"]`).focus();
    };
    th.append(button);
    labels.append(th);
  }
  head.append(labels);
  const body = html("tbody");
  const ordered = rows.filter((r) => historySport === "all" || historySport === r.sport).sort((a, b) => {
    const x = a[historySort.key], y = b[historySort.key];
    if (x == null || y == null) return Number(x == null) - Number(y == null);
    const cmp = typeof x === "string" ? x.localeCompare(y) : x - y;
    return cmp * historySort.direction || (b.date || "").localeCompare(a.date || "");
  });
  for (const record of ordered) {
    const tr = row(["", sportText(record.sport), reading(record.distance_m == null ? null : record.distance_m / 1000, "km", 2),
      record.sport === "cycling" ? reading(record.speed_kmh, "km/h") : pace(record.pace_s_per_km),
      compactTime(record.duration_s), reading(record.heart_bpm, "bpm", 0), reading(record.ascent_m, "m", 0)]);
    const link = html("a", "activity-link");
    link.href = `#explorer/${encodeURIComponent(record.id)}`;
    link.append(html("strong", null, record.name));
    if (record.date) link.append(html("span", null, dayText(record.date)));
    tr.firstChild.append(link);
    body.append(tr);
  }
  if (!ordered.length) tableCard.append(html("p", "comparison-copy", "No activities match this sport filter."));
  table.append(head, body);
  wrap.append(table);
  tableCard.append(wrap);
  if (privatePreview && agenda.cohort) {
    const { accepted, candidates } = agenda.cohort;
    tableCard.append(html("p", "comparison-copy", `${accepted} of ${candidates} staged candidates passed the cohort checks.`));
  }
  holder.replaceChildren(intro, stats, tableCard);
}

function weatherEvidence(detail) {
  const archive = detail.activity_weather;
  const demo = detail.fictional_conditions;
  const values = archive || demo;
  const card = comparisonCard("Environmental context", archive ? "Historical estimates for the full activity"
    : demo ? "Fictional weather scenario" : "Available measurements");
  const source = detail.weather_provenance;
  if (values) {
    const items = [["Air temperature", reading(values.air_temperature_c, "°C")],
      ["Wind speed", reading(values.wind_speed_mps, "m/s")], ["Wind from", windFrom(values.wind_from_deg)]];
    card.append(comparisonTable(["Variable", "Value"], items));
    const context = html("p", "comparison-copy");
    context.append(semanticLabel(detail.semantic.thermal));
    card.append(context);
    card.append(html("p", "comparison-copy", source
      ? `${source.provider} · ${source.product}. Reported field counts ${indexedWeatherCoverage(archive)}. Spatial and time-resolved conditions are unavailable for this archive summary.`
      : "Deterministic demonstration values."));
  } else {
    card.append(html("p", "comparison-copy", "Historical weather is unavailable for this activity."));
  }
  if (detail.device_temperature_c != null) card.append(html("p", "comparison-copy",
    `FIT device temperature ${reading(detail.device_temperature_c, "°C")} · ${covered(detail.device_temperature_coverage)} of timed GPS intervals. Body heat and exposure can affect wearable readings.`));
  if (detail.peer_weather?.air_temperature_c.count || detail.peer_weather?.wind_speed_mps.count) {
    const temperature = detail.peer_weather.air_temperature_c;
    const wind = detail.peer_weather.wind_speed_mps;
    const references = [
      temperature.count ? `air ${reading(temperature.median, "°C")} (${temperature.count} runs)` : null,
      wind.count ? `wind ${reading(wind.median, "m/s")} (${wind.count} runs)` : null,
    ].filter(Boolean);
    card.append(html("p", "comparison-copy", `Same-route whole-activity weather medians · ${references.join(" · ")}.`));
  }
  return card;
}

function peerEvidence(detail) {
  const { similar, same_route: sameRoute, profile } = detail.peer_context;
  const card = comparisonCard(recordedReview ? "Visible-section context" : "Running performance context",
    "The selected run is excluded from both historical references.");
  const labels = html("div", "semantic-strip peer-classifications");
  labels.append(semanticLabel(detail.semantic.similar_pace, "Similar distance · "),
    semanticLabel(detail.semantic.route_pace, "Same route · "));
  card.append(labels);
  const band = (stats) => stats.band ? `${clock(stats.band[0])}–${clock(stats.band[1])} /km` : "—";
  const percent = (stats) => stats.percentile == null ? "—" : covered(stats.percentile / 100);
  card.append(comparisonTable(["Reference", "Runs", "Median", "Middle 50%", "Peers slower¹"], [
    ["Similar distance", similar.count, pace(similar.median), band(similar), percent(similar)],
    ["Same-route subset", sameRoute.count, pace(sameRoute.median), band(sameRoute), percent(sameRoute)],
  ]));
  if (similar.percentile != null) card.append(html("p", "comparison-copy", "¹ Ties count half. The rank is shown from five peers."));
  const methods = html("details", "fit-checks");
  methods.append(html("summary", null, "Comparison methods"), html("p", null,
    recordedReview
      ? "Similar distances are compared within 500 m of the selected section length. Same-route peers need continuous same-direction overlap of at least 1 km and 60% of the shorter visible route. Pace uses retained timer-active intervals."
      : "Similar runs use the 5.5–6.5 km band for a 6 km selection and ±500 m for other selected runs. Same-route peers need at least 3 km of continuous same-direction overlap and 60% of the shorter GPS route. Whole-activity pace uses FIT timer time. Shared-ground chart bins use timer-active seconds over the selected route distance."));
  card.append(methods);
  return { card, profile };
}

function sameRouteChart(profile) {
  const card = comparisonCard("Same-route pace by distance",
    "Blue is the selected run. Teal shows the peer median and the middle 50% where four peers contribute.");
  const { bins, route_distance_m: distance } = profile;
  const graph = html("div", "plots peer-plots");
  const slider = html("input");
  Object.assign(slider, { id: "peer-distance", type: "range", min: 0, max: bins.length - 1, step: 1 });
  const label = html("label", null, "Matched distance");
  label.htmlFor = slider.id;
  const line = html("div", "timeline-label");
  const output = html("output");
  output.setAttribute("for", slider.id);
  line.append(label, output);
  const timeline = html("div", "timeline");
  timeline.append(line, slider);
  function select(index) {
    slider.value = index;
    const bin = bins[index];
    output.value = `${km(bin.distance_m)} · ${bin.count} historical ${bin.count === 1 ? "run" : "runs"}`;
    slider.setAttribute("aria-valuetext", `${output.value}, selected ${pace(bin.selected)}, median ${pace(bin.median)}`);
    plot.update(index);
  }
  const plot = comparisonChart({ title: "Pace · min/km", series: [
    { color: "#237cc0", get: (bin) => bin.selected }, { color: "#087b67", get: (bin) => bin.median },
  ], axis: clock, format: pace, minStep: 10, band: (bin) => bin.band }, bins, distance,
  (m) => distanceIndex(bins, m), select, card);
  graph.append(plot.container);
  card.append(graph, timeline);
  slider.addEventListener("input", () => select(slider.valueAsNumber));
  peerObserver = new ResizeObserver(() => {
    if (card.clientWidth) { plot.draw(); select(slider.valueAsNumber); }
  });
  peerObserver.observe(card);
  select(Math.floor(bins.length / 2));
  return card;
}

function renderRunComparison(detail, peers, evidence) {
  const fixed = detail.pair && { ...detail.pair, synthetic: !privatePreview };
  function show(pair) {
    const runs = pair?.run_ids.map((id) => agenda.history.find((run) => run.id === id));
    showComparison(pair, "running", runs);
  }
  show(fixed);
  if (!peers.length) return;

  const controls = html("div", "map-controls run-comparison-controls");
  const label = html("label", null, "Compare runs");
  const select = html("select");
  const status = html("span", "map-status");
  status.setAttribute("role", "status");
  const fixedPeer = fixed?.run_ids.find((id) => id !== detail.history.id);
  select.append(new Option(fixed ? "Original comparison" : "Choose a same-route run", ""));
  select.append(...peers.filter((peer) => peer.id !== fixedPeer).map((peer) =>
    new Option(activityLabel(peer), peer.id)));
  if (select.options.length === 1) return;
  label.append(select);
  controls.append(label, status);
  evidence.append(controls);

  const revision = renderRevision;
  let request = 0;
  select.addEventListener("change", async () => {
    const serial = ++request;
    const current = () => revision === renderRevision && serial === request;
    const peerId = select.value;
    status.textContent = peerId ? "Aligning shared route…" : "";
    if (!peerId) { show(fixed); return; }
    show(null);
    try {
      const response = await fetch(`/api/activities/${encodeURIComponent(detail.history.id)}/compare/${encodeURIComponent(peerId)}`);
      if (!response.ok) throw new Error("Comparison unavailable");
      const pair = await response.json();
      if (!current()) return;
      status.textContent = "";
      show(pair);
    } catch {
      if (current()) {
        status.textContent = "This comparison could not be loaded.";
        select.value = "";
        show(fixed);
      }
    }
  });
}

function renderExplorer(detail) {
  chooseActivity(detail.activity);
  const selected = detail.history;
  byId("dataset-intro").textContent = `${selected.name} · ${sportText(selected.sport)} · ${recordedReview
    ? (agenda.metadata.cycling_full_route && selected.sport === "cycling"
      ? "Complete recorded cycling activity. Private local review." : "Visible sections only. Full-activity metrics withheld.")
    : dayText(selected.date)}`;
  byId("activity-takeaway").replaceChildren(takeawayCard(detail.takeaway));
  peerObserver?.disconnect();
  const evidence = byId("explorer-context");
  evidence.replaceChildren();
  let historyPeers = [];
  const grid = html("div", "analysis-grid details-grid explorer-evidence");
  if (detail.peer_context) {
    grid.append(weatherEvidence(detail));
    const { card, profile } = peerEvidence(detail);
    grid.append(card);
    historyPeers = agenda.history.filter((r) => detail.peer_context.peer_ids.includes(r.id));
    evidence.append(grid);
    if (profile?.bins?.length) evidence.append(sameRouteChart(profile));
    renderRunComparison(detail, historyPeers, evidence);
  } else {
    showComparison({ synthetic: !privatePreview && !recordedReview, cycling: detail.cycling, provenance: detail.provenance,
      methods: detail.methods }, "cycling");
  }
  configureRouteMap(detail, agenda.map, historyPeers, fetchDetail);
}

async function renderPage() {
  if (!agenda) return;
  const serial = ++renderRevision;
  const [request, id] = location.hash.slice(1).split("/");
  const view = Object.hasOwn(pagePanels, request) ? request : "history";
  for (const button of pages) button.setAttribute("aria-pressed", String(button.dataset.view === view));
  for (const [key, panel] of Object.entries(pagePanels)) panel.hidden = key !== view || key === "explorer";
  document.body.dataset.view = view;
  byId("dataset-version").textContent = view === "profile" || view === "planner"
    ? "Fictional training history · 36 weeks"
    : `${recordedReview ? "Recorded route privacy review" : privatePreview
      ? "Private FIT preview" : "Fictional activity history"} · processing ${agenda.metadata.processing_version}`;
  byId("load-status").hidden = true;
  stopGeographicMap();
  if (view === "history") { renderHistory(); return; }
  if (view === "profile" || view === "planner") {
    renderAthletePage(view, pagePanels[view], id);
    return;
  }
  const found = id && agenda.history.find((r) => encodeURIComponent(r.id) === id);
  currentId = found?.id || currentId;
  const pending = byId("load-status");
  pending.textContent = "Loading activity analysis…";
  pending.hidden = false;
  try {
    const detail = await fetchDetail(currentId);
    if (serial !== renderRevision) return;
    pagePanels.explorer.hidden = false;
    renderExplorer(detail);
    pending.hidden = true;
  } catch (error) {
    if (serial !== renderRevision) return;
    pending.textContent = "This activity could not be loaded.";
    console.error(error);
  }
}

for (const button of pages) button.onclick = () => navigatePage(button.dataset.view);
controls.activities.onchange = () => navigatePage("explorer", controls.activities.value);
window.addEventListener("hashchange", renderPage);
fetch("/api/portfolio").then((response) => {
  if (!response.ok) throw new Error("Portfolio unavailable");
  return response.json();
}).then((data) => {
  agenda = data;
  setupExplorer(data.metadata);
  if (recordedReview) historySort = { key: "name", direction: 1 };
  const ordered = data.history.slice().sort((a, b) => (b.date || "").localeCompare(a.date || ""));
  currentId = ordered[0].id;
  controls.activities.append(...ordered.map((entry) => new Option(activityLabel(entry), entry.id)));
  renderPage();
}).catch((error) => {
  byId("load-status").hidden = false;
  byId("load-status").textContent = "The local portfolio could not be loaded.";
  console.error(error);
});
