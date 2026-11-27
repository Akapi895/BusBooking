"""Exact current controller surface, not a speculative OpenAPI contract."""
import re

ENDPOINTS = {
    ("GET", "/api/locations"), ("GET", "/api/trips"), ("GET", "/api/trips/{id}"),
    ("POST", "/api/bookings"), ("POST", "/api/bookings/{id}/confirm"), ("GET", "/api/bookings/{id}"), ("DELETE", "/api/bookings/{id}"),
    ("GET", "/api/users/me/bookings"), ("GET", "/api/users/me"), ("PUT", "/api/users/me"),
    ("GET", "/api/auth/me"), ("PUT", "/api/users/me/password"),
    *(("POST", "/api/auth/" + action) for action in
      ("register", "login", "verify-email", "resend-verification", "forgot-password", "reset-password", "logout")),
    *((method, "/api/admin/" + resource + suffix)
      for resource in ("operators", "locations", "vehicles", "routes")
      for method, suffix in (("GET", ""), ("POST", ""), ("PUT", "/{id}"))),
    *((method, "/api/admin/trips" + suffix)
      for method, suffix in (("GET", ""), ("POST", ""), ("PUT", "/{id}"), ("DELETE", "/{id}"))),
    ("GET", "/api/admin/bookings"), ("POST", "/api/admin/bookings/{id}/refund"), ("PUT", "/api/admin/users/{id}/role"),
}

REQUIRED_CASES = {
    "functional.auth", "functional.catalog_and_booking", "functional.security_filters_profile", "functional.default_rate_limit",
    "concurrency.last_seats", "concurrency.cancel", "concurrency.admin_booking", "concurrency.unique",
    "concurrency.assignment_status", "concurrency.profile_atomicity", "concurrency.otp", "concurrency.otp_expiry_lock",
    "fault.transaction_rollback", "fault.timeout_retry", "fault.smtp", "fault.db_lock_wait_recovery",
    "fault.postgres_restart", "data.invariants",
}


def canonical(path):
    path = path.split("?", 1)[0]
    return re.sub(r"/\d+(?=/|$)", "/{id}", path)


def verification_code(text):
    # Match the actual SMTP message's code line, not six-digit Instant fractions.
    match = re.search(r"^Mã xác minh email của bạn:\s*([0-9]{6})\s*$", text, re.MULTILINE)
    return match.group(1) if match else None


def reset_code(text):
    match = re.search(r"^Mã đặt lại mật khẩu của bạn:\s*([0-9]{6})\s*$", text, re.MULTILINE)
    return match.group(1) if match else None


def booking_valid(body, user_id, trip_id, quantity, price=None):
    from decimal import Decimal, InvalidOperation
    try:
        # BookingResponse intentionally has no userId; ownership is checked through HTTP + SQL.
        return (body["id"] > 0 and body["tripId"] == trip_id
                and body["quantity"] == quantity and body["status"] in ("HELD", "CONFIRMED")
                and Decimal(str(body["totalAmount"])) == Decimal(str(body["unitPrice"])) * quantity
                and (price is None or Decimal(str(body["unitPrice"])) == Decimal(str(price))))
    except (KeyError, TypeError, InvalidOperation):
        return False
