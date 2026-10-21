# Hướng dẫn test các tính năng phân tích Level 4–5

Tài liệu dùng để test thủ công trên Open WebUI/MID theo **các yêu cầu hiện tại**
của [BR.md](BR.md): câu 13–20, trong đó câu 14 và 14a dùng chung luồng kiểm tra.
Các checkbox dưới đây dành cho người chạy test; chưa được đánh dấu là đã đạt.
Phần `Tests` cũ ở cuối BR.md không phải danh sách tính năng đã triển khai đầy đủ:
việc xác định cùng một tàu qua nhiều thời điểm vẫn nằm ngoài phạm vi hiện tại.

## 1. Chuẩn bị trên MID

Trong virtualenv hiện có, từ root repository:

```bash
cd /home/mid/workspaces/aircraft_carrier_agents
git pull
```

Nếu vừa pull bản refactor, restart ba dịch vụ. Mỗi lệnh chạy ở một terminal riêng;
dừng process cũ tương ứng trước khi chạy lại để tránh trùng port:

```bash
python3 scripts/run_vessel_map_demo.py --port 8000
```

```bash
python -m uvicorn file_server.app:create_app --factory --host 127.0.0.1 --port 8001
```

```bash
langgraph dev --no-browser
```

Kiểm tra backend và bộ mẫu:

```bash
curl -fsS http://127.0.0.1:8001/health
curl -fsS http://127.0.0.1:8000/dataset-info
curl -fsS http://127.0.0.1:8001/carrier-references
```

- [ ] `/health` trả OK, đúng nguồn dữ liệu định dùng. Nếu có `map_snapshot_id`
  ở hai response đầu, chúng phải khớp; số lượng nguồn cũng phải phù hợp.
- [ ] Bộ mẫu có mô tả, revision và đủ tất cả ảnh mẫu thực tế. `git pull` không
  mang ảnh mẫu lên MID; chúng nằm trong `data/carrier_references/` theo cấu hình.
- [ ] Model chat hỗ trợ ảnh và tool calls; model vision hỗ trợ nhiều ảnh và
  kết quả JSON. Dùng cấu hình `OPENAI_*`/`OPENAI_VISION_*` hiện có.
- [ ] Dùng Pipe LangGraph đang dùng, map đã mở được. Không cần tạo Function mới.

Nếu thiếu bộ mẫu, xem [hướng dẫn chuẩn bị](missed_carrier_review.md).
Lỗi 503 ở `/carrier-references` cần xử lý trước khi test đọc ảnh.

## 2. Quy ước và cách ghi nhận

**Khoảng ngày mặc định:** 01/01/2025–31/12/2025. Dùng ngày cụ thể trước,
tránh “30 ngày qua” vô tình rơi vào thời gian không có dữ liệu. Các tool điều
tra yêu cầu khoảng 1–366 ngày, gồm cả hai đầu mốc. Câu 13 có thể đọc trực tiếp
một observation đã xác định, không cần khoảng ngày riêng.

**Vùng X:** gửi `mở bản đồ`, chọn/vẽ một vùng có dữ liệu rồi bấm **Xác nhận vùng**,
đợi thông báo đã lưu. Mọi câu “trong vùng vừa vẽ” phải chạy trong cùng chat và
dùng `use_chat_area=true`. Có thể dùng Biển Đông/Vịnh Bắc Bộ để lấy polygon
định nghĩa sẵn; các khu vực khác phải tự vẽ.

**Cách đối chiếu:** mở chi tiết tool call/result nếu Open WebUI có hiển thị;
nếu không, xem trace của run LangGraph. Đối chiếu JSON với câu trả lời cuối,
không chỉ dựa vào lời agent tự nói đã làm gì.

**Giới hạn review ban đầu:** 5 ứng viên (`limit=5`, `offset=0`). Đây là số lượt
được chọn xử lý, không phải số flag mong muốn. Nếu còn `next_offset`, dùng đúng
giá trị đó để tiếp tục, giữ nguyên ngày/vùng. Không cộng các trang khác
`source_snapshot_id` hoặc trộn bằng chứng khác `reference_revision`.

