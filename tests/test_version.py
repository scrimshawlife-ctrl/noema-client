from __future__ import annotations

import tomllib
from importlib.metadata import metadata, version
from pathlib import Path

import noema_client.client as client_module
from noema_client import __version__
from noema_client.cli import build_parser, main
from noema_client.client import NoemaClient
from noema_client.protocol import WebSocketGateway
from noema_client.transport import USER_AGENT, HttpGateway
from noema_client.types import ActionProposal, CommandResult, Observation


class Token:
    def reveal(self):
        return "fixture-token"


def test_package_metadata_derives_version_from_authoritative_module():
    metadata = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert "version" not in metadata["project"]
    assert "version" in metadata["project"]["dynamic"]
    assert metadata["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "noema_client._version.__version__"
    }


def test_installed_and_generated_metadata_match_authoritative_version():
    assert version("noema-client") == __version__
    assert metadata("noema-client")["Version"] == __version__
    package_info = (Path(__file__).parents[1] / "src/noema_client.egg-info/PKG-INFO").read_text()
    assert f"Version: {__version__}\n" in package_info


def test_cli_version_uses_runtime_package_version(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == __version__


def test_cli_parser_version_action_is_defined_from_package_version():
    action = next(action for action in build_parser()._actions if action.dest == "version")
    assert action.version == __version__


def test_http_advertisements_use_authoritative_version():
    requests = []

    def http(method, url, body, token, headers=None):
        requests.append((method, url, body, token, headers))
        return {"ok": True}

    HttpGateway("https://example.invalid", Token(), http=http).send_command("LOOK")
    assert USER_AGENT == f"noema-client/{__version__} (+https://github.com/scrimshawlife-ctrl/noema-client)"
    assert requests[-1][2]["client"]["client_version"] == __version__


def test_websocket_protocol_client_version_uses_authoritative_version():
    frames = []
    gateway = WebSocketGateway("wss://example.invalid", Token())
    gateway._ws = object()
    gateway._rpc = lambda frame: frames.append(frame) or {"ok": True}  # type: ignore[method-assign]
    gateway.send_command("LOOK")
    assert frames[-1]["body"]["client"]["client_version"] == __version__


def test_action_receipt_uses_runtime_package_version(monkeypatch):
    client = NoemaClient.__new__(NoemaClient)
    receipts = []
    client.telemetry = type(
        "Telemetry", (), {"record": lambda self, **fields: receipts.append(fields) or fields}
    )()
    client.observation = Observation()
    client.policy = object()
    client.config_home = None
    client.session = type("Session", (), {"protocol": "agent-protocol/v1", "transport": "http"})()
    client._require_gateway = lambda: type(
        "Gateway",
        (),
        {
            "send_command": lambda self, command, arguments=None, *, idempotency_key=None, request_id=None, retries=1: (
                CommandResult(True, {}, None, True, 200, None, "i", "r")
            )
        },
    )()
    monkeypatch.setattr(
        client_module,
        "validate_proposal",
        lambda proposal, _obs, _policy: type(
            "Validated", (), {"command": proposal.action, "arguments": proposal.arguments}
        )(),
    )

    client.act(ActionProposal("LOOK"))
    assert receipts[-1]["client_version"] == __version__
