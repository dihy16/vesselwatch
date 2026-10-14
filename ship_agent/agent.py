"""Explicit LangGraph agent -> tools -> agent loop."""

import os
from datetime import date

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from pydantic import ValidationError
from langchain_core.tools import ToolException

from .dates import DataSource, data_timezone, resolve_reference_date
from .tools import create_tools


def build_agent(
    *, model: ChatOpenAI | None = None, reference_date: date | None = None,
    data_source: DataSource = "file_server",
    observations: list[dict] | None = None,
):
    reference_date = resolve_reference_date(reference_date, data_source)
    tools = create_tools(reference_date, data_source=data_source, observations=observations)
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
    source_note = ("Chế độ mock: mọi quan sát, vị trí, phân loại và URL đều là dữ liệu giả lập."
                   if data_source == "mock" else
                   "Tools đọc dữ liệu thật từ file server. Mỗi ảnh Telegram là một tàu riêng; "
                   "không suy ra danh tính cùng tàu qua nhiều ảnh.")
    image_note = ("Nói rõ đây là URL ảnh giả lập và bạn chưa phân tích nội dung ảnh."
                  if data_source == "mock" else
                  "Đây là URL ảnh thật do file server phục vụ; bạn chưa tải hay phân tích nội dung ảnh.")
    confidence_note = ("Với danh sách tàu, đưa ship_url và độ tin cậy nếu có."
                       if data_source == "mock" else
                       "Với danh sách tàu, đưa ship_url và carrier score nếu có. confidence là score "
                       "tàu sân bay, không phải độ tin cậy của nhãn âm. File server chỉ trả ảnh có prediction.")
    prompt = SystemMessage(content=f"""Bạn là trợ lý truy vấn dữ liệu tàu khả nghi, trả lời bằng tiếng Việt.
Ngày tham chiếu là {reference_date.isoformat()}, múi giờ {data_timezone(data_source)}.
{source_note}
Dùng count_ships cho thống kê theo ngày; search_ships cho danh sách, kích thước,
phân loại hoặc xem riêng ship_id. Luôn dùng tool để lấy dữ liệu, không tự bịa số.
Ngày truyền vào tool chỉ có YYYY-MM-DD, bao gồm cả hai đầu mốc.
'7 ngày qua' là ngày tham chiếu và 6 ngày trước đó. Không có khoảng ngày thì
search_ships tìm toàn bộ dữ liệu. Không tự thêm bộ lọc người dùng không yêu cầu.
Đếm theo ngày không phải số tàu duy nhất của cả giai đoạn; không cộng các ngày
rồi gọi tổng đó là số tàu duy nhất. Phân loại aircraft_carrier chỉ là kết quả mô hình.
Trình bày thống kê bằng bảng. {confidence_note}
Khi người dùng yêu cầu báo cáo hoặc biểu đồ/chart, dùng daily_carrier_report.
Tool này chỉ thống kê lượt dự đoán tàu sân bay; nêu rõ phạm vi này trong câu trả lời.
Viết nhận xét ngắn từ daily_stats và total_detections, không tự tính lại nhãn từ score.
Nếu chart_url có giá trị, luôn chèn ![Biểu đồ lượt phát hiện nghi là tàu sân bay](chart_url)
với URL nguyên vẹn từ tool, giữ đầy đủ query string; không chỉ đưa liên kết chữ.
Nếu chart_url=null, nói chưa có ảnh chart và không tự tạo URL.
Nếu nguồn báo lỗi, không dùng số liệu cũ hoặc bịa URL chart.
Đây là số lượt trong observations đã ghép metadata/prediction và có ảnh; không
khẳng định đã bao phủ toàn bộ predictions.json. Dùng coverage nếu cần giải thích
các bản ghi bị bỏ qua. Không suy luận biến động số lượt là biến động số tàu thực tế.
Khi hiển thị ngày giờ, chỉ dùng nhãn 'Thời gian', không ghi 'Thời gian (UTC)'
hay thêm hậu tố múi giờ. Giữ nguyên giá trị thời gian của dữ liệu, không chuyển múi giờ.
Nếu người dùng yêu cầu xem ảnh, đưa Markdown ![chú thích](URL) từ images của tool,
Hiển thị ship_id đúng như tool trả về (tên tàu trong dòng '- Tàu:' của caption Telegram),
dùng ship_id làm chú thích ảnh; không tự tạo hay rút gọn ID tàu.
{image_note}
Kết quả có total lớn hơn số bản ghi trả về thì nói rõ phân trang, không gọi đó là toàn bộ.
Khi tool báo lỗi tham số, sửa tham số hoặc giải thích yêu cầu cần điều chỉnh.
Khi nguồn dữ liệu báo lỗi, nói rõ chưa truy vấn được; không suy ra không có tàu.
""")

    def call_model(state: MessagesState):
        return {"messages": [llm_with_tools.invoke([prompt, *state["messages"]])]}

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", ToolNode(tools, handle_tool_errors=(ToolException, ValidationError)))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")
    return graph.compile()
