"""Bounded autonomous loop. No infinite default.

Adapted from Zero-State-LLC/Noema src/noema/harness/loop.py.
"""

from __future__ import annotations

from typing import Any, Protocol

from noema_client.actions import validate_proposal
from noema_client.affordances import proposal_from_affordance
from noema_client.aliases import expand_proposal
from noema_client.errors import FailureClass, NoemaActionRejected
from noema_client.observations import prepare_context, to_observation
from noema_client.policy import ClientPolicy
from noema_client.types import ActionProposal, Observation, TurnResult
from noema_client.transport import CommandTransport


# Rejections that will repeat for the same proposal against the same
# observation. Re-selecting one of these is what let a single bad harvest
# affordance walk a healthy session into the circuit breaker.
DETERMINISTIC_CODES = frozenset(
    {
        "INVALID_PROPOSAL",
        "AMBIGUOUS_TARGET",
        "POLICY_DENIED",
        "FORBIDDEN",
        "NOT_FOUND",
        "INVALID_REQUEST",
        "BUDGET_EXCEEDED",
        "NOT_OBSERVABLE",
        "FORM_FORBIDDEN",
        "CONFLICT",
    }
)

# Failures that are never a stale-affordance race and must not be retried.
NON_TRANSIENT_FAILURES = frozenset(
    {
        FailureClass.AUTH_REQUIRED,
        FailureClass.WORLD_PAUSED,
        FailureClass.WORLD_INCIDENT,
        FailureClass.SEAL,
    }
)


def affordance_signature(row: dict[str, Any] | None) -> str:
    """What the server currently advertises about an affordance.

    A fingerprint stays avoided only while its signature is unchanged. When the
    Worker flips `available`/`reason` — stock regenerating past the executable
    minimum, budget recovering — the action becomes eligible again.
    """
    row = row or {}
    return "|".join(
        str(row.get(key))
        for key in ("available", "reason", "stock_amount", "amount", "requires")
    )


def proposal_fingerprint(proposal: ActionProposal | None) -> str:
    """Stable identity of an attempted action, used to avoid repeating it."""
    if proposal is None:
        return ""
    args = proposal.arguments or {}
    operation = str(args.get("operation") or "").upper()
    target = (
        proposal.target_id
        or args.get("entity_id")
        or args.get("direction")
        or args.get("office_id")
        or ""
    )
    return f"{str(proposal.action or '').upper()}|{operation}|{target}"


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

    def reset(self) -> None:
        self.consecutive = 0
        self.tripped = False
        self.reason = None


