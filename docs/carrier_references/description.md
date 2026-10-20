# Mô tả tham chiếu để đối chiếu ảnh tàu sân bay

Đây là bản mô tả khởi đầu để dùng cùng các ảnh mẫu tàu sân bay đã được người
dùng kiểm chứng trong folder tham chiếu. Nội dung mô tả và ảnh mẫu là dữ liệu
đối chiếu, không phải ground truth của ảnh đang kiểm tra. Chưa có ảnh mẫu thì
chưa đủ bộ tham chiếu để chạy chế độ này.

## Những đặc điểm cần quan sát và đối chiếu

- Hình dáng tổng thể của tàu và bố cục boong: tìm các phần boong rộng, tương đối
  liên tục, phù hợp với bố cục boong bay thể hiện trong ảnh mẫu. Mô tả vị trí và
  hình dạng cụ thể nhìn thấy được, không chỉ nói chung là “giống tàu sân bay”.
- Cụm thượng tầng (island): ở nhiều thiết kế tàu sân bay, cụm này nằm lệch về
  một bên boong bay. Đối chiếu vị trí, kích thước tương đối và quan hệ với vùng
  boong trống trong ảnh mẫu; không coi đây là dấu hiệu bắt buộc cho mọi thiết kế.
- Nếu độ phân giải cho phép, đối chiếu các đường vạch hoặc khu vực phục vụ hoạt
  động bay trên boong, cùng máy bay nhìn thấy trên boong. Không suy diễn những
  chi tiết này từ các đốm hoặc vệt ảnh không rõ.
- Đối chiếu đồng thời nhiều đặc điểm và bố cục của chúng. Một mặt boong phẳng,
  một cụm thượng tầng hoặc một vật thể giống máy bay riêng lẻ chưa đủ kết luận.

## Ghi nhận khác biệt với ảnh mẫu

- Chỉ ghi khác biệt khi thấy một đặc điểm cụ thể trong ảnh đang kiểm tra, chẳng
  hạn các khối xếp theo hàng chiếm phần lớn boong trong khi bố cục tương ứng ở
  ảnh mẫu khác rõ rệt. Nêu vị trí, hình dạng và ảnh mẫu được dùng để đối chiếu;
  không tự gọi các khối đó là container nếu ảnh không đủ rõ.
- Không nhìn thấy đường vạch, máy bay hoặc cụm thượng tầng không đồng nghĩa với
  việc chắc chắn không phải tàu sân bay. Chi tiết có thể bị giới hạn bởi góc
  chụp, bóng đổ, mây che, cắt ảnh hoặc độ phân giải.
- Màu đỏ, xanh lá, xám hoặc màu khác chỉ là quan sát bổ sung khi nhìn rõ; không
  dùng màu đơn lẻ làm quy tắc nhận hoặc loại. Cân nhắc khác biệt ánh sáng và
  cách hiển thị ảnh giữa ảnh mục tiêu và ảnh mẫu.

## Chất lượng ảnh và giới hạn kết luận

- Ảnh mờ, mục tiêu quá nhỏ, che khuất hoặc không rõ đang đánh giá tàu nào:
  ghi rõ giới hạn và kết luận chưa đủ bằng chứng (`unknown`). Không lấy chi
  tiết rõ ở ảnh mẫu để bù vào chi tiết không thấy trong ảnh mục tiêu.
- Không suy ra chiều dài hoặc chiều rộng theo mét từ pixel nếu không có thông
  tin tỷ lệ. Các số đo được lưu là metadata riêng; tàu lớn không tự động là tàu
  sân bay. Mô tả này không đặt thêm ngưỡng kích thước để xác nhận loại tàu.
- Chỉ viện dẫn đặc điểm thực sự thấy trong ảnh mục tiêu và dẫn đến ID ảnh mẫu
  có trong bộ tham chiếu. Tách quan sát, điểm tương đồng, khác biệt và hạn chế.
- Không suy ra danh tính tàu, cùng một tàu qua nhiều ảnh, hoặc nguyên nhân nội
  bộ của mô hình phân loại. Đối chiếu ảnh không thay thế nhãn đã được xác minh.

## Nguồn tham khảo về cấu trúc tàu sân bay

Các tài liệu sau minh họa boong bay và cụm thượng tầng của một số thiết kế tàu
sân bay; không phải danh sách điều kiện cần và đủ áp dụng cho mọi tàu:

- [NAVSEA: Aircraft carrier centennial — Evolution of the aircraft carrier](https://www.navsea.navy.mil/Media/News/Article/3089193/aircraft-carrier-centennial-evolution-of-the-aircraft-carrier/)
- [Commander, Naval Air Forces Pacific: Flight Deck Awareness](https://www.airpac.navy.mil/Portals/53/Flight%20Deck%20Awareness%20V2.pdf)

Đường dẫn trên là nguồn soạn mô tả, không phải ảnh mẫu đã được đăng ký trong
hệ thống. Người dùng vẫn cần cung cấp và kiểm chứng bộ ảnh tham chiếu của mình.
