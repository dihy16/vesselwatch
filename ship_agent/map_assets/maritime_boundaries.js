// Validate and draw supplied boundaries or explicitly illustrative user sketches.
const Maritime = (() => {
  const zones = {
    internal_waters: { label: "Internal Waters", color: "#167d9a", dashArray: null },
    territorial_sea: { label: "Territorial Sea", color: "#b06915", dashArray: "8 5" },
  };
  function validate(document) {
    if (!document || document.type !== "FeatureCollection" || !Array.isArray(document.features) || document.features.length > 500) {
      throw new Error("Choose a GeoJSON FeatureCollection with at most 500 features.");
    }
    let count = 0;
    const point = (value) => {
      if (!Array.isArray(value) || value.length !== 2 || !value.every(Number.isFinite) ||
          Math.abs(value[0]) > 180 || Math.abs(value[1]) > 90) throw new Error("Invalid [longitude, latitude] boundary position.");
      if (++count > 100000) throw new Error("Too many boundary positions.");
    };
    const line = (value, ring = false) => {
      if (!Array.isArray(value) || value.length < (ring ? 4 : 2)) throw new Error("Boundary geometry has too few positions.");
      value.forEach(point);
      if (ring && (value[0][0] !== value.at(-1)[0] || value[0][1] !== value.at(-1)[1])) throw new Error("Polygon rings must be closed.");
    };
    const features = document.features.map((feature) => {
      const properties = feature?.properties, geometry = feature?.geometry;
      if (feature?.type !== "Feature" || !Object.hasOwn(zones, properties?.zone)) throw new Error("Feature zone must be internal_waters or territorial_sea.");
      const illustrative = properties.illustrative ?? false;
      if (typeof illustrative !== "boolean" || typeof (properties.source ?? "") !== "string" ||
          (!illustrative && !properties.source?.trim())) throw new Error("Provide a source or mark the feature illustrative.");
      if (typeof (properties.dataset_date ?? "") !== "string") throw new Error("Invalid boundary dataset date.");
      const reference = properties.reference ?? false;
      if (typeof reference !== "boolean" || typeof (properties.name ?? "") !== "string" ||
          typeof (properties.coverage ?? "") !== "string") throw new Error("Invalid boundary reference or description.");
      const coordinates = geometry?.coordinates;
      switch (geometry?.type) {
        case "LineString": line(coordinates); break;
        case "MultiLineString": case "Polygon":
          if (!Array.isArray(coordinates) || !coordinates.length) throw new Error("Empty boundary geometry.");
          coordinates.forEach((value) => line(value, geometry.type === "Polygon")); break;
        case "MultiPolygon":
          if (!Array.isArray(coordinates) || !coordinates.length) throw new Error("Empty boundary geometry.");
          coordinates.forEach((polygon) => {
            if (!Array.isArray(polygon) || !polygon.length) throw new Error("Empty polygon.");
            polygon.forEach((value) => line(value, true));
          }); break;
        default: throw new Error("Boundaries must use line or polygon geometry.");
      }
      return { type: "Feature", geometry, properties: { zone: properties.zone, illustrative, source: (properties.source || "").slice(0, 500), dataset_date: (properties.dataset_date || "").slice(0, 30), reference, name: (properties.name || "").slice(0, 160), coverage: (properties.coverage || "").slice(0, 500) } };
    });
    return { type: "FeatureCollection", features };
  }
  function attach(map, L, element, initial) {
    const data = validate(initial || { type: "FeatureCollection", features: [] });
    const features = data.features.filter((feature) => feature.properties.reference);
    if (!features.length) return;
    const layer = L.geoJSON({ type: "FeatureCollection", features }, {
      style: () => ({ color: "#7b9aa2", weight: 2, opacity: .65, dashArray: "4 3", fill: false }),
      onEachFeature(feature, featureLayer) {
        const year = feature.properties.dataset_date?.slice(0, 4) || "2023";
        const label = document.createElement("span");
        label.textContent = `Older nationwide reference (${year})`;
        featureLayer.bindTooltip(label, { sticky: true });
        const popup = document.createElement("div");
        popup.textContent = `${label.textContent}. Source: ${feature.properties.source}. Visualization only; not a legal or navigation chart.`;
        featureLayer.bindPopup(popup);
      },
    }).addTo(map);
    const bounds = layer.getBounds();
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [35, 35], maxZoom: 10 });
  }
  return { validate, attach };
})();
