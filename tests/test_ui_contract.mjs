import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const html = readFileSync(new URL("../web/index.html", import.meta.url), "utf8");
const css = readFileSync(new URL("../web/styles.css", import.meta.url), "utf8");
const app = readFileSync(new URL("../web/app.js", import.meta.url), "utf8");
const route = readFileSync(new URL("../web/route-map.js", import.meta.url), "utf8");
const portfolio = readFileSync(new URL("../web/portfolio.js", import.meta.url), "utf8");

test("the redesigned Explorer retains every recorded-map and FIT control", () => {
  for (const id of ["leaflet-route", "route", "route-subtitle", "dataset-label",
    "route-metric", "map-controls", "sample-index", "fit-checks", "fit-check-fields"]) {
    assert.match(html, new RegExp('id="' + id + '"'), id + " must exist once");
    assert.equal(html.split('id="' + id + '"').length - 1, 1, id + " must be unique");
  }
  assert.match(html, /<div id="leaflet-route" hidden/);
  assert.match(html, /id="main-content"/);
  assert.match(html, /class="skip-link"/);
});

test("satellite uses a single map area, with accessible offline fallback", () => {
  assert.equal(html.split('class="route-map activity-map"').length - 1, 1);
  assert.match(css, /#leaflet-route\s*\{[^}]*position:\s*absolute/);
  assert.match(css, /#route\[hidden\][^}]*display:\s*none/);
  assert.match(css, /\.activity-map\s*\{[^}]*min-height:\s*clamp/);
  assert.match(route, /configureRouteMap/);
  assert.match(route, /Satellite imagery requests send the visible area and zoom to Mapbox/);
  assert.match(route, /Mapbox.*OpenStreetMap/);
});

test("recorded GPS and privacy semantics survive the visual transfer", () => {
  assert.match(app, /metadata\.dataset_type === "private-fit-preview"/);
  assert.match(app, /metadata\.dataset_type === "recorded-visible-review"/);
  assert.match(app, /geographicView\?\.repaint\(\)/);
  assert.match(portfolio, /configureRouteMap\(detail, agenda\.map, historyPeers, fetchDetail\)/);
  assert.match(app, /json-export"\)\.hidden = privatePreview \|\| recordedReview/);
});

test("route colours reference the approved CSS palette", () => {
  assert.match(app, /getComputedStyle\(controls\.route\)/);
  for (const name of ["--route-speed-low", "--route-speed-mid", "--route-speed-high",
    "--route-heart-low", "--route-heart-mid", "--route-heart-high"]) {
    assert.ok(css.includes(name), "Missing CSS colour "+name);
  }
});
