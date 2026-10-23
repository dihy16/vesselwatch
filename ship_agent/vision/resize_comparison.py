"""Controlled, independent native-versus-resized vision requests and local reports."""

import base64
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
import json
from pathlib import Path
from time import perf_counter

from langchain_core.messages import HumanMessage, SystemMessage

from file_server.media.image_assets import ImageVariant, normalize_image, prepare_vision_image
from ship_agent.vision.image_review import _vision_model, reference_review_prompt, visual_review_prompt
from ship_agent.vision.schemas import CarrierReferenceReview, VisualReview
from ship_agent.workflows.reference_review import reference_review_content


def compare_resize(data, *, observation_id, library=None, model=None, prepare_only=False):
    """Only target pixels vary; prompts, reference pixels and settings stay fixed."""
    normalized, width, height = normalize_image(data)
    variants = {"original": ImageVariant(normalized, width, height, width, height),
                "resized": prepare_vision_image(data)}
    if variants["original"].data == variants["resized"].data:
        raise ValueError("Ảnh này không đổi kích thước theo quy tắc 224 px; hãy chọn một crop nhỏ hơn.")
    if library is not None and (not library.images or not library.description.strip()):
        raise ValueError("Bộ mẫu phải có mô tả và toàn bộ ảnh hợp lệ.")
    prompt = reference_review_prompt() if library is not None else visual_review_prompt()
    schema = CarrierReferenceReview if library is not None else VisualReview
    # Do not tell the model which condition it sees or change dimension text between calls.
    target_text = (f"TARGET — đánh giá ảnh tàu này. Kích thước gốc {width} × {height} px. "
                   "Ảnh đầu vào có thể được nội suy; không coi nội suy là chi tiết mới.")
    reviewer = None if prepare_only else model if model is not None else _vision_model()
    result = {"experiment": "target_resize_comparison", "observation_id": observation_id,
              "created_at": datetime.now(timezone.utc).isoformat(), "prepare_only": prepare_only,
              "model": getattr(reviewer, "model_name", None), "detail": "high",
              "source_sha256": sha256(data).hexdigest(), "system_prompt_sha256": sha256(prompt.encode()).hexdigest(),
              "reference_revision": library.revision if library is not None else None,
              "reference_count": len(library.images) if library is not None else 0,
              "reference_resize_policy": "production_224px_upscale_only" if library is not None else None,
              "conditions": [], "is_accuracy_evaluation": False}
    known = {image.reference_id for image in library.images} if library is not None else set()
    for name, variant in variants.items():
        if library is not None:
            content = reference_review_content(variant, library)
            content[0] = {"type": "text", "text": target_text}
        else:
            content = [{"type": "text", "text": target_text}, {"type": "image_url", "image_url": {
                "url": "data:image/png;base64," + base64.b64encode(variant.data).decode("ascii"), "detail": "high"}}]
        condition = {"name": name, **variant.metadata(), "input_sha256": sha256(variant.data).hexdigest(),
                     "status": "prepared", "raw_response": None, "parsed_response": None}
        if not prepare_only:
            started = perf_counter()
            try:
                response = reviewer.invoke([SystemMessage(content=prompt), HumanMessage(content=content)],
                                           config={"tags": ["nostream"]})
                condition["raw_response"] = response.text
                condition["usage"] = getattr(response, "usage_metadata", None)
                parsed = schema.model_validate_json(response.text)
                if library is not None and any(item.reference_id not in known for item in parsed.reference_evidence):
                    raise ValueError("Unknown reference citation")
                condition.update(status="complete", parsed_response=parsed.model_dump())
            except Exception:
                # Preserve returned text for inspection; provider exceptions may contain pixel request bodies.
                condition["status"] = "invalid_response" if condition["raw_response"] is not None else "request_failed"
                condition["error"] = "Phản hồi không hợp lệ hoặc chưa gọi được model; kiểm tra model/endpoint và schema."
            condition["elapsed_seconds"] = round(perf_counter() - started, 3)
        result["conditions"].append(condition)
    return result, variants


def write_comparison_report(result, variants, directory):
    """Create a new UTF-8 report folder, with no API credentials or request base64 in JSON."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    panels = []
    for condition in result["conditions"]:
        name = condition["name"]
        variant = variants[name]
        (directory / f"{name}.png").write_bytes(variant.data)
        title = "Ảnh chưa resize" if name == "original" else "Ảnh có resize"
        url = "data:image/png;base64," + base64.b64encode(variant.data).decode("ascii")
        response = condition["raw_response"] or condition.get("error") or "Chưa gọi model (prepare-only)."
        panels.append(f'<section><h2>{title}</h2><p>{variant.width} × {variant.height} px; '
                      f'{escape(condition["status"])}</p><div class="image"><img src="{url}" alt="{title}"></div>'
                      f'<pre>{escape(response)}</pre></section>')
    metadata = {key: result[key] for key in ("observation_id", "model", "reference_revision", "reference_count")}
    html = ('<!DOCTYPE html><html lang="vi"><meta charset="utf-8"><title>So sánh ảnh gốc và resize</title>'
            '<style>body{font:16px sans-serif;margin:24px;color:#18364a}main{display:flex;gap:20px}'
            'section{flex:1;min-width:0;border:1px solid #ccc;padding:18px;border-radius:10px}'
            '.image{min-height:240px;display:flex;align-items:center;justify-content:center;background:#edf2f5}'
            'img{max-width:100%;height:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere}'
            '@media(max-width:800px){main{display:block}}</style><h1>Ảnh gốc và ảnh resize: phản hồi model</h1>'
            '<p>Hai yêu cầu độc lập, cùng model, prompt và bộ mẫu. Chỉ pixel ảnh mục tiêu thay đổi. '
            'Phản hồi hiển thị trước quy tắc hậu xử lý; không sửa nhãn hay tạo flag. '
            'Một cặp câu trả lời chưa chứng minh bản nào chính xác hơn.</p><pre>'
            + escape(json.dumps(metadata, ensure_ascii=False, indent=2)) + '</pre><main>' + ''.join(panels) + '</main></html>')
    (directory / "comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (directory / "comparison.html").write_text(html, encoding="utf-8")
    return directory / "comparison.html"