**Cách chấm:** `Đạt`, `Không đạt`, `Bị chặn do môi trường`, hoặc `Chưa đủ dữ liệu`.
Không có ứng viên/cặp/cụm là kết quả hợp lệ nhưng chưa xác nhận được nhánh đọc
ảnh tương ứng. Có 0 flag cũng có thể đúng; không bắt buộc agent phải tìm ra lỗi.

Mọi số đếm là **lượt quan sát**, chưa phải số tàu thực tế duy nhất. Việc hiển
thị ảnh/URL không tự chứng minh model đã được cấp pixel. Tool result có thể
chứng minh bước review; nếu cần xác nhận đầu vào pixel, dùng kiểm thử provider
serialization ở mục 6, không dựa vào câu “tôi đã xem ảnh” của LLM.

### Kiểm tra dữ liệu trước khi gọi vision

Trong chat gửi:

> Trong vùng vừa vẽ, từ 01/01/2025 đến 31/12/2025, có bao nhiêu lượt được phân
> loại là tàu sân bay? Liệt kê 5 lượt đầu kèm observation_id, thời gian, kích
> thước, score và ảnh.

Tool mong đợi: `query_ships_in_area`, đúng ngày/vùng và nhãn `aircraft_carrier`.
Ghi lại tổng cùng một `observation_id` thật để dùng ở T13. Nếu vùng không có
dữ liệu, đổi vùng và xác nhận lại hoặc thử câu tương tự **“trên toàn bộ dữ liệu,
không lọc khu vực”**. Không lấy ID giả như `SHIP_001` để test dữ liệu thật.

## 3. Level 4

### T13 — Bằng chứng của một observation

**Thao tác:** thay `[OBS_ID]` bằng ID lấy ở bước chuẩn bị; đây là chỗ điền,
không gửi nguyên placeholder.

> Với observation_id [OBS_ID], hãy đọc ảnh và đối chiếu với toàn bộ bộ mẫu.
> Dựa trên ảnh, kích thước và prediction đã lưu, nêu bằng chứng ủng hộ,
> mâu thuẫn và những điểm chưa thể kết luận nhận định đây là tàu sân bay.
> Kèm ảnh và tham chiếu mẫu đã dùng.

**Tool mong đợi:** `review_ship_images` với đúng ID và
`use_carrier_references=true`. Nếu chưa có ID trong context, được phép tìm
observation trước bằng tool truy vấn.

- [ ] Đúng ảnh/ID; giữ nguyên số đo trong `measured_dimensions` và nhãn/score
  trong `saved_prediction`.
- [ ] Có `supporting_evidence`, `contradicting_evidence`, `unresolved` theo bằng
  chứng thực tế. Nhãn gốc là `model_output`, không bị trình bày thành quan sát pixel.
- [ ] Bằng chứng ảnh dẫn `reference_id` thuộc bộ mẫu hiện tại; đối chiếu hình
  dáng tổng thể/màu thân, không lấy bóng/vệt nước làm bằng chứng.
- [ ] Nếu ảnh mờ hoặc thiếu bằng chứng, kết luận chưa đủ rõ. Không tự đặt ngưỡng
  250/300 m để kết luận cho câu 13; không tự sửa nhãn hay giải thích nội bộ classifier.

**Thử tiếp ở lượt chat mới:**

> Mở lại toàn bộ ảnh mẫu và mô tả hình dáng tổng thể, màu thân của từng ảnh,
> kèm tên file và reference_id.

Cần gọi `view_carrier_references` để mở lại bộ mẫu; không chỉ kể lại mô tả từ
lịch sử rồi khẳng định đó là quan sát mới.

### T14 / T14a — Kiểm tra tàu sân bay có thể bị bỏ sót

