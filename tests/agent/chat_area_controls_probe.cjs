// Execute the real controller with a minimal Leaflet/DOM boundary.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const token = "a".repeat(64);
const square = { type: "Polygon", coordinates: [[[110, 15], [112, 15], [112, 17], [110, 17], [110, 15]]] };
const clone = (value) => JSON.parse(JSON.stringify(value));

async function setup(active = null) {
  const elements = new Map();
  const el = (name) => {
    if (!elements.has(name)) elements.set(name, { value: "custom", textContent: "", disabled: false,
      events: {}, addEventListener(event, fn) { this.events[event] = fn; } });
    return elements.get(name);
  };
  const root = { style: {}, innerHTML: "", querySelector(selector) {
    return el(selector.match(/data-area="([^"]+)"/)[1]);
  }, querySelectorAll() { return [...elements.values()]; } };
  const layer = (geometry) => { map.shape = clone(geometry); return { addTo() { return this; }, getBounds() { return { isValid: () => true }; } }; };
  const map = { events: {}, fits: 0, on(name, fn) { this.events[name] = fn; },
    removeLayer() { this.shape = null; }, fitBounds() { this.fits++; } };
  const L = { control: () => ({ addTo() { this.onAdd(); } }), geoJSON: layer, polyline: layer,
    DomUtil: { create: () => root }, DomEvent: { disableClickPropagation() {}, disableScrollPropagation() {} } };
  const calls = [];
  let saved = { revision: 0, active_area: clone(active) }, conflict = false;
  const fetch = async (url, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : null;
    calls.push({ url, body, method: options.method || "GET" });
    if (url.startsWith("/query-areas/")) return { ok: true, json: async () => ({ geometry: square }) };
    if (options.method === "PUT") {
      if (conflict || body.expected_revision !== saved.revision) return { ok: false, json: async () => ({ detail: "Conflict: reload saved area" }) };
      saved = { revision: saved.revision + 1, active_area: clone(body.active_area) };
    }
    return { ok: true, json: async () => clone(saved) };
  };
  const intervals = new Map();
  const context = { window: { location: { search: `?map_session=${token}` } }, URLSearchParams,
    AbortController, setTimeout, clearTimeout, fetch,
    setInterval(fn, delay) { assert.equal(delay, 2000); intervals.set(fn, fn); return fn; },
    clearInterval(id) { intervals.delete(id); } };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(process.argv[2], "utf8") + "\nglobalThis.controls = ChatAreaControls;", context);
  await context.controls.attach({ map, L, document: {} });
  return { el, calls, click: (name) => el(name).events.click(),
    point: (lng, lat) => map.events.click({ latlng: { lng, lat } }),
    saved: () => clone(saved), setConflict: (value) => { conflict = value; }, map,
    remote(area) { saved = { revision: saved.revision + 1, active_area: clone(area) }; },
    async poll() { for (const fn of intervals.values()) await fn(); }, intervals };
}

(async () => {
  const app = await setup();
  assert.equal(app.calls.length, 1);
  await app.click("confirm");
  assert.equal(app.calls.length, 1, "Cannot confirm an empty selection");
  app.click("rectangle"); app.point(110, 15); app.point(112, 17);
  assert.equal(app.saved().active_area, null, "Drawing is not confirmation");
  await app.click("confirm");
  assert.deepEqual(app.saved().active_area, square);
  assert.equal(app.saved().revision, 1);
  app.click("polygon"); app.point(110, 15); app.point(112, 15);
  app.click("finish"); await app.click("confirm");
  assert.equal(app.calls.length, 2, "Unfinished polygon never overwrites confirmed area");
  assert.deepEqual(app.saved().active_area, square);
  app.point(111, 17); app.click("finish");
  app.setConflict(true);
  await app.click("confirm");
  assert.deepEqual(app.saved().active_area, square);
  assert.match(app.el("status").textContent, /reload saved area/);
  app.setConflict(false);
  await app.click("reload");
  await app.click("clear");
  assert.equal(app.saved().active_area, null);
  app.el("choice").value = "bien_dong";
  await app.el("choice").events.change();
  assert.equal(app.saved().active_area, null, "Choosing a preset is still a draft");
  await app.click("confirm");
  assert.deepEqual(app.saved().active_area, { type: "preset", key: "bien_dong" });
  assert.ok(app.calls.every((call) => !call.url.endsWith("/answer")), "No separate agent run from map");
  const restored = await setup(square);
  assert.match(restored.el("status").textContent, /chat/);
  const centered = await setup();
  centered.el("choice").value = "du_lam";
  centered.el("radius").value = "";
  await centered.el("choice").events.change();
  await centered.click("confirm");
  assert.equal(centered.saved().active_area, null, "No default radius");
  centered.el("radius").value = "20";
  await centered.el("radius").events.change();
  assert.equal(centered.calls.at(-1).url, "/query-areas/du_lam?radius_nm=20");
  await centered.click("confirm");
  assert.deepEqual(centered.saved().active_area, square, "Store computed geometry for chat follow-ups");
  const synced = await setup();
  synced.remote(square);
  await synced.poll();
  assert.deepEqual(synced.map.shape, square, "Chat selection appears on the mounted map");
  assert.equal(synced.map.fits, 1);
  await synced.poll();
  assert.equal(synced.map.fits, 1, "Unchanged revisions preserve the viewport");
  synced.click("polygon"); synced.point(113, 16); synced.point(114, 16);
  const draft = clone(synced.map.shape);
  synced.remote({ type: "preset", key: "vinh_bac_bo" });
  await synced.poll();
  assert.deepEqual(synced.map.shape, draft, "A remote selection never discards local draft vertices");
  assert.match(synced.el("status").textContent, /Tải vùng đã lưu/);
  synced.point(114, 17); synced.click("finish"); await synced.click("confirm");
  assert.match(synced.el("status").textContent, /Conflict/, "A stale draft cannot overwrite chat selection");
  await synced.click("reload");
  assert.equal(synced.el("choice").value, "vinh_bac_bo");
  synced.remote(null); await synced.poll();
  assert.equal(synced.map.shape, null, "Remote clear removes the selected area");
  synced.map.events.unload();
  assert.equal(synced.intervals.size, 0, "Unmounting the map stops polling");
  console.log("Chat area drawing/confirm/clear/restore/conflict probe passed");
})().catch((error) => { console.error(error); process.exit(1); });
