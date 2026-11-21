"use strict";

const comparisonRoot = byId("comparative-workspace");
const runColors = ["var(--speed)", "var(--elevation)"];
const km = (metres) => `${number(metres / 1000, 2)} km`;
const covered = (value) => `${number(value * 100)}%`;
const reading = (value, unit, precision = 1) => value == null ? "Unavailable" : `${number(value, precision)} ${unit}`;
const pace = (value) => value == null ? "Unavailable" : `${clock(value)} /km`;
const signed = (value) => value > 0 ? `+${number(value, 1)}` : number(value, 1);
const headwind = (value) => value == null ? "Unavailable" : Math.abs(value) < .05 ? "0.0 m/s along route"
  : `${number(Math.abs(value), 1)} m/s ${value > 0 ? "headwind" : "tailwind"}`;
const windFrom = (value) => value == null ? "Unavailable" : `${number(Math.round(value) % 360)}° true`;

function indexedWeatherCoverage(summary) {
  if (!summary) return "—";
  const counts = Object.values(summary.field_sample_counts).filter((count) => count > 0);
  const min = Math.min(...counts), max = Math.max(...counts);
  return `${min === max ? number(min) : `${number(min)}–${number(max)}`} of ${number(summary.source_sample_count)}`;
}

let comparisonData;
let comparisonObserver;

function comparisonCard(title, description) {
  const card = html("section", "panel comparison-card");
  const heading = html("div", "panel-heading");
  const labels = html("div");
  labels.append(html("h2", null, title));
  if (description) labels.append(html("p", null, description));
  heading.append(labels);
  card.append(heading);
  return card;
}

function comparisonTable(headers, rows) {
  const wrapper = html("div", "table-wrap");
  const table = html("table");
  const thead = html("thead");
  const header = html("tr");
  for (const text of headers) {
    const cell = html("th", null, text);
    cell.scope = "col";
    header.append(cell);
  }
  thead.append(header);
  const body = html("tbody");
  for (const values of rows) body.append(row(values));
  table.append(thead, body);
  wrapper.append(table);
  return wrapper;
}

function distanceIndex(bins, distance) {
  let lo = 0, hi = bins.length - 1;
  while (lo < hi) {
    const middle = Math.floor((lo + hi) / 2);
    if (bins[middle].distance_m + bins[middle].width_m / 2 < distance) lo = middle + 1;
    else hi = middle;
  }
  return lo;
}

function drawComparisonMap(graph, analysis, select) {
  const routes = analysis.routes.flat();
  const points = routes.flat();
  const bounds = points.reduce(([loX, hiX, loY, hiY], [, x, y]) =>
    [Math.min(loX, x), Math.max(hiX, x), Math.min(loY, y), Math.max(hiY, y)],
    [Infinity, -Infinity, Infinity, -Infinity]);
  const [loX, hiX, loY, hiY] = bounds;
  const scale = Math.min(490 / Math.max(1, hiX - loX), 295 / Math.max(1, hiY - loY));
  const projectPoint = ([x, y]) => [300 + (x - (hiX + loX) / 2) * scale, 186 - (y - (hiY + loY) / 2) * scale];
  const xy = ([, x, y]) => projectPoint([x, y]).map((value) => value.toFixed(2)).join(",");
  const drawPath = (d, color, width, dash = "none") => graph.append(svg("path", {
    d, fill: "none", stroke: color, "stroke-width": width, "stroke-dasharray": dash,
    "stroke-linecap": "round", "stroke-linejoin": "round",
  }));
  const path = (part) => part.map((p, i) => `${i ? "L" : "M"}${xy(p)}`).join("");
  const grid = svg("pattern", { id: "comparison-grid", width: 28, height: 28, patternUnits: "userSpaceOnUse" });
  grid.append(svg("path", { d: "M28 0H0V28", fill: "none", stroke: "var(--map-grid-minor)" }));
  graph.replaceChildren(svg("title", {}, "Routes and matched ground"),
    grid, svg("rect", { width: 600, height: 380, fill: "url(#comparison-grid)" }));
  graph.append(svg("text", { x: 565, y: 29, "text-anchor": "middle" }, "N"),
    svg("path", { d: "M565 35l-6 16 6-4 6 4Z", fill: "var(--map-mark)" }));
  const scaleM = gridStep(70 / scale);
  graph.append(svg("path", { d: `M23 339v5h${scaleM * scale}v-5`, fill: "none", stroke: "var(--map-mark)" }),
    svg("text", { x: 23, y: 361 }, scaleM >= 1000 ? `${scaleM / 1000} km` : `${scaleM} m`));
  for (const [i, route] of analysis.routes.entries()) {
    drawPath(route.map(path).join(""), runColors[i], 3, i === 0 ? "none" : "4 4");
  }
  drawPath(path(analysis.shared), "var(--map-route-outline)", 8);
  drawPath(path(analysis.shared), "var(--map-overlay)", 4);
  const marker = svg("g", { class: "comparison-marker" });
  graph.append(marker);
  const samples = analysis.bins.map((bin) => bin.values.map((value) => projectPoint(value.point)));
  graph.onclick = (event) => {
    const p = cursorPoint(graph, event);
    let nearest = -1, best = 26 ** 2;
    samples.forEach((group, i) => group.forEach(([x, y]) => {
      const d = (p.x - x) ** 2 + (p.y - y) ** 2;
      if (d < best) { nearest = i; best = d; }
    }));
    if (nearest >= 0) select(nearest);
  };
  return (i) => {
    const points = samples[i];
    const overlap = Math.hypot(points[0][0] - points[1][0], points[0][1] - points[1][1]) < 8;
    marker.replaceChildren(...points.map(([cx, cy], j) => svg("circle", {
      cx, cy, r: overlap ? (j === 0 ? 8 : 4) : 5.5, fill: runColors[j],
      stroke: "var(--paper)", "stroke-width": overlap ? 1.2 : 2,
    })));
  };
}

