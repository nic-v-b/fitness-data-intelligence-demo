"use strict";

const byId = (id) => document.getElementById(id);
const controls = {
  activities: byId("activities"), route: byId("route"), features: byId("map-features"),
  marker: byId("map-cursor"), metric: byId("route-metric"), plots: byId("plots"),
  slider: byId("sample-index"), position: byId("sample-position"),
};
const signals = [
  { id: "speed", name: "Speed", key: "speed_mps", unit: "km/h", ticks: [9, 12, 15],
    value: (sample) => sample.derived.speed_kmh, decimals: 1 },
  { id: "heart", name: "Heart rate", key: "heart_rate_bpm", unit: "bpm", ticks: [125, 150, 175],
    value: (sample) => sample.source.heart_rate_bpm, decimals: 0 },
  { id: "elevation", name: "Elevation", key: "elevation_m", unit: "m", ticks: [110, 140, 170],
    value: (sample) => sample.source.elevation_m, decimals: 1 },
];
let activity;
let selectedIndex = 0;
let routeMetric = "speed";
let project;
let routePoints;
let plots;
let plotTicks;
let historyOverlay;
let rideTimelineUpdate = null;

function html(tag, className, label) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (label !== undefined) element.textContent = label;
  return element;
}

function svg(tag, attributes = {}, label) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
  if (label !== undefined) element.textContent = label;
  return element;
}

