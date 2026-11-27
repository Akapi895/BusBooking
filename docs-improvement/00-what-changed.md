# 00 — Những gì đã thay đổi so với upstream

**Mốc so sánh:** repo gốc [BuiHuy16/Bus-booking-system](https://github.com/BuiHuy16/Bus-booking-system), commit `fd6b5f3`. Tài liệu gốc tại mốc này được giữ nguyên ở [`docs-upstream/`](../docs-upstream/). Các tài liệu 01–06 trong thư mục này là bản đã cập nhật theo code hiện tại.

**Quy mô:** 55 commit (không tính merge), 11 migration mới (V17–V27), số file test từ 37 lên 45 (327 test JUnit).

## 1. Hiệu năng

Số liệu đo trước/sau ở [08 — Kết quả Phase 2](08-phase2-results.md). Tóm tắt:

| Thay đổi | Cơ chế | Code/migration |
|---|---|---|
| Tìm chuyến có lọc nhanh hơn | Index cho truy vấn tìm chuyến công khai | V20 |
| Danh sách không còn trả toàn bộ dữ liệu | Phân trang, tối đa 100 bản ghi/trang | `PageQuery` |
| Đặt vé ít round-trip hơn | Giữ ghế và đọc giá trong một câu `UPDATE … RETURNING` | `TripRepositoryAdapter.reserveSeats` |
| Tranh ghế không làm nghẽn pool | Giới hạn số yêu cầu đặt vé đồng thời, trả `503` + `Retry-After` | `BookingAdmission` |
| Truy vấn vòng đời vé/chuyến nhanh hơn | Index theo trạng thái và thời gian | V22 |
| Mỗi request nạp tài khoản nhẹ hơn | Projection thay vì toàn bộ entity | `findActiveVerifiedPrincipal` |

## 2. Độ tin cậy và nghiệp vụ

| Thay đổi | Code/migration |
|---|---|
| Gửi lại yêu cầu đặt vé không tạo vé trùng (`Idempotency-Key`) | V17 |
| Một xe không chạy hai chuyến trùng giờ (ràng buộc ở database) | V18 |
| Email OTP qua outbox: SMTP lỗi vẫn đăng ký được, email gửi lại sau | V19 |
| Sửa tràn cột tổng tiền | V21 |
| Không đặt vé chuyến đã khởi hành; không hủy vé chuyến đã chạy; hủy lặp lại chỉ hoàn ghế một lần | `BookingService` |
| Hủy chuyến tự hoàn tiền và gửi email cho người đã đặt | V25, `TripCancellationNoticeWorker` |
| Giữ ghế trước khi xác nhận (`HELD`), hết hạn thì trả ghế | V26 |
| Mọi thời gian lưu và hiển thị theo giờ Việt Nam; sửa lỗi không đặt được chuyến khởi hành trong 7 giờ tới | V27, `TravelTime` |

## 3. Bảo mật

Đối chiếu đầy đủ với OWASP, NIST, RFC ở [09 — Đối chiếu tiêu chuẩn](09-standards-compliance.md).

| Thay đổi | Code/migration |
|---|---|
| Rate limit xác thực dùng chung qua Redis khi chạy nhiều backend; chỉ tin IP do proxy tin cậy chuyển tiếp | `security/ratelimit`, `deploy/compose.scale.yaml` |
| Giới hạn đăng nhập theo tài khoản, kể cả endpoint đổi mật khẩu | `AuthController`, `UserController` |
| Đăng xuất và thu hồi mọi token cũ (claim `ver`) | V23 |
| Đổi mật khẩu; quên mật khẩu bằng mã gửi qua email | V24 |
| Log `security.audit` cho đăng nhập, đăng xuất, đổi và đặt lại mật khẩu; log đổi quyền qua `RoleChangeAudit` | `AuthController`, `UserController`, `RoleChangeAudit` |
| Chặn mật khẩu phổ biến | `AuthInputPolicy` |

## 4. Vận hành và triển khai

| Thay đổi | Ở đâu |
|---|---|
| Actuator (health, metrics, Prometheus) trên cổng quản trị riêng, chỉ loopback | `application.properties` |
| Prometheus + Grafana + postgres-exporter | `compose.yaml` profile `metrics`, `deploy/observability/` |
| Nhiều backend sau Nginx | `deploy/compose.scale.yaml` |
| HTTPS, header bảo mật (CSP, HSTS…) | `deploy/compose.tls.yaml`, `deploy/nginx/` |
| Cổng database, backend, Mailpit chỉ mở trên loopback; profile `prod` không nạp dữ liệu demo | `compose.yaml` |
| Image chạy user không phải root, có healthcheck, múi giờ Việt Nam | `Dockerfile`, `compose.yaml` |
| Deploy miễn phí lên Render + Neon + Resend | `render.yaml`, [06](06-running-guide.md) |
| CI: test với PostgreSQL và Redis, build Docker image, kiểm tra file compose | `.github/workflows/ci.yml` |

## 5. Kiểm thử

- Test tích hợp trên PostgreSQL thật, test nâng cấp Flyway (từ V16 và cài mới).
- Bộ kiểm tải Locust trong `load-tests/` (smoke, acceptance, spike, phục hồi, soak; chạy được trên Kaggle).

## 6. Giao diện

Frontend tĩnh qua Nginx (`frontend/`): tìm chuyến theo ngày, đăng nhập, đặt và xác nhận vé. Dữ liệu demo nằm ở một chỗ: danh mục và chuyến (`db/catalogue/R__demo_catalogue.sql`) dùng cho profile `dev` và bản deploy Render; tài khoản và vé demo (`db/seed/R__dev_seed_data.sql`) chỉ cho `dev`.

## Bản đồ tài liệu

| Tài liệu | Nội dung |
|---|---|
| [01](01-overview-and-requirements.md) – [06](06-running-guide.md) | Tổng quan, database, kiến trúc, API, mã nguồn, cách chạy và deploy (theo code hiện tại) |
| [07](07-optimization-team-plan.md) | Kế hoạch Phase 2 ban đầu (giữ nguyên để đối chiếu) |
| [08](08-phase2-results.md) | Kết quả và số liệu đo Phase 2 |
| [09](09-standards-compliance.md) | Đối chiếu tiêu chuẩn và việc còn lại |
| [openapi.json](openapi.json) | Đặc tả OpenAPI xuất từ `/v3/api-docs` |
