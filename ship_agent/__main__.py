"""Run `python -m ship_agent --help`."""

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from .agent import build_agent
from .dates import resolve_reference_date
from .tools import create_tools


def main():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    parser = argparse.ArgumentParser(description="Agent LangGraph với 2 tools đọc dữ liệu tàu từ file server.")
    parser.add_argument("--question", default="Thống kê theo ngày trong 7 ngày qua: bao nhiêu tàu khả nghi, bao nhiêu tàu có khả năng là tàu sân bay?")
    parser.add_argument("--today", type=date.fromisoformat, help="Cố định ngày tham chiếu YYYY-MM-DD (UTC mặc định); không đổi ngày dữ liệu thật.")
    parser.add_argument("--mock-tools", action="store_true", help="Gọi thử 2 tools với mock, không gọi file server/LLM và không cần API key.")
    parser.add_argument("--show-tools", action="store_true", help="In tool calls và ToolMessages để kiểm tra vòng lặp.")
    args = parser.parse_args()
    anchor = resolve_reference_date(args.today, "mock" if args.mock_tools else "file_server")
    if args.mock_tools:
        count, search = create_tools(anchor, data_source="mock")
        result = {
            "count_ships": count.invoke({"observed_from": (anchor - timedelta(days=6)).isoformat(), "observed_to": anchor.isoformat()}),
            "search_ships": search.invoke({"min_length_m": 250, "max_length_m": 350, "min_width_m": 50, "max_width_m": 80}),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    try:
        graph = build_agent(reference_date=anchor)
    except ValueError as exc:
        parser.error(str(exc))
    for state in graph.stream({"messages": [HumanMessage(content=args.question)]}, config={"recursion_limit": 20}, stream_mode="values"):
        message = state["messages"][-1]
        if args.show_tools:
            message.pretty_print()
    if not args.show_tools:
        print(message.text)


if __name__ == "__main__":
    main()
