#!/usr/bin/env python3
"""Operator isolated hosted proof for the official client.

Mints a short-lived agent Controller via Admin session, then drives
noema-client against POST /v1/operator/test-world/command.

Never prints tokens. Never writes Admin material to credential.json.
Never targets Perihelion. Does not use ~/.config/noema/tester.env.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from noema_client.client import NoemaClient
from noema_client.config import StoredCredential, save_credential
from noema_client.errors import NoemaError
from noema_client.isolated import admit_isolated_world_id
from noema_client.transport import default_http
from noema_client.types import ActionProposal

OPERATOR_ENV = Path.home() / ".config" / "noema" / "operator.env"
DEFAULT_BASE = "https://noema.guru"
DEFAULT_WORLD = "test.hosted-canonical.client-proof"


def _parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _http(method: str, url: str, body: dict | None, token: str | None, extra: dict[str, str] | None = None) -> dict:
    payload = default_http(method, url, body, token, extra)
    return payload if isinstance(payload, dict) else {}


def _redact(obj: object) -> object:
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            lk = str(key).lower()
            if any(part in lk for part in ("token", "authorization", "secret", "password", "jwt")):
                out[key] = "<redacted>"
            else:
                out[key] = _redact(value)
        return out
    if isinstance(obj, list):
        return [_redact(item) for item in obj]
    return obj


def main() -> int:
    world_id = admit_isolated_world_id(os.environ.get("NOEMA_WORLD_ID") or DEFAULT_WORLD)
    base = (os.environ.get("NOEMA_SERVER") or DEFAULT_BASE).rstrip("/")
    if not OPERATOR_ENV.is_file():
        print(json.dumps({"ok": False, "code": "UNCONFIGURED", "message": "missing operator.env"}))
        return 2
    loaded = _parse_env(OPERATOR_ENV)
    operator = loaded.get("ADMIN_OPERATOR_TOKEN") or loaded.get("ADMIN_TOKEN") or ""
    if not operator:
        print(json.dumps({"ok": False, "code": "UNCONFIGURED", "message": "ADMIN_OPERATOR_TOKEN missing"}))
        return 2

    sess = _http("POST", f"{base}/v1/admin/session", {"admin_token": operator}, None)
    admin_jwt = str(sess.get("access_token") or "")
    if not admin_jwt:
        print(json.dumps({"ok": False, "code": "ADMIN_SESSION_FAILED", "http": sess.get("_http_status")}))
        return 1
    minted = _http(
        "POST",
        f"{base}/v1/admin/controller-token",
        {"handle": "client-proof", "controller_type": "agent", "expires_in": 1800},
        admin_jwt,
    )
    player = str(minted.get("access_token") or "")
    if not player:
        print(json.dumps({"ok": False, "code": "PLAYER_MINT_FAILED", "http": minted.get("_http_status")}))
        return 1

    peri = _http(
        "POST",
        f"{base}/v1/operator/test-world/command",
        {
            "world_id": "world.perihelion-reach",
            "request_id": "client-proof-peri-deny",
            "command": "LOOK",
            "arguments": {},
        },
        player,
        {"X-Noema-Admin-Token": admin_jwt},
    )

    peri_http = peri.get("_http_status")
    if peri_http is None:
        peri_http = 200 if peri.get("ok") else 0
    peri_http = int(peri_http)
    summary: dict = {
        "ok": False,
        "world_id": world_id,
        "base": base,
        "client": "noema-client",
        "perihelion_denied_http": peri_http,
        "commands": [],
    }
    if peri.get("ok") is True or peri_http != 403:
        summary["code"] = "PERIHELION_NOT_DENIED"
        summary["perihelion_denied_http"] = peri_http
        print(json.dumps(_redact(summary), sort_keys=True))
        return 1
    summary["perihelion_denied_http"] = peri_http

    with tempfile.TemporaryDirectory(prefix="noema-isolated-proof-") as tmp:
        home = Path(tmp)
        save_credential(
            StoredCredential(
                access_token=player,
                server=base,
                controller_type="agent",
                world_id=world_id,
                player_id=str(minted.get("player_id") or "") or None,
            ),
            home,
        )
        client = NoemaClient(
            server=base,
            config_home=home,
            transport="http",
            isolated=True,
            world_id=world_id,
            admin_token=admin_jwt,
        )
        disc = client.discover()
        summary["protocol"] = disc.protocol
        summary["seal"] = "none" if client.seal is None else "sent"
        client.connect()
        cred_text = (home / "credential.json").read_text(encoding="utf-8")
        if admin_jwt in cred_text or operator in cred_text:
            summary["code"] = "ADMIN_PERSISTED"
            print(json.dumps(_redact(summary), sort_keys=True))
            return 1

        client_peri_denied = False
        try:
            NoemaClient(
                server=base,
                config_home=home,
                transport="http",
                isolated=True,
                world_id="world.perihelion-reach",
                admin_token=admin_jwt,
            )._bind_gateway(client._credential)  # type: ignore[arg-type]
        except NoemaError as exc:
            client_peri_denied = exc.code == "WORLD_FORBIDDEN"
        summary["client_perihelion_denied"] = client_peri_denied

        steps = ["ENTER_WORLD", "OBSERVE", "LOOK", "WAIT"]
        for command in steps:
            result = client.act(ActionProposal(action=command))
            obs = result.observation or {}
            summary["commands"].append(
                {
                    "command": command,
                    "ok": result.ok,
                    "http": result.http_status,
                    "code": (result.error or {}).get("code") if result.error else None,
                    "cycle": obs.get("cycle"),
                    "sequence": obs.get("sequence"),
                    "in_world": obs.get("in_world"),
                    "world_name": obs.get("world_name"),
                }
            )
        status = client.status()
        summary["status_seal"] = status.get("seal")
        summary["status_isolated"] = status.get("isolated")
        summary["admin_header"] = status.get("admin_header")
        client.disconnect(forget=True)

    cmds_ok = all(item.get("ok") for item in summary["commands"]) and len(summary["commands"]) == 4
    summary["ok"] = bool(
        cmds_ok
        and summary.get("seal") == "none"
        and summary.get("perihelion_denied_http") == 403
        and summary.get("client_perihelion_denied") is True
    )
    print(json.dumps(_redact(summary), sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
