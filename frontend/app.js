// Demo UI for the BusBooking API. No build step: served as static files by Nginx.
const $ = (sel) => document.querySelector(sel);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const money = (v) => Number(v).toLocaleString('vi-VN') + ' ₫';
const clock = (v) => (v ? v.slice(11, 16) : '--:--');
const day = (v) => (v ? new Date(v).toLocaleDateString('vi-VN', { weekday: 'short', day: '2-digit', month: '2-digit' }) : '');
const dayDiff = (a, b) => Math.round((new Date(b.slice(0, 10)) - new Date(a.slice(0, 10))) / 864e5);
function duration(t) {
  const mins = t.arrivalTime ? (new Date(t.arrivalTime) - new Date(t.departureTime)) / 6e4 : t.route?.estimatedDurationMinutes;
  return mins > 0 ? `${Math.floor(mins / 60)}h${String(mins % 60).padStart(2, '0')}` : '';
}

const STATUS = {
  HELD: ['Đang giữ chỗ', 'warn'], EXPIRED: ['Hết hạn giữ chỗ', ''],
  SCHEDULED: ['Sắp khởi hành', 'ok'], IN_PROGRESS: ['Đang chạy', 'info'], COMPLETED: ['Đã hoàn thành', ''],
  CANCELLED: ['Đã huỷ', 'err'], CONFIRMED: ['Đã xác nhận', 'ok'], REFUND_PENDING: ['Chờ hoàn tiền', 'warn'], REFUNDED: ['Đã hoàn tiền', ''],
};
const chip = (s) => `<span class="chip ${STATUS[s]?.[1] ?? ''}">${esc(STATUS[s]?.[0] ?? s)}</span>`;

// Demo only: token in sessionStorage is readable by any script on the page.
let token = sessionStorage.getItem('token');
let me = null;
// '' + '/api' locally (same origin); the backend's own URL on Render, which saves the static-site hop.
const API = (window.BUSBOOKING_API || '') + '/api';

async function api(path, { method = 'GET', body, idempotencyKey } = {}) {
  const headers = {};
  if (body) headers['Content-Type'] = 'application/json';
  if (token) headers.Authorization = 'Bearer ' + token;
  if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey;
  const res = await fetch(API + path, { method, headers, body: body && JSON.stringify(body) });
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && token) logout();
    const details = data?.details ? ' (' + Object.values(data.details).join('; ') + ')' : '';
    const err = new Error((data?.message || res.statusText || 'Request failed') + details);
    err.status = res.status;
    throw err;
  }
  return data;
}

function toast(msg, isErr = false) {
  const el = $('#toast');
  el.textContent = msg;
  el.className = isErr ? 'err' : '';
  el.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => (el.hidden = true), 4000);
}

const formData = (form) => Object.fromEntries(new FormData(form));

function formError(form, msg) {
  const el = form.querySelector('.form-error');
  if (!el) return toast(msg, true);
  el.textContent = msg;
  el.hidden = false;
}

// Wrap a form handler: prevent submit, block double submits, show errors inside the form (or as a toast).
function onSubmit(form, fn) {
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = form.querySelector('button.primary');
    const err = form.querySelector('.form-error');
    if (err) err.hidden = true;
    btn.disabled = true;
    try { await fn(formData(form), form); } catch (ex) { formError(form, ex.message); }
    finally { btn.disabled = false; }
  });
}

// ---------- Views ----------
const views = ['search', 'bookings', 'stress', 'auth'];
function show(view) {
  views.forEach((v) => ($('#view-' + v).hidden = v !== view));
  document.querySelectorAll('nav [data-view]').forEach((b) => b.classList.toggle('active', b.dataset.view === view));
  if (view === 'search') loadTrips();
  if (view === 'bookings') loadBookings();
  window.scrollTo(0, 0);
}
document.querySelectorAll('[data-view]').forEach((b) => b.addEventListener('click', () => show(b.dataset.view)));

