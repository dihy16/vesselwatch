# Bộ câu hỏi mẫu dành cho Agent

## Level 1 — Truy vấn và lọc dữ liệu

- [x] 1. Có bao nhiêu tàu khả nghi được phát hiện trong 7 ngày qua?
- [x] 2. Liệt kê các tàu có chiều dài từ 250–350 m và chiều rộng từ 50–80 m.
- [x] 3. Những tàu nào được nhận dạng là tàu sân bay?
- [x] 4. Cho tôi xem ảnh vệ tinh và thông tin của tàu có ID SHIP_001.

## Level 2 — Truy vấn không gian và thời gian

- [x] 5. Trong khoảng thời gian từ ngày A đến ngày B, có những tàu khả nghi nào xuất hiện trong khu vực X?
- [x] 6. Những tàu có kích thước lớn hơn 250 m đã được quan sát ở những vị trí nào?
- [x] 7. Có bao nhiêu tàu nghi là tàu sân bay được phát hiện trong khu vực X trong tháng vừa qua?
- [ ] 8. Những tàu nào có nhiều lần quan sát vệ tinh tại các thời điểm khác nhau?

## Level 3 — Kết hợp dữ liệu đa nguồn

- [x] 9. Tìm các tàu có kích thước phù hợp với tàu sân bay nhưng mô hình nhận dạng kết luận không phải tàu sân bay.
- [x] 10. Trong số các tàu có chiều dài trên 250 m, bao nhiêu tàu được nhận dạng là tàu sân bay với độ tin cậy trên 80%?
- [ ] 11. Những tàu nào có kết quả nhận dạng khác nhau giữa các ảnh vệ tinh?
- [x] 12. Những trường hợp nào có kích thước tương đồng nhưng kết quả phân loại khác nhau?


## Level 4 — Phân tích và suy luận dựa trên bằng chứng

- [x] 13. Dựa trên ảnh vệ tinh, kích thước và kết quả phân loại, những bằng chứng nào ủng hộ hoặc mâu thuẫn với nhận định SHIP_001 là tàu sân bay?
- [x] 14. Trong khoảng ngày bắt buộc và khu vực tùy chọn, những lượt quan sát được dự đoán không phải tàu sân bay với score ≤0,01 và chiều dài ≥250 m nào có bằng chứng ảnh phù hợp với tàu sân bay? Hãy phân tích và flag các ảnh đủ rõ để kiểm tra thủ công.
- [x] 14a. Trong khoảng ngày bắt buộc và khu vực tùy chọn, lọc nhãn không phải tàu sân bay với score ≤0,01 và chiều dài ≥250 m; đối chiếu từng ảnh với mô tả và toàn bộ ảnh mẫu tàu sân bay, chỉ flag ảnh đủ rõ có bằng chứng phù hợp với tàu sân bay.
- [x] 15. Hai tàu có kích thước tương đương nhưng được phân loại khác nhau. Những đặc điểm nào có thể giải thích sự khác biệt này? Hãy đưa ra ví dụ cụ thể.
- [x] 16. Trong khoảng ngày bắt buộc và khu vực tùy chọn, những ảnh được phân loại là tàu sân bay nào có bằng chứng hình dáng tổng thể và màu sắc cho thấy có thể không phải tàu sân bay? Hãy phân tích và flag các ảnh đủ rõ để kiểm tra thủ công, không cần xác định loại tàu thay thế.

## Level 5 — Điều tra đa bước và tổng hợp

- [x] 17. Hãy điều tra các lượt được phân loại là tàu sân bay trong khu vực X trong 30 ngày qua (hoặc khoảng ngày được chỉ định): ưu tiên 1 là chiều dài <300 m, đưa vào danh sách ngay không đọc ảnh; phần còn lại đối chiếu toàn bộ bộ mẫu, ưu tiên 2 là ảnh đủ rõ có bằng chứng nghi không phải tàu sân bay. Ảnh mờ/unknown không flag; báo rõ phạm vi, phân trang và lỗi.
- [ ] 18. Hãy xác định những khu vực có nhiều lượt phát hiện tàu nghi là tàu sân bay trong 30 ngày qua. Phân tích phân bố theo vị trí, thời gian, kích thước và độ tin cậy, sau đó chọn các trường hợp đáng chú ý để kiểm tra chi tiết.
- [ ] 19. Hãy điều tra các trường hợp mô hình nhận dạng chưa chắc chắn trong khu vực X: tìm các trường hợp tiêu biểu, phân tích nguyên nhân có thể xảy ra, thống kê theo nhóm và đề xuất những trường hợp cần bổ sung nhãn.
- [ ] 20. Hãy lập báo cáo giám sát tàu khả nghi tại khu vực X trong 30 ngày qua: thống kê lượt phát hiện theo thời gian, kích thước và kết quả phân loại; xác định các xu hướng hoặc bất thường đáng chú ý; kiểm tra những trường hợp liên quan và tổng hợp nhận định kèm bằng chứng.

Tests:
## Level 4 — Phân tích và suy luận

- [ ] 13. Vì sao tàu SHIP_001 được nhận dạng là tàu sân bay?
- [ ] 14. Có những tàu nào mà kết quả nhận dạng chưa đủ đáng tin cậy?
- [ ] 15. So sánh đặc điểm kích thước và kết quả nhận dạng của các tàu khả nghi trong khu vực X.
- [ ] 16. Có dấu hiệu nào cho thấy mô hình nhận dạng đang nhầm lẫn giữa tàu sân bay và tàu hàng cỡ lớn?

## Level 5 — Phân tích đa bước và tổng hợp

- [ ] 17. Tổng hợp tất cả tàu có kích thước phù hợp với tàu sân bay, được quan sát trong khu vực X trong 30 ngày qua, kèm ảnh và đánh giá độ tin cậy.
- [ ] 18. Phân tích sự thay đổi kết quả nhận dạng của cùng một tàu qua các lần quan sát.
- [ ] 19. Những yếu tố nào khiến kết quả nhận dạng tàu sân bay chưa chắc chắn? Hãy thống kê và đưa ví dụ.
- [ ] 20. Tạo báo cáo thống kê tàu khả nghi theo khu vực, khoảng kích thước, thời gian và kết quả phân loại.
