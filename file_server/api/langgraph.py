"""HTTP adapter from a confirmed map query to LangGraph."""

import json

from fastapi import HTTPException
import httpx


async def ask_area_agent(query: dict, *, source: str) -> str:
    """Call the configured LangGraph server; credentials remain on that server."""
    from ship_agent import config

    url = config.DEMO_LANGGRAPH_URL if source == "demo" else config.LANGGRAPH_URL
    message = ("Truy vấn các lượt phát hiện trong vùng đã được người dùng xác nhận. "
               "Dùng query_ships_in_area với đúng tham số sau, trả tổng số lượt phát hiện, "
               "số lượt nghi là tàu sân bay và danh sách kèm vị trí; nói rõ nếu có phân trang.\n"
               + json.dumps(query, ensure_ascii=False))
    try:
        async with httpx.AsyncClient(timeout=180, trust_env=False) as client:
            response = await client.post(url.rstrip("/") + "/runs/wait", json={
                "assistant_id": "agent", "input": {"messages": [{"role": "user", "content": message}]},
                "config": {"recursion_limit": 20},
            })
            response.raise_for_status()
            state = response.json()
        if not isinstance(state, dict) or not isinstance(state.get("messages"), list):
            raise ValueError("Phản hồi agent không hợp lệ.")
        for item in reversed(state.get("messages", [])):
            if item.get("type") == "ai" and not item.get("tool_calls"):
                content = item.get("content")
                if isinstance(content, list):
                    content = "\n".join(block["text"] for block in content
                                        if isinstance(block, dict) and isinstance(block.get("text"), str))
                if isinstance(content, str) and content.strip():
                    return content
        raise ValueError("Agent chưa trả câu trả lời.")
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "Chưa nhận được câu trả lời từ agent. Kiểm tra URL và server LangGraph.") from exc
