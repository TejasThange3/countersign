"""Make the test-only fakes in tests/voice/fakes.py importable from every test module."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "voice"))
