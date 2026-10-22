# Câu 18 — Cụm nhiều lượt nghi tàu sân bay

## Tìm cụm và thống kê

`find_carrier_hotspots` gọi `POST /carrier-hotspots` để lọc toàn bộ snapshot
theo khoảng ngày bắt buộc, nhãn `aircraft_carrier` và vùng tùy chọn. Nếu không
chỉ định vùng thì tìm toàn nguồn. Vùng chat dùng `use_chat_area=true`, vùng
định nghĩa sẵn và vùng cần tự vẽ vẫn theo hai luồng đã có.

DBSCAN dùng đúng tham số đã chốt: **eps=30 km**, **min_samples=2**. Tọa độ được
đổi thành `[latitude, longitude]` theo radian; metric Haversine, eps được chia
cho bán kính Trái Đất 6371,0088 km. Hai lượt khác ID nhưng cùng vị trí vẫn là
hai điểm; cùng observation_id chỉ đếm một lần. Không dùng score/kích thước để
đổi nhãn hoặc thêm điều kiện lọc vào các cụm.

Theo [DBSCAN](https://scikit-learn.org/stable/modules/generated/sklearn.cluster.DBSCAN.html),
min_samples tính cả chính điểm đang xét; eps là khoảng cách lân cận, không
phải đường kính tối đa của một cụm. Chuỗi điểm nối tiếp có thể tạo cụm rộng
hơn 30 km. Thứ tự tọa độ và đơn vị theo
[Haversine](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.pairwise.haversine_distances.html).

Gom cụm trước khi phân trang. Cụm được xếp theo số lượt giảm dần, cùng số lượt
thì dùng ID ổn định để phân xử. Tên hiển thị là “Cụm 1”, “Cụm 2”, kèm phạm vi
tọa độ; không tự đặt tên địa danh. `limit`/`offset` ở tool tìm cụm là trang **cụm**.

Mỗi cụm và toàn phạm vi đều có:

- Tổng số lượt, số ngày có quan sát, ngày đầu/cuối và thống kê từng ngày, kể cả ngày 0 lượt.
- Phạm vi vĩ/kinh độ, có xử lý cụm qua kinh tuyến ±180°.
- Dài/rộng: số có/thiếu, min/mean/median/max; nhóm chiều dài <300 m và ≥300 m.
- Carrier score: số có/thiếu, min/mean/median/max và histogram các khoảng 0,1.

Score là đầu ra dự đoán, không phải độ tin cậy đã hiệu chỉnh. Phân bố score
không tạo thêm ngưỡng để chọn/flag ảnh. Thiếu kích thước/score là `null`, không
đổi thành 0. “30 ngày qua” gồm ngày tham chiếu và 29 ngày trước đó; có thể chỉ
định khoảng ngày có dữ liệu cũ.

`noise_count` đếm điểm có tọa độ chưa vào cụm; không phải ảnh sai. Thiếu tọa
độ không gán vào cụm. `unlocated_in_date_range_count` đếm thiếu vị trí trong
khoảng ngày trước khi lọc vùng; không chứng minh chúng nằm trong vùng đang
chọn. `missing_position_count` là số thiếu vị trí còn trong phạm vi (0 khi
lọc polygon). Các con số là lượt quan sát; nhiều lượt có thể do cùng một vị
trí được chụp nhiều lần. Không kết luận mật độ tàu hay mức hoạt động thực tế.

## Chọn trường hợp để kiểm tra chi tiết

Sau thống kê, agent bắt đầu từ cụm nhiều lượt nhất và gọi
`investigate_carrier_hotspot` → `POST /carrier-hotspot-candidates`, dùng
`report_id`, `cluster_id` và đúng khoảng ngày/vùng của bước tìm cụm.

Backend lấy đúng thành viên của cụm, không tạo polygon/bounding box xấp xỉ.
`report_id` gắn với snapshot nguồn, khoảng ngày, geometry thực tế và tham số
DBSCAN; thay đổi một trong các phần này thì trả 409 để tìm cụm lại. ID cụm
được tính từ membership; không dùng số nhãn tạm thời của sklearn làm ID.

Trong từng cụm dùng lại **câu 17**:

1. Dài **<300 m** vào ưu tiên 1 ngay, không tải/đọc ảnh và không cần model/bộ mẫu.
2. Phần còn lại (kể cả đúng 300 m và thiếu chiều dài) được đối chiếu toàn bộ
   bộ mẫu. Chỉ ảnh đủ rõ có bằng chứng nghi không phải tàu sân bay vào ưu tiên 2.

Ảnh mờ/unknown không flag; lỗi báo riêng, không xóa kết quả ưu tiên 1. Chỉ
dùng hình dáng tổng thể/màu thân, bỏ bóng/vệt nước. Giữ nguyên prediction.
Pixel của các ảnh thực sự được review, cùng toàn bộ mẫu, được gửi trực tiếp
cho LLM chat như trước; ảnh ưu tiên 1 không được gửi vào luồng đọc ảnh.

`limit`/`offset` ở bước kiểm tra là trang **lượt trong một cụm**, sau khi xếp
toàn bộ nhóm <300 m trước nhóm còn lại. Kết quả nêu số sàng lọc, số đã đọc ảnh,
flags, lỗi và `next_offset`/`coverage_complete`. Kiểm tra một trang hoặc một
cụm không có nghĩa đã kiểm tra tất cả khu vực. Với câu hỏi chỉ yêu cầu thống
kê cụm, không cần khởi tạo vision.

## Chạy trên MID

Trong virtualenv của ứng dụng:

```bash
git pull
python -m pip install -r requirements.txt
```

Đã thêm dependency `scikit-learn>=1.5,<2`; cần bộ NumPy/SciPy tương thích trong
virtualenv. Sau đó restart file server **8001** và LangGraph **2024**. Giữ
nguyên Pipe, map và thư mục bộ mẫu. Backend thiếu/hỏng thư viện trả lỗi dịch
vụ, không trả “0 cụm”. Không cần sửa mã Open WebUI.

Ví dụ:

> Trong năm 2025, tìm các khu vực nhiều lượt nghi tàu sân bay bằng DBSCAN.
> Phân tích vị trí, thời gian, kích thước và score, rồi kiểm tra chi tiết cụm
> nhiều lượt nhất theo quy tắc câu 17, xử lý 5 lượt đầu.

> Trong vùng vừa vẽ, tìm các cụm nghi tàu sân bay trong 30 ngày qua, rồi chọn
> các trường hợp đáng chú ý để kiểm tra chi tiết.

Kiểm tra thuật toán thật trên MID:

```bash
python -m pytest tests/file_server/test_hotspot_dbscan_engine.py tests/file_server/test_carrier_hotspot_api.py tests/agent/test_hotspot_tools.py -q
```
