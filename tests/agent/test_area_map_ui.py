"""Map UI tests use the actual renderer and JS; no FastAPI or LangGraph needed."""

from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from ship_agent.artifacts.map_artifacts import ASSETS
from ship_agent.artifacts.map_artifacts import render_map
from ship_agent.artifacts.map_artifacts import render_map_artifact


def test_rectangle_polygon_and_backend_agent_handoff():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the drawing probe")
    completed = subprocess.run(
        [node, str(Path(__file__).with_name("area_controls_probe.cjs")), str(ASSETS / "area_controls.js")],
        text=True, capture_output=True, check=True, timeout=15,
    )
    assert "Area drawing and agent handoff probe passed" in completed.stdout


@pytest.mark.parametrize("has_records", [False, True])
def test_existing_frozen_map_still_autoloads_without_fetch(has_records):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the map probe")
    payload = {"filters": {"observed_from": "2026-10-01", "observed_to": "2026-10-02"},
               "vessels": [{"id": "one", "name": "ship-one", "captured_at": "2026-10-01T01:00:00+00:00",
                            "latitude": 16, "longitude": 111, "image_path": "http://viewer/images/one",
                            "prediction": {"carrier_score": .9},
                            "metadata": {"source_id": "ship-one", "length_m": 300, "width_m": 60}}]
                          if has_records else []}
    html = render_map(payload)

    class Elements(HTMLParser):
        def __init__(self):
            super().__init__()
            self.elements = {}

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if "id" in attrs:
                self.elements[attrs["id"]] = {"tag": tag, "hidden": "hidden" in attrs, "checked": "checked" in attrs}

    parser = Elements()
    parser.feed(html)
    dataset = json.loads(re.search(r'<script id="embedded-data" type="application/json">(.*?)</script>', html, re.S)[1])
    scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", html, re.S)
    result = subprocess.run(
        [node, str(Path(__file__).with_name("map_dom_probe.cjs"))],
        input=json.dumps({"elements": parser.elements, "dataset": dataset, "script": scripts[-1]}),
        text=True, capture_output=True, check=True, timeout=15,
    )
    assert "Map application probe passed" in result.stdout
    assert "__AREA_CONTROLS__" not in html


def test_drawing_artifact_is_small_and_does_not_claim_zero_matches():
    artifact = render_map_artifact({"status": "needs_drawing", "map_url": "http://viewer/area-queries/a"})
    assert "Vẽ vùng truy vấn" in artifact and "0 lượt" not in artifact
    assert len(artifact) < 1500 and "leaflet.js" not in artifact
