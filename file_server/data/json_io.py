"""Read and validate dataset JSON files."""

import json
from pathlib import Path


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
