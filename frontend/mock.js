// In-browser mock of the BusBooking API for UI demos without a backend.
// Inert unless the page URL has ?mock (e.g. http://localhost:8090/?mock).
// Demo login: demo@busbooking.vn / matkhau123. Every emailed code (OTP, reset) is 123456.
(() => {
  if (!new URLSearchParams(location.search).has('mock')) return;

  // Deterministic random so the same trips come back on every reload.
  let seed = 20261125;
  const rnd = () => { seed |= 0; seed = (seed + 0x6d2b79f5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  const int = (a, b) => a + Math.floor(rnd() * (b - a + 1));
  const pick = (arr) => arr[Math.floor(rnd() * arr.length)];
  const pad = (n) => String(n).padStart(2, '0');
  const fmt = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:00`;

  const LOCATIONS = ['Hà Nội', 'TP. Hồ Chí Minh', 'Đà Nẵng', 'Huế', 'Hải Phòng', 'Hạ Long', 'Ninh Bình', 'Sapa', 'Vinh',
    'Nha Trang', 'Đà Lạt', 'Quy Nhơn', 'Buôn Ma Thuột', 'Cần Thơ', 'Vũng Tàu', 'Phan Thiết'].map((name, i) => ({ id: i + 1, name }));
  const loc = (name) => LOCATIONS.find((l) => l.name === name);

  // [origin, destination, minutes]; each route runs both ways.
  const ROUTES = [
    ['Hà Nội', 'Hải Phòng', 120], ['Hà Nội', 'Hạ Long', 180], ['Hà Nội', 'Ninh Bình', 120], ['Hà Nội', 'Sapa', 330],
    ['Hà Nội', 'Vinh', 330], ['Hà Nội', 'Huế', 780], ['Hà Nội', 'Đà Nẵng', 900], ['Vinh', 'Huế', 420],
    ['Huế', 'Đà Nẵng', 150], ['Đà Nẵng', 'Quy Nhơn', 330], ['Đà Nẵng', 'Nha Trang', 720], ['TP. Hồ Chí Minh', 'Đà Nẵng', 1080],
    ['TP. Hồ Chí Minh', 'Đà Lạt', 420], ['TP. Hồ Chí Minh', 'Nha Trang', 540], ['TP. Hồ Chí Minh', 'Vũng Tàu', 150],
    ['TP. Hồ Chí Minh', 'Phan Thiết', 240], ['TP. Hồ Chí Minh', 'Cần Thơ', 210], ['TP. Hồ Chí Minh', 'Buôn Ma Thuột', 480],
    ['TP. Hồ Chí Minh', 'Quy Nhơn', 690], ['Nha Trang', 'Đà Lạt', 240],
  ].flatMap(([a, b, m]) => [[a, b, m], [b, a, m]]);

  const OPERATORS = ['Phương Trang', 'Hoàng Long', 'Sao Việt', 'Thành Bưởi', 'Hưng Long', 'Kumho Samco', 'Hà Sơn Hải Vân',
    'Mai Linh Express', 'Tâm Hạnh', 'Văn Minh', 'Inter Bus Lines', 'Long Vân'];
  const VEHICLES = { // type: [capacity, price factor]
    'Giường nằm 40 chỗ': [40, 1], 'Giường nằm 34 phòng': [34, 1.2], 'Limousine 22 phòng': [22, 1.5],
    'Limousine 9 chỗ': [9, 1.3], 'Ghế ngồi 29 chỗ': [29, 0.75],
  };
  const SHORT = ['Limousine 9 chỗ', 'Ghế ngồi 29 chỗ', 'Limousine 22 phòng', 'Giường nằm 40 chỗ'];
  const LONG = ['Giường nằm 40 chỗ', 'Giường nằm 34 phòng', 'Limousine 22 phòng'];

  // ~4,000 trips: 10 days back (for booking history) to 14 days ahead, 3–6 departures per route per day.
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const trips = [];
  let tripId = 1001;
  for (let dayOffset = -10; dayOffset <= 14; dayOffset++) {
    for (const [o, d, mins] of ROUTES) {
      const slots = new Set();
      const count = int(3, 6);
      while (slots.size < count) slots.add(int(10, 47) * 30); // 05:00–23:30
      for (const slot of [...slots].sort((a, b) => a - b)) {
        const dep = new Date(today.getTime() + dayOffset * 864e5 + slot * 6e4);
        const arr = new Date(dep.getTime() + (mins + int(-15, 30)) * 6e4);
        const vehicleType = pick(mins <= 300 ? SHORT : LONG);
        const [cap, factor] = VEHICLES[vehicleType];
        const roll = rnd();
        const seats = roll < 0.08 ? 0 : roll < 0.22 ? int(1, 5) : int(6, cap);
        let status = rnd() < 0.03 ? 'CANCELLED' : 'SCHEDULED';
        if (status === 'SCHEDULED' && dep <= now) status = arr <= now ? 'COMPLETED' : 'IN_PROGRESS';
        const operatorName = pick(OPERATORS);
        trips.push({
          id: tripId++, routeId: ROUTES.findIndex((r) => r[0] === o && r[1] === d) + 1, vehicleId: int(1, 120),
          origin: o, destination: d, originId: loc(o).id, destinationId: loc(d).id,
          vehicleType, operatorName, departureTime: fmt(dep), arrivalTime: fmt(arr),
          price: Math.max(90000, Math.round((mins * 1100 * factor) / 10000) * 10000),
          availableSeats: Math.min(seats, cap), status,
          route: { origin: o, destination: d, estimatedDurationMinutes: mins },
          vehicle: { vehicleType, seatCapacity: cap, operatorName },
        });
      }
    }
  }
  const tripById = new Map(trips.map((t) => [t.id, t]));

  // Mutable state (accounts, bookings) survives reloads within the tab.
  const KEY = 'bb-mock-state';
  let state;
  try { state = JSON.parse(sessionStorage.getItem(KEY)); } catch { state = null; }
  if (!state) {
    state = {
      users: { 'demo@busbooking.vn': { fullName: 'Nguyễn Minh Anh', phone: '0912345678', password: 'matkhau123', verified: true } },
      bookings: [], idem: {}, seq: 1,
    };
    const passengers = ['Nguyễn Minh Anh', 'Trần Thu Hà', 'Lê Quốc Bảo', 'Phạm Gia Huy'];
    const sample = trips.filter((t) => t.status !== 'IN_PROGRESS' && rnd() < 0.012).slice(0, 42);
    for (const t of sample) {
      const dep = new Date(t.departureTime);
      const quantity = int(1, 3);
      const bookedAt = new Date(Math.min(now.getTime() - int(1, 600) * 6e4, dep.getTime() - int(1, 9) * 864e5));
      const status = t.status === 'CANCELLED' ? pick(['REFUND_PENDING', 'REFUNDED']) : rnd() < 0.18 ? 'CANCELLED' : 'CONFIRMED';
      state.bookings.push(newBooking(t, { passengerName: pick(passengers), passengerPhone: '0912345678', quantity }, 'demo@busbooking.vn', status, bookedAt));
    }
  }
  // Seats already held by stored bookings are taken off each trip.
  for (const b of state.bookings) if (b.status === 'CONFIRMED' && b.seatsHeld) tripById.get(b.tripId).availableSeats -= b.quantity;
  const save = () => { try { sessionStorage.setItem(KEY, JSON.stringify(state)); } catch { /* demo only */ } };
  save();

  function newBooking(t, d, email, status = 'CONFIRMED', bookedAt = new Date()) {
    const code = 'BK' + Array.from({ length: 6 }, () => 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'[Math.floor(Math.random() * 32)]).join('');
    return {
      id: state.seq++, bookingCode: code, tripId: t.id, passengerName: d.passengerName, passengerPhone: d.passengerPhone,
      quantity: d.quantity, unitPrice: t.price, totalAmount: t.price * d.quantity, status, bookedAt: fmt(bookedAt), email, seatsHeld: false,
    };
  }

  const PHONE = /^0(?:[35789][0-9]{8}|2[0-9]{9})$/;
  const normPhone = (p) => { p = String(p ?? '').trim(); return p.startsWith('+84') ? '0' + p.slice(3) : p; };
  const emailOf = (headers) => { const h = headers?.Authorization || ''; return h.startsWith('Bearer mock.') ? decodeURIComponent(h.slice(12)) : null; };
  const publicTrip = ({ originId, destinationId, ...t }) => t;
  const publicBooking = ({ email, seatsHeld, ...b }) => b;
  const userOut = (email) => { const u = state.users[email]; return { id: Object.keys(state.users).indexOf(email) + 1, fullName: u.fullName, email, phone: u.phone, role: 'USER', emailVerified: u.verified }; };

  function route(method, url, body, headers) {
    const u = new URL(url, location.origin);
    const p = u.pathname.replace(/^\/api/, '');
    const q = u.searchParams;
    const me = emailOf(headers);
    const authed = me && state.users[me]?.verified;
    const page = Math.max(0, +(q.get('page') ?? 0)), size = Math.min(100, Math.max(1, +(q.get('size') ?? 20)));
    const paged = (list) => list.slice(page * size, page * size + size);

    if (method === 'GET' && p === '/locations') return [200, LOCATIONS];

    if (method === 'GET' && p === '/trips') {
      // Same rules as the real search: future, SCHEDULED, seats left, earliest first.
      const o = +q.get('originId') || null, d = +q.get('destinationId') || null, date = q.get('departureDate');
      const nowStr = fmt(new Date());
      return [200, paged(trips.filter((t) => (!o || t.originId === o) && (!d || t.destinationId === d)
        && (!date || t.departureTime.startsWith(date)) && t.departureTime > nowStr
        && t.status === 'SCHEDULED' && t.availableSeats > 0)).map(publicTrip)];
    }
    let m = p.match(/^\/trips\/(\d+)$/);
    if (method === 'GET' && m) { const t = tripById.get(+m[1]); return t ? [200, publicTrip(t)] : [404, { message: 'Trip not found' }]; }

    if (method === 'POST' && p === '/auth/register') {
      const email = String(body.email ?? '').trim().toLowerCase();
      const details = {};
      if (!String(body.fullName ?? '').trim()) details.fullName = 'Full name must contain 1 to 100 characters';
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) details.email = 'A valid email of at most 100 characters is required';
      if (!PHONE.test(normPhone(body.phone))) details.phone = 'A Vietnamese phone number is required';
      if (String(body.password ?? '').length < 8) details.password = 'Password requires at least 8 characters and at most 72 UTF-8 bytes';
      if (Object.keys(details).length) return [400, { message: 'Validation failed', details }];
      if (state.users[email]?.verified) return [409, { message: 'Email already registered' }];
      state.users[email] = { fullName: body.fullName.trim(), phone: normPhone(body.phone), password: body.password, verified: false };
      return [201, userOut(email)];
    }
    if (method === 'POST' && p === '/auth/verify-email') {
      const email = String(body.email ?? '').trim().toLowerCase();
      if (!state.users[email] || state.users[email].verified || body.code !== '123456') return [400, { message: 'Invalid or expired verification code' }];
      state.users[email].verified = true;
      return [204];
    }
    if (method === 'POST' && p === '/auth/resend-verification') return [202, { message: 'If the account is eligible, a verification email has been requested' }];
    if (method === 'POST' && p === '/auth/forgot-password') return [202, { message: 'If the account is eligible, a password reset email has been sent' }];
    if (method === 'POST' && p === '/auth/reset-password') {
      const email = String(body.email ?? '').trim().toLowerCase();
      if (!state.users[email]?.verified || body.code !== '123456') return [400, { message: 'Invalid or expired reset code' }];
      if (String(body.newPassword ?? '').length < 8) return [400, { message: 'Validation failed', details: { newPassword: 'Password requires at least 8 characters' } }];
      state.users[email].password = body.newPassword;
      return [204];
    }
    if (method === 'POST' && p === '/auth/login') {
      const email = String(body.email ?? '').trim().toLowerCase();
      const user = state.users[email];
      if (!user || !user.verified || user.password !== body.password) return [401, { message: 'Invalid email or password' }];
      return [200, { token: 'mock.' + encodeURIComponent(email), tokenType: 'Bearer', expiresIn: 3600, user: userOut(email) }];
    }
    if (method === 'POST' && p === '/auth/logout') return authed ? [204] : [401, { message: 'Authentication required' }];
    if (method === 'GET' && p === '/auth/me') return authed ? [200, userOut(me)] : [401, { message: 'Authentication required' }];

    if (!authed && (p.startsWith('/bookings') || p.startsWith('/users/me'))) return [401, { message: 'Authentication required' }];

    if (method === 'POST' && p === '/bookings') {
      const key = headers?.['Idempotency-Key'];
      if (key && state.idem[key]) return [201, publicBooking(state.bookings.find((b) => b.id === state.idem[key]))];
      const t = tripById.get(+body.tripId);
      const quantity = +body.quantity;
      if (!String(body.passengerName ?? '').trim()) return [400, { message: 'Validation failed', details: { passengerName: 'Passenger name is required' } }];
      if (!PHONE.test(normPhone(body.passengerPhone))) return [400, { message: 'Validation failed', details: { passengerPhone: 'A Vietnamese phone number is required' } }];
      if (!Number.isInteger(quantity) || quantity < 1) return [400, { message: 'Validation failed', details: { quantity: 'Quantity must be at least 1' } }];
      if (!t) return [404, { message: 'Trip not found' }];
      if (t.status !== 'SCHEDULED' || t.departureTime <= fmt(new Date())) return [409, { message: 'Trip is not open for booking' }];
      if (t.availableSeats < quantity) return [409, { message: `Not enough seats available (${t.availableSeats} left)` }];
      t.availableSeats -= quantity;
      const b = newBooking(t, { ...body, passengerPhone: normPhone(body.passengerPhone), quantity }, me);
      b.seatsHeld = true;
      state.bookings.push(b);
      if (key) state.idem[key] = b.id;
      return [201, publicBooking(b)];
    }
    m = p.match(/^\/bookings\/(\d+)$/);
    if (m) {
      const b = state.bookings.find((x) => x.id === +m[1] && x.email === me);
      if (!b) return [404, { message: 'Booking not found' }];
      if (method === 'GET') return [200, publicBooking(b)];
      if (method === 'DELETE') {
        const t = tripById.get(b.tripId);
        if (b.status !== 'CONFIRMED') return [409, { message: 'Booking is already cancelled' }];
        if (t.departureTime <= fmt(new Date())) return [409, { message: 'Cannot cancel a booking after departure' }];
        b.status = 'CANCELLED';
        t.availableSeats += b.quantity;
        b.seatsHeld = false;
        return [204];
      }
    }
    if (method === 'GET' && p === '/users/me/bookings') {
      return [200, paged(state.bookings.filter((b) => b.email === me).sort((a, b) => b.bookedAt.localeCompare(a.bookedAt))).map(publicBooking)];
    }
    return [404, { message: 'Not found' }];
  }

  const realFetch = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    const url = typeof input === 'string' ? input : input.url;
    if (!new URL(url, location.origin).pathname.startsWith('/api/')) return realFetch(input, init);
    await new Promise((r) => setTimeout(r, 120 + Math.random() * 230)); // feel like a network
    let body = {};
    try { body = init.body ? JSON.parse(init.body) : {}; } catch { return new Response('{"message":"Malformed JSON"}', { status: 400 }); }
    const [status, data] = route((init.method || 'GET').toUpperCase(), url, body, init.headers);
    save();
    return new Response(status === 204 ? null : JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
  };

  addEventListener('DOMContentLoaded', () => {
    const tag = document.createElement('div');
    tag.textContent = 'Dữ liệu mẫu · demo@busbooking.vn / matkhau123 · mã OTP 123456';
    tag.style.cssText = 'position:fixed;left:12px;bottom:12px;z-index:40;padding:6px 10px;border-radius:6px;background:#fff7e0;color:#7a4b00;border:1px solid #f0d48a;font:12px/1.4 system-ui,sans-serif';
    document.body.append(tag);
  });
})();
