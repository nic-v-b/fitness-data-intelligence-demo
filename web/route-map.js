"use strict";

let geographicView;
let leafletLoad;
let mapRevision = 0;
let offlinePreferred = false;

function geographicMarker(index) {
  geographicView?.marker(index);
}

function leafletLibrary() {
  if (!leafletLoad) {
    const css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = "/leaflet.css";
    const script = document.createElement("script");
    script.src = "/leaflet.js";
    leafletLoad = Promise.all([css, script].map((node) => new Promise((resolve, reject) => {
      node.addEventListener("load", resolve, { once: true });
      node.addEventListener("error", reject, { once: true });
      document.head.append(node);
    }))).then(() => window.L).catch((error) => {
      css.remove();
      script.remove();
      leafletLoad = null;
      throw error;
    });
  }
  return leafletLoad;
}

function geographicPoint(point) {
  return Array.isArray(point) && point.length === 2 && point.every(Number.isFinite)
    && Math.abs(point[0]) <= 85.051129 && Math.abs(point[1]) <= 180;
}

function segmentedCoordinates(detail) {
  const pieces = [[]];
  for (const [i, point] of (detail.positions || []).entries()) {
    const valid = geographicPoint(point);
    if (pieces.at(-1).length && (!valid || detail.activity.samples[i].route_break_before)) pieces.push([]);
    if (valid) pieces.at(-1).push(point);
  }
  return pieces.filter((piece) => piece.length > 1);
}

function displayMap(satellite) {
  byId("route").toggleAttribute("hidden", satellite);
  const holder = byId("leaflet-route");
  holder.removeAttribute("data-loading");
  holder.hidden = !satellite;
  holder.parentElement.dataset.renderer = satellite ? "satellite" : "offline";
}

function stopGeographicMap() {
  mapRevision++;
  geographicView?.remove();
  geographicView = null;
  displayMap(false);
}

