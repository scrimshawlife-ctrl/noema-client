"""Official CLI: noema connect | status | observe | play | act | alias | do | disconnect | doctor."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from noema_client.aliases import apply_alias_command, parse_alias_command
from noema_client.client import NoemaClient
from noema_client.config import load_aliases, save_aliases
from noema_client.errors import NoemaError
from noema_client.observations import render_observation
from noema_client.seal import refused_play_flag
from noema_client.types import ActionProposal

BANNED = ("goal", "brief", "system", "hidden_prompt", "prompt")

_log = logging.getLogger("noema_client.cli")


def _client(ns: argparse.Namespace) -> NoemaClient:
    flagged = refused_play_flag(ns)
    if flagged:
        print(f"error: live flag --{flagged.replace('_', '-')} is refused (RFC-0115)", file=sys.stderr)
        raise SystemExit(2)
    return NoemaClient(
        server=getattr(ns, "server", None),
        config_home=Path(ns.config_dir) if getattr(ns, "config_dir", None) else None,
        transport=getattr(ns, "transport", "auto") or "auto",
        isolated=bool(getattr(ns, "isolated", False)),
        world_id=getattr(ns, "world_id", None),
    )


def cmd_connect(ns: argparse.Namespace) -> int:
    client = _client(ns)
    lines: list[str] = []

    def announce(msg: str) -> None:
        lines.append(msg)
        if "Approve" in msg and " at " in msg:
            code = msg.split("Approve ", 1)[1].split(" at ", 1)[0]
            uri = msg.split(" at ", 1)[1]
            print("NOEMA\n")
            print("Approve this agent:\n")
            print(uri)
            print()
            print("Code:")
            print(code)
            print()
            print("Waiting for approval...")
        else:
            print(msg)

    cred = client.connect(announce=announce)
    print()
    print("Connected.")
    print()
    print(f"World: {client.session.world or 'pending observe'}")
    print("Controller: agent")
    print(f"Protocol: {client.session.protocol}")
    print("Credential: stored locally")
    assert cred.access_token not in "".join(lines)
    return 0


def cmd_status(ns: argparse.Namespace) -> int:
    client = _client(ns)
    status = client.status()
    if ns.json:
        print(json.dumps(status, indent=2, sort_keys=True))
        return 0
    for key, value in status.items():
        print(f"{key}: {value}")
    blob = json.dumps(status)
    cred = client._credential
    if cred:
        assert cred.access_token not in blob
    return 0


def cmd_observe(ns: argparse.Namespace) -> int:
    client = _client(ns)
    if not client._credential:
        client.connect()
    obs = client.observe()
    if ns.json:
        print(json.dumps(obs.raw, indent=2, sort_keys=True, default=str))
    else:
        print(render_observation(obs))
    return 0


def cmd_act(ns: argparse.Namespace) -> int:
    client = _client(ns)
    if not client._credential:
        client.connect()
    action_upper = (ns.action or "").upper()
    if action_upper != "ENTER_WORLD":
        try:
            client.observe()
        except NoemaError as exc:
            if exc.code == "NOT_IN_WORLD":
                # The server-side in-world binding expires independently of the
                # JWT (#17). Re-enter (idempotent) and retry observe once so the
                # act below validates against the real affordance list instead
                # of a stale one — otherwise the client-side check misreports
                # the action as "not advertised". A failure here propagates to
                # main() and prints the true cause.
                client.act(ActionProposal(action="ENTER_WORLD"))
                client.observe()
            else:
                _log.debug("pre-act observe failed: %s", exc)
        except Exception as exc:
            _log.debug("pre-act observe failed: %s", exc)
    args: dict = {}
    if ns.arguments:
        args = json.loads(ns.arguments)
    proposal = ActionProposal(action=ns.action, target_id=ns.target, arguments=args)
    result = client.act(proposal)
    if not result.ok:
        err = result.error or {}
        print(f"{err.get('code') or 'REJECTED'}: {err.get('message') or ''}", file=sys.stderr)
        return 1
    if result.observation:
        from noema_client.observations import to_observation

        print(render_observation(to_observation(result.observation)))
    return 0


def cmd_play(ns: argparse.Namespace) -> int:
    client = _client(ns)
    if not client._credential:
        client.connect()
    turns = client.play(max_actions=ns.max_actions, enter=not ns.no_enter)
    ok = 0
    for turn in turns:
        if hasattr(turn, "ok"):
            ok += int(bool(turn.ok))
    print(f"play finished turns={len(turns)}")
    return 0 if turns else 1


def cmd_doctor(ns: argparse.Namespace) -> int:
    client = _client(ns)
    report = client.doctor()
    if ns.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0 if report.get("reachability") == "ok" else 1


def cmd_disconnect(ns: argparse.Namespace) -> int:
    client = _client(ns)
    client.disconnect(forget=ns.forget)
    print("Disconnected local Controller session.")
    if ns.forget:
        print("Local credential removed. The Player remains in the world.")
    return 0


def _config_home(ns: argparse.Namespace) -> Path | None:
    return Path(ns.config_dir) if getattr(ns, "config_dir", None) else None


def cmd_alias(ns: argparse.Namespace) -> int:
    directory = _config_home(ns)
    aliases = load_aliases(directory)
    if ns.alias_op == "list":
        line = "alias list"
    elif ns.alias_op == "rm":
        line = f"alias rm {ns.name}"
    else:
        line = f"alias set {ns.name} {' '.join(ns.expansion)}"
    parsed = parse_alias_command(line)
    applied = apply_alias_command(aliases, parsed)
    if parsed is None or not parsed.ok:
        print(applied.text, file=sys.stderr)
        return 1
    if parsed.op == "set" and parsed.name not in applied.aliases:
        print(applied.text, file=sys.stderr)
        return 1
    if parsed.op in {"set", "rm"}:
        save_aliases(applied.aliases, directory)
    print(applied.text)
    return 0


def cmd_do(ns: argparse.Namespace) -> int:
    client = _client(ns)
    if not client._credential:
        client.connect()
    client.observe()
    line = " ".join(ns.steps)
    if not line.lower().startswith("do "):
        line = f"do {line}"
    results = client.run_macro(line)
    ok = True
    for result in results:
        if result.ok:
            if result.observation:
                from noema_client.observations import to_observation

                print(render_observation(to_observation(result.observation)))
        else:
            ok = False
            err = result.error or {}
            print(f"{err.get('code') or 'REJECTED'}: {err.get('message') or ''}", file=sys.stderr)
    return 0 if ok and results else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="noema", description="Official NOEMA Controller client")
    parser.add_argument("--server", default=None, help="NOEMA origin (default https://noema.guru or NOEMA_SERVER)")
    parser.add_argument("--config-dir", default=None)
    parser.add_argument("--transport", choices=["auto", "http", "websocket"], default="auto")
    parser.add_argument(
        "--isolated",
        action="store_true",
        help="isolated hosted tenant; requires --world-id test.hosted-canonical.*",
    )
    parser.add_argument(
        "--world-id",
        default=None,
        help="isolated world id (test.hosted-canonical.<suffix>); also NOEMA_WORLD_ID",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_connect = sub.add_parser("connect", help="device enrollment")
    p_connect.set_defaults(func=cmd_connect)

    p_status = sub.add_parser("status", help="connection status")
    p_status.add_argument("--json", action="store_true")
    p_status.set_defaults(func=cmd_status)

    p_obs = sub.add_parser("observe", help="current observation")
    p_obs.add_argument("--json", action="store_true")
    p_obs.set_defaults(func=cmd_observe)

    p_act = sub.add_parser("act", help="debug structured action")
    p_act.add_argument("action")
    p_act.add_argument("target", nargs="?")
    p_act.add_argument("--arguments", default=None, help="JSON object")
    p_act.set_defaults(func=cmd_act)

    p_play = sub.add_parser("play", help="bounded headless loop")
    p_play.add_argument("--max-actions", type=int, default=8)
    p_play.add_argument("--duration", type=float, default=None)
    p_play.add_argument("--cooldown", type=float, default=0.0)
    p_play.add_argument("--no-enter", action="store_true")
    p_play.set_defaults(func=cmd_play)

    p_doc = sub.add_parser("doctor", help="local diagnostics; does not mutate the world")
    p_doc.add_argument("--json", action="store_true")
    p_doc.set_defaults(func=cmd_doctor)

    p_disc = sub.add_parser("disconnect", help="stop local session")
    p_disc.add_argument("--forget", action="store_true", help="remove local credential; does not delete Player")
    p_disc.set_defaults(func=cmd_disconnect)

    p_alias = sub.add_parser("alias", help="player-preference aliases; not world truth")
    alias_sub = p_alias.add_subparsers(dest="alias_op", required=True)
    p_alias_list = alias_sub.add_parser("list", help="list local aliases")
    p_alias_list.set_defaults(func=cmd_alias)
    p_alias_set = alias_sub.add_parser("set", help="set a local alias")
    p_alias_set.add_argument("name")
    p_alias_set.add_argument("expansion", nargs="+")
    p_alias_set.set_defaults(func=cmd_alias)
    p_alias_rm = alias_sub.add_parser("rm", help="remove a local alias")
    p_alias_rm.add_argument("name")
    p_alias_rm.set_defaults(func=cmd_alias)

    p_do = sub.add_parser("do", help="bounded sequential macro; each step is an ordinary action")
    p_do.add_argument("steps", nargs="+", help='example: look; wait   (quote if using ";")')
    p_do.set_defaults(func=cmd_do)
    return parser


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])
    for flag in BANNED:
        token = f"--{flag.replace('_', '-')}"
        if token in raw:
            print(f"error: {token} is refused (RFC-0115 sealed live attach)", file=sys.stderr)
            return 2
    parser = build_parser()
    try:
        ns = parser.parse_args(raw)
    except SystemExit as exc:
        return int(exc.code or 0)
    try:
        return int(ns.func(ns))
    except NoemaError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 1