async function refreshUser() {
  me = token ? await api('/auth/me').catch(() => null) : null;
  document.querySelectorAll('.auth-only').forEach((el) => (el.hidden = !me));
  document.querySelectorAll('.guest-only').forEach((el) => (el.hidden = !!me));
  $('#who').textContent = me ? me.fullName : '';
  return me;
}

function logout() {
  const old = token;
  token = null;
  pendingBooking = null;
  resumeTrip = null;
  bookingPage = 0;
  sessionStorage.removeItem('token');
  // Revoke server-side too; plain fetch so a 401 here cannot loop back into logout().
  if (old) fetch(API + '/auth/logout', { method: 'POST', headers: { Authorization: 'Bearer ' + old } }).catch(() => {});
  refreshUser();
  show('search');
}
$('#logout').addEventListener('click', logout);

// ---------- Search & book ----------
const pageSize = 20;
let tripPage = 0;
let bookingPage = 0;
let pendingBooking = null;
let tripRequest = 0;
let bookingRequest = 0;
let tripsById = new Map();
let bookingTrip = null;
let resumeTrip = null; // trip a guest picked before signing in

function updatePage(prefix, page, count) {
  $('#' + prefix + '-page').textContent = `Trang ${page + 1}`;
  $('#' + prefix + '-prev').disabled = page === 0;
  $('#' + prefix + '-next').disabled = count < pageSize;
}

async function loadLocations() {
  const locations = await api('/locations').catch(() => []);
  const opts = locations.map((l) => `<option value="${l.id}">${esc(l.name)}</option>`).join('');
  document.querySelectorAll('#search-form select').forEach((s) => s.insertAdjacentHTML('beforeend', opts));
}

$('#departure-date').min = new Date().toLocaleDateString('en-CA'); // local YYYY-MM-DD
$('#swap').addEventListener('click', () => {
  const [o, d] = [$('#origin'), $('#destination')];
  [o.value, d.value] = [d.value, o.value];
});

