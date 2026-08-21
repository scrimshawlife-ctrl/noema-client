"""Provider-neutral Controller types. One Player class.

Adapted from Zero-State-LLC/Noema src/noema/harness/types.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
