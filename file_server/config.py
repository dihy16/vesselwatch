"""Edit these data-server settings on MID, then restart the server."""

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
import math


# Read the same local_config.json, manifest, and saved run as the persistent map.
DATA_SOURCE = "map_bundle"  # Set to "telegram" to use the legacy paths below.
MAP_DEMO_DIR = Path(__file__).resolve().parents[1] / "data/exports/vessel-map-demo"
MAP_CARRIER_THRESHOLD = 0.5  # Same as the map's default 50% candidate threshold.

# Legacy Telegram configuration (used only when DATA_SOURCE == "telegram").
TELEGRAM_METADATA_PATH = Path("/data2/DATA/telegram_data/data.json")
TELEGRAM_IMAGE_ROOT = Path("/data2/DATA/telegram_data/images")

# Set to the JSON file containing the exported predictions array.
PREDICTIONS_PATH = "data/predictions.json"

# URL reachable by the image viewer. Match the Uvicorn port to this URL.
DATA_API_BASE_URL = "http://127.0.0.1:8001"

# Keep confirmed custom areas across restarts (ignored local data).
AREA_QUERY_DIR = Path("data/area_queries/real")

# User-supplied carrier description.md and example images, kept out of Git.
CARRIER_REFERENCE_DIR = Path(__file__).resolve().parents[1] / "data/carrier_references"


@dataclass(frozen=True)
class DataSettings:
    telegram_path: Path
    image_root: Path
    predictions_path: Path
    base_url: str = "http://127.0.0.1:8001"
    data_source: str = "telegram"
    map_demo_dir: Path | None = None
    carrier_threshold: float = 0.5
    carrier_reference_dir: Path | None = None

    def __post_init__(self):
        if self.data_source not in {"telegram", "map_bundle"}:
            raise ValueError("DATA_SOURCE must be telegram or map_bundle.")
        if (type(self.carrier_threshold) not in (int, float)
                or not math.isfinite(self.carrier_threshold)
                or not 0 <= self.carrier_threshold <= 1):
            raise ValueError("MAP_CARRIER_THRESHOLD must be between 0 and 1.")
        if self.data_source == "map_bundle" and self.map_demo_dir is None:
            raise ValueError("Set MAP_DEMO_DIR in file_server/config.py.")
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
            telegram_path=(required_path("TELEGRAM_METADATA_PATH", TELEGRAM_METADATA_PATH)
                           if DATA_SOURCE == "telegram" else Path()),
            image_root=(required_path("TELEGRAM_IMAGE_ROOT", TELEGRAM_IMAGE_ROOT)
                        if DATA_SOURCE == "telegram" else Path()),
            predictions_path=(required_path("PREDICTIONS_PATH", PREDICTIONS_PATH)
                              if DATA_SOURCE == "telegram" else Path()),
            base_url=DATA_API_BASE_URL.rstrip("/"),
            data_source=DATA_SOURCE,
            map_demo_dir=(required_path("MAP_DEMO_DIR", MAP_DEMO_DIR)
                          if DATA_SOURCE == "map_bundle" else None),
            carrier_threshold=MAP_CARRIER_THRESHOLD,
            carrier_reference_dir=required_path("CARRIER_REFERENCE_DIR", CARRIER_REFERENCE_DIR),
        )
