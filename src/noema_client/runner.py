"""Bounded autonomous loop. No infinite default.

Adapted from Zero-State-LLC/Noema src/noema/harness/loop.py.
"""

from __future__ import annotations

import time
from typing import Any, Protocol

from noema_client.actions import validate_proposal
from noema_client.errors import FailureClass, NoemaActionRejected, NoemaError
from noema_client.observations import prepare_context, to_observation
from noema_client.policy import ClientPolicy
from noema_client.types import ActionProposal, Observation, TurnResult
from noema_client.transport import HttpGateway


class Adapter(Protocol):
    def decide(self, context: dict[str, Any]) -> ActionProposal | None: ...


class CircuitBreaker:
    def __init__(self, max_consecutive_failures: int) -> None:
        self.max_consecutive_failures = max_consecutive_failures
        self.consecutive = 0
        self.tripped = False
        self.reason: str | None = None

    def record_success(self) -> None:
        self.consecutive = 0

    def record_failure(self, reason: str) -> None:
        self.consecutive += 1
        if self.consecutive >= self.max_consecutive_failures:
            self.tripped = True
            self.reason = reason

    def trip(self, reason: str) -> None:
        self.tripped = True
        self.reason = reason


class Runner:
    def __init__(self, gateway: HttpGateway, adapter: Adapter, policy: ClientPolicy | None = None) -> None:
        self.gateway = gateway
        self.adapter = adapter
        self.policy = policy or ClientPolicy()
        self.breaker = CircuitBreaker(self.policy.max_consecutive_failures)
        self.observation: Observation | None = None
        self.memory: list[dict[str, Any]] = []
        self.world_status: str | None = None

    def ingest(self, payload: dict[str, Any] | None, *, consequence: Any = None, world_status: str | None = None) -> Observation:
        self.world_status = world_status or self.world_status
        self.observation = to_observation(payload, last_consequence=consequence, world_status=self.world_status)
        return self.observation

    def turn(self) -> TurnResult:
        if self.breaker.tripped:
            return TurnResult(ok=False, stopped=True, reason=self.breaker.reason)
        obs = self.observation or to_observation({}, world_status=self.world_status)
        context = prepare_context(obs, self.memory, self.policy)
        assert "access_token" not in json_blob(context)
        proposal = self.adapter.decide(context)
        if proposal is None:
            return TurnResult(ok=False, stopped=True, reason="no_proposal")
        try:
            validated = validate_proposal(proposal, obs, self.policy)
        except NoemaActionRejected as exc:
            self.breaker.record_failure(exc.code)
            return TurnResult(ok=False, stopped=self.breaker.tripped, reason=exc.code, failure=exc.failure, proposal=proposal)
        if validated.mutating and (obs.world_status or self.world_status or "").upper() == "PAUSED":
            self.breaker.trip("WORLD_PAUSED")
            return TurnResult(ok=False, stopped=True, failure=FailureClass.WORLD_PAUSED, proposal=proposal)
        if validated.mutating and (obs.world_status or self.world_status or "").upper() == "INCIDENT":
            self.breaker.trip("WORLD_INCIDENT")
            return TurnResult(ok=False, stopped=True, failure=FailureClass.WORLD_INCIDENT, proposal=proposal)
        result = self.gateway.send_command(validated.command, validated.arguments)
        if result.failure == FailureClass.AUTH_REQUIRED and self.policy.stop_on_auth_failure:
            self.breaker.trip("auth_failure")
        elif result.failure == FailureClass.WORLD_INCIDENT:
            self.breaker.trip("WORLD_INCIDENT")
        elif not result.ok:
            self.breaker.record_failure((result.error or {}).get("code") or "rejected")
        else:
            self.breaker.record_success()
            self.ingest(result.observation, consequence=(result.observation or {}).get("consequence"), world_status=result.world_status)
            if self.observation and self.observation.last_consequence:
                self.memory.append({"fact": str(self.observation.last_consequence), "source_sequence": self.observation.sequence})
                self.memory = self.memory[-8:]
        if self.policy.cooldown_seconds > 0:
            time.sleep(self.policy.cooldown_seconds)
        return TurnResult(
            ok=result.ok,
            stopped=self.breaker.tripped,
            reason=self.breaker.reason,
            failure=None if result.ok else result.failure,
            proposal=proposal,
            result=result,
        )


def json_blob(value: Any) -> str:
    import json

    return json.dumps(value, default=str)
