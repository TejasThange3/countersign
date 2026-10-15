"""Approver credentials. They can approve held money calls, so they come from the local `.env`
only and refuse to load in CI (AGENTS.md, scope section 4 "Approvals")."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


class ApproverSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    armoriq_api_key: SecretStr = SecretStr("")
    armoriq_admin_email: str = ""
    armoriq_backend_endpoint: str = "https://api.armoriq.ai"
    # Our share of the delegation rate limit (~30-60/min, shared with the bridge's polling).
    approver_calls_per_minute: float = Field(default=30.0, gt=0, le=60)


class ApproverConfigError(RuntimeError):
    pass


def running_in_ci() -> bool:
    """GitHub Actions and most CI systems set CI=true. Anything but empty/0/false counts."""
    return os.environ.get("CI", "").strip().lower() not in ("", "0", "false", "no")


def load_approver_settings() -> ApproverSettings:
    """Load and check the approver settings. Never runs in CI."""
    if running_in_ci():
        raise ApproverConfigError(
            "The approver never runs in CI: its credentials can approve real held calls."
        )
    settings = ApproverSettings()
    missing = [
        name
        for name, value in (
            ("ARMORIQ_API_KEY", settings.armoriq_api_key.get_secret_value()),
            ("ARMORIQ_ADMIN_EMAIL", settings.armoriq_admin_email),
        )
        if not value
    ]
    if missing:
        raise ApproverConfigError(f"Set {', '.join(missing)} in the repo root .env")
    return settings
