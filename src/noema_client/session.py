"""Client-side session: connect, resume, disconnect. Does not delete the Player."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Session:
    server: str
    transport: str
    protocol: str = "agent-protocol/v1"
    world: str | None = None
    player_id: str | None = None
    controller_id: str | None = None
    controller_type: str = "agent"
    seal_sent: bool = False
    cycle: int | None = None
    connected: bool = False
    resume: str = "none"