function clock(seconds) {
  if (seconds === null) return "—";
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function number(value, decimals = 0) {
  return value === null ? "—" : value.toFixed(decimals);
}

function withUnit(value, unit) {
  return value === "—" ? value : `${value} ${unit}`;
}

function valueOf(sample, signal) {
  return sample.quality[signal.key] === "valid" ? signal.value(sample) : null;
}

function setStat(id, value, unit) {
  const field = byId(id);
  field.textContent = value;
  if (unit && value !== "—") field.append(html("small", null, unit));
}

function row(values) {
  const tr = html("tr");
  values.forEach((value, index) => {
    const cell = html(index ? "td" : "th", null, value);
    if (!index) cell.scope = "row";
    tr.append(cell);
  });
  return tr;
}

function renderSummary() {
  const s = activity.summary;
  const cycling = activity.sport === "cycling";
  setStat("stat-distance", number(s.distance_m === null ? null : s.distance_m / 1000, 2), "km");
  setStat("stat-time", clock(s.elapsed_s), "min:s");
  byId("stat-pace-label").textContent = cycling ? "Elapsed avg. speed" : "Elapsed pace";
  setStat("stat-pace", cycling ? number(s.mean_speed_kmh, 1) : clock(s.mean_pace_s_per_km), cycling ? "km/h" : "/km");
  setStat("stat-heart", number(s.mean_heart_rate_bpm), "bpm");
  setStat("stat-gain", number(s.elevation_gain_m), "m");
  byId("sample-count").textContent = `${s.sample_count} samples`;
  byId("splits").replaceChildren(...activity.splits.map((split) => row([
    `${split.number}${split.complete ? "" : " · partial"}`,
    `${number(split.distance_m / 1000, 2)} km`, clock(split.duration_s),
    withUnit(clock(split.pace_s_per_km), "/km"),
  ])));
  byId("quality").replaceChildren(...signals.map((signal) => {
    const counts = s.quality_counts[signal.key];
    return row([signal.name, counts.valid, counts.missing, counts.invalid]);
  }));
  byId("heart-coverage").textContent = s.heart_rate_coverage === null ? "Heart-rate coverage unavailable" :
    `Heart-rate time coverage ${number(s.heart_rate_coverage * 100, 1)}%`;
  const csv = byId("csv-export");
  csv.hidden = !["west-run", "east-run"].includes(activity.id);
  if (!csv.hidden) csv.href = `/exports/${activity.id}.csv`;
}

function facts(target, settings) {
  byId(target).replaceChildren(...settings.flatMap(([label, value]) =>
    [html("dt", null, label), html("dd", null, value)]));
}

function routeProjection(activities) {
  const points = activities.flatMap((run) => run.samples.map(({ source }) => source))
    .filter(({ x_m, y_m }) => x_m !== null && y_m !== null);
  const xs = points.map((point) => point.x_m);
  const ys = points.map((point) => point.y_m);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const scale = Math.min(520 / Math.max(1, maxX - minX), 286 / Math.max(1, maxY - minY));
  return {
    scale,
    point: ({ x_m, y_m }) => x_m === null || y_m === null ? null : [320 + (x_m - (minX + maxX) / 2) * scale,
      184 - (y_m - (minY + maxY) / 2) * scale],
  };
}

function gridStep(target) {
  const magnitude = 10 ** Math.floor(Math.log10(target));
  return [1, 2, 2.5, 5, 10].find((step) => step * magnitude >= target) * magnitude;
}

function signalTicks(activities, signal) {
  const values = activities.flatMap((run) => run.samples.map((sample) => valueOf(sample, signal)))
    .filter((value) => value !== null);
  if (!values.length) return signal.ticks;
  const lo = Math.min(...values), hi = Math.max(...values);
  const step = gridStep(Math.max(2, (hi - lo) / 3));
  const first = Math.floor(lo / step) * step;
  const count = Math.max(2, Math.ceil((hi - first) / step));
  return Array.from({ length: count + 1 }, (_, index) => first + index * step);
}

function segmentColor(a, b, palette) {
  if (a === null || b === null) return "var(--map-missing)";
  const scaled = Math.max(0, Math.min(1, ((a + b) / 2 - palette.min) / (palette.max - palette.min))) * 2;
  const stop = Math.min(1, Math.floor(scaled));
  const rgb = palette.colors[stop].map((channel, index) =>
    Math.round(channel + (palette.colors[stop + 1][index] - channel) * (scaled - stop)));
  return `rgb(${rgb.join(",")})`;
}

function routePalette() {
  const signal = signals.find((item) => item.id === routeMetric);
  const [min, ...ticks] = plotTicks[routeMetric];
  const theme = getComputedStyle(controls.route);
  const colors = ["low", "mid", "high"].map((stop) =>
    theme.getPropertyValue("--route-" + routeMetric + "-" + stop).trim().split(/\s+/).map(Number));
  return { signal, palette: { colors, min, max: ticks.at(-1) } };
}

function renderRoute() {
  const { signal, palette } = routePalette();
  const width = 5;
  const layer = document.createDocumentFragment();
  const connected = routePoints.map((point, i) =>
    Boolean(point && routePoints[i - 1] && !activity.samples[i].route_break_before));
  const path = routePoints.map((point, i) => point ? `${connected[i] ? "L" : "M"}${point.join(",")}` : "").join(" ");
  if (historyOverlay) {
    let previous = false;
    const overlay = historyOverlay.samples.map((sample) => {
      const point = project.point(sample.source);
      const command = previous && !sample.route_break_before ? "L" : "M";
      previous = Boolean(point);
      return point ? `${command}${point.join(",")}` : "";
    }).join(" ");
    layer.append(svg("path", { d: overlay, fill: "none", stroke: "var(--map-overlay)", "stroke-width": width + 3,
      opacity: .78, "stroke-dasharray": "3 5", "stroke-linecap": "round" }));
  }
  layer.append(svg("path", { d: path, fill: "none", stroke: "var(--map-route-outline)", "stroke-width": width + 5,
    "stroke-linejoin": "round", "stroke-linecap": "round" }));
  if (activity.shared_segment) {
    const { start_index: start, end_index: end } = activity.shared_segment;
    const shared = routePoints.slice(start, end + 1).map((point) => point.join(",")).join(" ");
    layer.append(svg("polyline", { points: shared, fill: "none", stroke: "var(--map-shared)", opacity: .73,
      "stroke-width": 11, "stroke-dasharray": "2 6", "stroke-linejoin": "round" }));
  }
  for (let i = 1; i < routePoints.length; i++) {
    if (!connected[i]) continue;
    const [x1, y1] = routePoints[i - 1];
    const [x2, y2] = routePoints[i];
    const a = valueOf(activity.samples[i - 1], signal);
    const b = valueOf(activity.samples[i], signal);
    layer.append(svg("line", { x1, y1, x2, y2, stroke: segmentColor(a, b, palette),
      "stroke-width": width, "stroke-linecap": "round", "data-sample-index": i }));
  }
  routePoints.forEach((point, i) => {
    if (point && !connected[i] && !connected[i + 1]) {
      layer.append(svg("circle", { cx: point[0], cy: point[1], r: 2, fill: "var(--map-missing)" }));
    }
  });
  const first = routePoints.find(Boolean), last = routePoints.findLast(Boolean);
  if (first && last) {
    const near = Math.hypot(first[0] - last[0], first[1] - last[1]) < 55;
    for (const [[x, y], text, dy] of [[first, "START", near ? -12 : 20], [last, "FINISH", 20]]) {
      layer.append(
        svg("circle", { cx: x, cy: y, r: 4.5, fill: "var(--map-mark)", stroke: "var(--paper)", "stroke-width": 2 }),
        svg("text", { x, y: y + dy, class: "map-tag", "text-anchor": "middle" }, text),
      );
    }
  }
  const scaleMetres = 500;
  const scale = project.scale * scaleMetres;
  layer.append(
    svg("path", { d: `M26 340v5h${scale}v-5`, fill: "none", stroke: "var(--map-mark)", "stroke-width": 1.2 }),
    svg("text", { x: 26 + scale / 2, y: 362, "text-anchor": "middle" },
      scaleMetres >= 1000 ? `${scaleMetres / 1000} km` : `${scaleMetres} m`),
  );
  controls.features.replaceChildren(layer);
  byId("overlay-legend").hidden = !historyOverlay;
  byId("map-name").textContent = `${activity.name} route coloured by ${signal.name.toLowerCase()}`;
  byId("legend-min").textContent = `${palette.min}`;
  byId("legend-max").textContent = `${palette.max} ${signal.unit}`;
  byId("legend-ramp").classList.toggle("heart", routeMetric === "heart");
}

function cursorPoint(element, event) {
  return new DOMPoint(event.clientX, event.clientY).matrixTransform(element.getScreenCTM().inverse());
}

function nearestSample(time) {
  const { samples } = activity;
  let low = 0;
  let high = samples.length - 1;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (samples[middle].source.elapsed_s < time) low = middle + 1;
    else high = middle;
  }
  if (low > 0 && time - samples[low - 1].source.elapsed_s <= samples[low].source.elapsed_s - time) {
    return low - 1;
  }
  return low;
}

