// Demo UI for the BusBooking API. No build step: served as static files by Nginx.
const $ = (sel) => document.querySelector(sel);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const money = (v) => Number(v).toLocaleString('vi-VN') + ' ₫';
const time = (v) => (v ? `${v.slice(8, 10)}/${v.slice(5, 7)}/${v.slice(0, 4)} ${v.slice(11, 16)}` : '');
const clock = (v) => (v ? v.slice(11, 16) : '--:--');
const day = (v) => (v ? new Date(v).toLocaleDateString('vi-VN', { weekday: 'short', day: '2-digit', month: '2-digit' }) : '');
const dayDiff = (a, b) => Math.round((new Date(b.slice(0, 10)) - new Date(a.slice(0, 10))) / 864e5);
function duration(t) {
  const mins = t.arrivalTime ? (new Date(t.arrivalTime) - new Date(t.departureTime)) / 6e4 : t.route?.estimatedDurationMinutes;
  return mins > 0 ? `${Math.floor(mins / 60)}h${String(mins % 60).padStart(2, '0')}` : '';
}

const STATUS = {
  SCHEDULED: ['Sắp khởi hành', 'ok'], IN_PROGRESS: ['Đang chạy', 'info'], COMPLETED: ['Đã hoàn thành', ''],
  CANCELLED: ['Đã huỷ', 'err'], CONFIRMED: ['Đã xác nhận', 'ok'], REFUND_PENDING: ['Chờ hoàn tiền', 'warn'], REFUNDED: ['Đã hoàn tiền', ''],
};
const chip = (s) => `<span class="chip ${STATUS[s]?.[1] ?? ''}">${esc(STATUS[s]?.[0] ?? s)}</span>`;

// Demo only: token in sessionStorage is readable by any script on the page.
let token = sessionStorage.getItem('token');

async function api(path, { method = 'GET', body, idempotencyKey } = {}) {
  const headers = {};
  if (body) headers['Content-Type'] = 'application/json';
  if (token) headers.Authorization = 'Bearer ' + token;
  if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey;
  const res = await fetch('/api' + path, { method, headers, body: body && JSON.stringify(body) });
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && token) logout();
    const details = data?.details ? ' (' + Object.values(data.details).join('; ') + ')' : '';
    throw new Error((data?.message || res.statusText || 'Request failed') + details);
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

// Wrap a form handler: prevent submit, show errors as a toast.
function onSubmit(form, fn) {
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    try { await fn(formData(form), form); } catch (err) { toast(err.message, true); }
  });
}

// ---------- Views ----------
const views = ['search', 'bookings', 'stress', 'auth'];
function show(view) {
  views.forEach((v) => ($('#view-' + v).hidden = v !== view));
  document.querySelectorAll('nav button').forEach((b) => b.classList.toggle('active', b.dataset.view === view));
  if (view === 'search') loadTrips();
  if (view === 'bookings') loadBookings();
}
document.querySelectorAll('nav button').forEach((b) => b.addEventListener('click', () => show(b.dataset.view)));

async function refreshUser() {
  let me = null;
  if (token) me = await api('/auth/me').catch(() => null);
  document.querySelectorAll('.auth-only').forEach((el) => (el.hidden = !me));
  document.querySelectorAll('.guest-only').forEach((el) => (el.hidden = !!me));
  $('#who').textContent = me ? `${me.fullName} · ${me.role}` : '';
  return me;
}

function logout() {
  token = null;
  pendingBooking = null;
  bookingPage = 0;
  sessionStorage.removeItem('token');
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

let tripsById = new Map();

function tripCard(t) {
  const seats = t.availableSeats ?? 0;
  const cap = t.vehicle?.seatCapacity;
  const bookable = t.status === 'SCHEDULED' && seats > 0;
  const next = t.arrivalTime ? dayDiff(t.departureTime, t.arrivalTime) : 0;
  return `
    <li class="trip">
      <div class="journey">
        <div class="stop"><b class="clock">${clock(t.departureTime)}</b><span>${esc(t.origin)}</span></div>
        <div class="leg"><span>${duration(t)}</span></div>
        <div class="stop end"><b class="clock">${clock(t.arrivalTime)}${next > 0 ? `<sup>+${next}</sup>` : ''}</b><span>${esc(t.destination)}</span></div>
      </div>
      <div class="info">
        <span class="when">${esc(day(t.departureTime))}<small>Chuyến #${t.id}</small></span>
        <span class="op">${esc(t.operatorName)}${t.vehicleType ? ' · ' + esc(t.vehicleType) : ''}</span>
        <span class="seats ${seats === 0 ? 'none' : seats <= 5 ? 'low' : ''}">
          ${cap ? `<span class="bar"><i style="--fill:${Math.min(100, (seats / cap) * 100)}%"></i></span>` : ''}
          ${seats === 0 ? 'Hết chỗ' : `Còn ${seats}${cap ? '/' + cap : ''} chỗ`}
        </span>
      </div>
      <div class="buy">
        <span class="price">${money(t.price)} <small>/ ghế</small></span>
        ${t.status === 'SCHEDULED' ? '' : chip(t.status)}
        <button class="primary" data-book="${t.id}" ${bookable ? '' : 'disabled'}>Chọn chuyến</button>
      </div>
    </li>`;
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
    $('#trips').innerHTML = trips.map(tripCard).join('')
      || '<li class="empty">Không có chuyến nào khớp. Thử bỏ bớt điều kiện hoặc chọn ngày khác.</li>';
  } catch (err) { if (request === tripRequest) toast(err.message, true); }
}
onSubmit($('#search-form'), () => loadTrips(0));
$('#trip-prev').addEventListener('click', () => loadTrips(tripPage - 1));
$('#trip-next').addEventListener('click', () => loadTrips(tripPage + 1));

