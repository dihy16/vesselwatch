"""Render the existing Leaflet viewer and a small iframe-only chat artifact."""

import base64
from html import escape
import json
from pathlib import Path
import re


ASSETS = Path(__file__).resolve().parents[1] / "map_assets"


def _json_for_html(value: dict) -> str:
    return (json.dumps(value, ensure_ascii=True, separators=(",", ":"))
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def render_map(payload: dict) -> str:
    """Everything except the OpenStreetMap base tiles stays inside this page."""
    filters = payload["filters"]
    dataset = {"sample_data": False, "vessels": payload["vessels"],
               "initial_date": filters["observed_to"],
               "default_date_range": {"from": filters["observed_from"], "to": filters["observed_to"]},
               "dataset_label": "VesselWatch demo · Saved predictions · Filtered snapshot",
               "snapshot_filters": filters,
               "area_query": payload.get("area_query", {
                   "prepare_url": "/area-queries", "query": filters,
               }),
               "boundaries": json.loads((ASSETS / "data/vietnam_maritime_boundaries.geojson")
                                        .read_text(encoding="utf-8"))}
    css = (ASSETS / "vendor/leaflet.css").read_text(encoding="utf-8")
    for name in ("layers.png", "layers-2x.png", "marker-icon.png"):
        data = base64.b64encode((ASSETS / "vendor" / name).read_bytes()).decode("ascii")
        css = css.replace(f"url(images/{name})", f'url("data:image/png;base64,{data}")')
    svg = (ASSETS / "vessel_marker_default.svg").read_text(encoding="utf-8")
    markers = []
    for palette in (("#167d9a", "#10586c", "#103e50"), ("#dc2626", "#991b1b", "#7f1d1d")):
        colored = svg
        for original, replacement in zip(("#1976D2", "#0C4A91", "#0B2E5D"), palette):
            colored = colored.replace(f'"{original}"', f'"{replacement}"')
        markers.append("data:image/svg+xml;base64," + base64.b64encode(colored.encode("utf-8")).decode("ascii"))
    replacements = {
        "__LEAFLET_LICENSE__": "<!--\n" + (ASSETS / "vendor/LICENSE").read_text(encoding="utf-8") + "\n-->",
        "__LEAFLET_CSS__": css,
        "__LEAFLET_JS__": re.sub(r"\n?//# sourceMappingURL=.*", "", (ASSETS / "vendor/leaflet.js").read_text(encoding="utf-8")),
        "__VESSEL_DATA__": _json_for_html(dataset),
        "__VESSEL_MARKER_DATA_URL__": markers[0], "__VESSEL_MARKER_SELECTED_DATA_URL__": markers[1],
        "__CLASSIFIER_CONNECT_SOURCE__": "",
    }
    for token, filename in (("__RESULT_HELPERS__", "result_helpers.js"),
                            ("__REVIEW_HELPERS__", "review_workflow.js"),
                            ("__BOUNDARY_HELPERS__", "maritime_boundaries.js"),
                            ("__CLASSIFIER_HELPERS__", "classifier_client.js")):
        replacements[token] = (ASSETS / filename).read_text(encoding="utf-8")
    replacements["__AREA_CONTROLS__"] = (ASSETS / "area_controls.js").read_text(encoding="utf-8")
    html = (ASSETS / "vessel_map_template.html").read_text(encoding="utf-8")
    for token, value in replacements.items():
        html = html.replace(token, value)
    return html


def render_map_artifact(result: dict) -> str:
    url = escape(result["map_url"], quote=True)
    caption = ("Vẽ vùng truy vấn rồi bấm xác nhận" if result.get("status") == "needs_drawing"
               else f"{result['total']} lượt quan sát")
    return f'''<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bản đồ tàu</title><style>body{{margin:0;font-family:system-ui,sans-serif}}p{{margin:10px}}iframe{{width:100%;height:780px;border:0}}</style></head>
<body><p>{caption} · <a href="{url}" target="_blank" rel="noopener">Mở bản đồ toàn màn hình</a></p>
<iframe src="{url}" title="Bản đồ tàu VesselWatch" allow="fullscreen"></iframe></body></html>'''
