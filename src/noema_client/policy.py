"""Controller-local policy. Does not change canonical action semantics.

Adapted from Zero-State-LLC/Noema src/noema/harness/policy.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ClientPolicy:
    allow_trade: bool = True
    allow_repair: bool = True
    allow_harvest: bool = True
    allow_message: bool = True
    allow_attest: bool = True
    allow_org_create: bool = True
    allow_contest: bool = True
    allow_access: bool = True
    stop_on_incident: bool = True
    stop_on_auth_failure: bool = True
    max_consecutive_failures: int = 3
    max_actions: int = 8
    max_actions_per_minute: int | None = None
    cooldown_seconds: float = 0.0
    pacing_mode: str = "TURN"
    allowed_actions: list[str] = field(default_factory=list)
    denied_actions: list[str] = field(default_factory=list)

    def permits(self, action: str) -> bool:
        name = action.upper()
        if name in {a.upper() for a in self.denied_actions}:
            return False
        if self.allowed_actions and name not in {a.upper() for a in self.allowed_actions}:
            if name not in {"LOOK", "OBSERVE", "WAIT", "ENTER_WORLD"}:
                return False
        if name in {"LOOK", "MOVE", "INSPECT", "WAIT", "ENTER_WORLD", "OBSERVE", "LEAVE_WORLD", "ATTEST"}:
            return True
        if name in {"REPAIR", "COMMIT.REPAIR"}:
            return self.allow_repair
        if name in {"HARVEST", "COMMIT.HARVEST"}:
            return self.allow_harvest
        if name == "TRADE":
            return self.allow_trade
        if name == "MESSAGE":
            return self.allow_message
        if name in {
            "BUILD",
            "CONSTRUCT",
            "DISMANTLE",
            "UPGRADE",
            "REPURPOSE",
            "RESTORE",
            "VEST",
            "SHARE",
            "CONNECT",
            "FOCUS",
            "ATTEST",
            "RECONSTRUCT",
            "RECONSTRUCT_PUBLISH",
            "RECONSTRUCT_SUPERSEDE",
        }:
            return True
        if name.startswith("ORG"):
            return self.allow_org_create
        if name.startswith("CONTEST") or name.startswith("AGREEMENT"):
            return self.allow_contest
        if name.startswith("ACCESS"):
            return self.allow_access
        if name == "ATTEST" or name.endswith(".ATTEST"):
            return self.allow_attest
        if "ATTEST" in name:
            return self.allow_attest
        return False
