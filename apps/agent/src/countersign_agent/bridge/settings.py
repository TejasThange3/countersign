"""Bridge configuration, read from the repo-root `.env` (never printed)."""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/agent/src/countersign_agent/bridge/settings.py -> repo root is five levels up.
REPO_ROOT = Path(__file__).resolve().parents[5]


class BridgeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    armoriq_api_key: SecretStr = SecretStr("")
    armoriq_agent_name: str = "countersign"
    armoriq_mcp_name: str = "hotel-mcp"
    # ArmorIQ identities (org members, so each gets its own member rule in the policy).
    armoriq_user_unverified: str = "voice-unverified@example.com"
    armoriq_user_guest: str = "voice-guest@example.com"
    armoriq_user_manager: str = "frontdesk-manager@example.com"
    # Only the live test uses it, as the approver of held calls.
    armoriq_admin_email: str = "admin@example.com"
    # Baseline mode: same gateway, no ArmorIQ calls, every tool runs.
    disable_armoriq: bool = False

    mcp_url: str = "http://localhost:8000/mcp"
    mcp_bearer_token: SecretStr = SecretStr("")

    # ArmorIQ has no per-caller rate limit, so the bridge counts failed verify_guest calls.
    armoriq_verify_max_attempts: int = 3
    # Delegation endpoints are rate limited (~30-60/min); poll every few seconds.
    armoriq_approval_poll_seconds: float = 5.0
    # One plan covers the whole phone call; the token must outlive the longest call.
    armoriq_session_validity_seconds: int = 3600

    def identity_mask(self) -> dict[str, str]:
        """Real identity emails -> placeholders, so events and evidence never name a person."""
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
        }

    def require_api_key(self) -> str:
        key = self.armoriq_api_key.get_secret_value()
        if not key:
            raise RuntimeError("ARMORIQ_API_KEY is empty in .env")
        return key

    def require_mcp_token(self) -> str:
        token = self.mcp_bearer_token.get_secret_value()
        if not token:
            raise RuntimeError("MCP_BEARER_TOKEN is empty in .env")
        return token
