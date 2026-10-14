# Agent truy vấn tàu — level 1

## FastAPI phục vụ dữ liệu thật trên MID

Server dữ liệu chạy riêng với LangGraph. Agent mặc định đọc dữ liệu thật qua HTTP;
`--mock-tools` chọn dữ liệu giả lập để thử tools độc lập.

Trên MID, cài dependencies và sửa trực tiếp các hằng số trong `file_server/config.py`:

```bash
python -m pip install -r requirements.txt
```

| Biến | Nội dung |
| --- | --- |
| `TELEGRAM_METADATA_PATH` | JSON array Telegram, có `message_id`, `date`, `caption`, `image` |
| `TELEGRAM_IMAGE_ROOT` | Thư mục chứa ảnh, ví dụ `/data2/DATA/telegram_data/images` |
| `PREDICTIONS_PATH` | Đường dẫn file JSON export chứa mảng `predictions` |
| `DATA_API_BASE_URL` | URL gốc cho `ship_url` và URL ảnh, mặc định `http://127.0.0.1:8001` |

Điền `PREDICTIONS_PATH` trong file cấu hình trước khi chạy; mặc định để trống và server
báo lỗi nếu chưa điền. Server dữ liệu không đọc `.env` hoặc biến môi trường để cấu hình.
Các đường dẫn phải là đường dẫn thực trên MID. Không cần checkpoint, GPU hoặc API key
để chạy server dữ liệu. Server đọc trực tiếp file export; các đường dẫn checkpoint và
`report_path` trong `runs` chỉ là thông tin nguồn, không được mở. Không cần manifest
hoặc tracking JSON. Lỗi nạp JSON báo file, dòng và cột.

Ví dụ cấu hình trên MID (thay bằng đường dẫn thật tới file export đầy đủ):

```python
PREDICTIONS_PATH = Path("/absolute/path/to/predictions.json")
```

File export có cấu trúc:

```json
{
  "schema_version": 2,
  "predictions": [
    {
      "image_path": "/data2/DATA/telegram_data/images/photo_2026-05-17_05-33-24.jpg",
      "carrier_probability": 0.97,
      "predicted_aircraft_carrier": true
    }
  ]
}
```

```bash
python -m uvicorn file_server.app:create_app --factory --host 127.0.0.1 --port 8001
```

Mở `http://127.0.0.1:8001/docs` để thử API:

- `GET /health`: số observation, prediction đã ghép, unknown và số bản ghi bị bỏ qua.
- `GET /observations?observed_from=2026-10-01&observed_to=2026-10-14&limit=20&offset=0`:
  lọc ngày UTC, tính cả hai đầu mốc; trả `total`, `limit`, `offset`, `observations`.
  Có thể bỏ một hoặc cả hai mốc; limit tối đa 100; sắp theo `ship_id` để phân trang ổn định.
- `GET /ships/{ship_id}`: một observation đầy đủ theo cấu trúc mock, hoặc 404.
- `GET /images/{image_id}`: nội dung ảnh và MIME type, hoặc 404. Chỉ ảnh đã đăng ký
  được phục vụ; không nhận đường dẫn file tùy ý.

Ghép tên file trong prediction `image_path` với tên file trong trường `image` của
metadata Telegram. Prediction trùng tên ảnh, score không hữu hạn/ngoài [0, 1] hoặc
nhãn không phải boolean gây lỗi khởi động. `carrier_probability` được giữ nguyên;
`predicted_aircraft_carrier=true` là `aircraft_carrier`, false là `not_aircraft_carrier`;
không có prediction là `unknown`, `confidence = null`. `confidence` giữ carrier
score nguyên gốc: 0.1 nghĩa là score tàu sân bay 10%, không phải độ tin cậy nhãn âm.
Server nạp toàn bộ `predictions`, giữ score và cờ `predicted_aircraft_carrier` đã lưu;
không áp ngưỡng hoặc lọc theo `review_tier`, `mining_threshold` hay `positive_count`.
Cờ này là kết quả dự đoán/chọn review của notebook, chưa phải nhãn xác nhận thủ công.
`ensemble_method` và ID `runs` được trả trong `/health` để xem nguồn prediction.

