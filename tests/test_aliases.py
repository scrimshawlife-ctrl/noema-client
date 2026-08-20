"""S4 player-preference aliases and bounded macros. Not world truth."""

from __future__ import annotations

from pathlib import Path

from fake_server import FakeNoema, serve_fake

from noema_client import ActionProposal, NoemaClient
from noema_client.aliases import (
    MAX_ALIAS_DEPTH,
    MAX_ALIASES,
    MAX_MACRO_STEPS,
    apply_alias_command,
    expand_aliases,
    expand_proposal,
    is_reserved_alias_name,
    macro_steps_from_line,
    parse_alias_command,
    proposal_from_line,
)
from noema_client.cli import main as cli_main
from noema_client.config import StoredCredential, load_aliases, load_credential, save_aliases, save_credential
from noema_client.transport import default_http


def _bound_client(tmp_path: Path, origin: str) -> NoemaClient:
    save_credential(StoredCredential(access_token="tok.fixture-secret", server=origin), tmp_path)
    client = NoemaClient(server=origin, config_home=tmp_path, transport="http", http=default_http)
    client._credential = load_credential(tmp_path)
    client.discover()
    client._bind_gateway(client._credential)
    client.observe()
    return client


def test_refuses_reserved_names_and_bounds_expansion_depth():
    assert is_reserved_alias_name("look") is True
    parsed = parse_alias_command("alias set look wait")
    assert parsed is not None
    assert parsed.ok is False
    loop = expand_aliases("a", {"a": "b", "b": "a"})
    assert loop.error and "deep" in loop.error.lower()
    assert MAX_ALIAS_DEPTH == 4
    assert MAX_MACRO_STEPS == 5
    assert MAX_ALIASES == 16


def test_lists_and_sets_aliases():
    parsed = parse_alias_command("alias set ii inspect scarred-conduit")
    applied = apply_alias_command({}, parsed)
    assert applied.aliases["ii"] == "inspect scarred-conduit"
    assert expand_aliases("ii", applied.aliases).line == "inspect scarred-conduit"
    listed = apply_alias_command(applied.aliases, parse_alias_command("alias list"))
    assert "ii → inspect scarred-conduit" in listed.text
    removed = apply_alias_command(applied.aliases, parse_alias_command("alias rm ii"))
    assert "ii" not in removed.aliases


def test_alias_expansion_appends_rest():
    expanded = expand_aliases("x scarred-conduit", {"x": "inspect"})
    assert expanded.line == "inspect scarred-conduit"
    proposal = proposal_from_line(expanded.line)
    assert proposal is not None
    assert proposal.action == "INSPECT"
    assert proposal.target_id == "scarred-conduit"


def test_dock_expands_to_move_south():
    expanded = expand_aliases("dock", {"dock": "move south"})
    proposal = expand_proposal(ActionProposal(action="dock"), {"dock": "move south"})
    assert expanded.line == "move south"
    assert proposal.action == "MOVE"
    assert proposal.arguments.get("direction") == "south"


def test_splits_do_macros_and_rejects_nesting_and_oversize():
    assert macro_steps_from_line("do look; wait").steps == ["look", "wait"]
    assert macro_steps_from_line("do look; do wait").error
    too_long = "do " + "; ".join(["look"] * 6)
    assert macro_steps_from_line(too_long).error


def test_alias_store_is_preference_file(tmp_path: Path):
    path = save_aliases({"dock": "move south"}, tmp_path)
    assert path.name == "aliases.json"
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    loaded = load_aliases(tmp_path)
    assert loaded["dock"] == "move south"


def test_act_expands_alias_to_ordinary_command(tmp_path: Path):
    fake = FakeNoema()
    origin, httpd, _ = serve_fake(fake)
    try:
        save_aliases({"ii": "inspect"}, tmp_path)
        client = _bound_client(tmp_path, origin)
        result = client.act(ActionProposal(action="ii", target_id="entity.way-lamp"))
        assert result.ok
        inspects = [c for c in fake.commands if c.get("command") == "INSPECT"]
        assert len(inspects) == 1
        assert inspects[0]["arguments"]["entity_id"] == "entity.way-lamp"
        aliases = [c for c in fake.commands if str(c.get("command") or "").upper() == "ALIAS"]
        assert aliases == []
    finally:
        httpd.shutdown()


def test_macro_steps_are_ordinary_independent_commands(tmp_path: Path):
    fake = FakeNoema()
    origin, httpd, _ = serve_fake(fake)
    try:
        client = _bound_client(tmp_path, origin)
        results = client.run_macro("do look; wait")
        assert len(results) == 2
        assert all(r.ok for r in results)
        commands = [c.get("command") for c in fake.commands]
        assert "LOOK" in commands
        assert "WAIT" in commands
        look_idx = commands.index("LOOK")
        wait_idx = commands.index("WAIT")
        assert wait_idx > look_idx
        keys = [c.get("idempotency_key") for c in fake.commands if c.get("command") in {"LOOK", "WAIT"}]
        assert len(set(keys)) == 2
    finally:
        httpd.shutdown()


def test_macro_stops_on_failure_without_hidden_retry(tmp_path: Path):
    fake = FakeNoema()
    fake.fail_command = "WAIT"
    fake.fail_error = {"code": "WORLD_BLOCKED", "message": "blocked"}
    origin, httpd, _ = serve_fake(fake)
    try:
        client = _bound_client(tmp_path, origin)
        results = client.run_macro("do look; wait; inspect entity.way-lamp")
        assert len(results) == 2
        assert results[0].ok is True
        assert results[1].ok is False
        inspects = [c for c in fake.commands if c.get("command") == "INSPECT"]
        waits = [c for c in fake.commands if c.get("command") == "WAIT"]
        assert inspects == []
        assert len(waits) == 1
    finally:
        httpd.shutdown()


def test_cli_alias_crud(tmp_path: Path, capsys):
    rc = cli_main(["--config-dir", str(tmp_path), "alias", "set", "dock", "move", "south"])
    assert rc == 0
    rc = cli_main(["--config-dir", str(tmp_path), "alias", "list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "dock → move south" in out
    rc = cli_main(["--config-dir", str(tmp_path), "alias", "rm", "dock"])
    assert rc == 0
    assert "dock" not in load_aliases(tmp_path)
    rc = cli_main(["--config-dir", str(tmp_path), "alias", "set", "look", "wait"])
    assert rc == 1
