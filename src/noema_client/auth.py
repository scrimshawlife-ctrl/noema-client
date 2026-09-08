"""Device enrollment. Token stays outside model context.

Adapted from Zero-State-LLC/Noema src/noema/harness/auth.py.
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Callable
from typing import Any, Literal

from noema_client.errors import FailureClass, NoemaAuthError
from noema_client.transport import cloudflare_challenge_code

HttpFn = Callable[..., dict[str, Any]]
CredentialState = Literal["stored", "expired", "invalid", "missing"]

DISCOVERING = "Discovering…"
REQUESTING_DEVICE_CODE = "Requesting device code…"
EMAIL_UNCONFIGURED = (
    "Email one-click is unconfigured. Use the short-code approval URL. Mail was not sent."
)
HEARTBEAT_PENDING = "authorization_pending: waiting for human approval"
ANNOUNCE_APPROVED = "Approved."
ANNOUNCE_DENIED = "Denied."
ANNOUNCE_EXPIRED = "Expired."
ANNOUNCE_CANCELLED = "Cancelled."
PENDING_HEARTBEAT_EVERY = 3
REVIEW_DELIVERY_SENT = "sent"

_START_TIMEOUT = (
    "Device enrollment timed out before a device code was issued. "
    "Check reachability with noema doctor, then retry."
)
_START_REFUSED = (
    "Device enrollment was refused (HTTP 403). "
    "The server did not issue a device code. "
    "Check that this client can reach the origin, then retry."
)
_START_CLOUDFLARE_1010 = (
    "Device enrollment was refused (HTTP 403). "
    "Cloudflare blocked this client (error 1010). "
    "Open the approval page in a browser, or retry from a network that can reach the origin."
)


def _b64url_json(segment: str) -> dict[str, Any] | None:
    try:
        pad = "=" * (-len(segment) % 4)
        raw = base64.urlsafe_b64decode(segment + pad)
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def credential_state(token: str | None, *, now: float | None = None) -> CredentialState:
    """Classify a stored access token without verifying the signature or contacting NOEMA.

    Opaque (non-JWT) tokens stay ``stored`` because expiry cannot be read locally.
    JWT-shaped tokens are ``expired`` when ``exp`` is in the past, ``invalid`` when
    the payload cannot be decoded, and ``stored`` otherwise.
    """
    raw = str(token or "").strip()
    if not raw:
        return "missing"
    parts = raw.split(".")
    if len(parts) != 3 or not all(parts):
        return "stored"
    payload = _b64url_json(parts[1])
    if payload is None:
        return "invalid"
    exp = payload.get("exp")
    if exp is None:
        return "stored"
    try:
        exp_ts = float(exp)
    except (TypeError, ValueError):
        return "invalid"
    clock = time.time() if now is None else float(now)
    if clock >= exp_ts:
        return "expired"
    return "stored"


def _payload_text(payload: dict[str, Any]) -> str:
    err = payload.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or err.get("code") or "")
    if isinstance(err, str):
        return err
    return ""


def start_failure_from_exc(exc: BaseException) -> NoemaAuthError:
    if isinstance(exc, TimeoutError):
        return NoemaAuthError("AUTH_REQUIRED", _START_TIMEOUT, failure=FailureClass.AUTH_REQUIRED)
    return NoemaAuthError(
        "AUTH_REQUIRED",
        (
            f"Device enrollment could not reach the server ({type(exc).__name__}). "
            "Check DNS and network, then retry."
        ),
        failure=FailureClass.AUTH_REQUIRED,
    )


def start_failure_from_http(payload: dict[str, Any], status: int) -> NoemaAuthError:
    challenge = payload.get("_cloudflare_code") or cloudflare_challenge_code(_payload_text(payload))
    if status == 403 and challenge == "1010":
        message = _START_CLOUDFLARE_1010
    elif status == 403:
        message = _START_REFUSED
    else:
        message = (
            f"Device enrollment failed (HTTP {status}). "
            "The server did not issue a device code. Retry, or run noema doctor."
        )
    return NoemaAuthError("AUTH_REQUIRED", message, failure=FailureClass.AUTH_REQUIRED)


def _review_delivery(started: dict[str, Any]) -> str:
    raw = started.get("review_delivery")
    if raw is None:
        return ""
    return str(raw).strip().lower()


def _short_code_uri(base_url: str, started: dict[str, Any], user_code: str, *, force_short_code: bool) -> str:
    origin = base_url.rstrip("/")
    if force_short_code:
        uri = f"{origin}/connect"
    else:
        uri = str(started.get("verification_uri") or started.get("verification_url") or f"{origin}/connect")
    if user_code and "code=" not in uri:
        sep = "&" if "?" in uri else "?"
        uri = f"{uri}{sep}code={user_code}"
    return uri


def _terminal_announce(status: str) -> str:
    if status in {"denied", "access_denied"}:
        return ANNOUNCE_DENIED
    if status == "expired":
        return ANNOUNCE_EXPIRED
    if status == "cancelled":
        return ANNOUNCE_CANCELLED
    if status == "approved":
        return ANNOUNCE_APPROVED
    return status


class StaticTokenProvider:
    def __init__(self, token: str) -> None:
        self._token = token

    def reveal(self) -> str:
        return self._token

    def __repr__(self) -> str:
        return "StaticTokenProvider(<redacted>)"


class DeviceEnrollment:
    def __init__(
        self,
        base_url: str,
        *,
        runtime: str = "noema-client",
        http: HttpFn,
        sleep: Callable[[float], None] | None = None,
        announce: Callable[[str], None] | None = None,
        owner_email: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.runtime = runtime
        self._http = http
        self._sleep = sleep or time.sleep
        self._announce = announce or (lambda _m: None)
        self._token: str | None = None
        self._meta: dict[str, Any] = {}
        self._device_code: str | None = None
        self._interval = 5.0
        self._deadline = 0.0
        self.owner_email = owner_email

    def start(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"metadata": {"runtime": self.runtime}}
        if self.owner_email:
            payload["owner_email"] = self.owner_email
        try:
            started = self._http(
                "POST",
                f"{self.base_url}/v1/auth/device",
                payload,
                None,
            )
        except (TimeoutError, OSError) as exc:
            raise start_failure_from_exc(exc) from exc
        if not isinstance(started, dict):
            raise NoemaAuthError("AUTH_REQUIRED", "device start failed", failure=FailureClass.AUTH_REQUIRED)
        status = int(started.get("_http_status") or 200)
        if status >= 400:
            raise start_failure_from_http(started, status)
        self._device_code = str(started.get("device_code") or "")
        if not self._device_code:
            raise NoemaAuthError(
                "AUTH_REQUIRED",
                "Device enrollment did not issue a short code. Retry, or run noema doctor.",
                failure=FailureClass.AUTH_REQUIRED,
            )
        self._interval = max(0.0, float(started.get("interval") if started.get("interval") is not None else 5))
        self._deadline = time.time() + max(
            0.0,
            float(started.get("expires_in") if started.get("expires_in") is not None else 600),
        )
        user_code = str(started.get("user_code") or "")
        delivery = _review_delivery(started)
        force_short_code = bool(self.owner_email) and delivery != REVIEW_DELIVERY_SENT
        uri = _short_code_uri(self.base_url, started, user_code, force_short_code=force_short_code)
        self._meta = {
            "user_code": user_code,
            "verification_uri": uri,
            "expires_in": started.get("expires_in"),
            "interval": started.get("interval"),
            "player_id": started.get("player_id"),
            "controller_id": started.get("controller_id"),
            "review_delivery": started.get("review_delivery"),
        }
        if force_short_code:
            self._announce(EMAIL_UNCONFIGURED)
        self._announce(f"Approve {user_code} at {uri}")
        return dict(self._meta)

    def poll_until_ready(self) -> dict[str, Any]:
        if not self._device_code:
            raise NoemaAuthError("AUTH_REQUIRED", "device start required", failure=FailureClass.AUTH_REQUIRED)
        pending_ticks = 0
        while time.time() <= self._deadline:
            try:
                polled = self._http(
                    "POST",
                    f"{self.base_url}/v1/auth/device/token",
                    {"device_code": self._device_code},
                    None,
                )
            except OSError:
                self._sleep(self._interval)
                continue
            status = polled.get("status")
            if status == "approved" and polled.get("access_token"):
                self._token = str(polled["access_token"])
                self._meta["player_id"] = polled.get("player_id") or self._meta.get("player_id")
                self._meta["controller_id"] = polled.get("controller_id") or self._meta.get("controller_id")
                self._announce(ANNOUNCE_APPROVED)
                return {"access_token": self._token, **{k: v for k, v in self._meta.items() if k != "access_token"}}
            if polled.get("interval") is not None:
                self._interval = max(0.0, float(polled["interval"]))
            if polled.get("error") == "slow_down" or status == "slow_down":
                self._interval += 5.0
                self._sleep(self._interval)
                continue
            if status in {"denied", "access_denied", "expired", "cancelled"}:
                self._announce(_terminal_announce(str(status)))
                raise NoemaAuthError("AUTH_REQUIRED", f"device enroll closed: {status}", failure=FailureClass.AUTH_REQUIRED)
            if status and status not in {"authorization_pending", "pending"}:
                self._announce(_terminal_announce(str(status)))
                raise NoemaAuthError("AUTH_REQUIRED", f"device enroll closed: {status}", failure=FailureClass.AUTH_REQUIRED)
            if int(polled.get("_http_status") or 0) >= 400 and status not in {None, "authorization_pending", "pending"}:
                raise NoemaAuthError("AUTH_REQUIRED", "device enroll failed", failure=FailureClass.AUTH_REQUIRED)
            if status in {None, "authorization_pending", "pending"}:
                pending_ticks += 1
                if pending_ticks % PENDING_HEARTBEAT_EVERY == 0:
                    self._announce(HEARTBEAT_PENDING)
            self._sleep(float(polled.get("interval") if polled.get("interval") is not None else self._interval))
        self._announce(ANNOUNCE_EXPIRED)
        raise NoemaAuthError("AUTH_REQUIRED", "device enroll expired", failure=FailureClass.AUTH_REQUIRED)

    def reveal(self) -> str:
        if not self._token:
            raise NoemaAuthError("AUTH_REQUIRED", "no controller token", failure=FailureClass.AUTH_REQUIRED)
        return self._token

    def __repr__(self) -> str:
        return "DeviceEnrollment(<redacted>)"
