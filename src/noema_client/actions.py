"""Preventive proposal validation. NOEMA remains final authority.

Adapted from Zero-State-LLC/Noema src/noema/harness/validate.py.
"""

from __future__ import annotations

from noema_client.errors import FailureClass, NoemaActionRejected
from noema_client.policy import ClientPolicy
from noema_client.types import ActionProposal, Observation, ValidatedAction

_DIRECT = {
    "LOOK": ("LOOK", False),
    "OBSERVE": ("OBSERVE", False),
    "WAIT": ("WAIT", False),
    "ENTER_WORLD": ("ENTER_WORLD", True),
    "LEAVE_WORLD": ("LEAVE_WORLD", False),
    "MOVE": ("MOVE", True),
    "INSPECT": ("INSPECT", False),
    "MESSAGE": ("MESSAGE", True),
    "TRADE": ("TRADE", True),
}

_COMMIT = {
    "REPAIR": "REPAIR",
    "HARVEST": "HARVEST",
    "ORG_CREATE": "ORG_CREATE",
    "ORG_MEMBER_ADD": "ORG_MEMBER_ADD",
    "ORG_MEMBER_REMOVE": "ORG_MEMBER_REMOVE",
    "CONTEST": "CONTEST_DECLARE",
    "CONTEST_DECLARE": "CONTEST_DECLARE",
    "CONTEST_DEFEND": "CONTEST_DEFEND",
    "AGREEMENT": "AGREEMENT_FORM",
    "AGREEMENT_FORM": "AGREEMENT_FORM",
    "AGREEMENT_TERMINATE": "AGREEMENT_TERMINATE",
    "ACCESS": "ACCESS_POLICY",
    "ACCESS_POLICY": "ACCESS_POLICY",
}


def visible_targets(obs: Observation) -> set[str]:
    found: set[str] = set()
    for ent in obs.entities:
        if isinstance(ent, dict) and ent.get("entity_id"):
            found.add(str(ent["entity_id"]))
    loc = obs.location or {}
    for exit_ in loc.get("exits") or []:
        if isinstance(exit_, dict):
            if exit_.get("direction"):
                found.add(str(exit_["direction"]))
            if exit_.get("to_room_id"):
                found.add(str(exit_["to_room_id"]))
    for aff in obs.affordances:
        if aff.target_id:
            found.add(str(aff.target_id))
    return found


def advertised(obs: Observation, action: str) -> bool:
    name = action.upper()
    if name in obs.available_actions:
        return True
    if any(a.action == name for a in obs.affordances):
        return True
    if name in {"ENTER_WORLD", "OBSERVE", "LOOK", "WAIT"}:
        return True
    return False


def validate_proposal(proposal: ActionProposal, obs: Observation, policy: ClientPolicy) -> ValidatedAction:
    action = (proposal.action or "").upper()
    if not action:
        raise NoemaActionRejected("INVALID_PROPOSAL", "missing action", failure=FailureClass.INVALID_PROPOSAL)
    if not policy.permits(action):
        raise NoemaActionRejected("POLICY_DENIED", f"{action} gated by client policy", failure=FailureClass.INVALID_PROPOSAL)
    if not advertised(obs, action):
        raise NoemaActionRejected("INVALID_PROPOSAL", f"{action} is not advertised", failure=FailureClass.INVALID_PROPOSAL)
    args = dict(proposal.arguments or {})
    target = proposal.target_id
    if action in _DIRECT:
        command, mutating = _DIRECT[action]
        if action == "MOVE":
            direction = args.get("direction") or target
            if not direction:
                raise NoemaActionRejected("INVALID_PROPOSAL", "MOVE requires direction", failure=FailureClass.INVALID_PROPOSAL)
            vis = visible_targets(obs)
            if vis and str(direction) not in vis and str(target or "") not in vis:
                if obs.available_actions or obs.entities or (obs.location or {}).get("exits"):
                    raise NoemaActionRejected("INVALID_PROPOSAL", "target not visible", failure=FailureClass.INVALID_PROPOSAL)
            args = {**args, "direction": direction}
        elif action == "INSPECT":
            entity_id = args.get("entity_id") or target
            if entity_id and (obs.entities or obs.affordances) and str(entity_id) not in visible_targets(obs):
                raise NoemaActionRejected("INVALID_PROPOSAL", "target not visible", failure=FailureClass.INVALID_PROPOSAL)
            if entity_id:
                args = {**args, "entity_id": entity_id}
        return ValidatedAction(command=command, arguments=args, mutating=mutating)
    if action in _COMMIT:
        vis = visible_targets(obs)
        if target and vis and str(target) not in vis:
            raise NoemaActionRejected("INVALID_PROPOSAL", "target not visible", failure=FailureClass.INVALID_PROPOSAL)
        mapped = {"operation": _COMMIT[action], **args}
        if target and "entity_id" not in mapped:
            mapped["entity_id"] = target
        return ValidatedAction(command="COMMIT", arguments=mapped, mutating=True)
    raise NoemaActionRejected("INVALID_PROPOSAL", f"unknown action {action}", failure=FailureClass.INVALID_PROPOSAL)
