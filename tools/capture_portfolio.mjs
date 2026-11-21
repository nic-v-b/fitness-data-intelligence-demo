import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { setTimeout as wait } from "node:timers/promises";

// Run the public app with `python app.py serve --port 8130` before capturing.
const origin = "http://127.0.0.1:8130";
const portfolio = await fetch(`${origin}/api/portfolio`).then((response) => {
  assert.ok(response.ok, "Start the public demo on port 8130");
  return response.json();
});
assert.equal(portfolio.metadata.dataset_type, "synthetic", "Capture requires public synthetic data");
assert.deepEqual(portfolio.map, { leaflet: false, satellite: null });

const output = resolve("artifacts/portfolio-media");
await mkdir(output, { recursive: true });
const profile = await mkdtemp(resolve("artifacts/portfolio-chrome-"));
const chrome = process.argv[2] || "C:/Program Files/Google/Chrome/Application/chrome.exe";
const browser = spawn(chrome, [
  "--headless=new", "--no-first-run", "--disable-background-networking", "--disable-component-update",
  "--remote-debugging-pipe", `--user-data-dir=${profile}`, "about:blank",
], { windowsHide: true, stdio: ["ignore", "ignore", "inherit", "pipe", "pipe"] });
const pending = new Map();
const runtimeErrors = [];
const externalRequests = [];
let id = 0, buffer = "", sessionId;
const cancel = (error) => {
  for (const callback of pending.values()) callback(null, error);
};
browser.on("error", cancel);
browser.on("exit", (code) => cancel(new Error(`Chrome exited with status ${code}`)));
browser.stdio[3].on("error", cancel);
function cdp(method, params = {}, session = sessionId) {
  return new Promise((resolveCommand, reject) => {
    const command = ++id;
    const finish = (result, error) => {
      clearTimeout(timer);
      pending.delete(command);
      if (error) reject(error);
      else resolveCommand(result);
    };
    const timer = setTimeout(() => finish(null, new Error(`${method} timed out`)), method === "Target.getTargets" ? 25000 : 10000);
    pending.set(command, finish);
    browser.stdio[3].write(JSON.stringify({ id: command, method, params, sessionId: session }) + "\0");
  });
}
browser.stdio[4].setEncoding("utf8");
browser.stdio[4].on("data", (chunk) => {
  const messages = (buffer + chunk).split("\0");
  buffer = messages.pop();
  for (const raw of messages) {
    const message = JSON.parse(raw);
    if (message.id) pending.get(message.id)?.(message.result, message.error && new Error(message.error.message));
    if (message.method === "Runtime.exceptionThrown") runtimeErrors.push(message.params.exceptionDetails.text);
    if (message.method === "Fetch.requestPaused") {
      const { request, requestId } = message.params;
      const local = new URL(request.url).origin === origin;
      if (!local) externalRequests.push(new URL(request.url).origin);
      cdp(local ? "Fetch.continueRequest" : "Fetch.failRequest",
        local ? { requestId } : { requestId, errorReason: "BlockedByClient" }).catch(cancel);
    }
  }
});

async function evaluate(expression) {
  const { result, exceptionDetails } = await cdp("Runtime.evaluate", {
    expression, returnByValue: true, awaitPromise: true,
  });
  if (exceptionDetails) throw new Error(exceptionDetails.exception?.description || exceptionDetails.text);
  return result.value;
}
async function ready(condition) {
  for (let i = 0; i < 60; i++) {
    if (await evaluate(condition)) return;
    await wait(100);
  }
  throw new Error(`Page did not reach expected state: ${condition}`);
}
const span = (id) => `document.querySelector('${id}')`;
async function capture(name, selector = null) {
  await evaluate(selector ? `${span(selector)}.scrollIntoView()` : "scrollTo(0, 0)");
  await evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve(true))))");
  const { data } = await cdp("Page.captureScreenshot", { format: "png" });
  await writeFile(resolve(output, `${name}.png`), Buffer.from(data, "base64"));
}

