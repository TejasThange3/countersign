"""The ArmorIQ bridge: the governed tool gateway between the LLM and hotel-mcp."""

from countersign_agent.bridge.gateway import GovernedGateway
from countersign_agent.bridge.gateway_factory import GovernedGatewayFactory
from countersign_agent.bridge.settings import BridgeSettings


def factory() -> GovernedGatewayFactory:
    """Entry point for GATEWAY_FACTORY=countersign_agent.bridge:factory (voice app and eval
    runner): a zero-argument callable returning the factory, configured from .env."""
    return GovernedGatewayFactory()


__all__ = ["BridgeSettings", "GovernedGateway", "GovernedGatewayFactory", "factory"]
