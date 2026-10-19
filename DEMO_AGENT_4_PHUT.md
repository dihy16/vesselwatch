# Kịch bản quay demo tác nhân phân tích tàu sân bay — khoảng 4 phút

Quay trực tiếp trên Open WebUI, không cần thoại. Gửi lần lượt 7 prompt bên dưới trong **cùng một cuộc hội thoại**. Bản demo dùng ảnh vệ tinh và kết quả mô hình đã lưu từ ShipClassification; các chức năng đều dùng chung một bộ dữ liệu cố định, không chạy nhận diện mới.

Nội dung chính: tra cứu theo phân loại, xem ảnh và thông tin tàu, lọc theo kích thước, thống kê theo ngày, xuất ảnh chart PNG riêng, tạo báo cáo HTML và mở bản đồ Leaflet nhúng.

## Công cụ được thể hiện trong clip

| Prompt | Tool agent gọi | Kết quả trên màn hình |
| --- | --- | --- |
| 1–3 | `search_ships` | Danh sách tàu, ảnh quan sát và kết quả lọc kích thước |
| 4 | `count_ships` | Bảng thống kê lượt quan sát và lượt dự đoán tàu sân bay theo ngày |
| 5 | `daily_carrier_report`, `output_format="png"` | Ảnh chart PNG trực tiếp trong chat |
| 6 | `daily_carrier_report`, `output_format="html"` | Báo cáo HTML Artifacts có biểu đồ, bảng số liệu và ảnh tàu |
| 7 | `create_vessel_map` | Bản đồ Leaflet nhúng iframe trong HTML Artifacts, kèm link toàn màn hình |

Prompt 5 và 6 dùng chung tool `daily_carrier_report` với khoảng ngày `observed_from=2025-12-24`, `observed_to=2025-12-30`. Prompt 5 xuất PNG bằng hàm vẽ chart hiện có và server demo cổng 8002 phục vụ ảnh. Prompt 6 dựng HTML Artifacts từ cùng số liệu. Khi quay, mở phần gọi công cụ để thấy tên tool, khoảng ngày và định dạng đầu ra.

Ảnh tàu ở prompt 2 là ảnh quan sát có sẵn; ảnh chart ở prompt 5 được vẽ từ số liệu theo ngày. Tool trả `chart_url` khi chọn `output_format="png"`; URL gắn với mã kiểm tra báo cáo và snapshot để không hiển thị nhầm số liệu sau khi đổi dữ liệu. Với HTML trong demo, `chart_url=null` vì báo cáo tự chứa biểu đồ.

Map dùng giao diện Leaflet đã đóng gói trong repo, phục vụ qua server **8002**.
Không cần upload ShipClassification, mở port mới hoặc thêm/sửa Pipe/Function.
Agent chỉ nhận URL và tóm tắt, tự đính kèm HTML iframe nhỏ như cơ chế Artifacts hiện có.
Ở câu hỏi tiếp theo, agent thay HTML artifact trong bản sao context gửi LLM bằng
tóm tắt ngắn có URL/ID liên quan, bỏ ảnh base64. Lịch sử gốc giữ HTML đầy đủ để
mở lại; không cần thêm Filter trong Open WebUI.

## Bật chế độ demo

