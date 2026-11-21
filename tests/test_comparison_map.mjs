import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { runInNewContext } from "node:vm";

test("coincident running markers retain both series colors without moving the points", () => {
  const build = (name, attrs = {}) => ({
    name, attrs, children: [],
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
  });
  const context = { byId: () => null, svg: build, gridStep: () => 50 };
  const script = readFileSync(new URL("../web/comparative.js", import.meta.url), "utf8");
  runInNewContext(script, context);
  const graph = build("svg");
  const trace = [[0, 10, 0], [400, 10, 400]];
  const update = context.drawComparisonMap(graph, {
    routes: [[trace], [trace]], shared: trace,
    bins: [{ values: [{ point: [10, 200] }, { point: [10, 200] }] },
      { values: [{ point: [5, 190] }, { point: [50, 200] }] }],
  }, () => {});
  const marker = graph.children.find(node => node.attrs.class === "comparison-marker");
  update(0);
  const [a, b] = marker.children.map(node => node.attrs);
  assert.equal(a.cx, b.cx);
  assert.equal(a.cy, b.cy);
  assert.notEqual(a.fill, b.fill);
  assert.ok(a.r > b.r, "both colors should remain visible");
  update(1);
  assert.equal(marker.children[0].attrs.r, marker.children[1].attrs.r);
});
