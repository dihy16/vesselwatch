"""Explicit LangGraph agent -> tools -> agent loop."""

import json
import os
import re
from datetime import date
from uuid import uuid4

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from pydantic import ValidationError
from langchain_core.tools import ToolException
from langchain_core.runnables import RunnableConfig

from .dates import DataSource, data_timezone, resolve_reference_date
from .report_artifacts import render_carrier_artifact
from .map_artifacts import render_map_artifact
from .llm_context import messages_for_llm
from .chat_area import chat_area_note
from .tools import create_tools


def _current_reports(messages: list[BaseMessage]) -> list[dict]:
    """Use successful report calls from this turn, never a previous answer."""
    turn = []
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        turn.append(message)
    reports = {}
    for message in reversed(turn):
        if isinstance(message, ToolMessage) and message.name == "daily_carrier_report":
            if message.status == "error":
                reports.clear()
            else:
                report = json.loads(message.content)
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
        if isinstance(message, ToolMessage) and message.name in {"create_vessel_map", "query_ships_in_area", "analyze_ship_observations"}:
            if message.status == "error":
                maps.clear()
            else:
                result = json.loads(message.content)
                if result.get("persistent_map"):
                    # The user already has the chat-linked map mounted in Artifacts.
                    continue
                if message.name in {"query_ships_in_area", "analyze_ship_observations"}:
                    maps = {key: value for key, value in maps.items() if value.get("status") != "needs_drawing"}
                if message.name == "create_vessel_map" or result.get("status") == "needs_drawing":
                    maps[result.get("map_id", result.get("selection_id"))] = result
    return list(maps.values())


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
                   "Tools đọc dữ liệu thật từ file server. Mỗi ảnh là một lượt quan sát riêng; "
                   "không suy ra danh tính cùng tàu qua nhiều ảnh.")
    if data_source == "demo":
        source_note = ("Tools cung cấp ảnh vệ tinh, thông tin quan sát và kết quả phân loại. "
                       "ship_id là ID tàu gốc (source_id) trong dữ liệu nguồn; giữ nguyên ID, không đặt bí danh. "
                       "Dùng số liệu tool trả về, không thay đổi ngày, vị trí, kích thước hay điểm dự đoán.")
    response_note = ("Trả lời trực tiếp kết quả người dùng hỏi, ngắn gọn, ưu tiên bảng hoặc ảnh được yêu cầu. "
                     "Không tự thêm mục 'Lưu ý', 'Ghi chú', cảnh báo hoặc đoạn giải thích cuối câu trả lời. "
                     "Trong các câu trả lời truy vấn thông thường, không nhắc đến demo, tập demo, bộ dữ liệu demo, "
                     "tập mẫu đã chọn, dữ liệu cố định, kết quả đã lưu hay việc không chạy inference mới. "
                     "Các trường is_demo, data_scope, demo_snapshot_id là metadata nội bộ; không đưa chúng vào câu trả lời. "
                     "Dùng cách gọi 'nghi là tàu sân bay' hoặc 'lượt phát hiện nghi là tàu sân bay' ngay trong kết quả. "
                     "Không tự giải thích lại ý nghĩa ID tàu, carrier score, làm tròn kích thước hoặc giới hạn dữ liệu. "
                     "Chỉ giải thích các nội dung này khi người dùng hỏi trực tiếp; khi đó trả lời đúng nguồn và phạm vi thực tế. "
                     "Không khẳng định đang nhận diện ảnh mới, theo dõi trực tiếp hay xác nhận danh tính tàu. "
                     "Vẫn báo lỗi truy vấn, thiếu dữ liệu hoặc phân trang khi chúng ảnh hưởng trực tiếp đến yêu cầu."
                     if data_source == "demo" else "")
    image_note = ("Nói rõ đây là URL ảnh giả lập và bạn chưa phân tích nội dung ảnh."
                  if data_source == "mock" else
                  "URL ảnh từ tool truy vấn chỉ dùng hiển thị; bạn chưa phân tích ảnh cho tới khi "
                  "review_ship_images trả thành công. Khi yêu cầu đọc/phân tích ảnh hoặc kiểm tra lại "
                  "nhận dạng, lấy observation_id bằng tool truy vấn rồi gọi review_ship_images. "
                  "Dùng visual_review để mô tả ảnh; phân biệt với saved_prediction. "
                  "Nếu comparison=disagrees, nói cần kiểm tra lại, không kết luận nhãn gốc sai. "
                  "Nếu unknown/inconclusive, nói chưa đủ bằng chứng. Không coi review là ground truth.")
    confidence_note = ("Với danh sách tàu, đưa ship_url và độ tin cậy nếu có."
                       if data_source == "mock" else
                       "Với danh sách tàu, đưa ship_url và carrier score nếu có. confidence là score "
                       "tàu sân bay, không phải độ tin cậy của nhãn âm. Nhãn unknown là chưa có prediction; "
                       "vị trí hoặc kích thước null là thiếu dữ liệu, không suy đoán giá trị.")
    map_note = ("Khi yêu cầu bản đồ/map, dùng create_vessel_map với khoảng ngày và đúng bộ lọc người dùng yêu cầu. "
                "Nếu chưa có khoảng ngày từ câu hỏi hoặc ngữ cảnh, hỏi người dùng để xác định khoảng ngày. "
                "Tool trả URL và tổng lượt quan sát; hệ thống tự đính kèm iframe HTML Artifacts. "
                "Chỉ viết tóm tắt ngắn, không tải hay tự viết lại HTML/Leaflet của map. "
                if data_source == "demo" else "")
    prompt = SystemMessage(content=f"""Bạn là trợ lý truy vấn dữ liệu tàu khả nghi, trả lời bằng tiếng Việt.
Ngày tham chiếu là {reference_date.isoformat()}, múi giờ {data_timezone(data_source)}.
{source_note}
{map_note}
Dùng count_ships cho thống kê theo ngày; search_ships cho danh sách, kích thước,
phân loại hoặc xem riêng ship_id. Luôn dùng tool để lấy dữ liệu, không tự bịa số.
Với truy vấn khu vực hoặc vị trí của tàu dài trên một mức, dùng query_ships_in_area
nếu tool này có sẵn. Chỉ Biển Đông và Vịnh Bắc Bộ có vùng định nghĩa sẵn.
Tên hiển thị và tên vùng truyền vào tool dùng tiếng Việt; gọi Biển Đông là Biển Đông.
Mọi khu vực khác hoặc mô tả mơ hồ: gọi tool với area_name nguyên văn, nhận
needs_drawing rồi mời người dùng tự vẽ rectangle/polygon và bấm xác nhận trên map.
Hệ thống tự đính kèm map; không gợi ý hay tự tạo polygon để người dùng chỉnh sửa.
Không kết luận không có tàu khi status là needs_drawing. Không tự bịa area_id.
Nếu có area_id do người dùng cung cấp, dùng mã đó cùng đúng bộ lọc đang được hỏi.
length_gt_m dùng cho chiều dài lớn hơn nghiêm ngặt (trên 250 m là length_gt_m=250).
Với kích thước phù hợp tàu sân bay nhưng mô hình kết luận không phải, dùng
analyze_ship_observations với analysis="dimension_mismatch". Mặc định dài 250–350 m,
rộng 50–80 m; nêu khoảng đã dùng nếu người dùng chưa chỉ định. Đây là tiêu chí
lọc kích thước, không kết luận mô hình sai hay xác nhận loại tàu.
Với dài trên 250 m, được nhận dạng tàu sân bay và score trên 80%, dùng
query_ships_in_area (hoặc search_ships nếu không có vùng) với length_gt_m=250,
classification="aircraft_carrier", carrier_score_gt=0.8. Lấy total do tool trả về,
không đếm số dòng của trang; carrier score không phải độ tin cậy nhãn âm.
Với kích thước tương đồng nhưng kết quả phân loại khác nhau, dùng
analyze_ship_observations với analysis="similar_dimensions", bỏ classification.
Sai lệch mặc định 10% cho CẢ chiều dài và rộng, mẫu số là kích thước lớn hơn;
dùng similarity_tolerance_pct khác nếu người dùng chỉ định. Trả ví dụ theo cặp,
kèm kích thước và nhãn của hai observations; nêu total là số cặp, không phải
số tàu duy nhất, không khẳng định hai observations thuộc cùng một tàu.
Kết quả truy vấn vùng đếm lượt phát hiện riêng theo observation_id, không đếm tàu duy nhất.
Ngày truyền vào tool chỉ có YYYY-MM-DD, bao gồm cả hai đầu mốc.
'7 ngày qua' là ngày tham chiếu và 6 ngày trước đó. Không có khoảng ngày thì
search_ships tìm toàn bộ dữ liệu. Không tự thêm bộ lọc người dùng không yêu cầu.
Đếm theo ngày không phải số tàu duy nhất của cả giai đoạn; không cộng các ngày
rồi gọi tổng đó là số tàu duy nhất. Phân loại aircraft_carrier chỉ là kết quả mô hình.
Trình bày thống kê bằng bảng. {confidence_note}
Khi người dùng yêu cầu báo cáo hoặc biểu đồ/chart, dùng daily_carrier_report.
Nếu yêu cầu ảnh chart PNG riêng hoặc biểu đồ trực tiếp trong chat, đặt output_format="png".
Nếu yêu cầu báo cáo HTML Artifacts, đặt output_format="html" (mặc định).
Tool này chỉ thống kê lượt dự đoán tàu sân bay; nêu rõ phạm vi này trong câu trả lời.
Viết nhận xét ngắn từ daily_stats và total_detections, không tự tính lại nhãn từ score.
Với output_format="html", hệ thống đính kèm HTML hoàn chỉnh trong code block html
để Open WebUI mở bằng Artifacts. Chỉ viết phần nhận xét, không tự tạo HTML,
không chèn ảnh PNG hoặc liên kết chart_url thay cho báo cáo HTML.
Với output_format="png", hệ thống đính kèm ảnh chart vào chat; chỉ viết nhận xét ngắn,
không tự tạo HTML hay sửa URL ảnh tool trả về.
Mock vẫn có báo cáo HTML từ số liệu giả lập; luôn nêu rõ dữ liệu giả lập.
Nếu nguồn báo lỗi, không dùng số liệu cũ hoặc bịa báo cáo.
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
{response_note}
""")

    def call_model(state: MessagesState, config: RunnableConfig):
        reports = _current_reports(state["messages"])
        maps = _current_maps(state["messages"])
        demo_images_requested = False
        if data_source == "demo":
            from .demo_data import wants_demo_images
            demo_images_requested = wants_demo_images(state["messages"])
        # Reports are added deterministically, without asking the LLM to copy HTML.
        # Emit the complete node output in messages mode instead of streaming an
        # incomplete answer before the artifact has been attached.
        area_note = chat_area_note(config)
        messages = [prompt]
        if area_note:
            messages.append(SystemMessage(content=area_note))
        messages.extend(messages_for_llm(state["messages"]))
        response = llm_with_tools.invoke(
            messages,
            config={"tags": ["nostream"]} if reports or maps or demo_images_requested else None,
        )
        if (reports or maps) and not response.tool_calls:
            artifacts = []
            for report in reports:
                if report.get("output_format") == "png":
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
            from .demo_data import demo_image_markdown
            images = demo_image_markdown(state["messages"], response.text)
            if images:
                response = response.model_copy(update={
                    "id": str(uuid4()), "content": f"{response.text}\n\n{images}",
                })
        return {"messages": [response]}

    graph = StateGraph(MessagesState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", ToolNode(tools, handle_tool_errors=(ToolException, ValidationError)))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")
    return graph.compile()
