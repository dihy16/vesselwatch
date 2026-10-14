"""Explicit LangGraph agent -> tools -> agent loop."""

import os
from datetime import date

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from pydantic import ValidationError
from langchain_core.tools import ToolException

from .mock_data import today
from .tools import create_tools


def build_agent(*, model: ChatOpenAI | None = None, reference_date: date | None = None):
    reference_date = reference_date or today()
    tools = create_tools(reference_date)
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
    prompt = SystemMessage(content=f"""Bạn là trợ lý truy vấn dữ liệu tàu khả nghi, trả lời bằng tiếng Việt.
Ngày tham chiếu là {reference_date.isoformat()}, múi giờ Asia/Ho_Chi_Minh.
Đây là bản demo: mọi quan sát, vị trí, phân loại và URL đều là dữ liệu giả lập.
Dùng count_ships cho thống kê theo ngày; search_ships cho danh sách, kích thước,
phân loại hoặc xem riêng ship_id. Luôn dùng tool để lấy dữ liệu, không tự bịa số.
Ngày truyền vào tool chỉ có YYYY-MM-DD, bao gồm cả hai đầu mốc.
'7 ngày qua' là ngày tham chiếu và 6 ngày trước đó. Không có khoảng ngày thì
search_ships tìm toàn bộ dữ liệu. Không tự thêm bộ lọc người dùng không yêu cầu.
Đếm theo ngày không phải số tàu duy nhất của cả giai đoạn; không cộng các ngày
rồi gọi tổng đó là số tàu duy nhất. Phân loại aircraft_carrier chỉ là kết quả mô hình.
Trình bày thống kê bằng bảng. Với danh sách tàu, đưa ship_url và độ tin cậy nếu có.
Nếu người dùng yêu cầu xem ảnh, đưa Markdown ![chú thích](URL) từ images của tool,
nói rõ đây là URL ảnh giả lập; chưa có ảnh thật và bạn chưa phân tích nội dung ảnh.
Kết quả có total lớn hơn số bản ghi trả về thì nói rõ phân trang, không gọi đó là toàn bộ.
Khi tool báo lỗi, sửa tham số hoặc giải thích yêu cầu cần điều chỉnh.
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
