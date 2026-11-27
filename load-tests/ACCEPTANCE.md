# Nghiệm thu kiến trúc BusBooking trên Kaggle

## 1. Upload và Run All

Notebook mới: **`notebook/busbooking-architecture-acceptance.ipynb`**. Notebook `busbooking-kaggle-cpu-test.ipynb` và kết quả ngày 27/10 là baseline lịch sử, không bị ghi đè.

Cách chuẩn bị một bộ upload sạch, từ repository root:

```powershell
python -B load-tests/scripts/package_kaggle.py --jar "DUONG_DAN_JAR_THUC_THI.jar"
```

Lệnh tạo `load-tests/local-runs/busbooking-kaggle-kit.zip`: chứa harness, config, tests, notebook và JAR đã chọn. Không đưa `.validation/`, DB dump, dependency cache hoặc kết quả lịch sử vào kit. Packager kiểm tra đúng entrypoint BusBooking và ghi hash từng file; không build/sửa JAR.

1. Upload kit thành **Private Kaggle Dataset**. Có thể upload folder đã giải nén, hoặc giữ file ZIP tên `busbooking-kaggle-kit.zip`.
2. Import notebook mới; chọn **Accelerator=None (CPU)**, **Internet=On**, Add Input dataset đó.
3. Chạy trên kernel mới bằng **Run All**. Notebook mặc định `MODE = 'smoke'` để kiểm tra nhanh trước; không cần `.env`, secret hay PostgreSQL/Mailpit bên ngoài.
4. Notebook tự tìm harness/JAR; nếu có nhiều bản, điền `SOURCE_OVERRIDE`/`JAR_OVERRIDE`. Nó không tự đoán chọn một version.
5. Cuối lượt tải ZIP kết quả từ link ở cell cuối hoặc Kaggle Output. Mỗi lượt có thư mục riêng.

Nếu không đóng gói JAR trong kit, Add Input thêm một dataset chứa JAR Spring Boot thực thi; không dùng `.jar.original`. Không upload source backend để chạy suite: schema do Flyway trong JAR tạo.

### Chạy thử tối giản trước: `MODE = 'smoke'`

Giữ `MODE = 'smoke'` và `OVERRIDES = {}` trong cell đầu rồi Run All. Bộ chạy thực hiện tuần tự:

1. Khởi động PostgreSQL + Mailpit + JAR, seed chỉ **5 tài khoản performance và 100 chuyến**.
2. Đăng ký → nhận OTP Mailpit → verify → login; CRUD catalog/chuyến → đặt vé → xem → hủy.
3. Chạy lần lượt **read, write, mixed**, mỗi lượt **1 VU / 1 worker / 5 giây đo**, có warm-up ngắn và drain; sau đó một lượt **tải mở 2 req/s** để kiểm tra đường chạy open-model.
4. Đối soát DB, dừng các dịch vụ thuộc lượt chạy và xuất REPORT/JSON/CSV/metrics/ZIP như đường chạy chính.

Không chạy tìm ngưỡng, concurrency, fault injection, JFR hay soak trong smoke. Khi hoàn tất phải thấy **`SMOKE_PASS` và exit code 0**. Đây chỉ là xác nhận full flow của bộ kiểm thử chạy được, không phải nghiệm thu hiệu năng/kiến trúc. Lần đầu cài dependencies/tải JDK có thể chiếm phần lớn thời gian; các API và lượt tải của smoke là ngắn.

Sau smoke thành công, đổi thành **`MODE = 'acceptance'`** rồi chạy lại từ cell đầu để có `RUN` mới. Không tái dùng thư mục kết quả smoke cho acceptance.

### Lỗi Kaggle `venv ... ensurepip ... exit status 1`

Bootstrap mới tạo venv bằng **`with_pip=False`**, nên không gọi `ensurepip` của Python hệ thống. Nó dùng `pip --python <venv-python>` để cài đúng vào venv; nếu pip host thiếu/quá cũ, tải bootstrap pip chính thức và chạy bằng Python của venv. Không cài dependency harness vào kernel và không cần `apt install python3.13-venv`.

