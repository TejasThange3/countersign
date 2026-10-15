"""LIVE: a real LLM conversation (LLM_PROVIDER, default Groq) in text mode against the
FakeGateway (no ArmorIQ).

Run on purpose only: `uv run --project apps/agent pytest -m live tests/voice/test_live_text.py`.
Needs GROQ_API_KEY (or GEMINI_API_KEY with LLM_PROVIDER=gemini) in .env. Spends LLM quota,
no ElevenLabs credits.
"""

from __future__ import annotations

import pytest
from countersign_agent.contracts import Decision, Outcome
from countersign_agent.voice.config import AgentSettings
from countersign_agent.voice.fake_gateway import FakeGatewayFactory
from countersign_agent.voice.text_mode import TextSession

pytestmark = pytest.mark.live


async def test_availability_then_small_refund() -> None:
    settings = AgentSettings()
    key = settings.groq_api_key if settings.llm_provider == "groq" else settings.gemini_api_key
    if not key:
        pytest.skip(f"no API key for LLM_PROVIDER={settings.llm_provider}")
    factory = FakeGatewayFactory()
    session = await TextSession.open("live-text", factory, settings)
    try:
        r1 = await session.send(
            "Hi, do you have a room for two people from November 2nd to November 4th, 2026?"
        )
        print("turn 1:", r1.model_dump_json(indent=1))
        assert any(r.tool == "check_availability" for r in r1.tool_results)
        assert r1.messages and not r1.errors
        assert r1.models

        r2 = await session.send(
            "Also, I'm already verified, booking LRK-1001, last name Rivera. "
            "Please refund 40 dollars on booking 1001 because the minibar charge was wrong."
        )
        r3 = r2
        if not any(r.tool == "issue_refund" for r in r2.tool_results):
            # The model may verify first; one follow-up turn is fair.
            r3 = await session.send("Yes, please go ahead with the 40 dollar refund now.")
        print("turn 2:", r2.model_dump_json(indent=1))
        print("turn 3:", r3.model_dump_json(indent=1))
        refunds = [r for r in r2.tool_results + r3.tool_results if r.tool == "issue_refund"]
        assert refunds, "the model never called issue_refund"
        assert refunds[-1].decision is Decision.ALLOW
        assert refunds[-1].outcome is Outcome.RAN
        assert r3.messages and not r3.errors
    finally:
        await session.close()
