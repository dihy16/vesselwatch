"""Synthetic file/API checks; no production images, LLM or network required."""

import json

from fastapi.testclient import TestClient
import pytest

from file_server.app import create_app
from file_server import config
from file_server.config import DataSettings
from file_server.loader import load_store


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def dataset(tmp_path):
    root = tmp_path / "images"
    root.mkdir()
    telegram, predictions = [], []
    for index, score in enumerate([0.5, 0.1, None]):
        source_id = f"SCENE_{index}"
        name = f"photo_{index}.jpg"
        (root / name).write_bytes(b"synthetic-image-" + str(index).encode())
        telegram.append({"message_id": index, "date": "2026-10-20T00:00:00Z",
                         "caption": "Thông báo\n- Vị trí: [12, 112]\n"
                                    "- Thời gian: 2026-10-13 18:00:00\n"
                                    "- Dài / Rộng: 300(m)/60(m)\n"
                                    f"- Tàu: <b>{source_id}</b>",
                         "image": f"telegram_data/images/{name}"})
        if score is not None:
            predictions.append({"image_path": f"/data2/DATA/telegram_data/images/{name}",
                                "source_id": source_id, "carrier_probability": score,
                                "predicted_aircraft_carrier": index == 0})
    prediction_path = tmp_path / "predictions.json"
    write_json(prediction_path, {
        "schema_version": 2, "runs": {"example_run": {"report_path": "/unused/report.json"}},
        "mining_threshold": 0.95, "predictions": predictions,
    })
    settings = DataSettings(tmp_path / "telegram.json", root, prediction_path)
    write_json(settings.telegram_path, telegram)
    return settings


def test_observation_contract_filename_join_dates_and_unknown(dataset):
    store = load_store(dataset)
    rows = {o.images[0].caption.split("<b>")[1].split("</b>")[0]: o for o in store.observations}
    assert rows["SCENE_0"].classification == "aircraft_carrier"
    assert rows["SCENE_0"].confidence == 0.5
    assert rows["SCENE_1"].classification == "not_aircraft_carrier"
    assert rows["SCENE_1"].confidence == 0.1
    assert rows["SCENE_2"].classification == "unknown"
    assert rows["SCENE_2"].confidence is None
    assert len({o.ship_id for o in rows.values()}) == 3
    assert all(observation.ship_id == source_id for source_id, observation in rows.items())
    for observation in rows.values():
        assert set(observation.model_dump()) == {
            "observation_id", "ship_id", "ship_url", "observed_date", "observed_at",
            "length_m", "width_m", "position", "classification", "confidence", "images",
        }
        assert observation.observed_date == "2026-10-13"
        assert observation.observed_at == "2026-10-13T18:00:00+00:00"
        assert observation.length_m == 300 and observation.width_m == 60


def test_api_pagination_filters_details_images_and_health(dataset):
    with TestClient(create_app(dataset)) as client:
        health = client.get("/health").json()
        assert health["observation_count"] == 3
        assert health["prediction_count"] == 2 and health["unknown_count"] == 1
        assert health["is_mock"] is False
        assert health["timezone"] == "UTC"
        assert "threshold" not in health
        assert health["runs"] == ["example_run"]
        first = client.get("/observations", params={"limit": 1}).json()
        second = client.get("/observations", params={"limit": 1, "offset": 1}).json()
        assert first["total"] == 3
        observation = first["observations"][0]
        assert observation["ship_id"] != second["observations"][0]["ship_id"]
        assert client.get(observation["ship_url"]).json() == observation
        image = client.get(observation["images"][0]["url"])
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/jpeg"
        assert image.content.startswith(b"synthetic-image-")
        assert client.get("/observations?observed_from=2026-10-13&observed_to=2026-10-13").json()["total"] == 3
        assert client.get("/observations?observed_from=2026-10-14").json()["observations"] == []
        assert client.get("/observations?offset=100").json()["total"] == 3
        assert client.get("/ships/unknown").status_code == 404
        assert client.get("/images/photo_0.jpg").status_code == 404
        assert client.get("/images/..%2Ftracking.json").status_code == 404


@pytest.mark.parametrize("query", [
    "limit=101", "limit=0", "offset=-1", "observed_from=2026-02-30",
    "observed_from=2026-10-15&observed_to=2026-10-14",
])
def test_api_invalid_queries(dataset, query):
    with TestClient(create_app(dataset)) as client:
        assert client.get(f"/observations?{query}").status_code == 422


