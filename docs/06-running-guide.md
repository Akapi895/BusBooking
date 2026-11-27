# 6. Hướng dẫn chạy


## 6.1. Các thành phần cần chạy

- **Spring Boot backend:** REST API, mặc định ở `http://localhost:8085` khi chạy local với cấu hình hiện dùng.
- **PostgreSQL:** lưu tài khoản, danh mục, chuyến xe và booking; **Flyway** thực thi/kiểm tra migration khi ứng dụng khởi động.
- **SMTP:** dùng để gửi mã xác thực email (OTP). Có thể dùng **Mailpit** để kiểm tra email trong môi trường phát triển.
- **Swagger/OpenAPI:** thử các endpoint; trong Pha 1 hệ thống có **32 REST API** theo phạm vi đã chốt.

## 6.2. Yêu cầu môi trường

| Công cụ | Yêu cầu / ghi chú |
|---|---|
| Git | Clone source từ GitHub |
| Docker Desktop + Docker Compose | Cách chạy ưu tiên; bật Linux containers |
| JDK 21 | Cần khi build/chạy backend trực tiếp trên Windows |
| Maven | **Không cần cài riêng** nếu dùng Maven Wrapper (`mvnw.cmd`) |
| PostgreSQL | Có thể chạy bằng Docker; không cần cài trên Windows nếu Compose đã cung cấp database |

Kiểm tra nhanh:

```powershell
java -version
.\mvnw.cmd -v
docker version
docker compose version
```

## 6.3. Chuẩn bị cấu hình

1. Clone repository, mở PowerShell ở thư mục `busbooking/`.
2. Kiểm tra `compose.yaml`, `.env.example` và `src/main/resources/application*.properties` trước khi chạy.
3. Nếu Compose sử dụng `.env`, sao chép mẫu và **tự điền các giá trị còn thiếu**, không đưa mật khẩu/secret thật lên GitHub:

   ```powershell
   if (-not (Test-Path .env)) { Copy-Item .env.example .env }
   ```

   Chỉ dùng lệnh này khi `.env.example` có tồn tại; `.env` là cấu hình cá nhân và phải được `.gitignore` loại trừ.
4. Tạo ba secret độc lập. `JWT_SECRET` và `EMAIL_OTP_SECRET` phải là Base64 giải mã ra ít nhất 32 byte. `OTP_OUTBOX_SECRET` phải giải mã ra đúng 32 byte. Dùng cùng giá trị outbox trên mọi instance chung DB và giữ giá trị ổn định qua các lần khởi động khi vẫn còn email chờ gửi.

   | Nhóm | Biến tiêu biểu |
   |---|---|
   | Database | `DB_URL`, `DB_USERNAME`, `DB_PASSWORD` |
   | JWT | `JWT_SECRET`, `JWT_EXPIRATION_MS`, `JWT_ISSUER` |
   | OTP | `EMAIL_OTP_SECRET`, `OTP_OUTBOX_SECRET` |
   | SMTP | `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`, `SMTP_AUTH`, `SMTP_STARTTLS` |
   | Docs / môi trường | `SPRING_PROFILES_ACTIVE`, `API_DOCS_ENABLED` |

   **Chú ý:** `.env.example` hiện ghi DB ở `5433/busbooking`, khác Compose (`5435/busbooking_dev_fresh`); dùng đúng URL của môi trường thực tế. Spring Boot chạy **trực tiếp bằng Maven không tự đọc `.env`**; Compose chỉ chuyển các biến đã khai báo trong `environment` vào backend, không tự chuyển mọi biến trong `.env`.

## 6.4. Cách 1: Chạy bằng Docker Compose (khuyến nghị)

