"""Everything the bridge publishes (events, CLI output, evidence, logs) goes through a Masker,
so nothing reaches the dashboard, a screen share or the repo with a credential, an identity or a
guest's email in it. Adapted from spikes/armoriq output.py."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from typing import Any

from countersign_agent.bridge.redact import mask_identities, redact

# Any email left after the known identities are replaced (guest records, tool errors).
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
EMAIL_PLACEHOLDER = "<email>"
# Personal fields a tool argument or result can carry; masked by key, whatever the value.
PERSONAL_KEYS = frozenset({"email", "first_name", "last_name", "phone", "guest_name"})
MASKED = "<masked>"


def _mask_personal(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: MASKED if str(k).lower() in PERSONAL_KEYS else _mask_personal(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_mask_personal(v) for v in value]
    return value


def _mask_emails(value: Any) -> Any:
    if isinstance(value, dict):
        return {_mask_emails(k): _mask_emails(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_emails(v) for v in value]
    if isinstance(value, str):
        return EMAIL.sub(EMAIL_PLACEHOLDER, value)
    return value


class Masker:
    def __init__(self, mask: Mapping[str, str]) -> None:
        # Real value -> placeholder: identity emails and secret values from settings. Empty
        # keys (unset secrets) are dropped so they never match ordinary text.
        self.mask = {k: v for k, v in mask.items() if k}

    def clean(self, data: Any) -> Any:
        data = self._clean_json_text(data)
        # Known identities first, so they keep a readable placeholder like <guest>.
        masked = mask_identities(_mask_personal(redact(data)), self.mask)
        return _mask_emails(masked)

    def _clean_json_text(self, value: Any) -> Any:
        """Tool results travel as JSON text (ToolResult.content), where key-based redaction
        and masking can't see. Each JSON object or list held in a string is decoded, given
        the full clean (nested JSON text included), and encoded again."""
        if isinstance(value, dict):
            return {k: self._clean_json_text(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._clean_json_text(v) for v in value]
        if isinstance(value, str) and value[:1] in ("{", "["):
            try:
                parsed = json.loads(value)
            except ValueError:
                return value
            return json.dumps(self.clean(parsed))
        return value


class MaskingFormatter(logging.Formatter):
    """Masks the fully formatted line, traceback included: exception messages from the SDK or
    httpx can quote emails, URLs or headers."""

    def __init__(self, masker: Masker, fmt: str) -> None:
        super().__init__(fmt)
        self.masker = masker

    def format(self, record: logging.LogRecord) -> str:
        return self.masker.clean(super().format(record))


def install_masked_logging(masker: Masker, level: int = logging.WARNING) -> None:
    """Route every logger (ours and the SDK's) through one masking stderr handler."""
    handler = logging.StreamHandler()
    handler.setFormatter(MaskingFormatter(masker, "%(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
