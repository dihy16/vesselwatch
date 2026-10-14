"""Test a running LangGraph dev server: python client.py --help."""

import argparse
import json
import sys
from uuid import uuid4

import httpx
from langgraph_sdk import get_sync_client


DEFAULT_QUESTION = "Thống kê tàu khả nghi theo ngày trong 7 ngày qua."


def text_content(content):
    """Read both plain text and structured message content."""
    if isinstance(content, str):
        return content
    return "\n".join(
        block["text"] for block in (content or [])
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    )


def ask(client, thread_id, graph, question, *, show_tools=False):
    message_id = str(uuid4())
    state = client.runs.wait(
        thread_id,
        graph,
        input={"messages": [{"id": message_id, "role": "user", "content": question}]},
        config={"recursion_limit": 20},
    )
    # The server returns the whole conversation. Show only this turn.
    messages = state.get("messages", [])
    start = next((i for i, message in enumerate(messages) if message.get("id") == message_id), None)
    if start is None:
        raise RuntimeError("Server không trả lại message vừa gửi trong state.messages.")
    answer = None
    for message in messages[start + 1:]:
        if show_tools:
            for call in message.get("tool_calls", []):
                print(f"[tool call] {call['name']}: {json.dumps(call.get('args', {}), ensure_ascii=False)}")
            if message.get("type") == "tool":
                print(f"[tool result] {message.get('name', '')}: {text_content(message.get('content'))}")
        if message.get("type") == "ai" and not message.get("tool_calls"):
            answer = text_content(message.get("content"))
    if not answer:
        raise RuntimeError("Run kết thúc nhưng chưa có câu trả lời từ agent.")
    return answer


def main(argv=None):
    parser = argparse.ArgumentParser(description="Client test server LangGraph dev đang chạy.")
    parser.add_argument("--url", default="http://127.0.0.1:2024", help="Địa chỉ server LangGraph (mặc định: %(default)s).")
    parser.add_argument("--graph", default="agent", help="Graph ID trong langgraph.json (mặc định: %(default)s).")
    parser.add_argument("--thread-id", help="Tiếp tục thread đã có; mặc định tạo thread mới.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--question", default=None, help="Gửi một câu hỏi rồi thoát.")
    mode.add_argument("--chat", action="store_true", help="Chat nhiều lượt, giữ lịch sử trên cùng thread.")
    parser.add_argument("--show-tools", action="store_true", help="In tool calls và kết quả tools của lượt hiện tại.")
    parser.add_argument("--timeout", type=float, default=300, help="Timeout HTTP tính bằng giây (mặc định: %(default)s).")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout phải lớn hơn 0.")
    if args.question is not None and not args.question.strip():
        parser.error("--question không được để trống.")

    client = get_sync_client(url=args.url, timeout=args.timeout)
    try:
        thread_id = args.thread_id or client.threads.create()["thread_id"]
        print(f"Server: {args.url} | Graph: {args.graph}\nThread ID: {thread_id}", flush=True)
        if not args.chat:
            print(ask(client, thread_id, args.graph, args.question or DEFAULT_QUESTION, show_tools=args.show_tools))
            return 0
        print("Nhập câu hỏi; /exit hoặc /quit để thoát.")
        while True:
            try:
                question = input("\nBạn: ").strip()
            except EOFError:
                break
            if question.lower() in {"/exit", "/quit"}:
                break
            if question:
                print("Agent:", ask(client, thread_id, args.graph, question, show_tools=args.show_tools))
        return 0
    except httpx.ConnectError:
        print(f"Không kết nối được tới {args.url}. Kiểm tra langgraph dev và --url.", file=sys.stderr)
        return 1
    except httpx.TimeoutException:
        print("Hết thời gian chờ. Kiểm tra log server hoặc tăng --timeout; run có thể vẫn đang chạy.", file=sys.stderr)
        return 1
    except (httpx.HTTPError, RuntimeError) as exc:
        print(f"Lỗi gọi LangGraph: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nĐã ngắt client; run đã gửi có thể vẫn đang chạy trên server.", file=sys.stderr)
        return 130
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
