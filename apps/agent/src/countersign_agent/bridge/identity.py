"""Who the caller is, as far as the bridge knows. The model never decides this (product rule 3).

A call starts unverified. One successful `verify_guest` makes it that guest for the rest of the
call. Staff identity is never granted over the phone, so there is no state for it.
"""

from __future__ import annotations

from enum import StrEnum


class Verify(StrEnum):
    """What a verify_guest result means for the call's identity."""

    SWITCHED = "switched"  # unverified -> this guest
    SAME_GUEST = "same_guest"  # already this guest: nothing changes
    OTHER_GUEST = "other_guest"  # already verified as someone else: refused
    FAILED = "failed"  # wrong reference or name


class CallIdentity:
    def __init__(self, max_failed_verifies: int) -> None:
        self.max_failed_verifies = max_failed_verifies
        self.guest_id: int | None = None
        self.failed_verifies = 0

    @property
    def verified(self) -> bool:
        return self.guest_id is not None

    @property
    def locked_out(self) -> bool:
        """ArmorIQ has no per-caller rate limit, so brute-forcing booking references is
        stopped here: after N failures in one call, verify_guest is not even attempted."""
        return self.failed_verifies >= self.max_failed_verifies

    def record_verify(self, verified: bool, guest_id: int | None) -> Verify:
        if not verified or guest_id is None:
            self.failed_verifies += 1
            return Verify.FAILED
        if self.guest_id is None:
            self.guest_id = guest_id
            return Verify.SWITCHED
        # A caller can't pivot to another guest's account mid-call.
        return Verify.SAME_GUEST if guest_id == self.guest_id else Verify.OTHER_GUEST
