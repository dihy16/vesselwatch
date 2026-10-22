"""Command-line adapter for a single observation review."""

import json

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
    args = parser.parse_args()
    try:
        if args.data_source == "demo":
            from ship_agent.data.demo_data import load_demo_observations
            observations = load_demo_observations()
        else:
            from ship_agent.clients.file_server_client import load_observations
            observations = load_observations()
        result = create_image_review_tool(observations, data_source=args.data_source).invoke(
            {"observation_id": args.observation_id})
    except (ToolException, RuntimeError, OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
