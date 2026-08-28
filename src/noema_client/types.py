"""Provider-neutral Controller types. One Player class.

Adapted from Zero-State-LLC/Noema src/noema/harness/types.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from noema_client.errors import FailureClass


@dataclass
class ActionProposal:
    action: str
    target_id: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    reason_summary: str | None = None


@dataclass
class ValidatedAction:
    command: str
    arguments: dict[str, Any]
    mutating: bool


@dataclass
class Affordance:
    action: str
    target_id: str | None = None
    arguments_schema: dict[str, Any] = field(default_factory=dict)
    available: bool = True
    label: str | None = None
    cmd: str | None = None
    hint: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Observation:
    world: str | None = None
    cycle: int | None = None
    sequence: int | None = None
    self_id: str | None = None
    location: dict[str, Any] | None = None
    resources: dict[str, Any] | None = None
    entities: list[Any] = field(default_factory=list)
    players_here: list[Any] = field(default_factory=list)
    services: list[Any] = field(default_factory=list)
    messages: list[Any] = field(default_factory=list)
    trades: list[Any] = field(default_factory=list)
    organizations: list[Any] = field(default_factory=list)
    available_actions: list[str] = field(default_factory=list)
    affordances: list[Affordance] = field(default_factory=list)
    last_consequence: Any = None
    world_status: str | None = None
    world_text: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    signaling_quality: float | None = None
    drift_alerts: list[Any] = field(default_factory=list)
    cascading_risk: float | None = None
    protocol_strength: float | None = None
    compositionality: float | None = None
    reputation_summary: dict[str, Any] | None = None
    active_norms: dict[str, Any] | None = None
    scars: list[Any] = field(default_factory=list)
    historical_context: dict[str, Any] | None = None
    path_dependence_index: float | None = None
    lore_attractors: list[Any] = field(default_factory=list)

    def __str__(self) -> str:
        loc = (self.location or {}).get("name") or "?"
        return f"Observation({self.world} {self.cycle}/{self.sequence} {loc})"


@dataclass
class CommandResult:
    ok: bool
    observation: dict[str, Any] | None
    error: dict[str, Any] | None
    settled: bool | None
    http_status: int | None
    failure: FailureClass | None
    idempotency_key: str
    request_id: str
    world_status: str | None = None
    raw: dict[str, Any] | None = None


@dataclass
class TurnResult:
    ok: bool
    stopped: bool = False
    reason: str | None = None
    failure: FailureClass | None = None
    proposal: ActionProposal | None = None
    result: CommandResult | None = None


class StopReason(str, Enum):
    """Why an autonomous play session stopped. Always reported."""

    ACTION_BOUND = "action_bound"
    DURATION_ELAPSED = "duration_elapsed"
    NO_PROPOSAL = "no_proposal"
    CIRCUIT_BREAKER = "circuit_breaker"
    AUTH_FAILURE = "auth_failure"
    WORLD_INCIDENT = "world_incident"
    WORLD_PAUSED = "world_paused"
    POLICY_REJECTION = "policy_rejection"
    VALIDATION_REJECTION = "validation_rejection"
    SERVER_REJECTION = "server_rejection"
    USER_INTERRUPT = "user_interrupt"


class PlayReport(list):
    """Turn list plus why the session ended.

    Subclasses ``list`` so existing callers that index or len() the return of
    ``play()`` keep working unchanged.
    """

    def __init__(
        self,
        turns: list[TurnResult] | None = None,
        *,
        stop_reason: StopReason | None = None,
        attempted: int = 0,
        succeeded: int = 0,
        rejected: int = 0,
        elapsed_seconds: float = 0.0,
        detail: str | None = None,
    ) -> None:
        super().__init__(turns or [])
        self.stop_reason = stop_reason
        self.attempted = attempted
        self.succeeded = succeeded
        self.rejected = rejected
        self.elapsed_seconds = elapsed_seconds
        self.detail = detail

    @property
    def reason_text(self) -> str:
        base = self.stop_reason.value if self.stop_reason else "unknown"
        return f"{base}: {self.detail}" if self.detail else base

    def summary(self) -> str:
        return (
            f"play finished turns={len(self)} attempted={self.attempted} "
            f"ok={self.succeeded} rejected={self.rejected} "
            f"elapsed={self.elapsed_seconds:.1f}s stop={self.reason_text}"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "turns": len(self),
            "attempted": self.attempted,
            "succeeded": self.succeeded,
            "rejected": self.rejected,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "stop_reason": self.stop_reason.value if self.stop_reason else None,
            "detail": self.detail,
        }
