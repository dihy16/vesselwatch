"""Explicit LangGraph agent -> tools -> agent loop."""

from datetime import date
import os
import re
from uuid import uuid4

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import ToolException
from langchain_openai import ChatOpenAI
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from pydantic import ValidationError

from ship_agent.artifacts.map_artifacts import render_map_artifact
from ship_agent.artifacts.image_previews import has_image_results, render_chat_image_previews
from ship_agent.artifacts.monitoring_artifacts import render_monitoring_artifact
from ship_agent.artifacts.report_artifacts import render_carrier_artifact
from ship_agent.runtime.attachments import _chat_visual_message, _current_reports, _current_maps, current_image_results
from ship_agent.runtime.chat_area import chat_area_note
from ship_agent.runtime.dates import DataSource, resolve_reference_date
from ship_agent.runtime.llm_context import messages_for_llm
from ship_agent.runtime.prompts import build_system_prompt
from ship_agent.tools.registry import create_tools


def build_agent(
    *, model: ChatOpenAI | None = None, reference_date: date | None = None,
    data_source: DataSource = "file_server",
    observations: list[dict] | None = None,
):
    reference_date = resolve_reference_date(reference_date, data_source)
    visual_context_rows = []
    tools = create_tools(reference_date, data_source=data_source, observations=observations,
                         visual_context_rows=visual_context_rows)
    if model is None:
        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("Chưa có OPENAI_API_KEY. Hãy cấu hình .env hoặc chạy --mock-tools.")
        model = ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            base_url=os.getenv("OPENAI_BASE_URL") or None,
            timeout=60,
            max_retries=2,
        )
    llm_with_tools = model.bind_tools(tools)
    prompt = build_system_prompt(reference_date, data_source)

    def call_model(state: MessagesState, config: RunnableConfig):
        reports = _current_reports(state["messages"])
        maps = _current_maps(state["messages"])
        image_results = current_image_results(state["messages"])
        demo_images_requested = False
        if data_source == "demo":
            from ship_agent.data.demo_data import wants_demo_images
            demo_images_requested = wants_demo_images(state["messages"])
        # Reports are added deterministically, without asking the LLM to copy HTML.
        # Emit the complete node output in messages mode instead of streaming an
        # incomplete answer before the artifact has been attached.
        area_note = chat_area_note(config)
        messages = [prompt]
        if area_note:
            messages.append(SystemMessage(content=area_note))
        messages.extend(messages_for_llm(state["messages"]))
        visual_message = _chat_visual_message(state["messages"], visual_context_rows, data_source)
        if visual_message is not None:
            # Ephemeral multimodal input: never checkpoint base64 or emit it to the UI.
            messages.append(visual_message)
        try:
            response = llm_with_tools.invoke(
                messages,
                config={"tags": ["nostream"]} if reports or maps or demo_images_requested
                    or data_source != "mock" and has_image_results(image_results) else None,
            )
        except Exception:
            if visual_message is not None and isinstance(visual_message.content, list):
                raise RuntimeError("LLM chat chưa xử lý được yêu cầu có ảnh. Kiểm tra OPENAI_MODEL, "
                                   "OPENAI_BASE_URL, hỗ trợ vision/tool calls và giới hạn số ảnh/context. "
                                   "Không tự chuyển sang trả lời chỉ từ mô tả.") from None
            raise
        if (reports or maps) and not response.tool_calls:
            artifacts = []
            for report in reports:
                if report.get("report_kind") == "vessel_monitoring":
                    artifacts.append(f"```html\n{render_monitoring_artifact(report)}\n```")
                elif report.get("output_format") == "png":
                    url = report["chart_url"]
                    if not re.search(r"!\[[^\]]*\]\(" + re.escape(url) + r"\)", response.text):
                        artifacts.append(f"![Biểu đồ lượt dự đoán tàu sân bay theo ngày]({url})")
                else:
                    artifacts.append(f"```html\n{render_carrier_artifact(report)}\n```")
            for result in maps:
                artifacts.append(f"```html\n{render_map_artifact(result)}\n```")
                artifacts.append(f"[Mở bản đồ toàn màn hình]({result['map_url']})")
            if artifacts:
                response = response.model_copy(update={
                    "id": str(uuid4()), "content": "\n\n".join([response.text, *artifacts]),
                })
        elif demo_images_requested and not response.tool_calls:
            from ship_agent.data.demo_data import demo_image_markdown
            images = demo_image_markdown(state["messages"], response.text)
            if images:
                response = response.model_copy(update={
                    "id": str(uuid4()), "content": f"{response.text}\n\n{images}",
                })
        if not response.tool_calls and data_source != "mock" and isinstance(response.content, str):
            displayed = render_chat_image_previews(response.content, visual_context_rows, image_results,
                                                   data_source=data_source)
            if displayed != response.content:
                response = response.model_copy(update={"id": str(uuid4()), "content": displayed})
        return {"messages": [response]}

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", ToolNode(tools, handle_tool_errors=(ToolException, ValidationError)))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")
    return graph.compile()
