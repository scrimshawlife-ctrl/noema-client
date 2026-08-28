"""Agent Protocol v1 WebSocket. HELLO / AUTH / OBSERVE / ACT / PING / resume.

Does not invent message types. Optional extra: pip install 'noema-client[ws]'.
Adapted from Zero-State-LLC/Noema clients/noema-llm-agent protocol.py and
workers/noema/src/protocol-ws.ts commandFromFrame.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Callable
from urllib.parse import urlparse, urlunparse

from noema_client._version import __version__
from noema_client.errors import FailureClass, NoemaProtocolError
from noema_client.transport import classify, payload_is_resync
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


def _sync_connect(url: str) -> Any:
    try:
        from websockets.sync.client import connect

        return connect(url, open_timeout=15, close_timeout=5)
    except ImportError as exc:
        raise NoemaProtocolError(
            "WS_UNAVAILABLE",
            "WebSocket extra not installed; use HTTP or pip install 'noema-client[ws]'",
            failure=FailureClass.PROTOCOL,
        ) from exc


class WebSocketGateway:
    """Persistent Agent Protocol v1 socket. Isolated worlds must not use this path."""

    def __init__(
        self,
        ws_url: str,
        token_provider: Any,
        *,
        seal: str | None = None,
        runtime: str = "noema-client",
        client_version: str = __version__,
        resume_token: str | None = None,
        connect_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self.ws_url = ws_url
        self._tokens = token_provider
        self.seal = seal
        self.runtime = runtime
        self.client_version = client_version
        self.session_id: str | None = None
        self.resume_token: str | None = resume_token
        self.player_id: str | None = None
        self.controller_id: str | None = None
        self.resumed = False
        self._ws = None
        self._seq = 0
        self._epoch = uuid.uuid4().hex[:8]
        self._factory = connect_factory

    def available(self) -> bool:
        if self._factory is not None:
            return True
        try:
            from websockets.sync.client import connect  # noqa: F401

            return True
        except ImportError:
            return False

    def _open(self) -> Any:
        if self._factory is not None:
            return self._factory(self.ws_url)
        return _sync_connect(self.ws_url)

    def _rpc(self, frame: dict[str, Any]) -> dict[str, Any]:
        if self._ws is None:
            raise NoemaProtocolError("WS_CLOSED", "websocket is not connected", failure=FailureClass.RETRYABLE_TRANSPORT, retryable=True)
        raw_out = json.dumps(frame)
        self._ws.send(raw_out)
        raw_in = self._ws.recv()
        if isinstance(raw_in, bytes):
            raw_in = raw_in.decode()
        payload = json.loads(raw_in) if raw_in else {}
        if not isinstance(payload, dict):
            raise NoemaProtocolError("PROTOCOL_MISMATCH", "websocket frame was not an object", failure=FailureClass.PROTOCOL)
        return payload

    def _hello(self) -> dict[str, Any]:
        body: dict[str, Any] = {"supported_protocols": ["agent-protocol/v1"]}
        if self.resume_token:
            body["resume_token"] = self.resume_token
        ack = self._rpc(
            {
                "protocol": "agent-protocol/v1",
                "type": "HELLO",
                "request_id": _rid(),
                "body": body,
            }
        )
        kind = str(ack.get("type") or "")
        if kind not in {"HELLO_ACK", "HELLO"}:
            if kind == "ERROR":
                err = ack.get("error") if isinstance(ack.get("error"), dict) else {}
                raise NoemaProtocolError(str(err.get("code") or "HELLO_FAILED"), str(err.get("message") or "hello failed"), failure=FailureClass.PROTOCOL)
            raise NoemaProtocolError("PROTOCOL_MISMATCH", "unexpected HELLO reply", failure=FailureClass.PROTOCOL)
        extra = ack.get("body") if isinstance(ack.get("body"), dict) else {}
        self.resumed = bool(extra.get("resume_offered") or extra.get("resumed") or kind == "RESUME_ACK")
        return ack

    def _auth(self) -> dict[str, Any]:
        auth_body: dict[str, Any] = {"access_token": self._tokens.reveal()}
        if self.seal:
            auth_body["prompt_version_hash"] = self.seal
        ack = self._rpc(
            {
                "protocol": "agent-protocol/v1",
                "type": "AUTH",
                "request_id": _rid(),
                "body": auth_body,
            }
        )
        if str(ack.get("type") or "") == "ERROR":
            err = ack.get("error") if isinstance(ack.get("error"), dict) else {}
            raise NoemaProtocolError(
                str(err.get("code") or "NOT_AUTHORIZED"),
                str(err.get("message") or "auth failed"),
                failure=FailureClass.AUTH_REQUIRED,
            )
        body = ack.get("body") if isinstance(ack.get("body"), dict) else ack
        self.session_id = body.get("session_id") if isinstance(body.get("session_id"), str) else self.session_id
        token = body.get("resume_token")
        if isinstance(token, str) and token:
            self.resume_token = token
        self.player_id = body.get("player_id") or body.get("agent_id") or self.player_id
        self.controller_id = body.get("controller_id") or self.controller_id
        self.resumed = False
        return ack

    def connect_session(self) -> dict[str, Any]:
        if not self.available():
            raise NoemaProtocolError("WS_UNAVAILABLE", "websockets package not installed", failure=FailureClass.PROTOCOL)
        self._quiet_close()
        self._ws = self._open()
        hello = self._hello()
        if self.resumed and self.resume_token:
            return hello
        return self._auth()

    def _reconnect(self) -> None:
        self._quiet_close()
        self.connect_session()

    def send_command(
        self,
        command: str,
        arguments: dict[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
        request_id: str | None = None,
        retries: int = 1,
    ) -> CommandResult:
        if self._ws is None:
            self.connect_session()
        verb = (command or "").upper()
        key = idempotency_key or f"idem.{self._epoch}.{self._seq:06d}"
        req_id = request_id or _rid()
        self._seq += 1
        action_seq = getattr(self, "_action_seq", 0)
        self._action_seq = action_seq + 1
        typ = "OBSERVE" if verb == "OBSERVE" else "ACT"
        body: dict[str, Any] = {
            "command": verb,
            "arguments": arguments or {},
            "action": {"verb": verb, "parameters": arguments or {}},
            "client": {
                "type": "agent",
                "runtime": self.runtime,
                "client_version": self.client_version,
                "client_action_sequence": action_seq,
            },
        }
        frame = {
            "protocol": "agent-protocol/v1",
            "type": typ,
            "request_id": req_id,
            "idempotency_key": key,
            "schema_version": "agent-action/1.0",
            "body": body,
        }
        last_exc: Exception | None = None
        payload: dict[str, Any] = {}
        attempts = max(1, retries + 1)
        resync_left = 1
        for attempt in range(attempts):
            try:
                payload = self._rpc(frame)
                if payload_is_resync(payload) and resync_left > 0:
                    resync_left -= 1
                    time.sleep(0.05)
                    continue
                if str(payload.get("type") or "") == "ERROR":
                    err = payload.get("error") if isinstance(payload.get("error"), dict) else {}
                    code = str(err.get("code") or "").upper()
                    if code in {"NOT_AUTHORIZED", "AUTH_REQUIRED"} and attempt + 1 < attempts:
                        self._auth()
                        continue
                    if code in {"NOT_AUTHORIZED", "AUTH_REQUIRED"}:
                        self._reconnect()
                        continue
                last_exc = None
                break
            except (NoemaProtocolError, TimeoutError, ConnectionError, OSError) as exc:
                last_exc = exc
                if attempt + 1 >= attempts:
                    break
                try:
                    self._reconnect()
                except Exception as reconnect_exc:
                    last_exc = reconnect_exc
                    break
        if last_exc is not None and not payload:
            failure = FailureClass.RETRYABLE_TRANSPORT
            code = "RETRYABLE_TRANSPORT"
            if isinstance(last_exc, NoemaProtocolError):
                failure = last_exc.failure or FailureClass.PROTOCOL
                code = last_exc.code
            return CommandResult(
                ok=False,
                observation=None,
                error={"code": code, "message": str(last_exc)},
                settled=None,
                http_status=None,
                failure=failure,
                idempotency_key=key,
                request_id=req_id,
            )
        return self._result(payload, key, req_id)

    def _result(self, payload: dict[str, Any], key: str, req_id: str) -> CommandResult:
        kind = str(payload.get("type") or "")
        body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
        err = payload.get("error") if isinstance(payload.get("error"), dict) else None
        if kind == "ERROR" or err:
            status_hint = payload.get("_status") if isinstance(payload.get("_status"), int) else None
            merged = dict(body)
            if err:
                merged["error"] = err
            failure = classify(merged, status_hint)
            return CommandResult(
                ok=False,
                observation=body.get("observation") if isinstance(body.get("observation"), dict) else None,
                error=err or {"code": "ACT_FAILED", "message": "act failed"},
                settled=None,
                http_status=status_hint,
                failure=failure or FailureClass.ACTION_REJECTED,
                idempotency_key=key,
                request_id=req_id,
                world_status=body.get("world_status") if isinstance(body.get("world_status"), str) else None,
                raw=payload,
            )
        observation = body.get("observation") if isinstance(body.get("observation"), dict) else None
        ok = True if observation is not None else bool(body.get("ok", True))
        return CommandResult(
            ok=ok,
            observation=observation,
            error=body.get("error") if isinstance(body.get("error"), dict) else None,
            settled=body.get("settled") if isinstance(body.get("settled"), bool) else None,
            http_status=None,
            failure=None if ok else FailureClass.ACTION_REJECTED,
            idempotency_key=key,
            request_id=req_id,
            world_status=body.get("world_status") if isinstance(body.get("world_status"), str) else None,
            raw=payload,
        )

    def ping(self) -> dict[str, Any]:
        return self._rpc({"protocol": "agent-protocol/v1", "type": "PING", "request_id": _rid(), "body": {}})

    def _quiet_close(self) -> None:
        ws = self._ws
        self._ws = None
        if ws is None:
            return
        try:
            closer = getattr(ws, "close", None)
            if callable(closer):
                closer()
        except Exception:
            return

    def close(self) -> None:
        if self._ws is not None:
            try:
                self._rpc({"protocol": "agent-protocol/v1", "type": "DISCONNECT", "request_id": _rid(), "body": {}})
            except Exception:
                pass
        self._quiet_close()
