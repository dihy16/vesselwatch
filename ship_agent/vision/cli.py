"""Command-line adapter for a single observation review."""

import json

import httpx

from langchain_core.tools import ToolException

from ship_agent.tools.images import create_image_review_tool


def main():
    """Run one review directly, without the conversational agent."""
    import argparse
    from dotenv import load_dotenv

    load_dotenv()
    parser = argparse.ArgumentParser(description="Đọc ảnh một observation bằng vision model.")
    parser.add_argument("--data-source", choices=["demo", "file_server"], default="demo")
    parser.add_argument("--observation-id", required=True)
    parser.add_argument("--compare-resize", action="store_true", help="Gọi độc lập ảnh gốc và resize, lưu hai phản hồi để so sánh.")
    parser.add_argument("--use-carrier-references", action="store_true", help="Dùng cùng toàn bộ bộ mẫu ở hai lượt so sánh.")
    parser.add_argument("--prepare-only", action="store_true", help="Chỉ chuẩn bị cặp ảnh/báo cáo, không gọi model.")
    parser.add_argument("--output-dir", help="Thư mục báo cáo mới (mặc định data/resize_comparisons/...).")
    args = parser.parse_args()
    if not args.compare_resize and (args.use_carrier_references or args.prepare_only or args.output_dir):
        parser.error("Các tùy chọn so sánh cần --compare-resize.")
    try:
        if args.data_source == "demo":
            from ship_agent.data.demo_data import load_demo_observations
            observations = load_demo_observations()
        else:
            from ship_agent.clients.file_server_client import load_observations
            observations = load_observations()
        if args.compare_resize:
            from datetime import datetime, timezone
            from pathlib import Path
            from uuid import uuid4
            from ship_agent.clients.carrier_reference_client import load_carrier_references
            from ship_agent.vision.image_review import _image_bytes
            from ship_agent.vision.resize_comparison import compare_resize, write_comparison_report

            observation = next((row for row in observations if row["observation_id"] == args.observation_id), None)
            if observation is None or not observation.get("images"):
                raise ValueError("Không tìm thấy observation có ảnh trong nguồn đã chọn.")
            library = load_carrier_references() if args.use_carrier_references else None
            result, variants = compare_resize(_image_bytes(observation, args.data_source, None),
                observation_id=args.observation_id, library=library, prepare_only=args.prepare_only)
            directory = args.output_dir or Path("data/resize_comparisons") / (
                datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
            report = write_comparison_report(result, variants, directory)
            result = {"report": str(report.resolve()), "conditions": [
                {key: item[key] for key in ("name", "status", "vision_image_width_px", "vision_image_height_px")}
                for item in result["conditions"]]}
        else:
            result = create_image_review_tool(observations, data_source=args.data_source).invoke(
                {"observation_id": args.observation_id})
    except httpx.HTTPError:
        parser.exit(1, "Không đọc được dữ liệu/ảnh/bộ mẫu từ API; kiểm tra file server và cấu hình URL.\n")
    except (ToolException, RuntimeError, OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
