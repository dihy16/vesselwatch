"""Configuration checks using only the Python standard library."""

from pathlib import Path
import unittest
from unittest.mock import patch

from file_server import config


class TestDataConfig(unittest.TestCase):
    def test_configuration_uses_file_values_and_ignores_environment(self):
        values = {"TELEGRAM_METADATA_PATH": "metadata.json", "TELEGRAM_IMAGE_ROOT": "images",
                  "PREDICTIONS_PATH": "predictions.json",
                  "DATA_API_BASE_URL": "http://mid:8001/", "DATA_SOURCE": "telegram"}
        with patch.multiple(config, **values), patch.dict("os.environ", {
            "PREDICTIONS_PATH": "wrong.json", "DATA_API_BASE_URL": "http://wrong:9999",
        }):
            settings = config.DataSettings.from_config()
        self.assertEqual(settings.predictions_path, Path("predictions.json").resolve())
        self.assertEqual(settings.telegram_path, Path("metadata.json").resolve())
        self.assertEqual(settings.base_url, "http://mid:8001")

    def test_empty_predictions_configuration_reports_file_to_edit(self):
        with patch.multiple(config, DATA_SOURCE="telegram", PREDICTIONS_PATH=""):
            with self.assertRaisesRegex(ValueError, r"PREDICTIONS_PATH.*file_server/config.py"):
                config.DataSettings.from_config()

    def test_map_source_does_not_require_legacy_telegram_paths(self):
        with patch.multiple(config, DATA_SOURCE="map_bundle", PREDICTIONS_PATH="",
                            TELEGRAM_METADATA_PATH="", TELEGRAM_IMAGE_ROOT="",
                            MAP_DEMO_DIR="data/exports/vessel-map-demo"):
            settings = config.DataSettings.from_config()
        self.assertEqual(settings.data_source, "map_bundle")
        self.assertEqual(settings.map_demo_dir, Path("data/exports/vessel-map-demo").resolve())

    def test_invalid_url_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "DATA_API_BASE_URL"):
            config.DataSettings(Path("metadata.json"), Path("images"), Path("predictions.json"), "file:///images")


if __name__ == "__main__":
    unittest.main()