function createPlot(signal, showTime) {
  const container = html("section", `plot plot-${signal.id}`);
  const header = html("div", "plot-header");
  const title = html("h3");
  const dot = html("i");
  dot.setAttribute("aria-hidden", "true");
  title.append(dot, signal.name, html("span", null, signal.unit));
  const reading = html("span", "plot-value");
  header.append(title, reading);
  const graph = svg("svg", { "aria-hidden": "true" });
  const plot = { signal, showTime, reading, graph };
  container.append(header, graph);
  controls.plots.append(container);
  const selectAtPointer = (event) => {
    const fraction = (cursorPoint(graph, event).x - plot.left) / (plot.right - plot.left);
    selectSample(nearestSample(Math.max(0, Math.min(1, fraction)) * activity.summary.elapsed_s));
  };
  let capturedPointer = null;
  graph.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || capturedPointer !== null) return;
    capturedPointer = event.pointerId;
    graph.setPointerCapture(capturedPointer);
    selectAtPointer(event);
  });
  graph.addEventListener("pointermove", (event) => {
    if (event.pointerId === capturedPointer || (capturedPointer === null && event.pointerType === "mouse")) {
      selectAtPointer(event);
    }
  });
  graph.addEventListener("lostpointercapture", (event) => {
    if (capturedPointer === event.pointerId) capturedPointer = null;
  });
  return plot;
}

