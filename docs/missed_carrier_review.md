# Đối chiếu ảnh để tìm tàu sân bay có thể bị bỏ sót

Đây là bước đã thống nhất cho Level 4: kiểm tra nhãn âm tự tin cao, không phải
triển khai toàn bộ câu 13–16 hoặc điều tra Level 5. Mỗi crop là một lượt quan sát;
không suy ra danh tính cùng tàu qua nhiều ảnh và không thay prediction đã lưu.

## Chuẩn bị bộ mẫu trên MID

Trong thư mục repo, tạo folder sau rồi đưa **mô tả và ảnh mẫu thật của bạn** vào:

```bash
mkdir -p data/carrier_references
cp -n docs/carrier_references/description.md data/carrier_references/description.md
```

```text
data/carrier_references/
  description.md
  carrier-example-01.jpg
  carrier-example-02.png
  more-examples/
    carrier-example-03.webp
```

`description.md` là mô tả UTF-8 về những đặc điểm muốn đối chiếu. Repo có bản mô
tả khởi đầu tại `docs/carrier_references/description.md`; lệnh trên chép bản này
vào folder runtime nếu chưa có file, không ghi đè mô tả riêng đã có của bạn.
Bạn có thể chỉnh bản runtime cho phù hợp với bộ ảnh thật. Không có ảnh mẫu mặc
định được giả lập sẵn. Ảnh và mô tả nằm trong `data/` được Git ignore;
`git pull` chỉ mang bản mô tả trong `docs/`, không mang bộ ảnh mẫu lên MID.

Khi muốn thay mô tả runtime bằng bản cập nhật trong repo, chạy lệnh sau (ghi đè
file mô tả hiện có; không thay ảnh mẫu):

```bash
cp docs/carrier_references/description.md data/carrier_references/description.md
```

Bản mô tả hiện tại dành cho crop vệ tinh ít chi tiết, dựa trên hai crop minh
họa người dùng cung cấp. Chỉ đối chiếu hình dáng tổng thể và màu sắc phần thân;
không dùng bóng/vệt nước và không đòi hỏi chi tiết của ảnh chụp gần. Hai ảnh
gửi trong chat không tự được đăng ký thành bộ mẫu trên MID.

Đường dẫn được cấu hình bằng `CARRIER_REFERENCE_DIR` trong `file_server/config.py`.
Đọc tất cả ảnh hỗ trợ trong folder và folder con: PNG, JPEG, WebP, TIFF, BMP, GIF
(frame đầu). Mỗi ảnh tối đa 10 MB/16 triệu pixel; mô tả tối đa 64 KiB. Symlink,
ảnh hỏng hoặc ảnh vượt giới hạn làm việc nạp bộ mẫu thất bại, không bị bỏ qua âm thầm.
Không tự lấy một phần ảnh mẫu khi đầu vào quá lớn cho vision model.

## Chạy và thử

Sau khi pull code, restart file server 8001 rồi LangGraph 2024. Map và Pipe hiện
tại giữ nguyên. Vision dùng `OPENAI_VISION_MODEL`, `OPENAI_VISION_BASE_URL`,
`OPENAI_VISION_API_KEY`, hoặc các biến `OPENAI_*` tương ứng nếu không cấu hình riêng.
Model/endpoint cần đọc được nhiều ảnh trong một yêu cầu.

Kiểm tra bộ mẫu:

```bash
curl http://127.0.0.1:8001/carrier-references
```

Thiếu mô tả/ảnh hợp lệ trả HTTP 503; không ảnh hưởng các truy vấn dữ liệu thường.
API trả mô tả, revision, tên/ID và URL ảnh. Có thể mở URL ảnh để kiểm tra pixel đã
đăng ký. Thay nội dung bộ mẫu được đọc lại ở lần lấy manifest tiếp theo; đổi đường
dẫn cấu hình cần restart file server.

Trong chat:

> Tìm tàu sân bay có thể bị bỏ sót trong vùng vừa vẽ từ 01/01/2025 đến 31/12/2025.
> Đọc đối chiếu 5 ảnh ứng viên đầu tiên với toàn bộ bộ mẫu.

