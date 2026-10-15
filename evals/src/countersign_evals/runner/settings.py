"""Runner configuration from the repo root `.env` (pydantic-settings)."""

from __future__ import annotations

import importlib
from pathlib import Path

from countersign_agent.contracts import GatewayFactory
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


class RunnerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql+asyncpg://countersign:countersign@localhost:5432/countersign"
    # Same convention as the voice lane's app.py: "module:attribute".
    gateway_factory: str = "countersign_agent.bridge:factory"
    disable_armoriq: bool = False
    # Text-mode endpoint of the voice lane, for the conversation driver.
    agent_text_url: str = "http://localhost:7860/text"
    approval_wait_timeout_s: float = 60.0

    def reset_command(self) -> list[str]:
        return [
            "uv",
            "run",
            "--project",
            str(REPO_ROOT / "apps" / "mcp-server"),
            "hotel-mcp",
            "reset",
            "--yes",
        ]


def load_factory(path: str) -> GatewayFactory:
    """Import "module:attribute". The attribute is a factory, or a zero-argument callable that
    returns one."""
    module_name, sep, attr = path.partition(":")
    if not sep or not attr:
        raise ValueError(f"GATEWAY_FACTORY must look like 'module:attribute', got {path!r}")
    obj = getattr(importlib.import_module(module_name), attr)
    if not hasattr(obj, "open_call") and callable(obj):
        obj = obj()
    if not hasattr(obj, "open_call"):
        raise TypeError(f"{path} is not a GatewayFactory (no open_call)")
    return obj