function drawPlot(plot) {
  const { signal, graph, showTime } = plot;
  const width = graph.clientWidth;
  const height = graph.clientHeight;
  graph.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const left = 34, right = width - 8, top = 6, bottom = height - (showTime ? 26 : 7);
  const ticks = plotTicks[signal.id];
  const minimum = ticks[0], maximum = ticks.at(-1);
  const duration = activity.summary.elapsed_s;
  const xAt = (time) => left + time / duration * (right - left);
  const yAt = (value) => bottom - (value - minimum) / (maximum - minimum) * (bottom - top);
  Object.assign(plot, { left, right, xAt, yAt, bottom });
  graph.replaceChildren();

  for (const tick of ticks) {
    const y = yAt(tick);
    graph.append(
      svg("line", { x1: left, y1: y, x2: right, y2: y, class: "gridline" }),
      svg("text", { x: left - 6, y: y + 3, "text-anchor": "end" }, tick),
    );
  }
  const tickSpacing = width < 360 ? 600 : 360;
  for (let time = 0; time <= duration; time += tickSpacing) {
    const x = xAt(time);
    graph.append(svg("line", { x1: x, y1: top, x2: x, y2: bottom, class: "gridline" }));
    if (showTime) graph.append(svg("text", { x, y: bottom + 14, "text-anchor": "middle" }, clock(time)));
  }
  if (showTime) {
    graph.append(svg("text", { x: right, y: height - 1, "text-anchor": "end" },
      "Elapsed time · min:s"));
  }

  let segment = [];
  function drawSegment() {
    if (segment.length > 1) {
      const pointList = segment.map((point) => point.join(",")).join(" ");
      const firstX = segment[0][0], lastX = segment.at(-1)[0];
      graph.append(svg("polygon", { points: `${firstX},${bottom} ${pointList} ${lastX},${bottom}`,
        class: "plot-area" }));
      graph.append(svg("polyline", { points: pointList, class: "plot-line" }));
    } else if (segment.length === 1) {
      graph.append(svg("circle", { cx: segment[0][0], cy: segment[0][1], r: 2, class: "plot-single" }));
    }
    segment = [];
  }
  for (const sample of activity.samples) {
    const value = valueOf(sample, signal);
    if (value === null || sample.break_before) drawSegment();
    if (value !== null) segment.push([xAt(sample.source.elapsed_s), yAt(value)]);
  }
  drawSegment();
  plot.line = svg("line", { y1: top, y2: bottom, class: "cursor-line" });
  plot.dot = svg("circle", { r: 3.6, class: "cursor-dot" });
  plot.gap = svg("rect", { y: bottom - 4, width: 7, height: 7, rx: 1, class: "cursor-missing" });
  graph.append(plot.line, plot.dot, plot.gap);
}

