"""Extract observation fields from Telegram captions; observation times are UTC."""

from dataclasses import dataclass
from datetime import datetime, timezone
import re


NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
SHIP_PATTERN = re.compile(r"Tàu\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
POSITION_PATTERN = re.compile(
    rf"Vị trí\s*:\s*\[\s*({NUMBER})\s*,\s*({NUMBER})\s*\]", re.IGNORECASE,
)
DIMENSION_PATTERN = re.compile(
    rf"Dài\s*/\s*Rộng\s*:\s*({NUMBER})\s*\(m\)\s*/\s*({NUMBER})\s*\(m\)",
    re.IGNORECASE,
)
TIME_PATTERN = re.compile(
    r"Thời gian\s*:\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", re.IGNORECASE,
)


def clean_caption(caption: str) -> str:
    return re.sub(r"<[^>]+>", "", caption)


@dataclass(frozen=True)
class CaptionMetadata:
    source_id: str
    latitude: float
    longitude: float
    length_m: float
    width_m: float
    observed_at: datetime


def parse_caption(caption: str) -> CaptionMetadata:
    """Use the caption's acquisition time, never the Telegram post date."""
    cleaned = clean_caption(caption)
    matches = {
        "detection ID": SHIP_PATTERN.search(cleaned),
        "position": POSITION_PATTERN.search(cleaned),
        "dimensions": DIMENSION_PATTERN.search(cleaned),
        "observation time": TIME_PATTERN.search(cleaned),
    }
    for field, match in matches.items():
        if match is None:
            raise ValueError(f"Telegram caption is missing {field}.")
    captured = datetime.strptime(
        " ".join(matches["observation time"].group(1).split()), "%Y-%m-%d %H:%M:%S",
    ).replace(tzinfo=timezone.utc)
    return CaptionMetadata(
        source_id=matches["detection ID"].group(1).strip(),
        latitude=float(matches["position"].group(1)),
        longitude=float(matches["position"].group(2)),
        length_m=float(matches["dimensions"].group(1)),
        width_m=float(matches["dimensions"].group(2)),
        observed_at=captured,
    )
