"""Atomic JSON storage for confirmed area-query records."""

import json
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4


class AreaNotFound(LookupError):
    """An invalid or unavailable area identifier."""

def _write(root, record):
    root.mkdir(parents=True, exist_ok=True)
    area_id = uuid4().hex
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=root, delete=False) as output:
            temporary = Path(output.name)
            json.dump(record, output, ensure_ascii=False, allow_nan=False)
        os.replace(temporary, root / f"{area_id}.json")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return area_id

def _read(root, area_id):
    if not re.fullmatch(r"[a-f0-9]{32}", area_id):
        raise AreaNotFound("Không tìm thấy vùng truy vấn.")
    try:
        return json.loads((root / f"{area_id}.json").read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AreaNotFound("Không tìm thấy vùng truy vấn.") from exc
