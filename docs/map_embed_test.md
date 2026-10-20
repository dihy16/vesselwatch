# Thử map nhúng trong Open WebUI qua phần cài đặt giao diện

Để dùng vùng đã xác nhận với **agent LangGraph hiện tại**, xem
[Liên kết vùng với cuộc chat](chat_area_sessions.md). Các bước bên dưới chỉ là
bài thử hiển thị bằng Pipe riêng.

Mẫu thử: [`scripts/openwebui_map_embed_test.py`](../scripts/openwebui_map_embed_test.py),
phiên bản 0.3.0. Cập nhật Function hiện có bằng nội dung file này. Mẫu có hai vị trí:
`inline` trong tin nhắn hoặc `artifact` trong panel Artifacts bên cạnh chat. Cả hai
đều dùng setting **Iframe Sandbox Allow Same Origin** của Open WebUI. Người dùng
chỉ cần quyền sửa Function và phần Settings trong giao diện.

Pipe trả lời cố định, không cần API key và chưa kết nối LangGraph. Bài thử này kiểm
tra việc map hoạt động và giữ trạng thái qua các lượt chat; chưa triển khai liên
kết vùng được chọn với agent.

## 1. Chạy map demo trên MID

Từ thư mục repo `aircraft_carrier_agents` trên MID:

```bash
python3 data/exports/vessel-map-demo/demo/run_vessel_demo.py --port 8000
```

Giữ terminal chạy server mở. Nếu trình duyệt ở máy cá nhân, mở thêm terminal trên
máy cá nhân để tạo SSH tunnel, thay `MID` bằng hostname/IP dùng để SSH:

```bash
ssh -N -L 18000:127.0.0.1:8000 mid@MID
```

Mở `http://127.0.0.1:18000/demo/vessel_map.html` từ trình duyệt. Nếu trình duyệt chạy
ngay trên MID thì dùng `http://127.0.0.1:8000/demo/vessel_map.html`. Dùng URL đã mở
thành công làm **MAP_URL**, theo góc nhìn của trình duyệt đang dùng Open WebUI.

## 2. Cập nhật Function qua giao diện

1. Vào **Admin Panel → Functions**, mở **VesselWatch Map Embed Test** hiện có.
2. Thay toàn bộ code bằng file Python phiên bản 0.3.0, **Save** và bật Function.
   Nếu chưa tạo Function, dùng **Create/New** và dán nội dung file.
3. Mở bánh răng **Valves**, kiểm tra **MAP_URL** đúng URL ở bước 1. Đặt
   **DISPLAY_MODE** là `artifact` để dùng panel bên cạnh hoặc `inline` để dùng trong
   tin nhắn. **MAP_HEIGHT_PX** đặt chiều cao inline (320–1600 pixel, mặc định 720);
   artifact dùng toàn bộ chiều cao phần preview.
4. Trong **Settings → Interface**, bật **Iframe Sandbox Allow Scripts** và
   **Iframe Sandbox Allow Same Origin**, rồi lưu nếu có nút Save. Với chế độ
   `artifact`, bật thêm **Detect Artifacts Automatically**.
5. Tạo chat thử mới, chọn model **VesselWatch Map Embed Test**, gửi đúng `map`.

Với `artifact`, Pipe trả về HTML wrapper trong code block `html`, để Open WebUI
nhận diện và hiển thị trong tab Artifacts. Nếu chưa tự mở, bấm Preview/nút mở
Artifacts của khối HTML. Với `inline`, map hiện trực tiếp trong tin nhắn. Cả hai
không cần bấm citation [1]. Tin nhắn cũ không tự đổi vị trí sau khi cập nhật Function.

