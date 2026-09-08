"""PROMETHEUS Slice A: loud, fail-closed enroll UX. Never print secrets."""

from __future__ import annotations

from pathlib import Path

import pytest
from fake_server import FakeNoema, serve_fake

from noema_client.auth import (
    ANNOUNCE_APPROVED,
    ANNOUNCE_DENIED,
    ANNOUNCE_EXPIRED,
    DISCOVERING,
    EMAIL_UNCONFIGURED,
    HEARTBEAT_PENDING,
    REQUESTING_DEVICE_CODE,
    DeviceEnrollment,
)
from noema_client.cli import main
from noema_client.client import NoemaClient
from noema_client.errors import NoemaAuthError
from noema_client.seal import sealed_prompt_hash
from noema_client.transport import cloudflare_challenge_code, default_http

SECRET_MARKERS = (
    "tok.fixture-secret",
    "dev.fixture",
    "access_token",
    "device_code",
    "eyJ",
)


def _assert_no_secrets(blob: str) -> None:
    lowered = blob.lower()
    for marker in SECRET_MARKERS:
        assert marker not in blob
        assert marker.lower() not in lowered


def _discovery_ok(_method, url, _body, _token, headers=None):
    if "well-known" in url:
        return {
            "protocol": "agent-protocol/v1",
            "accepted_seals": [sealed_prompt_hash()],
            "seal_required": False,
        }
    raise AssertionError(f"unexpected url {url}")


def test_cloudflare_challenge_code_detects_1010_without_dumping_body() -> None:
    html = "<html>Cloudflare / error code: 1010 Access denied eyJhbGciOiJIUzI1NiJ9.aaa.bbb</html>"
    assert cloudflare_challenge_code(html) == "1010"
    assert cloudflare_challenge_code('{"error":"nope"}') is None


