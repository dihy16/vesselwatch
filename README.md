# Agent truy vấn tàu — level 1

Python 3.10+, LangGraph và ChatOpenAI. Hai tools đọc dữ liệu giả lập trong bộ nhớ,
không cần SQLite hoặc dịch vụ lưu trữ. Chưa có giao diện chat.

```text
START → agent (ChatOpenAI.bind_tools)
          ├─ có tool_calls → tools (ToolNode) → agent
          └─ trả lời → END
```

## Cài đặt và chạy

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env
```

Điền `OPENAI_API_KEY` trong `.env`. `OPENAI_MODEL` mặc định là `gpt-4.1-mini`;
có thể đổi sang model hỗ trợ tool calling với ChatOpenAI. Không commit `.env`.

Để dùng endpoint tùy chỉnh tương thích OpenAI, cấu hình trong `.env`:

```dotenv
OPENAI_BASE_URL=http://localhost:8000/v1
OPENAI_MODEL=your-model-name
OPENAI_API_KEY=your-endpoint-key
```

`OPENAI_BASE_URL` là API root (thường kết thúc bằng `/v1`), không phải URL đầy đủ
`/chat/completions`. Để trống khi dùng endpoint OpenAI mặc định. Nếu server local
không yêu cầu xác thực, đặt `OPENAI_API_KEY=local-demo` để khởi tạo client.
Endpoint và model cần hỗ trợ `tools`/`tool_calls` để agent gọi được hai tools.
Tham khảo [cấu hình base_url của ChatOpenAI](https://docs.langchain.com/oss/python/integrations/chat/openai).

```bash
# Thử tools trực tiếp, không cần API key và không phát sinh lời gọi OpenAI.
python -m ship_agent --mock-tools --today 2026-10-13

# Agent gọi LLM thật; dữ liệu do tools trả về vẫn là giả lập.
python -m ship_agent --show-tools
python -m ship_agent --question "Liệt kê tàu dài 250–350 m, rộng 50–80 m."
python -m ship_agent --question "Những tàu nào được nhận dạng là tàu sân bay?"
python -m ship_agent --question "Cho tôi xem ảnh và thông tin tàu SHIP_001."
```

Mỗi lần chạy CLI xử lý một câu hỏi, giữ messages trong toàn bộ vòng gọi tools của
câu hỏi đó. Trong Python, có thể gọi `build_agent()` và truyền lịch sử messages vào
`graph.invoke(...)` để tiếp tục hội thoại. Chưa cấu hình checkpoint lưu hội thoại.

## Chạy bằng LangGraph dev / Studio

Cần Python 3.11+. Từ thư mục gốc dự án, dùng `.env` đã cấu hình
`OPENAI_API_KEY`, `OPENAI_MODEL` và `OPENAI_BASE_URL` nếu dùng endpoint tùy chỉnh:

```bash
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
langgraph dev
```

`langgraph.json` đăng ký graph `agent`, tự nạp `.env` và dùng factory
`ship_agent/graph.py:make_graph`. Server dev chạy ở `http://127.0.0.1:2024`,
API docs ở `http://127.0.0.1:2024/docs`. Mở liên kết Studio do terminal in ra,
đăng nhập LangSmith khi được yêu cầu, rồi chọn graph `agent` để chat và xem tool calls.
Không cần Docker. Server dev quản lý threads/checkpoints; dữ liệu phát sinh
trong `.langgraph_api/` được bỏ qua bởi Git.

Nếu chạy trên máy remote hoặc không muốn tự mở trình duyệt:

```bash
langgraph dev --no-browser
```

Dùng port forwarding tới cổng 2024 nếu trình duyệt ở máy khác.
Graph nhận input dạng:

```json
{
  "messages": [
    {"role": "user", "content": "Thống kê tàu khả nghi theo ngày trong 7 ngày qua."}
  ]
}
```