> Trong vùng vừa vẽ, từ 01/01/2025 đến 31/12/2025, tìm các lượt có nhãn không
> phải tàu sân bay, score không quá 0,01 và chiều dài ít nhất 250 m. Đọc 5 ảnh
> ứng viên đầu với toàn bộ bộ mẫu; chỉ flag ảnh đủ rõ có bằng chứng phù hợp
> với tàu sân bay. Báo tổng ứng viên, số đã đọc, lỗi và phần chưa kiểm tra.

**Tool mong đợi:** `investigate_missed_carriers`, đúng ngày/vùng, `limit=5`.

- [ ] Ứng viên đều nhãn `not_aircraft_carrier`, score **≤0,01**, dài **≥250 m**;
  các giá trị đúng biên được tính. Không tự đổi ngưỡng hoặc chọn nhãn dương.
- [ ] Từng flag có ảnh `sufficient`, assessment `aircraft_carrier`, đặc điểm
  nhìn thấy và dẫn chứng tương đồng với mẫu thật.
- [ ] `limited`/`insufficient`/`unknown` không tạo flag. Lỗi đọc ảnh được báo riêng.
- [ ] `total_candidates` là toàn phạm vi; số đọc/flag thuộc trang đã xử lý.
  Không có ứng viên khác với đã đọc nhưng không có flag, và khác với lỗi review.

Câu 14 và 14a hiện cùng phạm vi đã chốt; không cần chạy hai lần cùng đầu vào.

### T15 — Hai observation tương đồng kích thước, khác nhãn

> Trong vùng vừa vẽ, năm 2025, tìm một cặp observation có kích thước tương đồng
> nhưng khác nhãn tàu sân bay/không phải tàu sân bay. Cả dài và rộng sai lệch
> tối đa 10%. Đọc từng ảnh với cùng toàn bộ bộ mẫu và phân tích bằng chứng có
> thể liên quan đến khác biệt nhãn. Kèm hai ảnh, ID, số đo, nhãn và score.

**Tool mong đợi:** `analyze_ship_observations(analysis="similar_dimensions")`,
sau đó `review_ship_images` với hai ID, `comparison_observation_id`,
`use_carrier_references=true`, cùng `similarity_tolerance_pct=10`.

- [ ] Hai ID khác nhau, nhãn đối lập, đủ dài/rộng; sai lệch mỗi chiều là
  `100 * abs(a-b) / max(a,b)` và không vượt 10%.
- [ ] Hai ảnh được đối chiếu riêng với cùng revision và toàn bộ bộ mẫu.
- [ ] Chỉ diễn giải bằng chứng phù hợp với khác biệt nhãn khi
  `can_explain_label_difference=true`. Nếu cả hai đánh giá giống nhau, ngược
  nhãn cũ hoặc ảnh mờ, agent phải nói chưa giải thích được bằng chứng hiện có.
- [ ] Không tạo flag từ chế độ so sánh cặp, không coi hai ID là cùng một tàu,
  không bịa ví dụ nếu tool không tìm được cặp.

Nếu không có cặp trong vùng, thử lại toàn nguồn cùng năm. Nếu vẫn không có,
ghi `Chưa đủ dữ liệu`, không chấm nhánh đối chiếu ảnh là đã đạt.

### T16 — Nhãn tàu sân bay nhưng ảnh có bằng chứng mâu thuẫn

> Trong vùng vừa vẽ, từ 01/01/2025 đến 31/12/2025, kiểm tra 5 lượt đầu được
> phân loại là tàu sân bay. Đối chiếu từng ảnh với toàn bộ bộ mẫu; flag ảnh
> đủ rõ có bằng chứng nghi không phải tàu sân bay. Không cần xác định loại
> tàu thay thế. Kèm ảnh, ID, score gốc và bằng chứng khác mẫu.

**Tool mong đợi:** `investigate_false_carriers`.

- [ ] Chỉ lấy nhãn `aircraft_carrier`; không thêm ngưỡng score/kích thước.
- [ ] Đọc mọi ảnh được chọn, kể cả tàu <300 m; không dùng nhánh bỏ đọc ảnh của T17.
- [ ] Flag cần `sufficient`, assessment `not_aircraft_carrier`, đặc điểm rõ
  và khác biệt cụ thể dẫn mẫu. Không cần kết luận “tàu hàng”.