Hoặc bỏ “trong vùng vừa vẽ” để không giới hạn không gian. Thiếu khoảng ngày thì
agent cần hỏi lại; không tự dùng toàn bộ thời gian.

## Luồng xử lý

1. `investigate_missed_carriers` lấy ứng viên từ `POST /missed-carrier-candidates`.
   Server lọc toàn bộ snapshot theo ngày, polygon nếu có, nhãn
   `not_aircraft_carrier`, **carrier score ≤0,01**, **chiều dài ≥250 m**; gồm các biên.
   Thiếu score/chiều dài bị loại. Có polygon thì thiếu vị trí cũng bị loại.
2. Lấy `GET /carrier-references`, rồi tải **tất cả** pixel ảnh qua
   `GET /carrier-references/images/{reference_id}?revision=...` trên backend đã cấu hình.
   Revision/hash phát hiện bộ mẫu bị thay đổi hoặc tải không đầy đủ. Không theo URL
   ngoài backend; không bỏ bớt ảnh mẫu nếu một ảnh lỗi.
3. Với mỗi ứng viên trong trang, gửi TARGET + mô tả + **toàn bộ ảnh mẫu** cho vision.
   Cùng một bộ mẫu được dùng xuyên suốt trang. Vision không nhận score, nhãn gốc
   hoặc kích thước đo sẵn để tránh dựa vào các giá trị đó thay vì đọc pixel.
4. Chỉ flag khi ảnh được đánh giá đủ rõ (`sufficient`), assessment là
   `aircraft_carrier`, có đặc điểm nhìn thấy và điểm tương đồng dẫn đến ID ảnh mẫu
   có thật. Màu sắc đơn lẻ không phải quy tắc loại/nhận tự động.

Kết quả `flags` chứa ảnh, metadata/prediction gốc, đặc điểm nhìn thấy và bằng chứng
đối chiếu. Đây là các trường hợp **cần kiểm tra thủ công**, không phải nhãn xác nhận.
Chất lượng `limited`/`insufficient` không flag; kết luận không rõ là `inconclusive`.
Lỗi tải ảnh/provider/JSON là lỗi đọc ảnh, không phải kết quả âm.

## Phạm vi kết quả và phân trang

`limit`/`offset` chọn trang ứng viên được đọc ảnh, mặc định 20, tối đa 100.
Không áp giới hạn này trước khi lọc. Không tự đặt giới hạn số ảnh mẫu.
`total_candidates` là toàn bộ ứng viên khớp; `reviewed_count`, `flagged_count`,
`unflagged`, `errors` thuộc trang đang kiểm tra. `next_offset` chỉ trang tiếp theo.
`coverage_complete` chỉ true khi toàn bộ ứng viên được kiểm tra thành công từ đầu.
Một trang cuối bắt đầu ở offset khác 0 cũng không tự được coi là toàn bộ phạm vi.

Không có ứng viên (`no_candidates`) khác với đã đọc ảnh nhưng không có flag, và
không gọi vision khi không có ứng viên. Trang rỗng ở offset vượt tổng trả
`empty_page`. Thiếu bộ mẫu khi cần đọc ảnh báo lỗi; toàn bộ lượt đọc thất bại trả
`failed`, không được diễn giải là không có trường hợp bị bỏ sót. Chưa có bộ mẫu
thật hoặc chưa chạy trên MID thì chưa đánh giá chất lượng nhận dạng thực tế.

## Câu 13: bằng chứng của một observation bất kỳ

Dùng lại `review_ship_images` với `use_carrier_references=true` sau khi tìm đúng
`observation_id` bằng `search_ships` hoặc `query_ships_in_area`. Không áp bộ lọc
nhãn âm, score, chiều dài hoặc khoảng ngày bắt buộc của 14a lên một observation đã chọn.
Nếu một ship_id trả nhiều observations và chưa rõ ảnh/thời điểm muốn xem, agent
cần xác định observation trước, không ghép bằng chứng từ nhiều ảnh.

