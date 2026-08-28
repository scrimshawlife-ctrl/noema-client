"""Local credential expiry: status/doctor/connect (issue #21). Never prints tokens."""

from __future__ import annotations

import base64
import json
from pathlib import Path

from fake_server import FakeNoema, serve_fake
from noema_client.auth import credential_state
from noema_client.cli import main as cli_main
from noema_client.client import NoemaClient
from noema_client.config import StoredCredential, load_credential, save_credential
from noema_client.errors import NoemaAuthError
from noema_client.transport import default_http


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def make_jwt(payload: dict, *, header: dict | None = None) -> str:
    head = _b64url(json.dumps(header or {"alg": "none", "typ": "JWT"}).encode())
    body = _b64url(json.dumps(payload).encode())
    return f"{head}.{body}.fakesig"


EXPIRED_JWT = make_jwt({"sid": "sess.expired", "iat": 1_000_000_000, "exp": 1_000_003_600})
VALID_JWT = make_jwt({"sid": "sess.valid", "iat": 4_000_000_000, "exp": 4_000_003_600})
NO_EXP_JWT = make_jwt({"sid": "sess.noexp", "iat": 1_000_000_000})
INVALID_JWT = "aaa.bbb.ccc"


def _assert_secret_absent(blob: str, *secrets: str) -> None:
    for secret in secrets:
        assert secret not in blob


def test_credential_state_classifies_jwt_and_opaque():
    assert credential_state(None) == "missing"
    assert credential_state("") == "missing"
    assert credential_state("tok.fixture-secret") == "stored"
    assert credential_state(VALID_JWT) == "stored"
    assert credential_state(NO_EXP_JWT) == "stored"
    assert credential_state(EXPIRED_JWT) == "expired"
    assert credential_state(EXPIRED_JWT, now=1_000_003_599) == "stored"
    assert credential_state(EXPIRED_JWT, now=1_000_003_600) == "expired"
    assert credential_state(INVALID_JWT) == "invalid"
    assert credential_state(make_jwt({"exp": "not-a-time"})) == "invalid"


def test_status_reports_expired_not_connected(tmp_path: Path):
    save_credential(StoredCredential(access_token=EXPIRED_JWT, server="https://example.invalid"), tmp_path)
    client = NoemaClient(server="https://example.invalid", config_home=tmp_path, transport="http")
    client.session.connected = True
    status = client.status()
    assert status["credential"] == "expired"
    assert status["connected"] is False
    _assert_secret_absent(json.dumps(status), EXPIRED_JWT)


def test_status_reports_invalid_not_connected(tmp_path: Path):
    save_credential(StoredCredential(access_token=INVALID_JWT, server="https://example.invalid"), tmp_path)
    client = NoemaClient(server="https://example.invalid", config_home=tmp_path, transport="http")
    status = client.status()
    assert status["credential"] == "invalid"
    assert status["connected"] is False
    _assert_secret_absent(json.dumps(status), INVALID_JWT)


def test_status_reports_stored_for_valid_jwt_and_opaque(tmp_path: Path):
    save_credential(StoredCredential(access_token=VALID_JWT, server="https://example.invalid"), tmp_path)
    client = NoemaClient(server="https://example.invalid", config_home=tmp_path, transport="http")
    status = client.status()
    assert status["credential"] == "stored"
    assert status["connected"] is True
    _assert_secret_absent(json.dumps(status), VALID_JWT)

    save_credential(StoredCredential(access_token="tok.fixture-secret", server="https://example.invalid"), tmp_path)
    opaque = NoemaClient(server="https://example.invalid", config_home=tmp_path, transport="http")
    status = opaque.status()
    assert status["credential"] == "stored"
    assert status["connected"] is True
    _assert_secret_absent(json.dumps(status), "tok.fixture-secret")


def test_status_missing_credential(tmp_path: Path):
    client = NoemaClient(server="https://example.invalid", config_home=tmp_path, transport="http")
    status = client.status()
    assert status["credential"] == "missing"
    assert status["connected"] is False


