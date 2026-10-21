# Câu 17 — Điều tra và ưu tiên kiểm tra thủ công

Tool `investigate_carrier_detections` nhận khoảng ngày bắt buộc và một vùng
đang chọn (`use_chat_area=true`), vùng gọi tên hoặc `area_id`. Bỏ vùng thì
truy vấn toàn nguồn, đúng phạm vi trả về. “30 ngày qua” tính cả ngày tham chiếu
và 29 ngày trước đó; có thể chỉ định khoảng ngày khác để kiểm tra dữ liệu cũ.

Chỉ xét các observations có nhãn `aircraft_carrier`, giữ nguyên score/nhãn gốc.
Không thêm điều kiện score, chiều rộng hay bộ lọc nhãn âm của câu 14.

1. **Ưu tiên 1:** chiều dài hợp lệ, dương và **<300 m**. Đưa vào danh sách ngay
   theo số đo metadata; không tải/đọc ảnh, không cần bộ mẫu/model vision.
2. **Ưu tiên 2:** phần còn lại, kể cả đúng 300 m và thiếu chiều dài, được đối
   chiếu hình dáng tổng thể/màu thân với mô tả và **toàn bộ** ảnh mẫu hiện có.
   Chỉ ảnh đủ rõ có bằng chứng nghi không phải tàu sân bay mới vào danh sách,
   dùng cùng kiểm tra citation/revision/bằng chứng của câu 16.

Ảnh mờ, unknown hoặc nhận xét thiếu bằng chứng không flag. Bóng/vệt nước
không dùng làm tiêu chí. Đây là danh sách cần review, không phải lỗi mô hình
đã được xác nhận. Không sửa prediction hoặc human review đã lưu.

## Phạm vi và phân trang

`POST /carrier-investigation-candidates` lọc toàn bộ snapshot theo ngày/vùng,
khử trùng observation_id, rồi sắp toàn bộ nhóm <300 m trước nhóm đọc ảnh.
Trong mỗi nhóm giữ thứ tự thời gian/ID ổn định. Sau đó mới áp dụng `limit`
(mặc định 20, tối đa 100) và `offset`. Không xếp ưu tiên từ một trang tìm kiếm
bất kỳ. Thiếu vị trí chỉ bị loại khi truy vấn có polygon/vùng không gian.

Kết quả `flags` có `priority=1` trước `priority=2`. Nhóm 1 có
`flag_reason="length_below_300m"`, `visual_review=null` và
`reference_comparison_performed=false`. Nhóm 2 có bằng chứng ảnh, dẫn mẫu và
`flag_reason="suspected_non_carrier"`. URL ảnh của nhóm 1 vẫn có thể hiển thị
cho người dùng, nhưng không gửi pixel của chúng vào LLM trong luồng này.
Pixel của các ảnh được review thành công cùng toàn bộ bộ mẫu vẫn gửi vào LLM
chat theo cơ chế hiện có; không lưu base64 vào lịch sử.

`dimension_candidate_count` và `visual_candidate_count` đếm **toàn phạm vi**.
`priority_1_count`, `priority_2_count`, `flagged_count`, `dimension_screened_count`,
`reviewed_count` (chỉ ảnh đã đọc), `processed_count` và lỗi đếm **trang hiện tại**.
`coverage_complete` chỉ đúng khi đã xử lý toàn phạm vi từ offset 0, không lỗi.
Nếu có `next_offset`, tiếp tục cùng ngày/vùng và snapshot nguồn; không xem một
trang là toàn bộ kết quả. Đây là lượt quan sát, chưa phải tàu duy nhất.

Thiếu bộ mẫu/model hoặc lỗi đọc ảnh được báo riêng; nhóm 1 vẫn giữ nguyên.
Trang chỉ gồm nhóm 1 hoặc không có ứng viên không khởi tạo vision/bộ mẫu.

## Chạy trên MID

Sau khi pull code, restart file server **8001**, rồi restart LangGraph **2024**.
Giữ nguyên map, Pipe và bộ mẫu `data/carrier_references/`.

Ví dụ sau khi vẽ vùng và bấm xác nhận:

> Điều tra các lượt nghi tàu sân bay trong vùng vừa vẽ, từ 01/01/2025 đến
> 31/12/2025. Xếp ưu tiên kiểm tra thủ công theo câu 17, xử lý 5 lượt đầu.

Nếu có trang tiếp theo:

> Tiếp tục câu 17 trong cùng khoảng ngày và vùng, dùng next_offset vừa trả về.

Câu 16 vẫn đọc mọi ảnh nhãn dương, không áp dụng bước bỏ đọc ảnh theo kích thước
của câu 17. Các luồng cũ không đổi tiêu chí flag.
