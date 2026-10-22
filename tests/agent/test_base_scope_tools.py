"""A merged tool must forward base/coordinate fields accepted by its public schema."""

import importlib

import pytest

pytest.importorskip("langchain_core")

from ship_agent.tools.registry import create_tools


@pytest.mark.parametrize("name,module,request", [
    ("query_ships_in_area", "areas", "request_area_query"),
    ("analyze_ship_observations", "areas", "request_observation_analysis"),
    ("investigate_missed_carriers", "missed_carrier_tool", "request_missed_carrier_candidates"),
    ("investigate_false_carriers", "false_carrier_tool", "request_false_carrier_candidates"),
    ("investigate_carrier_detections", "carrier_investigation_tool", "request_carrier_investigation_candidates"),
    ("find_carrier_hotspots", "hotspot_tools", "request_carrier_hotspots"),
    ("investigate_carrier_hotspot", "hotspot_tools", "request_carrier_hotspot_candidates"),
    ("investigate_carrier_labels", "label_review_tool", "request_label_review_candidates"),
    ("vessel_monitoring_report", "monitoring_tool", "request_monitoring_report"),
])
@pytest.mark.parametrize("area", [{"area_name": "Du Lâm", "radius_nm": 20},
    {"center_latitude": 18.221, "center_longitude": 109.537, "radius_nm": 20}])
def test_base_or_coordinates_reach_backend_for_all_spatial_tools(monkeypatch, name, module, request, area):
    captured = []
    def backend(query, **kwargs):
        captured.append(query)
        return {"status": "needs_drawing", "map_url": "http://viewer/map", "selection_id": "a" * 32}

    monkeypatch.setattr(importlib.import_module("ship_agent.tools." + module), request, backend)
    tool = next(item for item in create_tools(observations=[]) if item.name == name)
    args = {"observed_from": "2025-01-01", "observed_to": "2025-12-31", **area}
    if name == "analyze_ship_observations":
        args["analysis"] = "dimension_mismatch"
    if name == "investigate_carrier_hotspot":
        args.update(report_id="b" * 64, cluster_id="c" * 32)
    assert tool.invoke(args)["status"] == "needs_drawing"
    assert len(captured) == 1
    assert all(captured[0][key] == value for key, value in area.items())
    assert captured[0].get("polygon") is None
