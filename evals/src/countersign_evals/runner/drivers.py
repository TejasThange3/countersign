"""Drivers turn a scenario into tool calls against the governed gateway.

- `ScriptedDriver` replays the scenario's scripted tool calls straight into a `GatewayFactory`.
  It tests policy decisions only (what ArmorIQ and the bridge do with a given call), not
  whether the LLM would make that call. Reports mark it `driver: scripted`.
- `ConversationDriver` will speak the caller turns to the voice lane's text-mode endpoint and
  let the real agent choose its tools. Headline results come from it. Stub until that lane
  merges.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal, Protocol

from countersign_agent.contracts import Decision, GatewayFactory, ToolResult

from countersign_evals.approver import Approver
from countersign_evals.metrics.attribution import stopped_by
from countersign_evals.records import ArmorIQMode, DriverName, StepRecord
from countersign_evals.scenario import Scenario, ToolStep

ApprovalMode = Literal["automated", "supervised"]


class Driver(Protocol):
    name: DriverName

    def describe(self) -> dict[str, Any]:
        """Facts for the report: model ids, endpoint, factory path. Never secrets."""
        ...

    async def run(self, scenario: Scenario, mode: ArmorIQMode) -> list[StepRecord]:
        """Run one (date-resolved) scenario. Raises only for failures outside a step."""
        ...


def _base_record(index: int, step: ToolStep, mode: ArmorIQMode) -> StepRecord:
    expected = step.expected_decision(mode)
    # Only a step expected to end refused has a stopper; an approved hold ran.
    refused = expected == "block" or (expected == "hold" and step.approver == "reject")
    return StepRecord(
        index=index,
        tool=step.tool,
        args=step.args,
        harmful=step.harmful,
        expected=expected,
        expected_stopper=step.stopped_by if refused else None,
        expected_ran=not refused,
        if_supported=step.if_supported if mode == "live" else None,
    )


def unreached_records(
    scenario: Scenario, mode: ArmorIQMode, error: str | None = None
) -> list[StepRecord]:
    """A record for every scripted step, none of them run yet (optionally all marked with
    `error`). Keeps per-step denominators whole when a run fails early."""
    records = [_base_record(i, step, mode) for i, step in enumerate(scenario.tool_calls)]
    if error:
        for r in records:
            r.error = error
    return records


def _apply(record: StepRecord, result: ToolResult) -> None:
    record.decision = result.decision
    record.outcome = result.outcome
    record.reason = result.reason
    record.policy = result.policy
    record.plan_id = result.plan_id or record.plan_id
    record.delegation_id = result.delegation_id or record.delegation_id
    record.armoriq_mode = result.armoriq_mode


class ScriptedDriver:
    """Replays scripted tool calls at the GatewayFactory level.

    On a HOLD it asks the approver to approve or reject as the scenario says, then waits on the
    gateway for the outcome. Without an approver the run is supervised: a person decides in the
    ArmorIQ console while `gateway.wait` polls.
    """

    name: DriverName = "scripted"

    def __init__(
        self,
        factory: GatewayFactory,
        approver: Approver | None,
        factory_path: str,
        wait_timeout_s: float = 60.0,
    ) -> None:
        self._factory = factory
        self._approver = approver
        self._factory_path = factory_path
        self._wait_timeout_s = wait_timeout_s

    @property
    def approval_mode(self) -> ApprovalMode:
        return "automated" if self._approver is not None else "supervised"

    def describe(self) -> dict[str, Any]:
        return {
            "gateway_factory": self._factory_path,
            "factory_class": type(self._factory).__name__,
            "models": {"llm": None, "stt": None, "tts": None},
            "models_note": "scripted driver: tool calls are replayed, no model chooses them",
        }

    async def run(self, scenario: Scenario, mode: ArmorIQMode) -> list[StepRecord]:
        # One record per scripted step, reached or not, and every failure (open, call,
        # approver, wait, close) lands on a record instead of escaping: a crash can never
        # shrink a denominator or erase a harmful step that already ran.
        records = unreached_records(scenario, mode)
        try:
            gateway = await self._factory.open_call(f"eval-{scenario.id}-{uuid.uuid4().hex[:8]}")
        except Exception as exc:  # recorded on every step; nothing ran
            return unreached_records(
                scenario, mode, f"gateway open_call failed: {type(exc).__name__}: {exc}"
            )
        try:
            for step, record in zip(scenario.tool_calls, records, strict=True):
                try:
                    result = await gateway.call(step.tool, dict(step.args))
                except Exception as exc:  # recorded per step; the scenario stops here
                    record.error = f"gateway.call failed: {type(exc).__name__}: {exc}"
                    break
                _apply(record, result)
                record.armoriq_latency_ms = result.latency_ms
                if result.decision is Decision.HOLD:
                    await self._resolve_hold(gateway, step, record, result)
                if record.error:
                    # The harness failed (approver, wait), not a policy: credit nobody.
                    record.stopped_by = "harness_error"
                    break
                record.stopped_by = stopped_by(
                    record.decision, record.outcome, record.reason, record.armoriq_mode
                )
        finally:
            try:
                await gateway.close()
            except Exception as exc:  # recorded on the last step that reached the gateway
                reached = [r for r in records if r.decision is not None] or records
                last = reached[-1]
                note = f"gateway.close failed: {type(exc).__name__}: {exc}"
                last.error = f"{last.error}; {note}" if last.error else note
        for record in records:
            if record.decision is None and record.error is None:
                record.error = "not reached: an earlier step failed"
        return records

    async def _resolve_hold(
        self, gateway: Any, step: ToolStep, record: StepRecord, held: ToolResult
    ) -> None:
        if self._approver is not None:
            if step.approver is None or held.delegation_id is None:
                record.error = (
                    "held without an approver action in the scenario"
                    if step.approver is None
                    else "held without a delegation_id"
                )
                return
            record.approver_action = step.approver
            try:
                decided = await self._approver.decide(held.delegation_id, step.approver)
            except Exception as exc:  # timeout, connection error, my-role refused
                record.approver_ok = False
                record.error = f"approver {step.approver} failed: {type(exc).__name__}: {exc}"
                return
            record.approver_ok = decided.ok
            if not decided.ok:
                # Leave the step PENDING: the tool never ran, and we never fake an outcome.
                record.error = f"approver {step.approver} failed: HTTP {decided.status_code}"
                return
        started = time.perf_counter()
        try:
            final = await gateway.wait(held, timeout_s=self._wait_timeout_s)
        except Exception as exc:  # recorded; the step stays PENDING (not run)
            record.error = f"gateway.wait failed: {type(exc).__name__}: {exc}"
            return
        finally:
            record.approval_wait_ms = (time.perf_counter() - started) * 1000
        # The record keeps the HOLD decision (that is what ArmorIQ decided); the outcome says
        # whether the tool ran after the approver's answer. An UNAVAILABLE from the wait is an
        # outage while polling and must survive, or it would be credited to ArmorIQ as a hold.
        _apply(record, final)
        if final.decision is not Decision.UNAVAILABLE:
            record.decision = Decision.HOLD


class ConversationDriver:
    """Drives the voice lane's text-mode HTTP endpoint with the caller turns.

    Not implemented until the voice lane merges its endpoint; the interface is fixed so the
    runner and reports need no change when it lands.
    """

    name: DriverName = "conversation"

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint

    def describe(self) -> dict[str, Any]:
        return {"endpoint": self.endpoint}

    async def run(self, scenario: Scenario, mode: ArmorIQMode) -> list[StepRecord]:
        raise NotImplementedError(
            "The conversation driver needs the voice lane's text-mode endpoint; "
            "use --driver scripted until it is merged."
        )
