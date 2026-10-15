"""Shared test setup for every agent test.

- Makes the test-only fakes in tests/voice/fakes.py importable from every test module.
- Live tests (`@pytest.mark.live`) call real services and spend quota, so they run only when
  asked for with `-m live`. A plain `pytest` collects them as skipped.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "voice"))


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if "live" in (config.option.markexpr or "").replace("not live", ""):
        return
    skip = pytest.mark.skip(reason="live test: run with -m live")
    for item in items:
        if item.get_closest_marker("live"):
            item.add_marker(skip)
