// Image prediction, geometry, and result filtering helpers.
const Results = (() => {
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
  function queue(records, filter, threshold, sort) {
    const filtered = records.filter((record) =>
      (filter !== "candidates" || (prediction(record).score !== null && prediction(record).score >= threshold)));
    return filtered.sort((a, b) => sort === "date" ?
      new Date(b.captured_at) - new Date(a.captured_at) :
      (prediction(b).score ?? -1) - (prediction(a).score ?? -1));
  }
  return { prediction, polygon, queue };
})();