def test_same_detection_multiple_images_are_separate_ships(dataset):
    rows = json.loads(dataset.telegram_path.read_text(encoding="utf-8"))
    rows.append({**rows[0], "image": "telegram_data/images/another.jpg"})
    (dataset.image_root / "another.jpg").write_bytes(b"another")
    rows.append(rows[0])
    write_json(dataset.telegram_path, rows)
    store = load_store(dataset)
    assert len(store.observations) == 4
    assert store.summary["prediction_count"] == 2
    other = next(o for o in store.observations if o.images[0].caption == rows[0]["caption"]
                 and o.confidence is None)
    assert other.classification == "unknown"
    assert store.summary["skipped"]["duplicate_image"] == 1
    same_id = [o for o in store.observations if o.ship_id == "SCENE_0"]
    assert len(same_id) == 2
    assert len({o.ship_url for o in same_id}) == 2
    with TestClient(create_app(dataset)) as client:
        for observation in same_id:
            assert client.get(observation.ship_url).json() == observation.model_dump()
        assert client.get("/ships/SCENE_0?observation_id=missing").status_code == 404


def test_skipped_records_are_visible_in_health(dataset):
    rows = json.loads(dataset.telegram_path.read_text(encoding="utf-8"))
    rows.extend([{}, {"caption": "- Tàu: SCENE_0", "image": "missing.jpg"}])
    write_json(dataset.telegram_path, rows)
    store = load_store(dataset)
    assert store.summary["skipped"] == dict(missing_detection_id=1, missing_image=1,
                                           duplicate_image=0, unsupported_image=0)


@pytest.mark.parametrize("change", ["score", "label", "duplicate_image", "missing_image", "shape"])
def test_reject_invalid_or_ambiguous_predictions(dataset, change):
    report = json.loads(dataset.predictions_path.read_text())
    if change == "score":
        report["predictions"][0]["carrier_probability"] = float("nan")
    elif change == "label":
        report["predictions"][0]["predicted_aircraft_carrier"] = "false"
    elif change == "duplicate_image":
        report["predictions"].append(report["predictions"][0])
    elif change == "missing_image":
        report["predictions"][0].pop("image_path")
    else:
        report["predictions"] = {}
    write_json(dataset.predictions_path, report)
    with pytest.raises(ValueError):
        with TestClient(create_app(dataset)):
            pass


def test_invalid_telegram_json_fails_startup(dataset):
    dataset.telegram_path.write_text('[{"message_id": broken}]', encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid JSON.*line 1"):
        load_store(dataset)


def test_image_removed_after_startup_returns_404(dataset):
    with TestClient(create_app(dataset)) as client:
        observation = client.get("/observations").json()["observations"][0]
        for path in dataset.image_root.iterdir():
            path.unlink()
        assert client.get(observation["images"][0]["url"]).status_code == 404


def test_symlink_outside_image_root_is_not_served(dataset, tmp_path):
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"outside")
    path = dataset.image_root / "photo_0.jpg"
    path.unlink()
    try:
        path.symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks requires privileges on this platform.")
    store = load_store(dataset)
    assert store.summary["skipped"]["missing_image"] == 1


def test_settings_from_config_file(dataset, monkeypatch):
    for name, value in {
        "TELEGRAM_METADATA_PATH": dataset.telegram_path,
        "TELEGRAM_IMAGE_ROOT": dataset.image_root,
        "PREDICTIONS_PATH": dataset.predictions_path,
        "DATA_API_BASE_URL": "http://mid:8001/",
    }.items():
        monkeypatch.setattr(config, name, value)
    assert DataSettings.from_config().base_url == "http://mid:8001"
    assert load_store(DataSettings.from_config()).observations[0].ship_url.startswith("http://mid:8001/")
    monkeypatch.setattr(config, "PREDICTIONS_PATH", "")
    with pytest.raises(ValueError, match="PREDICTIONS_PATH.*config.py"):
        DataSettings.from_config()


def test_invalid_caption_reports_filename(dataset):
    rows = json.loads(dataset.telegram_path.read_text(encoding="utf-8"))
    rows[0]["caption"] = "- Tàu: SCENE_0"
    write_json(dataset.telegram_path, rows)
    with pytest.raises(ValueError, match="photo_0.jpg.*missing position"):
        load_store(dataset)
