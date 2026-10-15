"""GATEWAY_FACTORY=countersign_agent.bridge:factory must load the way the voice app and the
eval runner load it (evals/.../runner/settings.py load_factory): import the module, take the
attribute, call it with no arguments if it isn't a factory itself."""

from __future__ import annotations

import importlib

from countersign_agent.bridge import GovernedGatewayFactory

ENTRY_POINT = "countersign_agent.bridge:factory"


def load_factory(path: str) -> object:
    module_name, _, attr = path.partition(":")
    obj = getattr(importlib.import_module(module_name), attr)
    if not hasattr(obj, "open_call") and callable(obj):
        obj = obj()
    return obj


def test_configured_entry_point_loads_a_gateway_factory() -> None:
    factory = load_factory(ENTRY_POINT)
    assert hasattr(factory, "open_call")
    assert isinstance(factory, GovernedGatewayFactory)
