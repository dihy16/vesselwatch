# Kịch bản quay demo tác nhân phân tích tàu sân bay — khoảng 4 phút

Quay trực tiếp trên Open WebUI, không cần thoại. Gửi lần lượt 5 prompt bên dưới trong **cùng một cuộc hội thoại**. Bản demo dùng ảnh vệ tinh và kết quả mô hình đã lưu từ ShipClassification; các chức năng đều dùng chung một bộ dữ liệu cố định, không chạy nhận diện mới.

Nội dung chính: tra cứu theo phân loại, xem ảnh và thông tin tàu, lọc theo kích thước, thống kê theo ngày, tạo báo cáo HTML và biểu đồ.

## Bật chế độ demo

Chạy từ thư mục `vesselwatch`, trong môi trường Python 3.11+ đã kích hoạt. Giữ cấu hình LLM đang dùng trong `.env`; agent vẫn dùng LLM để hiểu câu hỏi và chọn công cụ.

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
```

Bộ demo đã chuẩn bị tại `data/demo/`. Nếu cần tạo lại từ repo bên cạnh:

```powershell
python scripts/prepare_demo_data.py --source-repo "D:\10 Personal\10.11 Projects\VDT\ShipClassification"
```

Bộ demo `data/demo/snapshot.json` và 11 ảnh `data/demo/images/DEMO_*.png` được đưa vào Git để máy remote chỉ cần pull là có đủ dữ liệu. Các dữ liệu khác trong `data/` vẫn được bỏ qua.

### Chạy trên máy remote (Linux / SSH)

Chạy trong thư mục repo, giữ cấu hình LLM hiện có trong `.env`:

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

Bộ demo có **11 quan sát**: 3 mẫu có nhãn tàu sân bay và mô hình dự đoán đúng, cùng 8 mẫu âm có kết quả đã lưu. Mọi thời gian, vị trí, kích thước và điểm dự đoán giữ nguyên từ nguồn. ID demo là bí danh quan sát, không phải tên tàu thực tế; ID nguồn và mã kiểm tra ảnh được lưu trong snapshot.

| ID demo | Ngày quan sát | Dài × rộng, làm tròn |
| --- | --- | --- |
| DEMO_001 | 30/12/2025 | 350,6 × 81,0 m |
| DEMO_002 | 25/06/2025 | 315,9 × 73,3 m |
| DEMO_003 | 30/12/2025 | 350,6 × 81,0 m |

Tuần **24–30/12/2025** có **10 lượt quan sát**, trong đó **2 lượt dự đoán là tàu sân bay**. DEMO_002 nằm ngoài tuần này. Đây là tập mẫu đã chọn, không phải toàn bộ dữ liệu hoặc số tàu duy nhất.

## Chuẩn bị trước khi quay

- Mở sẵn agent trong một cuộc hội thoại mới; chuẩn bị các prompt để dán lần lượt.
- Chạy thử để chắc dữ liệu có kết quả nghi là tàu sân bay, ảnh tải được và báo cáo mở được trong Artifacts.
- Prompt 3 dùng ngưỡng dài 330 m, rộng 75 m và đã kiểm tra trả đúng 2 kết quả.
- Dùng đúng khoảng ngày trong prompt để các lần quay đều có cùng số liệu.
- Ảnh chat được phóng lớn để dễ xem, không thay đổi crop gốc. Đây vẫn là ảnh vệ tinh độ phân giải thấp.

## Nhịp quay dự kiến

| Thời gian | Thao tác | Khả năng thể hiện |
| --- | --- | --- |
| 00:00–00:10 | Mở cuộc hội thoại với agent | Giao diện tương tác |
| 00:10–00:50 | Prompt 1: tìm các quan sát nghi là tàu sân bay | Tra cứu và trình bày bảng |
| 00:50–01:25 | Prompt 2: xem ảnh của kết quả đầu tiên | Hiểu ngữ cảnh, hiển thị ảnh và vị trí |
| 01:25–02:05 | Prompt 3: lọc theo kích thước | Kết hợp nhiều điều kiện tìm kiếm |
| 02:05–02:45 | Prompt 4: thống kê 7 ngày | Xử lý khoảng thời gian, tổng hợp số liệu |
| 02:45–03:45 | Prompt 5: tạo báo cáo và mở Artifacts | Báo cáo HTML, biểu đồ và nhận xét |
| 03:45–04:00 | Xem báo cáo, bật/tắt tùy chọn ẩn ngày không có lượt phát hiện | Tương tác với báo cáo |

Các mốc trên gồm cả thời gian chờ trả lời, có thể xê dịch theo tốc độ agent. Dành khoảng một phút cuối cho báo cáo HTML.

## Prompt 1 — Tra cứu kết quả nhận diện

```text
Liệt kê 3 quan sát được dự đoán là tàu sân bay trong bộ dữ liệu demo. Trình bày bảng gồm ID, ngày quan sát, chiều dài, chiều rộng và điểm dự đoán. Làm tròn kích thước đến 1 chữ số thập phân. Chưa cần hiển thị ảnh, trả lời ngắn gọn.
```

**Mong đợi:** DEMO_001, DEMO_002, DEMO_003. Dừng vài giây ở bảng kết quả để người xem đọc được thông tin.

## Prompt 2 — Hỏi tiếp và xem ảnh

```text
Cho tôi xem ảnh của tàu DEMO_001 trong bảng vừa rồi, kèm vị trí, thời gian quan sát và kích thước. Hiển thị ảnh trực tiếp trong câu trả lời, không chỉ đưa liên kết.
```

**Khi quay:** giữ ảnh trên màn hình khoảng 5–8 giây; cuộn vừa đủ để thấy ảnh và thông tin đi kèm.

Muốn đổi ảnh khi quay lại, có thể dùng: **“Cho tôi xem ảnh tàu DEMO_002, kèm ngày quan sát và kích thước.”** Không cần gửi thêm câu này trong cùng clip nếu thiếu thời gian.

## Prompt 3 — Lọc theo nhiều điều kiện

```text
Tìm các quan sát được dự đoán là tàu sân bay có chiều dài từ 330 m và chiều rộng từ 75 m trở lên trong bộ dữ liệu demo. Trả bảng ID, ngày quan sát và kích thước. Cho biết tổng số kết quả phù hợp, chưa cần hiển thị ảnh.
```

**Mong đợi:** 2 kết quả, DEMO_001 và DEMO_003; DEMO_002 bị loại bởi điều kiện kích thước.

## Prompt 4 — Thống kê theo ngày

```text
Từ ngày 24/12/2025 đến hết ngày 30/12/2025, thống kê số lượt quan sát tàu khả nghi và số lượt được dự đoán là tàu sân bay theo từng ngày. Hiển thị cả ngày không có lượt quan sát và trả lời bằng bảng ngắn gọn.
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
| 30/12/2025 | 4 | 2 |

