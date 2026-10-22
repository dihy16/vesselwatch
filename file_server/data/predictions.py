"""Load authoritative prediction exports without recomputing labels."""

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Literal

from file_server.data.json_io import read_json


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
