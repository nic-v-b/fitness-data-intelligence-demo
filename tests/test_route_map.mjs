import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { setImmediate as settle } from "node:timers/promises";
import { runInNewContext } from "node:vm";

const script = readFileSync(new URL("../web/route-map.js", import.meta.url), "utf8");

const element = (label = "") => ({
  textContent: label, children: [], attrs: {}, parentElement: { dataset: {} },
  append(...nodes) { this.children.push(...nodes); },
  prepend(...nodes) { this.children.unshift(...nodes); },
  replaceChildren() { this.children = []; },
  setAttribute(key, value) { this.attrs[key] = value; },
  removeAttribute(key) { delete this.attrs[key]; },
  toggleAttribute(key, enabled) { this.attrs[key] = enabled; },
});
const mapElements = () => Object.fromEntries(["route", "leaflet-route", "map-controls"].map((id) => [id, element()]));

test("retained satellite geometry keeps the same breaks as the offline renderer", () => {
  const context = {};
  runInNewContext(script, context);
  const retained = [[1, 2], [1, 2.01], [1.03, 2.05], [1.04, 2.05]];
  const detail = { positions: retained, activity: { samples: [{}, {}, { route_break_before: true }, {}] } };
  const rendered = context.segmentedCoordinates(detail);
  assert.deepEqual(JSON.parse(JSON.stringify(rendered)), [retained.slice(0, 2), retained.slice(2)]);
});

test("satellite loads automatically and retains the chosen map preference across recordings", async () => {
  const dom = mapElements();
  let imageryAttempts = 0;
  const context = {
    byId: (name) => dom[name], html: (tag, style, label) => element(label),
    tryImagery: async () => { imageryAttempts++; throw new Error("Leaflet unavailable"); },
  };
  runInNewContext(script + "\nleafletLibrary = tryImagery;", context);
  const detail = { positions: [[45, -73], [45.001, -73]], activity: { samples: [{}, {}] } };
  const options = { leaflet: true, satellite: "pk.test.fixture" };
  const bar = dom["map-controls"];
  context.configureRouteMap(detail, { leaflet: false }, []);
  assert.equal(bar.children.length, 1);
  assert.equal(imageryAttempts, 0);
  context.configureRouteMap(detail, options, []);

  const offline = bar.children[0].children[1];
  const [, status, notice] = bar.children;
  assert.equal(imageryAttempts, 1);
  assert.equal(dom["leaflet-route"].hidden, true);
  assert.equal(offline.attrs["aria-pressed"], "true");
  assert.match(notice.textContent, /visible area and zoom to Mapbox/);

  await settle();
  assert.equal(dom.route.attrs.hidden, false);
  assert.match(status.textContent, /Showing the offline route/);
  context.configureRouteMap(detail, options, []);
  assert.equal(imageryAttempts, 2, "fallback preserves the satellite preference on activity switch");
  bar.children[0].children[1].onclick();
  context.configureRouteMap(detail, options, []);
  assert.equal(imageryAttempts, 2, "selecting Offline preserves the manual preference");
  await bar.children[0].children[0].onclick();
  assert.equal(imageryAttempts, 3, "selecting Satellite retries");
  assert.equal(dom["leaflet-route"].hidden, true);
});

test("satellite requests tiles for retained sections and restores SVG after tile failure", async () => {
  const dom = mapElements();
  const calls = {};
  const events = {};
  const layer = () => ({ addTo() { return this; }, on() {}, getBounds() { return {}; },
    setLatLng() { return this; }, addLayer() {}, clearLayers() {} });
  const map = { attributionControl: { setPrefix() {} }, invalidateSize() {}, fitBounds() {},
    on() {}, createPane() { return { style: {} }; }, remove() { calls.removed = true; } };
  const context = {
    byId: (id) => dom[id], html: (tag, style, label) => element(label),
    routePalette: () => ({ signal: "speed", palette: { min: 0, max: 10 } }),
    valueOf: () => 4, segmentColor: () => "blue", selectedIndex: 0,
    ResizeObserver: class { observe() {} disconnect() {} },
    setTimeout: () => 1, clearTimeout() {}, queueMicrotask,
    leaflet: {
      map: () => map, polyline: (points) => { calls.line ??= points; return layer(); },
      layerGroup: layer, circleMarker: layer,
      tileLayer: (url, options) => {
        calls.tileUrl = url;
        calls.options = options;
        return { on(name, callback) { events[name] = callback; }, addTo() {} };
      },
    },
  };
  runInNewContext(script + "\nleafletLibrary = async () => leaflet;", context);
  const positions = [[1, 2], [1, 2.01], [1.03, 2.05], [1.04, 2.05]];
  context.configureRouteMap(
    { positions, activity: { samples: [{}, {}, { route_break_before: true }, {}] } },
    { leaflet: true, satellite: "pk.test.fixture" }, [],
  );
  await settle();
  assert.deepEqual(JSON.parse(JSON.stringify(calls.line)), [positions.slice(0, 2), positions.slice(2)]);
  assert.equal(calls.tileUrl, "https://api.mapbox.com/v4/mapbox.satellite/{z}/{x}/{y}@2x.jpg90?access_token=pk.test.fixture");
  assert.equal(calls.options.referrerPolicy, "no-referrer");
  assert.match(calls.options.attribution, /Mapbox.*OpenStreetMap/);
  assert.equal(dom.route.attrs.hidden, false);
  assert.equal(dom["leaflet-route"].attrs["data-loading"], "");
  events.loading();
  events.tileload();
  assert.equal(dom.route.attrs.hidden, true);
  assert.equal(dom["leaflet-route"].attrs["data-loading"], undefined);
  events.loading();
  events.tileerror();
  events.load();
  await settle();
  assert.equal(calls.removed, true);
  assert.equal(dom["leaflet-route"].hidden, true);
  assert.equal(dom.route.attrs.hidden, false);
});
