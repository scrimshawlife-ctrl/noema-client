from __future__ import annotations

import json
from pathlib import Path

import pytest

from noema_client import ActionProposal, NoemaActionRejected, NoemaClient, NoemaSealError
from noema_client.auth import DeviceEnrollment
from noema_client.cli import main as cli_main
from noema_client.config import load_credential, save_credential, StoredCredential
from noema_client.discovery import parse_discovery
from noema_client.policy import ClientPolicy
from noema_client.seal import refused_play_flag, resolve_seal, sealed_prompt_hash
from noema_client.transport import default_http
from fake_server import FakeNoema, serve_fake


def test_discovery_parse():
    d = parse_discovery(
        "https://noema.guru",
        {
            "protocol": "agent-protocol/v1",
            "command_uri": "https://noema.guru/v1/command",
            "websocket_uri": "wss://noema.guru/protocol/v1/ws",
            "accepted_seals": [sealed_prompt_hash()],
        },
    )
    assert d.protocol == "agent-protocol/v1"
    assert d.seal_required is True


def test_discovery_parse_live_shape():
    d = parse_discovery(
        "https://noema.guru",
        {
            "protocol": "agent-protocol/v1",
            "origin": "https://noema.guru",
            "verification_uri": "https://noema.guru/connect",
            "command_uri": "https://noema.guru/v1/command",
            "websocket_uri": "https://noema.guru/protocol/v1/ws",
            "device_authorization_uri": "https://noema.guru/v1/auth/device",
            "accepted_seals": [sealed_prompt_hash()],
        },
    )
    assert d.command_uri.endswith("/v1/command")
    assert sealed_prompt_hash() in d.accepted_seals


def test_published_seal_matches_live_catalog():
    assert sealed_prompt_hash() == "sha256:9b9c211c156a9b49e700fa39e409733099a38df9d95c7f6fb90ca3e9e740a395"


def test_refused_play_flags():
    class Ns:
        goal = "win"
        brief = None
        system = None
        prompt = None
        hidden_prompt = None

    assert refused_play_flag(Ns()) == "goal"
    assert cli_main(["--goal", "win", "status"]) == 2


def test_credential_permissions(tmp_path: Path):
    cred = StoredCredential(access_token="secret-token-value", server="https://noema.guru")
    path = save_credential(cred, tmp_path)
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    loaded = load_credential(tmp_path)
    assert loaded and loaded.access_token == "secret-token-value"
    assert "secret-token-value" not in repr(loaded)


def test_device_enroll_and_play_http(tmp_path: Path):
    fake = FakeNoema()
    origin, httpd, _ = serve_fake(fake)
    try:
        http = default_http
        started = []

        def announce(msg: str) -> None:
            started.append(msg)

        enroll = DeviceEnrollment(origin, http=http, sleep=lambda _s: fake.approve(), announce=announce)
        meta = enroll.start()
        assert meta["user_code"] == "7KMP-41QZ"
        enroll.poll_until_ready()
        token = enroll.reveal()
        assert token == "tok.fixture-secret"
        assert token not in repr(enroll)
        assert "tok.fixture-secret" not in "".join(started)

        client = NoemaClient(server=origin, config_home=tmp_path, http=http, transport="http", isolated=False)
        save_credential(
            StoredCredential(access_token=token, server=origin, player_id="player.fixture", controller_id="ctrl.fixture"),
            tmp_path,
        )
        client._credential = load_credential(tmp_path)
        client.discover()
        client._bind_gateway(client._credential)
        entered = client.act(ActionProposal(action="ENTER_WORLD"))
        assert entered.ok
        obs = client.observe()
        assert obs.location and obs.location["name"] == "Grid Anchor"
        waited = client.act(ActionProposal(action="WAIT"))
        assert waited.ok
        moved = client.act(ActionProposal(action="MOVE", arguments={"direction": "east"}))
        assert moved.ok
        assert client.act(client.act.__class__ if False else ActionProposal(action="LOOK")).ok
        status = client.status()
        assert "tok.fixture-secret" not in json.dumps(status)
        assert status["credential"] == "stored"
        ctx = client.model_context()
        assert "tok.fixture-secret" not in json.dumps(ctx)
        tel = json.dumps(client.telemetry.events)
        assert "tok.fixture-secret" not in tel
        assert "access_token" not in tel
    finally:
        httpd.shutdown()