## Prompt 5 — Báo cáo HTML và biểu đồ

```text
Lập báo cáo HTML cho đúng khoảng ngày 24/12/2025–30/12/2025 về số lượt phát hiện nghi là tàu sân bay. Hiển thị biểu đồ, bảng số liệu và ảnh tàu sân bay trong báo cáo Artifacts. Kèm nhận xét tối đa 2 câu.
```

**Mong đợi:** tổng 2 lượt dự đoán, biểu đồ 7 ngày, bảng số liệu và ảnh DEMO_001, DEMO_003. DEMO_002 không xuất hiện vì nằm ngoài khoảng ngày.

**Khi quay:** mở bản xem trước Artifacts nếu chưa tự mở. Cho thấy số tổng, biểu đồ, bảng và ảnh; bật/tắt “Ẩn ngày không có lượt phát hiện”, rồi dừng vài giây ở báo cáo để kết thúc clip.

## Giới hạn nội dung demo

Clip tập trung vào những chức năng agent hiện đã hỗ trợ. Không thêm yêu cầu huấn luyện mô hình, nhận diện ảnh mới tải lên, theo dõi hành trình tàu hoặc dự báo hoạt động tàu. Phần xem ảnh minh họa việc truy xuất ảnh quan sát, không phải agent tự phân tích nội dung ảnh.

## Kiểm tra nhanh và quay lại chế độ bình thường

- Mở `http://127.0.0.1:8002/images/DEMO_001` để kiểm tra ảnh chat. Thêm `?original=true` để xem crop gốc.
- Mở `http://127.0.0.1:8002/report-preview` để xem trước đúng báo cáo HTML có ảnh, không cần gọi LLM.
- Nếu đổi địa chỉ phục vụ ảnh, khởi động lại demo agent và dùng cuộc hội thoại mới.
- Kết thúc demo: dừng các tiến trình demo; chạy lại file server bình thường và `langgraph dev --no-browser` với cấu hình mặc định.