function selectSample(index, syncRide = true) {
  selectedIndex = index;
  const sample = activity.samples[index];
  const { elapsed_s: elapsed, distance_m: distance } = sample.source;
  const point = routePoints[index];
  controls.marker.toggleAttribute("hidden", !point);
  if (point) controls.marker.setAttribute("transform", `translate(${point.join(" ")})`);
  controls.marker.dataset.sampleIndex = index;
  controls.slider.value = index;
  if (syncRide) rideTimelineUpdate?.(elapsed);
  const distanceKm = number(distance === null ? null : distance / 1000, 2);
  controls.position.value = `#${String(index + 1).padStart(3, "0")} · ${clock(elapsed)} · ${withUnit(distanceKm, "km")}${point ? "" : " · Position unavailable"}`;
  for (const plot of plots) {
    const value = valueOf(sample, plot.signal);
    const cursorX = plot.xAt(elapsed);
    plot.line.setAttribute("x1", cursorX);
    plot.line.setAttribute("x2", cursorX);
    plot.dot.toggleAttribute("hidden", value === null);
    plot.gap.toggleAttribute("hidden", value !== null);
    if (value !== null) {
      plot.dot.setAttribute("cx", cursorX);
      plot.dot.setAttribute("cy", plot.yAt(value));
    } else {
      plot.gap.setAttribute("x", cursorX - 3.5);
    }
    const status = sample.quality[plot.signal.key];
    plot.reading.textContent = value === null ? (status === "invalid" ? "Invalid reading" : "Missing reading") :
      `${number(value, plot.signal.decimals)} ${plot.signal.unit}`;
    if (activity.sport === "running" && plot.signal.id === "speed" && sample.derived.pace_s_per_km !== null) {
      plot.reading.textContent += ` · ${clock(sample.derived.pace_s_per_km)}/km`;
    }
    plot.reading.classList.toggle("unavailable", value === null);
  }
  const readings = plots.map(({ signal, reading }) => `${signal.name} ${reading.textContent}`).join(", ");
  controls.slider.setAttribute("aria-valuetext",
    `Sample ${index + 1}, ${clock(elapsed)} elapsed, ${distance === null ? "distance unavailable" : `${distanceKm} kilometres`}, ${readings}${point ? "" : ", route position unavailable"}`);
}

function chooseActivity(run) {
  activity = run;
  rideTimelineUpdate = null;
  historyOverlay = null;
  controls.activities.value = run.id;
  plotTicks = Object.fromEntries(signals.map((signal) => [signal.id, signalTicks([run], signal)]));
  project = routeProjection([run]);
  routePoints = run.samples.map(({ source }) => project.point(source));
  controls.slider.max = run.samples.length - 1;
  byId("shared-legend").hidden = !run.shared_segment;
  renderSummary();
  renderRoute();
  plots.forEach(drawPlot);
  selectSample(nearestSample(run.summary.elapsed_s * 0.40));
}

function provenance(metadata) {
  const origin = [
    ["Dataset", metadata.dataset_id], ["Source", "Deterministic synthetic generator"],
    ["Seeds", metadata.generation.runs.map((run) => run.seed).join(" · ")],
  ];
  facts("provenance-fields", [
    ...origin,
    ["Coordinate system", metadata.coordinate_system], ["Schema", metadata.schema_version],
    ["Processing", metadata.processing_version],
  ]);
  byId("dataset-version").textContent = metadata.dataset_id + " · processing " + metadata.processing_version;
}

function setupExplorer(metadata) {
  byId("json-export").hidden = false;
  plots = signals.map((signal, index) => createPlot(signal, index === signals.length - 1));
  for (const button of controls.metric.children) {
    button.addEventListener("click", () => {
      routeMetric = button.dataset.metric;
      for (const option of controls.metric.children) option.setAttribute("aria-pressed", String(button === option));
      renderRoute();
    });
  }
  controls.route.addEventListener("click", (event) => {
    const point = cursorPoint(controls.route, event);
    let nearest = selectedIndex;
    let best = 22 ** 2;
    routePoints.forEach((sample, index) => {
      if (!sample) return;
      const [x, y] = sample;
      const distance = (point.x - x) ** 2 + (point.y - y) ** 2;
      if (distance < best) {
        nearest = index;
        best = distance;
      }
    });
    selectSample(nearest);
  });
  controls.slider.addEventListener("input", () => selectSample(controls.slider.valueAsNumber));
  provenance(metadata);
  new ResizeObserver(() => {
    if (!activity || byId("workspace").hidden) return;
    plots.forEach(drawPlot);
    selectSample(selectedIndex);
  }).observe(controls.plots);
}

byId("provenance-button").addEventListener("click", () => byId("provenance-dialog").showModal());
