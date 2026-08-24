"""Device enrollment. Token stays outside model context.

Adapted from Zero-State-LLC/Noema src/noema/harness/auth.py.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any, Callable, Literal

from noema_client.errors import FailureClass, NoemaAuthError

HttpFn = Callable[..., dict[str, Any]]
CredentialState = Literal["stored", "expired", "invalid", "missing"]


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

    def start(self) -> dict[str, Any]:
        started = self._http(
            "POST",
            f"{self.base_url}/v1/auth/device",
            {"metadata": {"runtime": self.runtime}},
            None,
        )
        if int(started.get("_http_status") or 200) >= 400:
            raise NoemaAuthError("AUTH_REQUIRED", "device start failed", failure=FailureClass.AUTH_REQUIRED)
        self._device_code = str(started.get("device_code") or "")
        if not self._device_code:
            raise NoemaAuthError("AUTH_REQUIRED", "device start failed", failure=FailureClass.AUTH_REQUIRED)
        self._interval = float(started.get("interval") or 5)
        self._deadline = time.time() + float(started.get("expires_in") or 600)
        user_code = str(started.get("user_code") or "")
        uri = str(started.get("verification_uri") or started.get("verification_url") or f"{self.base_url}/connect")
        if user_code:
            sep = "&" if "?" in uri else "?"
            uri = f"{uri}{sep}code={user_code}"
        self._meta = {
            "user_code": user_code,
            "verification_uri": uri,
            "expires_in": started.get("expires_in"),
            "interval": started.get("interval"),
            "player_id": started.get("player_id"),
            "controller_id": started.get("controller_id"),
        }
        self._announce(f"Approve {user_code} at {uri}")
        return dict(self._meta)

    def poll_until_ready(self) -> dict[str, Any]:
        if not self._device_code:
            raise NoemaAuthError("AUTH_REQUIRED", "device start required", failure=FailureClass.AUTH_REQUIRED)
        while time.time() < self._deadline:
            polled = self._http(
                "POST",
                f"{self.base_url}/v1/auth/device/token",
                {"device_code": self._device_code},
                None,
            )
            status = polled.get("status")
            if status == "approved" and polled.get("access_token"):
                self._token = str(polled["access_token"])
                self._meta["player_id"] = polled.get("player_id") or self._meta.get("player_id")
                self._meta["controller_id"] = polled.get("controller_id") or self._meta.get("controller_id")
                return {"access_token": self._token, **{k: v for k, v in self._meta.items() if k != "access_token"}}
            if status and status not in {"authorization_pending", "pending"}:
                raise NoemaAuthError("AUTH_REQUIRED", f"device enroll closed: {status}", failure=FailureClass.AUTH_REQUIRED)
            if int(polled.get("_http_status") or 0) >= 400 and status not in {None, "authorization_pending", "pending"}:
                raise NoemaAuthError("AUTH_REQUIRED", "device enroll failed", failure=FailureClass.AUTH_REQUIRED)
            self._sleep(float(polled.get("interval") or self._interval))
        raise NoemaAuthError("AUTH_REQUIRED", "device enroll expired", failure=FailureClass.AUTH_REQUIRED)

    def reveal(self) -> str:
        if not self._token:
            raise NoemaAuthError("AUTH_REQUIRED", "no controller token", failure=FailureClass.AUTH_REQUIRED)
        return self._token

    def __repr__(self) -> str:
        return "DeviceEnrollment(<redacted>)"