Ở chế độ `inline`, code phát sự kiện `embeds` với `replace: True`, thay cho `source.embed_url`.
Theo [ResponseMessage.svelte v0.12.0](https://github.com/open-webui/open-webui/blob/v0.12.0/src/lib/components/chat/Messages/ResponseMessage.svelte),
embed trong tin nhắn nhận setting `iframeSandboxAllowSameOrigin`. Panel bên cạnh
trong [Embeds.svelte](https://github.com/open-webui/open-webui/blob/v0.12.0/src/lib/components/chat/ChatControls/Embeds.svelte)
chưa truyền setting đó. Tab Artifacts là một panel khác: theo
[tài liệu Artifacts](https://docs.openwebui.com/features/chat-conversations/chat-features/code-execution/artifacts/#what-a-preview-is-allowed-to-do),
sandbox của nó cũng đọc các setting Interface. Bài thử hiện tại không yêu cầu áp
dụng bản vá source Open WebUI.

## 3. URL map và chiều cao

Chế độ inline gửi một HTML wrapper nhỏ để đặt chiều cao và báo kích thước qua
`postMessage` loại `iframe:height`. Chế độ artifact trả HTML wrapper để hiện trong
preview bên cạnh chat và không báo chiều cao. Wrapper chứa iframe `src=MAP_URL`; Leaflet và
dữ liệu vẫn được tải từ server map. HTML/JavaScript của bản đồ không bị sao chép
vào tin nhắn. Có hai lớp iframe: wrapper của Open WebUI và iframe URL bên trong.

Lớp ngoài cần hai setting đã bật; iframe URL bên trong khai báo `allow-scripts`,
`allow-same-origin` và `allow-downloads`. Quyền của lớp trong không vượt qua được
hạn chế của lớp ngoài nếu setting ở Open WebUI bị tắt.

Referrer policy của wrapper và iframe URL là `strict-origin-when-cross-origin`.
Template map đã có cùng referrer policy. Sự kiện và cơ chế báo chiều cao được mô tả
trong [Events](https://docs.openwebui.com/features/extensibility/plugin/development/events/#embeds-or-chatmessageembeds)
và [FullHeightIframe](https://github.com/open-webui/open-webui/blob/v0.12.0/src/lib/components/common/FullHeightIframe.svelte).

## 4. Kiểm tra ảnh nền và trạng thái

1. Mở DevTools → Network, bật **Preserve log**. Gửi `map` trong chat thử mới, không
   chạy đoạn Console thêm quyền thủ công của lần thử trước.
2. Kiểm tra ảnh nền hiện và **Show results** tải được tàu. Nếu cần chẩn đoán 403,
   chọn request ảnh từ `tile.openstreetmap.org`, xem status/response và **Request
   Headers → Referer**. Chưa thể kết luận chính xác lý do OSM từ chối nếu chưa có
   request headers. [Chính sách OSM](https://operations.osmfoundation.org/policies/tiles/)
   yêu cầu Referer hợp lệ cho request từ trang web.
3. Zoom/kéo map, chọn **Candidates**, đổi ngưỡng và chọn một tàu.
4. Gửi `lượt 2`, `lượt 3`, `lượt 4`. Không gửi lại `map` trong bước này: mỗi lệnh
   `map` tạo embed hoặc artifact trên một tin nhắn mới. `replace: True` chỉ áp dụng cho tin nhắn
   đang được trả lời, không đảm bảo một iframe dùng chung cho toàn bộ cuộc chat.
5. Quan sát map trong Artifacts hoặc cuộn lại map inline đầu tiên. Kiểm tra zoom/bộ lọc/tàu đã chọn và request document
   `vessel_map.html`. Không có request mới cùng trạng thái giữ nguyên là bằng chứng
   map không tải lại trong các lượt đã thử. Nếu gửi thêm HTML artifact khác, chuyển
   version hoặc đóng/mở lại panel, Artifacts có thể thay nội dung và tải lại iframe;
   đây là các bài thử riêng. Không mặc định coi Artifacts là một panel map cố định.
6. F5 chat thành một bài thử riêng. Khôi phục embed từ lịch sử không đồng nghĩa
   khôi phục JavaScript state sau reload.

Để kiểm tra context còn sống, chọn đúng iframe URL map trong Console, chạy
`window.__vesselwatchEmbedProbe = crypto.randomUUID()` và ghi giá trị. Sau mỗi lượt
chat, đọc lại biến: giữ nguyên chứng tỏ context còn sống, `undefined` nghĩa là nó
đã bị thay. Đây là phép đo, không phải thay đổi quyền iframe.

Bản demo gốc 5.230 observations chưa có phần vẽ polygon mới của VesselWatch. Bài
thử này dùng zoom/bộ lọc/tàu đang chọn. Trạng thái vùng gắn với chat cần triển khai
ở bước tích hợp agent sau này.

## Nếu vẫn lỗi

- **Map vẫn mở qua [1]:** đang xem tin nhắn cũ hoặc Function chưa được cập nhật.
  Kiểm tra version 0.3.0 và DISPLAY_MODE, tạo chat thử mới và gửi `map`.
- **Chỉ thấy HTML code:** ở chế độ artifact, kiểm tra Detect Artifacts Automatically
  và nút Preview/mở Artifacts của khối HTML. Điều này chưa chứng tỏ map bị 403.
- **Không kết nối được:** mở chính MAP_URL trong tab thường của cùng trình duyệt;
  kiểm tra demo và SSH tunnel còn chạy.
- **Iframe chỉ hiện một dải thấp:** kiểm tra hai setting Scripts/Same Origin,
  MAP_HEIGHT_PX và lỗi CSP/JavaScript trong Console.
- **Ảnh nền vẫn 403:** kiểm tra request tile thực tế và sandbox của cả hai iframe.
  Ghi lại Referer/status/response để xác định nguyên nhân; không giả mạo header.
- **Show results lỗi:** kiểm tra request `/api/getAll` và Console để phân biệt
  CORS, CSP hay API. Nếu iframe bị `frame-src` chặn, cần quản trị viên điều chỉnh
  chính sách của Open WebUI; Function không ghi đè được chính sách của lớp ngoài.

Người dùng đã báo phép thử thêm quyền qua Console làm map chạy lại trong panel cũ.
Người dùng đã xác nhận Pipe inline 0.2.0 hoạt động. Chế độ Artifacts 0.3.0 cần được
dán vào Open WebUI và thử trên trình duyệt MID; chưa có xác nhận ảnh nền và giữ
trạng thái qua các lượt chat cho cách hiển thị Artifacts.
