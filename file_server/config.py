"""Edit these data-server settings on MID, then restart the server."""

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


# Observation times in Telegram captions are UTC.
TELEGRAM_METADATA_PATH = Path("/data2/DATA/telegram_data/data.json")
TELEGRAM_IMAGE_ROOT = Path("/data2/DATA/telegram_data/images")

# Set to the run folder containing originals_manifest.json and
# offline_cloud_crop_staged/report.json. No checkpoint is needed.
SAVED_RUN_DIR = ""
SAVED_RUN_SEED = 42

# URL reachable by the image viewer. Match the Uvicorn port to this URL.
DATA_API_BASE_URL = "http://127.0.0.1:8001"


@dataclass(frozen=True)
class DataSettings:
    telegram_path: Path
    image_root: Path
    saved_run_dir: Path
    base_url: str = "http://127.0.0.1:8001"
    seed: int = 42

    def __post_init__(self):
        url = urlsplit(self.base_url)
        if (url.scheme not in {"http", "https"} or not url.hostname
                or url.username or url.password or url.query or url.fragment):
            raise ValueError("DATA_API_BASE_URL must be an HTTP(S) base URL.")

    @classmethod
    def from_config(cls) -> "DataSettings":
        def required_path(name: str, value: str | Path) -> Path:
            if not str(value).strip():
                raise ValueError(f"Set {name} in file_server/config.py before starting the server.")
            return Path(value).expanduser().resolve()

        return cls(
            telegram_path=required_path("TELEGRAM_METADATA_PATH", TELEGRAM_METADATA_PATH),
            image_root=required_path("TELEGRAM_IMAGE_ROOT", TELEGRAM_IMAGE_ROOT),
            saved_run_dir=required_path("SAVED_RUN_DIR", SAVED_RUN_DIR),
            base_url=DATA_API_BASE_URL.rstrip("/"),
            seed=SAVED_RUN_SEED,
        )
