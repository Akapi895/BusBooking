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

## Benchmark trước và sau

Bản trước là `dev` tại `919bcef`. Bản sau là Phase 2 tại `e43c7c5`. Hai JAR chạy lần lượt trên cùng máy Windows 16 luồng, với cùng Java 21, heap tối đa 1 GiB và cấu hình PostgreSQL 16.15 trong Docker giới hạn 2 CPU và 2 GiB RAM. Mỗi bản dùng một DB mới với cùng cách sinh dữ liệu gồm 50.000 chuyến tương lai, 100 tuyến và 500 tài khoản tải.

- Tìm chuyến dùng cùng bộ lọc điểm đi, điểm đến và ngày khởi hành. Đặt vé rải đều gửi một ghế mỗi yêu cầu với `Idempotency-Key` riêng. Hai kịch bản chạy 40 người dùng ảo, nghỉ ngẫu nhiên 30–70 ms giữa các yêu cầu, khởi động tải 8 giây và đo 18 giây mỗi lượt. Mỗi bản lặp ba lần.
- Danh sách không lọc dùng một client gửi tuần tự với ba lượt làm nóng và 12 mẫu đo. Đo số chuyến, số byte JSON và thời gian nhận đủ phản hồi.
- Tranh ghế dùng một chuyến mới có 40 ghế mỗi lượt. Chạy ba đợt cho từng mức 20, 80 và 160 client. Đếm mã HTTP, ghi độ trễ rồi đối soát số booking và ghế trong PostgreSQL.

### Tìm chuyến và đặt vé rải đều

Các giá trị là trung vị của ba lượt. Khoảng trong ngoặc là giá trị thấp nhất và cao nhất đo được.

| Kịch bản | Chỉ số | `dev` | Phase 2 |
|---|---|---:|---:|
| Tìm chuyến có bộ lọc | p95 (ms) | 250 (109–328) | 16 (16–47) |
| Tìm chuyến có bộ lọc | p99 (ms) | 328 (140–437) | 31 (16–78) |
| Tìm chuyến có bộ lọc | Phản hồi thành công/giây | 225,0 (187,0–450,5) | 695,1 (584,2–723,6) |
| Đặt vé rải đều | p95 (ms) | 234 (140–375) | 203 (93–250) |
| Đặt vé rải đều | p99 (ms) | 359 (203–531) | 282 (125–375) |
| Đặt vé rải đều | Booking thành công/giây | 223,4 (170,1–321,7) | 331,2 (225,2–416,6) |

Tìm chuyến có cùng bộ lọc có p95 thấp hơn trong cả ba lượt Phase 2. Đặt vé rải đều cho trung vị tốt hơn nhưng khoảng dao động giữa hai bản chồng lên nhau và CPU máy đo chạm 100% ở một số lượt. Cả hai bản trả thành công mọi yêu cầu đo được trong hai kịch bản này, với 0 booking đã commit mà client chưa nhận biết.

### Danh sách không lọc

| Chỉ số | `dev` | Phase 2 |
|---|---:|---:|
| Chuyến trong mỗi phản hồi | 50.000 | 20 |
| Trung vị kích thước JSON | 23.216.895 byte | 9.180 byte |
| Trung vị thời gian nhận phản hồi | 1.812 ms | 16 ms |

Khác biệt này đo số dữ liệu mà client phải nhận khi mở danh sách lần đầu. Phase 2 chỉ trả trang đầu mặc định.

### Tranh ghế cùng một chuyến

Bảng ghi số phản hồi theo khoảng của ba lượt và p95 của mọi mã HTTP theo trung vị, với mỗi client chỉ gửi một lần.

| Client | `dev` 201 / 409 / 503 | Phase 2 201 / 409 / 503 | p95 `dev` → Phase 2 |
|---:|---|---|---:|
| 20 | 20 / 0 / 0 | 9–10 / 0 / 10–11 | 297 → 62 ms |
| 80 | 40 / 40 / 0 | 17–21 / 0 / 59–63 | 907 → 157 ms |
| 160 | 40 / 120 / 0 | 25–28 / 0 / 132–135 | 1.531 → 297 ms |

Phase 2 trả `503` kèm `Retry-After` khi chạm giới hạn theo chuyến, kể cả khi chuyến còn ghế. Ở 160 client, p95 riêng cho phản hồi thành công giảm từ 578 xuống 359 ms. Tất cả các lượt đối soát đúng số vé đã xác nhận, ghế còn lại và tổng tiền.

