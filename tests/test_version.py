from __future__ import annotations

import tomllib
from pathlib import Path

import noema_client.client as client_module
from noema_client import __version__
from noema_client.cli import build_parser, main
from noema_client.client import NoemaClient
from noema_client.types import ActionProposal, CommandResult, Observation


def test_runtime_version_matches_package_metadata():
    metadata = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert __version__ == metadata["project"]["version"]


def test_cli_version_uses_runtime_package_version(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == __version__


def test_cli_parser_version_action_is_defined_from_package_version():
    action = next(action for action in build_parser()._actions if action.dest == "version")
    assert action.version == __version__


def test_action_receipt_uses_runtime_package_version(monkeypatch):
    client = NoemaClient.__new__(NoemaClient)
    receipts = []
    client.telemetry = type("Telemetry", (), {"record": lambda self, **fields: receipts.append(fields) or fields})()
    client.observation = Observation()
    client.policy = object()
    client.config_home = None
    client.session = type("Session", (), {"protocol": "agent-protocol/v1", "transport": "http"})()
    client._require_gateway = lambda: type(
        "Gateway",
        (),
        {
            "send_command": lambda self, command, arguments=None, *, idempotency_key=None, request_id=None, retries=1: CommandResult(
                True, {}, None, True, 200, None, "i", "r"
            )
        },
    )()
    monkeypatch.setattr(client_module, "validate_proposal", lambda proposal, _obs, _policy: type(
        "Validated", (), {"command": proposal.action, "arguments": proposal.arguments}
    )())

    client.act(ActionProposal("LOOK"))
    assert receipts[-1]["client_version"] == __version__