Factory tạo graph theo mỗi run để ngày tham chiếu và mock data cập nhật theo ngày.
Chạy server không tự gọi LLM; khi gửi câu hỏi, agent mới gọi endpoint trong `.env`.
Xem [hướng dẫn LangGraph dev](https://docs.langchain.com/langsmith/local-dev-testing).

## Client test server LangGraph

Giữ `langgraph dev` đang chạy, mở terminal khác và kích hoạt `.venv`:

```bash
source .venv/bin/activate
python -m pip install -r requirements-dev.txt

# Gửi một câu hỏi và xem các tool mà agent gọi.
python client.py --question "Thống kê tàu khả nghi theo ngày trong 7 ngày qua." --show-tools

# Chat nhiều lượt trên cùng thread, ví dụ hỏi tiếp "Cho xem ảnh tàu đầu tiên".
python client.py --chat --show-tools

# Tiếp tục hội thoại bằng Thread ID được client in ra.
python client.py --thread-id THREAD_ID --question "Cho tôi xem ảnh tàu SHIP_001."

# Nếu server dùng cổng khác.
python client.py --url http://127.0.0.1:2025 --question "Liệt kê tàu sân bay."
```

Không truyền tham số thì client gửi câu hỏi thống kê 7 ngày qua. Trong chế độ
`--chat`, nhập `/exit`, `/quit` hoặc Ctrl+D để thoát. Mỗi lần chạy tạo thread mới,
trừ khi truyền `--thread-id`. Client chỉ gửi message mới; server giữ lịch sử hội thoại.
Kết quả được in khi run hoàn tất; `--show-tools` in tool calls/kết quả của lượt vừa gửi.
Timeout HTTP mặc định 300 giây, có thể đổi bằng `--timeout`.

Client dùng [LangGraph Python SDK](https://reference.langchain.com/python/langgraph-sdk/client)
để gọi API server, không cần đọc `.env`; server dùng cấu hình LLM đã nạp khi khởi động.
Mỗi câu hỏi sẽ gọi LLM đã cấu hình trên server.

## Hợp đồng tools

`count_ships(observed_from, observed_to)` trả `daily_stats`, mỗi ngày gồm
`suspicious_ship_count` và `possible_aircraft_carrier_count`. Hai ngày là chuỗi
`YYYY-MM-DD`, tính cả hai đầu mốc theo `Asia/Ho_Chi_Minh`, tối đa 366 ngày/lần gọi.
Ngày trống có số 0. Toàn bộ tàu trong tập dữ liệu đều là tàu khả nghi.
Đếm ID duy nhất mỗi ngày; phân loại dựa trên lần quan sát cuối ngày.
`aircraft_carrier` được tính là có khả năng là tàu sân bay, không áp thêm ngưỡng
confidence. Không cộng các ngày để suy ra số tàu duy nhất cả giai đoạn.

`search_ships` có các tham số tùy chọn:

| Tham số | Ý nghĩa |
| --- | --- |
| `observed_from`, `observed_to` | Ngày; có thể lọc một đầu mốc hoặc bỏ cả hai |
| `ship_id` | ID chính xác, dùng để xem riêng tàu |
| `min_length_m`, `max_length_m` | Chiều dài mét, gồm cả hai đầu mốc |
| `min_width_m`, `max_width_m` | Chiều rộng mét, gồm cả hai đầu mốc |
| `classification` | `aircraft_carrier`, `not_aircraft_carrier`, `unknown` |
| `limit`, `offset` | Mặc định 20/0, limit tối đa 100 |

Chọn lần quan sát mới nhất của mỗi tàu **trong khoảng ngày**, sau đó mới lọc
kích thước/phân loại. Sắp xếp theo `ship_id` để phân trang ổn định.
Trả `total` trước phân trang, `filters`, `ships` gồm ID tàu và lần quan sát,
`ship_url`, `observed_date`, `observed_at`, kích thước, vị trí, phân loại,
`confidence` (null nếu chưa xác định), `images` gồm URL/chú thích/MIME type.

Hai tools cùng dùng một snapshot. `is_mock`, `reference_date`, `timezone` được
trả kèm. Mock có 6 tàu, 8 lần quan sát, tạo ngày tương đối theo ngày chạy
(hoặc `--today`). Ví dụ `--today 2026-10-13`: ngày 07/10 có 2 tàu khả nghi,
1 có khả năng là tàu sân bay; ngày 12/10 có 2/1; ngày 13/10 có 2/1.
SHIP_001 có kết quả nhận dạng khác nhau qua các lần quan sát để thử quy tắc chọn
lần cuối. Các URL `example.com` chỉ là placeholder, chưa dẫn tới ảnh thật.
Agent có thể trả Markdown ảnh để frontend hỗ trợ Markdown hiển thị sau này;
không tự tải ảnh hay đưa ảnh vào model vision.

## Kiểm thử

```bash
python -m pytest -q
```

Test kiểm tra đếm trùng, ngày trống, lọc/phân trang, dữ liệu sai và vòng lặp graph
với **ChatOpenAI thật nhưng HTTP response giả lập**. Không cần key thật, không
gọi mạng. Muốn xác minh model tự chọn tool bằng LLM thật, chạy CLI với API key.

Tham khảo: [LangGraph quickstart](https://docs.langchain.com/oss/python/langgraph/quickstart),
[ChatOpenAI tools](https://docs.langchain.com/oss/python/integrations/chat/openai),
[OpenAI Docs: function calling](https://developers.openai.com/api/docs/guides/function-calling).