Ví dụ câu hỏi: “Dựa trên ảnh, kích thước và prediction, bằng chứng nào ủng hộ hoặc
mâu thuẫn với nhận định observation này là tàu sân bay?”

Tool tải cùng bộ mô tả và **tất cả ảnh mẫu**, dùng lại hàm đối chiếu ảnh của 14a,
rồi tổng hợp `supporting_evidence`, `contradicting_evidence`, `unresolved` cùng
metadata kích thước, nhãn/score gốc và revision bộ mẫu. Evidence từ prediction
(`model_output`) được tách khỏi nhận xét pixel (`reference_comparison`). Cả điểm
tương đồng và khác biệt cụ thể có thể xuất hiện trong cùng một đánh giá.

Số đo được giữ nguyên trong `measured_dimensions`. Không tự áp ngưỡng 250 m hay
coi kích thước tự nó là bằng chứng xác nhận/phủ nhận tàu sân bay. Chỉ đối chiếu số
đo với tiêu chí kích thước nếu bộ mô tả do người dùng cung cấp có tiêu chí đó.
Ảnh mờ hoặc nhận xét âm không có đặc điểm/khác biệt dẫn đến ảnh mẫu được coi là
chưa đủ bằng chứng. Không suy ra chi tiết nội bộ classifier hoặc sửa prediction.

Mặc định `use_carrier_references=false` giữ luồng đọc ảnh độc lập trước đây, không
bắt buộc bộ mẫu. Chế độ đối chiếu thiếu bộ mẫu sẽ báo lỗi, không tự quay về đoán
từ nhãn/kích thước. Dùng lại cấu hình folder/endpoints của 14a; sau khi cập nhật
code câu 13 chỉ cần restart LangGraph để nhận schema tool và prompt mới.

## Câu 15: đối chiếu hai observation khác nhãn với bộ mẫu

Agent dùng `analyze_ship_observations(analysis="similar_dimensions")` của câu 12
để tìm một cặp khác nhãn nếu chưa có hai observation cụ thể. Mặc định cả chiều
dài và rộng chênh không quá 10%, tính bằng `100 * abs(a-b) / max(a,b)`; có thể
thay bằng mức sai lệch người dùng yêu cầu. Giữ bộ lọc ngày/vùng của câu hỏi.

Sau đó gọi `review_ship_images` với `observation_id`, `comparison_observation_id`,
`use_carrier_references=true` và cùng `similarity_tolerance_pct`. Tool kiểm tra
hai ID khác nhau, nhãn đối lập và đủ số đo phù hợp trước khi đọc ảnh. Bộ mẫu
được tải một lần; mỗi ảnh được đối chiếu riêng với **cùng mô tả và toàn bộ ảnh
mẫu**, dùng lại luồng câu 13. Không áp bộ lọc score/chiều dài của 14a.

Kết quả giữ ảnh, số đo, nhãn/score và bằng chứng đối chiếu của từng observation.
Chỉ nêu đặc điểm có thể liên quan đến khác biệt nhãn khi hai đánh giá ảnh có
bằng chứng phù hợp với hai nhãn đã lưu (`can_explain_label_difference=true`).
Nếu ảnh mờ, cả hai đánh giá giống nhau hoặc đánh giá trái với nhãn gốc thì báo
chưa giải thích được khác biệt nhãn bằng bằng chứng hiện có. Lỗi đọc một ảnh
hoặc thiếu bộ mẫu là lỗi rõ ràng, không tạo ví dụ thay thế từ metadata.

Không suy ra nguyên nhân nội bộ classifier, không xác nhận hai observation là
cùng một tàu, không sửa prediction và không tạo flag từ chế độ so sánh cặp.
Ví dụ: “Trong vùng vừa vẽ, năm 2025, cho một ví dụ hai tàu kích thước tương đồng
nhưng khác nhãn; đối chiếu từng ảnh với bộ mẫu để phân tích.”

Dùng lại folder/API bộ mẫu hiện có. Sau khi pull code câu 15, restart LangGraph;
không cần đổi Pipe hoặc cấu hình map.