function comparisonChart(plot, bins, distance, indexAt, select, resizeTarget) {
  const container = html("section", "plot comparison-plot");
  const header = html("div", "plot-header");
  const live = html("span", "comparison-reading");
  header.append(html("h3", null, plot.title), live);
  const graph = svg("svg", { "aria-hidden": "true" });
  container.append(header, graph);
  const values = [...plot.series.flatMap((series) => bins.map(series.get)),
    ...bins.flatMap((bin) => plot.band?.(bin) || [])].filter((v) => v != null);
  if (!values.length) {
    graph.hidden = true;
    container.append(html("p", "comparison-empty-plot", "No data within source coverage."));
    return { container, draw() {}, update() {} };
  }
  const min = Math.min(...values), max = Math.max(...values);
  const step = gridStep(Math.max(plot.minStep, (max - min) / 3));
  const lo = Math.floor(Math.min(min, plot.zero ? 0 : min) / step) * step;
  const hi = Math.max(lo + step, Math.ceil(Math.max(max, plot.zero ? 0 : max) / step) * step);
  let cursor, markers, xAt, yAt, left, right;
  function draw() {
    const width = resizeTarget.clientWidth - 38;
    if (width < 100) return;
    left = 36; right = width - 12;
    const top = 7, bottom = 65;
    graph.setAttribute("viewBox", `0 0 ${width} 87`);
    xAt = (m) => left + m / distance * (right - left);
    yAt = (v) => bottom - (v - lo) / (hi - lo) * (bottom - top);
    graph.replaceChildren();
    for (let tick = lo; tick < hi + step / 2; tick += step) {
      const y = yAt(tick);
      graph.append(svg("line", { x1: left, x2: right, y1: y, y2: y,
        class: plot.zero && Math.abs(tick) < 1e-8 ? "comparison-zero" : "gridline" }),
      svg("text", { x: left - 5, y: y + 3, "text-anchor": "end" }, plot.axis ? plot.axis(tick) : number(tick, step < 1 ? 1 : 0)));
    }
    const kmStep = gridStep(distance / 1000 / (width < 390 ? 4 : 5));
    for (let tick = 0; tick < distance / 1000 + .000001; tick += kmStep) {
      const x = xAt(tick * 1000);
      graph.append(svg("line", { x1: x, x2: x, y1: top, y2: bottom, class: "gridline" }),
        svg("text", { x, y: 81, "text-anchor": "middle" }, tick === 0 ? "0 km" : number(tick, kmStep < 1 ? 1 : 0)));
    }
    if (plot.band) {
      let piece = [];
      function drawBand() {
        if (piece.length > 1) {
          const bounds = [piece.map((p) => [p[0], p[1]]), piece.slice().reverse().map((p) => [p[0], p[2]])];
          graph.append(svg("polygon", { points: bounds.flat().map((p) => p.join(",")).join(" "), class: "peer-band" }));
        }
        piece = [];
      }
      for (const bin of bins) {
        const band = plot.band(bin);
        if (!band) drawBand();
        else piece.push([xAt(bin.distance_m), yAt(band[0]), yAt(band[1])]);
      }
      drawBand();
    }
    for (const { get, color, dash = "none" } of plot.series) {
      let path = "", wasValid = false;
      for (const bin of bins) {
        const value = get(bin);
        if (value != null) path += `${wasValid && !bin.break_before ? "L" : "M"}${xAt(bin.distance_m)},${yAt(value)}`;
        wasValid = value != null;
      }
      graph.append(svg("path", { d: path, class: "comparison-line", stroke: color, "stroke-dasharray": dash }));
    }
    cursor = svg("line", { y1: top, y2: bottom, class: "cursor-line" });
    markers = plot.series.map(({ color }) => svg("circle", { r: 3.7, fill: color, stroke: "white" }));
    graph.append(cursor, ...markers);
  }
  const fromPointer = (event) => {
    if (!cursor) return;
    const x = cursorPoint(graph, event).x;
    select(indexAt(Math.max(0, Math.min(1, (x - left) / (right - left))) * distance));
  };
  graph.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    graph.setPointerCapture(event.pointerId);
    fromPointer(event);
  });
  graph.addEventListener("pointermove", (event) => {
    if (event.pointerType === "mouse" || graph.hasPointerCapture(event.pointerId)) fromPointer(event);
  });
  function update(i) {
    const bin = bins[i];
    live.replaceChildren(...plot.series.map(({ get }, j) =>
      html("span", j === 1 ? "read-secondary" : "read-primary", plot.format(get(bin)))));
    if (!cursor) return;
    const x = xAt(bin.distance_m);
    cursor.setAttribute("x1", x);
    cursor.setAttribute("x2", x);
    markers.forEach((marker, j) => {
      const value = plot.series[j].get(bin);
      marker.toggleAttribute("hidden", value == null);
      if (value != null) {
        marker.setAttribute("cx", x);
        marker.setAttribute("cy", yAt(value));
      }
    });
  }
  return { container, draw, update };
}

