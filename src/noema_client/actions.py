"""Preventive proposal validation. NOEMA remains final authority.

Adapted from Zero-State-LLC/Noema src/noema/harness/validate.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

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

# Operations whose target names a visible world entity. Everything else in
# _COMMIT targets an office, player, org or agreement, and must not be run
# through the entity resolver.
_ENTITY_TARGET_OPS = {
    "HARVEST",
    "REPAIR",
    "DISMANTLE",
    "UPGRADE",
    "REPURPOSE",
    "RESTORE",
    "VEST",
    "SHARE",
    "CONNECT",
    "RECONSTRUCT",
    "ATTEST",
}

_BUILD = {
    "CONSTRUCT",
    "DISMANTLE",
    "UPGRADE",
    "REPURPOSE",
    "RESTORE",
    "VEST",
    "SHARE",
    "CONNECT",
}

_COMMIT = {
    "REPAIR": "REPAIR",
    "HARVEST": "HARVEST",
    "ORG_CREATE": "ORG_CREATE",
    "ORG_MEMBER_ADD": "ORG_MEMBER_ADD",
    "ORG_MEMBER_REMOVE": "ORG_MEMBER_REMOVE",
    "ORG_OFFICE_CREATE": "ORG_OFFICE_CREATE",
    "ORG_OFFICE_ASSIGN": "ORG_OFFICE_ASSIGN",
    "ORG_OFFICE_VACATE": "ORG_OFFICE_VACATE",
    "ORG_OFFICE_RETIRE": "ORG_OFFICE_RETIRE",
    "ORG_OFFICE_ACT": "ORG_OFFICE_ACT",
    "ORG_EMERGENCY_ACTIVATE": "ORG_EMERGENCY_ACTIVATE",
    "ORG_EMERGENCY_REVOKE": "ORG_EMERGENCY_REVOKE",
    "ORG_SUCCESSION_DESIGNATE": "ORG_SUCCESSION_DESIGNATE",
    "ORG_SUCCESSION_CONSENT": "ORG_SUCCESSION_CONSENT",
    "ORG_SUCCESSION_RULE": "ORG_SUCCESSION_RULE",
    "CONTEST": "CONTEST_DECLARE",
    "CONTEST_DECLARE": "CONTEST_DECLARE",
    "CONTEST_DEFEND": "CONTEST_DEFEND",
    "CONTEST_WITHDRAW": "CONTEST_WITHDRAW",
    "AGREEMENT": "AGREEMENT_FORM",
    "AGREEMENT_FORM": "AGREEMENT_FORM",
    "AGREEMENT_TERMINATE": "AGREEMENT_TERMINATE",
    "ACCESS": "ACCESS_POLICY",
    "ACCESS_POLICY": "ACCESS_POLICY",
    "FOCUS": "FOCUS",
    "ATTEST": "ATTEST",
    "RECONSTRUCT": "RECONSTRUCT",
    "RECONSTRUCT_PUBLISH": "RECONSTRUCT_PUBLISH",
    "RECONSTRUCT_SUPERSEDE": "RECONSTRUCT_SUPERSEDE",
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


def _normalize_label(raw: str) -> str:
    """Case- and separator-insensitive label key.

    `-`, `_` and whitespace are treated alike so an advertised `salvage-cache`
    matches a typed `salvage cache`. This never widens the candidate set beyond
    what the observation already made visible.
    """
    return re.sub(r"[\s_-]+", " ", str(raw or "").strip().lower()).strip()


@dataclass(frozen=True)
class TargetResolution:
    ok: bool
    entity_id: str | None = None
    code: str | None = None
    message: str | None = None
    choices: tuple[str, ...] = field(default_factory=tuple)


def _visible_entity_index(obs: Observation) -> tuple[set[str], dict[str, set[str]]]:
    """Visible entity ids, and normalized label -> set of entity ids.

    Only the current observation is consulted: its entities, its location
    entities, and its affordances. Nothing else can become a target.
    """
    ids: set[str] = set()
    by_label: dict[str, set[str]] = {}

    def note(entity_id: Any, *labels: Any) -> None:
        if not entity_id:
            return
        eid = str(entity_id)
        ids.add(eid)
        for label in labels:
            key = _normalize_label(label) if label else ""
            if key:
                by_label.setdefault(key, set()).add(eid)

    for ent in list(obs.entities or []) + list((obs.location or {}).get("entities") or []):
        if isinstance(ent, dict):
            note(ent.get("entity_id"), ent.get("label"), ent.get("target_label"))
    for aff in obs.affordances or []:
        raw = aff.raw or {}
        note(aff.target_id, raw.get("target_label"), raw.get("label"))
    return ids, by_label


def resolve_visible_entity(obs: Observation, raw: str) -> TargetResolution:
    """Canonical, ambiguity-aware target resolver for entity-targeted actions.

    Exact entity id wins. A unique exact label resolves. An ambiguous label is
    an explicit error rather than a silent pick, and anything not visible in
    this observation stays rejected.
    """
    needle = str(raw or "").strip()
    if not needle:
        return TargetResolution(False, code="INVALID_PROPOSAL", message="target required")
    ids, by_label = _visible_entity_index(obs)
    if needle in ids:
        return TargetResolution(True, entity_id=needle)
    matches = by_label.get(_normalize_label(needle)) or set()
    if len(matches) == 1:
        return TargetResolution(True, entity_id=next(iter(matches)))
    if len(matches) > 1:
        return TargetResolution(
            False,
            code="AMBIGUOUS_TARGET",
            message=f"{needle!r} matches more than one visible target",
            choices=tuple(sorted(matches)),
        )
    if needle.startswith("entity.") and not ids:
        # No entity view in this observation at all; leave the id for the server.
        return TargetResolution(True, entity_id=needle)
    return TargetResolution(False, code="INVALID_PROPOSAL", message="target not visible")


def _require_visible_entity(obs: Observation, raw: str) -> str:
    resolved = resolve_visible_entity(obs, raw)
    if resolved.ok and resolved.entity_id:
        return resolved.entity_id
    raise NoemaActionRejected(
        resolved.code or "INVALID_PROPOSAL",
        resolved.message or "target not visible",
        failure=FailureClass.INVALID_PROPOSAL,
    )


def _resolve_visible_entity_id(obs: Observation, raw: str) -> str:
    resolved = resolve_visible_entity(obs, raw)
    return resolved.entity_id if resolved.ok and resolved.entity_id else str(raw or "").strip()


def _player_recipient(raw: str) -> str:
    handle = str(raw or "").strip()
    if not handle:
        return handle
    if handle.startswith(("player.", "entity.", "org.", "ctrl.")):
        return handle
    return f"player.{handle}"


def advertised(obs: Observation, action: str, operation: str | None = None) -> bool:
    names = {action.upper()}
    if operation:
        names.add(operation.upper())
    if "BUILD" in names:
        names |= set(_BUILD)
    if names & {a.upper() for a in obs.available_actions}:
        return True
    for aff in obs.affordances:
        aff_op = str((aff.raw or {}).get("operation") or aff.action or "").upper()
        if aff.action in names or aff_op in names:
            return True
    if names & {"ENTER_WORLD", "OBSERVE", "LOOK", "WAIT"}:
        return True
    return False


def _resolve_entity_argument(
    obs: Observation, mapped: dict[str, Any], target: str | None
) -> dict[str, Any]:
    """Resolve an entity-targeted operation's target to a canonical entity id.

    Non-entity operations keep the previous visible-target check so office,
    player and agreement targets behave exactly as before.
    """
    op = str(mapped.get("operation") or "").upper()
    if op in _ENTITY_TARGET_OPS:
        raw = mapped.get("entity_id") or target
        if raw:
            mapped["entity_id"] = _require_visible_entity(obs, str(raw))
        return mapped
    vis = visible_targets(obs)
    if target and vis and str(target) not in vis:
        raise NoemaActionRejected("INVALID_PROPOSAL", "target not visible", failure=FailureClass.INVALID_PROPOSAL)
    return mapped


def validate_proposal(proposal: ActionProposal, obs: Observation, policy: ClientPolicy) -> ValidatedAction:
    action = (proposal.action or "").upper()
    if not action:
        raise NoemaActionRejected("INVALID_PROPOSAL", "missing action", failure=FailureClass.INVALID_PROPOSAL)
    args = dict(proposal.arguments or {})
    args.pop("line", None)
    operation = str(args.get("operation") or "").upper()
    if not policy.permits(action) and not (operation and policy.permits(operation)):
        raise NoemaActionRejected("POLICY_DENIED", f"{action} gated by client policy", failure=FailureClass.INVALID_PROPOSAL)
    if not advertised(obs, action, operation or None):
        raise NoemaActionRejected("INVALID_PROPOSAL", f"{action} is not advertised", failure=FailureClass.INVALID_PROPOSAL)
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
            if entity_id:
                args = {**args, "entity_id": _require_visible_entity(obs, str(entity_id))}
        elif action == "MESSAGE":
            recipient = args.get("recipient_id") or args.get("handle") or target
            text = args.get("text") or (args.get("message") if isinstance(args.get("message"), str) else None)
            if recipient:
                args["recipient_id"] = _player_recipient(str(recipient))
            if text:
                args["text"] = text
        return ValidatedAction(command=command, arguments=args, mutating=mutating)
    build_op = operation if operation in _BUILD else (action if action in _BUILD else None)
    if action == "BUILD" or build_op:
        mapped = {**args, "operation": build_op or "CONSTRUCT"}
        mapped = _resolve_entity_argument(obs, mapped, target)
        if target and "entity_id" not in mapped and mapped["operation"] != "CONSTRUCT":
            mapped["entity_id"] = target
        return ValidatedAction(command="BUILD", arguments=mapped, mutating=True)
    if action in _COMMIT or operation in _COMMIT:
        op = _COMMIT.get(operation) or _COMMIT.get(action)
        if not op:
            raise NoemaActionRejected("INVALID_PROPOSAL", f"unknown action {action}", failure=FailureClass.INVALID_PROPOSAL)
        mapped = {**args, "operation": op}
        if target and "entity_id" not in mapped:
            mapped["entity_id"] = target
        mapped = _resolve_entity_argument(obs, mapped, target)
        return ValidatedAction(command="COMMIT", arguments=mapped, mutating=True)
    raise NoemaActionRejected("INVALID_PROPOSAL", f"unknown action {action}", failure=FailureClass.INVALID_PROPOSAL)
