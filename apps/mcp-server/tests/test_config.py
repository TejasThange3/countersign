"""DATABASE_URL normalisation for asyncpg, and CLI safety guards."""

import pytest
from hotel_mcp.cli import main
from hotel_mcp.config import normalize_database_url


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (
            "postgresql://u:p@ep-x.neon.tech/db?sslmode=require&channel_binding=require",
            "postgresql+asyncpg://u:p@ep-x.neon.tech/db?ssl=require",
        ),
        ("postgres://u:p@h:5432/db", "postgresql+asyncpg://u:p@h:5432/db"),
        ("postgresql+asyncpg://u:p@h/db", "postgresql+asyncpg://u:p@h/db"),
        ("sqlite+aiosqlite:///x.db", "sqlite+aiosqlite:///x.db"),
    ],
)
def test_normalize_database_url(given: str, expected: str) -> None:
    assert normalize_database_url(given) == expected


def test_reset_requires_yes_flag() -> None:
    # Exits before touching any database, so this needs no Postgres.
    with pytest.raises(SystemExit) as exc:
        main(["reset"])
    assert exc.value.code == 2