Chạy từ thư mục `vesselwatch`, trong môi trường Python 3.11+ đã kích hoạt. Giữ cấu hình LLM đang dùng trong `.env`; agent vẫn dùng LLM để hiểu câu hỏi và chọn công cụ.

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
```

Bộ demo đã chuẩn bị tại `data/demo/`. Nếu cần tạo lại từ repo bên cạnh:

```powershell
python scripts/prepare_demo_data.py --source-repo "D:\10 Personal\10.11 Projects\VDT\ShipClassification"
```

Bộ demo `data/demo/snapshot.json` và 11 ảnh `data/demo/images/DEMO_*.png` được đưa vào Git để máy remote chỉ cần pull là có đủ dữ liệu. Các dữ liệu khác trong `data/` vẫn được bỏ qua. Mã `DEMO_*` chỉ dùng nội bộ cho ID/tên file ảnh; ID tàu hiển thị lấy từ `source_id` gốc.

### Chạy trên máy remote (Linux / SSH)

Dừng server demo cũ ở cổng **8002** và LangGraph cũ ở cổng **2024** trước khi
khởi động lại. Chạy trong thư mục repo, giữ cấu hình LLM hiện có trong `.env`:

```bash
git pull --ff-only origin main
source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m uvicorn ship_agent.demo:create_app --factory --host 127.0.0.1 --port 8002
```

Giữ terminal này chạy. Trong terminal SSH thứ hai, vào cùng thư mục repo:

```bash
source .venv/bin/activate
export VESSELWATCH_DEMO_PUBLIC_URL=http://127.0.0.1:8002
langgraph dev --config langgraph.demo.json --no-browser --host 0.0.0.0
```

Mở `http://127.0.0.1:8002/health` trên máy đang dùng trình duyệt để kiểm tra
forward port; kết quả cần có `is_demo=true` và `observation_count=11`.
Sau đó mở hội thoại mới và chạy thử prompt 7 trước khi quay. Backend, tool,
chart và lọc context đã được kiểm thử; iframe trong Open WebUI remote cần được
đối chiếu trên cấu hình thực tế đang dùng.

Forward cổng **8002** từ remote về máy đang mở trình duyệt (VS Code Ports hoặc SSH `-L 8002:127.0.0.1:8002`). URL trên là địa chỉ trình duyệt dùng để tải ảnh. Nếu dùng một URL public thay cho port forwarding, đặt biến `VESSELWATCH_DEMO_PUBLIC_URL` thành URL đó. Giữ kết nối Open WebUI tới agent như trước; dừng LangGraph cũ nếu cổng 2024 đang được dùng. Chế độ demo không cần file server dữ liệu thật ở cổng 8001.

**Terminal 1 — phục vụ ảnh demo:**

```powershell
python -m uvicorn ship_agent.demo:create_app --factory --host 127.0.0.1 --port 8002
```

**Terminal 2 — chạy agent với bộ dữ liệu cố định:**

```powershell
langgraph dev --config langgraph.demo.json --no-browser
```

Nếu LangGraph khác đang dùng cổng 2024, dừng nó trước khi chạy lệnh demo. Mở Open WebUI với kết nối agent hiện có; graph vẫn tên `agent`.

Nếu trình duyệt ở máy khác, forward thêm cổng **8002**, hoặc đặt `VESSELWATCH_DEMO_PUBLIC_URL` thành địa chỉ máy chủ ảnh mà trình duyệt truy cập được trước khi khởi động agent. Ảnh chat dùng máy chủ này; ảnh trong báo cáo HTML được nhúng sẵn.

## Dữ liệu và kết quả đã kiểm tra

Bộ demo có **11 quan sát**: 3 mẫu có nhãn tàu sân bay và mô hình dự đoán đúng, cùng 8 mẫu âm có kết quả đã lưu. Mọi thời gian, vị trí, kích thước và điểm dự đoán giữ nguyên từ nguồn. ID tàu hiển thị là `source_id` gốc trong dữ liệu ShipClassification, không dùng bí danh demo. ID này định danh bản ghi nguồn, không xác nhận tên tàu ngoài thực tế; mã kiểm tra ảnh được lưu trong snapshot.

| ID tàu gốc | Ngày quan sát | Dài × rộng, làm tròn |
| --- | --- | --- |
| fb21fe76-1b74-4ee3-af60-be68f2e1b20b | 30/12/2025 | 350,6 × 81,0 m |
| S2C_MSIL2A_20250625T030601_N0511_R075_T49QCU_20250625T064400_0 | 25/06/2025 | 315,9 × 73,3 m |
| 3087952c-ba2b-4e74-b405-311025f5959d | 14/06/2025 | 342,6 × 76,0 m |

