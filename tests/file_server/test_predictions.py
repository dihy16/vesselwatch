"""Exported prediction checks without FastAPI or production data."""

import json

import pytest

from file_server.config import DataSettings
from file_server.loader import load_predictions, load_store


def write_report(tmp_path, rows, **metadata):
    path = tmp_path / "predictions.json"
    path.write_text(json.dumps({"predictions": rows, **metadata}), encoding="utf-8")
    return path


def prediction(name="photo.jpg", score=0.8, label=False):
    return {"image_path": f"/data2/DATA/telegram_data/images/{name}",
            "carrier_probability": score, "predicted_aircraft_carrier": label}


def test_exported_score_and_label_are_preserved_without_loading_run_files(tmp_path):
    path = write_report(tmp_path, [prediction(), prediction("other.jpg", 0.2, True)],
                        schema_version=2, mining_threshold=0.95,
                        ensemble_method="clipped_mean_logit",
                        runs={"run_id": {"report_path": "/missing/report.json",
                                         "checkpoints": ["/missing/seed_42.pt"]}})
    rows, metadata = load_predictions(path)
    assert rows["photo.jpg"].score == 0.8
    assert rows["photo.jpg"].classification == "not_aircraft_carrier"
    assert rows["other.jpg"].score == 0.2
    assert rows["other.jpg"].classification == "aircraft_carrier"
    assert metadata == {"runs": ["run_id"],
                        "ensemble_method": "clipped_mean_logit"}


def test_empty_predictions_are_valid(tmp_path):
    rows, _ = load_predictions(write_report(tmp_path, []))
    assert rows == {}


@pytest.mark.parametrize("field,value", [
    ("carrier_probability", float("nan")), ("carrier_probability", float("inf")),
    ("carrier_probability", -0.1), ("carrier_probability", 1.1),
    ("carrier_probability", True), ("carrier_probability", "0.9"),
    ("predicted_aircraft_carrier", "false"), ("predicted_aircraft_carrier", 1),
    ("predicted_aircraft_carrier", None), ("image_path", ""), ("image_path", None),
])
def test_invalid_prediction_is_rejected(tmp_path, field, value):
    row = {**prediction(), field: value}
    with pytest.raises(ValueError, match="Invalid prediction"):
        load_predictions(write_report(tmp_path, [row]))


def test_duplicate_basename_is_rejected_even_with_different_directories(tmp_path):
    other = {**prediction(), "image_path": "C:\\images\\photo.jpg"}
    with pytest.raises(ValueError, match="Duplicate prediction.*photo.jpg"):
        load_predictions(write_report(tmp_path, [prediction(), other]))


@pytest.mark.parametrize("report", [[], {}, {"predictions": {}}, {"predictions": [None]}])
def test_invalid_report_shape_is_rejected(tmp_path, report):
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError):
        load_predictions(path)


def test_invalid_json_reports_file_and_line(tmp_path):
    path = tmp_path / "truncated.json"
    path.write_text('{"predictions": [{', encoding="utf-8")
    with pytest.raises(ValueError, match="truncated.json.*line 1"):
        load_predictions(path)


def test_join_uses_filename_and_does_not_share_score_between_same_detection(tmp_path):
    root = tmp_path / "images"
    root.mkdir()
    messages = []
    for name in ("photo.jpg", "other.jpg", "unknown.jpg"):
        (root / name).write_bytes(b"synthetic-image")
        messages.append({"image": f"telegram_data/images/{name}",
                         "caption": "- Vị trí: [13, 114]\n"
                                    "- Thời gian: 2026-05-15 10:04:14\n"
                                    "- Dài / Rộng: 300(m)/60(m)\n- Tàu: SAME_DETECTION"})
    metadata_path = tmp_path / "telegram.json"
    metadata_path.write_text(json.dumps(messages), encoding="utf-8")
    report_path = write_report(tmp_path, [prediction(), prediction("other.jpg", 0.97, True)])
    store = load_store(DataSettings(metadata_path, root, report_path))
    assert len(store.observations) == 3
    assert all(o.ship_id == "SAME_DETECTION" for o in store.observations)
    by_name = {store.images[o.images[0].image_id][0]: o for o in store.observations}
    assert by_name["photo.jpg"].confidence == 0.8
    assert by_name["photo.jpg"].classification == "not_aircraft_carrier"
    assert by_name["other.jpg"].classification == "aircraft_carrier"
    assert by_name["unknown.jpg"].classification == "unknown"
    assert by_name["unknown.jpg"].confidence is None
    assert store.summary["prediction_count"] == 2
    assert store.summary["unknown_count"] == 1
    assert all(o.observed_at == "2026-05-15T10:04:14+00:00" for o in store.observations)
