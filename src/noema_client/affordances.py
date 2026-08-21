"""Structured affordances. Canonical IDs only. Never `arguments.line`."""

from __future__ import annotations

from typing import Any

from noema_client.types import ActionProposal, Affordance

# LOOK fields the Worker puts on ObservationAffordance. RFC-0120: copy these, not line.
ARGUMENT_KEYS = (
    "operation",
    "extent",
    "track",
    "clear",
    "class",
    "subject_id",
    "subject_entity_id",
    "archive_claim",
    "org_id",
    "player_id",
    "dest",
    "contest_form",
    "target",
    "contest_id",
    "stake",
    "agreement_type",
    "party_ids",
    "agreement_id",
    "agreement_reason",
    "scope",
    "mode",
    "applies_to",
    "direction",
    "acting_for",
    "office_id",
    "subject_ref",
    "claim",
    "visibility",
    "reconstruction_id",
    "evidence",
    "template_id",
    "target_ref",
    "emergency_scope_id",
    "successors",
    "rule_id",
    "entity_id",
    "amount",
)


def arguments_from_affordance(row: dict[str, Any]) -> dict[str, Any]:
    """Copy structured LOOK fields. Never `line`. Never unavailable-copy `reason`."""
    out: dict[str, Any] = {}
    for key in ARGUMENT_KEYS:
        if key not in row:
            continue
        value = row[key]
        if value is None:
            continue
        out[key] = value
    if "agreement_reason" in out and "reason" not in out:
        out["reason"] = out["agreement_reason"]
    if "subject_id" in out and "subject_entity_id" not in out:
        out["subject_entity_id"] = out["subject_id"]
    out.pop("line", None)
    return out


def proposal_from_affordance(row: dict[str, Any]) -> ActionProposal | None:
    operation = str(row.get("operation") or "").upper()
    action = str(row.get("action") or operation or row.get("verb") or "").upper()
    if not action:
        return None
    args = arguments_from_affordance(row)
    if operation:
        args.setdefault("operation", operation)
        action = operation
    target = row.get("target_id") or row.get("entity_id")
    return ActionProposal(action=action, target_id=str(target) if target else None, arguments=args)


def parse_affordances(rows: list[Any]) -> list[Affordance]:
    out: list[Affordance] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        action = str(row.get("operation") or row.get("action") or row.get("verb") or "").upper()
        if not action:
            continue
        out.append(
            Affordance(
                action=action,
                target_id=row.get("target_id") or row.get("entity_id"),
                arguments_schema=row.get("arguments_schema") if isinstance(row.get("arguments_schema"), dict) else {},
                available=bool(row.get("available", True)),
                label=row.get("label"),
                cmd=row.get("cmd"),
                raw=row,
            )
        )
    return out
