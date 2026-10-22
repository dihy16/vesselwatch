"""Daily report tool for real, demo and mock sources."""

from urllib.parse import urlencode

from langchain_core.tools import ToolException, tool

from file_server.services.carrier_reports import daily_carrier_report as aggregate_carriers
from ship_agent.clients.file_server_client import FileServerError, load_daily_carrier_report
from ship_agent.tools.schemas import CarrierReportInput
from ship_agent.tools.validation import _date_range


def create_report_tools(context):
    observations, metadata, is_mock = context.observations, context.metadata, context.is_mock
    data_source, demo_snapshot, anchor = context.data_source, context.demo_snapshot, context.anchor

    @tool(args_schema=CarrierReportInput)
    def daily_carrier_report(observed_from: str, observed_to: str, output_format: str = "html") -> dict:
        """Tạo báo cáo HTML hoặc ảnh chart PNG lượt dự đoán tàu sân bay theo ngày.

        Dùng khi người dùng yêu cầu báo cáo/chart/biểu đồ tàu sân bay hoặc tàu khả nghi.
        Chỉ đếm aircraft_carrier, không đếm toàn bộ tàu khả nghi. Đây là lượt
        phát hiện từ từng ảnh, không phải số tàu duy nhất hoặc nhãn đã xác nhận.
        Ngày từ caption, gồm cả hai đầu mốc, tối đa 366 ngày. Trả daily_stats,
        total_detections; hệ thống dùng chúng để đính kèm HTML vào câu trả lời.
        output_format=png khi yêu cầu ảnh chart PNG riêng; hệ thống đính kèm ảnh
        từ chart_url vào chat. Mặc định html tạo báo cáo Artifacts hoàn chỉnh.
        Mock trả số liệu giả lập và chart_url=null, vẫn dựng được báo cáo HTML.
        PNG cần server ảnh ở chế độ demo hoặc file_server; không hỗ trợ mock.
        """
        first, last = _date_range(observed_from, observed_to)
        if not 0 <= (last - first).days < 366:
            raise ToolException("Mỗi báo cáo có từ 1 đến 366 ngày.")
        if is_mock and output_format == "png":
            raise ToolException("Ảnh chart PNG cần server demo hoặc file_server; mock hỗ trợ báo cáo HTML.")
        if is_mock or data_source == "demo":
            result = aggregate_carriers(observations, first, last)
            if output_format == "png":
                from ship_agent.data.demo_data import public_base_url
                query = urlencode({"observed_from": observed_from, "observed_to": observed_to,
                                   "report_id": result["report_id"],
                                   "snapshot_id": demo_snapshot["snapshot_id"]})
                return {**result, **metadata, "output_format": "png",
                        "chart_url": f"{public_base_url()}/charts/daily-carriers.png?{query}"}
            return {**result, **metadata, "chart_url": None}
        try:
            return {**load_daily_carrier_report(first, last),
                    "reference_date": anchor.isoformat(), "output_format": output_format}
        except FileServerError as exc:
            raise ToolException(str(exc)) from exc

    return [daily_carrier_report]
