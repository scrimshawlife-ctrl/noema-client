from __future__ import annotations

from pathlib import Path

import pytest

from noema_client.auth import DeviceEnrollment
from noema_client.cli import main
from noema_client.client import NoemaClient
from noema_client.config import credential_path, load_credential
from noema_client.errors import NoemaAuthError
from fake_server import FakeNoema, serve_fake


def test_device_start_sends_optional_owner_email() -> None:
    calls = []

    def http(method, url, body, token):
        calls.append((method, url, body, token))
        return {"device_code": "dev", "user_code": "U", "verification_uri": "http://v", "interval": 0, "expires_in": 1}

    DeviceEnrollment("http://server", http=http, owner_email="owner@example.com").start()

    assert calls[0][2]["owner_email"] == "owner@example.com"


def test_poll_approve_slow_down_and_throttling_intervals() -> None:
    sleeps: list[float] = []
    responses = iter([
        {"status": "authorization_pending", "interval": 2},
        {"error": "slow_down"},
        {"status": "approved", "access_token": "secret", "player_id": "p"},
    ])

    def http(method, url, body, token):
        if url.endswith("/device"):
            return {"device_code": "dev", "interval": 1, "expires_in": 10}
        return next(responses)

    e = DeviceEnrollment("http://server", http=http, sleep=sleeps.append)
    e.start()

    assert e.poll_until_ready()["access_token"] == "secret"
    assert sleeps == [2.0, 7.0]


@pytest.mark.parametrize("status", ["denied", "access_denied", "expired", "cancelled"])
def test_poll_terminal_denied_expired_cancelled(status: str) -> None:
    def http(method, url, body, token):
        if url.endswith("/device"):
            return {"device_code": "dev", "interval": 0, "expires_in": 10}
        return {"status": status}

    e = DeviceEnrollment("http://server", http=http, sleep=lambda _: None)
    e.start()
    with pytest.raises(NoemaAuthError, match=status):
        e.poll_until_ready()


def test_poll_retries_network_interruptions() -> None:
    calls = 0

    def http(method, url, body, token):
        nonlocal calls
        if url.endswith("/device"):
            return {"device_code": "dev", "interval": 0, "expires_in": 10}
        calls += 1
        if calls == 1:
            raise OSError("temporary")
        return {"status": "approved", "access_token": "secret"}

    e = DeviceEnrollment("http://server", http=http, sleep=lambda _: None)
    e.start()
    assert e.poll_until_ready()["access_token"] == "secret"


def test_connect_persists_atomically_enters_world_and_hides_secret(tmp_path: Path, capsys) -> None:
    fake = FakeNoema()
    fake.auto_approve = True
    fake.observe_requires_enter = True
    base, server, _thread = serve_fake(fake)
    try:
        client = NoemaClient(server=base, config_home=tmp_path, transport="http")
        cred = client.connect(owner_email="owner@example.com")
        out = capsys.readouterr().out + capsys.readouterr().err
        assert cred.access_token == "tok.fixture-secret"
        assert "tok.fixture-secret" not in out
        assert not credential_path(tmp_path).with_suffix(".json.tmp").exists()
        assert load_credential(tmp_path).access_token == "tok.fixture-secret"  # type: ignore[union-attr]
        assert [cmd["command"] for cmd in fake.commands] == ["ENTER_WORLD", "OBSERVE"]
        assert fake.in_world is True
        assert fake.approved["dev.fixture"].get("owner_email") == "owner@example.com"
    finally:
        server.shutdown()


def test_reconnect_is_idempotent_and_does_not_start_duplicate_player(tmp_path: Path) -> None:
    fake = FakeNoema()
    fake.auto_approve = True
    base, server, _thread = serve_fake(fake)
    try:
        first = NoemaClient(server=base, config_home=tmp_path, transport="http")
        first.connect(auto_enter=False)
        second = NoemaClient(server=base, config_home=tmp_path, transport="http")
        second.connect(auto_enter=False)
        assert fake.device_starts == 1
    finally:
        server.shutdown()


def test_cli_connect_email_no_enter_keeps_code_fallback_and_hides_secret(tmp_path: Path, capsys) -> None:
    fake = FakeNoema()
    fake.auto_approve = True
    base, server, _thread = serve_fake(fake)
    try:
        rc = main(["--server", base, "--config-dir", str(tmp_path), "--transport", "http", "connect", "--email", "owner@example.com", "--no-enter"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "tok.fixture-secret" not in out
        assert "Credential: stored locally" in out
        assert fake.approved["dev.fixture"].get("owner_email") == "owner@example.com"
        assert fake.commands == []

        fake2 = FakeNoema()
        fake2.auto_approve = True
        base2, server2, _thread2 = serve_fake(fake2)
        try:
            rc = main(["--server", base2, "--config-dir", str(tmp_path / "fallback"), "--transport", "http", "connect", "--no-enter"])
            assert rc == 0
            assert "owner_email" not in fake2.approved["dev.fixture"]
        finally:
            server2.shutdown()
    finally:
        server.shutdown()