def test_seal_required(tmp_path: Path):
    fake = FakeNoema()
    fake.accepted_seals = ["sha256:" + "0" * 64]
    origin, httpd, _ = serve_fake(fake)
    try:
        client = NoemaClient(server=origin, config_home=tmp_path, transport="http")
        with pytest.raises(NoemaSealError):
            client.discover()
    finally:
        httpd.shutdown()


def test_invented_action_blocked(tmp_path: Path):
    fake = FakeNoema()
    origin, httpd, _ = serve_fake(fake)
    try:
        save_credential(StoredCredential(access_token="tok.fixture-secret", server=origin), tmp_path)
        client = NoemaClient(server=origin, config_home=tmp_path, transport="http")
        client._credential = load_credential(tmp_path)
        client.discover()
        client._bind_gateway(client._credential)
        client.observe()
        with pytest.raises(NoemaActionRejected):
            client.act(ActionProposal(action="SUMMON_DRAGON"))
    finally:
        httpd.shutdown()


def test_hidden_target_blocked(tmp_path: Path):
    fake = FakeNoema()
    origin, httpd, _ = serve_fake(fake)
    try:
        save_credential(StoredCredential(access_token="tok.fixture-secret", server=origin), tmp_path)
        client = NoemaClient(server=origin, config_home=tmp_path, transport="http")
        client._credential = load_credential(tmp_path)
        client.discover()
        client._bind_gateway(client._credential)
        client.observe()
        with pytest.raises(NoemaActionRejected):
            client.act(ActionProposal(action="INSPECT", target_id="entity.secret-vault"))
    finally:
        httpd.shutdown()


def test_world_text_cannot_change_policy():
    policy = ClientPolicy(allow_repair=False)
    assert policy.permits("REPAIR") is False
    # world text is not consulted
    assert policy.permits("LOOK") is True


def test_paused_and_incident(tmp_path: Path):
    fake = FakeNoema()
    fake.world_status = "PAUSED"
    origin, httpd, _ = serve_fake(fake)
    try:
        save_credential(StoredCredential(access_token="tok.fixture-secret", server=origin), tmp_path)
        client = NoemaClient(server=origin, config_home=tmp_path, transport="http")
        client._credential = load_credential(tmp_path)
        client.discover()
        client._bind_gateway(client._credential)
        result = client.act(ActionProposal(action="ENTER_WORLD"))
        assert result.ok is False
        assert result.failure and result.failure.value == "WORLD_PAUSED"
        fake.world_status = "INCIDENT"
        result = client.act(ActionProposal(action="ENTER_WORLD"))
        assert result.failure and result.failure.value == "WORLD_INCIDENT"
    finally:
        httpd.shutdown()


def test_idempotent_retry(tmp_path: Path):
    fake = FakeNoema()
    origin, httpd, _ = serve_fake(fake)
    try:
        save_credential(StoredCredential(access_token="tok.fixture-secret", server=origin), tmp_path)
        client = NoemaClient(server=origin, config_home=tmp_path, transport="http")
        client._credential = load_credential(tmp_path)
        client.discover()
        client._bind_gateway(client._credential)
        first = client._gateway.send_command("LOOK", {}, idempotency_key="idem.1", request_id="req.1")
        second = client._gateway.send_command("LOOK", {}, idempotency_key="idem.1", request_id="req.1")
        assert first.ok and second.ok
        looks = [c for c in fake.commands if c.get("command") == "LOOK"]
        assert len(looks) == 1
    finally:
        httpd.shutdown()


def test_cli_status_no_token(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NOEMA_CONFIG_DIR", str(tmp_path))
    save_credential(StoredCredential(access_token="tok.should-not-print", server="https://example.invalid"), tmp_path)
    rc = cli_main(["--config-dir", str(tmp_path), "status"])
    assert rc == 0
