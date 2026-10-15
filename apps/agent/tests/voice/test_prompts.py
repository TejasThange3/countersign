"""The system prompt: dated per call, and silent about the enforcement layer."""

from __future__ import annotations

from datetime import date

from countersign_agent.voice.prompts import system_prompt


def test_prompt_states_todays_date() -> None:
    assert "Today is Thursday, October 15, 2026." in system_prompt(date(2026, 10, 15))


def test_prompt_requires_an_explicit_request_before_acting() -> None:
    # Prompt-only safeguard (a scripted fake LLM can't test model compliance): live, the
    # agent booked the first room option after a "yes" that confirmed the caller's identity.
    text = system_prompt(date(2026, 10, 15))
    assert "clearly asked for that exact action" in text
    assert 'A "yes" to a different question is not that request' in text


def test_prompt_says_nothing_a_caller_could_probe() -> None:
    text = system_prompt(date(2026, 10, 15)).lower()
    for word in ("armoriq", "policy", "policies", "limit", "threshold", "$"):
        assert word not in text