## LLM chat trực tiếp xem ảnh và mở lại bộ mẫu

LLM chat nhận pixel của ảnh mục tiêu và toàn bộ ảnh mẫu sau khi tool phân tích
trả thành công. Câu 13 gửi một ảnh mục tiêu; câu 15 gửi cả hai ảnh. Với 14a,
gửi các ảnh đã được tool đọc thành công trong trang cùng toàn bộ bộ mẫu;
các lỗi và phạm vi phân trang vẫn được báo riêng. Luồng review độc lập không
dùng bộ mẫu cũng gửi pixel ảnh mục tiêu cho LLM chat.

Tool `view_carrier_references` mở riêng toàn bộ bộ mẫu, không cần observation.
Thử: “Mở lại toàn bộ ảnh mẫu, mô tả trực tiếp hình dáng và màu sắc của từng ảnh,
kèm tên file và reference_id.” LLM cần gọi tool này để xem lại ảnh ở lượt mới;
văn bản trong lịch sử không thay cho ảnh đang được gửi vào model.

Tool trả ID ảnh và revision, không ghi base64 vào lịch sử chat. Trước lần gọi
model, LangGraph tải pixel qua backend đã cấu hình, xác minh đúng observation,
image_id và revision bộ mẫu, rồi thêm một message ảnh chỉ dành cho đầu vào model.
Message này không lưu vào state/checkpoint, không gửi sang Open WebUI và không
bị bộ lọc HTML artifact loại bỏ. Các tool ảnh gọi song song dùng cùng bộ mẫu
được gộp để không lặp ảnh. Không tự cắt bớt bộ mẫu; nếu tải một ảnh lỗi hoặc
revision thay đổi thì báo chưa tải đủ ảnh trực tiếp, không ghép bộ mẫu khác.

`OPENAI_MODEL` và `OPENAI_BASE_URL` của **LLM chat** phải hỗ trợ cả ảnh và tool
calls. `OPENAI_VISION_*` vẫn cấu hình model review có cấu trúc trong tool;
chỉ cấu hình các biến vision không làm model chat tự có khả năng đọc ảnh.
Nếu model chat từ chối đầu vào ảnh/context quá lớn, graph báo lỗi, không tự
quay về trả lời từ văn bản. Có thể chọn trang mục tiêu nhỏ hơn bằng `limit`;
toàn bộ ảnh mẫu vẫn được gửi. Luồng này có thêm chi phí đầu vào ảnh ở LLM chat.

LLM chat phân biệt quan sát trực tiếp, nhận xét review của tool và prediction
đã lưu. Chỉ đối chiếu hình dáng tổng thể/màu phần thân; bỏ bóng/vệt nước.
Nhận xét bổ sung không tự sửa prediction hay phát sinh/thay flags do tool
kiểm tra. Nếu nhận xét mâu thuẫn thì nêu để người dùng kiểm tra lại.

Sau `git pull`, restart LangGraph; không cần sửa Pipe/Open WebUI hoặc endpoint
file server cho bước này. Thử câu hỏi về bộ mẫu ở trên và câu hỏi phân tích cặp
ở câu 15. Unit test kiểm tra đầy đủ pixel; test provider/graph dùng HTTPX
MockTransport để kiểm tra body thực tế của request chat và mở lại qua lượt mới.
Chưa có xác minh vision thực tế trên MID chỉ từ các kiểm tra offline.

## Câu 14 và 16: hai chiều kiểm tra nhãn

Phạm vi câu 14 được người dùng chốt giữ nguyên nhánh 14a đã triển khai:
khoảng ngày bắt buộc, vùng tùy chọn, nhãn `not_aircraft_carrier`, score ≤0,01,
chiều dài ≥250 m. Dùng `investigate_missed_carriers` và endpoint
`POST /missed-carrier-candidates`; không mở rộng sang ngưỡng hoặc kích thước khác.
`docs/BR.md` ghi rõ phạm vi này, thay vì đánh dấu một bộ kiểm tra lỗi mô hình
tổng quát không có bộ lọc đã được chốt.