Tuần **24–30/12/2025** có **9 lượt quan sát**, trong đó **1 lượt dự đoán là tàu sân bay**. Hai mẫu tháng 6 nằm ngoài tuần này. Đây là tập mẫu đã chọn, không phải toàn bộ dữ liệu hoặc số tàu duy nhất. Ba mẫu dương được chọn thủ công ở ba vị trí khác nhau; không tự thêm crop khác của cùng lượt chụp vào bộ demo. Prompt 7 dùng khoảng **01/06–30/12/2025** để hiện cả ba vị trí.

## Chuẩn bị trước khi quay

- Mở sẵn agent trong một cuộc hội thoại mới; chuẩn bị các prompt để dán lần lượt.
- Chạy thử để chắc dữ liệu có kết quả nghi là tàu sân bay, ảnh tàu và ảnh chart PNG tải được, báo cáo mở được trong Artifacts.
- Prompt 3 dùng ngưỡng dài 330 m, rộng 75 m và đã kiểm tra trả đúng 2 kết quả.
- Dùng đúng khoảng ngày trong prompt để các lần quay đều có cùng số liệu.
- Ảnh chat được phóng lớn để dễ xem, không thay đổi crop gốc. Đây vẫn là ảnh vệ tinh độ phân giải thấp.
- Thử prompt 7, mở URL map độc lập rồi kiểm tra iframe trong Artifacts. Giữ `data/demo/maps/` khi deploy để link trong lịch sử chat còn hoạt động.
- Agent tạo map qua `VESSELWATCH_DEMO_API_URL` (mặc định `http://127.0.0.1:8002`); iframe dùng `VESSELWATCH_DEMO_PUBLIC_URL` qua port forwarding. Nếu agent chạy trong container, đặt API URL theo địa chỉ container truy cập được.

## Nhịp quay dự kiến

| Thời gian | Thao tác | Khả năng thể hiện |
| --- | --- | --- |
| 00:00–00:10 | Mở cuộc hội thoại với agent | Giao diện tương tác |
| 00:10–00:35 | Prompt 1: tìm các quan sát nghi là tàu sân bay | Tra cứu và trình bày bảng |
| 00:35–01:00 | Prompt 2: xem ảnh theo ID trong bảng | Hiểu ngữ cảnh, hiển thị ảnh và vị trí |
| 01:00–01:25 | Prompt 3: lọc theo kích thước | Kết hợp nhiều điều kiện tìm kiếm |
| 01:25–01:50 | Prompt 4: thống kê 7 ngày | Xử lý khoảng thời gian, tổng hợp số liệu |
| 01:50–02:20 | Prompt 5: xuất ảnh chart PNG | Gọi tool và hiển thị biểu đồ trực tiếp trong chat |
| 02:20–03:10 | Prompt 6: tạo báo cáo và mở Artifacts | Báo cáo HTML, biểu đồ, bảng và ảnh |
| 03:10–04:00 | Prompt 7: mở map, chọn quan sát | Bản đồ iframe, ảnh và thông tin tàu |

Các mốc trên gồm cả thời gian chờ trả lời, có thể xê dịch theo tốc độ agent. Dành phần cuối cho báo cáo HTML và bản đồ.

## Prompt 1 — Tra cứu kết quả nhận diện

```text
Từ ngày 01/06/2025 đến hết ngày 30/12/2025, có những lượt phát hiện nào nghi là tàu sân bay? Trình bày bảng gồm ID tàu, ngày quan sát, chiều dài, chiều rộng và điểm dự đoán. Làm tròn kích thước đến 1 chữ số thập phân, chưa cần hiển thị ảnh.
```

**Mong đợi:** fb21fe76-1b74-4ee3-af60-be68f2e1b20b, S2C_MSIL2A_20250625T030601_N0511_R075_T49QCU_20250625T064400_0, 3087952c-ba2b-4e74-b405-311025f5959d. Dừng vài giây ở bảng kết quả để người xem đọc được thông tin.

**Tool cần thấy:** `search_ships` với `observed_from="2025-06-01"`, `observed_to="2025-12-30"`, `classification="aircraft_carrier"`; tổng 3 kết quả.

## Prompt 2 — Hỏi tiếp và xem ảnh