Cập nhật dataset bằng kit mới và import notebook mới trước khi chạy lại; cell trong notebook cũ vẫn còn lệnh tạo venv gây lỗi. Có thể dùng kernel mới cho lượt smoke. Bootstrap cũng hỗ trợ chạy lại trên venv còn dở do ensurepip trước đó thất bại.

### Warning `sitecustomize / wrapt` và APT `main/source/Sources`

- `Error in sitecustomize ... No module named 'wrapt'` là Python startup hook không import được `wrapt`. Requirements đã bổ sung `wrapt==2.0.1` trong venv và kiểm tra import bằng tiến trình mới. Một warning ở bước bootstrap **trước khi dependency được cài** vẫn có thể xuất hiện; nếu tiếp tục xuất hiện sau cài đặt, cần xem đường dẫn `sitecustomize`/interpreter từ traceback thay vì cài mù vào kernel.
- Warning APT về repo r2u thiếu `main/source/Sources` là index **source package**, không phải PostgreSQL hay lỗi dữ liệu. Suite chỉ cần binary package, nên lệnh `apt-get update` vô hiệu hóa target deb-src Sources cho riêng lần gọi đó; không sửa/xóa cấu hình repo của Kaggle.
- `SMOKE_PASS`, `cleanup_status: PASS`, `fatal: null` xác nhận smoke đã kết thúc đúng. `missing_cases`, endpoint coverage `UNKNOWN`, capacity `NOT_MEASURED`, recovery/endurance `NOT_REQUESTED` là phần nghiệm thu đầy đủ chưa được yêu cầu, không phải smoke chạy thiếu do lỗi. Đổi MODE sang acceptance và chạy lại từ đầu với RUN mới.

## 2. Phạm vi thực thi và baseline bất biến

- Chỉ chạy **JAR được upload**, không biên dịch, sửa service/controller, tạo index, thay pool, bỏ khóa, tắt constraint hoặc đổi rate limit.
- Tạo một **PostgreSQL cluster mới**, chỉ bind loopback, DB/user ngẫu nhiên. Không kết nối DB dev/test có sẵn. App dùng profile `dev`, heap `-Xms256m -Xmx1024m`, timezone UTC giống notebook lịch sử. Ghi nhận phiên bản Java/PostgreSQL và cấu hình DB thực tế; không mặc định chúng giống môi trường sản xuất.
- **Tách CPU** (`runtime.cpu_split`, mặc định bật, chỉ Linux): Java, PostgreSQL và Mailpit được ghim vào nửa đầu số CPU; harness và mọi tiến trình Locust ở nửa còn lại. Như vậy máy phát tải không giành CPU của backend. RAM, đĩa và cache vẫn dùng chung. Phân chia thực tế được ghi trong `environment.json` (`cpu_split`).
- Mailpit thuộc suite, bind `127.0.0.1:1025/8025`. Runtime cung cấp JWT secret, OTP HMAC secret và outbox secret độc lập cho JAR của mỗi lượt chạy.
- Các biến Spring/DB/JWT/auth thừa kế được loại khỏi tiến trình app. Hai secret được tạo độc lập cho lượt chạy; không lưu secret/token vào báo cáo.
- Tài khoản performance được seed SQL và dùng JWT fixture đúng HS256/sub/iss/iat/exp. JWT vẫn đi qua filter và DB role/active/verified như request thật. Luồng register → email OTP → verify → login được test qua HTTP riêng; không giả vờ rằng seed đã kiểm thử login.
- SQL chỉ chuẩn bị fixture/đối soát và tạo lịch cạnh tranh trên dữ liệu test. Không thay schema/constraint để ép ứng dụng pass.
- Mỗi case chức năng và mỗi trial tải độc lập bắt đầu từ cùng DB snapshot và app được khởi động lại. Spike giữ nguyên trạng thái giữa low/peak/recovery. Probe phục hồi sau quá tải chạy **trước khi restart/restore**.

## 3. Các tiêu chí tự động chạy

