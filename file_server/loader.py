"""Join Telegram observations and saved crop predictions on detection IDs."""

from dataclasses import dataclass
import hashlib
import json
import math
import mimetypes
from pathlib import Path
import re
from typing import Literal

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


def load_predictions(run_dir: Path, seed: int) -> tuple[dict[str, float], str]:
    """Validate saved predictions against their original manifest, as in the demo."""
    manifest = read_json(run_dir / "originals_manifest.json")
    report = read_json(run_dir / "offline_cloud_crop_staged" / "report.json")
    items = manifest["items"]
    by_path = {item["image_path"]: item for item in items}
    if len(by_path) != len(items):
        raise ValueError("Saved manifest has duplicate image paths.")
    splits = report.get("seed_predictions", {}).get(str(seed))
    if not isinstance(splits, dict):
        raise ValueError(f"Saved run has no predictions for seed {seed}.")
    predictions = {}
    hashes = set()
    for split, rows in splits.items():
        for row in rows:
            item = by_path.get(row.get("image_path"))
            score = row.get("score")
            if (item is None or item.get("split") != split or item.get("label") != row.get("label")
                    or type(score) not in (int, float) or not math.isfinite(score)
                    or not 0 <= score <= 1):
                raise ValueError("Saved prediction does not match its original crop manifest.")
            source_id = item.get("source_id")
            digest = item.get("sha256")
            if not isinstance(source_id, str) or not source_id.strip():
                raise ValueError("Predicted crop has no source_id.")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("Predicted crop has an invalid SHA-256.")
            if digest in hashes or source_id in predictions:
                raise ValueError(f"Ambiguous saved prediction for source_id {source_id}.")
            hashes.add(digest)
            predictions[source_id] = float(score)
    return predictions, f"{report['model']} / seed {seed} / {run_dir.name}"


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
    predictions, model = load_predictions(settings.saved_run_dir, settings.seed)
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
        name = value.replace("\\", "/").rsplit("/", 1)[-1] if isinstance(value, str) else ""
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
            score = predictions.get(source_id)
            classification = ("unknown" if score is None else
                              "aircraft_carrier" if score >= 0.5 else "not_aircraft_carrier")
            # Filename identity makes separate Telegram images separate ships.
            token = hashlib.sha256(name.encode("utf-8")).hexdigest()
            ship_id, image_id = f"SHIP_{token}", f"IMG_{token}"
            base = settings.base_url.rstrip("/")
            observation = Observation(
                observation_id=f"OBS_{token}", ship_id=ship_id,
                ship_url=f"{base}/ships/{ship_id}",
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
               "model": model, "seed": settings.seed, "threshold": 0.5}
    return ObservationStore(observations, {o.ship_id: o for o in observations}, images, root, summary)
