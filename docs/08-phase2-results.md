# Kết quả kiểm chứng Phase 2

Kiểm tra ngày 24/11/2026 trên Java 21, PostgreSQL 16 và Mailpit. PostgreSQL dùng cho kiểm tra được tách khỏi dữ liệu đang phục vụ. Flyway đã nâng cấp một DB kiểm thử từ V16 lên V21 và khởi tạo một DB trống đến V21.

| Hạng mục | Kết quả kiểm tra |
|---|---|
| Booking và retry | Ca HTTP giữ khóa chuyến cho tới khi client timeout. Request đầu commit khi nhả khóa. Retry cùng key trả lại cùng booking ID và số ghế chỉ giảm một lần. Payload khác cùng key bị từ chối. |
| Ghế và rollback | Ca cạnh tranh ghế cuối, hủy lặp và booking đồng thời với đổi xe hoặc hủy chuyến đều qua. Khi ghi booking thất bại sau khi cập nhật ghế, transaction hoàn lại thay đổi. Đối soát các ca này ghi nhận 0 sai lệch ghế và tổng tiền. |
| Lịch và vòng đời | Integration test kiểm tra chuyến trùng giờ, chuyến nối tiếp, chuyến đã qua giờ khởi hành và giới hạn thay đổi giờ/tuyến khi đã bán vé. Test chuyển trạng thái chạy trên PostgreSQL. |
| Quá tải có kiểm soát | Trong ca giữ khóa một chuyến với 20 yêu cầu, 8 yêu cầu đặt vé thành công sau khi nhả khóa và 12 yêu cầu nhận `503` kèm `Retry-After`. Kiểm tra DB ghi nhận đúng 8 booking. Đây là ca kiểm tra hành vi khi có tranh chấp khóa. |
| Phục hồi SMTP | Trong lúc tắt Mailpit, đăng ký trả `201` và worker ghi lịch retry. Sau khi mở lại Mailpit, người dùng nhận được mã và xác minh thành công. Integration test cũng kiểm tra mã đã gửi trước đó vẫn dùng được khi lần gửi mới lỗi. |
| Smoke test | Ca đăng ký/xác minh/đăng nhập và ca CRUD danh mục/đặt/hủy vé đều qua. Ba workload Locust read, write và mixed đều qua ở 1 VU. |
| Ranh giới tầng | Bộ kiểm tra constant pool của JAR quét 47 class nghiệp vụ và không phát hiện phụ thuộc trực tiếp vào các package hạ tầng thuộc phạm vi kiểm tra. |

Chạy lại test Java bằng `mvn -B verify` với PostgreSQL kiểm thử. Xem cách chạy smoke và acceptance trong [hướng dẫn kiểm thử tải](../load-tests/ACCEPTANCE.md).

Chưa có benchmark trước/sau hoặc số liệu p95/p99 ở tải lớn. Rate limit và giới hạn yêu cầu theo chuyến hiện chạy ở từng instance. RabbitMQ, Redis và đo tải nhiều instance thuộc kiến trúc đích trong [kế hoạch tối ưu](07-optimization-team-plan.md).