| Nhóm | Bằng chứng kiểm tra |
|---|---|
| Architecture | Đọc constant pool class trong JAR để phát hiện business tham chiếu API/data/security/notification/JPA/Servlet; không load target class |
| Schema | Flyway migrate DB rỗng, checksum/version migration trong manifest, Hibernate validate khi app khởi động |
| API | Quan sát thành công toàn bộ 38 method–path của controller hiện tại; CRUD catalog/trip, profile, auth (đổi/đặt lại mật khẩu, logout), booking, hoàn tiền và đổi role |
| Business | Lọc ngày/tuyến, dữ liệu rỗng/sai, giá × quantity, history, ownership, hủy booking/hủy chuyến đúng chính sách hiện tại |
| Security | Thiếu token/sai role trên admin surface, USER-only booking/history, role đổi có hiệu lực với token cũ, inactive bị từ chối, profile không tự nâng role |
| Rate limit | Giữ nguyên default: 10 login sai rồi request thứ 11 nhận 429; không tăng giới hạn để làm đẹp baseline |
| Concurrency | 100 vòng với các burst 2/10/50/100 request tranh 1/2/10 ghế; hoàn ghế một lần; tạo/hủy; booking–hủy chuyến/đổi xe; assignment–vô hiệu hóa route/vehicle |
| Unique/update | Tạo trùng location/operator/vehicle/route; đăng ký trùng email; cập nhật profile nguyên tử theo chính sách last-writer-wins hiện có |
| OTP | Verify một lần, resend nguyên tử/cooldown, 5 lần sai khóa mã, mã hết hạn trong lúc chờ account lock |
| Rollback | Delete user fixture chưa commit → HTTP booking chờ FK → commit delete → lỗi lưu booking; kiểm tra không mất ghế, không có booking |
| Timeout/retry | Giữ trip lock để client timeout, quan sát commit, rồi retry với cùng key. Xác nhận cùng booking ID và từ chối khi đổi payload. |
| SMTP/DB faults | Dừng và khôi phục Mailpit và PostgreSQL của suite. Worker gửi lại OTP đã xếp hàng. Kiểm tra phản hồi quá tải khi giữ khóa và khả năng phục hồi sau DB restart. |
| DB chậm/lock | Giữ root trip lock, phát 50 booking qua HTTP, quan sát nhiều DB waiters và hoàn tất sau release; không đoán kích thước/occupancy pool |
| Performance | Read/write/mixed/hotspot, tìm thô → refine → probe cao hơn → xác nhận hai đầu tối thiểu 3 lần; diagnostic JFR riêng |
| Endurance | Spike low→peak→low trong một tiến trình; kiểm tra target VU thực đạt; soak 1 giờ ở 65% mức low đã xác nhận |
| Data | Ghế không âm/vượt capacity; ghế + vé CONFIRMED = capacity; chuyến đã hủy không còn vé CONFIRMED; tiền đúng; ID/owner của booking đã ACK tồn tại trong DB |

Hủy chuyến có vé CONFIRMED thành công: vé chuyển sang `REFUND_PENDING`, ghế được trả lại, khách nhận email và admin đánh dấu `REFUNDED`. Hủy booking lặp lại trả `200` và chỉ hoàn ghế một lần. Đổi mật khẩu, đặt lại mật khẩu và logout thu hồi mọi token cũ. Yêu cầu gửi lại OTP trả **202** và xác minh thành công trả **204**. Khi kiểm thử hotspot, `409 INSUFFICIENT_SEATS` và `503 SERVICE_UNAVAILABLE` kèm `Retry-After` được đếm là từ chối dự kiến. Các workload thông thường vẫn tính `503` vào tỷ lệ lỗi. Mỗi JVM chỉ xử lý tối đa 8 booking cùng lúc (`booking.max-in-flight-total`), nên ngưỡng `write`/`mixed` thường dừng ở giới hạn này: đó là kết quả cần báo cáo, không phải lỗi harness.

## 4. Tìm vùng chịu tải không có trần VU cố định

Chỉnh các tham số của **harness** trong `config/acceptance.yaml`, hoặc `OVERRIDES` của notebook. Mỗi cấu hình khác nhau là một thí nghiệm khác; config đầy đủ được lưu trong kết quả.

