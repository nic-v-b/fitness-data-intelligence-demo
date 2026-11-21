"use strict";

const athleteRequests = new Map();
let athleteScenario = "typical";
let athleteRevision = 0;
let volumePeriod = "weekly";
let planChoice = 0;
let healthTrendChoice = "hrv";

function athleteData(scenario) {
  if (!athleteRequests.has(scenario)) {
    const path = scenario === "typical" ? "/api/athlete" : "/api/athlete/compressed";
    athleteRequests.set(scenario, fetch(path).then((response) => {
      if (!response.ok) throw new Error("Athlete fixture unavailable");
      return response.json();
    }).catch((error) => { athleteRequests.delete(scenario); throw error; }));
  }
  return athleteRequests.get(scenario);
}

const sleepDisplay = (minutes) => `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")} min`;
const unitCount = (count) => count.toLocaleString("en-CA");

function scenarioPicker(intro, data, view, holder) {
  const control = html("label", "scenario-picker", "Fictional scenario");
  const select = html("select");
  select.append(...Object.entries(data.scenarios).map(([key, name]) => new Option(name, key, false, data.scenario === key)));
  select.onchange = () => { athleteScenario = select.value; renderAthletePage(view, holder, null, true); };
  control.append(select);
  intro.append(control);
}

function metricTiles(metrics) {
  const tiles = html("div", "history-overview athlete-tiles");
  for (const [title, value, detail] of metrics) {
    const tile = html("div", "history-stat");
    tile.append(html("span", null, title), html("strong", null, value), html("small", null, detail));
    tiles.append(tile);
  }
  return tiles;
}

const monthText = (value) => new Date(`${value.slice(0, 7)}-15T12:00:00Z`).toLocaleDateString("en-CA", {
  month: "short", timeZone: "UTC",
});

function trainingVolume(profile) {
  const card = comparisonCard("Training volume", "Select a period to inspect distance by sport.");
  card.id = "training-volume";
  const toggle = html("div", "segmented small");
  toggle.setAttribute("role", "group");
  toggle.setAttribute("aria-label", "Volume period");
  const output = html("p", "athlete-chart-readout");
  output.setAttribute("aria-live", "polite");
  const plot = html("div", "volume-plot");
  const monthlyNote = html("span", null, "September is a partial month.");
  const keys = [["weekly", "Weekly"], ["monthly", "Monthly"]];
  const buttons = keys.map(([value, text]) => {
    const button = html("button", null, text);
    button.type = "button";
    button.onclick = () => { volumePeriod = value; draw(); };
    toggle.append(button);
    return button;
  });
  function draw() {
    const data = volumePeriod === "weekly" ? profile.weekly.slice(-8) : profile.monthly;
    const max = Math.max(...data.map((p) => p.totals.running.distance_m + p.totals.cycling.distance_m));
    const bins = data.map(({ period, totals }) => {
      const dateLabel = volumePeriod === "weekly" ? dayText(period).split(",")[0] : monthText(period);
      const bar = html("button", "volume-column");
      bar.type = "button";
      const stack = html("span", "volume-stack");
      for (const sport of ["cycling", "running"]) {
        const part = html("i", `volume-${sport}`);
        part.style.height = `${totals[sport].distance_m / max * 100}%`;
        stack.append(part);
      }
      const label = html("span", "volume-date", dateLabel);
      const text = `${dateLabel} · Running ${km(totals.running.distance_m)} · Cycling ${km(totals.cycling.distance_m)}`;
      bar.setAttribute("aria-label", text);
      bar.append(stack, label);
      bar.onclick = () => {
        plot.querySelector('[aria-pressed="true"]')?.setAttribute("aria-pressed", "false");
        bar.setAttribute("aria-pressed", "true");
        output.textContent = text;
      };
      bar.setAttribute("aria-pressed", "false");
      return bar;
    });
    plot.replaceChildren(...bins);
    buttons.forEach((button, i) => button.setAttribute("aria-pressed", String(keys[i][0] === volumePeriod)));
    monthlyNote.hidden = volumePeriod !== "monthly";
    bins.at(-1).onclick();
  }
  const legend = html("div", "map-legend athlete-legend");
  legend.append(html("span", "key-blue", "■ Running"), html("span", "key-teal", "▧ Cycling"),
    monthlyNote);
  card.querySelector(".panel-heading").append(toggle);
  card.append(plot, legend, output);
  draw();
  return card;
}