function windDiagram(referenceWind) {
  const wrapper = html("div", "wind-diagram");
  const graph = svg("svg", { viewBox: "0 0 132 132", role: "img", "aria-label": "Travel and airflow directions" });
  const rider = svg("path", { d: "M66 31l-5 11h3v35h4V42h3Z", fill: "var(--speed)" });
  const air = svg("path", { d: "M66 25l-5 12h3v50h4V37h3Z", fill: "var(--elevation)" });
  graph.append(svg("circle", { cx: 66, cy: 66, r: 46, fill: "var(--surface)", stroke: "var(--line)" }),
    svg("path", { d: "M66 20v92M20 66h92", stroke: "var(--line)" }), rider, air);
  for (const [label, x, y] of [["N", 66, 14], ["E", 120, 70], ["S", 66, 127], ["W", 11, 70]]) {
    graph.append(svg("text", { x, y, "text-anchor": "middle" }, label));
  }
  const legend = html("div", "comparison-copy");
  legend.append(html("span", "key-blue", "● Travel"), html("span", "key-teal", "● Airflow"));
  const detail = html("p");
  legend.append(detail);
  wrapper.append(graph, legend);
  return { wrapper, update(bin) {
    const windSpeed = referenceWind ? referenceWind.wind_speed_mps : bin.wind_speed_mps;
    const direction = referenceWind ? referenceWind.wind_from_deg : bin.wind_from_deg;
    const head = referenceWind ? bin.reference_headwind_mps : bin.headwind_mps;
    const cross = referenceWind ? bin.reference_crosswind_mps : bin.crosswind_mps;
    rider.toggleAttribute("hidden", bin.heading_deg == null);
    air.toggleAttribute("hidden", direction == null || !windSpeed);
    rider.setAttribute("transform", `rotate(${bin.heading_deg || 0} 66 66)`);
    air.setAttribute("transform", `rotate(${(direction || 0) + 180} 66 66)`);
    const lateral = cross == null ? "crosswind unavailable" : Math.abs(cross) < .05 ? "no crosswind"
      : `${reading(Math.abs(cross), "m/s")} toward rider’s ${cross > 0 ? "right" : "left"}`;
    detail.textContent = `Travel heading ${windFrom(bin.heading_deg)}. ${head == null ? "Wind unavailable at this position."
      : `${headwind(head)} · ${lateral}`}`;
  } };
}

