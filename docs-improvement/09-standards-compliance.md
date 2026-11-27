# Đối chiếu tiêu chuẩn

Tài liệu đối chiếu hệ thống BusBooking (nhánh `dev`, sau Phase 2 và các thay đổi auth) với các chuẩn được chọn. Mỗi dòng ghi trạng thái và nơi kiểm chứng được trong mã nguồn hoặc test.

Trạng thái: **Đạt** · **Một phần** (đạt cốt lõi, còn giới hạn đã nêu) · **Chưa đạt** (còn việc phải làm, xem mục 7).

| Chuẩn | Dùng cho |
|---|---|
| ISO/IEC 25010 | Khung đánh giá chất lượng tổng thể |
| OWASP ASVS (mức 1–2), OWASP API Security Top 10 (2023) | Bảo mật ứng dụng và API |
| NIST SP 800-63B | Mật khẩu, mã OTP, giới hạn thử |
| RFC 7519, RFC 8725 | JWT |
| RFC 9110, OpenAPI 3 | Ngữ nghĩa HTTP và mô tả API |
| ISTQB (CT-PT), ISO/IEC 25023 | Kiểm thử chức năng và kiểm thử tải |
| Conventional Commits | Lịch sử commit |

## 1. ISO/IEC 25010 — khung chất lượng

| Đặc tính | Trạng thái | Bằng chứng |
|---|---|---|
| Phù hợp chức năng | Đạt | 327 test JUnit, gồm test tích hợp trên PostgreSQL thật (`src/test/java/.../integration`, `.../api`) |
| Hiệu năng | Một phần | SLO và kịch bản tải trong `load-tests/config/acceptance.yaml`, `load-tests/ACCEPTANCE.md`; kết quả trước/sau ở `load-tests/results/phase2-before-after.json`. Chưa có lượt acceptance đầy đủ sau các thay đổi auth |
| Tương thích | Đạt | REST + JSON, mô tả OpenAPI qua springdoc; chạy bằng Docker Compose |
| Tương tác (giao diện) | Một phần | Frontend demo tĩnh (`frontend/`); trọng số thấp theo phạm vi đề tài |
| Độ tin cậy | Đạt | `Idempotency-Key` cho đặt vé (V17), outbox gửi email (V19), ràng buộc chống trùng lịch xe (V18), đối soát ghế sau load test |
| Bảo mật | Một phần | Xem mục 2–4; các điểm còn lại ở mục 7 |
| Khả năng bảo trì | Đạt | Layered + Ports & Adapters (`api` → `business` → `business/port` ← `data`/`security`/`notification`); migration Flyway có phiên bản |
| Linh hoạt (triển khai) | Đạt | Cấu hình qua biến môi trường (`.env.example`), rate limit chọn `local`/`redis`, Actuator chỉ trên cổng loopback |

## 2. OWASP API Security Top 10 (2023)

| Mục | Trạng thái | Bằng chứng |
|---|---|---|
| API1 Broken Object Level Authorization | Đạt | Booking kiểm tra chủ sở hữu (`BookingService`, `ForbiddenOperationException`); test `TripBookingIntegrationTest` |
| API2 Broken Authentication | Đạt | JWT HS256 + kiểm tra DB mỗi request (`CurrentUserLoader`); giới hạn theo IP và theo tài khoản; thu hồi token bằng `token_version` |
| API3 Broken Object Property Level Authorization | Đạt | DTO từ chối trường lạ (`@JsonAnySetter rejectUnknown`); đổi role chỉ qua endpoint SUPER_ADMIN |
| API4 Unrestricted Resource Consumption | Đạt | `PageQuery` tối đa 100 bản ghi/trang; rate limit cho mọi endpoint auth công khai (`AuthRateLimitFilter`) |
| API5 Broken Function Level Authorization | Đạt | Quy tắc theo method + path, mặc định `denyAll` (`SecurityConfig`) |
| API6 Unrestricted Access to Sensitive Business Flows | Một phần | Có giới hạn đăng nhập/OTP; chưa giới hạn số vé mỗi tài khoản (một tài khoản đặt được cả chuyến) |
| API7 SSRF | Không áp dụng | API không gọi URL do người dùng cung cấp |
| API8 Security Misconfiguration | Một phần | CORS chỉ nhận origin cụ thể; Swagger tắt mặc định; Actuator loopback, `show-details=never`; Nginx gửi CSP, `X-Content-Type-Options`, `Referrer-Policy` (`deploy/nginx/nginx-app.conf`), HTTPS + HSTS qua `deploy/compose.tls.yaml`; Compose chỉ publish DB, backend, Mailpit trên loopback. Chứng chỉ TLS do người triển khai cung cấp |
| API9 Improper Inventory Management | Đạt | OpenAPI sinh tự động (springdoc); `docs-improvement/openapi.json` xuất lại từ `/v3/api-docs`, bỏ `/error` nội bộ |
| API10 Unsafe Consumption of APIs | Không áp dụng | Chỉ dùng SMTP, PostgreSQL, Redis nội bộ |

## 3. OWASP ASVS — các nhóm liên quan

