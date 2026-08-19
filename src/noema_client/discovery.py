"""Discovery-first. GET /.well-known/noema-agent.json before assuming endpoints."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from noema_client.errors import NoemaProtocolError

HttpFn = Callable[..., dict[str, Any]]


@dataclass
class Discovery:
    origin: str
    protocol: str = "agent-protocol/v1"
    command_uri: str = "/v1/command"
    websocket_uri: str = "/protocol/v1/ws"
    verification_uri: str = "/connect"
    device_auth: bool = True
    seal_required: bool | None = None
    accepted_seals: list[str] = field(default_factory=list)
    transports: list[str] = field(default_factory=lambda: ["http", "websocket"])
    raw: dict[str, Any] = field(default_factory=dict)


def parse_discovery(origin: str, payload: dict[str, Any]) -> Discovery:
    origin = origin.rstrip("/")
    protocol = str(payload.get("protocol") or payload.get("protocol_version") or "agent-protocol/v1")
    if protocol not in {"agent-protocol/v1", "1", "v1"}:
        raise NoemaProtocolError("PROTOCOL_MISMATCH", f"unsupported protocol {protocol}", failure=None)
    command = str(payload.get("command_uri") or f"{origin}/v1/command")
    websocket = str(payload.get("websocket_uri") or f"{origin}/protocol/v1/ws")
    verify = str(payload.get("verification_uri") or f"{origin}/connect")
    seals = payload.get("accepted_seals") or payload.get("seals") or []
    if not isinstance(seals, list):
        seals = []
    seal_required = payload.get("seal_required")
    if seal_required is None and payload.get("accepted_seals"):
        seal_required = True
    transports = payload.get("transports") or payload.get("transport_capabilities") or ["http", "websocket"]
    if not isinstance(transports, list):
        transports = ["http", "websocket"]
    return Discovery(
        origin=str(payload.get("origin") or origin),
        protocol="agent-protocol/v1",
        command_uri=command,
        websocket_uri=websocket,
        verification_uri=verify,
        device_auth=bool(payload.get("device_auth", True)),
        seal_required=bool(seal_required) if seal_required is not None else None,
        accepted_seals=[str(s) for s in seals],
        transports=[str(t) for t in transports],
        raw=payload,
    )


def discover(origin: str, http: HttpFn) -> Discovery:
    origin = origin.rstrip("/")
    payload = http("GET", f"{origin}/.well-known/noema-agent.json", None, None)
    if int(payload.get("_http_status") or 200) >= 400:
        raise NoemaProtocolError("DISCOVERY_FAILED", "discovery document unavailable")
    return parse_discovery(origin, payload)