function comparisonMethods(running, analysis) {
  const card = comparisonCard("Methods and sources");
  const body = html("div", "comparison-copy");
  const { methods, provenance, synthetic } = comparisonData;
  body.append(html("p", null, running
    ? `Geometry is tested every ${methods.match_step_m} m. A match needs ${methods.match_min_m} m of continuous forward progress, within ${methods.match_tolerance_m} m and ${methods.max_heading_difference_deg}° of direction. RMS separation here is ${reading(analysis.rms_separation_m, "m")}.`
      : `Speed uses timed route distance in bins up to ${methods.ride_bin_m} m. Grade is elevation change over ${methods.grade_baseline_m} m of horizontal route. Headwind is positive, tailwind negative. The airflow arrow points in the direction the air moves.`));
  body.append(html("p", null, running
    ? "Pace uses common horizontal distance and timer-active seconds. Recording gaps split the route. Heart rate and device temperature are weighted by valid moving time."
    : synthetic ? "The elevation profile is generated. Weather and motion are fictional."
      : "FIT elevation is recorded by the device. Its sensor method can vary and short grades are sensitive to elevation errors. Terrain-model elevations have separate coverage."));
  for (const source of Object.values(provenance).filter(Boolean)) {
    const bounds = source.max_distance_m ? ` Within ${reading(source.max_distance_m, "m", 0)}${source.max_time_offset_s
      ? ` and ±${reading(source.max_time_offset_s / 60, "min", 0)}` : ""}.` : "";
    body.append(html("p", null, `${source.provider} · ${source.product} · ${source.source_kind}. ${source.resolution}.${bounds} Reference ${source.reference}.`));
  }
  if (!provenance.weather) body.append(html("p", null, running && synthetic
    ? "Segment weather is unavailable for this pair." : "Time- and location-resolved historical weather is unavailable."));
  if (!provenance.terrain) body.append(html("p", null, "Terrain model unavailable."));
  card.append(body);
  return card;
}

