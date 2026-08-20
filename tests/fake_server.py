"""Deterministic in-process NOEMA fixture. Not Perihelion.

Provenance: written for scrimshawlife-ctrl/noema-client tests.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse


class FakeNoema:
    def __init__(self) -> None:
        self.pending: dict[str, dict[str, Any]] = {}
        self.approved: dict[str, dict[str, Any]] = {}
        self.tokens: dict[str, dict[str, Any]] = {}
        self.commands: list[dict[str, Any]] = []
        self.world_status = "ACTIVE"
        self.in_world = False
        self.cycle = 4
        self.sequence = 10
        self.seen_idem: dict[str, dict[str, Any]] = {}
        self.seal_required = True
        self.accepted_seals = ["sha256:9b9c211c156a9b49e700fa39e409733099a38df9d95c7f6fb90ca3e9e740a395"]
        self.require_seal_on_command = True
        self.resync_remaining = 0

    def observation(self) -> dict[str, Any]:
        return {
            "ok": True,
            "world_name": "Perihelion Reach" if self.in_world else "fixture",
            "cycle": self.cycle,
            "sequence": self.sequence,
            "player_id": "player.fixture",
            "world_status": self.world_status,
            "location": {
                "room_id": "room.anchor",
                "name": "Grid Anchor",
                "exits": [{"direction": "east", "to_room_id": "room.east"}],
                "entities": [{"entity_id": "entity.way-lamp", "label": "way-lamp", "entity_type": "PROP"}],
            },
            "available_actions": ["LOOK", "WAIT", "OBSERVE", "MOVE", "INSPECT", "ENTER_WORLD"],
            "affordances": [
                {"action": "LOOK", "available": True},
                {"action": "WAIT", "available": True},
                {"action": "MOVE", "cmd": "move east", "target_id": "east", "available": True},
            ],
            "consequence": "You look around." if self.in_world else None,
            "in_world": self.in_world,
        }

    def handle(self, method: str, path: str, body: dict[str, Any], headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
        if method == "GET" and path == "/.well-known/noema-agent.json":
            return 200, {
                "protocol": "agent-protocol/v1",
                "origin": "http://fixture",
                "verification_uri": "http://fixture/connect",
                "command_uri": "http://fixture/v1/command",
                "websocket_uri": "ws://fixture/protocol/v1/ws",
                "seal_required": self.seal_required,
                "accepted_seals": list(self.accepted_seals),
                "transports": ["http", "websocket"],
            }
        if method == "GET" and path == "/health":
            return 200, {"status": "ok", "protocol_version": "1"}
        if method == "POST" and path == "/v1/auth/device":
            rec = {
                "device_code": "dev.fixture",
                "user_code": "7KMP-41QZ",
                "verification_uri": "http://fixture/connect",
                "expires_in": 600,
                "interval": 0,
                "status": "authorization_pending",
            }
            self.pending[rec["device_code"]] = rec
            return 200, rec
        if method == "POST" and path == "/v1/auth/device/token":
            code = str(body.get("device_code") or "")
            if code in self.approved:
                tok = {
                    "status": "approved",
                    "access_token": "tok.fixture-secret",
                    "player_id": "player.fixture",
                    "controller_id": "ctrl.fixture",
                }
                self.tokens[tok["access_token"]] = tok
                return 200, tok
            if code in self.pending:
                return 200, {"status": "authorization_pending", "interval": 0}
            return 400, {"status": "expired"}
        if method == "POST" and path in {"/v1/command", "/v1/operator/test-world/command"}:
            isolated = path.endswith("/test-world/command")
            auth = headers.get("Authorization") or headers.get("authorization") or ""
            if not auth.startswith("Bearer "):
                return 401, {"ok": False, "error": {"code": "NOT_AUTHORIZED", "message": "missing bearer"}}
            if isolated:
                admin = headers.get("X-Noema-Admin-Token") or headers.get("x-noema-admin-token") or ""
                if admin.count(".") != 2 or not admin:
                    return 401, {"ok": False, "error": {"code": "NOT_AUTHORIZED", "message": "signed admin jwt required"}}
                world_id = str(body.get("world_id") or "")
                if world_id == "world.perihelion-reach" or world_id.startswith("world.perihelion") or world_id == "world-01":
                    return 403, {"ok": False, "error": {"code": "WORLD_FORBIDDEN", "message": "not admitted"}}
                if not world_id.startswith("test.hosted-canonical."):
                    return 403, {"ok": False, "error": {"code": "WORLD_FORBIDDEN", "message": "not admitted"}}
            elif self.require_seal_on_command:
                seal = headers.get("X-Noema-Seal") or headers.get("x-noema-seal")
                if seal not in self.accepted_seals:
                    return 403, {"ok": False, "error": {"code": "SEAL_REQUIRED", "message": "seal required"}}
            idem = str(body.get("idempotency_key") or "")
            if idem in self.seen_idem:
                return 200, self.seen_idem[idem]
            command = str(body.get("command") or "").upper()
            rec = dict(body)
            rec["_path"] = path
            rec["_had_seal"] = bool(headers.get("X-Noema-Seal") or headers.get("x-noema-seal"))
            rec["_had_admin"] = bool(headers.get("X-Noema-Admin-Token") or headers.get("x-noema-admin-token"))
            self.commands.append(rec)
            if self.resync_remaining > 0:
                self.resync_remaining -= 1
                return 200, {
                    "ok": False,
                    "retryable": True,
                    "world_status": "ACTIVE",
                    "error": {
                        "code": "SETTLEMENT_RESYNC",
                        "message": "world head resynced after sequence drift; retry the command",
                    },
                }
            if self.world_status == "PAUSED" and command not in {"LOOK", "OBSERVE", "WAIT"}:
                return 409, {"ok": False, "error": {"code": "WORLD_PAUSED"}, "world_status": "PAUSED"}
            if self.world_status == "INCIDENT" and command not in {"LOOK", "OBSERVE"}:
                return 409, {"ok": False, "error": {"code": "WORLD_INCIDENT"}, "world_status": "INCIDENT"}
            if command == "ENTER_WORLD":
                self.in_world = True
            self.sequence += 1
            payload = {"ok": True, "observation": self.observation(), "settled": True, "world_status": self.world_status}
            if idem:
                self.seen_idem[idem] = payload
            return 200, payload
        return 404, {"error": {"code": "NOT_FOUND", "message": path}}

    def approve(self, device_code: str = "dev.fixture") -> None:
        rec = self.pending.pop(device_code, {"device_code": device_code})
        rec["status"] = "approved"
        self.approved[device_code] = rec


class _Handler(BaseHTTPRequestHandler):
    fake: FakeNoema

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _read(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode()) if raw else {}

    def _write(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        status, payload = self.fake.handle("GET", path, {}, dict(self.headers))
        self._write(status, payload)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        status, payload = self.fake.handle("POST", path, self._read(), dict(self.headers))
        self._write(status, payload)


def serve_fake(fake: FakeNoema) -> tuple[str, ThreadingHTTPServer, threading.Thread]:
    _Handler.fake = fake
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[:2]
    return f"http://{host}:{port}", httpd, thread
