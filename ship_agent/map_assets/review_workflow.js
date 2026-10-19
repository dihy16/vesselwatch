// Pure review helpers, embedded by the HTML builder; no network or DOM access.
const Review = (() => {
  const labels = ["Carrier present", "Carrier absent", "Uncertain"];
  function prediction(record) {
    const value = record.prediction ?? record.metadata?.prediction;
    const score = value?.carrier_score;
    if (typeof score !== "number" || !Number.isFinite(score) || score < 0 || score > 1) {
      return { score: null, model: "Not provided", simulated: false };
    }
    return { score, model: String(value.model || "Unknown model"), simulated: value.simulated === true };
  }
  function polygon(value) {
    if (!Array.isArray(value) || value.length !== 4 || !value.every((point) =>
      Array.isArray(point) && point.length === 2 && point.every((coordinate) =>
        typeof coordinate === "number" && Number.isFinite(coordinate) && coordinate >= 0 && coordinate <= 1))) return null;
    return value;
  }
  function queue(records, reviews, filter, threshold, sort) {
    const filtered = records.filter((record) =>
      (filter !== "candidates" || (prediction(record).score !== null && prediction(record).score >= threshold)) &&
      (filter !== "unreviewed" || !reviews.has(record.id)));
    return filtered.sort((a, b) => sort === "date" ?
      new Date(b.captured_at) - new Date(a.captured_at) :
      (prediction(b).score ?? -1) - (prediction(a).score ?? -1));
  }
  function reviewStore(storage, key) {
    const records = new Map();
    let writable = Boolean(storage);
    try {
      const payload = JSON.parse(storage?.getItem(key) || "[]");
      if (!Array.isArray(payload)) throw new Error("Invalid saved reviews");
      for (const row of payload) {
        if (row && typeof row.id === "string" && labels.includes(row.label) &&
            typeof row.notes === "string" && typeof row.updated_at === "string" &&
            Number.isFinite(Date.parse(row.updated_at))) records.set(row.id, {
          ...row, notes: row.notes.slice(0, 2000), reviewer: String(row.reviewer || "").slice(0, 80)
        });
      }
    } catch { writable = false; }
    return { records, save(row) {
      if (!labels.includes(row.label)) throw new Error("Choose a review label.");
      const saved = { ...row, notes: String(row.notes || "").slice(0, 2000),
        reviewer: String(row.reviewer || "").slice(0, 80), updated_at: new Date().toISOString() };
      const next = new Map(records);
      next.set(row.id, saved);
      let persisted = false;
      try {
        if (writable) { storage.setItem(key, JSON.stringify([...next.values()])); persisted = true; }
      } catch { writable = false; }
      records.set(row.id, saved);
      return persisted;
    }, get persistent() { return writable; } };
  }
  function csv(records, reviews, threshold) {
    const header = ["observation_id", "capture_time_utc", "latitude", "longitude", "carrier_score",
      "prediction", "carrier_score_threshold", "model", "simulated", "review_label", "reviewer", "notes", "reviewed_at_utc"];
    const cell = (value) => {
      let text = String(value ?? "");
      if (/^[\s]*[=+\-@]/.test(text) || /^[\t\r\n]/.test(text)) text = "'" + text;
      return '"' + text.replaceAll('"', '""') + '"';
    };
    const rows = records.filter((record) => reviews.has(record.id)).map((record) => {
      const result = prediction(record), review = reviews.get(record.id);
      return [record.id, record.captured_at, record.latitude, record.longitude, result.score,
        result.score === null ? "Not available" : result.score >= threshold ? "Carrier present" : "Carrier absent",
        threshold, result.model, result.simulated, review.label, review.reviewer, review.notes, review.updated_at].map(cell).join(",");
    });
    return [header.join(","), ...rows].join("\r\n");
  }
  return { labels, prediction, polygon, queue, reviewStore, csv };
})();