**Bước 1.** Kiểm tra Compose hợp lệ và xem tên service thực tế: `compose.yaml` có `postgres`, `backend`, `mailpit`; PostgreSQL publish `127.0.0.1:5435:5432`, backend `127.0.0.1:8086:8085`, Mailpit UI `127.0.0.1:8026:8025` (chỉ máy host truy cập được; máy khác vào qua Nginx cổng 5173); SMTP 1025 chỉ dùng trong Docker network. Mặc định chạy profile `dev` (dữ liệu demo, Swagger); trên máy người khác truy cập được, đặt `SPRING_PROFILES_ACTIVE=prod` trong `.env`.

```powershell
docker compose config --quiet
docker compose config --services
```

Nếu repository chưa có `compose.yaml` hoặc lệnh kiểm tra báo lỗi, **không tiếp tục với lệnh khởi chạy**; kiểm tra lại bản bàn giao và cấu hình cần thiết.

**Bước 2.** Build và khởi động các service. Compose cấu hình Mailpit làm SMTP cho backend. Khi nâng cấp DB cũ, chạy truy vấn kiểm tra lịch xe trùng trước khi Flyway áp dụng V18. Xem [Thiết kế database](02-database-design.md#26-migration-phase-2).

```powershell
docker compose up -d --build
docker compose ps
```

**Bước 3.** Xem log khởi động để kiểm tra kết nối database và Flyway:

```powershell
docker compose logs --tail=100
docker compose logs -f
```

Thoát chế độ xem log bằng `Ctrl+C` (không dừng container).

**Bước 4.** Mở Swagger tại `http://localhost:8086/swagger-ui/index.html` và Mailpit UI tại `http://localhost:8026`. Gửi yêu cầu đăng ký, đợi email xuất hiện trong Mailpit rồi dùng OTP để xác minh.

**Dừng hệ thống** (không xóa database volume):

```powershell
docker compose down
```

**Dùng chung quota xác thực qua Redis.** Khởi chạy Compose với tệp bổ sung:

```powershell
docker compose -f compose.yaml -f compose.auth-rate-limit.yaml up -d --build
```

Redis chạy trên mạng riêng của Compose. Backend mặc định dùng bộ đếm local, còn tệp bổ sung bật `AUTH_RATE_LIMIT_BACKEND=redis`. Khi triển khai nhiều backend, dùng chung Redis, `AUTH_RATE_REDIS_PREFIX` và các giá trị quota. Có thể cấu hình kết nối Redis ngoài Compose bằng các biến `SPRING_DATA_REDIS_*`.

Nginx ghi `X-Forwarded-For` từ kết nối trực tiếp. Cấu hình Compose tin địa chỉ proxy `172.31.241.2`. Khi triển khai ở mạng khác, dùng địa chỉ chính xác của proxy tin cậy và cấu hình proxy ghi đè header do client gửi.

**Triển khai trên máy người khác truy cập được.** Trong `.env` đặt thêm:

- `SPRING_PROFILES_ACTIVE=prod`: không nạp dữ liệu demo (tài khoản `admin@busbooking.local` có mật khẩu công khai), tắt Swagger.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_AUTH=true`, `SMTP_STARTTLS=true`, `SMTP_FROM`: nhà cung cấp email thật; mặc định gửi vào Mailpit.

Bật HTTPS bằng cách đặt chứng chỉ của tên miền vào `certs/fullchain.pem` và `certs/privkey.pem` (ví dụ từ Let's Encrypt; thư mục `certs/` không được commit), rồi chạy:

```powershell
docker compose -f compose.yaml -f compose.tls.yaml up -d --build
```

Nginx khi đó nghe cổng 443, cổng 80 chỉ chuyển hướng sang HTTPS, và gửi HSTS. Mọi cấu hình Nginx đều gửi CSP, `X-Content-Type-Options` và `Referrer-Policy`.

**Deploy lên Render + Neon (miễn phí).** `render.yaml` mô tả backend (Docker, gói free, profile `prod`) và frontend (static site, rewrite `/api/*` sang backend để trình duyệt vẫn gọi cùng origin). Database dùng Neon, email dùng Brevo.

1. **Neon:** tạo project (region Singapore) và lấy chuỗi kết nối của endpoint **direct**, không phải *pooled*, vì pooler bỏ các lệnh `SET lock_timeout`/`SET TIME ZONE` mà Hikari chạy cho mỗi kết nối. Đổi sang dạng JDBC: `jdbc:postgresql://<host>/<db>?sslmode=require`.
2. **Brevo:** xác minh địa chỉ gửi, tạo SMTP key. Render free chặn cổng 25/465/587 nên `render.yaml` dùng cổng 2525.
3. **Render:** New → Blueprint → chọn repo, nhánh. Nhập các giá trị `sync: false`: `DB_URL`, `DB_USERNAME`, `DB_PASSWORD`, `SMTP_USERNAME` (login SMTP của Brevo), `SMTP_PASSWORD` (SMTP key), `SMTP_FROM`. Ba secret JWT/OTP do Render tự sinh.
4. Nếu Render đặt URL khác `busbooking-api.onrender.com` / `busbooking-web.onrender.com` (tên đã có người dùng), sửa `CORS_ALLOWED_ORIGINS` và rule rewrite `/api/*` trong `render.yaml` cho khớp.
5. **Tài khoản quản trị:** profile `prod` không nạp dữ liệu demo và không cho bootstrap SUPER_ADMIN. Đăng ký và xác minh email một tài khoản qua giao diện, rồi nâng quyền một lần trong SQL Editor của Neon: `UPDATE users SET role_id = (SELECT id FROM roles WHERE name = 'SUPER_ADMIN') WHERE email = '<email>';` (chỉ được có một SUPER_ADMIN; sau đó dùng màn quản trị để cấp ADMIN cho người khác).

Giới hạn của gói free:

- Backend ngủ sau 15 phút không có request. Đo local với `--cpus 0.1 --memory 512m`: khởi động mất khoảng 6–7 phút (lần đầu kèm migration khoảng 7 phút), RAM khoảng 375 MB. Render có thể cấp CPU nhanh hơn mức giới hạn cứng này, nhưng nên mở trang trước buổi demo vài phút. Email OTP trong outbox chỉ được gửi khi backend đang thức.
- Rate limit theo IP đọc `X-Forwarded-For` (`SERVER_FORWARD_HEADERS_STRATEGY=native`) và chỉ tin proxy trong dải địa chỉ nội bộ. Sau khi deploy, thử đăng nhập sai từ hai mạng khác nhau: nếu mạng thứ hai cũng bị `429` ngay thì proxy của Render nằm ngoài dải đó.

> **Không dùng `docker compose down -v`** khi muốn giữ dữ liệu. Compose hiện có backend service; khi dùng cách 2 để chạy Java local, dừng backend Compose nếu đang chạy (`docker compose stop backend`), chỉ khởi động `postgres` và dùng SMTP truy cập được từ host theo mục 6.5.

## 6.5. Cách 2: Chạy Spring Boot trực tiếp trên Windows

Dùng cách này khi cần debug backend bằng VS Code/IntelliJ hoặc khi Compose chỉ chạy các dịch vụ phụ trợ.

**Bước 1.** Khởi động PostgreSQL (có thể dùng `docker compose up -d postgres`) và SMTP thử nghiệm trước; kiểm tra host/port đang publish:

```powershell
docker ps
```

Mailpit trong Compose không publish SMTP 1025 ra host, nên backend local không dùng được cổng đó của service này. Có thể chạy **một container Mailpit riêng** cho backend local, miễn là cổng 1025/8025 chưa bị chiếm:

```powershell
docker run -d --name busbooking-auth-mailpit `
  -p 127.0.0.1:1025:1025 `
  -p 127.0.0.1:8025:8025 `
  axllent/mailpit:v1.27.8
```

Mailpit UI: `http://localhost:8025`. Nếu container đã tồn tại, dùng `docker start busbooking-auth-mailpit` thay vì `docker run` lần nữa.

**Bước 2.** Khai báo biến môi trường cho tiến trình PowerShell. Ví dụ dưới dùng PostgreSQL của `compose.yaml` tại `5435/busbooking_dev_fresh`; nếu tự tạo database khác, thay cả cổng và tên DB theo môi trường thực tế. Cung cấp mật khẩu/secret **của môi trường phát triển**, không đưa chúng vào source code:

```powershell
$env:SPRING_PROFILES_ACTIVE = "dev"
$env:DB_URL = "jdbc:postgresql://localhost:5435/busbooking_dev_fresh"
$env:DB_USERNAME = "busbooking_user"
$env:DB_PASSWORD = Read-Host "Mật khẩu PostgreSQL dev"

# Tạo ba secret độc lập dùng trong phiên demo.
# Giữ giá trị ổn định qua các lần khởi động.
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
$jwtBytes = New-Object byte[] 32
$otpBytes = New-Object byte[] 32
$outboxBytes = New-Object byte[] 32
$rng.GetBytes($jwtBytes)
$rng.GetBytes($otpBytes)
$rng.GetBytes($outboxBytes)
$env:JWT_SECRET = [Convert]::ToBase64String($jwtBytes)
$env:EMAIL_OTP_SECRET = [Convert]::ToBase64String($otpBytes)
$env:OTP_OUTBOX_SECRET = [Convert]::ToBase64String($outboxBytes)
$rng.Dispose()
$env:JWT_ISSUER = "busbooking"
$env:JWT_EXPIRATION_MS = "86400000"

$env:SMTP_HOST = "127.0.0.1"
$env:SMTP_PORT = "1025"
$env:SMTP_AUTH = "false"
$env:SMTP_STARTTLS = "false"
$env:SMTP_FROM = "noreply@example.com"
$env:API_DOCS_ENABLED = "true"
$env:BOOTSTRAP_SUPER_ADMIN_ENABLED = "false"
```

**Bước 3.** Build và chạy. Với DB mới chưa có quản trị viên, trước khi chạy hãy đặt `$env:BOOTSTRAP_SUPER_ADMIN_ENABLED = "true"` thay giá trị `false` ở trên và khai báo `BOOTSTRAP_SUPER_ADMIN_EMAIL`, `BOOTSTRAP_SUPER_ADMIN_PASSWORD`, `BOOTSTRAP_SUPER_ADMIN_FULL_NAME`, `BOOTSTRAP_SUPER_ADMIN_PHONE` trong cùng phiên PowerShell. Bootstrap chỉ cho profile `dev`/`test`, tạo tài khoản mới chưa xác minh, không nâng quyền/reset tài khoản cũ hoặc thay SUPER_ADMIN khác. Xác minh OTP qua Mailpit trước khi login; sau khởi tạo đặt lại flag `false`. Compose hiện cố định flag `false` và chưa chuyển bốn biến tài khoản, nên quy trình này áp dụng cho backend local:

```powershell
.\mvnw.cmd -DskipTests clean package
.\mvnw.cmd spring-boot:run '-Dspring-boot.run.jvmArguments=-Duser.timezone=Asia/Ho_Chi_Minh'
```

Ứng dụng sử dụng cấu hình `dev` trong phiên PowerShell trên. Khi chạy bằng IDE, cần khai báo **cùng các biến môi trường** trong Run Configuration. Nếu PostgreSQL/SMTP chạy **trong container** và backend cũng chạy **trong container**, không dùng `localhost` để kết nối container khác; thay bằng hostname/service tương ứng của Docker network.

## 6.6. Kiểm tra sau khi khởi chạy

Với backend local cổng 8085 hoặc Compose publish 8086, khi tài liệu API được bật:

| Thành phần | URL |
|---|---|
| Swagger UI | http://localhost:8085/swagger-ui/index.html (local); http://localhost:8086/swagger-ui/index.html (Compose) |
| OpenAPI JSON | http://localhost:8085/v3/api-docs (local); http://localhost:8086/v3/api-docs (Compose) |
| Base API | http://localhost:8085/api (local); http://localhost:8086/api (Compose) |
| Mailpit (nếu có) | http://localhost:8025 (container riêng cho local); http://localhost:8026 (Compose) |
| Actuator health | http://127.0.0.1:8081/actuator/health (local); http://127.0.0.1:8087/actuator/health (Compose) |
| Metric pool DB | http://127.0.0.1:8081/actuator/metrics/hikaricp.connections.active (local); cổng 8087 với Compose. Xem thêm `hikaricp.connections.pending`, `.max`, `.idle`, `.acquire` |

Actuator chạy trên cổng quản trị riêng (`MANAGEMENT_PORT`, mặc định 8081) và chỉ nghe `127.0.0.1` (`MANAGEMENT_ADDRESS`); cổng API 8085/8086 không phục vụ `/actuator`. Chỉ mở `health`, `metrics` và `prometheus` (bản scrape cho Prometheus); health không hiện chi tiết và không tính SMTP. Khi dùng Redis cho rate limit, đặt `MANAGEMENT_HEALTH_REDIS=true` để health phản ánh Redis.

**Prometheus và Grafana.** Ghép `compose.observability.yaml` để thu metric của mọi backend (tìm theo DNS tên dịch vụ `backend`), PostgreSQL qua `postgres_exporter` (gồm số lock đang chờ) và bật `log_lock_waits`:

```powershell
docker compose -f compose.yaml -f compose.observability.yaml up -d
```

Prometheus ở http://127.0.0.1:9090, Grafana ở http://127.0.0.1:3000 (dashboard `BusBooking`, xem không cần đăng nhập, chỉ nghe loopback): request/s và mã phản hồi, p95/p99 theo endpoint, request/s theo instance, kết nối Hikari đang chờ/đang dùng, lock PostgreSQL đang chờ, heap JVM.

**Chạy nhiều backend sau Nginx.** `compose.scale.yaml` bỏ tên container và cổng publish của backend để chạy nhiều replica; frontend Nginx chia request cho mọi replica, rate limit auth dùng chung qua Redis:

```powershell
docker compose -f compose.yaml -f compose.auth-rate-limit.yaml -f compose.scale.yaml -f compose.observability.yaml up -d --scale backend=3
```

Nginx chỉ phân giải tên `backend` lúc khởi động, nên đổi số replica xong phải restart service `frontend`. Truy cập API qua http://localhost:5173/api.

Kiểm tra HTTP và xuất đặc tả API từ **ứng dụng đang chạy**:

```powershell
Invoke-WebRequest http://localhost:8085/v3/api-docs `
  -OutFile docs/openapi.json
```

Swagger có thể bị tắt ngoài profile `dev`/`test` nếu chưa bật `API_DOCS_ENABLED`; **404 từ Swagger không đồng nghĩa backend bị lỗi**.

**Luồng kiểm tra chức năng tối thiểu:**

1. `POST /api/auth/register` — đăng ký một email thử nghiệm; chưa nhận JWT.
2. Mở Mailpit hoặc hộp thư đã cấu hình để lấy OTP; gọi `POST /api/auth/verify-email`.
3. `POST /api/auth/login` — nhận JWT, dùng Swagger **Authorize** với Bearer token.
4. `GET /api/auth/me`, `GET /api/locations`, `GET /api/trips` — kiểm tra xác thực và dữ liệu công khai.
5. `POST /api/bookings` — giữ ghế cho chuyến còn chỗ (vé `HELD`, giữ 10 phút theo `BOOKING_HOLD_MINUTES`); `POST /api/bookings/{id}/confirm` để xác nhận trước hạn, quá hạn thì vé thành `EXPIRED` và ghế được trả lại; kiểm tra xem/hủy booking theo quyền.
6. Dùng tài khoản có quyền phù hợp để thử API quản trị; `USER` không được truy cập endpoint chỉ dành cho `ADMIN`/`SUPER_ADMIN`.

Chi tiết request/response, quyền và 32 endpoint: [`04-api-design.md`](04-api-design.md). `docs/openapi.json` hiện còn lỗi response/validation và chứa `/error` nội bộ; chỉ xuất lại JSON không bảo đảm các lỗi đặc tả đã được sửa.

## 6.7. Kiểm thử và benchmark

```powershell
# Chạy các bài kiểm thử Maven; cần môi trường test và database test độc lập
.\mvnw.cmd test

# Build JAR để đóng gói/bàn giao
.\mvnw.cmd -DskipTests clean package
```

**Không trỏ integration test vào database development có dữ liệu cần giữ.** Kiểm tra `application-test.properties`, `TEST_DB_URL` và các biến liên quan trước khi chạy test. Lệnh `test` mặc định chưa bao gồm các class `*SmokeIT`; có thể chạy riêng bằng `.\mvnw.cmd "-Dtest=AuthLiveHttpSmokeIT,SuperAdminLiveHttpSmokeIT,SmtpMailpitSmokeIT" test` khi database test và Mailpit sẵn sàng. Kết quả build/test mới nhất chưa được xác minh trong lần đối chiếu tài liệu.

Baseline hiệu năng GET Trip / POST Booking Pha 1 trên Kaggle CPU, script Locust, dữ liệu giả lập và kết quả nằm ở [`../load-tests/`](../load-tests/). Bài benchmark Kaggle chạy Java + PostgreSQL + Locust trong notebook, **không yêu cầu Docker bên trong Kaggle**.

## 6.8. Xử lý lỗi thường gặp

| Hiện tượng | Kiểm tra / xử lý |
|---|---|
| `Connection refused` PostgreSQL | `docker compose ps` hoặc `docker ps`; kiểm tra đúng **cổng host**, database, user, password và network |
| Flyway checksum mismatch / missing table | Đối chiếu migration V1–V22 với lịch sử DB. |
| PostgreSQL từ chối múi giờ `Asia/Saigon` | Đặt JVM option `-Duser.timezone=Asia/Ho_Chi_Minh` khi chạy từ IDE hoặc JAR trực tiếp. |
| Backend không lên vì JWT/OTP secret | Kiểm tra ba secret Base64 độc lập. JWT và HMAC OTP cần ít nhất 32 byte, còn khóa outbox cần đúng 32 byte sau giải mã. |
| Không nhận OTP | Kiểm tra SMTP, Mailpit và log worker. Khi chạy backend trên host, dùng cổng SMTP publish ra host. Worker thử lại với giãn cách tăng dần, tối đa 8 lần trong thời hạn OTP. |
| Swagger trả 404 | Kiểm tra profile `dev`, `API_DOCS_ENABLED` và cổng publish backend |
| HTTP `401` / `403` | Kiểm tra JWT, trạng thái xác minh email, role và ownership; đây có thể là phản hồi phân quyền đúng |
| HTTP `429` khi thử auth | Rate limit đăng ký/đăng nhập/OTP; chờ hết cửa sổ giới hạn thay vì gọi liên tục |
| HTTP `503` ở endpoint auth khi bật Redis | Kiểm tra kết nối Redis. Auth trả `Retry-After` trong khi chưa xác định được quota. |
| Port 8085/8086/5435/1025/8025/8026 bị chiếm | Dùng `docker ps`, `Get-NetTCPConnection -State Listen`; điều chỉnh cổng phù hợp trong cấu hình |
| Chạy Java trong container không kết nối được DB | JDBC URL không được dùng `localhost` để chỉ container PostgreSQL khác; dùng tên service/network thực tế |


### Kiểm tra Flyway từ V16

Chạy riêng bằng mvn -B -Dtest=FlywayUpgradeIntegrationTest test, hoặc chạy mvn -B verify như CI.
Dùng PostgreSQL 16 dành riêng cho kiểm thử. Tài khoản TEST_DB_USERNAME cần quyền CREATEDB để suite tạo và dọn các DB kiểm thử riêng trong cùng cụm.
Suite kiểm tra cài schema trên DB trống, nâng cấp dữ liệu V16 và xác nhận chạy lại migration không làm mất dữ liệu.