Mỗi tên file ảnh Telegram có một `ship_id` riêng, được tạo ổn định bằng SHA-256
của tên file. Hai ảnh cùng detection ID vẫn là hai tàu riêng. Bản ghi lặp cùng tên
file/cùng detection chỉ giữ một; cùng tên file nối nhiều detection gây lỗi.
`observation_id` và `image_id` cũng dựa trên tên file. Lấy tọa độ từ `- Vị trí:`,
chiều dài/rộng từ `- Dài / Rộng:`, thời gian quan sát từ `- Thời gian:` trong caption.
Giờ trong caption là UTC và giữ nguyên UTC (`observed_at` có `+00:00`, `observed_date`
là ngày UTC); không dùng `date` của message vì đó là ngày gửi Telegram.
Ví dụ `2026-05-15 10:04:14` → `2026-05-15T10:04:14+00:00`.
Tên file lấy từ trường `image`: `telegram_data/images/photo_2026-05-17_05-33-24.jpg`
→ `photo_2026-05-17_05-33-24.jpg` trong `TELEGRAM_IMAGE_ROOT`.
Thiếu detection ID, file ảnh hoặc loại ảnh không hỗ trợ thì bỏ qua và đếm
trong `/health`; ảnh khớp nhưng caption thiếu/sai trường quan sát gây lỗi khởi động.
Không tự lọc theo ground truth, split hay chiều dài.

Code phục vụ dữ liệu nằm riêng trong `file_server/`: `config.py` chứa các thiết lập,
`app.py` khai báo endpoints, `loader.py` nạp metadata/prediction và tạo observations,
`caption.py` phân tích caption.
Metadata, ảnh và file prediction thật giữ trên MID, ngoài thư mục code.

Metadata/prediction được nạp một lần khi khởi động; đổi dữ liệu hoặc cấu hình cần restart.
Ảnh đọc từ đĩa khi truy cập URL. Nếu xem từ laptop, forward cổng 8001 từ MID và dùng
`DATA_API_BASE_URL = "http://127.0.0.1:8001"` trong `config.py` (hoặc cổng local đã forward). `127.0.0.1`
luôn là máy của bên mở URL. Nếu truy cập MID trực tiếp, cấu hình URL mà trình duyệt
truy cập được và bind Uvicorn vào địa chỉ phù hợp.

Kiểm tra server mà không gọi LLM:

```bash
curl http://127.0.0.1:8001/health
curl 'http://127.0.0.1:8001/observations?limit=1'
```

