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

## Thử trực tiếp agent trong Open WebUI: ảnh gốc và ảnh resize

Đây là luồng để so **hai câu trả lời tự do của chính agent đang chat**, không phải
chạy vision reviewer riêng. Sau `git pull`, restart LangGraph port 2024 để nạp tool
`view_ship_image`; giữ file server đang chạy. Không cần sửa Pipe hay source Open WebUI.
Model nhận pixel là `OPENAI_MODEL` của agent, không phải model `OPENAI_VISION_MODEL`
của reviewer (hai cấu hình có thể trỏ cùng model hoặc khác nhau).

Mở **hai chat mới**, chọn cùng agent và dùng cùng observation_id/bộ mẫu. Không gửi
hai prompt liên tiếp trong cùng chat nếu muốn tránh ảnh hưởng của câu trả lời đầu.

Trong chat thứ nhất:

> Dùng view_ship_image với observation_id
> validation-c6fadfc1ac916210cebbbfba093d3ea916358a69727073d0db42125e78139784,
> image_size="original", use_carrier_references=true. Hãy tự xem pixel và đối chiếu
> với toàn bộ bộ mẫu. Chỉ mô tả hình dáng tổng thể và màu thân, nêu điểm giống, khác
> và điều chưa rõ. Bỏ bóng/vệt nước, không suy đoán chi tiết nhỏ. Trả lời tự do,
> không gọi review_ship_images hay vision reviewer riêng.

Trong chat thứ hai, gửi **cùng prompt trên, chỉ đổi** `image_size="resized"`.

Kiểm tra tool call là `view_ship_image` với đúng `image_size`. Tool result phải có
`review_source="chat_model_direct_pixels"`; ảnh này có kích thước gửi lần lượt
48×26 và 224×121, `image_resampling` lần lượt là `none` và `bilinear`. Cả hai giữ
cùng `reference_revision` và `reference_count`; ảnh mẫu vẫn theo quy tắc 224 px.
Tool chỉ mở ảnh, không tạo flag hoặc sửa nhãn. Nếu tải ảnh/mẫu lỗi thì chưa có
phản hồi từ pixel hợp lệ để so sánh.

Ảnh hiển thị trong chat vẫn có thể được phóng lên 384 px cho người xem; đó là bản
preview riêng. Xác định kích thước gửi agent từ tool metadata, không từ kích cỡ ảnh
trên màn hình. Hệ thống giữ pixel ở kích thước đã chọn khi gửi request; provider
vẫn có thể xử lý ảnh thêm ở bên trong. Một cặp câu trả lời chưa chứng minh độ chính xác.

## Thử vision model riêng bằng CLI: ảnh gốc và ảnh resize

Trong virtualenv trên MID, chạy file server 8001 và dùng ID thật. Ví dụ với crop
48×26 px đã kiểm tra trước đó:

```bash
python -m ship_agent.image_review --data-source file_server \
  --observation-id validation-c6fadfc1ac916210cebbbfba093d3ea916358a69727073d0db42125e78139784 \
  --compare-resize --use-carrier-references --free-text
```

Lệnh gọi model **hai lần độc lập**: ảnh mục tiêu gốc 48×26 px và bản bilinear
224×121 px. Cả hai dùng cùng model/cấu hình `OPENAI_VISION_*` (hoặc `OPENAI_*`),
cùng prompt, `detail=high`, cùng mô tả và toàn bộ bộ mẫu. Ảnh mẫu giữ nguyên cách
chuẩn bị 224 px của ứng dụng ở cả hai lượt; chỉ ảnh mục tiêu thay đổi. Model không
đọc câu trả lời của lượt kia. Không truyền nhãn, score hay kích thước mét vào model.

`--free-text` lấy **hai câu trả lời tự do**, không yêu cầu JSON/schema. Prompt chỉ
yêu cầu hình dáng tổng thể và màu thân, đối chiếu toàn bộ mẫu, nêu điểm giống/khác
và điều chưa rõ. Không dùng bóng/vệt nước hoặc yêu cầu chi tiết boong/thượng tầng.
Kích thước pixel TARGET được ghi trong báo cáo, không đưa vào prompt ở chế độ này,
để model nhận xét hình ảnh thay vì dựa vào con số kích thước. Hai lượt có cùng prompt.

Lệnh này gọi trực tiếp vision model đã cấu hình trong `.env`, bỏ qua agent và
Open WebUI. Đây là thí nghiệm riêng với luồng chat ở trên. Chỉ cần file server
đang chạy; không cần restart LangGraph để chạy thí nghiệm CLI.

Bỏ `--free-text` để chạy lại chế độ JSON/schema như bài test ban đầu. Hai chế độ
dùng prompt khác nhau; chỉ so ảnh gốc với ảnh resize trong cùng một chế độ.

Thư mục mới trong `data/resize_comparisons/` có `comparison.html` để xem cạnh nhau,
`comparison.json` chứa nguyên văn hai phản hồi, kích thước/hash đầu vào, model,
revision mẫu, thời gian xử lý và token nếu provider trả; kèm `original.png` và
`resized.png`. Không thay file gốc, nhãn hay flag. Phản hồi được giữ trước quy tắc
hậu xử lý; ở chế độ tự do, phản hồi có văn bản được ghi `complete`, không parse JSON.
Ở chế độ JSON, phản hồi sai schema vẫn được lưu để đọc; lỗi API được báo riêng.

Bỏ `--use-carrier-references` để thử đọc riêng ảnh mục tiêu, không đối chiếu mẫu.
Thêm `--prepare-only` để chỉ tạo cặp ảnh/báo cáo mà không gọi model; vẫn cần API
dữ liệu để lấy ảnh và API bộ mẫu nếu có tùy chọn mẫu. `--output-dir` chỉ định một
thư mục mới nếu muốn chọn nơi lưu. Ảnh có cạnh dài từ 224 px trở lên không tạo hai
điều kiện khác nhau theo quy tắc hiện tại nên lệnh yêu cầu chọn crop nhỏ hơn.

So sánh câu trả lời giúp phát hiện khác biệt hành vi, chưa chứng minh resize chính
xác hơn. Model có thể không trả giống nhau qua các lần gọi và provider có thể xử lý
kích thước nội bộ; muốn đánh giá chất lượng cần nhiều ảnh, nhiều lượt và nhãn review.
