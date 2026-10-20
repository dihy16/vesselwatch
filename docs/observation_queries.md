# Truy vấn kích thước và kết quả nhận dạng (BR 9, 10, 12)

Các câu hỏi dùng agent/Pipe hiện tại, đọc dữ liệu từ cùng file server như truy vấn
vùng. Restart file server 8001 rồi LangGraph 2024 sau khi pull code. Không cần đổi
Function hoặc Valves; không tự cập nhật markers trên map.

## Câu 9: kích thước phù hợp nhưng nhãn âm

Ví dụ: “Tìm các tàu có kích thước phù hợp với tàu sân bay nhưng mô hình kết luận
không phải tàu sân bay trong năm 2025.”

Tool `analyze_ship_observations`, `analysis="dimension_mismatch"`.
Mặc định dài **250–350 m**, rộng **50–80 m**, gồm cả hai biên, kết hợp nhãn
`not_aircraft_carrier`. Đây là quy tắc chọn ứng viên theo kích thước, không phải
xác nhận tàu sân bay hoặc kết luận mô hình sai. Câu trả lời nêu khoảng đang dùng.

Người dùng có thể chỉ định khoảng khác. Nếu đặt bất kỳ giới hạn chiều dài nào,
không tự thêm giới hạn chiều dài mặc định còn lại; chiều rộng xử lý tương tự.
Ảnh thiếu kích thước không khớp bộ lọc tương ứng. Nhãn `unknown` không phải nhãn âm.

## Câu 10: chiều dài và carrier score lớn hơn một mức

Ví dụ: “Trong vùng vừa vẽ, năm 2025 có bao nhiêu lượt phát hiện dài trên 250 m,
được nhận dạng là tàu sân bay với score trên 80%?”

Tool `query_ships_in_area` với `use_chat_area=true`, `length_gt_m=250`,
`carrier_score_gt=0.8`, `classification="aircraft_carrier"` và khoảng ngày.
Không có vùng thì dùng `search_ships` với cùng các bộ lọc, hoặc truy vấn vùng
không chỉ định vùng. **250 m và 0.8 chính xác không được tính**; score null bị loại.
Lấy `total` trả về, không đếm số dòng của trang kết quả. Bộ lọc score không đổi nhãn
đã lưu và không diễn giải score như độ tin cậy của nhãn âm.

## Câu 12: kích thước tương đồng nhưng khác nhãn

Ví dụ: “Tìm các trường hợp trong năm 2025 có kích thước tương đồng nhưng kết quả
phân loại khác nhau; cho tôi 5 cặp ví dụ.”

Tool `analyze_ship_observations`, `analysis="similar_dimensions"`, `limit=5`.
Mỗi cặp có một observation `aircraft_carrier`, một `not_aircraft_carrier`.
Không đặt bộ lọc `classification`; có thể đặt bộ lọc kích thước chung nếu muốn.

Với từng chiều, sai lệch tính bằng `100 * abs(a-b) / max(a,b)`.
Cả dài **và** rộng phải sai lệch không quá `similarity_tolerance_pct` (mặc định 10%).
Ví dụ 300×60 m và 270×54 m nằm đúng biên 10%. Đặt 0 để yêu cầu kích thước bằng nhau.
Không dùng nhãn ground truth để thay prediction. Loại các observation thiếu kích
thước hoặc nhãn unknown; phản hồi có số lượng bị loại tương ứng.

`total` là tổng **cặp observations**, không phải số tàu duy nhất. Một observation
có thể xuất hiện trong nhiều cặp. Không suy ra hai ảnh thuộc cùng một tàu.
Các cặp có thứ tự ổn định, không lặp cặp đảo chiều. Chỉ giữ trang yêu cầu trong
phản hồi nhưng đếm trên toàn bộ dữ liệu khớp bộ lọc.

## Vùng, thời gian và API

Hai tool hỗ trợ polygon đã xác nhận của chat qua `use_chat_area=true`. Cả hai
thành viên của một cặp phải nằm trong vùng và khoảng ngày. Không có vùng xác nhận
thì báo lỗi, không tự chuyển sang toàn bộ dữ liệu. Tên vùng ngoài hai preset vẫn
yêu cầu tự vẽ. Không chỉ định vùng/ngày thì phân tích toàn nguồn tương ứng.

File server bổ sung `POST /observation-analyses` nhận
`ObservationAnalysisRequest`: các bộ lọc của `/area-queries`, `analysis`,
`similarity_tolerance_pct` và tùy chọn polygon. Kết quả câu 9 có `ships`; câu 12 có
`pairs`, mỗi cặp kèm hai observations và sai lệch dài/rộng. `limit`/`offset` chỉ
phân trang đầu ra. Lỗi nguồn dữ liệu hoặc tham số không được chuyển thành kết quả 0.
