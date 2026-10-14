"""The toy server must never run without auth: through the tunnel that would bypass ArmorIQ."""

from __future__ import annotations

import pytest
from armoriq_spike.settings import SpikeSettings
from armoriq_spike.toy_server import build_server
from pydantic import SecretStr


def test_empty_token_refuses_to_build() -> None:
    with pytest.raises(ValueError, match="without auth"):
        build_server("")


def test_token_turns_auth_on() -> None:
    assert build_server("fake-token").auth is not None


def test_settings_refuse_an_empty_mcp_token() -> None:
    settings = SpikeSettings(_env_file=None, mcp_bearer_token=SecretStr(""))
    with pytest.raises(RuntimeError, match="MCP_BEARER_TOKEN"):
        settings.require_mcp_token()