def test_doctor_reports_expired_without_world_commands(tmp_path: Path):
    fake = FakeNoema()
    origin, httpd, _ = serve_fake(fake)
    try:
        save_credential(StoredCredential(access_token=EXPIRED_JWT, server=origin), tmp_path)
        client = NoemaClient(server=origin, config_home=tmp_path, transport="http")
        report = client.doctor()
        assert report["credential"] == "expired"
        assert report["reachability"] == "ok"
        assert fake.commands == []
        _assert_secret_absent(json.dumps(report), EXPIRED_JWT)
    finally:
        httpd.shutdown()


def test_doctor_reports_stored_for_opaque_and_valid_jwt(tmp_path: Path):
    fake = FakeNoema()
    origin, httpd, _ = serve_fake(fake)
    try:
        save_credential(StoredCredential(access_token="tok.fixture-secret", server=origin), tmp_path)
        opaque = NoemaClient(server=origin, config_home=tmp_path, transport="http")
        report = opaque.doctor()
        assert report["credential"] == "stored"
        assert report["reachability"] == "ok"
        assert fake.commands == []

        save_credential(StoredCredential(access_token=VALID_JWT, server=origin), tmp_path)
        jwt_client = NoemaClient(server=origin, config_home=tmp_path, transport="http")
        report = jwt_client.doctor()
        assert report["credential"] == "stored"
        _assert_secret_absent(json.dumps(report), VALID_JWT, "tok.fixture-secret")
        assert fake.commands == []
    finally:
        httpd.shutdown()


def test_connect_reenrolls_expired_token(tmp_path: Path):
    fake = FakeNoema()
    origin, httpd, _ = serve_fake(fake)
    try:
        save_credential(
            StoredCredential(access_token=EXPIRED_JWT, server=origin, player_id="player.old"),
            tmp_path,
        )
        client = NoemaClient(server=origin, config_home=tmp_path, http=default_http, transport="http")
        notes: list[str] = []
        cred = client.connect(announce=lambda msg: (notes.append(msg), fake.approve()))
        assert fake.device_starts == 1
        assert cred.access_token == "tok.fixture-secret"
        loaded = load_credential(tmp_path)
        assert loaded and loaded.access_token == "tok.fixture-secret"
        assert any("expired" in msg for msg in notes)
        _assert_secret_absent("".join(notes), EXPIRED_JWT, "tok.fixture-secret")
        assert client.session.connected is True
        assert client.status()["credential"] == "stored"
    finally:
        httpd.shutdown()


def test_connect_reenrolls_invalid_token(tmp_path: Path):
    fake = FakeNoema()
    origin, httpd, _ = serve_fake(fake)
    try:
        save_credential(StoredCredential(access_token=INVALID_JWT, server=origin), tmp_path)
        client = NoemaClient(server=origin, config_home=tmp_path, http=default_http, transport="http")
        cred = client.connect(announce=lambda _msg: fake.approve())
        assert fake.device_starts == 1
        assert cred.access_token == "tok.fixture-secret"
    finally:
        httpd.shutdown()


def test_connect_is_noop_for_usable_token(tmp_path: Path):
    fake = FakeNoema()
    origin, httpd, _ = serve_fake(fake)
    try:
        save_credential(StoredCredential(access_token=VALID_JWT, server=origin), tmp_path)
        client = NoemaClient(server=origin, config_home=tmp_path, http=default_http, transport="http")
        cred = client.connect()
        assert cred.access_token == VALID_JWT
        assert fake.device_starts == 0
        assert load_credential(tmp_path).access_token == VALID_JWT
        assert client.session.connected is True
    finally:
        httpd.shutdown()