### Khi client thử lại sau 503

Chạy thêm một lượt mỗi mức trên Phase 2 với DB riêng có 100 chuyến. Mỗi client chỉ thử lại sau `503`, dùng cùng key, chờ `Retry-After` cộng 0–400 ms và thử lại tối đa ba lần.

| Client | Booking ở lần gửi đầu | Booking sau thử lại | Phản hồi cuối 409 / 503 | p95 từ lần gửi đầu đến kết quả cuối |
|---:|---:|---:|---:|---:|
| 20 | 8 | 20 | 0 / 0 | 1,77 giây |
| 80 | 15 | 40 | 40 / 0 | 2,35 giây |
| 160 | 24 | 40 | 120 / 0 | 2,54 giây |

Các lượt thử lại lấp đủ 40 ghế khi có đủ nhu cầu và giữ đúng một booking trên mỗi client thành công. Thời gian chờ thử lại được tính trong độ trễ cuối.

### Giới hạn phép đo

Hai JAR chạy theo thứ tự `dev` rồi Phase 2 trên máy dùng chung với tiến trình phát tải. Đồng hồ của benchmark chính có độ phân giải khoảng 16 ms trên Windows. Mức 40 người dùng ảo là kịch bản đo tải cố định, còn các đợt 160 client có yêu cầu bắt đầu rải trong tối đa khoảng 0,3 giây. Kết quả áp dụng cho cấu hình local này. Đo tải nhiều instance và chạy kéo dài vẫn thuộc [kế hoạch tối ưu](07-optimization-team-plan.md).

[Số liệu theo từng lượt và cấu hình đo](../load-tests/results/phase2-before-after.json)

## Kiểm tra bổ sung về bảo mật và dữ liệu

Hai backend và một Redis chạy trong Compose kiểm thử. Với quota đăng nhập đặt là 2, hai yêu cầu từ cùng nguồn qua hai backend đều qua bộ giới hạn, còn yêu cầu thứ ba nhận `429`. Qua Nginx, thay đổi giá trị `X-Forwarded-For` do client gửi vẫn dùng chung quota của địa chỉ kết nối thực tế. Khi Redis dừng, yêu cầu auth trả `503` kèm `Retry-After` và yêu cầu đọc danh mục công khai vẫn trả `200`.

Flyway đã chạy V22 trên DB kiểm thử có V21 và khởi tạo một DB trống đến V22. Bộ Maven chạy 293 test với PostgreSQL và Redis, bao gồm cạnh tranh ghế cuối, rollback giữ ghế khi insert booking thất bại và chia sẻ quota với hai kết nối Redis.

Dùng `EXPLAIN (ANALYZE, BUFFERS)` trên bộ dữ liệu riêng gồm 50.000 chuyến và 100.000 booking. Hai truy vấn được chạy có và không có ba index V22 trong cùng transaction kiểm thử.

| Truy vấn | Kế hoạch khi có V22 | Execution Time không có → có V22 |
|---|---|---:|
| Đếm ghế xác nhận theo chuyến | `Index Scan` qua `idx_bookings_trip_status` | 5,984 → 0,222 ms |
| Lọc các chuyến tới mốc chuyển trạng thái | `BitmapOr` qua hai partial index | 3,700 → 0,016 ms |

Các thời gian trên là quan sát của từng query plan trên fixture này. Phần benchmark API trước/sau ở trên dùng bản Phase 2 tại `e43c7c5`.

## Lượt chạy thử với một và hai backend

Ngày 25/11/2026, chạy một lượt cho mỗi cấu hình với 160 client cùng đặt một ghế trên chuyến có 40 ghế. Hai lượt dùng cùng JAR, cấu hình mặc định và dữ liệu được tạo lại trên PostgreSQL 16. Với hai backend, client chia yêu cầu luân phiên qua hai cổng loopback.

| Backend | HTTP 201 | HTTP 503 | Ghế còn lại | p95 (ms) | p99 (ms) |
|---|---:|---:|---:|---:|---:|
| 1 | 8 | 152 | 32 | 1007,43 | 1174,14 |
| 2 | 16 | 144 | 24 | 1254,64 | 1325,12 |

Cả hai lượt đều đối soát đúng booking thành công và số ghế. Độ trễ bao gồm phản hồi thành công lẫn phản hồi từ chối có kiểm soát. Mỗi cấu hình mới có một mẫu, dùng để kiểm chứng kịch bản chạy và đối soát trên máy local.
