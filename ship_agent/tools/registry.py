"""Prepare a source snapshot and register tools in the established order."""

from datetime import date

from ship_agent.clients.file_server_client import load_observations
from ship_agent.data.mock_data import build_observations
from ship_agent.runtime.dates import DataSource, resolve_reference_date, data_timezone
from ship_agent.tools.areas import create_area_tools
from ship_agent.tools.context import ToolContext
from ship_agent.tools.maps import create_map_tools
from ship_agent.tools.queries import create_query_tools
from ship_agent.tools.reports import create_report_tools


def create_tools(reference_date: date | None = None, *, data_source: DataSource = "file_server",
                 observations: list[dict] | None = None, visual_context_rows: list[dict] | None = None):
    """Load a complete snapshot at creation, or reuse a preloaded server snapshot."""
    anchor = resolve_reference_date(reference_date, data_source)
    is_mock = data_source == "mock"
    demo_snapshot = None
    if is_mock:
        observations = build_observations(anchor)
    elif data_source == "demo":
        from ship_agent.data.demo_data import load_demo_observations, read_snapshot
        observations = load_demo_observations()
        demo_snapshot = read_snapshot()
    elif observations is None:
        observations = load_observations()
    if visual_context_rows is not None:
        # Share exactly the tool snapshot with the graph's model-only pixel loader.
        visual_context_rows.extend(observations)
    metadata = {"is_mock": is_mock, "reference_date": anchor.isoformat(), "timezone": data_timezone(data_source)}
    if data_source == "demo":
        metadata.update(is_demo=True, data_scope="selected_demo_subset",
                        demo_snapshot_id=demo_snapshot["snapshot_id"])

    context = ToolContext(anchor, data_source, observations, metadata, demo_snapshot)
    query_tools = [*create_query_tools(context), *create_report_tools(context)]
    if data_source == "demo":
        query_tools.extend(create_map_tools(context))
    if not is_mock:
        query_tools.extend(create_area_tools(context))
        from ship_agent.tools.images import create_image_review_tool, create_reference_view_tool, create_image_view_tool
        query_tools.extend([create_image_review_tool(observations, data_source=data_source), create_reference_view_tool(),
                            create_image_view_tool(observations, data_source=data_source)])
    if data_source == "file_server":
        from ship_agent.tools.missed_carrier_tool import create_missed_carrier_tool
        from ship_agent.tools.false_carrier_tool import create_false_carrier_tool
        from ship_agent.tools.carrier_investigation_tool import create_carrier_investigation_tool
        from ship_agent.tools.hotspot_tools import create_carrier_hotspot_tools
        from ship_agent.tools.monitoring_tool import create_monitoring_report_tool
        from ship_agent.tools.label_review_tool import create_label_review_tool
        query_tools.extend([create_missed_carrier_tool(), create_false_carrier_tool(), create_carrier_investigation_tool()])
        query_tools.extend(create_carrier_hotspot_tools())
        query_tools.extend([create_monitoring_report_tool(), create_label_review_tool()])
    source_description = ("Dữ liệu và URL giả lập." if is_mock else
                          "Dữ liệu thật từ file server; mỗi ảnh Telegram là một tàu riêng.")
    if data_source == "demo":
        source_description = "Truy vấn ảnh vệ tinh và kết quả phân loại theo thời gian quan sát."
    for query_tool in query_tools:
        query_tool.description += f"\nMúi giờ: {metadata['timezone']}. {source_description}"
    return query_tools