function benchmarkChart(profile) {
  const points = profile.benchmarks;
  const first = points[0], latest = points.at(-1);
  const card = comparisonCard("5 km benchmark trend", "Completed benchmark sessions at the same distance.");
  card.id = "running-benchmarks";
  const graph = svg("svg", { viewBox: "0 0 470 160", role: "img", class: "benchmark-chart",
    "aria-label": points.map((point) => `${dayText(point.date)} ${clock(point.duration_s)}`).join(", ") });
  const low = Math.floor(Math.min(...points.map((p) => p.duration_s)) / 30) * 30;
  const high = Math.ceil(Math.max(...points.map((p) => p.duration_s)) / 30) * 30;
  const start = Date.parse(first.date), finish = Date.parse(latest.date);
  const x = (day) => 53 + (Date.parse(day) - start) / (finish - start) * 368;
  const y = (seconds) => 17 + (high - seconds) / (high - low) * 111;
  for (let tick = low; tick <= high; tick += 60) {
    graph.append(svg("line", { x1: 53, x2: 429, y1: y(tick), y2: y(tick), stroke: "var(--separator)" }),
      svg("text", { x: 44, y: y(tick) + 4, "text-anchor": "end" }, clock(tick)));
  }
  graph.append(svg("polyline", { points: points.map((p) => [x(p.date), y(p.duration_s)].join(",")).join(" "),
    fill: "none", stroke: "var(--elevation)", "stroke-width": 2.7, "stroke-linejoin": "round" }));
  for (const point of points) {
    const mark = svg("circle", { cx: x(point.date), cy: y(point.duration_s), r: 4, fill: "var(--elevation)" });
    mark.append(svg("title", {}, `${dayText(point.date)} · ${clock(point.duration_s)}`));
    graph.append(mark);
  }
  graph.append(svg("text", { x: 53, y: 150 }, monthText(first.date)),
    svg("text", { x: 421, y: 150, "text-anchor": "end" }, monthText(latest.date)));
  const delta = first.duration_s - latest.duration_s;
  card.append(graph, html("p", "inline-takeaway", `${clock(latest.duration_s)} latest · ${clock(delta)} faster than the first benchmark.`));
  return card;
}

function healthStatus(health) {
  const { latest, recent, vo2max } = health;
  const semantic = health.semantic;
  const card = comparisonCard("Health and training indicators", `Fictional morning snapshot · ${dayText(latest.date)}`);
  card.id = "athlete-health";
  const values = [
    ["HRV · 7-day median", `${number(recent.hrv_ms, 1)} ms`, `${number(recent.baseline_hrv_ms, 1)} ms personal baseline`, semantic.hrv],
    ["Resting heart rate · 7-day median", `${number(recent.resting_bpm, 1)} bpm`, `${number(recent.baseline_resting_bpm, 1)} bpm baseline`, semantic.resting_hr],
    ["Estimated VO₂max", `${number(vo2max.at(-1).estimate, 1)} mL/kg/min`, "5 km performance estimate", semantic.vo2max],
    ["Sleep · 7-day average", sleepDisplay(recent.sleep_min), `${number(recent.sleep_quality, 1)}/5 average quality`, semantic.sleep],
    ["Training load · 7 days", `${unitCount(recent.load_7)} units`, `${number(semantic.load.value, 2)}× · ${unitCount(recent.prior_weekly_load)} units per prior week`, semantic.load],
    ["Illustrative readiness", `${latest.readiness}/100`, "HRV, resting HR, sleep and load composite", semantic.readiness],
  ];
  const grid = html("dl", "health-readings");
  for (const [label, value, context, classification] of values) {
    const item = html("div");
    const cell = html("dd");
    cell.append(html("strong", null, value), html("small", null, context));
    cell.append(semanticLabel(classification));
    item.append(html("dt", null, label), cell);
    grid.append(item);
  }
  const methods = html("details", "evidence-details health-methods");
  methods.append(html("summary", null, "Sources and calculations"),
    html("p", null, "HRV, resting heart rate, sleep and sleep quality are simulated daily observations. VO₂max is estimated from fictional 5 km performance. Load is session minutes multiplied by a fictional effort rating."),
    html("p", null, "Readiness is an illustrative weighted score. The personal reference uses the preceding 28 mornings. The load windows end before the scored morning."));
  const components = html("ul");
  for (const item of latest.components) components.append(html("li", null,
    `${item.name} · ${Math.round(item.weight * 100)}% weight · ${item.score}/100 component`));
  methods.append(components);
  card.append(grid, methods);
  return card;
}