- [ ] Mờ/unknown hoặc nhận xét không có dẫn chứng không flag. Không khẳng định
  đã xác nhận lỗi mô hình, không sửa prediction.

## 4. Level 5

### T17 — Điều tra và xếp ưu tiên kiểm tra thủ công

> Điều tra các lượt được phân loại là tàu sân bay trong vùng vừa vẽ, từ
> 01/01/2025 đến 31/12/2025, theo câu 17. Xử lý 5 lượt đầu: tàu dài dưới 300 m
> vào ưu tiên 1 ngay; phần còn lại đọc ảnh đối chiếu bộ mẫu, chỉ đưa vào ưu
> tiên 2 khi có bằng chứng rõ nghi không phải tàu sân bay. Báo phạm vi và lỗi.

**Tool mong đợi:** `investigate_carrier_detections`.

- [ ] Backend xếp toàn bộ nhóm <300 m trước khi phân trang. Không thêm ngưỡng score.
- [ ] Ưu tiên 1 có `flag_reason=length_below_300m`,
  `reference_comparison_performed=false`, `visual_review=null`. Agent nói rõ
  kết quả này từ metadata, không nói đã đọc ảnh để kết luận.
- [ ] Đúng 300 m, >300 m hoặc thiếu chiều dài đi nhánh đọc ảnh; ưu tiên 2
  cần bằng chứng rõ như T16. Mờ/unknown không tạo ưu tiên 2.
- [ ] `processed_count = dimension_screened_count + reviewed_count`;
  `selected_count = processed_count + failed_count`;
  `flagged_count = priority_1_count + priority_2_count`.
- [ ] `dimension_candidate_count`/`visual_candidate_count` thuộc toàn phạm vi;
  số ưu tiên/đã đọc/lỗi thuộc trang. Hiển thị ưu tiên 1 trước ưu tiên 2.

Nếu 5 lượt đầu đều <300 m, việc không gọi vision là đúng. Tiếp tục bằng
`next_offset` cho tới trang có ứng viên cần đọc ảnh để kiểm tra nhánh ưu tiên 2.
Không tự thêm bộ lọc ≥300 m làm thay đổi phạm vi T17.

**Phân biệt với T16/T19:** quy tắc <300 m chỉ áp dụng ở T17 và các luồng dùng
lại nó (T18/T20). Một ảnh mờ vẫn có thể thuộc ưu tiên 1 theo metadata; đó
không phải flag được tạo từ bằng chứng ảnh.

### T18 — Tìm cụm DBSCAN và kiểm tra chi tiết

> Trong vùng vừa vẽ, năm 2025, tìm các khu vực có nhiều lượt nghi tàu sân bay
> bằng DBSCAN với eps 30 km, min_samples 2. Phân tích vị trí, thời gian, kích
> thước và score. Sau đó kiểm tra 5 lượt đầu của cụm nhiều lượt nhất theo
> quy tắc câu 17, kèm ID, ảnh và lý do ưu tiên.

**Tool mong đợi:** `find_carrier_hotspots`, sau đó `investigate_carrier_hotspot`
nếu có cụm, dùng `report_id`/`cluster_id` vừa trả và cùng ngày/vùng.

- [ ] Tham số đúng: DBSCAN, eps **30 km**, min_samples **2**, metric Haversine.
  Min_samples tính cả chính điểm; cụm có thể rộng hơn 30 km do chuỗi lân cận.
- [ ] Cụm xếp theo `detection_count` giảm dần, tên Cụm 1/Cụm 2; có tọa độ,
  phân bố ngày, dài/rộng và score, số có/thiếu. Không tự gán tên địa danh.
