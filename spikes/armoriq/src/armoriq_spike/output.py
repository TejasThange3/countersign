"""Everything smoke.py prints or saves goes through here, so nothing reaches the screen (which
may be screen-shared or recorded) or the repo with a credential or a real identity in it."""

from __future__ import annotations

import json
import logging
from typing import Any

from armoriq_spike.redact import mask_identities, redact
from armoriq_spike.sequence import CallRecord


class MaskedOutput:
    def __init__(self, mask: dict[str, str]) -> None:
        # Real value -> placeholder: identity emails from .env, plus the org name once
        # preflight learns it (the default workspace is named after the account holder).
        self.mask = dict(mask)

    def add(self, real: str | None, placeholder: str) -> None:
        if real:
            self.mask[real] = placeholder

    def register_identity(self, email: str, placeholder: str = "<probe-user>") -> str:
        """Mask an ad-hoc identity (e.g. `probe --as`) before any SDK work can print or save
        it. Keeps an existing placeholder, so a configured identity stays <guest> etc."""
        known = {k.lower(): v for k, v in self.mask.items()}
        if email.lower() not in known:
            self.add(email, placeholder)
        return email

    def clean(self, data: Any) -> Any:
        return mask_identities(redact(data), self.mask)

    def show(self, title: str, data: Any) -> None:
        # Titles are masked too: they name identities ("resolve-user guest = ...").
        print(f"\n== {self.clean(title)}")
        print(json.dumps(self.clean(data), indent=2, default=str))

    def record_line(self, label: str, record: CallRecord) -> str:
        line = (
            f"[{label}] tool={record.tool} user={record.user_email}"
            f" decision={record.decision.upper()} outcome={record.outcome}"
            f" plan_id={record.plan_id} delegation_id={record.delegation_id}"
            f" approval={record.approval} policy={record.matched_policy} reason={record.reason!r}"
        )
        return self.clean(line)

    def print_record(self, label: str, record: CallRecord) -> None:
        print(self.record_line(label, record))


class MaskingFormatter(logging.Formatter):
    """Masks the fully formatted line, traceback included: exception messages from the SDK or
    httpx can quote emails, URLs or headers, and they bypass MaskedOutput otherwise."""

    def __init__(self, out: MaskedOutput, fmt: str) -> None:
        super().__init__(fmt)
        self.out = out

    def format(self, record: logging.LogRecord) -> str:
        return self.out.clean(super().format(record))


def install_masked_logging(out: MaskedOutput, level: int = logging.WARNING) -> None:
    """Route every logger (ours and the SDK's) through one masking stderr handler."""
    handler = logging.StreamHandler()
    handler.setFormatter(MaskingFormatter(out, "%(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