function healthTrends(health) {
  const card = comparisonCard("Physiology trends", "Choose an observation, estimate or composite.");
  const selector = html("div", "segmented small health-trend-toggle");
  selector.setAttribute("role", "group");
  selector.setAttribute("aria-label", "Physiology history metric");
  const graph = svg("svg", { viewBox: "0 0 430 160", role: "img", class: "benchmark-chart" });
  const readout = html("p", "athlete-chart-readout");
  const rows = {
    hrv: { label: "HRV", unit: "ms", data: health.daily.slice(-28).map((p) => [p.date, p.hrv_ms]),
      reference: health.recent.baseline_hrv_ms, explanation: "Dashed line shows the 28-day median preceding the latest seven mornings." },
    aerobic: { label: "VO₂max", unit: "mL/kg/min", data: health.vo2max.map((p) => [p.date, p.estimate]),
      explanation: "Performance-based estimate from comparable fictional 5 km efforts." },
    ready: { label: "Readiness", unit: "/100", data: health.daily.slice(-21).map((p) => [p.date, p.readiness]),
      explanation: "Illustrative morning score. The plotted scale spans 0–100." },
  };
  const buttons = Object.entries(rows).map(([key, config]) => {
    const button = html("button", null, config.label);
    button.type = "button";
    button.addEventListener("click", () => { healthTrendChoice = key; draw(); });
    selector.append(button);
    return [key, button];
  });
  function draw() {
    const { label, unit, data, reference, explanation } = rows[healthTrendChoice];
    const values = data.map((p) => p[1]);
    if (reference != null) values.push(reference);
    const lo = healthTrendChoice === "ready" ? 0 : Math.floor(Math.min(...values) / 5) * 5;
    const hi = healthTrendChoice === "ready" ? 100 : Math.ceil((Math.max(...values) + 1) / 5) * 5;
    const start = Date.parse(data[0][0]), end = Date.parse(data.at(-1)[0]);
    const xAt = (day) => 42 + (Date.parse(day) - start) / (end - start) * 374;
    const yAt = (value) => 117 - (value - lo) / (hi - lo) * 100;
    graph.setAttribute("aria-label", `${label} trend · latest ${values[data.length - 1]} ${unit}`);
    graph.replaceChildren();
    for (const value of [lo, (lo + hi) / 2, hi]) {
      const y = yAt(value);
      graph.append(svg("line", { x1: 42, x2: 416, y1: y, y2: y, stroke: "var(--separator)" }),
        svg("text", { x: 34, y: y + 4, "text-anchor": "end" }, number(value, Number.isInteger(value) ? 0 : 1)));
    }
    if (reference != null) graph.append(svg("line", { x1: 42, x2: 416, y1: yAt(reference), y2: yAt(reference),
      stroke: "var(--muted)", "stroke-dasharray": "4 4" }));
    const points = data.map(([day, value]) => [xAt(day), yAt(value)]);
    graph.append(svg("polyline", { points: points.map((p) => p.join(",")).join(" "), fill: "none",
      stroke: "var(--elevation)", "stroke-width": 2.5, "stroke-linejoin": "round" }));
    for (let i = 0; i < points.length; i++) {
      const marker = svg("circle", { cx: points[i][0], cy: points[i][1], r: points.length < 10 || i === points.length - 1 ? 3.6 : 2.3,
        fill: "var(--elevation)" });
      marker.append(svg("title", {}, `${dayText(data[i][0])} · ${data[i][1]} ${unit}`));
      graph.append(marker);
    }
    graph.append(svg("text", { x: 42, y: 143 }, dayText(data[0][0]).split(",")[0]),
      svg("text", { x: 416, y: 143, "text-anchor": "end" }, dayText(data.at(-1)[0]).split(",")[0]));
    buttons.forEach(([key, button]) => button.setAttribute("aria-pressed", String(key === healthTrendChoice)));
    readout.textContent = explanation;
  }
  card.append(selector, graph, readout);
  draw();
  return card;
}

