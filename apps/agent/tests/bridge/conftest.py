"""Live tests write real rows and approve real holds, so they run only when asked for
(`-m live`). A plain `pytest` over this folder skips them."""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if "live" in (config.option.markexpr or "").replace("not live", ""):
        return
    skip = pytest.mark.skip(reason="live test: run with -m live")
    for item in items:
        if item.get_closest_marker("live"):
            item.add_marker(skip)
