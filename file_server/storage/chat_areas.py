"""One confirmed area per Open WebUI user/chat, persisted as atomic JSON files."""

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
from threading import RLock

from file_server.schemas.geometry import UserPolygon
from file_server.services.spatial import AREA_NAMES


class AreaConflict(ValueError):
    """Another map changed the confirmed area since this map last read it."""


def validate_active_area(value):
    """Keep custom GeoJSON small; named boundaries remain shared by key."""
    if value is None:
        return None
    if isinstance(value, dict) and value.get("type") == "preset":
        if (set(value) != {"type", "key"} or not isinstance(value.get("key"), str)
                or value["key"] not in AREA_NAMES):
            raise ValueError("Chỉ Biển Đông và Vịnh Bắc Bộ có polygon định nghĩa sẵn.")
        return dict(value)
    return UserPolygon.model_validate(value).model_dump()


class ChatAreaStore:
    """Thread-safe for the single-process ThreadingHTTPServer map runner."""

    def __init__(self, root):
        self.root = Path(root)
        self._lock = RLock()
        self._sessions = {}

    @staticmethod
    def _identity(user_id, chat_id):
        if any(not isinstance(value, str) or not value.strip() or len(value) > 200
               for value in (user_id, chat_id)):
            raise ValueError("Thiếu user_id hoặc chat_id hợp lệ.")
        return sha256(json.dumps([user_id, chat_id]).encode()).hexdigest()

    def _read(self, path):
        record = json.loads(path.read_text(encoding="utf-8"))
        validate_active_area(record["active_area"])
        if (not re.fullmatch(r"[a-f0-9]{64}", record["session_id"])
                or type(record["revision"]) is not int or record["revision"] < 0
                or path.stem != self._identity(record["user_id"], record["chat_id"])):
            raise ValueError("File vùng chat không hợp lệ.")
        return record

    def _write(self, path, record):
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.root,
                                             delete=False) as output:
                temporary = Path(output.name)
                json.dump(record, output, ensure_ascii=False, allow_nan=False)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def ensure(self, user_id, chat_id):
        path = self.root / f"{self._identity(user_id, chat_id)}.json"
        with self._lock:
            if path.exists():
                record = self._read(path)
            else:
                record = {"user_id": user_id, "chat_id": chat_id,
                          "session_id": secrets.token_hex(32), "active_area": None,
                          "revision": 0, "updated_at": self._now()}
                self._write(path, record)
            self._sessions[record["session_id"]] = path
            return deepcopy(record)

    def _path(self, session_id):
        if not isinstance(session_id, str) or not re.fullmatch(r"[a-f0-9]{64}", session_id):
            raise KeyError("Không tìm thấy phiên map.")
        path = self._sessions.get(session_id)
        if path is not None:
            return path
        for path in self.root.glob("*.json"):
            record = self._read(path)
            self._sessions[record["session_id"]] = path
            if record["session_id"] == session_id:
                return path
        raise KeyError("Không tìm thấy phiên map.")

    def get(self, session_id):
        with self._lock:
            return deepcopy(self._read(self._path(session_id)))

    def set_area(self, session_id, active_area, expected_revision):
        area = validate_active_area(active_area)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("Thiếu phiên bản vùng hợp lệ.")
        with self._lock:
            path = self._path(session_id)
            record = self._read(path)
            if record["revision"] != expected_revision:
                raise AreaConflict("Vùng đã đổi ở cửa sổ khác. Tải lại vùng đã lưu trước khi xác nhận.")
            record.update(active_area=area, revision=record["revision"] + 1,
                          updated_at=self._now())
            self._write(path, record)
            return deepcopy(record)

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
