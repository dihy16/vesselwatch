"""Check caption-based counts and PNG endpoints with temporary observations."""

from datetime import date
from io import BytesIO
import json

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from file_server.app import create_app
from file_server.carrier_reports import daily_carrier_report, render_carrier_chart
from file_server.config import DataSettings


def observation(identity, day, classification="aircraft_carrier"):
    return {"observation_id": identity, "ship_id": "SAME_SHIP",
            "observed_date": day, "classification": classification}


def test_counts_observations_not_vessels_inclusive_zero_filled_and_label_only():
    rows = [observation("first", "2026-10-12"),
            observation("second", "2026-10-12"),
            observation("first", "2026-10-12"),
            observation("negative", "2026-10-12", "not_aircraft_carrier"),
            observation("unknown", "2026-10-12", "unknown"),
            observation("last", "2026-10-14"),
            observation("outside", "2026-10-15")]
    result = daily_carrier_report(rows, date(2026, 10, 12), date(2026, 10, 14))
    assert result["daily_stats"] == [
        {"date": "2026-10-12", "possible_aircraft_carrier_count": 2},
        {"date": "2026-10-13", "possible_aircraft_carrier_count": 0},
        {"date": "2026-10-14", "possible_aircraft_carrier_count": 1},
    ]
    assert result["total_detections"] == 3
    assert result["count_unit"] == "detections" and result["timezone"] == "UTC"


@pytest.mark.parametrize("days", [1, 366])
def test_png_is_decodable_for_empty_and_long_ranges(days):
    from datetime import timedelta

    first = date(2026, 1, 1)
    report = daily_carrier_report([], first, first + timedelta(days=days - 1))
    assert len(report["daily_stats"]) == days
    assert report["total_detections"] == 0
    with Image.open(BytesIO(render_carrier_chart(report))) as image:
        assert image.format == "PNG"
        assert image.size == (1680, 672)
        image.verify()


@pytest.mark.parametrize("first,last", [
    (date(2026, 10, 14), date(2026, 10, 13)),
    (date(2026, 1, 1), date(2027, 1, 2)),
])
def test_invalid_ranges_are_rejected(first, last):
    with pytest.raises(ValueError):
        daily_carrier_report([], first, last)


@pytest.fixture
def dataset(tmp_path):
    root = tmp_path / "images"
    root.mkdir()
    messages, predictions = [], []
    for index, (day, label, score) in enumerate([
        ("2026-10-12", True, 0.1), ("2026-10-12", True, 0.2),
        ("2026-10-12", False, 0.99), ("2026-10-14", True, 0.95),
    ]):
        name = f"photo_{index}_2025-01-01.jpg"
        (root / name).write_bytes(b"synthetic")
        messages.append({"date": "2025-01-01T00:00:00Z", "image": name,
                         "caption": "- Vị trí: [12, 112]\n"
                                    f"- Thời gian: {day} 23:59:59\n"
                                    "- Dài / Rộng: 300(m)/60(m)\n"
                                    "- Tàu: SAME_DETECTION"})
        predictions.append({"image_path": name, "carrier_probability": score,
                            "predicted_aircraft_carrier": label})
    telegram_path, prediction_path = tmp_path / "telegram.json", tmp_path / "predictions.json"
    telegram_path.write_text(json.dumps(messages), encoding="utf-8")
    prediction_path.write_text(json.dumps({"predictions": predictions}), encoding="utf-8")
    return DataSettings(telegram_path, root, prediction_path, "http://viewer:8001")


def test_report_png_contract_caption_day_and_unchanged_prediction_files(dataset):
    original = dataset.predictions_path.read_bytes()
    with TestClient(create_app(dataset)) as client:
        result = client.get("/reports/daily-carriers", params={
            "observed_from": "2026-10-12", "observed_to": "2026-10-14",
        })
        assert result.status_code == 200
        report = result.json()
        assert report["total_detections"] == 3
        assert [s["possible_aircraft_carrier_count"] for s in report["daily_stats"]] == [2, 0, 1]
        assert report["chart_url"].startswith("http://viewer:8001/charts/")
        assert report["coverage"]["observation_count"] == 4
        png = client.get(report["chart_url"])
        assert png.status_code == 200 and png.headers["content-type"] == "image/png"
        with Image.open(BytesIO(png.content)) as image:
            image.verify()
        assert client.get("/charts/daily-carriers.png", params={
            "observed_from": "2026-10-12", "observed_to": "2026-10-14",
            "report_id": "0" * 64,
        }).status_code == 409
    assert dataset.predictions_path.read_bytes() == original
    assert sorted(p.name for p in dataset.predictions_path.parent.iterdir()) == [
        "images", "predictions.json", "telegram.json",
    ]


def test_chart_refuses_old_counts_after_snapshot_changes(dataset):
    with TestClient(create_app(dataset)) as client:
        report = client.get("/reports/daily-carriers?observed_from=2026-10-12&observed_to=2026-10-14").json()
    data = json.loads(dataset.predictions_path.read_text())
    data["predictions"][0]["predicted_aircraft_carrier"] = False
    dataset.predictions_path.write_text(json.dumps(data), encoding="utf-8")
    with TestClient(create_app(dataset)) as client:
        assert client.get(report["chart_url"]).status_code == 409


@pytest.mark.parametrize("query", [
    "", "observed_from=2026-02-30&observed_to=2026-10-14",
    "observed_from=2026-10-14&observed_to=2026-10-12",
    "observed_from=2026-01-01&observed_to=2027-01-02",
])
def test_endpoint_rejects_missing_invalid_and_excessive_ranges(dataset, query):
    with TestClient(create_app(dataset)) as client:
        assert client.get(f"/reports/daily-carriers?{query}").status_code == 422
