"""Server configuration, read from the environment (and `.env` when present)."""

from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_LOCAL_DATABASE_URL = "postgresql+asyncpg://countersign:countersign@localhost:5432/countersign"


def normalize_database_url(url: str) -> str:
    """Make a Postgres URL usable by SQLAlchemy's asyncpg driver.

    Hosts like Neon hand out `postgresql://...?sslmode=require`. asyncpg rejects `sslmode`
    (it wants `ssl`) and SQLAlchemy needs the `+asyncpg` driver suffix, so both are fixed here
    instead of asking whoever deploys to hand-edit the URL.
    """
    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+asyncpg"
    if scheme != "postgresql+asyncpg":
        return url
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key == "sslmode":
            query.append(("ssl", value))
        elif key == "channel_binding":
            # libpq-only option; asyncpg errors on unknown query parameters.
            continue
        else:
            query.append((key, value))
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = _LOCAL_DATABASE_URL
    mcp_bearer_token: str = ""
    port: int = 8000
    host: str = "0.0.0.0"  # noqa: S104 - the server runs in a container and must accept outside traffic

    @field_validator("database_url")
    @classmethod
    def _normalize(cls, value: str) -> str:
        value = value.strip()
        # Seen on Railway: a variable reference to a database service that doesn't exist (or
        # has another name) arrives empty or as the literal reference text.
        if not value or "${{" in value:
            raise ValueError(
                "DATABASE_URL is empty or an unresolved reference "
                f"({value!r}); point it at the Postgres service's DATABASE_URL"
            )
        return normalize_database_url(value)

    @field_validator("mcp_bearer_token")
    @classmethod
    def _strip_token(cls, value: str) -> str:
        # A trailing newline pasted into a host's variables UI would otherwise 401 everything.
        return value.strip()


@lru_cache
def get_settings() -> Settings:
    return Settings()
