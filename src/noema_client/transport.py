"""Idempotent HTTP /v1/command. Token is header-only.

Adapted from Zero-State-LLC/Noema src/noema/harness/transport.py.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Callable, Protocol

from noema_client._version import __version__
from noema_client.errors import FailureClass
from noema_client.types import CommandResult

USER_AGENT = f"noema-client/{__version__} (+https://github.com/scrimshawlife-ctrl/noema-client)"


def cloudflare_challenge_code(text: str) -> str | None:
    """Return a Cloudflare challenge code when the body names one. Never returns secrets."""
    raw = str(text or "")
    lowered = raw.lower()
    if "1010" not in raw:
        return None
    if "cloudflare" in lowered or "error 1010" in lowered or "error code: 1010" in lowered:
        return "1010"
    return None


class TokenProvider(Protocol):
    def reveal(self) -> str: ...


class CommandTransport(Protocol):
    def send_command(
        self,
        command: str,
        arguments: dict[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
        request_id: str | None = None,
        retries: int = 1,
    ) -> CommandResult: ...

    def close(self) -> None: ...


def _ipv4_opener() -> urllib.request.OpenerDirector:
    orig = socket.getaddrinfo

    def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):  # noqa: A002
        return orig(host, port, socket.AF_INET, type, proto, flags)

    socket.getaddrinfo = getaddrinfo_ipv4  # type: ignore[assignment]
    return urllib.request.build_opener()


_OPENER = _ipv4_opener()


def default_http(
    method: str,
    url: str,
    body: dict | None = None,
    token: str | None = None,
    headers: dict[str, str] | None = None,
) -> dict:
    data = None if body is None else json.dumps(body).encode()
    hdrs = {
        "content-type": "application/json",
        "accept": "application/json",
        "user-agent": USER_AGENT,
    }
    if token:
        hdrs["authorization"] = f"Bearer {token}"
    if headers:
        hdrs.update({k: v for k, v in headers.items() if v})
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with _OPENER.open(req, timeout=30) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"error": {"message": raw or str(e)}}
        if not isinstance(payload, dict):
            payload = {"error": {"message": raw or str(e)}}
        payload["_http_status"] = e.code
        challenge = cloudflare_challenge_code(raw)
        if challenge:
            payload["_cloudflare_code"] = challenge
        return payload


def _error_code(payload: dict[str, Any]) -> str:
    err = payload.get("error")
    if isinstance(err, dict):
        return str(err.get("code") or "").upper()
    return ""


def payload_is_resync(payload: dict[str, Any]) -> bool:
    if _error_code(payload) == "SETTLEMENT_RESYNC":
        return True
    body = payload.get("body")
    if isinstance(body, dict) and _error_code(body) == "SETTLEMENT_RESYNC":
        return True
    return False


def classify(payload: dict[str, Any], http_status: int | None) -> FailureClass | None:
    if http_status in (401, 403):
        code = ""
        err = payload.get("error")
        if isinstance(err, dict):
            code = str(err.get("code") or "").upper()
        if code in {"SEAL_REQUIRED", "SEAL_MISMATCH"}:
            return FailureClass.SEAL
        return FailureClass.AUTH_REQUIRED
    status = str(payload.get("world_status") or "").upper()
    code = ""
    err = payload.get("error")
    if isinstance(err, dict):
        code = str(err.get("code") or "").upper()
        status = status or str(err.get("world_status") or "").upper()
    if code in {"SEAL_REQUIRED", "SEAL_MISMATCH"}:
        return FailureClass.SEAL
    if status == "PAUSED" or code in {"WORLD_PAUSED", "PAUSED"}:
        return FailureClass.WORLD_PAUSED
    if status == "INCIDENT" or code in {"WORLD_INCIDENT", "INCIDENT"}:
        return FailureClass.WORLD_INCIDENT
    if code == "SETTLEMENT_RESYNC":
        return FailureClass.SETTLEMENT_RESYNC
    if status in {"PREVIEW", "ARCHIVED"} or code in {"WORLD_NOT_READY", "NOT_ACTIVE"}:
        return FailureClass.WORLD_NOT_READY
    if payload.get("ok") is False or (http_status and http_status >= 400):
        if code in {"CONFLICT", "INVALID_SCHEMA", "NONCONTIGUOUS_SEQUENCE", "DUPLICATE_EVENT_CONFLICT"}:
            return FailureClass.SETTLEMENT_FAILURE
        return FailureClass.ACTION_REJECTED
    return None


def call_http(
    fn: Callable[..., dict[str, Any]],
    method: str,
    url: str,
    body: dict | None,
    token: str | None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        return fn(method, url, body, token, headers=headers)
    except TypeError:
        return fn(method, url, body, token)


class HttpGateway:
    def __init__(
        self,
        base_url: str,
        token_provider: TokenProvider,
        *,
        http: Callable[..., dict[str, Any]] | None = None,
        runtime: str = "noema-client",
        client_version: str = __version__,
        command_path: str = "/v1/command",
        world_id: str | None = None,
        seal: str | None = None,
        admin_token: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._tokens = token_provider
        self._http = http or default_http
        self.runtime = runtime
        self.client_version = client_version
        self.command_path = command_path or "/v1/command"
        if self.command_path.startswith("http"):
            self.command_url = self.command_path
        else:
            self.command_url = f"{self.base_url}{self.command_path}"
        self.world_id = world_id
        self.seal = seal
        self._admin_token = admin_token
        self.last_fallback_note: str | None = None
        self._action_seq = 0

    def send_command(
        self,
        command: str,
        arguments: dict[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
        request_id: str | None = None,
        retries: int = 1,
    ) -> CommandResult:
        key = idempotency_key or f"idem.{uuid.uuid4().hex[:12]}"
        req_id = request_id or f"req.{uuid.uuid4().hex[:10]}"
        action_seq = self._action_seq
        last_timeout: Exception | None = None
        payload: dict[str, Any] = {}
        resync_left = 1
        transport_left = retries + 1
        while transport_left > 0:
            try:
                body: dict[str, Any] = {
                    "request_id": req_id,
                    "idempotency_key": key,
                    "command": command,
                    "arguments": arguments or {},
                    "client": {
                        "type": "agent",
                        "runtime": self.runtime,
                        "client_version": self.client_version,
                        "client_action_sequence": action_seq,
                    },
                }
                if self.world_id:
                    body["world_id"] = self.world_id
                extra: dict[str, str] = {}
                if self.seal:
                    extra["X-Noema-Seal"] = self.seal
                if self._admin_token:
                    extra["X-Noema-Admin-Token"] = self._admin_token
                payload = call_http(self._http, "POST", self.command_url, body, self._tokens.reveal(), extra)
                last_timeout = None
                if payload_is_resync(payload) and resync_left > 0:
                    resync_left -= 1
                    time.sleep(0.05)
                    continue
                break
            except (TimeoutError, urllib.error.URLError, ConnectionError, OSError) as exc:
                last_timeout = exc
                transport_left -= 1
                continue
        self._action_seq = action_seq + 1
        if last_timeout is not None and not payload:
            return CommandResult(
                ok=False,
                observation=None,
                error={"code": "RETRYABLE_TRANSPORT", "message": "transport failed"},
                settled=None,
                http_status=None,
                failure=FailureClass.RETRYABLE_TRANSPORT,
                idempotency_key=key,
                request_id=req_id,
            )
        http_status = payload.get("_http_status") if isinstance(payload, dict) else None
        failure = classify(payload, http_status if isinstance(http_status, int) else None)
        return CommandResult(
            ok=bool(payload.get("ok")),
            observation=payload.get("observation") if isinstance(payload.get("observation"), dict) else None,
            error=payload.get("error") if isinstance(payload.get("error"), dict) else None,
            settled=payload.get("settled") if isinstance(payload.get("settled"), bool) else None,
            http_status=http_status if isinstance(http_status, int) else None,
            failure=None if payload.get("ok") else (failure or FailureClass.ACTION_REJECTED),
            idempotency_key=key,
            request_id=req_id,
            world_status=payload.get("world_status") if isinstance(payload.get("world_status"), str) else None,
            raw=payload,
        )

    def close(self) -> None:
        return
