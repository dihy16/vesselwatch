"""Join Telegram observations and exported predictions by image filename."""

from dataclasses import dataclass
import hashlib
import json
import math
import mimetypes
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field

from .caption import SHIP_PATTERN, clean_caption, parse_caption
from .config import DataSettings


class Position(BaseModel):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)


class ImageInfo(BaseModel):
    image_id: str
    url: str
    mime_type: str
    caption: str


class Observation(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    observation_id: str
    ship_id: str
    ship_url: str
    observed_date: str
    observed_at: str
    length_m: float = Field(gt=0)
    width_m: float = Field(gt=0)
    position: Position
    classification: Literal["aircraft_carrier", "not_aircraft_carrier", "unknown"]
    confidence: float | None = Field(ge=0, le=1)
    images: list[ImageInfo]


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON in {path} at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc


def read_records(path: Path) -> list[dict]:
    records = read_json(path)
    if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
        raise ValueError(f"{path} must contain a JSON array of objects.")
    return records


@dataclass(frozen=True)
class Prediction:
    score: float
    classification: Literal["aircraft_carrier", "not_aircraft_carrier"]


def image_filename(value: object) -> str:
    """Use the same filename key for exported and Telegram image paths."""
    return value.replace("\\", "/").rsplit("/", 1)[-1] if isinstance(value, str) else ""


def load_predictions(path: Path) -> tuple[dict[str, Prediction], dict]:
    """Read exported scores and labels without recomputing either."""
    report = read_json(path)
    if not isinstance(report, dict) or not isinstance(report.get("predictions"), list):
        raise ValueError(f"{path} must contain an object with a predictions array.")
    predictions = {}
    for index, row in enumerate(report["predictions"]):
        if not isinstance(row, dict):
            raise ValueError(f"Invalid prediction at index {index} in {path}.")
        name = image_filename(row.get("image_path"))
        score = row.get("carrier_probability")
        label = row.get("predicted_aircraft_carrier")
        if (not name or name in {".", ".."}
                or type(score) not in (int, float) or not math.isfinite(score)
                or not 0 <= score <= 1 or type(label) is not bool):
            raise ValueError(f"Invalid prediction for {name or index} in {path}: "
                             "expected image_path, probability in [0, 1], and boolean label.")
        if name in predictions:
            raise ValueError(f"Duplicate prediction for image {name} in {path}.")
        predictions[name] = Prediction(
            float(score), "aircraft_carrier" if label else "not_aircraft_carrier",
        )
    # Provenance only: these paths are never opened by the file server.
    metadata = {"runs": list(report.get("runs", {})),
                "ensemble_method": report.get("ensemble_method")}
    return predictions, metadata


def registered_image(root: Path, name: str) -> Path | None:
    """Resolve only an image filename inside the configured image directory."""
    candidate = (root / name).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    return candidate


@dataclass
class ObservationStore:
    observations: list[Observation]
    ships: dict[str, Observation]
    images: dict[str, tuple[str, str]]
    image_root: Path
    summary: dict


def load_store(settings: DataSettings) -> ObservationStore:
    predictions, prediction_metadata = load_predictions(settings.predictions_path)
    root = settings.image_root.resolve()
    if not root.is_dir():
        raise ValueError(f"Telegram image directory does not exist: {root}")
    observations = []
    images = {}
    seen = {}
    counts = dict(missing_detection_id=0, missing_image=0,
                  duplicate_image=0, unsupported_image=0)
    for message in read_records(settings.telegram_path):
        caption = message.get("caption", "")
        cleaned = clean_caption(caption) if isinstance(caption, str) else ""
        match = SHIP_PATTERN.search(cleaned)
        if not match:
            counts["missing_detection_id"] += 1
            continue
        source_id = match.group(1).strip()
        # Telegram exports use telegram_data/images/<filename>, while root is images/.
        value = message.get("image")
        name = image_filename(value)
        if not name or registered_image(root, name) is None:
            counts["missing_image"] += 1
            continue
        mime = mimetypes.guess_type(name)[0]
        if mime not in {"image/jpeg", "image/png", "image/webp", "image/gif", "image/tiff", "image/bmp"}:
            counts["unsupported_image"] += 1
            continue
        if name in seen:
            if seen[name] != source_id:
                raise ValueError(f"Telegram image {name} links to multiple detection IDs.")
            counts["duplicate_image"] += 1
            continue
        seen[name] = source_id
        try:
            metadata = parse_caption(caption)
            captured = metadata.observed_at
            prediction = predictions.get(name)
            score = prediction.score if prediction is not None else None
            classification = prediction.classification if prediction is not None else "unknown"
            # Filename identity makes separate Telegram images separate ships.
            token = hashlib.sha256(name.encode("utf-8")).hexdigest()
            ship_id, image_id = metadata.source_id, f"IMG_{token}"
            base = settings.base_url.rstrip("/")
            observation = Observation(
                observation_id=f"OBS_{token}", ship_id=ship_id,
                ship_url=f"{base}/ships/{quote(ship_id, safe='')}?observation_id=OBS_{token}",
                observed_date=captured.date().isoformat(), observed_at=captured.isoformat(),
                length_m=metadata.length_m, width_m=metadata.width_m,
                position=Position(latitude=metadata.latitude, longitude=metadata.longitude),
                classification=classification, confidence=score,
                images=[ImageInfo(image_id=image_id, url=f"{base}/images/{image_id}",
                                  mime_type=mime, caption=caption)],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid Telegram observation for {name} (detection {source_id}): {exc}"
            ) from exc
        observations.append(observation)
        images[image_id] = (name, mime)
    observations.sort(key=lambda observation: observation.ship_id)
    matched = sum(observation.confidence is not None for observation in observations)
    summary = {"observation_count": len(observations), "prediction_count": matched,
               "unknown_count": len(observations) - matched, "skipped": counts,
               **prediction_metadata}
    # A caption ID may occur in several images; direct links select the exact observation.
    ships = {}
    for observation in observations:
        previous = ships.get(observation.ship_id)
        if previous is None or observation.observed_at > previous.observed_at:
            ships[observation.ship_id] = observation
    return ObservationStore(observations, ships, images, root, summary)
