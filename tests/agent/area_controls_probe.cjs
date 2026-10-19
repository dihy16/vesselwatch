// Exercise drawing and the real browser helper without a network or a classifier.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync(process.argv[2], "utf8");
const square = { type: "Polygon", coordinates: [[[110, 15], [112, 15], [112, 17], [110, 17], [110, 15]]] };

function setup(config = {}) {
  const elements = new Map();
  const el = (id) => {
    if (!elements.has(id)) elements.set(id, { value: "", textContent: "", hidden: true, disabled: false,
      events: {}, addEventListener(name, handler) { this.events[name] = handler; } });
    return elements.get(id);
  };
  const map = { events: {}, on(name, handler) { this.events[name] = handler; }, removeLayer() {}, fitBounds() {} };
  const layers = [];
  const layer = (value) => {
    const result = { value, addTo() { layers.push(this); return this; }, getBounds: () => ({ isValid: () => false }) };
    return result;
  };
  const L = { geoJSON: layer, polyline: layer };
  const calls = [];
  const rows = [{ observation_id: "one" }];
  let failAnswer = false, shown = null;
  const fetch = async (url, options) => {
    const body = options.body ? JSON.parse(options.body) : undefined;
    calls.push({ url, body });
    if (url.startsWith("/query-areas/")) return { ok: true, json: async () => ({ geometry: square, properties: { name: "Biển Đông" } }) };
    if (url.endsWith("/answer")) return failAnswer ?
      { ok: false, json: async () => ({ detail: "Agent unavailable" }) } :
      { ok: true, json: async () => ({ answer: "42 detections" }) };
    return { ok: true, json: async () => ({ area_id: "a".repeat(32), total: 42,
      possible_aircraft_carrier_count: 3, ships: rows, map_url: "/area-queries/result" }) };
  };
  const context = { fetch, AbortController, setTimeout, clearTimeout };
  vm.createContext(context);
  vm.runInContext(source + "\nglobalThis.controls = AreaControls;", context);
  context.controls.attach({ map, L, document: { getElementById: el },
    config: { prepare_url: "/area-queries", query: { observed_from: "2026-10-01", classification: "aircraft_carrier" }, ...config },
    onResults: (result) => { shown = result; } });
  return { el, calls, layers, map, click: (id) => el(id).events.click(),
    point: (lng, lat) => map.events.click({ latlng: { lng, lat } }),
    setFail: (value) => { failAnswer = value; }, getShown: () => shown };
}

(async () => {
  const app = setup();
  await app.click("area-confirm");
  assert.equal(app.calls.length, 0, "Cannot query before drawing");
  app.click("area-rectangle");
  app.point(110, 15); app.point(112, 17);
  await app.click("area-confirm");
  assert.deepEqual(app.calls[0].body.polygon, square);
  assert.equal(app.calls[0].body.classification, "aircraft_carrier");
  assert.equal(app.calls[1].url, `/area-queries/${"a".repeat(32)}/answer`);
  assert.ok(app.el("area-status").textContent.includes("42"), "Use server total, not visible marker count");
  assert.equal(app.el("area-answer").textContent, "42 detections");
  assert.equal(app.getShown().length, 1);

  app.click("area-polygon");
  app.point(110, 15); app.point(112, 15);
  app.click("area-finish");
  await app.click("area-confirm");
  assert.equal(app.calls.length, 2, "Two vertices cannot be confirmed");
  app.point(111, 17); app.click("area-finish");
  app.setFail(true);
  await app.click("area-confirm");
  assert.equal(app.calls[2].body.polygon.coordinates[0].length, 4);
  assert.equal(app.el("area-answer").textContent, "Agent unavailable");
  assert.equal(app.el("area-retry").hidden, false);
  assert.ok(app.el("area-status").textContent.includes("42"), "Agent failure preserves authoritative counts");
  app.setFail(false);
  await app.click("area-retry");
  assert.equal(app.el("area-answer").textContent, "42 detections");

  app.el("area-choice").value = "bien_dong";
  await app.el("area-choice").events.change();
  await app.click("area-confirm");
  const named = app.calls.at(-2).body;
  assert.equal(named.area_name, "Biển Đông");
  assert.equal(named.polygon, undefined, "Saved boundaries use names, never substitute a user polygon");

  app.click("area-clear");
  const previousCalls = app.calls.length;
  await app.click("area-confirm");
  assert.equal(app.calls.length, previousCalls);
  assert.equal(app.el("area-reference").value, "");

  const selection = setup({ confirm_url: "/area-queries/pending/confirm" });
  selection.click("area-rectangle"); selection.point(110, 15); selection.point(112, 17);
  await selection.click("area-confirm");
  assert.equal(selection.calls[0].url, "/area-queries/pending/confirm");
  assert.deepEqual(selection.calls[0].body, { polygon: square });
  console.log("Area drawing and agent handoff probe passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
