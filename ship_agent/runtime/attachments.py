"""Select current-turn tool artifacts and assemble ephemeral pixel context."""

import json

import httpx
from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import ToolException

from ship_agent.runtime.visual_context import build_visual_content, latest_visual_input


def current_image_results(messages):
    results = []
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        if isinstance(message, ToolMessage) and message.status != "error":
            try:
                result = json.loads(message.content)
            except (ValueError, TypeError):
                continue
            if isinstance(result, dict):
                results.append(result)
    return results


def _chat_visual_message(messages, observations, data_source):
    try:
        descriptor = latest_visual_input(messages)
        if descriptor is None:
            return None
        from ship_agent.clients.carrier_reference_client import load_carrier_references
        from ship_agent.vision.image_review import _image_bytes

        content = build_visual_content(descriptor, observations,
            load_references=load_carrier_references,
            load_image=lambda row: _image_bytes(row, data_source, None))
        return HumanMessage(content=content)
    except (ValueError, OSError, httpx.HTTPError, ToolException):
        # Never leak request bodies or silently show a different reference revision.
        return HumanMessage(content="direct_visual_context_unavailable: Chưa tải đủ pixel cho LLM chat; "
                            "kiểm tra file server, ảnh và revision bộ mẫu. Lượt này bạn chưa xem ảnh trực tiếp; "
                            "nêu rõ lỗi, không thay pixel bằng mô tả rồi nói đã xem. Không lặp tool liên tục; "
                            "chỉ thử lại khi có yêu cầu hoặc nguồn đã được sửa.")

def _current_reports(messages: list[BaseMessage]) -> list[dict]:
    """Use successful report calls from this turn, never a previous answer."""
    turn = []
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        turn.append(message)
    reports = {}
    for message in reversed(turn):
        if isinstance(message, ToolMessage) and message.name in {"daily_carrier_report", "vessel_monitoring_report"}:
            if message.status == "error":
                reports.clear()
            else:
                report = json.loads(message.content)
                if message.name == "vessel_monitoring_report" and (report.get("status") != "complete" or report.get("output_format") != "html"):
                    continue
                reports[(report["report_id"], report.get("output_format", "html"))] = report
    return list(reports.values())

def _current_maps(messages: list[BaseMessage]) -> list[dict]:
    turn = []
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        turn.append(message)
    maps = {}
    for message in reversed(turn):
        if isinstance(message, ToolMessage) and message.name in {"create_vessel_map", "query_ships_in_area", "analyze_ship_observations", "investigate_missed_carriers", "investigate_false_carriers", "investigate_carrier_detections", "find_carrier_hotspots", "investigate_carrier_hotspot", "vessel_monitoring_report", "investigate_carrier_labels"}:
            if message.status == "error":
                maps.clear()
            else:
                result = json.loads(message.content)
                if result.get("persistent_map"):
                    # The user already has the chat-linked map mounted in Artifacts.
                    continue
                if message.name in {"query_ships_in_area", "analyze_ship_observations", "investigate_missed_carriers", "investigate_false_carriers", "investigate_carrier_detections", "find_carrier_hotspots", "investigate_carrier_hotspot", "vessel_monitoring_report", "investigate_carrier_labels"}:
                    maps = {key: value for key, value in maps.items() if value.get("status") != "needs_drawing"}
                if message.name == "create_vessel_map" or result.get("status") == "needs_drawing":
                    maps[result.get("map_id", result.get("selection_id"))] = result
    return list(maps.values())
