# Kích thước ảnh cho model và chat

Ảnh crop trong dataset giữ nguyên byte, kích thước và đường dẫn. Có hai bản
phục vụ khi cần, được tạo trong bộ nhớ bằng nội suy bilinear, giữ tỷ lệ:

| Mục đích | Kích thước cạnh dài | Ví dụ ảnh gốc 48×26 px |
| --- | --- | --- |
| Đầu vào model vision và model chat | Phóng ảnh nhỏ đến 224 px; ảnh từ 224 px trở lên giữ nguyên | 224×121 px |
| Hiển thị trong chat | 384 px, có thể phóng hoặc thu nhỏ | 384×208 px |
| Bấm mở ảnh gốc | Kích thước gốc | 48×26 px |

Cả ảnh mục tiêu và toàn bộ ảnh mẫu đều dùng cùng quy tắc đầu vào model.
Model được thông báo kích thước gốc và kích thước đã gửi. Nội suy chỉ làm pixel
lớn hơn; không tạo thêm chi tiết, không đủ để kết luận ảnh mờ đã rõ hơn.
Các ngưỡng chọn ứng viên, số đo tàu, score, nhãn và quy tắc flag không đổi.

## API và metadata

- `/images/{image_id}` vẫn trả ảnh gốc. Thêm `?preview=1` để lấy PNG cạnh dài
  384 px; header `X-Original-Width` và `X-Original-Height` ghi kích thước gốc.
- `/carrier-references/images/{reference_id}?revision=...` giữ nguyên ảnh mẫu
  của revision đó. Thêm `&preview=1` để lấy preview; ID/hash/revision vẫn tính
  trên ảnh mẫu gốc, không tính trên bản resize.
- Manifest bộ mẫu và kết quả tool có URL ảnh mẫu thật cùng `preview_url`, giúp
  agent dẫn đúng ảnh thay vì tự dựng URL từ observation khác.
- Kết quả review giữ `image_width_px`, `image_height_px` cho kích thước gốc;
  thêm `vision_image_width_px`, `vision_image_height_px` và `image_resampling`
  (`bilinear` hoặc `none`) cho ảnh thực tế gửi model.

Sau khi model trả lời, agent đổi Markdown của ảnh đã đăng ký sang preview có
liên kết mở ảnh gốc. Biểu đồ và URL ngoài dataset không bị xử lý như ảnh tàu.
Đây là bước hiển thị; URL trong dữ liệu/tool và pixel gửi model không bị thay
bằng preview 384 px. Pixel base64 vẫn chỉ có trong lượt gọi model, không lưu
vào lịch sử graph.

## Áp dụng trên MID

Chạy `git pull` trong repository rồi restart file server port 8001 và LangGraph
port 2024 bằng các lệnh hiện có. Không cần sửa Pipe, chuyển dataset hay thêm
dependency. Map demo port 8000 tiếp tục dùng giao diện hiển thị riêng.

Trong chat, chạy lại T13 với observation thật, yêu cầu kèm ảnh mục tiêu và ảnh
mẫu. Kiểm tra ảnh hiện lớn hơn, bấm mở được bản gốc, URL preview có `preview=1`,
và kích thước native/sent trong tool result đúng. Đây chưa phải bằng chứng
resize cải thiện độ chính xác; cần đối chiếu kết quả vision thực tế trên MID.
