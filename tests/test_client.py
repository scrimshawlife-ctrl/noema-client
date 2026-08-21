from __future__ import annotations

import json
from pathlib import Path

import pytest

from noema_client import ActionProposal, NoemaActionRejected, NoemaClient, NoemaError, NoemaSealError
from noema_client.auth import DeviceEnrollment
from noema_client.cli import main as cli_main
from noema_client.config import load_credential, save_credential, StoredCredential
from noema_client.discovery import parse_discovery
from noema_client.errors import NoemaAuthError
from noema_client.isolated import admit_isolated_world_id, is_isolated_world
from noema_client.policy import ClientPolicy
from noema_client.seal import refused_play_flag, resolve_seal, sealed_prompt_hash
from noema_client.transport import default_http
from fake_server import FakeNoema, serve_fake
from fake_ws import FakeWsServer


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


def test_settlement_resync_retries_once_same_keys(tmp_path: Path):
    fake = FakeNoema()
    fake.resync_remaining = 1
    origin, httpd, _ = serve_fake(fake)
    try:
        save_credential(StoredCredential(access_token="tok.fixture-secret", server=origin), tmp_path)
        client = NoemaClient(server=origin, config_home=tmp_path, transport="http")
        client._credential = load_credential(tmp_path)
        client.discover()
        client._bind_gateway(client._credential)
        result = client._gateway.send_command("LOOK", {}, idempotency_key="idem.resync", request_id="req.resync")
        assert result.ok is True
        looks = [c for c in fake.commands if c.get("command") == "LOOK"]
        assert len(looks) == 2
        assert looks[0]["idempotency_key"] == looks[1]["idempotency_key"] == "idem.resync"
        seq0 = (looks[0].get("client") or {}).get("client_action_sequence")
        seq1 = (looks[1].get("client") or {}).get("client_action_sequence")
        assert seq0 == seq1
        assert seq0 is not None
        assert result.failure is None
        assert result.world_status != "INCIDENT"
    finally:
        httpd.shutdown()


def test_settlement_resync_does_not_loop(tmp_path: Path):
    fake = FakeNoema()
    fake.resync_remaining = 5
    origin, httpd, _ = serve_fake(fake)
    try:
        save_credential(StoredCredential(access_token="tok.fixture-secret", server=origin), tmp_path)
        client = NoemaClient(server=origin, config_home=tmp_path, transport="http")
        client._credential = load_credential(tmp_path)
        client.discover()
        client._bind_gateway(client._credential)
        result = client._gateway.send_command("LOOK", {}, idempotency_key="idem.loop")
        assert result.ok is False
        assert (result.error or {}).get("code") == "SETTLEMENT_RESYNC"
        from noema_client.errors import FailureClass

        assert result.failure == FailureClass.SETTLEMENT_RESYNC
        assert result.failure != FailureClass.WORLD_INCIDENT
        looks = [c for c in fake.commands if c.get("idempotency_key") == "idem.loop"]
        assert len(looks) == 2
    finally:
        httpd.shutdown()


def test_forbidden_is_not_auto_retried(tmp_path: Path):
    fake = FakeNoema()
    origin, httpd, _ = serve_fake(fake)
    try:
        save_credential(StoredCredential(access_token="tok.fixture-secret", server=origin), tmp_path)
        client = NoemaClient(server=origin, config_home=tmp_path, transport="http")
        client._credential = load_credential(tmp_path)
        client.discover()
        client._bind_gateway(client._credential)
        fake.world_status = "INCIDENT"
        result = client._gateway.send_command("MOVE", {"direction": "east"}, idempotency_key="idem.inc")
        assert result.ok is False
        assert result.failure and result.failure.value == "WORLD_INCIDENT"
        moves = [c for c in fake.commands if c.get("command") == "MOVE"]
        assert len(moves) == 1
    finally:
        httpd.shutdown()