function configureRouteMap(detail, options, peers, load) {
  stopGeographicMap();
  const revision = mapRevision;
  const bar = byId("map-controls");
  const holder = byId("leaflet-route");
  const trace = segmentedCoordinates(detail);
  const available = options.leaflet && options.satellite && trace.length > 0;
  const status = html("span", "map-status", detail.positions ? "Offline route trace." : "Fictional route · offline.");
  status.setAttribute("role", "status");
  bar.replaceChildren();
  let historical = null, selectionRevision = 0, attempt = 0;
  if (peers.length) {
    const label = html("label", null, "Historical overlay");
    const select = html("select");
    select.append(new Option("None", ""), ...peers.map((peer) => new Option(activityLabel(peer), peer.id)));
    label.append(select);
    bar.append(label);
    select.addEventListener("change", async () => {
      const serial = ++selectionRevision;
      try {
        const next = select.value ? await load(select.value) : null;
        if (revision !== mapRevision || serial !== selectionRevision) return;
        historical = next;
        historyOverlay = historical?.activity || null;
        renderRoute();
        geographicView?.overlay(historical);
      } catch {
        if (revision === mapRevision) status.textContent = "The historical route could not be loaded.";
      }
    });
  }
  bar.append(status);
  if (!available) return;

  const toggle = html("div", "segmented small satellite-toggle");
  toggle.setAttribute("role", "group");
  toggle.setAttribute("aria-label", "Map background");
  const satellite = html("button", null, "Satellite");
  const offline = html("button", null, "Offline");
  for (const button of [satellite, offline]) button.type = "button";
  toggle.append(satellite, offline);
  bar.prepend(toggle);
  const privacy = html("p", "map-status satellite-privacy",
    "Satellite imagery requests send the visible area and zoom to Mapbox.");
  bar.append(privacy);

  function setButtons(showSatellite) {
    satellite.setAttribute("aria-pressed", String(showSatellite));
    offline.setAttribute("aria-pressed", String(!showSatellite));
  }

  function restore(message) {
    attempt++;
    geographicView?.remove();
    geographicView = null;
    displayMap(false);
    setButtons(false);
    status.textContent = message;
  }

  async function open() {
    if (geographicView) return;
    const ticket = ++attempt;
    const current = () => revision === mapRevision && ticket === attempt;
    status.textContent = "Loading satellite imagery…";
    let map;
    try {
      const L = await leafletLibrary();
      if (!current()) return;
      // Keep the SVG visible while Leaflet lays out its first tiles.
      holder.setAttribute("data-loading", "");
      holder.hidden = false;
      map = L.map(holder, { maxZoom: 19, scrollWheelZoom: false });
      map.attributionControl.setPrefix(false);
      const outline = L.polyline(trace, { color: "#142c3c", weight: 7, opacity: .9, smoothFactor: 0 }).addTo(map);
      const bounds = outline.getBounds();
      let fitting = true, userMoved = false, tileTimeout;
      function fit() {
        fitting = true;
        map.invalidateSize({ animate: false });
        map.fitBounds(bounds, { padding: [24, 24], maxZoom: 16, animate: false });
        fitting = false;
      }
      fit();
      map.on("dragstart zoomstart", () => { if (!fitting) userMoved = true; });
      const resize = new ResizeObserver(() => {
        if (!current() || !holder.clientWidth) return;
        if (userMoved) map.invalidateSize({ animate: false, debounceMoveend: true });
        else fit();
      });
      resize.observe(holder);
      const overlay = L.layerGroup().addTo(map);
      const painted = L.layerGroup().addTo(map);
      map.createPane("selection").style.zIndex = 520;
      const marker = L.circleMarker([0, 0], {
        pane: "selection", radius: 6, color: "#16334b", fillColor: "#fff", fillOpacity: 1, weight: 2,
        interactive: false,
      });
      geographicView = {
        remove() { clearTimeout(tileTimeout); resize.disconnect(); map.remove(); holder.replaceChildren(); },
        marker(i) {
          const p = detail.positions[i];
          if (geographicPoint(p)) marker.setLatLng(p).addTo(map);
          else marker.remove();
        },
        overlay(reference) {
          overlay.clearLayers();
          if (reference) overlay.addLayer(L.polyline(segmentedCoordinates(reference), {
            color: "#ffe392", dashArray: "6 8", weight: 5, interactive: false, smoothFactor: 0,
          }));
          this.repaint();
        },
        repaint() {
          painted.clearLayers();
          const { signal, palette } = routePalette();
          const groups = new Map();
          const bins = 16;
          const step = (palette.max - palette.min) / bins;
          for (let i = 1; i < detail.positions.length; i++) {
            const [a, b] = [detail.positions[i - 1], detail.positions[i]];
            const [left, right] = detail.activity.samples.slice(i - 1, i + 1);
            if (!geographicPoint(a) || !geographicPoint(b) || right.route_break_before) continue;
            const x = valueOf(left, signal), y = valueOf(right, signal);
            const midpoint = x === null || y === null ? null
              : palette.min + Math.round(((x + y) / 2 - palette.min) / step) * step;
            const color = segmentColor(midpoint, midpoint, palette);
            if (!groups.has(color)) groups.set(color, []);
            groups.get(color).push([a, b]);
          }
          for (const [color, lines] of groups) painted.addLayer(L.polyline(lines, {
            color, weight: 4, opacity: 1, interactive: false, smoothFactor: 0,
          }));
        },
      };
      outline.on("click", (event) => {
        const point = map.latLngToLayerPoint(event.latlng);
        let nearest = Infinity, index = selectedIndex;
        detail.positions.forEach((coordinate, i) => {
          if (!geographicPoint(coordinate)) return;
          const distance = point.distanceTo(map.latLngToLayerPoint(coordinate));
          if (distance < nearest) { nearest = distance; index = i; }
        });
        selectSample(index);
      });
      geographicView.overlay(historical);
      geographicView.marker(selectedIndex);
      const base = L.tileLayer(`https://api.mapbox.com/v4/mapbox.satellite/{z}/{x}/{y}@2x.jpg90?access_token=${encodeURIComponent(options.satellite)}`, {
        maxZoom: 19, maxNativeZoom: 19, referrerPolicy: "no-referrer",
        attribution: '<a href="https://www.mapbox.com/about/maps/">© Mapbox</a> · <a href="https://www.openstreetmap.org/copyright">© OpenStreetMap</a> · <a href="https://www.mapbox.com/map-feedback/">Improve this map</a>',
      });
      let loaded = false, failures = 0;
      const fail = () => { if (current()) restore("Satellite tiles unavailable. Showing the offline route."); };
      base.on("loading", () => {
        loaded = false;
        failures = 0;
        clearTimeout(tileTimeout);
        tileTimeout = setTimeout(() => { if (!loaded) fail(); }, 8500);
      });
      base.on("tileload", () => {
        if (!current()) return;
        loaded = true;
        displayMap(true);
        setButtons(true);
        status.textContent = "Satellite imagery · recorded GPS route.";
      });
      base.on("tileerror", () => { failures++; });
      base.on("load", () => {
        clearTimeout(tileTimeout);
        if (!loaded && failures) {
          // Leaflet completes its tile callback after emitting this event.
          queueMicrotask(() => { if (!loaded) fail(); });
        }
      });
      const logo = html("a", "mapbox-mark");
      logo.href = "https://www.mapbox.com/about/maps/";
      const img = html("img");
      img.src = "/mapbox-logo";
      img.alt = "Mapbox";
      logo.append(img);
      holder.append(logo);
      base.addTo(map);
    } catch {
      if (!current()) return;
      if (map && !geographicView) { map.remove(); holder.replaceChildren(); }
      restore("Satellite map unavailable. Showing the offline route.");
    }
  }
  offline.onclick = () => {
    offlinePreferred = true;
    restore("Offline route trace.");
  };
  satellite.onclick = () => {
    offlinePreferred = false;
    return open();
  };
  setButtons(false);
  if (!offlinePreferred) open();
}