- Bắt đầu 20 VU; mức sau tăng khoảng ×1,6 cho tới khi vi phạm SLO/lỗi.
- Refine giữa mức đạt và mức không đạt đến khoảng sai số 5%.
- Chạy thêm hai probe tăng 10% vượt bound: có thể đi qua 2.000, 2.100 và cao hơn. Nếu probe cao hơn lại PASS, bound cũ bị vô hiệu hóa; tiếp tục khám phá và ghi nhận không đơn điệu, không công bố ngưỡng xác nhận giả.
- Xác nhận luân phiên low/high ít nhất 3 lần. Không truyền một VU cap ngầm vào scheduler.
- Mỗi trial đợi đủ VU thực tế. Discovery warm-up 60 giây, settle 30 giây, đo 120 giây; confirmation warm-up 180 giây, settle 30 giây, đo 300 giây. Discovery là thăm dò; chỉ các confirmation lặp mới chốt bound. Think time cố định 0,2–0,6 giây.
- Có ngân sách discovery/workload/tổng để không vượt phiên Kaggle. Ngân sách hết, generator bão hòa hoặc fixture hết nghĩa là **chưa tìm xong giới hạn**, không phải backend đã đạt công suất tối đa.
- Spike/soak chỉ được neo vào một mức low đã xác nhận. Không có mức đó thì ghi UNKNOWN thay vì chọn đại 400 VU.

**SLO khởi đầu:** mỗi endpoint GET p95 ≤300 ms; ghi p95 ≤500 ms; lỗi ngoài dự kiến ≤0,1%; mọi vi phạm dữ liệu/response contract đều fail. Đây là tiêu chí cấu hình của thí nghiệm, không phải một SLA đã được khách hàng chấp thuận.

### Workload

- `read`: 55% list có lọc origin/destination/date; 35% detail nhiều ID; 5% list không lọc; 5% location. Ghi riêng endpoint/filtered và kích thước response. List phân trang mặc định 20 chuyến; harness kiểm tra mỗi trang không vượt 20.
- `write`: tạo booking quantity=1 trên các trip/slot phân vùng riêng giữa worker. Mọi 409 là ngoài dự kiến khi còn slot.
- `mixed`: 65% nhánh đọc ở trên, 20% đặt, 10% history, 5% hủy booking của chính VU; nếu VU chưa có booking để hủy thì đọc. Báo cáo số request thực tế, không coi trọng số là tỷ lệ thực đo chính xác.
- `hotspot`: worker cố ý dùng chung các trip; mỗi nhóm khoảng 100 lượt chuyển sang trip tiếp theo. Chỉ 409 `INSUFFICIENT_SEATS` là từ chối dự kiến. Báo cáo riêng throughput thành công và throughput từ chối, không gọi mọi request là vé bán được.

**Mô hình tải:** việc tìm ngưỡng dùng mô hình đóng (closed-loop): mỗi VU chờ phản hồi rồi mới gửi tiếp, nên khi hệ thống chậm thì tải gửi vào cũng giảm. Hiện tượng này gọi là *coordinated omission*: độ trễ đo được trông tốt hơn thực tế. Không thể suy ra số người dùng toàn hệ thống chỉ từ VU.

**Tải mở cho đặt vé** (`open-write`, chạy sau khi tìm ngưỡng xong), theo cách *constant-arrival-rate* của k6:

- Mỗi VU giữ một lịch cố định: gửi đúng một booking mỗi `open_pacing_seconds` (mặc định 2 giây), pha ngẫu nhiên, không phụ thuộc thời gian phản hồi. Tốc độ mục tiêu = số VU / pacing.
- Các mức tải = `open_rate_fractions` (0,5; 0,8; 1,0; 1,2) × throughput đặt vé thành công đã xác nhận lặp ở mô hình đóng. Không có mức xác nhận thì ghi UNKNOWN, không tự chọn.
- Một lượt gửi bắt đầu trễ hơn lịch quá `generator_max_lag_ms` được đếm là **late arrival**: phản hồi trước đó đã vượt quá pacing nên tốc độ mục tiêu không được phục vụ. Late arrival vượt `max_unexpected_error_ratio` là `SLO_BREACH`. Vì vậy độ trễ của một mức PASS không bị coordinated omission.
- Kết quả: `open-model.json` và bảng "Open model" trong REPORT (mục tiêu, tốc độ gửi thực, thành công, p95/p99, late arrivals).
- Không dùng `constant_pacing` của Locust: nó tính nhịp từ lúc tạo user, mà Locust tạo user theo lô, khiến nhiều user bắn cùng lúc. Lần chạy thử trên Windows với `constant_pacing` cho 15–36% `503` sai ở 10–40 req/s; với lịch riêng thì 0 lỗi, p95 14–16 ms ở 20/40/80 req/s.

