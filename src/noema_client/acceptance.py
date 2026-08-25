"""Explicitly gated production acceptance workflows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from noema_client.client import NoemaClient
from noema_client.types import ActionProposal, CommandResult, Observation

PRODUCTION_SERVER = "https://noema.guru"


@dataclass(frozen=True)
class AcceptanceError(Exception):
    code: str
    message: str


def validate_materials_gate(*, server: str, world_id: str, ack: str, run_id: str) -> None:
    if server.rstrip("/") != PRODUCTION_SERVER:
        raise AcceptanceError("PRODUCTION_HOST_REQUIRED", f"server must be {PRODUCTION_SERVER}")
    if not re.fullmatch(r"world\.[a-z0-9][a-z0-9._-]{2,127}", world_id):
        raise AcceptanceError("WORLD_PIN_REQUIRED", "pass an explicit canonical world.* id")
    if ack != f"MUTATE {world_id}":
        raise AcceptanceError("ACK_REQUIRED", f"ack must equal MUTATE {world_id}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}", run_id):
        raise AcceptanceError("RUN_ID_INVALID", "run id must be 3-64 lowercase safe characters")


def _available_harvest(obs: Observation, target_id: str | None) -> str:
    candidates = [
        aff
        for aff in obs.affordances
        if aff.available and aff.action.upper() == "HARVEST" and aff.target_id
    ]
    if not candidates:
        raise AcceptanceError("HARVEST_UNAVAILABLE", "no available HARVEST affordance")
    if target_id is None:
        return str(candidates[0].target_id)
    if not any(aff.target_id == target_id for aff in candidates):
        raise AcceptanceError("HARVEST_TARGET_UNAVAILABLE", "requested HARVEST target is unavailable")
    return target_id


def _sequence(result: CommandResult) -> int | None:
    value = (result.observation or {}).get("sequence")
    return value if isinstance(value, int) else None


def _cargo_observed(result: CommandResult) -> bool:
    obs = result.observation or {}
    cargo = obs.get("cargo")
    if isinstance(cargo, (dict, list)) and bool(cargo):
        return True
    return any("cargo" in str(line).lower() for line in (obs.get("lot_lines") or []))


def _construction_observed(result: CommandResult) -> bool:
    raw = result.raw or {}
    events = raw.get("events") or []
    if any(
        isinstance(event, dict)
        and "CONSTRUCT" in str(event.get("event_type") or event.get("type") or "").upper()
        for event in events
    ):
        return True
    consequence = str((result.observation or {}).get("consequence") or "").lower()
    return any(word in consequence for word in ("construct", "built", "created"))


def run_materials_acceptance(
    client: NoemaClient,
    *,
    ready: dict[str, Any],
    world_id: str,
    ack: str,
    run_id: str,
    harvest_target: str | None = None,
    construct_class: str = "workshop",
) -> dict[str, Any]:
    validate_materials_gate(server=client.server, world_id=world_id, ack=ack, run_id=run_id)
    if ready.get("world_id") != world_id:
        raise AcceptanceError("WORLD_MISMATCH", "ready world does not match the pinned world")
    if str(ready.get("status") or "").upper() != "ACTIVE" or str(
        ready.get("settlement_health") or ""
    ).upper() != "HEALTHY":
        raise AcceptanceError("WORLD_NOT_HEALTHY", "world must be ACTIVE and HEALTHY")

    observed = client.observe()
    target = _available_harvest(observed, harvest_target)
    before_sequence = observed.sequence
    harvested = client.act(
        ActionProposal(action="HARVEST", target_id=target, arguments={"amount": 1}),
        idempotency_key=f"accept.materials.{run_id}.harvest",
        request_id=f"accept.materials.{run_id}.harvest",
    )
    if not harvested.ok or harvested.settled is not True:
        raise AcceptanceError("HARVEST_FAILED", "HARVEST did not return settled success")
    harvest_sequence = _sequence(harvested)
    if before_sequence is not None and harvest_sequence is not None and harvest_sequence <= before_sequence:
        raise AcceptanceError("HARVEST_RECEIPT_INVALID", "HARVEST sequence did not advance")
    if not _cargo_observed(harvested):
        raise AcceptanceError("CARGO_NOT_OBSERVED", "HARVEST did not expose cargo evidence")

    constructed = client.act(
        ActionProposal(action="BUILD", arguments={"operation": "CONSTRUCT", "class": construct_class}),
        idempotency_key=f"accept.materials.{run_id}.construct",
        request_id=f"accept.materials.{run_id}.construct",
    )
    if not constructed.ok or constructed.settled is not True:
        raise AcceptanceError("CONSTRUCT_FAILED", "CONSTRUCT did not return settled success")
    construct_sequence = _sequence(constructed)
    if harvest_sequence is not None and construct_sequence is not None and construct_sequence <= harvest_sequence:
        raise AcceptanceError("CONSTRUCT_RECEIPT_INVALID", "CONSTRUCT sequence did not advance")
    if not _construction_observed(constructed):
        raise AcceptanceError("ENTITY_RECEIPT_MISSING", "CONSTRUCT lacked entity receipt evidence")

    return {
        "ok": True,
        "run_id": run_id,
        "world_id": world_id,
        "harvest": {"target_id": target, "settled": True, "sequence": harvest_sequence},
        "construct": {"class": construct_class, "settled": True, "sequence": construct_sequence},
    }
