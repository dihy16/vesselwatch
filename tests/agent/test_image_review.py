"""Exercise image bytes, provider serialization, and visual review failures offline."""

import base64
from io import BytesIO
import json

import httpx
from langchain_core.messages import AIMessage
from langchain_core.tools import ToolException
from langchain_openai import ChatOpenAI
from PIL import Image
import pytest

import ship_agent.vision.image_review as image_review
from ship_agent.tools.registry import create_tools


@pytest.fixture
def observation():
    return {
        "observation_id": "OBS_one", "ship_id": "SHIP_one",
        "classification": "aircraft_carrier", "confidence": .97,
        "length_m": 300, "width_m": 60,
        "images": [{"image_id": "IMG_one", "url": "http://public.example/images/IMG_one"}],
    }


def png_bytes():
    output = BytesIO()
    Image.new("RGB", (32, 24), "blue").save(output, format="PNG")
    return output.getvalue()


def review_payload(**changes):
    return {"image_quality": "limited", "visible_features": ["Thân dài"],
            "limitations": ["Ảnh nhỏ"], "assessment": "unknown",
            "reasoning": "Không thấy đủ chi tiết để kết luận.", **changes}


class Reviewer:
    def __init__(self, **changes):
        self.changes = changes

    def invoke(self, messages, **kwargs):
        return AIMessage(content=json.dumps(review_payload(**self.changes)))


def test_registered_image_pixels_are_sent_without_saved_prediction(observation):
    data = png_bytes()
    requests = []

    def image_response(request):
        assert str(request.url).endswith("/images/IMG_one")
        assert request.url.host != "public.example"
        return httpx.Response(200, content=data, headers={"Content-Type": "image/png"})

    def model_response(request):
        body = json.loads(request.content)
        requests.append(body)
        content = body["messages"][1]["content"]
        assert content[1]["type"] == "image_url"
        uri = content[1]["image_url"]["url"]
        with Image.open(BytesIO(base64.b64decode(uri.split(",", 1)[1]))) as image:
            assert image.size == (224, 168)
        assert "0.97" not in json.dumps(body)
        assert "SHIP_one" not in json.dumps(body)
        assert "300" not in content[0]["text"]
        return httpx.Response(200, json={
            "id": "review", "object": "chat.completion", "created": 0, "model": "vision-test",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps(review_payload(
                    image_quality="sufficient", assessment="not_aircraft_carrier")),
            }}],
        })

    with httpx.Client(transport=httpx.MockTransport(model_response)) as client:
        model = ChatOpenAI(model="vision-test", api_key="test-only", http_client=client, max_retries=0)
        result = image_review.review_image(observation, model=model,
                                          transport=httpx.MockTransport(image_response))
    assert len(requests) == 1
    assert result["comparison"] == "disagrees"
    assert result["saved_prediction"]["carrier_score"] == .97
    assert (result["image_width_px"], result["image_height_px"]) == (32, 24)
    assert (result["vision_image_width_px"], result["vision_image_height_px"]) == (224, 168)
    assert result["is_ground_truth"] is False
    assert observation["classification"] == "aircraft_carrier"
    assert "base64" not in json.dumps(result)


@pytest.mark.parametrize("quality,assessment,comparison", [
    ("sufficient", "aircraft_carrier", "agrees"),
    ("limited", "unknown", "inconclusive"),
    ("insufficient", "aircraft_carrier", "inconclusive"),
])
def test_uncertainty_and_agreement(observation, quality, assessment, comparison):
    result = image_review.review_image(
        observation, model=Reviewer(image_quality=quality, assessment=assessment),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=png_bytes())),
    )
    assert result["comparison"] == comparison
    if quality == "insufficient":
        assert result["visual_review"]["assessment"] == "unknown"