function showComparison(data, view, wholeRuns = []) {
  rideTimelineUpdate = null;
  if (comparisonObserver) comparisonObserver.disconnect();
  comparisonRoot.replaceChildren();
  comparisonRoot.hidden = !data;
  if (!data) return;
  comparisonData = data;
  const running = view === "running";
  const analysis = comparisonData[view];
  const intro = html("section", "section-intro");
  const titles = html("div");
  const names = running && analysis.available ? analysis.runs.map((run, i) =>
    wholeRuns[i]?.date ? `${run.name} · ${dayText(wholeRuns[i].date)}` : run.name) : [];
  const headline = running ? "Matched section · fictional pair" : "Terrain, wind and cycling speed";
  titles.append(html("h2", null, headline), html("p", null, running
      ? names.length ? `${names.join(" and ")} · aligned by distance over a continuous same-direction segment` : analysis.message
      : analysis.available ? `${analysis.name} · ${km(analysis.distance_m)} of timed route geometry${analysis.recorded_ascent_m == null
        ? "" : ` · ${reading(analysis.recorded_ascent_m, "m", 0)} ascent`}` : analysis.message));
  intro.append(titles);
  comparisonRoot.append(intro);
  if (!analysis.available) return;

  const { bins, distance_m: distance } = analysis;
  const indexAt = (m) => distanceIndex(bins, m);
  const hasTerrain = !running && bins.some((bin) => bin.terrain_m != null);
  const hasWind = running ? bins.some((bin) => bin.values.some((v) => v.headwind_mps != null))
    : bins.some((bin) => bin.headwind_mps != null);
  const referenceWind = !running && !hasWind && bins.some((bin) => bin.reference_headwind_mps != null)
    ? analysis.activity_weather : null;
  const windKey = referenceWind ? "reference_headwind_mps" : "headwind_mps";
  const charts = comparisonCard(running ? "Aligned performance" : "Along-route grade and wind",
    running ? "Select a distance to move the matched-route markers." : "Select a distance to inspect the same position on the activity map and timeline.");
  const timeline = html("div", "timeline");
  const line = html("div", "timeline-label");
  const label = html("label", null, running ? "Shared distance" : "Route distance");
  const slider = html("input");
  Object.assign(slider, { id: "comparison-distance", type: "range", min: 0, max: bins.length - 1, step: 1 });
  label.htmlFor = slider.id;
  const output = html("output");
  output.setAttribute("for", slider.id);
  line.append(label, output);
  timeline.append(line, slider);
  const chartBody = html("div", "plots");
  const paired = (key) => runColors.map((color, i) => ({
    color, dash: i === 0 ? "none" : "4 3", get: (bin) => bin.values[i][key],
  }));
  const single = (key, color = "var(--speed)") => [{ color, get: (bin) => bin[key] }];
  const series = running ? [
    { title: "Moving pace · min/km", series: paired("pace_s_per_km"), axis: clock, format: pace, minStep: 15 },
    { title: "Heart rate · bpm", series: paired("mean_heart_bpm"), format: (v) => reading(v, "bpm", 0), minStep: 2 },
    ...(hasWind ? [{ title: "Along-track wind · m/s", series: paired("headwind_mps"),
      format: headwind, zero: true, minStep: 1 }] : []),
  ] : [
    { title: "Grade · %", series: [...single("recorded_grade_display_pct"), ...(hasTerrain ? single("terrain_grade_pct", "var(--elevation)") : [])],
      format: (v) => v == null ? "Unavailable" : `${signed(v)}%`, zero: true, minStep: 1 },
    { title: referenceWind ? "Along-track wind reference · m/s" : "Along-track wind · m/s",
      series: single(windKey, "var(--elevation)"), format: headwind, zero: true, minStep: 1 },
  ];
  const plots = series.map((plot) => comparisonChart(plot, bins, distance, indexAt, select, charts));
  chartBody.append(...plots.map(({ container }) => container));
  charts.append(chartBody, timeline);
  const grid = html("div", "analysis-grid comparison-layout");

  let selection = analysis.strongest_climb ? indexAt(analysis.strongest_climb.distance_m) : Math.floor(bins.length * .38);
  let updateMap;
  const vector = running ? null : windDiagram(referenceWind);
  function select(i, link = true) {
    selection = i;
    slider.value = i;
    const bin = bins[i];
    output.value = running ? km(bin.distance_m) : `${km(bin.distance_m)} · ${clock(bin.elapsed_s)} elapsed`;
    for (const plot of plots) plot.update(i);
    slider.setAttribute("aria-valuetext", [output.value, ...plots.map(({ container }) =>
      container.querySelector(".plot-header").innerText.trim())].join(", "));
    if (updateMap) updateMap(i);
    if (vector) vector.update(bin);
    if (!running && link) selectSample(nearestSample(bin.elapsed_s), false);
  }
  slider.addEventListener("input", () => select(slider.valueAsNumber));
  if (running) {
    const mapCard = comparisonCard("Matched route", "North-up route trace · select a position");
    const mapFrame = html("div", "route-map compare-map");
    const map = svg("svg", { viewBox: "0 0 600 380", role: "img" });
    const legend = html("div", "map-legend comparison-legend");
    mapFrame.append(map);
    mapCard.append(mapFrame, legend);
    updateMap = drawComparisonMap(map, analysis, select);
    legend.append(html("span", "map-legend-a", `━ ${names[0]}`),
      html("span", "map-legend-b", `┄ ${names[1]}`), html("span", "map-legend-shared", "━ Matched ground"));
    grid.append(mapCard);
  } else {
    rideTimelineUpdate = (elapsed) => {
      let lo = 0, hi = bins.length - 1;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (bins[mid].elapsed_s < elapsed) lo = mid + 1;
        else hi = mid;
      }
      if (lo && elapsed - bins[lo - 1].elapsed_s < bins[lo].elapsed_s - elapsed) lo--;
      select(lo, false);
    };
  }
  grid.append(charts);
  const supporting = html("div", running ? "analysis-grid details-grid compare-support" : "details-grid compare-support");
  if (running) renderRunningEvidence(analysis, supporting, names, wholeRuns);
  else renderCyclingEvidence(analysis, grid, vector, hasTerrain, referenceWind, (m) => select(indexAt(m)));
  supporting.append(comparisonMethods(running, analysis));
  comparisonRoot.append(grid, supporting);
  comparisonObserver = new ResizeObserver(() => {
    for (const plot of plots) plot.draw();
    select(selection, false);
  });
  comparisonObserver.observe(charts);
  select(selection);
}