| Nhóm | Trạng thái | Bằng chứng |
|---|---|---|
| Xác thực, lưu mật khẩu | Đạt | BCrypt (`BCryptPasswordHasher`); so sánh với dummy hash khi email không tồn tại để không lộ qua thời gian phản hồi (`AuthService.login`) |
| Quản lý phiên/token | Đạt | Logout, đổi mật khẩu và đặt lại mật khẩu đều thu hồi mọi token cũ (V23, `JwtAuthIntegrationTest`, `ProfileAndRolesIntegrationTest`, `PasswordResetIntegrationTest`) |
| Kiểm soát truy cập | Đạt | Như API1/API5 |
| Kiểm tra đầu vào | Đạt | `AuthFieldValidator`, `AuthInputPolicy`, Bean Validation trên DTO |
| Xử lý lỗi | Đạt | Body lỗi chung, không lộ SQL/stack (`GlobalExceptionHandler`); lỗi 500 được ghi log phía server (`event=unexpected_error`) |
| Ghi log bảo mật | Một phần | Log `security.audit`: `login_succeeded`, `login_failed`, `login_throttled`, `logout`, `password_changed`, `password_reset`, `password_reset_failed`; đổi quyền ghi qua logger `RoleChangeAudit`. Tài khoản ghi bằng id hoặc 12 ký tự đầu SHA-256 của email. Log chỉ ra stdout, chưa có lưu trữ tập trung |
| Chống dò tài khoản | Một phần | Resend OTP và quên mật khẩu trả cùng phản hồi; riêng đăng ký trả `409` khi email đã tồn tại |

## 4. NIST SP 800-63B — mật khẩu và OTP

| Yêu cầu | Trạng thái | Bằng chứng |
|---|---|---|
| Tối thiểu 8 ký tự, không ép quy tắc ký tự | Đạt | `AuthInputPolicy.registrationPassword` |
| Cho phép mật khẩu dài | Một phần | Giới hạn 72 byte UTF-8 do BCrypt; đủ 64 ký tự ASCII nhưng ít hơn với ký tự có dấu |
| Chặn mật khẩu phổ biến | Đạt | Danh sách mật khẩu phổ biến trong `AuthInputPolicy`, áp dụng khi đăng ký, đổi và đặt lại mật khẩu; test `AuthInputPolicyTest` |
| Giới hạn số lần thử | Đạt | Theo IP và theo tài khoản (`AUTH_RATE_LOGIN_ACCOUNT_LIMIT`), kể cả endpoint đổi mật khẩu |
| Không bắt đổi mật khẩu định kỳ | Đạt | Không có cơ chế hết hạn mật khẩu |
| OTP: ngẫu nhiên, hạn ngắn, dùng một lần, giới hạn thử | Đạt | 6 số, 10 phút, tối đa 5 lần sai, lưu dạng HMAC, so sánh constant-time (`EmailVerificationRepositoryAdapter`, `PasswordResetRepositoryAdapter`) |
| Xác thực nhiều yếu tố | Chưa đạt | Chỉ mức AAL1 (mật khẩu); xem mục 7 |

## 5. JWT (RFC 7519, RFC 8725) và HTTP (RFC 9110)

| Yêu cầu | Trạng thái | Bằng chứng |
|---|---|---|
| Cố định thuật toán, không chấp nhận `none` | Đạt | Parser chỉ giữ HS256 (`JwtService`) |
| Khóa đủ mạnh | Đạt | `JWT_SECRET` tối thiểu 32 byte, kiểm tra khi khởi động (`JwtProperties`) |
| Kiểm tra `iss`, `exp`, `iat` | Đạt | `requireIssuer`, kiểm tra biên hết hạn chính xác |
| Thu hồi token | Đạt | Claim `ver` so với `users.token_version` |
| Thời hạn token ngắn | Một phần | Mặc định 24 giờ, chưa có refresh token |
| Claim `aud` | Không áp dụng | Một dịch vụ duy nhất phát hành và nhận token |
| Mã trạng thái, `Retry-After`, `Cache-Control: no-store` | Đạt | `201/202/204/409/429/503` theo đúng ngữ nghĩa; `no-store` trên mọi response auth |

## 6. Kiểm thử và quy trình

| Yêu cầu | Trạng thái | Bằng chứng |
|---|---|---|
| Phân loại kiểm thử tải theo ISTQB CT-PT | Đạt | Smoke, read/write/mixed, spike, phục hồi, soak trong `load-tests/ACCEPTANCE.md` |
| Ngưỡng theo percentile và tỉ lệ lỗi | Đạt | p95 đọc ≤ 300 ms, ghi ≤ 500 ms, lỗi ngoài dự kiến ≤ 0,1% (`acceptance.yaml`) |
| CI chạy test | Đạt | `.github/workflows/ci.yml` với PostgreSQL và Redis |
| Conventional Commits | Đạt | Lịch sử từ Phase 2 dùng `<type>(scope): description` |

## 7. Việc còn lại

| # | Việc | Chuẩn liên quan | Mức |
|---|---|---|---|
| 1 | Đăng ký không lộ email đã tồn tại (trả cùng phản hồi, gửi email báo cho chủ tài khoản) | ASVS, API2 | Trung bình |
| 2 | Rút ngắn thời hạn access token, thêm refresh token | RFC 8725, ASVS | Trung bình |
| 3 | ~~Header bảo mật cho Nginx frontend~~ Đã làm: `deploy/nginx/nginx-app.conf`, `deploy/compose.tls.yaml` | API8 | Xong |
| 4 | Giới hạn số vé mỗi tài khoản cho một chuyến | API6 | Cần chốt nghiệp vụ |
| 5 | Đưa log `security.audit` vào kho log tập trung có thời hạn lưu | ASVS (ghi log) | Thấp |
| 6 | ~~Cập nhật `openapi.json`~~ Đã làm: xuất lại từ `/v3/api-docs` | API9 | Xong |
| 7 | Xác thực hai yếu tố cho ADMIN/SUPER_ADMIN | NIST 800-63B (AAL2) | Thấp, ngoài phạm vi hiện tại |
| 8 | Chạy lại acceptance tải sau các thay đổi auth | ISO 25010 (hiệu năng) | Trung bình |