@pytest.mark.parametrize("response", [
    httpx.Response(404), httpx.Response(302, headers={"Location": "http://other.example/secret"}),
    httpx.Response(200, content=b"not an image"),
])
def test_bad_images_fail_before_model_call(observation, response):
    class NeverCalled:
        def invoke(self, *args, **kwargs):
            pytest.fail("The model must not receive invalid image data")

    with pytest.raises(ToolException, match="Không tải/đọc"):
        image_review.review_image(observation, model=NeverCalled(),
                                  transport=httpx.MockTransport(lambda request: response))


def test_download_size_limit(observation, monkeypatch):
    monkeypatch.setattr(image_review, "MAX_IMAGE_BYTES", 10)
    with pytest.raises(ToolException, match="Không tải/đọc"):
        image_review.review_image(observation, model=Reviewer(), transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=png_bytes())))


def test_invalid_provider_output_is_not_a_successful_review(observation):
    class InvalidReviewer:
        def invoke(self, *args, **kwargs):
            return AIMessage(content="I cannot read images")

    with pytest.raises(ToolException, match="model/endpoint"):
        image_review.review_image(observation, model=InvalidReviewer(), transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=png_bytes())))


def test_tool_looks_up_exact_observation_and_excludes_mock(observation, monkeypatch):
    calls = []
    monkeypatch.setattr(image_review, "review_image", lambda row, **kwargs: calls.append(row) or {"ok": True})
    tool = next(t for t in create_tools(observations=[observation]) if t.name == "review_ship_images")
    result = tool.invoke({"observation_id": "OBS_one"})
    assert result["ok"] is True
    assert result["visual_input"]["targets"] == [{"observation_id": "OBS_one",
                                                 "image_id": observation["images"][0]["image_id"]}]
    assert calls == [observation]
    with pytest.raises(ToolException, match="Không tìm thấy"):
        tool.invoke({"observation_id": "SHIP_one"})
    assert "review_ship_images" not in {t.name for t in create_tools(data_source="mock")}


def test_demo_uses_verified_local_image_without_http():
    from ship_agent.data.demo_data import load_demo_observations

    observation = load_demo_observations()[0]
    result = image_review.review_image(observation, data_source="demo", model=Reviewer(),
                                      transport=httpx.MockTransport(lambda request: pytest.fail("No HTTP")))
    assert result["observation_id"] == observation["observation_id"]
    assert result["image_width_px"] > 0


def test_vision_settings_fall_back_to_existing_configuration(monkeypatch):
    for name in ("OPENAI_VISION_MODEL", "OPENAI_VISION_BASE_URL", "OPENAI_VISION_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_MODEL", "configured-vision")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:9999/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    model = image_review._vision_model()
    assert model.model_name == "configured-vision"
    assert model.openai_api_base == "http://localhost:9999/v1"


def test_missing_key_is_actionable(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_VISION_API_KEY", raising=False)
    with pytest.raises(ToolException, match="API key"):
        image_review._vision_model()


def test_graph_executes_review_and_returns_result_to_agent(observation, monkeypatch):
    from langchain_core.messages import HumanMessage, ToolMessage
    from ship_agent.runtime.agent import build_agent

    monkeypatch.setattr(image_review, "_image_bytes", lambda *args: png_bytes())
    monkeypatch.setattr(image_review, "_vision_model", lambda: Reviewer())

    class Planner:
        calls = 0

        def bind_tools(self, tools):
            assert "review_ship_images" in {tool.name for tool in tools}
            return self

        def invoke(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[{
                    "id": "review_call", "name": "review_ship_images",
                    "args": {"observation_id": "OBS_one"},
                }])
            result = json.loads(next(m.content for m in messages if isinstance(m, ToolMessage)))
            assert result["visual_review"]["assessment"] == "unknown"
            assert result["comparison"] == "inconclusive"
            return AIMessage(content="Ảnh chưa đủ chi tiết để kết luận.")

    planner = Planner()
    graph = build_agent(model=planner, observations=[observation])
    result = graph.invoke({"messages": [HumanMessage(content="Đọc ảnh OBS_one")]})
    assert planner.calls == 2
    assert result["messages"][-1].content == "Ảnh chưa đủ chi tiết để kết luận."