def test_connect_force_reenrolls_usable_token(tmp_path: Path):
    fake = FakeNoema()
    origin, httpd, _ = serve_fake(fake)
    try:
        save_credential(StoredCredential(access_token=VALID_JWT, server=origin), tmp_path)
        client = NoemaClient(server=origin, config_home=tmp_path, http=default_http, transport="http")
        notes: list[str] = []
        cred = client.connect(force=True, announce=lambda msg: (notes.append(msg), fake.approve()))
        assert fake.device_starts == 1
        assert cred.access_token == "tok.fixture-secret"
        assert any("Forcing" in msg for msg in notes)
        _assert_secret_absent("".join(notes), VALID_JWT, "tok.fixture-secret")
    finally:
        httpd.shutdown()


def test_require_gateway_refuses_expired_without_commands(tmp_path: Path):
    fake = FakeNoema()
    origin, httpd, _ = serve_fake(fake)
    try:
        save_credential(StoredCredential(access_token=EXPIRED_JWT, server=origin), tmp_path)
        client = NoemaClient(server=origin, config_home=tmp_path, transport="http")
        try:
            client._require_gateway()
            raise AssertionError("expected NOT_AUTHORIZED")
        except NoemaAuthError as exc:
            assert exc.code == "NOT_AUTHORIZED"
            assert "expired" in exc.message
        assert fake.commands == []
    finally:
        httpd.shutdown()


def test_cli_status_expired_does_not_print_token(tmp_path: Path, capsys):
    save_credential(StoredCredential(access_token=EXPIRED_JWT, server="https://example.invalid"), tmp_path)
    rc = cli_main(["--config-dir", str(tmp_path), "--server", "https://example.invalid", "status"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "credential: expired" in captured.out
    assert "connected: False" in captured.out
    _assert_secret_absent(captured.out + captured.err, EXPIRED_JWT)


def test_cli_doctor_expired_exits_nonzero(tmp_path: Path, capsys):
    fake = FakeNoema()
    origin, httpd, _ = serve_fake(fake)
    try:
        save_credential(StoredCredential(access_token=EXPIRED_JWT, server=origin), tmp_path)
        rc = cli_main(["--config-dir", str(tmp_path), "--server", origin, "doctor"])
        captured = capsys.readouterr()
        assert rc == 1
        assert "credential: expired" in captured.out
        assert fake.commands == []
        _assert_secret_absent(captured.out + captured.err, EXPIRED_JWT)
    finally:
        httpd.shutdown()


def test_cli_connect_expired_reenrolls(tmp_path: Path, capsys):
    fake = FakeNoema()
    fake.auto_approve = True
    origin, httpd, _ = serve_fake(fake)
    try:
        save_credential(StoredCredential(access_token=EXPIRED_JWT, server=origin), tmp_path)
        rc = cli_main(["--config-dir", str(tmp_path), "--server", origin, "--transport", "http", "connect"])
        captured = capsys.readouterr()
        assert rc == 0
        assert "Connected." in captured.out
        assert "expired" in captured.out
        assert fake.device_starts == 1
        loaded = load_credential(tmp_path)
        assert loaded and loaded.access_token == "tok.fixture-secret"
        _assert_secret_absent(captured.out + captured.err, EXPIRED_JWT, "tok.fixture-secret")
    finally:
        httpd.shutdown()


def test_cli_connect_force_reenrolls_usable_token(tmp_path: Path, capsys):
    fake = FakeNoema()
    fake.auto_approve = True
    origin, httpd, _ = serve_fake(fake)
    try:
        save_credential(StoredCredential(access_token=VALID_JWT, server=origin), tmp_path)
        rc = cli_main(
            ["--config-dir", str(tmp_path), "--server", origin, "--transport", "http", "connect", "--force"]
        )
        captured = capsys.readouterr()
        assert rc == 0
        assert fake.device_starts == 1
        loaded = load_credential(tmp_path)
        assert loaded and loaded.access_token == "tok.fixture-secret"
        _assert_secret_absent(captured.out + captured.err, VALID_JWT, "tok.fixture-secret")
    finally:
        httpd.shutdown()
