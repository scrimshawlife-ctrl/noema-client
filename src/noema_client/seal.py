"""Published sealed prompt. Official client sends the hash, never operator goals.

Adapted from Zero-State-LLC/Noema src/noema/harness/seal.py.
Vendored prompt bytes match Specs AGENT-SEAL-S0 / RFC-0115.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from noema_client.discovery import Discovery
from noema_client.errors import NoemaSealError
from noema_client.isolated import is_isolated_world

PROMPT_PATH = Path(__file__).with_name("data") / "sealed-prompt-s0.txt"
FORBIDDEN_FLAG_NAMES = ("goal", "prompt", "system", "brief", "hidden_prompt")
SEAL_HEADER = "X-Noema-Seal"
PUBLISHED_LIVE_HASH = "sha256:9b9c211c156a9b49e700fa39e409733099a38df9d95c7f6fb90ca3e9e740a395"


def sealed_prompt_hash() -> str:
    if PROMPT_PATH.is_file():
        return "sha256:" + hashlib.sha256(PROMPT_PATH.read_bytes()).hexdigest()
    return PUBLISHED_LIVE_HASH


def refused_play_flag(namespace: object) -> str | None:
    for name in FORBIDDEN_FLAG_NAMES:
        if getattr(namespace, name, None):
            return name
    return None


def resolve_seal(
    discovery: Discovery | None,
    *,
    live_default: bool,
    isolated: bool,
    world_id: str | None = None,
) -> str | None:
    """Admitted isolated worlds skip the seal. Live agents send a catalog-accepted hash.

    `--isolated` without an admitted test.hosted-canonical.* id is not a live-seal bypass.
    """
    if isolated or is_isolated_world(world_id):
        return None
    accepted = list(discovery.accepted_seals) if discovery else []
    published = sealed_prompt_hash()
    if discovery and discovery.seal_required is False:
        return None
    if accepted:
        if published in accepted:
            return published
        raise NoemaSealError("SEAL_MISMATCH", "published seal is not in server catalog", failure=None)
    if live_default or (discovery and discovery.seal_required):
        return published
    return published if live_default else None


def command_headers(seal: str | None) -> dict[str, str]:
    if not seal:
        return {}
    return {SEAL_HEADER: seal}
