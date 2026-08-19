"""Controller-local telemetry. Never records credentials."""

from __future__ import annotations

from typing import Any

from noema_client.redaction import redact_mapping


class Telemetry:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self._secrets: list[str] = []

    def remember_secret(self, value: str | None) -> None:
        if value and value not in self._secrets:
            self._secrets.append(value)

    def record(self, **fields: Any) -> dict[str, Any]:
        forbidden = {"token", "access_token", "refresh_token", "authorization", "secret"}
        clean = {k: v for k, v in fields.items() if k.lower() not in forbidden}
        event = redact_mapping(clean, self._secrets)
        if not isinstance(event, dict):
            event = {"event": event}
        self.events.append(event)
        return event
