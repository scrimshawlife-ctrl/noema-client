"""Minimal adapter interface. Model proposes; client transports."""

from __future__ import annotations

from typing import Any, Protocol

from noema_client.types import ActionProposal


class ModelAdapter(Protocol):
    def decide(self, context: dict[str, Any]) -> ActionProposal | None: ...