function renderRunningEvidence(analysis, section, names, wholeRuns) {
  const [a, b] = analysis.runs;
  const change = 100 * analysis.pace_change_fraction;
  const verdict = analysis.pace_change_fraction == null ? "Moving pace is unavailable."
    : Math.abs(change) < .05 ? "Matching moving pace at displayed precision."
      : `The second run took ${number(Math.abs(change), 1)}% ${change < 0 ? "less" : "more"} time per kilometre on the matched section.`;
  const highlight = html("p", "comparison-highlight", `${km(analysis.distance_m)} shared · ${verdict}`);
  comparisonRoot.append(highlight);
  const heart = (bpm, coverage) => bpm == null ? "Unavailable"
    : `${reading(bpm, "bpm", 0)} · ${covered(coverage)} coverage`;
  const scope = "Whole-run";
  const summary = comparisonCard("Whole runs and matched section",
    "Differences in recorded pace and heart rate describe these efforts. A fitness trend requires repeated evidence under comparable conditions.");
  summary.classList.add("run-comparison-summary");
  summary.append(comparisonTable(["Measurement", ...names], [
    [`${scope} distance`, ...wholeRuns.map((r) => r?.distance_m == null ? "Unavailable" : km(r.distance_m))],
    [`${scope} timer pace`, ...wholeRuns.map((r) => pace(r?.pace_s_per_km))],
    [`${scope} heart rate`, ...wholeRuns.map((r) => heart(r?.heart_bpm, r?.heart_coverage))],
    ["Matched-section moving pace", ...analysis.runs.map((r) => pace(r.pace_s_per_km))],
    ["Matched-section heart rate", ...analysis.runs.map((r) => heart(r.mean_heart_bpm, r.heart_coverage))],
  ]));
  summary.append(html("p", "comparison-copy",
    "Heart-rate coverage uses elapsed time for the whole run and timer-active time for the matched section."));
  comparisonRoot.append(summary);
  const panel = comparisonCard("Other segment measurements", "Coverage is shown beside means.");
  const runCells = (get) => analysis.runs.map(get);
  const hasSegmentWeather = analysis.runs.some((run) => run.air_temperature_c != null || run.wind_speed_mps != null);
  const hasArchivedWeather = analysis.runs.some((run) => run.activity_weather);
  const field = (label, key, unit) => [label, ...runCells((r) => r[key] == null ? "—"
    : `${reading(r[key], unit)} · ${covered(r[key + "_coverage"])}`)];
  panel.append(comparisonTable(["Measurement", ...names], [
    ["Moving time", ...runCells((r) => clock(r.moving_s))],
    ["Elapsed time", ...runCells((r) => clock(r.elapsed_s))],
    ...(hasSegmentWeather ? [
      field(comparisonData.synthetic ? "Fictional air temperature" : "Historical air temperature", "air_temperature_c", "°C"),
      field("Wind speed", "wind_speed_mps", "m/s"),
      ["Mean along-track wind", ...runCells((r) => r.headwind_mps == null ? "—"
        : `${headwind(r.headwind_mps)} · ${covered(r.headwind_mps_coverage)}`)],
    ] : []),
    ...(comparisonData.provenance.terrain ? [field("Terrain-model elevation", "terrain_m", "m")] : []),
  ]));
  const caption = html("p", "comparison-copy");
  const differences = [];
  if (a.air_temperature_c_coverage >= .999999 && b.air_temperature_c_coverage >= .999999) {
    const delta = b.air_temperature_c - a.air_temperature_c;
    differences.push(Math.abs(delta) < .05 ? "Mean air temperature was similar across the segment."
      : `${b.name}’s mean air temperature was ${reading(Math.abs(delta), "°C")} ${delta > 0 ? "higher" : "lower"} over the shared segment.`);
  }
  if (a.headwind_mps_coverage >= .999999 && b.headwind_mps_coverage >= .999999) {
    differences.push(`Mean along-track wind shifted from ${headwind(a.headwind_mps)} to ${headwind(b.headwind_mps)}.`);
  }
  if (a.device_temperature_c != null || b.device_temperature_c != null) {
    differences.push("Wearable temperature can reflect body heat and exposure.");
  }
  caption.textContent = differences.join(" ");
  panel.append(caption);
  if (hasArchivedWeather) {
    const heading = html("div", "panel-heading archive-weather-heading");
    const labels = html("div");
    labels.append(html("h2", null, "Historical weather for the full runs"),
      html("p", null, "Archive estimates cover the full activities. Segment weather requires time- and location-resolved values."));
    heading.append(labels);
    panel.append(heading, comparisonTable(["Estimate", ...names], [
      ["Air temperature", ...runCells((r) => reading(r.activity_weather?.air_temperature_c, "°C"))],
      ["Wind speed", ...runCells((r) => reading(r.activity_weather?.wind_speed_mps, "m/s"))],
      ["Wind from", ...runCells((r) => windFrom(r.activity_weather?.wind_from_deg))],
      ["Reported field counts", ...runCells((r) => indexedWeatherCoverage(r.activity_weather))],
    ]));
  }
  section.append(panel);
}

