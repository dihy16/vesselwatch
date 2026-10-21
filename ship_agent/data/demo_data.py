"""Fixed, source-verified satellite crops shared by every recording-demo tool."""

import base64
from datetime import date
import hashlib
from html import escape
import json
import mimetypes
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from file_server.schemas.observations import Observation


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEMO_REFERENCE_DATE = date(2025, 12, 30)


def demo_root() -> Path:
    return Path(os.environ.get("VESSELWATCH_DEMO_DIR", PROJECT_ROOT / "data/demo")).resolve()


def public_base_url() -> str:
    value = os.environ.get("VESSELWATCH_DEMO_PUBLIC_URL", "http://127.0.0.1:8002").rstrip("/")
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("VESSELWATCH_DEMO_PUBLIC_URL must be an HTTP(S) base URL.")
    return value


def read_snapshot() -> dict:
    path = demo_root() / "snapshot.json"
    if not path.is_file():
        raise FileNotFoundError("Missing demo snapshot. Run python scripts/prepare_demo_data.py first.")
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1 or not document.get("observations"):
        raise ValueError("Invalid or empty demo snapshot.")
    payload = {key: value for key, value in document.items() if key != "snapshot_id"}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    if digest != document.get("snapshot_id"):
        raise ValueError("Demo snapshot was modified; regenerate it from the source data.")
    ids = [row["ship_id"] for row in document["observations"]]
    observation_ids = [row["observation_id"] for row in document["observations"]]
    image_ids = [row["image_id"] for row in document["observations"]]
    if any(len(values) != len(set(values)) for values in (ids, observation_ids, image_ids)):
        raise ValueError("Demo snapshot contains duplicate identities.")
    return document


def image_path(record: dict) -> Path:
    root = (demo_root() / "images").resolve()
    path = (root / record["image_file"]).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise ValueError("Invalid demo image path.")
    if hashlib.sha256(path.read_bytes()).hexdigest() != record["image_sha256"]:
        raise ValueError("Demo crop does not match its saved model input.")
    return path


def load_demo_observations() -> list[dict]:
    base = public_base_url()
    observations = []
    for row in read_snapshot()["observations"]:
        path = image_path(row)
        observation = Observation.model_validate({
            **row, "ship_url": f"{base}/ships/{row['ship_id']}",
            "images": [{"image_id": row["image_id"], "url": f"{base}/images/{row['image_id']}",
                        "mime_type": mimetypes.guess_type(path.name)[0],
                        "caption": f"{row['ship_id']} · Ảnh vệ tinh · {row['observed_at']}"}],
        })
        observations.append(observation.model_dump())
    return observations


def demo_gallery(report: dict) -> str:
    """Embed only matching carrier crops; no image request or base64 goes to the LLM."""
    snapshot = read_snapshot()
    if report.get("demo_snapshot_id") != snapshot["snapshot_id"]:
        raise ValueError("Report and demo images must come from the same snapshot.")
    selected = [row for row in snapshot["observations"]
                if row["classification"] == "aircraft_carrier"
                and report["observed_from"] <= row["observed_date"] <= report["observed_to"]][:3]
    if not selected:
        return ""
    cards = []
    for row in selected:
        path = image_path(row)
        uri = f"data:{mimetypes.guess_type(path.name)[0]};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"
        cards.append(
            f'<figure><img src="{uri}" alt="{escape(row["ship_id"], quote=True)}">'
            f'<figcaption><strong>{escape(row["ship_id"])}</strong> · {escape(row["observed_date"])}'
            f'<br>{row["length_m"]:.1f} × {row["width_m"]:.1f} m</figcaption></figure>'
        )
    return ('<section class="demo-gallery"><h2>Ảnh tàu sân bay trong bộ demo</h2>'
            '<p class="muted">Ảnh cắt vệ tinh và kết quả đã lưu; không chạy nhận diện mới.</p>'
            f'<div class="image-grid">{"".join(cards)}</div></section>')


def wants_demo_images(messages) -> bool:
    from langchain_core.messages import HumanMessage
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            request = message.text.lower()
            return (any(phrase in request for phrase in ("xem ảnh", "hiển thị ảnh"))
                    and not any(phrase in request for phrase in ("không cần", "chưa cần", "không hiển thị")))
    return False


def demo_image_markdown(messages, response_text: str) -> str:
    """Attach the current search's exact URLs when the model omits an image."""
    from langchain_core.messages import HumanMessage, ToolMessage
    if not wants_demo_images(messages):
        return ""
    images = {}
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        if isinstance(message, ToolMessage) and message.name == "search_ships":
            # A failed correction must not expose an earlier successful result.
            if message.status == "error":
                return ""
            result = json.loads(message.content)
            if not result.get("is_demo"):
                continue
            for ship in result["ships"]:
                for image in ship["images"]:
                    images.setdefault(image["url"], ship["ship_id"])
            break
    return "\n\n".join(
        f"![{ship_id}]({url})" for url, ship_id in list(images.items())[:3]
        if not re.search(r"!\[[^\]]*\]\(" + re.escape(url) + r"\)", response_text)
    )