function renderProfile(data, holder) {
  const { profile } = data;
  const intro = pageTitle("Fitness Profile", `${data.name} · training history through ${dayText(data.through)}`, "Fictional athlete");
  scenarioPicker(intro, data, "profile", holder);
  const totalHours = Object.values(profile.lifetime).reduce((sum, sport) => sum + sport.duration_s, 0) / 3600;
  const tiles = metricTiles([
    ["Running history", km(profile.lifetime.running.distance_m), `${profile.lifetime.running.count} sessions`],
    ["Cycling history", km(profile.lifetime.cycling.distance_m), `${profile.lifetime.cycling.count} sessions`],
    ["Training time", `${number(totalHours, 1)} h`, `${profile.recent_active_weeks} of the last 8 weeks active`],
  ]);
  const primary = html("div", "analysis-grid athlete-grid");
  primary.append(trainingVolume(profile), benchmarkChart(profile));
  const healthGrid = html("div", "analysis-grid athlete-grid health-grid");
  healthGrid.append(healthStatus(data.health), healthTrends(data.health));
  const lower = html("div", "analysis-grid details-grid athlete-grid");
  const records = comparisonCard("Personal records", "Best eligible activities in this fictional history.");
  records.append(comparisonTable(["Record", "Result", "Date"], [
    ["Fastest 5 km benchmark", clock(profile.records.fastest_5k.duration_s), dayText(profile.records.fastest_5k.date)],
    ["Longest run", km(profile.records.longest_run.distance_m), dayText(profile.records.longest_run.date)],
    ["Longest ride", km(profile.records.longest_ride.distance_m), dayText(profile.records.longest_ride.date)],
  ]));
  const context = comparisonCard("Recent training and rest", "Last four complete Monday–Sunday weeks");
  context.append(html("p", "inline-takeaway",
    `${profile.recent_training_days} training days · ${28 - profile.recent_training_days} days without a logged session.`),
  html("p", "comparison-copy", `${km(profile.recent.running.distance_m)} running and ${km(profile.recent.cycling.distance_m)} cycling in this window.`),
  html("p", "comparison-copy", "Days without a logged session describe the schedule. The fixture has no direct recovery measurement."));
  const jump = html("a", "athlete-link", "Open Training Planner →");
  jump.href = "#planner";
  context.append(jump);
  lower.append(records, context);
  holder.replaceChildren(intro, tiles, primary, healthGrid, takeawayCard(data.takeaway), lower);
}

