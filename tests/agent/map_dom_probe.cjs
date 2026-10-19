// Exercise the actual app script with isolated DOM and Leaflet test doubles.
// This checks application behavior, not browser rendering or tile networking.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const input = JSON.parse(fs.readFileSync(0, "utf8"));

class Element {
  constructor(tag, hidden = false) {
    this.tagName = tag;
    this.hidden = hidden;
    this.children = [];
    this.attributes = {};
    this.dataset = {};
    this.events = {};
    this.style = {};
    this.className = "";
    this.textContent = "";
    this.value = "";
    this.classList = {
      contains: (name) => this.className.split(/\s+/).includes(name),
      toggle: (name, force) => {
        const names = new Set(this.className.split(/\s+/).filter(Boolean));
        const active = force === undefined ? !names.has(name) : Boolean(force);
        if (active) names.add(name); else names.delete(name);
        this.className = [...names].join(" ");
        return active;
      },
      add: (name) => this.classList.toggle(name, true),
      remove: (name) => this.classList.toggle(name, false),
    };
  }
  set innerHTML(value) {
    throw new Error(`Application used an HTML sink: ${value}`);
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  removeAttribute(name) { delete this.attributes[name]; delete this[name]; }
  append(...children) {
    for (const child of children) {
      if (child.tagName === "#fragment") {
        this.children.push(...child.children);
        child.children = [];
      } else this.children.push(child);
    }
  }
  replaceChildren(...children) { this.children = children; }
  querySelectorAll(selector) {
    assert.equal(selector, ".vessel-row");
    return this.children.filter((child) => child.className === "vessel-row");
  }
  querySelector(selector) {
    assert.ok(selector.startsWith("."));
    for (const child of this.children) {
      if (child.classList.contains(selector.slice(1))) return child;
      const nested = child.querySelector(selector);
      if (nested) return nested;
    }
    return null;
  }
  addEventListener(name, handler) { this.events[name] = handler; }
  click() { return this.events.click?.({}); }
  focus() { document.activeElement = this; }
  scrollIntoView(options) { this.scrollOptions = options; }
  showModal() { this.open = true; }
  close() { this.open = false; this.events.close?.({}); }
  remove() {}
}

const elements = Object.fromEntries(Object.entries(input.elements).map(
  ([id, properties]) => {
    const element = new Element(properties.tag, properties.hidden);
    element.checked = properties.checked;
    return [id, element];
  }
));
elements["embedded-data"].textContent = JSON.stringify(input.dataset);
const document = {
  body: new Element("body"),
  getElementById: (id) => elements[id],
  createElement: (tag) => new Element(tag),
  createDocumentFragment: () => new Element("#fragment"),
  createElementNS: (namespace, tag) => {
    const element = new Element(tag);
    element.namespaceURI = namespace;
    return element;
  },
};
const map = {
  zoom: 5,
  events: {},
  on(name, handler) { this.events[name] = handler; return this; },
  removeLayer() {},
  setView(_position, zoom) { this.zoom = zoom; return this; },
  getZoom() { return this.zoom; },
  fitBounds(bounds) { this.bounds = bounds; },
  invalidateSize() {},
};
const layer = {
  markers: [],
  addTo() { return this; },
  clearLayers() { this.markers = []; },
};
const boundaryLayers = [];
const L = {
  map: () => map,
  layerGroup: () => layer,
  tileLayer: () => ({ addTo() { return this; }, on() { return this; } }),
  geoJSON(data, options) {
    const boundary = { data, options, addTo() { return this; }, getBounds() { return { isValid: () => false }; } };
    boundaryLayers.push(boundary);
    for (const feature of data.features) options.onEachFeature(feature, { bindTooltip(content) {
      assert.ok(content instanceof Element);
    }, bindPopup(content) { assert.ok(content instanceof Element); } });
    return boundary;
  },
  polyline: (positions, options) => ({ positions, options, addTo() { return this; } }),
  divIcon(options) {
    assert.ok(options.html instanceof Element, "Ship icon must use safe DOM content");
    assert.deepEqual(Array.from(options.iconSize), [32, 32]);
    assert.deepEqual(Array.from(options.iconAnchor), [16, 16], "Anchor must remain at the icon center");
    const glyph = options.html.children[0];
    assert.equal(glyph.className, "ship-marker-glyph");
    return options;
  },
  marker(position, options) {
    const iconElement = new Element("div");
    iconElement.append(options.icon.html);
    return {
      position, options, events: {},
      addTo(target) { target.markers.push(this); return this; },
      bindTooltip(content) {
        assert.ok(content instanceof Element, "Tooltip must receive a DOM node");
        this.tooltip = content;
      },
      on(name, handler) { this.events[name] = handler; },
      getElement() { return iconElement; },
      setZIndexOffset(offset) { this.zIndexOffset = offset; },
      getLatLng() { return this.position; },
    };
  },
};
// A sandboxed iframe may deny storage. Viewing a saved map must still work.
const window = {
  location: new URL("http://localhost:8002/maps/test"),
  addEventListener() {}, setTimeout() {}, clearTimeout() {},
  get localStorage() { throw new Error("Storage unavailable in sandbox"); },
};
const fetch = () => { throw new Error("A saved map must not fetch metadata or images through JS"); };
elements["prediction-source"].value = "saved";
elements["queue-filter"].value = "all";
elements["queue-sort"].value = "score";
vm.runInNewContext(input.script, { document, window, L, URL, Intl, Date, fetch,
  AbortController, Blob, FormData, setTimeout, clearTimeout }, { timeout: 3000 });

const count = input.dataset.vessels.length;
assert.equal(elements["search-status"].hidden, true, elements["search-status"].textContent);
assert.equal(elements["record-count"].textContent, String(count));
assert.equal(layer.markers.length, count);
assert.equal(elements["panel-query"].hidden, true);
assert.equal(elements["panel-results"].hidden, false);
if (count) {
  const row = elements["vessel-list"].children[0];
  row.click();
  const selected = input.dataset.vessels.find((record) => record.id === row.dataset.vesselId);
  assert.equal(elements["vessel-title"].textContent, selected.metadata.source_id);
  assert.equal(elements["vessel-image"].src, selected.image_path);
  assert.equal(elements["detail-content"].hidden, false);
  assert.equal(elements["detail-table"].children[0].children[1].textContent, selected.captured_at);
  assert.equal(elements["detail-table"].children[3].children[1].textContent, `${selected.metadata.width_m.toFixed(2)} m`);
  layer.markers[0].events.click();
  assert.equal(elements["vessel-list"].children[0].attributes["aria-current"], "true");
} else {
  assert.equal(elements["detail-content"].hidden, true);
}
console.log("Map application probe passed");
