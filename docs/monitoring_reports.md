# Câu 20 — Báo cáo giám sát theo tháng

`vessel_monitoring_report` gọi `POST /vessel-monitoring-reports` để lấy thống
kê và trang ứng viên kiểm tra từ **cùng snapshot nguồn**, sau đó dùng lại
luồng đọc ảnh câu 17. LLM nhận số liệu/bằng chứng và viết nhận xét; HTML được
render từ kết quả tool, không yêu cầu LLM tự tính số hoặc viết HTML.

## Phạm vi thống kê

Khoảng ngày bắt buộc, vùng tùy chọn; dùng `use_chat_area=true` cho polygon
đã xác nhận của chat, hoặc tên/mã vùng theo hai luồng hiện có. Bỏ vùng thì
toàn nguồn. “30 ngày qua” gồm ngày tham chiếu và 29 ngày trước đó. Đếm riêng
observation_id; không nhận dạng cùng một tàu qua nhiều ảnh.

Thống kê lọc toàn nguồn trước khi phân trang, gồm **cả ba nhãn**:
`aircraft_carrier`, `not_aircraft_carrier`, `unknown`. Có tổng/theo ngày (kể
cả ngày 0), số nhãn, dài/rộng/score và dữ liệu thiếu, ma trận chiều dài
<300 m/≥300 m/thiếu với từng nhãn. Score không thay thế nhãn đã lưu.

`unlocated_in_date_range_count` tính số thiếu tọa độ trước lọc vùng; không
gán chúng vào vùng được chọn. `missing_position_count` là số thiếu tọa độ
còn trong phạm vi báo cáo (0 khi dùng polygon).

## So sánh theo tháng dương lịch

Mỗi tháng giao với khoảng ngày báo cáo được nhóm riêng, có ngày đầu/cuối,
`queried_days`, `calendar_days`, `partial_month`, tổng, số theo nhãn và
`average_daily_count = tổng lượt / số ngày truy vấn`.

Kỳ đối chiếu là **toàn bộ tháng dương lịch liền trước**, cùng geometry và
snapshot. Ví dụ báo cáo 15/01–28/02: phần tháng 1 là 15/01–31/01 đối chiếu
01/12–31/12, phần tháng 2 đối chiếu 01/01–31/01. Kỳ đối chiếu có thể nằm
ngoài khoảng ngày báo cáo và không thêm các ảnh đó vào trang review.

Tool trả chênh lệch tổng và chênh lệch trung bình lượt/ngày, phần trăm/direction
cho tổng và từng nhãn. Khi tháng đối chiếu có 0 lượt, phần trăm là `null`,
direction `no_baseline`; không tạo phần trăm vô hạn. Tháng không có dữ liệu
trong nguồn vẫn có hàng 0; không coi là bằng chứng vệ tinh đã quan sát đầy đủ.
Số ngày truy vấn là số ngày trong khoảng chọn, không phải độ phủ ảnh.

Nhận xét xu hướng dựa trên các số đã tính và nêu rõ kỳ/tháng thiếu ngày. Chưa
có ngưỡng kiểm định bất thường thống kê. Biến động lượt quan sát không đủ để
kết luận biến động số tàu hoặc mức hoạt động thực tế.

## Kiểm tra chi tiết và bằng chứng

Chỉ các lượt nhãn `aircraft_carrier` trong khoảng ngày báo cáo được chọn để
kiểm tra theo quy tắc câu 17, xếp toàn bộ nhóm <300 m trước rồi mới phân trang:

1. <300 m vào ưu tiên 1 từ metadata; LLM không đọc ảnh của chúng.
2. Phần còn lại (đúng 300 m/thiếu chiều dài cũng vào nhánh này) đọc mô tả và
   toàn bộ bộ mẫu. Chỉ ảnh đủ rõ có bằng chứng nghi không phải tàu sân bay
   vào ưu tiên 2. Mờ/unknown không flag; lỗi báo riêng.

`limit` (mặc định 20, tối đa 100) và `offset` chỉ áp dụng bước review, **không
cắt thống kê**. `review.processed_count`, `reviewed_count`, flags và lỗi thuộc
trang đang trả; `coverage_complete`/`next_offset` cho biết phần chưa xử lý.
Thiếu bộ mẫu hoặc model/ảnh lỗi vẫn giữ thống kê và kết quả ưu tiên 1.
Không sửa prediction hoặc nhãn human review. Câu 20 không cần gọi DBSCAN.

LLM chat nhận trực tiếp pixel của các ảnh thực sự được review và toàn bộ
mẫu, theo cơ chế đã có. Ảnh ưu tiên 1 không gửi vào đầu vào ảnh của model.
Không ghi base64 vào tool JSON hoặc checkpoint.

## HTML và chạy thử trên MID

`output_format="html"` mặc định: gắn báo cáo vào Artifacts với bảng/biểu đồ
tháng, phân loại/kích thước, các trường hợp có ảnh/ID/bằng chứng, phạm vi
kiểm tra và bảng ngày. Model viết nhận xét trong chat. `output_format="json"`
trả dữ liệu/bằng chứng để trình bày trong chat, không gắn HTML. Báo cáo không
reload map của chat; các câu hỏi tiếp theo vẫn dùng polygon đã xác nhận.

Sau `git pull`, restart **file server 8001** và **LangGraph 2024**. Không thêm
dependency mới; dùng lại cấu hình bộ mẫu và model vision/chat hiện có.

Ví dụ:

> Lập báo cáo giám sát trong vùng vừa vẽ từ 01/01/2025 đến 31/12/2025.
> So sánh theo tháng và kiểm tra 5 ứng viên đầu, kèm bằng chứng và báo cáo HTML.

> Lập báo cáo giám sát trong vùng này trong 30 ngày qua, so theo tháng.

Ngày/vùng phải giữ nguyên khi tiếp tục một trang review; đối chiếu report_id
và source_snapshot_id, không trộn kết quả từ snapshot khác. `daily_carrier_report`
vẫn là báo cáo nhãn dương theo ngày trước đây; không thay thế báo cáo giám sát
ba nhãn có vùng của câu 20.
