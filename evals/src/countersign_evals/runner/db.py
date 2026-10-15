"""Database access for the runner: reset to the seed state, then read rows for the diff.

The runner never writes rows itself. Reset goes through `hotel-mcp reset --yes` (the same code
path a developer uses), and the probe only selects from the tables in TABLE_COLUMNS.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from countersign_evals.scenario import TABLE_COLUMNS

Row = dict[str, Any]


class DbReset(Protocol):
    async def reset(self) -> None: ...


class DbProbe(Protocol):
    async def rows(self, table: str, where: Mapping[str, Any]) -> list[Row]: ...


class CommandReset:
    """Runs a reset command (default: `hotel-mcp reset --yes` in apps/mcp-server)."""

    def __init__(
        self,
        command: Sequence[str],
        database_url: str | None = None,
        cwd: Path | None = None,
        timeout_s: float = 120.0,
    ) -> None:
        self.command = list(command)
        self.database_url = database_url
        self.cwd = cwd
        self.timeout_s = timeout_s

    async def reset(self) -> None:
        # Pass the probe's DATABASE_URL explicitly: hotel-mcp reads its own .env relative to
        # its working directory, so without this the reset could wipe a different database
        # from the one the probe then scores.
        env = dict(os.environ)
        if self.database_url is not None:
            env["DATABASE_URL"] = self.database_url
        # Fixed argv from settings, no shell, so nothing from a scenario reaches the command.
        proc = await asyncio.create_subprocess_exec(
            *self.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            cwd=self.cwd,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), self.timeout_s)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(f"DB reset timed out after {self.timeout_s}s") from None
        if proc.returncode != 0:
            tail = out.decode(errors="replace")[-800:]
            raise RuntimeError(f"DB reset failed (exit {proc.returncode}): {tail}")


def _coerce(column: str, value: Any) -> Any:
    """asyncpg is strict about parameter types: scenario dates arrive as ISO strings and
    amounts as plain numbers, but the columns are DATE and NUMERIC."""
    if column in {"check_in", "check_out"} and isinstance(value, str):
        return date.fromisoformat(value)
    if column == "amount" and isinstance(value, int | float) and not isinstance(value, bool):
        return Decimal(str(value))
    return value


class PostgresProbe:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @classmethod
    def from_url(cls, database_url: str) -> PostgresProbe:
        return cls(create_async_engine(database_url, pool_size=1))

    async def rows(self, table: str, where: Mapping[str, Any]) -> list[Row]:
        columns = TABLE_COLUMNS.get(table)
        if columns is None:
            raise ValueError(f"table {table!r} is not readable by the probe")
        unknown = set(where) - columns
        if unknown:
            raise ValueError(f"unknown columns for {table}: {sorted(unknown)}")
        # Table and column names come only from the TABLE_COLUMNS allowlist; values are bound.
        select_list = ", ".join(sorted(columns))
        clauses = [f"{c} = :{c}" if v is not None else f"{c} IS NULL" for c, v in where.items()]
        sql = f"SELECT {select_list} FROM {table}"  # noqa: S608 - identifiers from allowlist only
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        params = {c: _coerce(c, v) for c, v in where.items() if v is not None}
        stmt = text(sql).bindparams(*(bindparam(c) for c in params))
        async with self._engine.connect() as conn:
            result = await conn.execute(stmt, params)
            return [dict(r._mapping) for r in result]

    async def close(self) -> None:
        await self._engine.dispose()
