"""Structured affordances. Canonical IDs only."""

from __future__ import annotations

from typing import Any

from noema_client.types import Affordance


def parse_affordances(rows: list[Any]) -> list[Affordance]:
    out: list[Affordance] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        action = str(row.get("action") or row.get("operation") or row.get("verb") or "").upper()
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