const longDay = (v) => new Date(v).toLocaleDateString('vi-VN', { weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric' });

// A ticket: operator + vertical timeline on the left, a tear-off stub with price and action on the right.
function tripCard(t) {
  const seats = t.availableSeats ?? 0;
  const bookable = t.status === 'SCHEDULED' && seats > 0;
  const next = t.arrivalTime ? dayDiff(t.departureTime, t.arrivalTime) : 0;
  return `
    <li class="trip">
      <div class="ticket">
        <div class="ticket-head">
          <b>${esc(t.operatorName)}</b>
          ${t.vehicleType ? `<span>${esc(t.vehicleType)}</span>` : ''}
          ${t.status === 'SCHEDULED' ? '' : chip(t.status)}
        </div>
        <div class="timeline">
          <time>${clock(t.departureTime)}</time><i class="dot"></i><span class="place">${esc(t.origin)}</span>
          <span></span><i class="rail"></i><span class="dur">${duration(t)}</span>
          <time>${clock(t.arrivalTime)}${next > 0 ? `<sup title="Đến ngày hôm sau">+${next}</sup>` : ''}</time><i class="dot end"></i><span class="place">${esc(t.destination)}</span>
        </div>
      </div>
      <div class="stub">
        <span class="price">${money(t.price)}</span>
        <span class="seats ${seats === 0 ? 'none' : seats <= 5 ? 'low' : ''}">${seats === 0 ? 'Hết chỗ' : `Còn ${seats} chỗ trống`}</span>
        <button class="primary" data-book="${t.id}" ${bookable ? '' : 'disabled'}>Chọn chuyến</button>
      </div>
    </li>`;
}

// Group the (already time-ordered) trips under one heading per departure day.
function tripList(trips) {
  let lastDay = '';
  return trips.map((t) => {
    const d = t.departureTime.slice(0, 10);
    const head = d === lastDay ? '' : `<li class="day-head">${esc(longDay(t.departureTime))}</li>`;
    lastDay = d;
    return head + tripCard(t);
  }).join('');
}

async function loadTrips(page = tripPage) {
  const request = ++tripRequest;
  const params = new URLSearchParams(Object.entries(formData($('#search-form'))).filter(([, v]) => v));
  params.set('page', page);
  params.set('size', pageSize);
  try {
    const trips = await api('/trips?' + params);
    if (request !== tripRequest) return;
    tripPage = page;
    updatePage('trip', tripPage, trips.length);
    tripsById = new Map(trips.map((t) => [String(t.id), t]));
    $('#trips').innerHTML = tripList(trips)
      || '<li class="empty">Không có chuyến nào khớp. Thử bỏ bớt điều kiện hoặc chọn ngày khác.</li>';
  } catch (err) { if (request === tripRequest) toast(err.message, true); }
}
onSubmit($('#search-form'), (d) => {
  if (d.originId && d.originId === d.destinationId) throw new Error('Điểm đi và điểm đến phải khác nhau.');
  return loadTrips(0);
});
$('#trip-prev').addEventListener('click', () => loadTrips(tripPage - 1));
$('#trip-next').addEventListener('click', () => loadTrips(tripPage + 1));

function newBookingKey() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

$('#trips').addEventListener('click', (e) => {
  const t = tripsById.get(e.target.closest('[data-book]')?.dataset.book);
  if (!t) return;
  if (!me) {
    resumeTrip = t;
    return showAuth('login', { notice: `Đăng nhập để đặt vé ${t.origin} → ${t.destination}, ${clock(t.departureTime)} ${day(t.departureTime)}.` });
  }
  openBooking(t);
});

function openBooking(t) {
  bookingTrip = t;
  const form = $('#book-form');
  form.reset();
  form.tripId.value = t.id;
  form.passengerName.value = me?.fullName ?? '';
  form.passengerPhone.value = me?.phone ?? '';
  form.quantity.max = t.availableSeats || '';
  $('#book-route').textContent = `${t.origin} → ${t.destination}`;
  $('#book-when').textContent = `${day(t.departureTime)} · ${clock(t.departureTime)} · ${t.operatorName}`;
  bookStep('step');
  updateTotal();
  $('#book-dialog').showModal();
}

function updateTotal() {
  const qty = +$('#book-form').quantity.value || 0;
  $('#book-total').textContent = bookingTrip ? money(bookingTrip.price * qty) : '';
}
$('#book-form').quantity.addEventListener('input', updateTotal);

$('#book-form').addEventListener('submit', async (e) => {
  if (e.submitter?.value !== 'ok') return; // "Huỷ"/"Đóng" just close the dialog
  e.preventDefault();
  const d = formData(e.target);
  const body = { ...d, tripId: +d.tripId, quantity: +d.quantity };
  const serialized = JSON.stringify(body);
  if (pendingBooking?.body !== serialized) {
    pendingBooking = { body: serialized, key: newBookingKey() };
  }
  const submit = e.submitter;
  submit.disabled = true;
  try {
    const b = await api('/bookings', { method: 'POST', body, idempotencyKey: pendingBooking.key });
    pendingBooking = null;
    startHold(b);
    loadTrips();
  } catch (err) { toast(err.message, true); }
  finally { submit.disabled = false; }
});
$('#go-bookings').addEventListener('click', () => { $('#book-dialog').close(); show('bookings'); });

// ---------- Seat hold: HELD until confirmed, or EXPIRED after the deadline ----------
const bookStep = (name) => ['step', 'hold', 'done'].forEach((s) => ($('#book-' + s).hidden = s !== name));
let heldBooking = null;

function startHold(b) {
  heldBooking = b;
  // Count down from the server's own hold length, so browser clock and timezone don't matter.
  const deadline = Date.now() + (new Date(b.holdExpiresAt) - new Date(b.bookedAt));
  $('#hold-total').textContent = `${b.quantity} ghế · ${money(b.totalAmount)}`;
  $('#hold-confirm').disabled = false;
  $('#hold-note').textContent = 'Xác nhận trước khi hết giờ, nếu không ghế sẽ được trả lại cho chuyến.';
  clearInterval(startHold.timer);
  const tick = () => {
    const left = Math.max(0, Math.round((deadline - Date.now()) / 1000));
    $('#hold-countdown').textContent = `${String(Math.floor(left / 60)).padStart(2, '0')}:${String(left % 60).padStart(2, '0')}`;
    if (left === 0) { clearInterval(startHold.timer); holdLapsed(); }
  };
  tick();
  startHold.timer = setInterval(tick, 1000);
  bookStep('hold');
}

function holdLapsed() {
  $('#hold-confirm').disabled = true;
  $('#hold-note').textContent = 'Hết thời gian giữ chỗ, ghế đã được trả lại. Chọn chuyến để đặt lại.';
}

function showDone(b) {
  clearInterval(startHold.timer);
  $('#done-code').textContent = b.bookingCode;
  $('#done-summary').textContent = `${b.quantity} ghế · ${money(b.totalAmount)} · ${bookingTrip.origin} → ${bookingTrip.destination}, ${clock(bookingTrip.departureTime)} ${day(bookingTrip.departureTime)}`;
  bookStep('done');
}

const confirmBooking = (id) => api(`/bookings/${id}/confirm`, { method: 'POST' }).catch((err) => {
  if (err.status === 409) throw new Error('Hết thời gian giữ chỗ, ghế đã được trả lại. Vui lòng đặt lại.');
  throw err;
});

$('#hold-confirm').addEventListener('click', async (e) => {
  e.currentTarget.disabled = true;
  try { showDone(await confirmBooking(heldBooking.id)); }
  catch (err) { toast(err.message, true); if (/Hết thời gian/.test(err.message)) holdLapsed(); else e.currentTarget.disabled = false; }
});

$('#hold-release').addEventListener('click', async () => {
  try {
    await api('/bookings/' + heldBooking.id, { method: 'DELETE' });
    clearInterval(startHold.timer);
    $('#book-dialog').close();
    toast('Đã huỷ giữ chỗ');
    loadTrips();
  } catch (err) { toast(err.message, true); }
});
$('#book-dialog').addEventListener('close', () => clearInterval(startHold.timer));

// ---------- My bookings ----------
// shortcut: booking history carries only tripId, so each trip is fetched once and cached;
// add route and departure to BookingHistoryResponse if pages grow past ~20 distinct trips.
const tripCache = new Map();
const tripFor = (id) => {
  if (!tripCache.has(id)) tripCache.set(id, api('/trips/' + id).catch(() => null));
  return tripCache.get(id);
};

function bookingCard(b, t) {
  const actions = (b.status === 'HELD' ? `<button class="primary" data-confirm="${b.id}">Xác nhận</button>` : '')
    + (b.status === 'CONFIRMED' || b.status === 'HELD' ? `<button class="ghost danger" data-cancel="${b.id}">Huỷ vé</button>` : '');
  return `
    <li class="booking">
      <div class="booking-main">
        <div class="booking-head"><b>${t ? `${esc(t.origin)} → ${esc(t.destination)}` : `Chuyến #${b.tripId}`}</b>${chip(b.status)}</div>
        ${t ? `<p>${esc(day(t.departureTime))} · ${clock(t.departureTime)} · ${esc(t.operatorName)}</p>` : ''}
        ${b.status === 'HELD' && b.holdExpiresAt ? `<p class="deadline">Xác nhận trước ${clock(b.holdExpiresAt)}, nếu không ghế sẽ được trả lại.</p>` : ''}
        <p><span class="code">${esc(b.bookingCode)}</span> · ${esc(b.passengerName)} · ${b.quantity} ghế</p>
      </div>
      <div class="booking-side">
        <span class="price">${money(b.totalAmount)}</span>
        <div class="row-actions">${actions}</div>
      </div>
    </li>`;
}

async function loadBookings(page = bookingPage) {
  const request = ++bookingRequest;
  try {
    const list = await api(`/users/me/bookings?page=${page}&size=${pageSize}`);
    const trips = await Promise.all(list.map((b) => tripFor(b.tripId)));
    if (request !== bookingRequest || !token) return;
    bookingPage = page;
    updatePage('booking', bookingPage, list.length);
    $('#bookings').innerHTML = list.map((b, i) => bookingCard(b, trips[i])).join('')
      || '<li class="empty">Bạn chưa đặt vé nào. Vào Tìm chuyến để chọn chuyến đầu tiên.</li>';
  } catch (err) { if (request === bookingRequest && token) toast(err.message, true); }
}
$('#booking-prev').addEventListener('click', () => loadBookings(bookingPage - 1));
$('#booking-next').addEventListener('click', () => loadBookings(bookingPage + 1));

$('#bookings').addEventListener('click', async (e) => {
  if (e.target.dataset.confirm) {
    try { await confirmBooking(e.target.dataset.confirm); toast('Đã xác nhận vé'); }
    catch (err) { toast(err.message, true); }
    return loadBookings();
  }
  const id = e.target.dataset.cancel;
  if (!id || !confirm('Huỷ vé này?')) return;
  try {
    await api('/bookings/' + id, { method: 'DELETE' });
    toast('Đã huỷ vé');
    loadBookings();
  } catch (err) { toast(err.message, true); }
});

// ---------- Concurrency demo ----------
onSubmit($('#stress-form'), async ({ tripId, n }) => {
  const out = $('#stress-out');
  const before = await api('/trips/' + tripId);
  out.textContent = `Chuyến #${tripId}: còn ${before.availableSeats} ghế. Đang gửi ${n} yêu cầu cùng lúc...`;

  const body = { tripId: +tripId, passengerName: 'Load Test', passengerPhone: '0900000000', quantity: 1 };
  const started = performance.now();
  const results = await Promise.allSettled(Array.from({ length: +n }, () =>
    api('/bookings', { method: 'POST', body, idempotencyKey: newBookingKey() })));
  const ms = Math.round(performance.now() - started);

  const ok = results.filter((r) => r.status === 'fulfilled').length;
  const errors = {};
  results.filter((r) => r.status === 'rejected').forEach((r) => (errors[r.reason.message] = (errors[r.reason.message] || 0) + 1));
  const after = await api('/trips/' + tripId);
  const consistent = before.availableSeats - ok === after.availableSeats && ok <= before.availableSeats;

  out.textContent = [
    `Ghế trước:      ${before.availableSeats}`,
    `Yêu cầu gửi:    ${n} (xong trong ${ms} ms)`,
    `Thành công:     ${ok}`,
    `Bị từ chối:     ${+n - ok}`,
    ...Object.entries(errors).map(([m, c]) => `   ${c} × ${m}`),
    `Ghế sau:        ${after.availableSeats}`,
    '',
    consistent ? '✅ Nhất quán: không oversell, số ghế khớp số vé bán ra.' : '❌ KHÔNG nhất quán: số ghế không khớp số vé bán ra!',
  ].join('\n');
});

// ---------- Auth: login → (register → verify) / (forgot → reset) ----------
const authScreens = ['login', 'register', 'verify', 'forgot', 'reset'];
const visibleAuthForm = () => ($('#view-auth').hidden ? null : authScreens.map((s) => $('#' + s + '-form')).find((f) => !f.hidden));

function showAuth(screen, { email, notice } = {}) {
  email ??= visibleAuthForm()?.email.value; // carry the typed email between screens
  authScreens.forEach((s) => ($('#' + s + '-form').hidden = s !== screen));
  const form = $('#' + screen + '-form');
  form.querySelector('.form-error').hidden = true;
  if (email) form.email.value = email;
  const n = form.querySelector('.form-notice');
  if (n) { n.textContent = notice ?? ''; n.hidden = !notice; }
  show('auth');
  (form.email.value ? form.querySelector('input:not([type=hidden]):not([name=email])') : form.email)?.focus();
}
document.querySelectorAll('[data-auth]').forEach((b) => b.addEventListener('click', () => showAuth(b.dataset.auth)));

document.querySelectorAll('[data-toggle-pw]').forEach((b) => b.addEventListener('click', () => {
  const input = b.previousElementSibling;
  const reveal = input.type === 'password';
  input.type = reveal ? 'text' : 'password';
  b.textContent = reveal ? 'Ẩn' : 'Hiện';
  b.setAttribute('aria-label', reveal ? 'Ẩn mật khẩu' : 'Hiện mật khẩu');
}));

function cooldown(btn, seconds) {
  const label = (btn.dataset.label ??= btn.textContent);
  clearTimeout(btn.timer);
  btn.disabled = true;
  const tick = () => {
    if (seconds <= 0) { btn.disabled = false; btn.textContent = label; return; }
    btn.textContent = `${label} (${seconds--}s)`;
    btn.timer = setTimeout(tick, 1000);
  };
  tick();
}

onSubmit($('#login-form'), async (d, form) => {
  let res;
  try { res = await api('/auth/login', { method: 'POST', body: d }); }
  catch (e) {
    // The API answers the same for a wrong password and an unverified email, on purpose.
    if (e.status === 401) throw new Error('Email hoặc mật khẩu không đúng. Nếu vừa đăng ký, hãy kích hoạt tài khoản bằng mã gửi qua email trước.');
    throw e;
  }
  token = res.token;
  sessionStorage.setItem('token', token);
  form.reset();
  await refreshUser();
  toast(`Xin chào, ${me?.fullName ?? ''}`);
  const t = resumeTrip;
  resumeTrip = null;
  show('search');
  if (t) openBooking(t);
});

onSubmit($('#register-form'), async (d, form) => {
  await api('/auth/register', { method: 'POST', body: d });
  form.reset();
  showAuth('verify', { email: d.email, notice: `Đã gửi mã kích hoạt tới ${d.email}. Mã có thể mất vài giây để tới.` });
  cooldown($('#resend'), 60);
});

onSubmit($('#verify-form'), async (d, form) => {
  await api('/auth/verify-email', { method: 'POST', body: d });
  form.reset();
  showAuth('login', { email: d.email, notice: 'Tài khoản đã được kích hoạt. Đăng nhập để tiếp tục.' });
});

$('#resend').addEventListener('click', async (e) => {
  const form = $('#verify-form');
  const btn = e.currentTarget;
  if (!form.email.reportValidity()) return;
  btn.disabled = true;
  try {
    await api('/auth/resend-verification', { method: 'POST', body: { email: form.email.value } });
    toast('Đã gửi lại mã. Kiểm tra hộp thư sau vài giây.');
    cooldown(btn, 60);
  } catch (err) { btn.disabled = false; formError(form, err.message); }
});

onSubmit($('#forgot-form'), async (d) => {
  await api('/auth/forgot-password', { method: 'POST', body: d });
  showAuth('reset', { email: d.email, notice: `Nếu ${d.email} đã đăng ký, mã đặt lại mật khẩu đã được gửi tới hộp thư.` });
});

onSubmit($('#reset-form'), async (d, form) => {
  await api('/auth/reset-password', { method: 'POST', body: d });
  form.reset();
  showAuth('login', { email: d.email, notice: 'Đã đổi mật khẩu. Đăng nhập bằng mật khẩu mới.' });
});

// ---------- Boot ----------
loadLocations();
refreshUser().then(() => show('search'));
