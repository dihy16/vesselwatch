"""Persistent, self-contained map snapshots for the recording demo."""

import base64
from datetime import date
from hashlib import sha256
import json
import mimetypes
import os
from pathlib import Path
import re
import tempfile
from typing import Annotated, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .demo_data import demo_root, image_path, public_base_url


DateString = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]


class MapFilters(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    observed_from: DateString
    observed_to: DateString
    ship_id: str | None = None
    classification: Literal["aircraft_carrier", "not_aircraft_carrier", "unknown"] | None = None
    min_length_m: float | None = Field(default=None, ge=0)
    max_length_m: float | None = Field(default=None, ge=0)
    min_width_m: float | None = Field(default=None, ge=0)
    max_width_m: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_range(self):
        first, last = date.fromisoformat(self.observed_from), date.fromisoformat(self.observed_to)
        if not 0 <= (last - first).days < 366:
            raise ValueError("Bản đồ hỗ trợ từ 1 đến 366 ngày, gồm cả hai đầu mốc.")
        for dimension in ("length_m", "width_m"):
            minimum, maximum = getattr(self, "min_" + dimension), getattr(self, "max_" + dimension)
            if minimum is not None and maximum is not None and minimum > maximum:
                raise ValueError(f"min_{dimension} phải nhỏ hơn hoặc bằng max_{dimension}.")
        return self


class CreateMapInput(MapFilters):
    expected_snapshot_id: str = Field(pattern=r"^[a-f0-9]{64}$")


def map_root() -> Path:
    return Path(os.environ.get("VESSELWATCH_DEMO_MAP_DIR", demo_root() / "maps")).resolve()


def _serialized(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def select_records(snapshot: dict, filters: MapFilters) -> list[dict]:
    selected = []
    for row in snapshot["observations"]:
        if not filters.observed_from <= row["observed_date"] <= filters.observed_to:
            continue
        if filters.ship_id is not None and row["ship_id"] != filters.ship_id:
            continue
        if filters.classification is not None and row["classification"] != filters.classification:
            continue
        if any((getattr(filters, "min_" + key) is not None and row[key] < getattr(filters, "min_" + key))
               or (getattr(filters, "max_" + key) is not None and row[key] > getattr(filters, "max_" + key))
               for key in ("length_m", "width_m")):
            continue
        selected.append(row)
    return sorted(selected, key=lambda row: row["ship_id"])


def save_map(snapshot: dict, filters: MapFilters) -> dict:
    """Embed original verified crops so old maps survive dataset replacement."""
    vessels = []
    for row in select_records(snapshot, filters):
        path = image_path(row)
        mime = mimetypes.guess_type(path.name)[0]
        vessels.append({
            "id": row["observation_id"], "name": row["ship_id"],
            "captured_at": row["observed_at"], **row["position"],
            "image_path": f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}",
            "prediction": {"carrier_score": row["confidence"],
                           "model": snapshot.get("source", {}).get("model", "Saved model")},
            "metadata": {"source_id": row["ship_id"], "length_m": row["length_m"],
                         "width_m": row["width_m"], "classification": row["classification"]},
        })
    payload = {"schema_version": 1, "source_snapshot_id": snapshot["snapshot_id"],
               "filters": filters.model_dump(), "vessels": vessels}
    raw = _serialized(payload)
    map_id = sha256(raw).hexdigest()
    root = map_root()
    root.mkdir(parents=True, exist_ok=True)
    # Each writer owns its temporary file; parallel identical requests are safe.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=root, suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(raw)
        os.replace(temporary, root / f"{map_id}.json")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return map_summary(map_id, payload)


def read_map(map_id: str) -> dict:
    if not re.fullmatch(r"[a-f0-9]{64}", map_id):
        raise FileNotFoundError("Map not found.")
    payload = json.loads((map_root() / f"{map_id}.json").read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or sha256(_serialized(payload)).hexdigest() != map_id:
        raise ValueError("Map snapshot was modified; create a new map.")
    return payload


def map_summary(map_id: str, payload: dict) -> dict:
    return {"map_id": map_id, "map_url": f"{public_base_url()}/maps/{map_id}",
            "total": len(payload["vessels"]), "filters": payload["filters"],
            "source_snapshot_id": payload["source_snapshot_id"], "is_demo": True,
            "data_scope": "selected_demo_subset"}


def request_map(filters: MapFilters, snapshot_id: str, *, transport=None) -> dict:
    """Use the server address internally and its public URL only in browser links."""
    base = os.environ.get("VESSELWATCH_DEMO_API_URL", "http://127.0.0.1:8002").rstrip("/")
    with httpx.Client(base_url=base + "/", timeout=30, trust_env=False, transport=transport) as client:
        response = client.post("maps", json={**filters.model_dump(), "expected_snapshot_id": snapshot_id})
        response.raise_for_status()
        result = response.json()
    # A mismatch indicates stale agent/server snapshots or an invalid server response.
    if (not isinstance(result, dict) or result.get("source_snapshot_id") != snapshot_id
            or result.get("filters") != filters.model_dump()
            or not re.fullmatch(r"[a-f0-9]{64}", str(result.get("map_id", "")))
            or type(result.get("total")) is not int or result["total"] < 0):
        raise ValueError("Server trả snapshot bản đồ không hợp lệ.")
    # The agent's public URL is authoritative; never embed an arbitrary response URL.
    return {"map_id": result["map_id"], "map_url": f"{public_base_url()}/maps/{result['map_id']}",
            "total": result["total"], "filters": filters.model_dump(),
            "source_snapshot_id": snapshot_id, "is_demo": True, "data_scope": "selected_demo_subset"}