function newBookingKey() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

$('#trips').addEventListener('click', (e) => {
  const id = e.target.dataset.book;
  if (!id) return;
  if (!token) { toast('Đăng nhập để đặt vé', true); return show('auth'); }
  const t = tripsById.get(id);
  const form = $('#book-form');
  form.tripId.value = id;
  form.quantity.max = t?.availableSeats || '';
  $('#book-trip').textContent = id;
  $('#book-route').textContent = t ? `${t.origin} → ${t.destination}` : '';
  $('#book-when').textContent = t ? `${day(t.departureTime)} · ${clock(t.departureTime)} · ${t.operatorName}` : '';
  updateTotal();
  $('#book-dialog').showModal();
});

function updateTotal() {
  const form = $('#book-form');
  const t = tripsById.get(form.tripId.value);
  $('#book-total').textContent = t ? money(t.price * (+form.quantity.value || 0)) : '';
}
$('#book-form').quantity.addEventListener('input', updateTotal);

$('#book-form').addEventListener('submit', async (e) => {
  if (e.submitter?.value !== 'ok') return; // "Huỷ" just closes the dialog
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
    $('#book-dialog').close();
    toast(`Đặt thành công ${b.bookingCode} · ${money(b.totalAmount)}`);
    loadTrips();
  } catch (err) { toast(err.message, true); }
  finally { submit.disabled = false; }
});

// ---------- My bookings ----------
async function loadBookings(page = bookingPage) {
  const request = ++bookingRequest;
  try {
    const list = await api(`/users/me/bookings?page=${page}&size=${pageSize}`);
    if (request !== bookingRequest || !token) return;
    bookingPage = page;
    updatePage('booking', bookingPage, list.length);
    $('#bookings').innerHTML = list.map((b) => `
      <tr>
        <td class="code">${esc(b.bookingCode)}</td>
        <td>#${b.tripId}</td>
        <td>${esc(b.passengerName)}</td>
        <td class="num">${b.quantity}</td>
        <td class="num">${money(b.totalAmount)}</td>
        <td>${chip(b.status)}</td>
        <td>${time(b.bookedAt)}</td>
        <td>${b.status === 'CONFIRMED' ? `<button class="ghost danger" data-cancel="${b.id}">Huỷ vé</button>` : ''}</td>
      </tr>`).join('') || '<tr><td colspan="8" class="empty-cell">Bạn chưa đặt vé nào. Vào Tìm chuyến để chọn chuyến đầu tiên.</td></tr>';
  } catch (err) { if (request === bookingRequest && token) toast(err.message, true); }
}
$('#booking-prev').addEventListener('click', () => loadBookings(bookingPage - 1));
$('#booking-next').addEventListener('click', () => loadBookings(bookingPage + 1));

$('#bookings').addEventListener('click', async (e) => {
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

// ---------- Auth ----------
onSubmit($('#login-form'), async (d, form) => {
  const res = await api('/auth/login', { method: 'POST', body: d });
  token = res.token;
  sessionStorage.setItem('token', token);
  form.reset();
  await refreshUser();
  toast('Đăng nhập thành công');
  show('search');
});

onSubmit($('#register-form'), async (d, form) => {
  await api('/auth/register', { method: 'POST', body: d });
  $('#verify-form').email.value = d.email;
  form.reset();
  toast('Đã tiếp nhận yêu cầu gửi mã OTP. Kiểm tra Mailpit sau vài giây.');
});

onSubmit($('#verify-form'), async (d, form) => {
  await api('/auth/verify-email', { method: 'POST', body: d });
  $('#login-form').email.value = d.email;
  form.reset();
  toast('Xác minh xong, giờ đăng nhập được rồi');
});

// ---------- Boot ----------
loadLocations();
refreshUser().then(() => show('search'));