function renderPlanner(data, holder) {
  const plan = data.planner;
  const basis = plan.baseline;
  const choice = plan.alternatives[planChoice];
  const intro = pageTitle("Training Planner", `${plan.objective} · week of ${dayText(choice.days[0].date)}`, "Fictional athlete");
  scenarioPicker(intro, data, "planner", holder);
  const summary = metricTiles([
    ["Planned running", km(choice.totals.running), `${choice.days.filter((d) => d.sport === "running").length} sessions`],
    ["Planned cycling", km(choice.totals.cycling), "Easy aerobic ride"],
    ["Morning readiness", `${basis.readiness}/100`, `${unitCount(basis.load_7)} units of recent load`],
  ]);
  const grid = html("div", "analysis-grid planner-grid");
  const schedule = comparisonCard("Suggested week", "Adjust the volume to compare two versions of the week.");
  const options = html("div", "segmented small");
  options.setAttribute("role", "group");
  options.setAttribute("aria-label", "Plan volume");
  for (const [i, variant] of plan.alternatives.entries()) {
    const button = html("button", null, variant.label);
    button.type = "button";
    button.setAttribute("aria-pressed", String(planChoice === i));
    button.onclick = () => {
      planChoice = i;
      renderPlanner(data, holder);
      holder.querySelector('button[aria-pressed="true"]').focus();
    };
    options.append(button);
  }
  schedule.querySelector(".panel-heading").append(options);
  const list = html("ol", "plan-list");
  for (const day of choice.days) {
    const item = html("li", day.sport ? `plan-${day.sport}` : "plan-rest");
    const weekday = new Date(`${day.date}T12:00:00Z`).toLocaleDateString("en-CA", { weekday: "short", timeZone: "UTC" });
    const cell = html("div");
    cell.append(html("strong", null, day.session), html("p", null, day.detail));
    item.append(html("span", "plan-day", weekday), cell);
    if (day.sport) item.append(html("span", "plan-distance", km(day.distance_m)));
    list.append(item);
  }
  schedule.append(list);
  const reasoning = comparisonCard("Evidence behind the week", "Deterministic rules applied to the same history as Fitness Profile.");
  const samples = [
    ["Weekly volume", `The last week was ${km(basis.last_run_m)}. The four-week median was ${km(basis.median_run_m)}. The plan stays at or below both. The lighter option reduces the starting budget by 25% before rounding.`, "#profile/training-volume"],
    ["Load and readiness", `The morning score is ${basis.readiness}/100. Recent load was ${unitCount(basis.load_7)} units versus ${unitCount(basis.typical_load)} per week in the earlier 28-day reference. ${basis.volume_guard ? "The volume guard reduces the starting budgets by 20%." : "The volume guard is inactive."}`, "#profile/athlete-health"],
    ["Run frequency and long session", `The median was ${number(basis.median_run_sessions, 1)} runs per week. The longest recent run was ${km(basis.longest_recent_run_m)}, which sets the upper bound for Saturday.`, "#profile/training-volume"],
    ["Paced work", `${basis.recent_paced_sessions} steady or benchmark sessions appear in the recent four weeks. ${choice.paced ? "This week includes one controlled effort." : "This week uses easy efforts."}`, "#profile/running-benchmarks"],
    ["Cycling volume", `The recent median ride was ${km(basis.median_ride_m)}. The easy ride is rounded down from that reference.`, "#profile/training-volume"],
  ];
  for (const [title, text, href] of samples) {
    const expander = html("details", "evidence-details planner-evidence");
    const link = html("a", null, "See supporting Fitness Profile metrics →");
    link.href = href;
    expander.append(html("summary", null, title), html("p", null, text), link);
    reasoning.append(expander);
  }
  reasoning.append(html("p", "plan-caution", "This plan uses fictional training, sleep and effort inputs. Actual recovery and current constraints are unknown."));
  grid.append(schedule, reasoning);
  holder.replaceChildren(intro, summary, takeawayCard(choice.takeaway), grid);
}

async function renderAthletePage(view, holder, section, focusScenario = false) {
  const revision = ++athleteRevision;
  const loading = html("p", "feedback", "Loading fictional athlete history…");
  if (!holder.firstChild) holder.append(loading);
  try {
    const data = await athleteData(athleteScenario);
    if (holder.hidden || revision !== athleteRevision) return;
    if (view === "profile") renderProfile(data, holder);
    else renderPlanner(data, holder);
    if (focusScenario) holder.querySelector(".scenario-picker select")?.focus();
    if (["training-volume", "running-benchmarks", "athlete-health"].includes(section)) byId(section)?.scrollIntoView({ block: "start" });
  } catch {
    if (holder.hidden || revision !== athleteRevision) return;
    holder.replaceChildren(html("p", "feedback", "The fictional athlete history could not be loaded."));
  }
}