try {
  const { targetInfos } = await cdp("Target.getTargets");
  ({ sessionId } = await cdp("Target.attachToTarget", { targetId: targetInfos.find((x) => x.type === "page").targetId,
    flatten: true }));
  await cdp("Runtime.enable");
  await cdp("Page.enable");
  await cdp("Fetch.enable", { patterns: [{ urlPattern: "http*://*" }] });
  const viewport = (width, height, mobile) =>
    cdp("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile });
  await viewport(1440, 1200, false);
  await cdp("Page.navigate", { url: origin });
  await ready(`${span("#history-workspace a.activity-link")} !== null`);
  assert.match(await evaluate("document.querySelector('#history-workspace').innerText"), /Fictional demonstration/i);
  await capture("activity-history");
  await capture("frame-01");
  await evaluate(`${span('a[href="#explorer/ridge-8"]')}.click()`);
  await ready(`${span("#dataset-intro")}?.textContent.includes('6 km Demo Run 08') && !!${span(".run-comparison-controls select")}`);
  await capture("running-explorer");
  const setSlider = (selector, fraction) => evaluate(`(() => {
    const slider = ${span(selector)};
    slider.value = Math.round(slider.max * ${fraction});
    slider.dispatchEvent(new Event('input'));
  })()`);
  const cursor = () => evaluate(`${span("#map-cursor")}.dataset.sampleIndex`);
  const before = await cursor();
  const chartCursor = () => evaluate(`${span("#plots .cursor-line")}.getAttribute('x1')`);
  const chartBefore = await chartCursor();
  for (const [frame, fraction] of [[2, .28], [3, .42], [4, .56], [5, .70]]) {
    await setSlider("#sample-index", fraction);
    await capture(`frame-0${frame}`);
  }
  assert.notEqual(await cursor(), before, "Slider should move the route marker");
  assert.notEqual(await chartCursor(), chartBefore, "Slider should move the chart cursor");
  await evaluate(`(() => { const select = ${span(".run-comparison-controls select")};
    select.value = 'ridge-2'; select.dispatchEvent(new Event('change')); })()`);
  await ready(`!!${span(".run-comparison-summary")} && ${span(".run-comparison-summary")}.innerText.includes('6 km Demo Run 02')`);
  const comparison = "#comparative-workspace";
  const sharedCursor = () => evaluate(`${span(".comparison-marker circle")}.getAttribute('cx')`);
  const sharedBefore = await sharedCursor();
  await capture("same-route-comparison", comparison);
  for (const [frame, fraction] of [[6, .25], [7, .48], [8, .75]]) {
    await setSlider("#comparison-distance", fraction);
    await capture(`frame-0${frame}`, comparison);
  }
  assert.notEqual(await sharedCursor(), sharedBefore, "Shared-distance slider should move the comparison map marker");
  await evaluate("location.hash = '#explorer/foothills'");
  await ready(`${span("#dataset-intro")}?.textContent.includes('35 km Demo Ride 01') && !!${span(".climb-highlight button")}`);
  assert.equal(await evaluate(`${span("#leaflet-route")}.hidden`), true);
  await capture("cycling-explorer");
  for (const [page, heading, name] of [["profile", "Fitness Profile", "fitness-profile"],
    ["planner", "Training Planner", "training-planner"]]) {
    await evaluate(`location.hash = '#${page}'`);
    await ready(`${span(`#${page}-workspace:not([hidden]) h1`)}?.textContent === '${heading}'`);
    await capture(name);
  }
  await viewport(390, 844, true);
  for (const view of ["history", "explorer/ridge-8", "explorer/foothills", "profile", "planner"]) {
    await evaluate(`location.hash = '#${view}'`);
    const [page, activityId] = view.split("/");
    const panel = activityId ? "#workspace" : `#${page}-workspace`;
    await ready(`!!${span(`${panel}:not([hidden])`)}${activityId ? ` && ${span("#activities")}.value === '${activityId}'` : ""}`);
    assert.equal(await evaluate("document.documentElement.scrollWidth <= innerWidth"), true, `${view} mobile width`);
  }
  assert.deepEqual(runtimeErrors, []);
  assert.deepEqual(externalRequests, []);
  console.log("Public desktop captures, interaction checks and mobile widths passed.");
} finally {
  browser.kill();
}
