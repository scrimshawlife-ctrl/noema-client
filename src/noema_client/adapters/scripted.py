"""Deterministic controllers. No vendor model SDK.

Adapted from Zero-State-LLC/Noema src/noema/harness/adapters.py.
"""

from __future__ import annotations

import re
from typing import Any

from noema_client.types import ActionProposal

_DIRECTIONS = ("north", "south", "east", "west", "up", "down", "in", "out")
_MOVE_DIR = re.compile(r"\bmove\s+(north|south|east|west|up|down|in|out)\b", re.IGNORECASE)


class ScriptedAdapter:
    def __init__(self, steps: list[ActionProposal]) -> None:
        self._steps = list(steps)

    def decide(self, _context: dict[str, Any]) -> ActionProposal | None:
        if not self._steps:
            return None
        return self._steps.pop(0)


def _quiet_room(canonical: dict[str, Any]) -> bool:
    for ent in canonical.get("entities") or []:
        if not isinstance(ent, dict):
            continue
        if ent.get("repairable") or ent.get("harvestable"):
            return False
        cond = ent.get("condition")
        if isinstance(cond, (int, float)) and cond < 70:
            return False
    return True


def move_direction(aff: dict[str, Any]) -> str | None:
    tid = aff.get("target_id")
    if isinstance(tid, str) and tid.lower() in _DIRECTIONS:
        return tid.lower()
    for field in (aff.get("cmd"), aff.get("label"), aff.get("target_label")):
        match = _MOVE_DIR.search(str(field or ""))
        if match:
            return match.group(1).lower()
    return None


class FirstValidAffordanceAdapter:
    def decide(self, context: dict[str, Any]) -> ActionProposal | None:
        canonical = context.get("canonical") or {}
        policy = (context.get("system") or {}).get("permits") or {}
        if _quiet_room(canonical):
            return ActionProposal(action="WAIT")
        for aff in canonical.get("affordances") or []:
            if not aff.get("available", True):
                continue
            action = str(aff.get("action") or aff.get("operation") or "").upper()
            if not action:
                continue
            if action == "REPAIR" and policy.get("repair") is False:
                continue
            if action == "HARVEST" and policy.get("harvest") is False:
                continue
            args: dict[str, Any] = {}
            if action == "MOVE":
                direction = move_direction(aff)
                if not direction:
                    continue
                args["direction"] = direction
            return ActionProposal(action=action, target_id=aff.get("target_id"), arguments=args)
        available = list(canonical.get("available_actions") or [])
        if "WAIT" in available or _quiet_room(canonical):
            return ActionProposal(action="WAIT")
        if "LOOK" in available or not available:
            return ActionProposal(action="LOOK")
        return ActionProposal(action=str(available[0]))