**Độ ổn định giữa các lượt:** mỗi mức xác nhận ghi trung vị, min, max và độ lệch chuẩn tương đối (RSD) của throughput thành công và p95 qua các lần lặp (`searches.json` → `variability`). RSD throughput ở mức low vượt `max_rsd_pct` (10%) thì đánh dấu `stable: false` trong báo cáo: không gộp các lần lặp dao động mạnh thành một con số.

**Độ trễ event loop của generator:** một greenlet riêng nhịp 50 ms đo mỗi giây lần bị chặn lâu nhất. Cách này bắt được cả lần chặn do chính vòng giám sát ghi file, thay vì chỉ đo lượt ngủ 1 giây của nó.

## 5. Fixture và công bằng giữa các lượt

Mặc định 10.000 USER performance, 50.000 trip ×40 ghế. Seed SQL hiện tại ở `datasets/` không được import thêm vào snapshot mới vì có số ghế đã tiêu thụ nhưng không có booking tương ứng.

- Tạo fixture ngoài cửa sổ đo; không tự bơm thêm ghế/data giữa lượt chạy.
- Giữ cùng số hàng và snapshot giữa các trial; ghi số hàng sau tải. Booking/history tăng trong một trial là hành vi thật, không rollback mỗi request để làm hệ thống nhanh hơn.
- Hết tài khoản/slot phải báo `FIXTURE_EXHAUSTED`. Muốn đo cao/lâu hơn, tăng `fixture.users/trips` rồi chạy **một experiment mới từ đầu**.
- Dự toán cả ramp/warm-up/settle/measure: `lượt đặt ≈ VU × tổng giây / (think time trung bình + latency) × tỷ lệ POST`. Đặc biệt soak có thể cần nhiều ghế hơn stress ngắn. Không có một fixture hữu hạn bảo đảm đủ cho VU tăng vô hạn.
- Các worker chạy process riêng, được chia account/trip không trùng; hotspot là ngoại lệ có chủ đích. Harness tăng số worker để recheck khi generator bị giới hạn, ghi rõ topology của mỗi trial.

## 6. Metrics, kết quả và điều kiện kết thúc

Artifact chính:

- `environment.json`, `harness-identity.json`, `config.json`, `fixture.json`: identity/config và dữ liệu test.
- `acceptance.json`, `acceptance-http.jsonl`, `endpoint-coverage.json`, `architecture.json`: case, mã HTTP, coverage và boundary scan.
- `stages/*/result.json`: histogram latency millisecond hợp nhất giữa worker, p95/p99 theo endpoint, cửa sổ đo, oracle và validity.
- `stages/*/resources.jsonl`: CPU/RSS/thread/I/O Java và các tiến trình PostgreSQL thuộc cluster; system memory/CPU; DB activity/wait/blocking/totals.
- `worker-*-history.jsonl`: VU thực tế, event-loop lag, CPU generator, số request/lỗi theo phase. Validity chỉ xét mẫu trong cửa sổ đo tương ứng.
- `bookings-*.csv`: ID/owner/phase đã ACK; không chứa JWT/password. SQL đối chiếu journal sau drain.
- `searches.json`, `recovery.jsonl`, `endurance.json`: khoảng tìm được, mọi lần xác nhận, phục hồi và spike/soak.
- Diagnostic riêng: thread dump, heap info, JFR. Không dùng số liệu có profiler để chốt throughput baseline.
- `REPORT.md`, `summary.json`, `stage-summary.csv`, `throughput.svg`, ZIP: kết luận và artifact tải xuống. DB dump, tools và credential riêng không được đưa vào ZIP.
- `bottlenecks.json`: giả thuyết gắn với metric/path cụ thể (lock, Java/DB CPU, máy dùng chung, response lớn, generator); không biến tương quan thành kết luận nhân quả.