function renderCyclingEvidence(analysis, section, vector, hasTerrain, referenceWind, selectDistance) {
  const climb = analysis.strongest_climb;
  const environment = analysis.environment;
  const highlight = html("div", "comparison-highlight climb-highlight");
  if (climb) {
    const jump = html("button", null, `View the 500 m climb near ${km(climb.distance_m)}`);
    jump.type = "button";
    jump.addEventListener("click", () => selectDistance(climb.distance_m));
    highlight.append(jump);
    comparisonRoot.append(highlight);
  }
  const panel = comparisonCard(referenceWind ? "Wind reference at the selected distance" : "Wind at the selected distance",
    referenceWind ? "The archived speed and direction stay fixed as the rider’s heading changes."
      : "Along-track and crosswind depend on travel direction.");
  panel.append(vector.wrapper, html("p", "comparison-copy",
    `Time- and location-resolved wind coverage ${covered(environment.headwind_mps_coverage)} · terrain-model coverage ${covered(environment.terrain_m_coverage)}.`));
  const archive = analysis.activity_weather;
  if (archive) {
    const parts = [archive.air_temperature_c == null ? null : reading(archive.air_temperature_c, "°C"),
      archive.wind_speed_mps == null ? null : reading(archive.wind_speed_mps, "m/s"),
      archive.wind_from_deg == null ? null : `from ${windFrom(archive.wind_from_deg)}`].filter(Boolean);
    const anchors = archive.spatial_anchor_count == null ? "" : ` across ${number(archive.spatial_anchor_count)} archive anchors`;
    panel.append(html("p", "comparison-copy", `Whole-activity estimates · ${parts.join(" · ")}. Reported field counts ${indexedWeatherCoverage(archive)}${anchors}.`));
  }
  if (analysis.device_temperature_c != null) panel.append(html("p", "comparison-copy",
    `Device temperature averaged ${reading(analysis.device_temperature_c, "°C")} across ${covered(analysis.device_temperature_coverage)} of usable moving time.`));
  if (environment.air_temperature_c != null) panel.append(html("p", "comparison-copy",
    `Air temperature averaged ${reading(environment.air_temperature_c, "°C")} across ${covered(environment.air_temperature_c_coverage)} of the route.`));
  if (hasTerrain) panel.append(html("p", "comparison-copy", "Blue profile · Recorded FIT. Teal profile · Terrain model."));
  section.append(panel);
}
