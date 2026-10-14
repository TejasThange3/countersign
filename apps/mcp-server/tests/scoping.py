"""The booking-scoped tools and valid arguments for each, shared by unit and integration tests.

Every tool listed here takes `guest_id` + `booking_id` and must refuse a booking owned by
another guest with exactly `BOOKING_NOT_FOUND`. Adding a booking-scoped tool means adding it here.
"""

from datetime import timedelta
from typing import Any

from tests.conftest import TODAY

NEW_IN = (TODAY + timedelta(days=120)).isoformat()
NEW_OUT = (TODAY + timedelta(days=122)).isoformat()

BOOKING_SCOPED_TOOLS: dict[str, dict[str, Any]] = {
    "get_booking": {},
    "modify_booking_dates": {"check_in": NEW_IN, "check_out": NEW_OUT},
    "add_booking_note": {"note": "please upgrade me"},
    "request_housekeeping": {"request": "extra towels"},
    "cancel_own_booking": {},
    "issue_refund": {"amount": 50.0, "reason": "test"},
    "apply_comp_credit": {"amount": 50.0, "reason": "test"},
    "waive_fee": {"amount": 50.0, "reason": "test"},
}
