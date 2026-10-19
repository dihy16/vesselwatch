// Batch prepared detection crops; preserve IDs and cancel superseded searches.
const Classifier = (() => {
  function aborted(signal) {
    if (signal?.aborted) {
      const error = new Error("Classification cancelled.");
      error.name = "AbortError";
      throw error;
    }
  }

  function pause(ms, signal) {
    aborted(signal);
    return new Promise((resolve, reject) => {
      const cancel = () => {
        clearTimeout(timer);
        signal?.removeEventListener("abort", cancel);
        const error = new Error("Classification cancelled.");
        error.name = "AbortError";
        reject(error);
      };
      const timer = setTimeout(() => {
        signal?.removeEventListener("abort", cancel);
        resolve();
      }, ms);
      signal?.addEventListener("abort", cancel, { once: true });
    });
  }

  async function request(url, options, read, timeoutMs = 120000) {
    const parent = options.signal;
    aborted(parent);
    const controller = new AbortController();
    const cancel = () => controller.abort();
    parent?.addEventListener("abort", cancel, { once: true });
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
    try {
      let response;
      for (let attempt = 0; ; attempt++) {
        response = await fetch(url, { ...options, signal: controller.signal });
        aborted(parent);
        // A cancelled search can leave its GPU batch running. Retry only busy
        // responses, with the same bounded request timeout and upload contents.
        if (options.method !== "POST" || response.status !== 409 || attempt >= 2) break;
        const retryAfter = Number(response.headers?.get("Retry-After") ?? "1");
        await pause(Number.isFinite(retryAfter) ? Math.min(5, Math.max(0, retryAfter)) * 1000 : 1000,
          controller.signal);
      }
      aborted(parent);
      if (!response.ok) {
        let detail = "";
        try {
          const payload = await response.json();
          const message = payload?.detail ?? payload?.error;
          if (typeof message === "string") detail = ` ${message.slice(0, 400)}`;
        } catch { /* Gateways can return HTML rather than an API error. */ }
        throw new Error(`Request failed (HTTP ${response.status}).${detail}`);
      }
      const result = await read(response);
      aborted(parent);
      return result;
    } catch (error) {
      if (timedOut) throw new Error("Classification request timed out. Try again.");
      throw error;
    } finally {
      clearTimeout(timer);
      parent?.removeEventListener("abort", cancel);
    }
  }

  function limit(value, fallback) {
    return Number.isSafeInteger(value) && value > 0 ? value : fallback;
  }

  async function classify(records, baseUrl, { signal, onProgress = () => {} } = {}) {
    for (const record of records) {
      record.prediction = { model: "Pending classification", simulated: false };
      record.metadata = { ...record.metadata, prediction: record.prediction };
      record.classification_error = "Classification has not completed for this crop.";
    }
    if (!records.length) return { failed: 0, model: "" };
    const base = baseUrl.replace(/\/+$/, "");
    const headers = { Accept: "application/json", "ngrok-skip-browser-warning": "1" };
    const health = await request(`${base}/health`, { headers, signal }, (r) => r.json(), 30000);
    if (health?.status !== "ready" || typeof health.model !== "string" || !health.model.trim()) {
      throw new Error("The classifier is not ready or returned invalid model information. Try again.");
    }
    const maxCount = Math.min(32, limit(health.max_batch_size, 32));
    const maxImageBytes = limit(health.max_image_bytes, 8 * 1024 * 1024);
    const maxBatchBytes = limit(health.max_batch_bytes, 32 * 1024 * 1024);
    let batch = [], batchBytes = 0, completed = 0;

    async function flush() {
      if (!batch.length) return;
      aborted(signal);
      const form = new FormData();
      form.append("detection_ids", JSON.stringify(batch.map(({ record }) => record.id)));
      for (const { blob } of batch) form.append("images", blob, "crop");
      const result = await request(`${base}/predict/batch`, {
        method: "POST", headers, body: form, signal,
      }, (r) => r.json());
      if (!Array.isArray(result?.predictions) || !Array.isArray(result.errors) ||
          typeof result.model !== "string" || !result.model || result.simulated !== false ||
          result.total !== batch.length) throw new Error("The classifier returned an invalid batch response.");
      if (result.model !== health.model) {
        throw new Error("The classifier model changed during this search. Run the search again.");
      }
      const expected = new Map(batch.map(({ record }) => [record.id, record]));
      const seen = new Set();
      const updates = [];
      for (const prediction of result.predictions) {
        const id = prediction?.detection_id, score = prediction?.carrier_score;
        if (!expected.has(id) || seen.has(id) || typeof score !== "number" ||
            !Number.isFinite(score) || score < 0 || score > 1) {
          throw new Error("The classifier returned invalid detection IDs or scores.");
        }
        seen.add(id);
        updates.push({ record: expected.get(id), prediction: {
          carrier_score: score, model: result.model, simulated: false,
        } });
      }
      for (const error of result.errors) {
        const id = error?.detection_id;
        if (!expected.has(id) || seen.has(id) || typeof error.message !== "string") {
          throw new Error("The classifier returned invalid crop errors.");
        }
        seen.add(id);
        updates.push({ record: expected.get(id), error: error.message });
      }
      if (seen.size !== batch.length) throw new Error("The classifier omitted detection results.");
      for (const update of updates) {
        update.record.prediction = update.prediction || { model: result.model, simulated: false };
        update.record.metadata.prediction = update.record.prediction;
        update.record.classification_error = update.error || "";
      }
      completed += batch.length;
      batch = [];
      batchBytes = 0;
      onProgress(completed, records.length);
    }

    onProgress(0, records.length);
    for (const record of records) {
      aborted(signal);
      let blob;
      try {
        blob = await request(record.image_url, { signal }, (r) => r.blob(), 30000);
        if (!blob.size || blob.size > Math.min(maxImageBytes, maxBatchBytes)) {
          throw new Error("Crop is empty or exceeds the classifier upload limit.");
        }
        if (blob.type === "image/svg+xml") throw new Error("SVG demo images cannot be classified.");
      } catch (error) {
        aborted(signal);
        record.classification_error = `Crop unavailable: ${error.message}`;
        completed++;
        onProgress(completed, records.length);
        continue;
      }
      if (batchBytes + blob.size > maxBatchBytes) await flush();
      batch.push({ record, blob });
      batchBytes += blob.size;
      if (batch.length >= maxCount) await flush();
    }
    await flush();
    return { failed: records.filter((r) => r.classification_error).length, model: health.model };
  }
  return { classify };
})();
