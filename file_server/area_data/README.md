# Vùng truy vấn có sẵn

Chỉ có **Biển Đông** và **Vịnh Bắc Bộ**. Hình học EPSG:4326 được tải từ WFS
của Marine Regions, lưu nguyên tọa độ dưới dạng GeoJSON nén gzip, không làm
đơn giản đường biên. `sources.json` ghi URL truy vấn, thời điểm và SHA-256 của
phản hồi gốc/hình học để đối chiếu. Runtime đọc file local, không gọi nguồn ngoài.

- Biển Đông: IHO Sea Areas, Marine Regions / VLIZ, MRGID 4332.
- Vịnh Bắc Bộ: SeaVoX v19, Marine Regions, MRGID 24143.

Nguồn và điều kiện sử dụng: https://www.marineregions.org/sources.php và
https://www.marineregions.org/disclaimer.php.

Đây là phạm vi địa lý dùng để lọc observations. Các tên hiển thị tiếng Việt
được quản lý riêng với tên trong dữ liệu nguồn. Những khu vực khác chưa có tâm
được lưu do người dùng tự vẽ.

## Truy vấn mở rộng từ tâm

`AREA_CENTERS` trong `file_server/spatial.py` lưu các điểm tham chiếu WGS84
(không phải ranh giới căn cứ), kiểm tra nguồn ngày 2026-10-21:

| Khóa | Điểm tham chiếu (vĩ độ, kinh độ) | Nguồn |
| --- | --- | --- |
| `thanh_dao` | 35.73525, 119.99199 — Thanh Đảo / Yuchi | https://mapcarta.com/W510086495 (OpenStreetMap way 510086495) |
| `du_lam` | 18.221, 109.537 — Du Lâm truyền thống, Tam Á | https://www.govinfo.gov/content/pkg/GOVPUB-D208-PURL-gpo246371/pdf/GOVPUB-D208-PURL-gpo246371.pdf (China Maritime Report, hình 32 và bảng 25, trang PDF 68) |
| `long_pha` | 18.21171, 109.685 — Long Pha / Du Lâm Đông | https://mapcarta.com/W158981830 (OpenStreetMap way 158981830) |

Thanh Đảo ở đây là căn cứ Yuchi, không phải căn cứ tàu ngầm Khương Các Trang
(Jianggezhuang). Du Lâm truyền thống và Long Pha/Du Lâm Đông là hai tâm riêng.
Có thể cập nhật bảng tâm khi dự án chốt điểm tham chiếu khác.

Hai tên truy vấn `căn cứ Thanh Đảo` và `căn cứ Du Lâm` lần lượt dùng
`thanh_dao` và `du_lam` trong bảng trên. Tọa độ ghi theo thứ tự **vĩ độ,
kinh độ**, đơn vị độ thập phân; GeoJSON khi dựng ô dùng thứ tự **kinh độ,
vĩ độ**. Đây là điểm tham chiếu trong khu vực căn cứ để mở rộng theo hải lý,
không phải polygon ranh giới được khảo sát của toàn căn cứ.

Người dùng phải cung cấp `radius_nm` với tên căn cứ hoặc cặp
`center_latitude`/`center_longitude`. Ví dụ `{"area_name":"Thanh Đảo","radius_nm":20}`
hoặc `{"center_latitude":18.221,"center_longitude":109.537,"radius_nm":20}`.
Không có khoảng cách mặc định. Một hải lý = 1852 m; ô có biên Bắc/Nam/Đông/Tây
cách tâm theo khoảng cách nhập, cạnh xấp xỉ `2 * radius_nm`. Công thức dùng
mặt cầu bán kính trung bình 6371008.8 m và hiệu chỉnh kinh độ theo cos(vĩ độ tâm),
phù hợp truy vấn địa phương; không phải đa giác đo đạc trắc địa chính xác trên
ellipsoid. Bao gồm các góc và điểm trên biên, không lọc theo hình tròn.
Vùng vượt cực hoặc kinh tuyến 180 độ bị từ chối. Lưu polygon đã tính để
phân trang, mở lại map và hỏi agent cùng một phạm vi.
