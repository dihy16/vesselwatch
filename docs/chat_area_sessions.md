# Một vùng đã xác nhận cho mỗi cuộc chat

Tính năng dùng **Pipe LangGraph hiện tại**, file `scripts/aircraft_carrier_pipe.py`
phiên bản 0.2.0. Polygon được lưu trong JSON theo user/chat. Pipe thử map riêng
`openwebui_map_embed_test.py` chỉ dùng cho bài thử giao diện trước đó.

## Chạy trên MID

Từ `/home/mid/workspaces/aircraft_carrier_agents`, dừng server map cũ ở port 8000
rồi chạy wrapper mới:

```bash
python3 scripts/run_vessel_map_demo.py --port 8000
```

Runner mặc định đọc bundle `data/exports/vessel-map-demo`: runtime, manifest 5.230
observations, ảnh và saved predictions như trước. Nó bổ sung API lưu vùng cùng
origin và điều khiển vẽ; không sửa hoặc chép lại các file trong bundle. Nếu bundle
nằm nơi khác, thêm `--demo-dir /duong/dan/vessel-map-demo`.

File server dữ liệu chạy như trước. Restart LangGraph sau khi cập nhật code để
nhận tool và ngữ cảnh vùng mới. Với nguồn thật, các dịch vụ thông thường là:

```bash
python -m uvicorn file_server.app:create_app --factory --host 127.0.0.1 --port 8001
langgraph dev --no-browser
```

Hai lệnh chạy trong hai terminal riêng nếu các dịch vụ chưa chạy.

## Cập nhật Function qua giao diện Open WebUI

1. Vào **Admin Panel → Functions**, chọn Function đang kết nối LangGraph.
2. Thay code bằng toàn bộ `scripts/aircraft_carrier_pipe.py`, **Save** và bật nó.
   Giữ các Valves LangGraph đang dùng: `LANGGRAPH_SERVER_URL`, `MODEL_ID`, v.v.
3. Đặt hai Valves mới:

   | Valve | Vai trò | Ví dụ |
   |---|---|---|
   | `MAP_URL` | URL map nhìn từ trình duyệt | `http://127.0.0.1:18000/demo/vessel_map.html` |
   | `MAP_API_URL` | Server map nhìn từ backend Open WebUI | `http://127.0.0.1:8000` |

   Ví dụ API trên áp dụng khi Open WebUI chạy trực tiếp trên MID. Nếu ở container,
   dùng địa chỉ host mà container truy cập được theo network hiện có. Để MAP_URL
   trống sẽ tắt liên kết vùng và giữ luồng hỏi đáp LangGraph thông thường.
4. Giữ **Detect Artifacts Automatically**, **Iframe Sandbox Allow Scripts** và
   **Iframe Sandbox Allow Same Origin** bật trong **Settings → Interface**.

Nếu trình duyệt ở máy cá nhân, mở tunnel như trước:

```bash
ssh -N -L 18000:127.0.0.1:8000 mid@MID
```

Thay MID bằng hostname/IP SSH thực tế. Nếu trình duyệt chạy trên MID, MAP_URL có
thể dùng port 8000 trực tiếp.

## Luồng sử dụng

1. Chọn **model/Pipe LangGraph hiện tại**, trong cùng chat gửi `map` hoặc `mở bản đồ`.
   Pipe tạo/lấy phiên theo user/chat rồi trả Artifact có URL chứa `map_session`.
   Lệnh mở map không gọi thêm agent.
2. Trên map chọn Biển Đông/Vịnh Bắc Bộ hoặc tự vẽ rectangle/polygon.
3. Bấm **Xác nhận vùng** và đợi thông báo đã lưu. Vẽ dở/lưu thất bại không thay vùng
   cũ. Nút xác nhận chỉ lưu vùng, không gọi một agent run riêng.
4. Quay lại chat, hỏi ví dụ **“Có bao nhiêu lượt tàu nghi là tàu sân bay trong vùng
   vừa vẽ trong tháng 10/2026?”** Pipe đọc snapshot vùng mới nhất rồi gửi cùng câu
   hỏi vào chính thread LangGraph. Agent dùng `query_ships_in_area` với
   `use_chat_area=true`; tọa độ được tool lấy từ runtime, không yêu cầu LLM nhập lại.
5. Xác nhận vùng mới sẽ ghi đè vùng cũ. **Xóa vùng đã lưu** lưu null. Khi chưa có
   vùng hoặc server map lỗi, truy vấn vùng yêu cầu xác nhận/báo lỗi, không tự chuyển
   thành đếm toàn bộ dữ liệu hay dùng vùng của lượt trước.

Chỉ một vùng cho mỗi truy vấn. Biển Đông/Vịnh Bắc Bộ lưu bằng khóa ranh giới có sẵn;
mọi tên khác vẫn yêu cầu người dùng tự vẽ.

## Lưu trữ và API

Mỗi user/chat có một file `data/map_sessions/<hash-user-chat>.json`, được ignore:

