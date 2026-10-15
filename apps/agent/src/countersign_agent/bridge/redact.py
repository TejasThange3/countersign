"""Clean live responses before they are printed or saved as evidence: redact anything
credential-shaped, and mask identity emails behind placeholders like <guest>."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

SENSITIVE_PARTS = ("key", "token", "secret", "password", "authorization", "jwt", "signature")
REDACTED = "<redacted>"


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: REDACTED if any(part in str(k).lower() for part in SENSITIVE_PARTS) else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def mask_identities(value: Any, mask: Mapping[str, str]) -> Any:
    """Replace each real email (case-insensitive, also inside longer strings) with its
    placeholder. Longest first, so an alias is never half-replaced by a shorter address."""
    pattern = (
        re.compile(
            "|".join(re.escape(e) for e in sorted(mask, key=len, reverse=True) if e),
            re.IGNORECASE,
        )
        if any(mask)
        else None
    )
    lookup = {k.lower(): v for k, v in mask.items()}

    def walk(v: Any) -> Any:
        if isinstance(v, dict):
            return {walk(k): walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, str) and pattern is not None:
            return pattern.sub(lambda m: lookup[m.group(0).lower()], v)
        return v

    return walk(value)
