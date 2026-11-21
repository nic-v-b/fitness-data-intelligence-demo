"use strict";

let mapRevision = 0;

function resetRouteOverlay() {
  mapRevision++;
}

function configureRouteOverlay(peers, load) {
  const revision = ++mapRevision;
  const bar = byId("map-controls");
  const status = html("span", "map-status");
  status.setAttribute("role", "status");
  bar.replaceChildren();
  if (!peers.length) return;
  let selectionRevision = 0;

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
      historyOverlay = next?.activity || null;
      renderRoute();
      status.textContent = "";
    } catch {
      if (revision === mapRevision && serial === selectionRevision) status.textContent = "The historical route could not be loaded.";
    }
  });
  bar.append(status);
}