- [ ] `total_detections = located_count + missing_position_count`;
  `located_count = clustered_detection_count + noise_count`.
  Không cộng `unlocated_in_date_range_count` vào số trong vùng vì đó là số
  thiếu vị trí trước lọc không gian.
- [ ] Bước kiểm tra lấy đúng thành viên cụm và dùng quy tắc T17; không thay
  membership bằng một bounding box hay đọc một trang rồi báo đã kiểm tra hết cụm.
- [ ] Điểm lẻ không bị gọi là ảnh sai; nhiều lượt cùng tọa độ không bị gọi
  là nhiều tàu thực tế. Lỗi thư viện DBSCAN phải báo lỗi, không trả “0 cụm”.

Nếu không có cụm, thử toàn nguồn cùng năm; chỉ chấm nhánh điều tra cụm khi
có membership thực tế. Phân trang tìm cụm đếm **cụm**; phân trang kiểm tra
chi tiết đếm **lượt trong một cụm**.

### T19 — Review nhãn, chia nhóm và đề xuất xác minh

> Trong vùng vừa vẽ, từ 01/01/2025 đến 31/12/2025, kiểm tra nhãn tàu sân bay
> để tìm false positive. Đọc 5 ảnh đầu theo score tăng dần với toàn bộ bộ mẫu.
> Thống kê từng nhóm, nêu ví dụ thực tế và đề xuất các trường hợp cần con
> người xác minh/bổ sung nhãn, kèm ảnh và bằng chứng.

**Tool mong đợi:** `investigate_carrier_labels`.

- [ ] Xét mọi nhãn `aircraft_carrier`, xếp score tăng dần toàn phạm vi trước
  phân trang, thiếu score cuối. Không cắt ở 0,9/0,99 hoặc chỉ lấy score gần 0,5.
- [ ] Đọc mọi ảnh được chọn, kể cả <300 m và score cao; không dùng ưu tiên 1 của T17.
- [ ] Có năm nhóm bên dưới; nhóm rỗng được phép có số 0, không cần bịa ví dụ.

| Giá trị trong tool | Ý nghĩa |
| --- | --- |
| `suspected_false_positive` | Ảnh rõ có bằng chứng nghi không phải tàu sân bay. |
| `reference_consistent` | Ảnh rõ có bằng chứng phù hợp bộ mẫu. |
| `inconclusive` | Chưa đủ bằng chứng để kết luận theo mẫu. |
| `insufficient_image` | Ảnh chưa đủ rõ để đối chiếu. |
| `review_failed` | Lỗi chuẩn bị/tải/đọc/validation. |

- [ ] `sum(group_counts) = selected_count = reviewed_count + failed_count`;
  `annotation_candidate_count = flagged_count`.
- [ ] `candidate_statistics` thuộc toàn phạm vi; `group_counts` và ví dụ
  chỉ thuộc trang xử lý. Không ngoại suy số nhóm cho ảnh chưa đọc.
- [ ] Chỉ nhóm nghi false positive có bằng chứng đủ rõ được đề xuất xác minh
  thủ công. `label_applied=false`; không sửa nhãn, không xác nhận model sai.
- [ ] “Phù hợp mẫu” không được gọi là ground truth. `review_factors` chỉ là
  bằng chứng nhìn thấy/hạn chế ảnh, không phải nguyên nhân nội bộ classifier.

### T20 — Báo cáo giám sát và so sánh tháng

> Lập báo cáo giám sát trong vùng vừa vẽ từ 01/01/2025 đến 31/12/2025.
> Thống kê toàn bộ lượt theo thời gian, kích thước và ba nhãn; so sánh từng
> tháng với tháng liền trước. Kiểm tra 5 ứng viên đầu theo câu 17, tổng hợp
> bằng chứng và xuất báo cáo HTML.

**Tool mong đợi:** `vessel_monitoring_report(output_format="html")`.
Không chỉ dùng `daily_carrier_report` vì tool đó chỉ thống kê nhãn dương.

- [ ] Báo cáo HTML mở được trong Artifacts, có thống kê ngày/tháng, kích
  thước, nhãn và kết quả kiểm tra. Nhận xét trong chat khớp số liệu HTML/tool.
