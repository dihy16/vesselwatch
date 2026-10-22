// Draw a custom query polygon; counts always come from the complete server snapshot.
const AreaControls = (() => {
  function attach({ map, L, document, config, onResults }) {
    if (!config) return;
    const el = (id) => document.getElementById(id);
    const choice = el("area-choice"), status = el("area-status"), answer = el("area-answer");
    const centers = { thanh_dao: "Thanh Đảo", du_lam: "Du Lâm", long_pha: "Long Pha" };
    const radius = el("area-radius");
    const buttons = ["area-rectangle", "area-polygon", "area-finish", "area-clear", "area-confirm"];
    let mode = null, points = [], geometry = config.polygon || null, layer = null;
    let busy = false, boundaryVersion = 0;
    choice.value = config.center_key || config.named_area || "custom";
    radius.value = config.query?.radius_nm ?? "";
    function updateRadius() { el("area-radius-fields").hidden = !centers[choice.value]; }
    updateRadius();
    el("area-controls").open = Boolean(config.selection_id);

    function clearLayer() { if (layer) map.removeLayer(layer); layer = null; }
    function paint() {
      clearLayer();
      if (geometry) layer = L.geoJSON(geometry, { style: { color: "#167d9a", weight: 2, fillOpacity: .12 } }).addTo(map);
      else if (points.length) layer = L.polyline(points.map(([lng, lat]) => [lat, lng]), { color: "#167d9a" }).addTo(map);
    }
    function clearAnswer() {
      answer.textContent = "";
      el("area-reference").value = "";
      el("area-result-link").hidden = true;
      el("area-retry").hidden = true;
    }
    function setBusy(value) {
      busy = value;
      choice.disabled = value;
      radius.disabled = value;
      for (const id of buttons) el(id).disabled = value;
    }
    async function request(url, body, timeout = 30000) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeout);
      try {
        const response = await fetch(url, { method: body === undefined ? "GET" : "POST",
          headers: body === undefined ? {} : { "Content-Type": "application/json" },
          body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal });
        const result = await response.json();
        if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Vùng hoặc bộ lọc không hợp lệ.");
        return result;
      } catch (error) {
        if (error instanceof TypeError) throw new Error("Không kết nối được API. Hãy mở bản đồ toàn màn hình rồi thử lại.");
        throw error;
      } finally { clearTimeout(timer); }
    }
    function begin(kind) {
      if (busy) return;
      boundaryVersion++;
      choice.value = "custom";
      updateRadius();
      mode = kind; points = []; geometry = null;
      clearAnswer(); paint();
      status.textContent = kind === "rectangle" ? "Chọn hai góc đối diện trên bản đồ." :
        "Bấm các đỉnh trên bản đồ, rồi chọn Hoàn tất polygon (tối đa 200 đỉnh).";
    }
    function finish() {
      if (points.length < 3) { status.textContent = "Cần ít nhất 3 đỉnh."; return; }
      geometry = { type: "Polygon", coordinates: [[...points, points[0]]] };
      mode = null; paint();
      status.textContent = "Vùng đã vẽ. Bấm Xác nhận và hỏi agent để truy vấn.";
    }
    map.on("click", (event) => {
      if (!mode || busy) return;
      if (points.length >= 200) { status.textContent = "Tối đa 200 đỉnh."; return; }
      const lng = ((event.latlng.lng + 180) % 360 + 360) % 360 - 180;
      points.push([lng, event.latlng.lat]);
      if (mode === "rectangle" && points.length === 2) {
        const [a, b] = points;
        points = [a, [b[0], a[1]], b, [a[0], b[1]]];
        finish();
      } else paint();
    });
    async function showNamed() {
      const version = ++boundaryVersion;
      mode = null; points = []; geometry = null; clearLayer(); clearAnswer();
      updateRadius();
      if (choice.value === "custom") {
        status.textContent = "Chọn Vẽ rectangle hoặc Vẽ polygon để xác định vùng tùy ý.";
        return;
      }
      status.textContent = "Đang tải ranh giới khu vực…";
      const isCenter = Boolean(centers[choice.value]);
      if (isCenter && !(Number(radius.value) > 0 && Number.isFinite(Number(radius.value)))) {
        status.textContent = "Nhập khoảng cách mở rộng mỗi hướng, đơn vị hải lý."; return;
      }
      try {
        const feature = await request(`/query-areas/${choice.value}` + (isCenter ? `?radius_nm=${encodeURIComponent(radius.value)}` : ""));
        if (version !== boundaryVersion) return;
        geometry = feature.geometry; paint();
        const bounds = layer.getBounds();
        if (bounds.isValid()) map.fitBounds(bounds, { padding: [20, 20] });
        if (!busy) status.textContent = isCenter ? `${feature.properties.name}: ±${radius.value} hải lý, cạnh khoảng ${2 * Number(radius.value)} hải lý. Bấm xác nhận để truy vấn.` : `${feature.properties.name}: dùng polygon đã lưu.`;
      } catch (error) { if (version === boundaryVersion) status.textContent = error.message; }
    }
    let confirmedId = null;
    async function askAgent() {
      setBusy(true);
      answer.textContent = "Đang chờ agent trả lời…";
      el("area-retry").hidden = true;
      try {
        const result = await request(`/area-queries/${confirmedId}/answer`, {}, 190000);
        answer.textContent = result.answer;
      } catch (error) {
        answer.textContent = error.name === "AbortError" ? "Hết thời gian chờ agent." : error.message;
        el("area-retry").hidden = false;
      } finally { setBusy(false); }
    }
    async function confirm() {
      if (busy) return;
      if (mode || (choice.value === "custom" && !geometry)) {
        status.textContent = "Hãy vẽ xong vùng trước khi xác nhận."; return;
      }
      if (centers[choice.value] && (!geometry || !(Number(radius.value) > 0))) {
        status.textContent = "Nhập khoảng cách hải lý và chờ vùng xem trước."; return;
      }
      setBusy(true); clearAnswer();
      status.textContent = "Đang truy vấn dữ liệu trong vùng…";
      try {
        const query = { ...config.query, area_name: null, area_id: null,
          center_latitude: null, center_longitude: null, radius_nm: null };
        const name = { bien_dong: "Biển Đông", vinh_bac_bo: "Vịnh Bắc Bộ" }[choice.value];
        let result;
        if (centers[choice.value]) result = await request(config.prepare_url,
          { ...query, area_name: centers[choice.value], radius_nm: Number(radius.value) });
        else if (name) result = await request(config.prepare_url, { ...query, area_name: name });
        else if (config.confirm_url) result = await request(config.confirm_url, { polygon: geometry });
        else result = await request(config.prepare_url, { ...query, polygon: geometry });
        confirmedId = result.area_id;
        status.textContent = `${result.total} lượt phát hiện, ${result.possible_aircraft_carrier_count} lượt nghi là tàu sân bay. Hiển thị ${result.ships.length}/${result.total} kết quả.`;
        el("area-reference").value = `Mã vùng: ${confirmedId}`;
        const link = el("area-result-link");
        link.href = result.map_url; link.hidden = false;
        onResults(result.ships);
        await askAgent();
      } catch (error) {
        status.textContent = error.name === "AbortError" ? "Hết thời gian chờ truy vấn vùng." : error.message;
      } finally { setBusy(false); }
    }
    el("area-rectangle").addEventListener("click", () => begin("rectangle"));
    el("area-polygon").addEventListener("click", () => begin("polygon"));
    el("area-finish").addEventListener("click", () => { if (mode === "polygon") finish(); });
    el("area-clear").addEventListener("click", () => {
      boundaryVersion++; mode = null; points = []; geometry = null;
      choice.value = "custom"; clearLayer(); clearAnswer();
      updateRadius();
      status.textContent = "Vùng đã xóa. Chọn cách vẽ để bắt đầu lại.";
    });
    el("area-confirm").addEventListener("click", confirm);
    el("area-retry").addEventListener("click", () => { if (!busy && confirmedId) return askAgent(); });
    choice.addEventListener("change", showNamed);
    radius.addEventListener("change", showNamed);
    if (config.named_area || config.center_key) showNamed();
    else if (geometry) {
      paint();
      const bounds = layer.getBounds();
      if (bounds.isValid()) map.fitBounds(bounds, { padding: [20, 20] });
      status.textContent = "Vùng đã xác nhận. Có thể truy vấn lại hoặc vẽ vùng mới.";
    }
  }
  return { attach };
})();