Tests dùng file tạm, metadata nhỏ và HTTP TestClient trong tiến trình:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests/file_server/test_data_api.py -q
```

Kiểm tra parser bằng thư viện chuẩn, không cần cài dependency:

```bash
python -m unittest discover -s tests/file_server -p test_caption.py -v
```

## Agent truy vấn dữ liệu

Python 3.10+, LangGraph và ChatOpenAI. Khi tool được gọi, nó đọc observations từ
file server rồi đếm/lọc dữ liệu. Chưa có giao diện chat trong repo.

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

# Agent gọi LLM và đọc dữ liệu thật từ file server đang chạy.
python -m ship_agent --show-tools
python -m ship_agent --question "Liệt kê tàu dài 250–350 m, rộng 50–80 m."
python -m ship_agent --question "Những tàu nào được nhận dạng là tàu sân bay?"
python -m ship_agent --question "Liệt kê tàu rồi cho tôi xem ảnh của tàu đầu tiên."
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

Factory tạo graph theo mỗi run để ngày tham chiếu UTC cập nhật theo ngày.
Import module, tạo tools hoặc graph không gọi file server. Khi tool chạy, nó gọi
`/observations` với khoảng ngày được hỏi, lấy đủ các trang 100 bản ghi rồi đếm/lọc.
Mỗi lần gọi tool đọc lại API; snapshot gốc trên file server được nạp lúc server khởi động.
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
python client.py --thread-id THREAD_ID --question "Cho tôi xem ảnh của tàu vừa liệt kê."

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
`YYYY-MM-DD`, tính cả hai đầu mốc theo UTC (mock dùng `Asia/Ho_Chi_Minh`), tối đa 366 ngày/lần gọi.
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
`confidence` (carrier score với dữ liệu thật, null nếu chưa có prediction),
`images` gồm URL/chú thích/MIME type.

Với dữ liệu thật, `ship_id` giữ nguyên tên sau `- Tàu:` trong caption Telegram,
không sinh ID tàu từ tên ảnh. Mỗi ảnh vẫn được đếm và trả về riêng khi trùng tên
tàu; `observation_id` phân biệt các ảnh. `ship_url` có tham số `observation_id`
để mở đúng bản ghi; `/ships/{ship_id}` không có tham số trả lần quan sát mới nhất.

`is_mock`, `reference_date`, `timezone` được trả kèm. Agent thật trả `is_mock=false`
và `timezone="UTC"`. `reference_date` chỉ là mốc giải thích câu hỏi, không đổi ngày
observations. Lỗi kết nối/timeout/HTTP hoặc response sai được báo lỗi tool, không
trả kết quả rỗng hoặc số 0 thay lỗi. Timeout mỗi HTTP request là 30 giây.

Chế độ mock dùng chung một snapshot có 6 tàu, 8 lần quan sát, tạo ngày tương đối theo ngày chạy
(hoặc `--today`). Ví dụ `--today 2026-10-13`: ngày 07/10 có 2 tàu khả nghi,
1 có khả năng là tàu sân bay; ngày 12/10 có 2/1; ngày 13/10 có 2/1.
SHIP_001 có kết quả nhận dạng khác nhau qua các lần quan sát để thử quy tắc chọn
lần cuối. Các URL `example.com` chỉ là placeholder, chưa dẫn tới ảnh thật.
Agent có thể trả Markdown ảnh để frontend hỗ trợ Markdown hiển thị sau này;
không tự tải ảnh hay đưa ảnh vào model vision.

### Cấu hình kết nối tools với file server

Sửa `FILE_SERVER_URL` trong `ship_agent/config.py`, mặc định `http://127.0.0.1:8001`.
Đây là URL LangGraph gọi từ MID; `DATA_API_BASE_URL` trong `file_server/config.py`
là URL được trả về cho trình duyệt mở ảnh. Hai URL có thể khác nhau khi dùng port forwarding.

Trên MID, chạy file server và LangGraph trong hai terminal:

```bash
# Terminal 1
python -m uvicorn file_server.app:create_app --factory --host 127.0.0.1 --port 8001
# Terminal 2
langgraph dev --no-browser
```

LangGraph chạy port 2024. Với trình duyệt trên laptop, forward cả 2024 và 8001
để truy cập chat và ảnh. Có thể thử thống kê một ngày UTC có trong dữ liệu:

```bash
python client.py --question "Thống kê tàu khả nghi ngày 2026-05-15." --show-tools
```

Trong Python, `create_tools()` và `build_agent()` mặc định dùng file server.
Truyền `data_source="mock"` khi muốn dùng mock; `--mock-tools` tự chọn chế độ này.

## Kiểm thử

Tests được chia theo phạm vi: `tests/agent/`, `tests/file_server/` và
`tests/integration/`. Có thể chạy riêng từng nhóm:

```bash
python -m pytest tests/agent -q
python -m pytest tests/file_server -q
python -m pytest tests/integration -q
```

```bash
python -m pytest -q
```

Test kiểm tra đếm trùng, ngày trống, lọc/phân trang, dữ liệu sai và vòng lặp graph
với **ChatOpenAI thật nhưng HTTP response giả lập**. Không cần key thật, không
gọi mạng. Tests nguồn thật dùng HTTPX MockTransport để kiểm tra đủ trang, ngày UTC,
lọc trước phân trang và lỗi nguồn dữ liệu. Muốn xác minh model tự chọn tool bằng
LLM thật, chạy CLI với API key.

Tham khảo: [LangGraph quickstart](https://docs.langchain.com/oss/python/langgraph/quickstart),
[ChatOpenAI tools](https://docs.langchain.com/oss/python/integrations/chat/openai),
[OpenAI Docs: function calling](https://developers.openai.com/api/docs/guides/function-calling).
