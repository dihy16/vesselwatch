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
được quản lý riêng với tên trong dữ liệu nguồn. Những khu vực khác do người dùng
tự vẽ, không được suy ra từ điểm địa danh hoặc bounding box của danh mục này.