@pytest.mark.parametrize(
    "factory",
    [
        lambda: TimeoutError("timed out"),
        lambda: OSError("network down"),
    ],
)
def test_cli_start_failure_prints_progress_then_exits_nonzero(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch, factory
) -> None:
    def http(method, url, body, token, headers=None):
        if "well-known" in url:
            return _discovery_ok(method, url, body, token, headers)
        if url.endswith("/v1/auth/device"):
            raise factory()
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("noema_client.client.default_http", http)
    rc = main(
        [
            "--server",
            "https://example.invalid",
            "--config-dir",
            str(tmp_path),
            "--transport",
            "http",
            "connect",
            "--no-enter",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert DISCOVERING in captured.out
    assert REQUESTING_DEVICE_CODE in captured.out
    assert captured.out.index(DISCOVERING) < captured.out.index(REQUESTING_DEVICE_CODE)
    assert "AUTH_REQUIRED" in captured.err
    _assert_no_secrets(captured.out + captured.err)


def test_cli_start_http_403_cloudflare_1010_fail_closed(tmp_path: Path, capsys) -> None:
    fake = FakeNoema()
    fake.device_start_status = 403
    fake.device_start_body = {"error": {"message": "error code: 1010 Access denied by Cloudflare"}}
    origin, httpd, _ = serve_fake(fake)
    try:
        rc = main(
            [
                "--server",
                origin,
                "--config-dir",
                str(tmp_path),
                "--transport",
                "http",
                "connect",
                "--no-enter",
            ]
        )
        captured = capsys.readouterr()
        assert rc == 1
        assert DISCOVERING in captured.out
        assert REQUESTING_DEVICE_CODE in captured.out
        assert "1010" in captured.err
        assert "HTTP 403" in captured.err
        _assert_no_secrets(captured.out + captured.err)
    finally:
        httpd.shutdown()


def test_announce_user_code_before_poll(tmp_path: Path) -> None:
    events: list[str] = []
    poll_calls = 0

    def http(method, url, body, token, headers=None):
        nonlocal poll_calls
        if "well-known" in url:
            return _discovery_ok(method, url, body, token, headers)
        if url.endswith("/v1/auth/device"):
            events.append("start")
            return {
                "device_code": "dev.secret-must-not-print",
                "user_code": "7KMP-41QZ",
                "verification_uri": "http://fixture/connect",
                "interval": 0,
                "expires_in": 10,
            }
        poll_calls += 1
        events.append("poll")
        return {"status": "approved", "access_token": "tok.fixture-secret", "player_id": "p"}

    announced: list[str] = []

    def announce(msg: str) -> None:
        events.append(f"announce:{msg}")
        announced.append(msg)

    client = NoemaClient(
        server="https://example.invalid",
        config_home=tmp_path,
        http=http,
        transport="http",
    )
    client.connect(announce=announce, auto_enter=False)
    start_at = events.index("start")
    first_approve = next(i for i, item in enumerate(events) if item.startswith("announce:Approve "))
    first_poll = events.index("poll")
    assert start_at < first_approve < first_poll
    assert events[0] == f"announce:{DISCOVERING}"
    assert REQUESTING_DEVICE_CODE in events[1]
    assert any(msg.startswith("Approve 7KMP-41QZ at ") for msg in announced)
    assert ANNOUNCE_APPROVED in announced
    _assert_no_secrets("\n".join(announced))
    assert poll_calls == 1


def test_email_unconfigured_when_review_delivery_not_sent() -> None:
    announced: list[str] = []

    def http(method, url, body, token, headers=None):
        if url.endswith("/v1/auth/device"):
            return {
                "device_code": "dev.secret-must-not-print",
                "user_code": "ABCD-9999",
                "verification_uri": "https://magic.example/email?tok=eyJhbGciOiJIUzI1NiJ9.aaa.bbb",
                "review_delivery": "unconfigured",
                "interval": 0,
                "expires_in": 1,
            }
        raise AssertionError("poll should not run in this test")

    enroll = DeviceEnrollment(
        "https://noema.example",
        http=http,
        announce=announced.append,
        owner_email="owner@example.com",
    )
    meta = enroll.start()

    assert EMAIL_UNCONFIGURED in announced
    assert any(msg.startswith("Approve ABCD-9999 at ") for msg in announced)
    assert meta["verification_uri"] == "https://noema.example/connect?code=ABCD-9999"
    assert "magic.example" not in "\n".join(announced)
    assert "Mail was not sent" in EMAIL_UNCONFIGURED
    for banned in ("sent an email", "email was sent", "mail was sent to"):
        assert banned not in "\n".join(announced).lower()
    _assert_no_secrets("\n".join(announced))


def test_email_sent_review_delivery_does_not_warn() -> None:
    announced: list[str] = []

    def http(method, url, body, token, headers=None):
        return {
            "device_code": "dev.secret-must-not-print",
            "user_code": "CODE-1",
            "verification_uri": "http://v",
            "review_delivery": "sent",
            "interval": 0,
            "expires_in": 1,
        }

    DeviceEnrollment(
        "http://server",
        http=http,
        announce=announced.append,
        owner_email="owner@example.com",
    ).start()
    assert EMAIL_UNCONFIGURED not in announced
    assert announced[0].startswith("Approve CODE-1 at ")
    _assert_no_secrets("\n".join(announced))


def test_cli_email_unconfigured_keeps_short_code_and_hides_secrets(tmp_path: Path, capsys) -> None:
    fake = FakeNoema()
    fake.auto_approve = True
    fake.review_delivery = "unconfigured"
    origin, httpd, _ = serve_fake(fake)
    try:
        rc = main(
            [
                "--server",
                origin,
                "--config-dir",
                str(tmp_path),
                "--transport",
                "http",
                "connect",
                "--email",
                "owner@example.com",
                "--no-enter",
            ]
        )
        out = capsys.readouterr().out
        assert rc == 0
        assert DISCOVERING in out
        assert REQUESTING_DEVICE_CODE in out
        assert EMAIL_UNCONFIGURED in out
        assert "7KMP-41QZ" in out
        assert "Approve this agent" in out
        assert ANNOUNCE_APPROVED in out
        assert "Waiting for approval" in out
        _assert_no_secrets(out)
    finally:
        httpd.shutdown()


def test_poll_heartbeats_and_distinct_terminals() -> None:
    announced: list[str] = []
    pending_left = 3

    def http(method, url, body, token, headers=None):
        nonlocal pending_left
        if url.endswith("/v1/auth/device"):
            return {"device_code": "dev.secret-must-not-print", "user_code": "U", "interval": 0, "expires_in": 10}
        if pending_left:
            pending_left -= 1
            return {"status": "authorization_pending", "interval": 0}
        return {"status": "approved", "access_token": "tok.fixture-secret"}

    enroll = DeviceEnrollment("http://server", http=http, sleep=lambda _: None, announce=announced.append)
    enroll.start()
    enroll.poll_until_ready()
    assert HEARTBEAT_PENDING in announced
    assert ANNOUNCE_APPROVED in announced
    _assert_no_secrets("\n".join(announced))

    def denied(method, url, body, token, headers=None):
        if url.endswith("/v1/auth/device"):
            return {"device_code": "dev.secret-must-not-print", "interval": 0, "expires_in": 10}
        return {"status": "denied"}

    closed: list[str] = []
    deny = DeviceEnrollment("http://server", http=denied, sleep=lambda _: None, announce=closed.append)
    deny.start()
    with pytest.raises(NoemaAuthError, match="denied"):
        deny.poll_until_ready()
    assert ANNOUNCE_DENIED in closed
    _assert_no_secrets("\n".join(closed))


def test_poll_expired_announces_expired() -> None:
    announced: list[str] = []

    def http(method, url, body, token, headers=None):
        if url.endswith("/v1/auth/device"):
            return {"device_code": "dev.secret-must-not-print", "interval": 0, "expires_in": 0}
        return {"status": "authorization_pending", "interval": 0}

    enroll = DeviceEnrollment("http://server", http=http, sleep=lambda _: None, announce=announced.append)
    enroll.start()
    with pytest.raises(NoemaAuthError, match="expired"):
        enroll.poll_until_ready()
    assert ANNOUNCE_EXPIRED in announced
    _assert_no_secrets("\n".join(announced))


def test_default_http_tags_cloudflare_1010(monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import urllib.error

    class Tagged(urllib.error.HTTPError):
        def __init__(self) -> None:
            super().__init__(
                "http://x",
                403,
                "Forbidden",
                hdrs=None,
                fp=io.BytesIO(b"<html>Cloudflare error code: 1010</html>"),
            )

    class Opener:
        def open(self, _req, timeout=30):
            raise Tagged()

    monkeypatch.setattr("noema_client.transport._OPENER", Opener())
    payload = default_http("POST", "http://example.invalid/v1/auth/device", {}, None)
    assert payload["_http_status"] == 403
    assert payload["_cloudflare_code"] == "1010"