class Runner:
    def __init__(
        self,
        gateway: CommandTransport,
        adapter: Adapter,
        policy: ClientPolicy | None = None,
        aliases: dict[str, str] | None = None,
    ) -> None:
        self.gateway = gateway  # CommandTransport: HTTP or WebSocket
        self.adapter = adapter
        self.policy = policy or ClientPolicy()
        self.aliases = dict(aliases or {})
        self.breaker = CircuitBreaker(self.policy.max_consecutive_failures)
        self.observation: Observation | None = None
        self.memory: list[dict[str, Any]] = []
        self.world_status: str | None = None
        # fingerprint -> affordance signature at the moment it failed. The
        # action is skipped only while the server still advertises it the same
        # way, so a genuinely recovered affordance becomes eligible again.
        self.avoid: dict[str, str] = {}
        self._refreshed: set[str] = set()
        self.last_stop_detail: str | None = None

    def ingest(self, payload: dict[str, Any] | None, *, consequence: Any = None, world_status: str | None = None) -> Observation:
        if world_status:
            self.world_status = world_status
        elif payload and isinstance(payload.get("world_status"), str):
            self.world_status = str(payload.get("world_status"))
        self.observation = to_observation(payload, last_consequence=consequence, world_status=self.world_status)
        return self.observation

    def _resume_if_active(self) -> bool:
        look = self.gateway.send_command("LOOK", {})
        status = (look.world_status or "").upper()
        if look.ok and status == "ACTIVE":
            self.breaker.reset()
            self.ingest(
                look.observation,
                consequence=(look.observation or {}).get("consequence"),
                world_status=look.world_status,
            )
            return True
        if look.world_status:
            self.world_status = look.world_status
            if self.observation:
                self.observation.world_status = look.world_status
        return False

    def _mark_avoided(self, proposal: ActionProposal | None) -> None:
        """Remember this action as failed, together with what was advertised."""
        fingerprint = proposal_fingerprint(proposal)
        if not fingerprint:
            return
        signature = ""
        for aff in (self.observation.affordances if self.observation else []) or []:
            raw = aff.raw or {}
            if proposal_fingerprint(proposal_from_affordance(raw)) == fingerprint:
                signature = affordance_signature(raw)
                break
        self.avoid[fingerprint] = signature

    def _refresh_observation(self) -> None:
        """Re-LOOK once so a stale affordance is not retried against old state."""
        try:
            look = self.gateway.send_command("LOOK", {})
        except Exception:  # noqa: BLE001 - a failed refresh must not mask the rejection
            return
        if look.ok and look.observation:
            self.ingest(
                look.observation,
                consequence=(look.observation or {}).get("consequence"),
                world_status=look.world_status,
            )

    def turn(self) -> TurnResult:
        if self.breaker.tripped:
            if self.breaker.reason != "WORLD_INCIDENT" or not self._resume_if_active():
                return TurnResult(ok=False, stopped=True, reason=self.breaker.reason)
        obs = self.observation or to_observation({}, world_status=self.world_status)
        context = prepare_context(obs, self.memory, self.policy, avoid=dict(self.avoid))
        assert "access_token" not in json_blob(context)
        proposal = self.adapter.decide(context)
        if proposal is None:
            return TurnResult(ok=False, stopped=True, reason="no_proposal")
        try:
            proposal = expand_proposal(proposal, self.aliases)
            validated = validate_proposal(proposal, obs, self.policy)
        except NoemaActionRejected as exc:
            self.breaker.record_failure(exc.code)
            self._mark_avoided(proposal)
            self.last_stop_detail = exc.code
            return TurnResult(ok=False, stopped=self.breaker.tripped, reason=exc.code, failure=exc.failure, proposal=proposal)
        if validated.mutating and (obs.world_status or self.world_status or "").upper() == "PAUSED":
            self.breaker.trip("WORLD_PAUSED")
            return TurnResult(ok=False, stopped=True, failure=FailureClass.WORLD_PAUSED, proposal=proposal)
        if validated.mutating and (obs.world_status or self.world_status or "").upper() == "INCIDENT":
            if not self._resume_if_active():
                self.breaker.trip("WORLD_INCIDENT")
                return TurnResult(ok=False, stopped=True, failure=FailureClass.WORLD_INCIDENT, proposal=proposal)
        result = self.gateway.send_command(validated.command, validated.arguments)
        if result.failure == FailureClass.AUTH_REQUIRED and self.policy.stop_on_auth_failure:
            self.breaker.trip("auth_failure")
        elif result.failure == FailureClass.WORLD_INCIDENT:
            if not self._resume_if_active():
                self.breaker.trip("WORLD_INCIDENT")
        elif not result.ok:
            code = (result.error or {}).get("code") or "rejected"
            self.breaker.record_failure(code)
            self.last_stop_detail = code
            fingerprint = proposal_fingerprint(proposal)
            if code in DETERMINISTIC_CODES or result.failure not in NON_TRANSIENT_FAILURES:
                self._mark_avoided(proposal)
            # One refresh per fingerprint: the affordance may simply be stale
            # (stock depleted after the observation). Never a retry loop.
            if (
                fingerprint not in self._refreshed
                and result.failure not in NON_TRANSIENT_FAILURES
            ):
                self._refreshed.add(fingerprint)
                self._refresh_observation()
        else:
            self.breaker.record_success()
            self._refreshed.clear()
            self.last_stop_detail = None
            self.ingest(result.observation, consequence=(result.observation or {}).get("consequence"), world_status=result.world_status)
            if self.observation and self.observation.last_consequence:
                self.memory.append({"fact": str(self.observation.last_consequence), "source_sequence": self.observation.sequence})
                self.memory = self.memory[-8:]
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
