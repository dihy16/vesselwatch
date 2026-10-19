"""Verify model-only artifact compaction and preserve the original chat history."""

import base64
from datetime import date
import json

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
import pytest

from ship_agent.agent import build_agent
from ship_agent.llm_context import messages_for_llm
from ship_agent.map_artifacts import render_map_artifact


IMAGE = base64.b64encode(b"large saved crop" * 16000).decode("ascii")
HTML = ('<!DOCTYPE html><html><head><title>Báo cáo tàu sân bay</title>'
        '<style>.private-style { width: 100%; }</style></head><body>'
        '<p>2025-12-24 → 2025-12-30 · Tổng 2 lượt.</p>'
        f'<img alt="REAL_SHIP_001" src="data:image/png;base64,{IMAGE}">'
        '<script>const privateScript = "do not send";</script></body></html>')


@pytest.mark.parametrize("artifact", [
    "```html\n" + HTML + "\n```",
    "```HTML\r\n" + HTML + "\r\n```",
    "~~~~html\n" + HTML + "\n~~~~",
    "```html\n" + HTML + "\n````",
    "```html\n" + HTML,  # A truncated historical code fence is still an artifact.
    HTML,
], ids=["html-fence", "uppercase-crlf", "tilde-fence", "longer-closing-fence", "truncated-fence", "raw-html"])
def test_artifact_is_summarized_without_mutating_message(artifact):
    original = AIMessage(content="Có 2 lượt.\n" + artifact + "\nNhận xét cuối.", id="answer",
                         response_metadata={"model_name": "test"})
    before = original.model_dump()
    compact = messages_for_llm([original])[0]
    assert compact is not original and original.model_dump() == before
    assert compact.id == "answer" and compact.response_metadata == original.response_metadata
    assert "Có 2 lượt." in compact.text and "Nhận xét cuối." in compact.text
    assert "Báo cáo tàu sân bay" in compact.text and "2025-12-30" in compact.text
    assert "REAL_SHIP_001" in compact.text and "Tổng 2 lượt" in compact.text
    for removed in ("<html", "base64", IMAGE, "privateScript", "private-style"):
        assert removed not in compact.text
    assert len(compact.text) < 1500


def test_map_keeps_url_and_observation_count_but_not_iframe():
    url = "http://viewer:8002/maps/" + "a" * 64
    html = render_map_artifact({"map_url": url, "total": 2})
    original = AIMessage(content=f"Bản đồ của bạn.\n```html\n{html}\n```\n[Mở map]({url})")
    text = messages_for_llm([original])[0].text
    assert "<iframe" not in text and "```html" not in text
    assert url in text and "2 lượt quan sát" in text
    assert f"[Mở map]({url})" in text
    assert "<iframe" in original.text


def test_user_tool_messages_and_normal_code_are_kept_verbatim():
    messages = [
        SystemMessage(content="Hướng dẫn giữ nguyên."),
        HumanMessage(content=f"Giải thích HTML này:\n```html\n{HTML}\n```"),
        ToolMessage(content=json.dumps({"html": HTML}), tool_call_id="source", name="custom"),
        AIMessage(content='Ví dụ:\n```python\nprint("hello")\n```\n```html\n<div>Hello</div>\n```'),
        AIMessage(content="![REAL_SHIP_001](http://viewer:8002/images/one)"),
    ]
    compact = messages_for_llm(messages)
    assert all(old is new for old, new in zip(messages, compact))


def test_text_content_blocks_and_tool_calls_keep_their_structure():
    original = AIMessage(content=[
        {"type": "text", "text": f"```html\n{HTML}\n```", "annotations": []},
        "Nhận xét. " + f"data:image/png;base64,{IMAGE}",
        {"type": "image_url", "image_url": {"url": "http://viewer/image.png"}},
    ], tool_calls=[{"id": "search", "name": "search_ships", "args": {"ship_id": "REAL_SHIP_001"}}])
    before = original.model_dump()
    compact = messages_for_llm([original])[0]
    assert compact.tool_calls == original.tool_calls and original.model_dump() == before
    assert compact.content[0]["type"] == "text" and compact.content[0]["annotations"] == []
    assert "<html" not in compact.content[0]["text"]
    assert IMAGE not in compact.content[1] and "Nhận xét." in compact.content[1]
    assert compact.content[2] == original.content[2]


def test_summary_is_bounded_and_never_keeps_data_urls_from_links():
    html = ('<html><head><title>' + "T" * 10000 + '</title></head><body>'
            + "visible " * 10000 + f'<a href="data:image/png;base64,{IMAGE}">image</a>'
            + '<iframe src="javascript:alert(1)"></iframe></body></html>')
    compact = messages_for_llm([AIMessage(content=html)])[0].text
    assert len(compact) < 1000 and "javascript:" not in compact and IMAGE not in compact


@pytest.mark.parametrize("stream", [False, True])
def test_report_followup_strips_html_on_every_model_call_and_preserves_history(monkeypatch, stream):
    from ship_agent import agent as agent_module

    monkeypatch.setattr(agent_module, "render_carrier_artifact", lambda report: HTML)
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        # Report -> answer -> follow-up search -> answer.
        if len(requests) in (1, 3):
            name = "daily_carrier_report" if len(requests) == 1 else "search_ships"
            args = ({"observed_from": "2026-10-07", "observed_to": "2026-10-13"}
                    if name == "daily_carrier_report" else {"ship_id": "SHIP_001"})
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": f"call-{len(requests)}", "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }]}
            finish = "tool_calls"
        else:
            message = {"role": "assistant", "content": "Nhận xét từ số liệu tool."}
            finish = "stop"
        if len(requests) >= 3:
            serialized = json.dumps(body["messages"], ensure_ascii=False)
            assert IMAGE not in serialized and "privateScript" not in serialized
            assert "<html" not in serialized and "HTML artifact đã lược" in serialized
            assert "REAL_SHIP_001" in serialized and "2025-12-30" in serialized
            report = next(m for m in body["messages"] if m.get("tool_call_id") == "call-1")
            assert json.loads(report["content"])["observed_from"] == "2026-10-07"
            assert len(serialized) < 25000
        if body.get("stream"):
            delta = dict(message)
            if delta.get("tool_calls"):
                delta["tool_calls"] = [{"index": i, **call} for i, call in enumerate(delta["tool_calls"])]
            chunks = [
                {"id": "context", "object": "chat.completion.chunk", "created": 0, "model": "test",
                 "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                {"id": "context", "object": "chat.completion.chunk", "created": 0, "model": "test",
                 "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
            ]
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=(
                "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
            ).encode())
        return httpx.Response(200, json={
            "id": "context", "object": "chat.completion", "created": 0, "model": "test",
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        })

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        model = ChatOpenAI(model="test", api_key="synthetic", http_client=client, max_retries=0)
        graph = build_agent(model=model, data_source="mock", reference_date=date(2026, 10, 13))
        first = graph.invoke({"messages": [HumanMessage(content="Báo cáo 7 ngày qua.")]})
        original = first["messages"][-1]
        assert HTML in original.text
        history = [*first["messages"], HumanMessage(content="Xem thêm SHIP_001.")]
        if stream:
            states = list(graph.stream({"messages": history}, stream_mode="values"))
            final = states[-1]
        else:
            final = graph.invoke({"messages": history})
    assert len(requests) == 4
    saved = next(m for m in final["messages"] if m.id == original.id)
    assert saved.content == original.content and IMAGE in saved.text
    assert "<html" not in final["messages"][-1].text
