// One confirmed polygon per chat. This controller never calls a separate agent.
const ChatAreaControls = (() => {
  function attach({ map, L, document }) {
    const session = new URLSearchParams(window.location.search).get("map_session");
    if (!/^[a-f0-9]{64}$/.test(session || "")) return;
    const control = L.control({ position: "topright" });
    let root;
    control.onAdd = () => {
      root = L.DomUtil.create("div", "leaflet-control vesselwatch-chat-area");
      Object.assign(root.style, { background: "white", color: "#18364a", padding: "10px",
        borderRadius: "8px", width: "280px", maxWidth: "65vw", font: "13px sans-serif" });
      root.innerHTML = `<details open><summary><b>Vùng của cuộc chat</b></summary>
        <select data-area="choice" style="width:100%;margin:8px 0">
          <option value="custom">Vùng tùy ý — tự vẽ</option>
          <option value="bien_dong">Biển Đông</option><option value="vinh_bac_bo">Vịnh Bắc Bộ</option>
        </select><div style="display:flex;flex-wrap:wrap;gap:5px">
          <button data-area="rectangle">Vẽ rectangle</button><button data-area="polygon">Vẽ polygon</button>
          <button data-area="finish">Hoàn tất polygon</button><button data-area="confirm">Xác nhận vùng</button>
          <button data-area="clear">Xóa vùng đã lưu</button><button data-area="reload">Tải vùng đã lưu</button>
        </div><p data-area="status" role="status" style="margin-bottom:0">Đang đọc vùng đã lưu…</p></details>`;
      L.DomEvent.disableClickPropagation(root);
      L.DomEvent.disableScrollPropagation(root);
      return root;
    };
    control.addTo(map);
    const el = (name) => root.querySelector(`[data-area="${name}"]`);
    let revision = 0, initialized = false, busy = false, version = 0;
    let mode = null, points = [], geometry = null, layer = null;
    function status(text) { el("status").textContent = text; }
    function setBusy(value) {
      busy = value;
      for (const element of root.querySelectorAll("button,select")) element.disabled = value;
    }
    function paint() {
      if (layer) map.removeLayer(layer);
      layer = geometry ? L.geoJSON(geometry, { style: { color: "#167d9a", weight: 2, fillOpacity: .12 } }).addTo(map)
        : points.length ? L.polyline(points.map(([lng, lat]) => [lat, lng]), { color: "#167d9a" }).addTo(map) : null;
    }
    function fit() {
      if (layer && layer.getBounds().isValid()) map.fitBounds(layer.getBounds(), { padding: [20, 20] });
    }
    async function request(url, options = {}) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 30000);
      try {
        const response = await fetch(url, { ...options, signal: controller.signal, cache: "no-store" });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Không lưu được vùng.");
        return data;
      } finally { clearTimeout(timer); }
    }
    async function loadPreset(key, marker) {
      const feature = await request(`/query-areas/${key}`);
      if (marker !== version) return;
      geometry = feature.geometry; paint(); fit();
    }
    async function reload() {
      if (busy) return;
      const marker = ++version;
      setBusy(true);
      try {
        const saved = await request(`/map-sessions/${session}`);
        revision = saved.revision; initialized = true;
        mode = null; points = []; geometry = null;
        el("choice").value = saved.active_area?.type === "preset" ? saved.active_area.key : "custom";
        if (saved.active_area?.type === "preset") await loadPreset(saved.active_area.key, marker);
        else { geometry = saved.active_area; paint(); if (geometry) fit(); }
        status(saved.active_area ? "Vùng đã lưu. Quay lại chat để hỏi về vùng này." : "Chọn hoặc vẽ một vùng rồi bấm Xác nhận.");
      } catch (error) { status(`Chưa tải được vùng: ${error.message}`); }
      finally { setBusy(false); }
    }
    function begin(kind) {
      if (busy || !initialized) return;
      version++; mode = kind; points = []; geometry = null;
      el("choice").value = "custom"; paint();
      status(kind === "rectangle" ? "Bấm hai góc đối diện. Vùng cũ còn hiệu lực đến khi xác nhận." :
        "Bấm các đỉnh, rồi Hoàn tất polygon. Vùng cũ còn hiệu lực đến khi xác nhận.");
    }
    function finish() {
      if (points.length < 3) { status("Cần ít nhất 3 đỉnh."); return; }
      geometry = { type: "Polygon", coordinates: [[...points, points[0]]] };
      mode = null; paint(); status("Vùng đang vẽ chưa được lưu. Bấm Xác nhận vùng.");
    }
    map.on("click", (event) => {
      if (busy || !mode) return;
      if (points.length >= 200) { status("Tối đa 200 đỉnh."); return; }
      const lng = ((event.latlng.lng + 180) % 360 + 360) % 360 - 180;
      points.push([lng, event.latlng.lat]);
      if (mode === "rectangle" && points.length === 2) {
        const [a, b] = points;
        points = [a, [b[0], a[1]], b, [a[0], b[1]]];
        finish();
      } else paint();
    });
    async function save(clear = false) {
      if (busy || !initialized) return;
      if (!clear && (mode || !geometry)) { status("Hãy vẽ/chọn xong một vùng trước khi xác nhận."); return; }
      setBusy(true);
      try {
        const active = clear ? null : el("choice").value === "custom" ? geometry
          : { type: "preset", key: el("choice").value };
        const saved = await request(`/map-sessions/${session}/area`, {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ active_area: active, expected_revision: revision })
        });
        revision = saved.revision;
        if (clear) { version++; mode = null; points = []; geometry = null; el("choice").value = "custom"; paint(); }
        status(clear ? "Đã xóa vùng của cuộc chat." : "Đã lưu vùng. Quay lại chat và hỏi về vùng vừa chọn.");
      } catch (error) { status(`Chưa cập nhật vùng: ${error.message}`); }
      finally { setBusy(false); }
    }
    el("rectangle").addEventListener("click", () => begin("rectangle"));
    el("polygon").addEventListener("click", () => begin("polygon"));
    el("finish").addEventListener("click", () => { if (!busy && mode === "polygon") finish(); });
    el("confirm").addEventListener("click", () => save());
    el("clear").addEventListener("click", () => save(true));
    el("reload").addEventListener("click", reload);
    el("choice").addEventListener("change", async () => {
      const marker = ++version;
      mode = null; points = []; geometry = null; paint();
      if (el("choice").value === "custom") { status("Chọn cách vẽ vùng tùy ý."); return; }
      setBusy(true);
      try { await loadPreset(el("choice").value, marker); status("Bấm Xác nhận để dùng vùng này cho cuộc chat."); }
      catch (error) { status(error.message); }
      finally { setBusy(false); }
    });
    return reload();
  }
  return { attach };
})();
