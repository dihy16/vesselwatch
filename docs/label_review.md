# Câu 19 — Kiểm tra nhãn và đề xuất bổ sung nhãn

Tool `investigate_carrier_labels` gọi `POST /carrier-label-review-candidates`,
sau đó đọc ảnh và chia nhóm bằng chứng. Mục tiêu là tìm các lượt có thể bị
gán nhầm nhãn tàu sân bay để con người xác minh.

## Chọn ứng viên

Khoảng ngày bắt buộc, từ 1 đến 366 ngày gồm cả hai mốc; khu vực tùy chọn.
Dùng `use_chat_area=true` cho polygon
đã xác nhận trong chat; hoặc truyền `area_name`/`area_id` theo hai luồng vùng
hiện có. Không chọn vùng thì truy vấn toàn nguồn. Đếm theo observation_id,
không phải số tàu duy nhất.

Backend lọc toàn nguồn theo ngày, vùng và **nhãn aircraft_carrier đã lưu**,
loại observation_id trùng, rồi xếp score tăng dần trước khi phân trang.
Thiếu score xếp cuối; cùng score xếp theo thời gian rồi ID. Không áp dụng
ngưỡng score hoặc kích thước; kể cả nhãn dương có score thấp hơn 0,5 vẫn giữ.
Score là điểm mô hình, chưa được coi là xác suất đã hiệu chuẩn. Ưu tiên score
thấp giúp sắp thứ tự kiểm tra, không khẳng định đó là lỗi.

`limit` mặc định 20, tối đa 100; `offset` mặc định 0. Trang đầu không có nghĩa
là đã kiểm tra hết. `candidate_statistics` gồm tổng, vị trí, ngày, kích thước
và score của **toàn phạm vi**; `group_counts` chỉ tính **trang đã xử lý**.

## Đọc ảnh và chia nhóm

Mọi ảnh được chọn đều qua bước đọc ảnh, kể cả tàu <300 m và score cao.
Câu 19 không dùng nhánh bỏ qua đọc ảnh của câu 17. Bước thị giác nhận ảnh
đích, description.md và **toàn bộ ảnh mẫu**, không nhận prediction/score/số
đo cũ. Chỉ đối chiếu hình dáng tổng thể và màu thân; không dùng bóng/vệt nước
hay suy đoán chi tiết không nhìn thấy. Nhãn cũ được đối chiếu sau bước này.

| Nhóm | Ý nghĩa |
| --- | --- |
| `suspected_false_positive` | Ảnh đủ rõ, có đặc điểm nhìn thấy và khác biệt dẫn tới mẫu cụ thể, nghi không phải tàu sân bay. |
| `reference_consistent` | Ảnh đủ rõ có đặc điểm và dẫn chứng tương đồng với mẫu. |
| `inconclusive` | Chưa đủ bằng chứng để kết luận theo mẫu. |
| `insufficient_image` | Chất lượng ảnh hạn chế hoặc không đủ rõ. |
| `review_failed` | Lỗi tải/đọc ảnh, thiếu bộ mẫu/model hoặc kết quả không hợp lệ. |

`review_factors` ghi bằng chứng hình dáng/màu thân hoặc hạn chế ảnh. Đây
không phải lời giải thích cơ chế nội bộ của classifier. `group_observation_ids`
và kết quả từng ảnh cho phép LLM lấy ví dụ thực tế của từng nhóm; các ảnh của
một trang không được coi là mẫu đại diện thống kê của toàn bộ nguồn.

Chỉ nhóm `suspected_false_positive` xuất hiện trong `annotation_candidates`:
đề xuất xác minh/bổ sung nhãn **thủ công**, kèm ID, URL ảnh và bằng chứng trong
`flags`. Ảnh mờ/unknown không flag. Không sửa prediction hoặc nhãn review;
`label_applied=false`, không kết luận lỗi đã được xác nhận hay ground truth.

`reviewed_count`, `failed_count`, `coverage_complete`, `next_offset` báo phạm
vi thực tế. Thiếu bộ mẫu/model vẫn giữ thống kê toàn phạm vi và báo lỗi cho
các ảnh được chọn; không biến lỗi thành kết quả âm. Tiếp tục trang sau bằng
cùng ngày/vùng, đối chiếu `source_snapshot_id` và `reference_revision` trước
khi tổng hợp; dữ liệu hoặc bộ mẫu đổi thì kiểm tra lại.

LLM chat nhận trực tiếp pixel của các ảnh đã review thành công và toàn bộ
ảnh mẫu qua cơ chế ảnh hiện có. Không lưu base64 trong lịch sử graph. Không
tạo map mới hay thay Pipe/Open WebUI.

## Thử trên MID

Sau `git pull`, restart **file server 8001** và **LangGraph 2024**. Không thêm
dependency; dùng bộ mẫu và cấu hình model vision/chat hiện có. Cả model chat
và vision phải hỗ trợ nhận ảnh như các luồng đối chiếu trước.

Trong chat đang có vùng đã xác nhận, hỏi:

> Điều tra nhãn tàu sân bay trong vùng vừa vẽ từ 01/01/2025 đến 31/12/2025.
> Kiểm tra 5 ảnh đầu theo score tăng dần, thống kê từng nhóm và đề xuất các
> trường hợp cần xác minh nhãn, kèm ảnh và bằng chứng đối chiếu mẫu.

Tool cần có `use_chat_area=true`, `limit=5`, `offset=0`; đối chiếu
`selected_count = tổng group_counts` và `reviewed_count + failed_count`.
Nếu còn `next_offset`, tiếp tục trang sau; không báo là đã kiểm tra toàn bộ.
