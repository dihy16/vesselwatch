"""Native/resized pixels reach the conversational model without a vision reviewer."""

import base64
from io import BytesIO
import json

import httpx
from PIL import Image
import pytest

pytest.importorskip("langchain_openai")
pytest.importorskip("langgraph")

from langchain_core.messages import HumanMessage
from langchain_core.tools import ToolException
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from file_server.media.carrier_references import load_reference_library
from file_server.media.image_assets import prepare_vision_image
from ship_agent.runtime.agent import build_agent
from ship_agent.tools.images import create_image_view_tool
from tests.agent.test_pair_evidence import pair_rows
from tests.file_server.test_carrier_references import png, reference_folder


@pytest.mark.parametrize("image_size,expected_size", [("original", (48, 26)), ("resized", (224, 121))])
@pytest.mark.parametrize("use_references", [False, True])
def test_actual_chat_request_receives_selected_size_and_unchanged_references(
        tmp_path, monkeypatch, image_size, expected_size, use_references):
    import ship_agent.clients.carrier_reference_client as references
    import ship_agent.tools.images as image_tools
    import ship_agent.vision.image_review as reviewer

    library = load_reference_library(reference_folder(tmp_path))
    rows = list(pair_rows())
    data = png(size=(48, 26))
    monkeypatch.setattr(reviewer, "_image_bytes", lambda *args: data)
    for module in (references, image_tools):
        monkeypatch.setattr(module, "load_carrier_references", lambda: library)

    def forbidden(*args, **kwargs):
        pytest.fail("Direct chat viewing must not call a separate vision reviewer")

    monkeypatch.setattr(reviewer, "_vision_model", forbidden)
    monkeypatch.setattr(reviewer, "review_image", forbidden)
    monkeypatch.setattr(reviewer, "review_image_against_references", forbidden)
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            answer = {"role": "assistant", "content": None, "tool_calls": [{"id": "open-image",
                "type": "function", "function": {"name": "view_ship_image", "arguments": json.dumps({
                    "observation_id": rows[0]["observation_id"], "image_size": image_size,
                    "use_carrier_references": use_references})}}]}
            finish = "tool_calls"
        else:
            blocks = [part for message in body["messages"] if isinstance(message.get("content"), list)
                      for part in message["content"] if part.get("type") == "image_url"]
            assert len(blocks) == 1 + (len(library.images) if use_references else 0)
            actual = [base64.b64decode(part["image_url"]["url"].split(",", 1)[1]) for part in blocks]
            with Image.open(BytesIO(actual[0])) as target:
                assert target.size == expected_size
            assert actual[1:] == ([prepare_vision_image(image.data).data for image in library.images]
                                  if use_references else [])
            result = json.loads(next(message for message in reversed(body["messages"])
                                     if message["role"] == "tool")["content"])
            assert result["image_size"] == image_size
            assert (result["vision_image_width_px"], result["vision_image_height_px"]) == expected_size
            assert result["reference_count"] == (len(library.images) if use_references else 0)
            assert "saved_prediction" not in result and "visual_review" not in result
            assert "base64" not in json.dumps(result)
            answer = {"role": "assistant", "content": "Thân tàu thuôn dài; chưa rõ đường bao."}
            finish = "stop"
        return httpx.Response(200, json={"id": "view-image", "object": "chat.completion", "created": 0,
            "model": "chat-test", "choices": [{"index": 0, "finish_reason": finish, "message": answer}]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        model = ChatOpenAI(model="chat-test", api_key="test-only", http_client=client, max_retries=0)
        result = build_agent(model=model, observations=rows).invoke({"messages": [HumanMessage(
            content="Nhận xét tự do từ ảnh, không dùng vision reviewer.")]})
    assert len(requests) == 2
    assert "thuôn dài" in result["messages"][-1].content
    assert "data:image" not in json.dumps([message.model_dump() for message in result["messages"]])


def test_direct_view_rejects_unknown_observation_or_size_before_loading(monkeypatch):
    import ship_agent.vision.image_review as reviewer

    monkeypatch.setattr(reviewer, "_image_bytes", lambda *args: pytest.fail("Invalid input must not load images"))
    rows = list(pair_rows())
    tool = create_image_view_tool(rows, data_source="file_server")
    with pytest.raises(ToolException, match="observation"):
        tool.invoke({"observation_id": "missing", "image_size": "original"})
    with pytest.raises(ValidationError):
        tool.invoke({"observation_id": rows[0]["observation_id"], "image_size": "arbitrary"})
