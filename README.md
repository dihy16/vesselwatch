# Agent truy vấn tàu

## Thử đọc ảnh bằng AI

Tool `review_ship_images(observation_id)` đọc ảnh đầu tiên của một lượt quan sát,
trả đặc điểm nhìn thấy, chất lượng ảnh, giới hạn đánh giá và đối chiếu với prediction
đã lưu. Lấy `observation_id` từ `search_ships` hoặc `query_ships_in_area` trước.
Trong chat có thể hỏi: “Phân tích ảnh của tàu [ID] và đối chiếu kết quả nhận dạng”.
Tool có trong chế độ `demo` và `file_server`; mock không có ảnh thật.

Model/endpoint phải hỗ trợ ảnh và trả JSON. Mặc định dùng cấu hình `OPENAI_MODEL`,
`OPENAI_BASE_URL`, `OPENAI_API_KEY`; có thể cấu hình riêng trong `.env` bằng
`OPENAI_VISION_MODEL`, `OPENAI_VISION_BASE_URL`, `OPENAI_VISION_API_KEY`.
Biến vision để trống sẽ dùng giá trị tương ứng của agent.

Chạy trực tiếp, không cần LLM điều phối hoặc server demo:

```powershell
# Xem các observation_id có sẵn trong bộ ảnh demo.
python -c "from ship_agent.demo_data import load_demo_observations; print('\n'.join(o['observation_id'] for o in load_demo_observations()))"
python -m ship_agent.image_review --data-source demo --observation-id <observation_id>
```

Với dữ liệu thật, chạy file server trước và dùng `--data-source file_server`.
Tool tải ảnh qua `FILE_SERVER_URL` nội bộ rồi gửi nội dung ảnh dạng base64 đến
vision endpoint; không yêu cầu endpoint truy cập URL localhost của file server.
Demo đọc ảnh local đã kiểm tra hash. Giới hạn ảnh 10 MB và 16 triệu pixel;
ảnh được chuẩn hóa PNG, không phóng to hoặc suy diễn thêm chi tiết.

Lời gọi thị giác chỉ nhận ảnh, không nhận kích thước, nhãn hay score cũ. Kết quả
`visual_review` được đối chiếu sau với `saved_prediction`; `comparison` là `agrees`,
`disagrees` hoặc `inconclusive`. Ảnh không đủ rõ trả `unknown`. Nhận xét này không
thay nhãn gốc và không phải ground truth hay xác suất đã được hiệu chuẩn.
Hiển thị URL ảnh trong chat không tự động gọi đánh giá ảnh.