- [ ] `statistics` tính cả `aircraft_carrier`, `not_aircraft_carrier`, `unknown`;
  tổng ba nhãn và tổng các tháng bằng tổng lượt của kỳ được yêu cầu.
- [ ] `limit=5` chỉ giới hạn trang review. Thống kê và baseline tháng vẫn là
  toàn nguồn trong ngày/vùng tương ứng.
- [ ] Review dùng T17: <300 m chỉ metadata; còn lại đọc ảnh; lỗi và phạm vi
  nằm trong `review`. Không nói đã đọc ảnh của mọi lượt trong báo cáo.
- [ ] So sánh tháng dùng cùng vùng, tháng trước đầy đủ; baseline có thể nằm
  ngoài khoảng báo cáo. Không suy từ số lượt thành mức hoạt động tàu thực tế.

**Kiểm tra thêm tháng không đủ ngày:**

> Lập báo cáo trong cùng vùng từ 15/01/2025 đến 28/02/2025, so sánh theo tháng,
> xử lý 5 ứng viên đầu và xuất HTML. Ghi rõ tháng lấy một phần và lượt/ngày.

Kỳ tháng 1 chỉ là 15–31/01 (**17 ngày**) và so với toàn tháng 12/2024;
tháng 2 là 01–28/02 (**28 ngày**) và so với toàn tháng 1/2025. Tháng 1 cần
`partial_month=true`; nhận xét phải dùng `average_daily_count` và số ngày,
không coi hai tổng có độ dài kỳ khác nhau là trực tiếp tương đương.
Nếu baseline bằng 0, phần trăm thay đổi là `null`/`no_baseline`, không phải vô hạn.

**Kiểm tra JSON nếu cần:** yêu cầu lại cùng phạm vi nhưng “chỉ trả dữ liệu
trong chat, không tạo HTML”; tool phải dùng `output_format="json"`.

## 5. Các tình huống kiểm tra chéo

| Tình huống | Cách thử | Kết quả mong đợi |
| --- | --- | --- |
| Chưa chọn vùng | Chat mới chưa xác nhận vùng, hỏi review trong “vùng vừa vẽ”. | Yêu cầu xác nhận vùng; không tự chuyển toàn nguồn hoặc dùng vùng chat cũ. |
| Chưa có ngày | Chat mới hỏi “tìm tàu sân bay bị bỏ sót trong vùng này”, chưa cung cấp ngày. | Hỏi khoảng ngày cho luồng điều tra, không tự chọn năm 2025. |
| Đổi vùng | Xác nhận vùng A → truy vấn → xác nhận vùng B → hỏi lại cùng ngày. | Dùng revision/phạm vi B. Tổng có thể trùng ngẫu nhiên; kiểm tra scope/ID thay vì chỉ so tổng. |
| Bản vẽ chưa xác nhận | Có vùng A đã lưu, vẽ B nhưng chưa bấm xác nhận. | Vùng đang hiệu lực vẫn là A; không coi bản nháp là vùng đã lưu. |
| Xóa vùng | Xóa vùng đã lưu rồi hỏi “trong vùng này”. | Báo cần chọn lại vùng; không âm thầm dùng A. |
| Phân trang | Sau T14/T16/T17/T19, hỏi tiếp cùng ngày/vùng với next_offset được trả. | Đúng offset/limit; báo số trang đã xử lý và lỗi, không gọi một trang là toàn bộ. |
| Ảnh mờ | Dùng một ID mờ thật trong T13/T16/T19 hoặc trang review chứa ảnh mờ. | Không flag bằng bằng chứng ảnh; nói hạn chế. Ngoại lệ metadata <300 m của T17/T18/T20 vẫn giữ. |
| Không có dữ liệu | Dùng vùng nhỏ đã xác nhận và khoảng ngày mà truy vấn kiểm tra trả 0. | Báo không có ứng viên; không gọi vision hay tạo tàu/cặp/cụm giả. |
| Lỗi backend/model/bộ mẫu | Chạy các kiểm thử lỗi offline ở mục 6; nếu thử tay dùng môi trường test riêng. | Báo chưa đánh giá được/lỗi; không diễn giải thành 0 flag hoặc kết luận nhãn đúng. |
| Lỗi vision ở T17/T20 | Dùng test offline tương ứng. | Giữ kết quả ưu tiên 1 và thống kê tính độc lập; phần đọc ảnh lỗi được báo riêng. |
| Bộ mẫu thay đổi | Mở lại bộ mẫu ở lượt sau; kiểm tra revision khi tổng hợp nhiều trang. | Lấy bộ mẫu hiện tại, không ghép các revision thành một kết quả đồng nhất. |