```text
Cho tôi xem ảnh của lượt phát hiện ngày 30/12/2025 trong bảng vừa rồi, kèm ID tàu, vị trí, thời gian quan sát và kích thước. Hiển thị ảnh trực tiếp trong câu trả lời.
```

**Khi quay:** giữ ảnh trên màn hình khoảng 5–8 giây; cuộn vừa đủ để thấy ảnh và thông tin đi kèm.

**Mong đợi:** ảnh và thông tin của `fb21fe76-1b74-4ee3-af60-be68f2e1b20b`, là kết quả ngày 30/12 trong bảng trước. Agent dùng ID đã tìm được từ ngữ cảnh.

Muốn đổi ảnh khi quay lại, có thể dùng: **“Cho tôi xem ảnh của lượt phát hiện ngày 25/06/2025 trong bảng vừa rồi, kèm ID tàu và kích thước.”** Không cần gửi thêm câu này trong cùng clip nếu thiếu thời gian.

## Prompt 3 — Lọc theo nhiều điều kiện

```text
Trong khoảng 01/06/2025–30/12/2025, lọc các lượt phát hiện nghi là tàu sân bay có chiều dài từ 330 m và chiều rộng từ 75 m trở lên. Trả bảng ID tàu, ngày quan sát, kích thước và tổng số kết quả phù hợp, chưa cần hiển thị ảnh.
```

**Mong đợi:** 2 kết quả, fb21fe76-1b74-4ee3-af60-be68f2e1b20b và 3087952c-ba2b-4e74-b405-311025f5959d; S2C_MSIL2A_20250625T030601_N0511_R075_T49QCU_20250625T064400_0 bị loại bởi điều kiện kích thước.

**Tool cần thấy:** `search_ships` với cùng khoảng ngày ở prompt 1, `classification="aircraft_carrier"`, `min_length_m=330`, `min_width_m=75`.

## Prompt 4 — Thống kê theo ngày

```text
Từ ngày 24/12/2025 đến hết ngày 30/12/2025, thống kê theo từng ngày có bao nhiêu lượt quan sát tàu khả nghi và bao nhiêu lượt nghi là tàu sân bay. Hiển thị cả ngày không có lượt quan sát và trình bày bằng bảng ngắn gọn.
```

**Khi quay:** dừng ở phần khoảng ngày và bảng thống kê. Giữ đúng cách gọi “lượt quan sát/lượt phát hiện”, không gọi đây là số tàu duy nhất.

| Ngày | Lượt quan sát | Lượt dự đoán tàu sân bay |
| --- | ---: | ---: |
| 24/12/2025 | 0 | 0 |
| 25/12/2025 | 2 | 0 |
| 26/12/2025 | 0 | 0 |
| 27/12/2025 | 2 | 0 |
| 28/12/2025 | 0 | 0 |
| 29/12/2025 | 2 | 0 |
| 30/12/2025 | 3 | 1 |

## Prompt 5 — Xuất ảnh chart PNG riêng

```text
Vẽ biểu đồ cột về số lượt phát hiện nghi là tàu sân bay theo từng ngày từ 24/12/2025 đến hết 30/12/2025. Hiển thị biểu đồ dưới dạng ảnh trực tiếp trong chat, gồm cả ngày có 0 lượt, kèm một câu nhận xét ngắn.
```

**Tool cần thấy:** `daily_carrier_report` với `observed_from="2025-12-24"`, `observed_to="2025-12-30"`, `output_format="png"`.

**Mong đợi:** ảnh PNG có 7 ngày, ngày 30/12 có 1 lượt và 6 ngày còn lại có 0 lượt; tổng 1 lượt. Số liệu khớp cột lượt dự đoán tàu sân bay ở prompt 4. Ảnh chart hiển thị ngay trong chat qua `chart_url` của tool.

**Khi quay:** cho thấy phần gọi tool, sau đó giữ ảnh chart trên màn hình khoảng 5–8 giây để đọc ngày và số lượt.

## Prompt 6 — Báo cáo HTML và biểu đồ