```json
{
  "user_id": "user-1",
  "chat_id": "chat-1",
  "session_id": "<ma-phien-ngau-nhien>",
  "active_area": {
    "type": "Polygon",
    "coordinates": [[[110,15],[112,15],[112,17],[110,17],[110,15]]]
  },
  "revision": 1,
  "updated_at": "2026-10-20T10:00:00Z"
}
```

Preset dùng `{"type":"preset","key":"bien_dong"}` hoặc `vinh_bac_bo`, tránh
nhân bản polygon lớn. Các API đều nằm trên server map:

| Method | Path | Tác dụng |
|---|---|---|
| POST | `/map-sessions` | Tạo/lấy phiên theo user_id và chat_id |
| GET | `/map-sessions/{session_id}` | Đọc vùng và revision |
| PUT | `/map-sessions/{session_id}/area` | Lưu một vùng/null, kèm expected_revision |

Ghi qua file tạm rồi atomic replace; runner có lock cho các request trong một tiến
trình. Chỉ chạy **một tiến trình map server cho cùng thư mục session**. Hai cửa sổ
ghi cùng revision sẽ có một cửa sổ nhận 409. Dùng **Tải vùng đã lưu** trước khi sửa
tiếp ở cửa sổ đó.

Pipe đọc một snapshot cho mỗi câu hỏi. Mọi tool call trong run dùng cùng snapshot,
kể cả khi vùng được thay giữa lúc agent trả lời; câu hỏi kế tiếp nhận vùng mới.
`chat_id` tiếp tục là `thread_id` như Pipe cũ.

API này chạy trong mạng riêng/SSH tunnel hiện tại. URL có mã phiên cho phép đọc/ghi
vùng của phiên đó; không chia sẻ URL phiên. Không bổ sung cơ chế xác thực để đưa
server map này ra Internet công khai.

## Nguồn dữ liệu và hiển thị

File server port 8001 mặc định đọc **cùng bundle với map**, qua
`DATA_SOURCE = "map_bundle"` và `MAP_DEMO_DIR` trong `file_server/config.py`.
Đường dẫn mặc định là `data/exports/vessel-map-demo` tính từ repo. Cả hai đọc
`demo/local_config.json` để lấy manifest, saved run và seed; không dùng
`data/predictions.json` hay Telegram metadata trong chế độ này. Nếu dùng
`--demo-dir` khác cho map, đặt `MAP_DEMO_DIR` trùng thư mục đó.

Sau khi pull, restart **map 8000, file server 8001, rồi LangGraph 2024**.
Không cần thay code Function hoặc Valves cho lần đổi nguồn dữ liệu này.
Kiểm tra hai snapshot trên MID:

```bash
python3 - <<'PY'
import json
from urllib.request import urlopen
with urlopen("http://127.0.0.1:8000/dataset-info") as r:
    map_info = json.load(r)
with urlopen("http://127.0.0.1:8001/health") as r:
    api_info = json.load(r)
assert map_info["map_snapshot_id"] == api_info["map_snapshot_id"], "Different map/agent snapshots"
assert map_info["observation_count"] == api_info["observation_count"]
print("Same snapshot:", api_info["observation_count"], "observations")
print("Saved run:", api_info["runs"], "seed:", api_info["saved_run_seed"])
print("Predictions:", api_info["prediction_count"], "unknown:", api_info["unknown_count"])
print("Carrier threshold:", api_info["carrier_threshold"])
PY
```

Nhãn `aircraft_carrier` dùng score ≥ `MAP_CARRIER_THRESHOLD` (mặc định 0.5),
bằng ngưỡng 50% mặc định trên map. Ảnh thiếu prediction được giữ với nhãn
`unknown`, không dùng nhãn ground truth để thay kết quả mô hình. Ảnh thiếu vị trí
vẫn có trong danh sách toàn bộ nhưng không được tính trong polygon; thiếu kích
thước thì không khớp bộ lọc kích thước. Đơn vị là lượt phát hiện theo ID crop.

Ngày, ngưỡng slider và bộ lọc trên giao diện map **chưa tự truyền vào câu hỏi
agent**. Để đối chiếu kết quả, chọn cùng khoảng ngày và dùng ngưỡng 50% trên map.
Đổi nguồn file server về Telegram bằng `DATA_SOURCE = "telegram"` nếu cần.

Pipe chỉ trả Artifact khi yêu cầu mở map. Tool không đính kèm thêm map cho câu hỏi
tiếp nối. Đóng/mở panel, thêm artifact khác hoặc F5 vẫn phụ thuộc Open WebUI.
Polygon xác nhận được khôi phục từ JSON khi map tải lại; tính năng này không lưu
viewport/bộ lọc của trình duyệt.

Đã kiểm tra local JSON/API HTTP, Pipe với LangGraph giả lập và JavaScript vẽ vùng.
Kiểm tra trực tiếp Open WebUI + LangGraph trên MID vẫn cần thực hiện.