Ảnh review không có ground truth chưa đủ để đánh giá tỷ lệ giảm false positive.
Muốn đo chất lượng model cần người review gán nhãn bộ đánh giá; tài liệu này
kiểm tra luồng xử lý, tính nhất quán và cách trình bày bằng chứng.

## 6. Kiểm thử tự động và phân biệt loại lỗi

Trong virtualenv đầy đủ trên MID:

```bash
python -m pytest tests -q
```

Kiểm tra riêng entry points/imports/assets sau refactor:

```bash
python -m pytest tests/test_package_structure.py -q
```

Kiểm tra việc gửi pixel đích và toàn bộ bộ mẫu vào model chat, rồi mở lại ảnh
ở lượt tiếp theo (HTTP provider được mock; không gọi LLM thật):

```bash
python -m pytest tests/agent/test_direct_visual_graph.py -q
```

Kiểm tra DBSCAN thật với bộ NumPy/SciPy/scikit-learn trên MID:

```bash
python -m pytest tests/file_server/test_hotspot_dbscan_engine.py -q
```

`Skipped` vì thiếu dependency chưa được coi là đã đạt. Kiểm thử tự động dùng
fixtures/mocked responses nên không thay thế test chất lượng ảnh/model thật
trong Open WebUI. Khi thiếu dependency trên MID, dùng requirements của repo
trong đúng virtualenv; không sửa ngưỡng/thuật toán để làm lỗi biến mất.

## 7. Phiếu ghi kết quả

Ghi commit (`git rev-parse --short HEAD`), ngày test, nguồn/snapshot, vùng và
revision, khoảng ngày, model chat/vision đang cấu hình, revision bộ mẫu.
Với mỗi lỗi lưu câu hỏi, tool name + arguments/result hoặc run ID, câu trả
lời cuối và ảnh chụp nếu lỗi giao diện. Không đưa API key vào phiếu.

| Test | Trạng thái | Run ID / ghi nhận |
| --- | --- | --- |
| Chuẩn bị: nguồn, bộ mẫu, vùng | Chưa chạy | |
| T13: bằng chứng một ảnh + mở lại mẫu | Chưa chạy | |
| T14/T14a: nhãn âm score ≤0,01, dài ≥250 m | Chưa chạy | |
| T15: cặp tương đồng, khác nhãn | Chưa chạy | |
| T16: ảnh nhãn dương nghi không phải tàu sân bay | Chưa chạy | |
| T17: ưu tiên kích thước rồi đọc ảnh | Chưa chạy | |
| T18: cụm DBSCAN + điều tra thành viên | Chưa chạy | |
| T19: score tăng dần, chia nhóm, đề xuất nhãn | Chưa chạy | |
| T20: HTML, tháng đầy đủ/tháng một phần, JSON | Chưa chạy | |
| Chọn/đổi/xóa vùng và phân trang | Chưa chạy | |
| Kiểm thử tự động, pixel serialization, DBSCAN engine | Chưa chạy | |

Chỉ đánh dấu đạt sau khi đối chiếu kết quả thực tế. Nếu một nhóm/nhánh chưa
có dữ liệu để kiểm tra thì ghi rõ, không tự tick checkbox tương ứng trong BR.