Câu 16 được mở rộng theo yêu cầu người dùng: không cần chứng minh đó là tàu
hàng/container; bất kỳ ảnh mang nhãn `aircraft_carrier` nào có bằng chứng rõ
cho thấy có thể không phải tàu sân bay đều có thể được flag để kiểm tra.

| Luồng | Ứng viên | Bằng chứng ảnh tạo flag |
| --- | --- | --- |
| Câu 14/14a — `investigate_missed_carriers` | Nhãn âm, score ≤0,01, dài ≥250 m | Ảnh đủ rõ, nhận xét nghi tàu sân bay, có đặc điểm nhìn thấy và tương đồng dẫn đến mẫu |
| Câu 16 — `investigate_false_carriers` | Tất cả nhãn `aircraft_carrier` trong phạm vi; không thêm ngưỡng score/kích thước | Ảnh đủ rõ, nhận xét nghi không phải tàu sân bay, có đặc điểm nhìn thấy và khác biệt cụ thể dẫn đến mẫu |

`POST /false-carrier-candidates` lọc toàn bộ snapshot trước `limit`/`offset`,
dùng cùng xác nhận polygon, snapshot nguồn và quy tắc ngày UTC như nhánh 14a.
Thiếu số đo/score không tự loại một observation đã có nhãn `aircraft_carrier`.
Thiếu vị trí chỉ bị loại khi truy vấn có vùng không gian.

Tool mới dùng lại bộ mẫu và hàm review từng ảnh. Review không được biết nhãn
hoặc score gốc trước khi đọc pixel. Sau đó kiểm tra danh tính observation,
revision, citation và chuẩn hóa bằng chứng như câu 13, rồi mới quyết định flag
theo chiều nghi không phải tàu sân bay. Không đảo nhãn hoặc dùng riêng kích
thước/màu sắc để tạo flag. Khác một ảnh mẫu hoặc không thấy chi tiết nhỏ chưa
đủ để kết luận. Ảnh `limited`/`insufficient`, nhận xét âm thiếu đặc điểm hoặc
khác biệt dẫn mẫu là chưa đủ bằng chứng, không flag. Không bắt buộc bộ mẫu tàu
hàng và không tự gán một loại tàu khác.

Kết quả có ảnh/ID, prediction gốc, `visual_review`, bằng chứng ủng hộ/mâu thuẫn,
hạn chế và `flag_reason="suspected_non_carrier"` cho ảnh được flag. Đây không
phải lỗi mô hình đã xác nhận (`is_confirmed_error=false`). Flag nằm trong kết
quả điều tra; không ghi đè prediction hoặc nhãn human review đã lưu.

Số đã đọc, lỗi, ảnh chưa đủ rõ, tổng ứng viên và `next_offset`/`coverage_complete`
vẫn theo trang. Không có ứng viên khác với lỗi đọc toàn bộ ảnh. Các ảnh được
review thành công trong trang cùng toàn bộ bộ mẫu cũng được đưa trực tiếp vào
LLM chat như các luồng trước; kết quả không tạo thêm map khi dùng vùng chat.

Sau `git pull`, restart **file server 8001** để có endpoint mới, rồi restart
**LangGraph 2024**. Giữ cấu hình bộ mẫu, Pipe và map. LLM chat vẫn cần hỗ trợ
ảnh và tool calls như phần trên.

Thử câu 14:

> Trong vùng vừa vẽ, từ 01/01/2025 đến 31/12/2025, tìm tàu sân bay có thể bị bỏ
> sót với score ≤0,01 và dài ≥250 m. Đối chiếu 5 ảnh đầu với toàn bộ bộ mẫu.

Thử câu 16:

> Trong vùng vừa vẽ, từ 01/01/2025 đến 31/12/2025, kiểm tra 5 ảnh đầu được phân
> loại là tàu sân bay. Flag các ảnh đủ rõ có bằng chứng có thể không phải tàu
> sân bay, kèm ảnh và lý do. Không cần xác định loại tàu khác.
