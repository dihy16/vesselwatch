# Thử agent với ảnh táo qua Open WebUI

File server tạm trỏ vào `data/test/apple.jpg`, với metadata và prediction fixture
trong `tests/fixtures/apple_review/`. Không đổi tool `review_ship_images`, prompt
đọc ảnh hoặc Pipe. File ảnh có sẵn trên từng máy, không đưa vào Git.

Tọa độ [0, 0], kích thước 1 × 1 m, thời gian 2026-10-20 và prediction nhãn âm/score 0
là dữ liệu giả chỉ để loader đăng ký ảnh, không phải kết quả mô hình hoặc quan sát
thật. Lời gọi thị giác hiện chỉ nhận pixel ảnh, không nhận các trường này.

Từ thư mục gốc trên remote, restart file server và LangGraph để bỏ snapshot cũ:

```bash
python -m uvicorn file_server.app:create_app --factory --host 127.0.0.1 --port 8001
```

Trong terminal khác:

```bash
langgraph dev --no-browser
```

Chọn agent dùng graph mặc định (`langgraph.json`), không chọn graph demo. Giữ cấu
hình model có khả năng đọc ảnh trong `.env`; nếu dùng model vision riêng thì điền
`OPENAI_VISION_MODEL`, `OPENAI_VISION_BASE_URL`, `OPENAI_VISION_API_KEY`.

Mở một cuộc chat mới trong Open WebUI và hỏi:

> Phân tích nội dung ảnh của TEST_APPLE bằng tool đọc ảnh. Hãy mô tả những gì thực sự nhìn thấy, không chỉ nhắc lại nhãn hoặc kích thước đã lưu.

Luồng cần quan sát trong LangGraph/tool calls:

1. `search_ships(ship_id="TEST_APPLE")` trả một observation với ảnh táo.
2. `review_ship_images(observation_id=...)` tải ảnh từ `/images/{image_id}`.
3. Agent trả lời dựa trên `visual_review`, không chỉ `saved_prediction`.

Đây là kiểm thử thực tế: chưa biết model sẽ phản hồi thế nào. Nếu nó mô tả boong
hoặc thân tàu trên ảnh táo thì test đã phát hiện suy diễn sai. Nếu tool lỗi thì chưa
thể đánh giá khả năng nhìn ảnh; xem lỗi cấu hình/endpoint trước.

Sau test, khôi phục ba đường dẫn production đã comment trong
`file_server/config.py`, rồi restart cả hai server.
