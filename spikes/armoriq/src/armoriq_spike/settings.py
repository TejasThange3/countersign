"""Spike configuration, read from the repo-root `.env` (never printed)."""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# spikes/armoriq/src/armoriq_spike/settings.py -> repo root is four levels up.
REPO_ROOT = Path(__file__).resolve().parents[4]


class SpikeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    armoriq_api_key: SecretStr = SecretStr("")
    armoriq_agent_name: str = "countersign"
    armoriq_mcp_name: str = "hotel-mcp"
    armoriq_user_unverified: str = "voice-unverified@example.com"
    armoriq_user_guest: str = "voice-guest@example.com"
    armoriq_user_manager: str = "frontdesk-manager@example.com"
    # The org_admin login, used only as the approver in approve-test. Real value lives in .env.
    armoriq_admin_email: str = "admin@example.com"
    # Optional: a dashboard session JWT, only for testing which credentials
    # POST /delegation/approve accepts. The user puts it in .env themselves.
    armoriq_dashboard_jwt: SecretStr = SecretStr("")

    mcp_bearer_token: SecretStr = SecretStr("")
    # The toy server listens on its own port so it never collides with hotel-mcp (8000).
    spike_mcp_port: int = 8765
    # How long smoke.py waits for a human to approve a held call.
    approval_wait_seconds: float = 180.0
    # Delegation endpoints are rate limited (~30-60/min); poll every few seconds.
    approval_poll_seconds: float = 5.0

    def identity_mask(self) -> dict[str, str]:
        """Real identity emails -> placeholders, so committed evidence never names a person."""
        return {
            self.armoriq_user_unverified: "<unverified>",
            self.armoriq_user_guest: "<guest>",
            self.armoriq_user_manager: "<manager>",
            self.armoriq_admin_email: "<admin>",
        }

    def secret_mask(self) -> dict[str, str]:
        """Credential values -> placeholders, for text that redact()'s key check can't see
        (log lines, exception messages that echo a header)."""
        return {
            self.armoriq_api_key.get_secret_value(): "<api-key>",
            self.mcp_bearer_token.get_secret_value(): "<mcp-token>",
            self.armoriq_dashboard_jwt.get_secret_value(): "<jwt>",
        }

    def require_mcp_token(self) -> str:
        token = self.mcp_bearer_token.get_secret_value()
        if not token:
            raise RuntimeError("MCP_BEARER_TOKEN is empty in .env")
        return token

    def require_api_key(self) -> str:
        key = self.armoriq_api_key.get_secret_value()
        if not key:
            raise RuntimeError("ARMORIQ_API_KEY is empty in .env")
        return key
