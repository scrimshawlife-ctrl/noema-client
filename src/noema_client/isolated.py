"""Admitted isolated hosted worlds. Never Perihelion.

Mirrors Zero-State-LLC/Noema workers/noema/src/test-world.ts admitTestWorldId.
The official client does not mint Admin sessions and does not persist Admin material.
"""

from __future__ import annotations

import re

from noema_client.errors import FailureClass, NoemaAuthError, NoemaError

ISOLATED_PREFIX = "test.hosted-canonical."
ISOLATED_COMMAND_PATH = "/v1/operator/test-world/command"
ADMIN_HEADER = "X-Noema-Admin-Token"
_SUFFIX_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,47}$", re.I)


def is_isolated_world(world_id: str | None) -> bool:
    return str(world_id or "").startswith(ISOLATED_PREFIX)


def looks_like_jwt(value: str | None) -> bool:
    raw = str(value or "").strip()
    parts = raw.split(".")
    return len(parts) == 3 and all(parts)


def admit_isolated_world_id(raw: str | None) -> str:
    world_id = str(raw or "").strip()
    if not world_id:
        raise NoemaError("WORLD_FORBIDDEN", "isolated attach requires test.hosted-canonical.<suffix>")
    if (
        world_id in {"world-01", "world.perihelion-reach"}
        or world_id.startswith("world.perihelion")
    ):
        raise NoemaError("WORLD_FORBIDDEN", "that world is not admitted for isolated verification")
    if not world_id.startswith(ISOLATED_PREFIX):
        raise NoemaError("WORLD_FORBIDDEN", "world_id must be test.hosted-canonical.<suffix>")
    suffix = world_id[len(ISOLATED_PREFIX) :]
    if not suffix or suffix.startswith(".") or suffix.endswith(".") or ".." in suffix:
        raise NoemaError("WORLD_FORBIDDEN", "invalid test world suffix")
    if not _SUFFIX_RE.match(suffix):
        raise NoemaError("WORLD_FORBIDDEN", "invalid test world suffix")
    return world_id


def require_isolated_admin_header(token: str | None) -> str:
    """Signed admin JWT only. Never accept or store the raw operator secret."""
    raw = str(token or "").strip()
    if not raw:
        raise NoemaAuthError(
            "ADMIN_REQUIRED",
            "isolated attach needs a signed admin JWT in NOEMA_ADMIN_TOKEN (not stored)",
            failure=FailureClass.AUTH_REQUIRED,
        )
    if not looks_like_jwt(raw):
        raise NoemaAuthError(
            "ADMIN_REQUIRED",
            "NOEMA_ADMIN_TOKEN must be a signed admin JWT, not ADMIN_OPERATOR_TOKEN",
            failure=FailureClass.AUTH_REQUIRED,
        )
    return raw