Định dạng gửi ảnh tham khảo [OpenAI Images and vision](https://developers.openai.com/api/docs/guides/images-vision).

## Truy vấn theo khu vực

Tool `query_ships_in_area` hỗ trợ dữ liệu thật và demo, với đúng hai luồng:

- **Biển Đông / Vịnh Bắc Bộ:** dùng polygon đã lưu từ Marine Regions (IHO / SeaVoX).
- **Mọi khu vực khác hoặc mô tả mơ hồ:** mở bản đồ cho người dùng tự vẽ rectangle/polygon
  rồi bấm **Xác nhận và hỏi agent**. Không tạo polygon gợi ý.

Trên map hiện có, mở mục **Vùng truy vấn** trong panel Results. Rectangle được vẽ bằng
cách chọn hai góc đối diện. Polygon được vẽ bằng cách bấm các đỉnh rồi chọn **Hoàn tất
polygon**. Có thể xóa và vẽ lại trước khi xác nhận. Tên khu vực hiển thị bằng tiếng Việt.

Backend lọc toàn bộ snapshot của nguồn theo ngày, vùng, kích thước và nhãn trước khi
phân trang. `total` là số `observation_id` khác nhau, chưa phải số tàu duy nhất.
`length_gt_m=250` nghĩa là chiều dài **lớn hơn** 250 m; nhãn tàu sân bay giữ nguyên
prediction đã lưu. Điểm trên đường biên polygon được tính trong vùng.

Nút xác nhận hiển thị số liệu backend, sau đó gọi agent LangGraph và hiện câu trả lời
ngay trong map. Đây là lượt gọi riêng, chưa tự chèn vào thread Open WebUI đang mở.
Để hỏi tiếp trong chat, sao chép **Mã vùng** trên map và đưa vào câu hỏi; agent dùng
`area_id` đó cùng các bộ lọc mới. Nếu iframe chặn request, mở link **Mở bản đồ toàn
màn hình** rồi thao tác. Khi agent lỗi, số liệu vẫn được giữ và có nút **Hỏi lại agent**.

Cấu hình tại `ship_agent/config.py`:

- `LANGGRAPH_URL`: địa chỉ LangGraph dữ liệu thật mà data server truy cập được.
- `DEMO_LANGGRAPH_URL`: địa chỉ LangGraph chạy `langgraph.demo.json` mà server demo truy cập được.

Cả hai mặc định `http://127.0.0.1:2024`; nếu chạy hai graph ở hai server, đặt URL/cổng
tương ứng. API key vẫn nằm ở LangGraph, file server không cần đọc `.env`.
Sau khi cập nhật, restart data server/demo server và LangGraph.

Vùng vẽ được lưu dưới `data/area_queries/real` (đổi bằng `AREA_QUERY_DIR` trong
`file_server/config.py`) hoặc `<demo_root>/area_queries` cho demo. Giữ thư mục này
qua restart để mã vùng còn dùng được. Nếu snapshot dữ liệu thay đổi, mã cũ trả lỗi
409 và cần tạo lại truy vấn vùng. Polygon có sẵn được đóng gói trong
`file_server/area_data/`; `sources.json` ghi nguồn và SHA-256, không tải mạng khi chạy.

Ví dụ:

```text
Từ 01/10/2026 đến 15/10/2026 có những tàu khả nghi nào trong Vịnh Bắc Bộ?
Những tàu dài trên 250 m được quan sát ở những vị trí nào?
Có bao nhiêu lượt nghi là tàu sân bay ở Biển Đông trong tháng vừa qua?
Tìm tàu trong vùng biển quanh Hoàng Sa từ 01/10/2026 đến 15/10/2026.
```

Câu cuối sẽ mở map để người dùng tự vẽ. Bộ kiểm thử không gọi LLM/dịch vụ thật:

```bash
python -m pytest tests/file_server/test_spatial.py tests/file_server/test_area_queries.py tests/agent/test_area_map_ui.py tests/agent/test_area_agent.py tests/integration/test_area_client.py -q
```

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
ảnh không có prediction bị bỏ qua, không đưa vào danh sách hay số đếm của tools.
`/health.skipped.missing_prediction` cho biết số ảnh bị bỏ qua vì lý do này.
`confidence` giữ carrier
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
Endpoint và model cần hỗ trợ `tools`/`tool_calls` để agent gọi được các tools.
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
observations. LangGraph nạp tất cả observations khi khởi động, lấy đủ các trang
và dùng chung snapshot trong bộ nhớ cho các lượt chat. Tools lọc và đếm trên
snapshot, không gọi HTTP khi chạy. Lỗi kết nối/timeout/HTTP hoặc response sai
làm khởi tạo thất bại, không thay bằng dữ liệu rỗng. Timeout mỗi request là 30 giây.
Chạy file server trước LangGraph. Khi cập nhật metadata hoặc predictions, restart
file server rồi restart LangGraph để nạp snapshot mới.

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


## Báo cáo HTML trong Open WebUI Artifacts

### Bản đồ Leaflet nhúng trong demo

Chế độ `langgraph.demo.json` có thêm tool `create_vessel_map` nhận
`observed_from`, `observed_to` và các bộ lọc ID tàu, phân loại, dài/rộng như
`search_ships`. Tool gọi `POST /maps` trên server demo cổng **8002** và trả URL,
số lượt quan sát, bộ lọc và mã snapshot. Agent ghép một HTML Artifacts nhỏ chứa
iframe và link mở toàn màn hình vào câu trả lời. Giữ nguyên kết nối Open WebUI;
không cần thêm/sửa Pipe, Function hoặc Filter.

Server phục vụ bản đồ tại `GET /maps/<map_id>`, dùng lại giao diện Leaflet từ
ShipClassification đã được đóng gói trong `ship_agent/map_assets/`. Không cần
upload repo ShipClassification hoặc chạy thêm dịch vụ/port. Bản đồ mở sẵn kết
quả đúng bộ lọc, dùng ID nguồn và dự đoán đã lưu, không chạy inference mới.

Mỗi map đóng băng dữ liệu và ảnh gốc đã kiểm tra trong `data/demo/maps/`
(được Git bỏ qua). Giữ thư mục này khi deploy để link trong lịch sử chat còn
hoạt động sau restart hoặc thay dữ liệu nguồn. Đây là lượt quan sát, không phải
số tàu duy nhất. Ba mẫu dương trong bộ demo được chọn ở ba vị trí khác nhau;
không đưa crop khác của cùng lượt chụp vào danh sách mẫu dương.
Map và ảnh không cần gọi API từ iframe; nền OpenStreetMap vẫn cần internet.

- `VESSELWATCH_DEMO_PUBLIC_URL`: URL trình duyệt truy cập, mặc định
  `http://127.0.0.1:8002` qua port forwarding.
- `VESSELWATCH_DEMO_API_URL`: URL agent gọi server để tạo map, mặc định
  `http://127.0.0.1:8002`. Nếu agent chạy trong container thì dùng địa chỉ server
  mà container truy cập được. URL này không được đưa vào iframe.
- `VESSELWATCH_DEMO_MAP_DIR`: tùy chọn nơi lưu map; đặt ở server demo, nơi có
  quyền ghi và được giữ lại qua các lần deploy. Server demo không tự đọc `.env`.

Sau khi cập nhật code, restart server demo và LangGraph, giữ forward **8002**.
Thử: **“Hiển thị các quan sát được dự đoán là tàu sân bay từ 01/06/2025 đến
30/12/2025 trên bản đồ tương tác.”** Tool trả 3 quan sát ở 3 vị trí trong snapshot demo.
Mở URL map độc lập trước, sau đó mở iframe trong Artifacts. Nếu độc lập mở được
nhưng iframe trắng, kiểm tra cấu hình iframe/CSP thực tế của Open WebUI cho phép
trang map và script của nó; dùng link mở toàn màn hình để đối chiếu.

HTML Leaflet, ảnh base64 và dữ liệu marker chỉ đi từ server tới trình duyệt.
Tool trả tóm tắt nhỏ; lịch sử hội thoại chỉ thêm iframe wrapper nhỏ và URL.
Trước mỗi lần gọi LLM, agent lọc bản sao assistant messages: thay HTML artifact
bằng tóm tắt giới hạn độ dài, giữ URL/ID ảnh và bỏ ảnh base64 trong phần text.
Message gốc vẫn giữ nguyên trong lịch sử để Open WebUI mở lại artifact đầy đủ.
Nội dung người dùng, kết quả tool có cấu trúc, tool call và ID message được giữ nguyên.
Lớp lọc này áp dụng cho cả báo cáo HTML có ảnh và map iframe; không cần cài Filter
trong Open WebUI. Các kiểm thử HTTPX kiểm tra cả câu hỏi tiếp theo và vòng gọi tool;
chưa đo input tokens thực tế trên Open WebUI remote.

### Báo cáo và ảnh chart

Để quay clip với ảnh vệ tinh và số liệu cố định từ ShipClassification, xem
[kịch bản demo 4 phút](DEMO_AGENT_4_PHUT.md). Chạy `langgraph.demo.json` để chọn
bộ demo riêng; `langgraph.json` tiếp tục dùng nguồn dữ liệu thật như trước.

Tool `daily_carrier_report(observed_from, observed_to)` lấy số liệu báo cáo từ file server.
Tham số tùy chọn `output_format="png"` xuất ảnh chart riêng trực tiếp trong chat;
`output_format="html"` là mặc định để tạo báo cáo Artifacts. Cả hai dùng cùng tool
và hàm vẽ PNG hiện có. PNG hỗ trợ nguồn `file_server` và `demo`; mock hỗ trợ HTML.
Trong demo, server cổng 8002 phục vụ `/charts/daily-carriers.png`; trình duyệt cần
truy cập được URL này giống ảnh tàu. URL được kiểm tra theo báo cáo và snapshot.

Với định dạng HTML, agent dựng HTML trực tiếp từ kết quả tool, rồi ghép vào câu trả lời cuối trong một
code block `html` hoàn chỉnh, sau phần nhận xét của model. Không yêu cầu model
chép lại HTML hay tự tạo biểu đồ. Chỉ đính kèm báo cáo thành công của lượt hỏi hiện tại.

HTML chứa số tổng, biểu đồ cột ngang theo ngày, bảng số liệu và tùy chọn ẩn ngày 0.
HTML/CSS nằm trong cùng một trang; không dùng JavaScript, CDN, ảnh PNG hoặc gọi mạng
từ trình duyệt. Hoạt động cả khi iframe không cho chạy script hoặc truy cập same origin.
Mock mode cũng có HTML với nhãn **DỮ LIỆU GIẢ LẬP**.

Thiết lập một lần trên Open WebUI:

1. Vào **Settings → Interface**, bật **Artifacts** hoặc tùy chọn tự phát hiện Artifacts
   nếu phiên bản đang dùng có mục này.
2. Gửi câu hỏi yêu cầu báo cáo/biểu đồ và mở panel **Artifacts** hoặc nút preview
   của code block HTML nếu panel chưa tự mở. Tên nút có thể khác theo phiên bản.
3. Phần kết nối LangGraph hiện tại phải chuyển nguyên văn câu trả lời cuối, bao gồm
   dấu mở ` ```html ` và dấu đóng code block; không escape hoặc loại bỏ HTML.

Không cần tạo Tool/Pipe mới, sửa source hoặc build lại Open WebUI. Nếu chỉ thấy code,
kiểm tra tùy chọn Artifacts và câu trả lời cuối từ LangGraph trước. Nếu mất cả code block,
kiểm tra lớp kết nối chat có giữ nguyên nội dung không. Repo không chứa Pipe đang chạy
trên Open WebUI remote, nên phần hiển thị remote cần kiểm tra sau khi cập nhật agent.

Luồng `stream_mode="messages"` phát câu trả lời báo cáo hoàn chỉnh sau khi model viết xong
nhận xét, để HTML không bị bỏ sót hoặc lặp trong stream. Những lượt không tạo báo cáo
vẫn dùng luồng model bình thường. Client chỉ nghe sự kiện token `on_chat_model_stream`
cần đọc cả message đầu ra của node `agent`; SDK `runs.wait` nhận câu trả lời đầy đủ.

Xem [tài liệu Artifacts của Open WebUI](https://docs.openwebui.com/features/chat-conversations/chat-features/code-execution/artifacts/).

- Chỉ đếm prediction `predicted_aircraft_carrier=true` (classification `aircraft_carrier`),
  không áp lại ngưỡng score và không tính toàn bộ observations là tàu sân bay.
- Ngày lấy từ `observed_at` đã parse bằng `TIME_PATTERN` trong caption, giữ UTC;
  không dùng ngày gửi Telegram, tên ảnh hoặc thời gian trong Sentinel ID.
- Đếm từng `observation_id` riêng; hai ảnh của cùng tàu/detection vẫn là hai lượt.
  Bản ghi lặp cùng observation không tăng số đếm. Đây không phải số tàu duy nhất
  hoặc nhãn tàu sân bay đã được xác nhận.
- Khoảng ngày gồm cả hai đầu mốc, tối đa 366 ngày; các ngày không có lượt trả 0.
- Report và HTML cùng dùng số liệu từ snapshot của file server. Chỉ bao gồm observations
  có metadata, prediction và ảnh đã được nạp. `coverage` trả số observations và
  các bản ghi bị bỏ qua. Không suy diễn số đếm là mức độ hoạt động tàu thực tế.
- HTML tạo trong bộ nhớ, không ghi vào dataset và không cần URL để mở tab mới.
  Endpoint PNG vẫn được giữ để tương thích client cũ. URL PNG gắn với hash số liệu;
  nếu restart server với số liệu khác, URL cũ trả 409 thay vì hiện chart sai.
  Hỏi lại báo cáo để nhận URL mới. Agent dùng endpoint báo cáo mới khi gọi tool,
  không dùng snapshot cũ của `count_ships` để tạo chart.
- Mock mode trả số liệu giả và `chart_url=null`, không tạo URL ảnh giả; HTML vẫn hiển thị.

Trên remote, cập nhật code và restart LangGraph. Không có dependency mới cho Artifacts.
Nếu môi trường chưa cài đủ dependencies:

```bash
python -m pip install -r requirements.txt
```

Chỉ để xem báo cáo HTML, trình duyệt không cần truy cập port `8001`;
LangGraph vẫn phải truy cập được file server qua `FILE_SERVER_URL`.
Ảnh tàu và PNG dự phòng vẫn cần `DATA_API_BASE_URL` mà trình duyệt truy cập được,
ví dụ forward port `8001` nếu URL ảnh là `http://127.0.0.1:8001`.

Ví dụ câu hỏi:

```text
Vẽ biểu đồ số lượt phát hiện nghi là tàu sân bay theo ngày từ 2026-10-01 đến 2026-10-14.
```

Thử không cần LLM bằng cách mở:

```text
http://127.0.0.1:8001/reports/daily-carriers?observed_from=2026-10-01&observed_to=2026-10-14
```

Endpoint này trả JSON số liệu và `chart_url` PNG dự phòng; HTML được dựng ở agent.
Trong chat, kết quả mong đợi là nhận xét ngắn kèm code block bắt đầu bằng
`<!DOCTYPE html>` và kết thúc bằng `</html>`, được Open WebUI mở trong Artifacts.

Kiểm tra offline với metadata/predictions và ảnh giả trong thư mục tạm:

```bash
python -m pytest tests -q
```

Các test báo cáo kiểm tra ngày caption, nhãn boolean đã lưu, lượt đếm, ngày 0,
PNG dự phòng, HTML đủ ngày và đúng số liệu, mock, escape HTML, vòng gọi LangGraph
và message streaming bằng LLM giả, cùng việc không tái sử dụng báo cáo của lượt cũ.
Không cần GPU, dữ liệu production hoặc API key thật. Việc hiển thị trong Open WebUI
đang chạy trên remote cần được kiểm tra sau khi cập nhật và restart dịch vụ.