```text
Lập báo cáo tổng hợp các lượt phát hiện nghi là tàu sân bay từ ngày 24/12/2025 đến hết ngày 30/12/2025. Báo cáo gồm biểu đồ theo ngày, bảng số liệu và ảnh các lượt phát hiện, kèm nhận xét tối đa 2 câu.
```

**Mong đợi:** tổng 1 lượt dự đoán, biểu đồ 7 ngày, bảng số liệu và ảnh fb21fe76-1b74-4ee3-af60-be68f2e1b20b. Hai mẫu tháng 6 không xuất hiện vì nằm ngoài khoảng ngày.

**Tool cần thấy:** `daily_carrier_report` với `observed_from="2025-12-24"`, `observed_to="2025-12-30"`, `output_format="html"` (hoặc bỏ qua định dạng để dùng mặc định HTML). Biểu đồ trong HTML có cùng số liệu với ảnh PNG ở prompt 5.

**Khi quay:** mở bản xem trước Artifacts nếu chưa tự mở. Cho thấy số tổng, biểu đồ, bảng và ảnh; bật/tắt “Ẩn ngày không có lượt phát hiện”, rồi dừng vài giây ở báo cáo để kết thúc clip.

## Prompt 7 — Bản đồ Leaflet nhúng iframe

```text
Đánh dấu các lượt phát hiện nghi là tàu sân bay từ ngày 01/06/2025 đến hết ngày 30/12/2025 trên bản đồ tương tác. Tôi muốn chọn từng vị trí để xem ảnh, ID tàu, thời gian quan sát và kích thước. Kèm liên kết mở bản đồ toàn màn hình.
```

**Tool cần thấy:** `create_vessel_map` với `observed_from="2025-06-01"`, `observed_to="2025-12-30"`, `classification="aircraft_carrier"`.

**Mong đợi:** 3 quan sát ở 3 vị trí khác nhau, ID `fb21fe76-1b74-4ee3-af60-be68f2e1b20b`, `S2C_MSIL2A_20250625T030601_N0511_R075_T49QCU_20250625T064400_0` và `3087952c-ba2b-4e74-b405-311025f5959d`. Chọn từng marker hoặc từng dòng trong danh sách để xem ảnh. Khoảng ngày map rộng hơn chart/báo cáo tuần để gồm cả hai mẫu tháng 6. Map tự mở kết quả, ảnh và dự đoán đã lưu; không gọi classifier.

**Khi quay:** mở Artifacts, chọn một dòng để hiện ảnh và thông tin; phóng/thu bản đồ. Link toàn màn hình nằm cả trong Artifact và câu trả lời chat.

Map được lưu trong `data/demo/maps/`, giữ được sau restart. Nền OpenStreetMap cần internet. Nếu URL mở độc lập được nhưng iframe trắng, kiểm tra iframe/CSP trên Open WebUI thực tế; không cần thêm Filter nếu viewer lớn không lọt vào context.

## Giới hạn nội dung demo

Clip tập trung vào những chức năng agent hiện đã hỗ trợ. Không thêm yêu cầu huấn luyện mô hình, nhận diện ảnh mới tải lên, theo dõi hành trình tàu hoặc dự báo hoạt động tàu. Phần xem ảnh minh họa việc truy xuất ảnh quan sát, không phải agent tự phân tích nội dung ảnh.

## Kiểm tra nhanh và quay lại chế độ bình thường

- Mở `http://127.0.0.1:8002/images/DEMO_001` để kiểm tra ảnh chat. Thêm `?original=true` để xem crop gốc.
- Mở `http://127.0.0.1:8002/report-preview` để xem trước đúng báo cáo HTML có ảnh, không cần gọi LLM.
- Gửi prompt 5 để kiểm tra ảnh chart PNG; URL nằm trong kết quả tool và cần đi qua cổng 8002 đã forward giống ảnh tàu.
- Nếu đổi địa chỉ phục vụ ảnh, khởi động lại demo agent và dùng cuộc hội thoại mới.
- Kết thúc demo: dừng các tiến trình demo; chạy lại file server bình thường và `langgraph dev --no-browser` với cấu hình mặc định.
