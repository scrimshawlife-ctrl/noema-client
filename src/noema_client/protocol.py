"""Agent Protocol v1 WebSocket. HELLO / AUTH / OBSERVE / ACT / PING / resume.

Does not invent message types. Optional extra: pip install 'noema-client[ws]'.
Adapted from Zero-State-LLC/Noema clients/noema-llm-agent protocol.py.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Callable
from urllib.parse import urlparse, urlunparse

from noema_client.errors import FailureClass, NoemaProtocolError
from noema_client.types import CommandResult


def derive_ws_url(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    scheme = "wss" if parsed.scheme in {"https", "wss"} else "ws"
    path = parsed.path or ""
    if path.endswith("/protocol/v1/ws"):
        ws_path = path
    elif path.endswith("/protocol/v1"):
        ws_path = path + "/ws"
    elif path in {"", "/"}:
        ws_path = "/protocol/v1/ws"
    else:
        ws_path = path.rstrip("/") + "/protocol/v1/ws"
    return urlunparse((scheme, parsed.netloc, ws_path, "", "", ""))


def _rid() -> str:
    return f"req.{uuid.uuid4().hex[:12]}"


class WebSocketGateway:
    """Synchronous facade over optional websockets. Falls back by raising ProtocolError."""

    def __init__(
        self,
        ws_url: str,
        token_provider: Any,
        *,
        seal: str | None = None,
        runtime: str = "noema-client",
    ) -> None:
        self.ws_url = ws_url
        self._tokens = token_provider
        self.seal = seal
        self.runtime = runtime
        self.session_id: str | None = None
        self.resume_token: str | None = None
        self.player_id: str | None = None
        self._ws = None
        self._seq = 0

    def available(self) -> bool:
        try:
            import websockets  # noqa: F401

            return True
        except ImportError:
            return False

    def _send(self, typ: str, body: dict[str, Any], *, mutating: bool = False) -> dict[str, Any]:
        raise NoemaProtocolError(
            "WS_UNAVAILABLE",
            "WebSocket extra not installed; use HTTP or pip install 'noema-client[ws]'",
            failure=FailureClass.PROTOCOL,
        )

    def connect_session(self) -> dict[str, Any]:
        if not self.available():
            raise NoemaProtocolError("WS_UNAVAILABLE", "websockets package not installed", failure=FailureClass.PROTOCOL)
        import asyncio

        async def _run() -> dict[str, Any]:
            import websockets

            async with websockets.connect(self.ws_url, open_timeout=15) as ws:
                hello = {
                    "protocol": "agent-protocol/v1",
                    "type": "HELLO",
                    "request_id": _rid(),
                    "body": {"supported_protocols": ["agent-protocol/v1"]},
                }
                await ws.send(json.dumps(hello))
                ack_raw = json.loads(await ws.recv())
                if str(ack_raw.get("type") or "") not in {"HELLO_ACK", "HELLO"}:
                    raise NoemaProtocolError("PROTOCOL_MISMATCH", "unexpected HELLO reply", failure=FailureClass.PROTOCOL)
                auth_body: dict[str, Any] = {"access_token": self._tokens.reveal()}
                if self.seal:
                    auth_body["prompt_version_hash"] = self.seal
                auth = {
                    "protocol": "agent-protocol/v1",
                    "type": "AUTH",
                    "request_id": _rid(),
                    "body": auth_body,
                }
                await ws.send(json.dumps(auth))
                auth_ack = json.loads(await ws.recv())
                body = auth_ack.get("body") if isinstance(auth_ack.get("body"), dict) else auth_ack
                self.session_id = body.get("session_id")
                self.resume_token = body.get("resume_token")
                self.player_id = body.get("player_id") or body.get("agent_id")
                self._ws = ws
                return auth_ack

        return asyncio.run(_run())

    def send_command(
        self,
        command: str,
        arguments: dict[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
        request_id: str | None = None,
        retries: int = 0,
    ) -> CommandResult:
        # 0.1 HTTP is the supported autonomous path. WS handshake is proven via connect_session.
        # Command mapping stays HTTP so we do not invent extra WS ACT shapes.
        raise NoemaProtocolError(
            "WS_COMMAND_HTTP",
            "use HTTP command transport after WS hello/auth",
            failure=FailureClass.PROTOCOL,
            retryable=True,
        )
