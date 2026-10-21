from datetime import date

import pytest
from langchain_core.tools import ToolException
from pydantic import ValidationError

from ship_agent.tools.registry import create_tools


@pytest.fixture
def tools():
    return create_tools(date(2026, 10, 13), data_source="mock")


def test_daily_counts_deduplicate_and_use_latest_classification(tools):
    result = tools[0].invoke({"observed_from": "2026-10-07", "observed_to": "2026-10-13"})
    assert len(result["daily_stats"]) == 7
    assert result["daily_stats"][0] == {
        "date": "2026-10-07", "suspicious_ship_count": 2, "possible_aircraft_carrier_count": 1,
    }
    assert result["daily_stats"][1] == {
        "date": "2026-10-08", "suspicious_ship_count": 0, "possible_aircraft_carrier_count": 0,
    }
    assert result["daily_stats"][-1]["suspicious_ship_count"] == 2
    assert result["daily_stats"][-1]["possible_aircraft_carrier_count"] == 1
    assert result["is_mock"] is True


def test_search_inclusive_dimensions_pagination_and_urls(tools):
    result = tools[1].invoke({"min_length_m": 250, "max_length_m": 350,
                              "min_width_m": 50, "max_width_m": 80, "limit": 2, "offset": 3})
    assert result["total"] == 5
    assert [s["ship_id"] for s in result["ships"]] == ["SHIP_004", "SHIP_006"]
    ship = result["ships"][-1]
    assert ship["length_m"] == 350 and ship["width_m"] == 80
    assert ship["ship_url"].startswith("https://")
    assert ship["images"][0]["url"].endswith(".jpg")


def test_time_window_selected_before_classification_filter(tools):
    search = tools[1]
    result = search.invoke({"observed_from": "2026-10-07", "observed_to": "2026-10-07",
                            "classification": "aircraft_carrier"})
    assert [s["ship_id"] for s in result["ships"]] == ["SHIP_002"]
    latest = search.invoke({"ship_id": "SHIP_001"})["ships"][0]
    assert latest["observed_date"] == "2026-10-12"
    assert latest["classification"] == "aircraft_carrier"
    assert search.invoke({"classification": "unknown"})["ships"][0]["confidence"] is None


def test_empty_results_and_return_values_are_isolated(tools):
    search = tools[1]
    result = search.invoke({"ship_id": "DOES_NOT_EXIST"})
    assert result["total"] == 0 and result["ships"] == []
    ship = search.invoke({"ship_id": "SHIP_001"})["ships"][0]
    ship["images"][0]["url"] = "changed"
    assert search.invoke({"ship_id": "SHIP_001"})["ships"][0]["images"][0]["url"] != "changed"
    assert search.invoke({"observed_from": "2026-10-13"})["total"] == 2


@pytest.mark.parametrize("tool_index,arguments,error", [
    (0, {"observed_from": "2026-10-14", "observed_to": "2026-10-13"}, ToolException),
    (0, {"observed_from": "2026-02-30", "observed_to": "2026-03-01"}, ToolException),
    (0, {"observed_from": "2026-10-13T00:00:00", "observed_to": "2026-10-13"}, ValidationError),
    (0, {"observed_from": "2025-01-01", "observed_to": "2026-10-13"}, ToolException),
    (1, {"min_length_m": 350, "max_length_m": 250}, ToolException),
    (1, {"limit": 101}, ValidationError),
    (1, {"min_width_m": -1}, ValidationError),
    (1, {"classification": "invalid"}, ValidationError),
    (1, {"unexpected": "ignored?"}, ValidationError),
])
def test_invalid_arguments_are_rejected(tools, tool_index, arguments, error):
    with pytest.raises(error):
        tools[tool_index].invoke(arguments)