Latency dùng cohort request **bắt đầu** trong measure, gồm cả completion trong drain và timeout. RPS completed tính completion trong cửa sổ; pending/cross-boundary không bị lẳng lặng xóa. Trial bị abort/incomplete không có RPS so sánh trong biểu đồ. Không lấy trung bình các p95 worker.

Exit code **0** chỉ khi đủ inventory chức năng, architecture/38 endpoint, các workload được xác nhận, recovery và spike/soak đạt, profile acceptance đầy đủ. Exit **2** là FAIL/UNKNOWN/incomplete; artifact vẫn được xuất. Bất kỳ kết quả giảm scope, hết budget, thiếu case, skipped fault, thiếu confirmation đều không được báo full PASS.

Suite tạo ZIP checkpoint sau nhóm chức năng và sau mỗi workload. Nếu bị ngắt, có thể xuất lại mọi artifact đã có mà không khởi động dịch vụ:

```bash
python -B load-tests/scripts/export_results.py /kaggle/working/acceptance-TEN_LUOT_CHAY
```

Notebook cũng gọi exporter sau khi tiến trình suite kết thúc. Các dòng JSONL chưa ghi xong do ngắt bị ghi nhận là invalid/missing evidence, không làm mất toàn bộ ZIP hay được tính thành PASS. SIGKILL/tắt kernel không bảo đảm chạy cleanup; khi đó dùng kernel mới và giữ checkpoint cũ.

`config/smoke.yaml` là overlay được ghép với acceptance config bởi `scripts/configure_run.py`; file kết quả đã resolve được lưu ngoài dataset. `profile: smoke` chọn nhánh tuần tự tối giản riêng; không chạy thuật toán adaptive và không được dùng làm kết quả nghiệm thu. `profile: acceptance` yêu cầu ít nhất 100 vòng concurrency và 3 lần confirmation.

## 7. Những giới hạn phải giữ trong báo cáo

- Java, DB và Locust cùng một máy Kaggle. Tách CPU loại được việc tranh CPU, nhưng RAM, đĩa và cache vẫn dùng chung, và backend chỉ có một nửa số CPU. Đây vẫn là công suất của **môi trường cùng máy**. Muốn kết luận cho backend độc lập phải chạy generator trên máy khác.
- Thiếu metric occupancy của Hikari nếu ứng dụng chưa expose; không thêm Actuator, không đoán pool size. Dùng wait/thread/log làm bằng chứng hỗ trợ, không coi tương quan là nguyên nhân đã chứng minh.
- CPU process 100% tương ứng một core. Affinity/quota và CPU máy được ghi riêng.
- Kiểm thử retry dùng cùng `Idempotency-Key` theo tài khoản trong thời hạn hiệu lực 24 giờ.
- Scan constant pool chỉ kiểm tra boundary hữu hạn; không thay thế toàn bộ kiểm chứng kiến trúc. Schema được test migrate mới và validate; không giả vờ đã test nâng cấp từ mọi version production cũ.
- Số liệu native Windows/Linux smoke để xác nhận harness chạy được, không phải benchmark Kaggle hoặc bằng chứng đã đạt tải hàng nghìn VU.

## 8. Kiểm tra harness trước upload

```powershell
python -B -m unittest discover -s load-tests/tests -v
```

Tests kiểm tra thuật toán vượt 2.000 VU, refine/probe, bound không đơn điệu, histogram hợp nhất, timeout/pending, generator validity, complete-case/endurance gate, JWT/DTO và Locust process protocol với HTTP server giả. Server giả chỉ kiểm chứng harness; không tạo số liệu nghiệm thu cho backend.

Notebook tạo venv riêng không dùng ensurepip, chạy unit checks trước khi khởi động ứng dụng ở mode acceptance; mode smoke giữ đường chạy tối giản. Các file test tạm nằm ở `/kaggle/working`, không ghi vào dataset chỉ đọc. Dependencies được pin trong `requirements-kaggle.txt`, manifest ghi cả dependency inventory và tiến trình mới kiểm tra version để tránh lỗi psutil bị giữ trong kernel. Package của kernel không bị thay thế.