def test_cli_status_no_token(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NOEMA_CONFIG_DIR", str(tmp_path))
    save_credential(StoredCredential(access_token="tok.should-not-print", server="https://example.invalid"), tmp_path)
    rc = cli_main(["--config-dir", str(tmp_path), "status"])
    assert rc == 0


def test_cli_act_enter_world_skips_observe_on_fresh_session(tmp_path: Path):
    fake = FakeNoema()
    fake.observe_requires_enter = True
    origin, httpd, _ = serve_fake(fake)
    try:
        save_credential(StoredCredential(access_token="tok.fixture-secret", server=origin), tmp_path)
        rc = cli_main(["--config-dir", str(tmp_path), "act", "ENTER_WORLD"])
        assert rc == 0
        assert fake.in_world is True
        assert any(c.get("command") == "ENTER_WORLD" for c in fake.commands)
        assert not any(c.get("command") in {"LOOK", "OBSERVE"} for c in fake.commands)
    finally:
        httpd.shutdown()


def test_admit_isolated_world_id():
    assert is_isolated_world("test.hosted-canonical.client-proof")
    assert not is_isolated_world("world.perihelion-reach")
    assert admit_isolated_world_id("test.hosted-canonical.client-proof") == "test.hosted-canonical.client-proof"
    with pytest.raises(NoemaError) as peri:
        admit_isolated_world_id("world.perihelion-reach")
    assert peri.value.code == "WORLD_FORBIDDEN"
    with pytest.raises(NoemaError):
        admit_isolated_world_id("world-01")
    with pytest.raises(NoemaError):
        admit_isolated_world_id("test.hosted-canonical.")
    with pytest.raises(NoemaError):
        admit_isolated_world_id(None)


def test_isolated_flag_is_not_a_live_seal_bypass():
    d = parse_discovery(
        "https://noema.guru",
        {"protocol": "agent-protocol/v1", "accepted_seals": [sealed_prompt_hash()], "seal_required": True},
    )
    # isolated=True still skips only when the caller also uses an admitted world via client bind
    assert resolve_seal(d, live_default=True, isolated=False) == sealed_prompt_hash()
    assert resolve_seal(d, live_default=True, isolated=True, world_id="test.hosted-canonical.ack") is None


def test_isolated_posts_test_world_path_without_seal(tmp_path: Path):
    fake = FakeNoema()
    origin, httpd, _ = serve_fake(fake)
    try:
        save_credential(StoredCredential(access_token="tok.fixture-secret", server=origin), tmp_path)
        client = NoemaClient(
            server=origin,
            config_home=tmp_path,
            transport="http",
            isolated=True,
            world_id="test.hosted-canonical.client-proof",
            admin_token="aaa.bbb.ccc",
        )
        client._credential = load_credential(tmp_path)
        client.discover()
        client._bind_gateway(client._credential)
        entered = client.act(ActionProposal(action="ENTER_WORLD"))
        assert entered.ok
        obs = client.observe()
        assert obs.location and obs.location["name"] == "Grid Anchor"
        assert client.act(ActionProposal(action="LOOK")).ok
        assert client.act(ActionProposal(action="WAIT")).ok
        paths = [c.get("_path") for c in fake.commands]
        assert all(p == "/v1/operator/test-world/command" for p in paths)
        assert all(c.get("world_id") == "test.hosted-canonical.client-proof" for c in fake.commands)
        assert all(c.get("_had_seal") is False for c in fake.commands)
        assert all(c.get("_had_admin") is True for c in fake.commands)
        status = client.status()
        assert status["isolated"] is True
        assert status["seal"] == "none"
        assert status["admin_header"] == "present"
        assert "aaa.bbb.ccc" not in json.dumps(status)
        assert "tok.fixture-secret" not in json.dumps(status)
        cred_blob = (tmp_path / "credential.json").read_text()
        assert "aaa.bbb.ccc" not in cred_blob
        assert "ADMIN" not in cred_blob
    finally:
        httpd.shutdown()


def test_isolated_refuses_perihelion_world_id(tmp_path: Path):
    fake = FakeNoema()
    origin, httpd, _ = serve_fake(fake)
    try:
        save_credential(StoredCredential(access_token="tok.fixture-secret", server=origin), tmp_path)
        client = NoemaClient(
            server=origin,
            config_home=tmp_path,
            transport="http",
            isolated=True,
            world_id="world.perihelion-reach",
            admin_token="aaa.bbb.ccc",
        )
        client._credential = load_credential(tmp_path)
        client.discover()
        with pytest.raises(NoemaError) as exc:
            client._bind_gateway(client._credential)
        assert exc.value.code == "WORLD_FORBIDDEN"
        assert fake.commands == []
    finally:
        httpd.shutdown()


def test_isolated_refuses_raw_operator_secret(tmp_path: Path):
    fake = FakeNoema()
    origin, httpd, _ = serve_fake(fake)
    try:
        save_credential(StoredCredential(access_token="tok.fixture-secret", server=origin), tmp_path)
        client = NoemaClient(
            server=origin,
            config_home=tmp_path,
            transport="http",
            isolated=True,
            world_id="test.hosted-canonical.client-proof",
            admin_token="operator-token-value-ok",
        )
        client._credential = load_credential(tmp_path)
        client.discover()
        with pytest.raises(NoemaAuthError) as exc:
            client._bind_gateway(client._credential)
        assert exc.value.code == "ADMIN_REQUIRED"
        assert fake.commands == []
    finally:
        httpd.shutdown()


def test_isolated_without_world_id_fails_closed(tmp_path: Path):
    save_credential(StoredCredential(access_token="tok.fixture-secret", server="https://example.invalid"), tmp_path)
    client = NoemaClient(server="https://example.invalid", config_home=tmp_path, transport="http", isolated=True)
    client._credential = load_credential(tmp_path)
    with pytest.raises(NoemaError) as exc:
        client._bind_gateway(client._credential)
    assert exc.value.code == "WORLD_FORBIDDEN"


def test_websocket_act_observe_and_resume(tmp_path: Path):
    fake_http = FakeNoema()
    origin, httpd, _ = serve_fake(fake_http)
    ws = FakeWsServer()
    try:
        save_credential(StoredCredential(access_token="tok.fixture-secret", server=origin), tmp_path)
        client = NoemaClient(
            server=origin,
            config_home=tmp_path,
            transport="websocket",
            ws_connect=ws.connect,
        )
        client._credential = load_credential(tmp_path)
        client.discover()
        client._bind_gateway(client._credential)
        assert client.session.transport == "websocket"
        entered = client.act(ActionProposal(action="ENTER_WORLD"))
        assert entered.ok
        obs = client.observe()
        assert obs.location and obs.location["name"] == "Grid Anchor"
        waited = client.act(ActionProposal(action="WAIT"))
        assert waited.ok
        types = [f.get("type") for f in ws.frames]
        assert "HELLO" in types
        assert "AUTH" in types
        assert "ACT" in types
        assert "OBSERVE" in types
        status = client.status()
        assert status["transport"] == "websocket"
        assert status["resume"] == "stored"
        blob = json.dumps(status)
        assert "resume.fixture.1" not in blob
        cred = load_credential(tmp_path)
        assert cred and cred.resume_token == "resume.fixture.1"
        assert "resume.fixture.1" not in repr(cred)
        client.disconnect()
        assert ws.closed >= 1

        again = NoemaClient(
            server=origin,
            config_home=tmp_path,
            transport="websocket",
            ws_connect=ws.connect,
        )
        again._credential = load_credential(tmp_path)
        again.discover()
        again._bind_gateway(again._credential)
        hello_bodies = [f.get("body") or {} for f in ws.frames if f.get("type") == "HELLO"]
        assert any(b.get("resume_token") == "resume.fixture.1" for b in hello_bodies)
        assert again.act(ActionProposal(action="LOOK")).ok
        again.disconnect(forget=True)
        assert load_credential(tmp_path) is None
    finally:
        httpd.shutdown()


def test_websocket_reconnects_after_drop(tmp_path: Path):
    fake_http = FakeNoema()
    origin, httpd, _ = serve_fake(fake_http)
    ws = FakeWsServer()
    ws.drop_after = 1
    try:
        save_credential(
            StoredCredential(access_token="tok.fixture-secret", server=origin, resume_token="resume.fixture.1"),
            tmp_path,
        )
        ws.resume_tokens["resume.fixture.1"] = {"player_id": "player.fixture"}
        client = NoemaClient(
            server=origin,
            config_home=tmp_path,
            transport="websocket",
            ws_connect=ws.connect,
        )
        client._credential = load_credential(tmp_path)
        client.discover()
        client._bind_gateway(client._credential)
        first = client.act(ActionProposal(action="LOOK"))
        assert first.ok
        second = client.act(ActionProposal(action="WAIT"))
        assert second.ok
        assert ws.connections >= 2
    finally:
        httpd.shutdown()


def test_isolated_refuses_websocket_transport(tmp_path: Path):
    save_credential(StoredCredential(access_token="tok.fixture-secret", server="https://example.invalid"), tmp_path)
    client = NoemaClient(
        server="https://example.invalid",
        config_home=tmp_path,
        transport="websocket",
        isolated=True,
        world_id="test.hosted-canonical.client-proof",
        admin_token="aaa.bbb.ccc",
    )
    client._credential = load_credential(tmp_path)
    with pytest.raises(NoemaError) as exc:
        client._bind_gateway(client._credential)
    assert exc.value.code == "WS_ISOLATED"


def test_play_continues_after_settlement_race(tmp_path: Path):
    from noema_client.adapters.scripted import ScriptedAdapter
    from noema_client.errors import FailureClass
    from noema_client.types import CommandResult

    class Seq:
        def __init__(self) -> None:
            self.waits = 0

        def send_command(self, command, arguments=None, **kwargs):
            cmd = str(command).upper()
            if cmd in {"OBSERVE", "LOOK", "ENTER_WORLD"}:
                return CommandResult(
                    ok=True,
                    observation={"world_status": "ACTIVE", "available_actions": ["WAIT"]},
                    error=None,
                    settled=True,
                    http_status=200,
                    failure=None,
                    idempotency_key="k",
                    request_id="r",
                    world_status="ACTIVE",
                )
            self.waits += 1
            if self.waits == 1:
                return CommandResult(
                    ok=False,
                    observation=None,
                    error={"code": "STALE_HEAD", "message": "That action lost the settlement race. Observe and try again."},
                    settled=False,
                    http_status=409,
                    failure=FailureClass.ACTION_REJECTED,
                    idempotency_key="k",
                    request_id="r",
                    world_status="ACTIVE",
                )
            return CommandResult(
                ok=True,
                observation={"world_status": "ACTIVE", "available_actions": ["WAIT"], "consequence": "waited"},
                error=None,
                settled=True,
                http_status=200,
                failure=None,
                idempotency_key="k",
                request_id="r",
                world_status="ACTIVE",
            )

        def close(self) -> None:
            return None

    client = NoemaClient(server="https://example.invalid", config_home=tmp_path, transport="http")
    client._gateway = Seq()
    turns = client.play(
        max_actions=3,
        adapter=ScriptedAdapter([ActionProposal(action="WAIT"), ActionProposal(action="WAIT"), ActionProposal(action="WAIT")]),
        enter=False,
    )
    assert len(turns) == 3
    assert turns[0].ok is False
    assert turns[0].stopped is False
    assert turns[1].ok is True
    assert turns[2].ok is True


def test_cli_act_recovers_from_expired_in_world_binding(tmp_path: Path):
    """#17: NOT_IN_WORLD from the pre-act observe must trigger re-enter + retry,
    not be swallowed into a misleading 'is not advertised' failure."""
    fake = FakeNoema()
    fake.observe_requires_enter = True
    fake.in_world = False  # world-session expired; JWT still valid
    origin, httpd, _ = serve_fake(fake)
    try:
        save_credential(StoredCredential(access_token="tok.fixture-secret", server=origin), tmp_path)
        rc = cli_main(["--config-dir", str(tmp_path), "act", "LOOK"])
        assert rc == 0
        sent = [c.get("command") for c in fake.commands]
        # auto ENTER_WORLD before the action; observe retried; LOOK succeeds
        assert "ENTER_WORLD" in sent
        assert sent.index("ENTER_WORLD") < sent.index("LOOK")
        assert fake.in_world is True
    finally:
        httpd.shutdown()


def test_cli_act_still_best_effort_on_other_observe_failures(tmp_path: Path, monkeypatch):
    """Non-NOT_IN_WORLD observe failures stay best-effort (logged, not fatal)."""
    from noema_client import cli as cli_mod
    from noema_client.errors import NoemaTransportError

    fake = FakeNoema()
    origin, httpd, _ = serve_fake(fake)
    try:
        save_credential(StoredCredential(access_token="tok.fixture-secret", server=origin), tmp_path)
        real_observe = cli_mod.NoemaClient.observe
        calls = {"n": 0}

        def flaky_observe(self):
            if calls["n"] == 0:
                calls["n"] += 1
                raise NoemaTransportError("TIMEOUT", "lost response", retryable=True)
            return real_observe(self)

        monkeypatch.setattr(cli_mod.NoemaClient, "observe", flaky_observe)
        rc = cli_main(["--config-dir", str(tmp_path), "act", "LOOK"])
        assert rc == 0
        sent = [c.get("command") for c in fake.commands]
        assert "LOOK" in sent
        assert "ENTER_WORLD" not in sent  # no spurious re-enter for transport blips
    finally:
        httpd.shutdown()
