"""Configuration checks using only the Python standard library."""

from pathlib import Path
import unittest
from unittest.mock import patch

from file_server import config


class TestDataConfig(unittest.TestCase):
    def test_configuration_uses_file_values_and_ignores_environment(self):
        values = {"TELEGRAM_METADATA_PATH": "metadata.json", "TELEGRAM_IMAGE_ROOT": "images",
                  "SAVED_RUN_DIR": "run", "SAVED_RUN_SEED": 43,
                  "DATA_API_BASE_URL": "http://mid:8001/"}
        with patch.multiple(config, **values), patch.dict("os.environ", {
            "SAVED_RUN_DIR": "wrong-run", "DATA_API_BASE_URL": "http://wrong:9999",
        }):
            settings = config.DataSettings.from_config()
        self.assertEqual(settings.saved_run_dir, Path("run").resolve())
        self.assertEqual(settings.telegram_path, Path("metadata.json").resolve())
        self.assertEqual(settings.base_url, "http://mid:8001")
        self.assertEqual(settings.seed, 43)

    def test_empty_run_configuration_reports_file_to_edit(self):
        with patch.object(config, "SAVED_RUN_DIR", ""):
            with self.assertRaisesRegex(ValueError, r"SAVED_RUN_DIR.*file_server/config.py"):
                config.DataSettings.from_config()

    def test_invalid_url_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "DATA_API_BASE_URL"):
            config.DataSettings(Path("metadata.json"), Path("images"), Path("run"), "file:///images")


if __name__ == "__main__":
    unittest.main()
