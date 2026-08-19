"""In-process Agent Protocol v1 socket. Not Perihelion."""

from __future__ import annotations

import json
from typing import Any


class FakeSocket:
    def __init__(self, server: "FakeWsServer") -> None:
        self.server = server
        self.closed = False
        self._inbox: list[str] = []

    def send(self, raw: str | bytes) -> None:
        if self.closed:
            raise ConnectionError("closed")
        text = raw.decode() if isinstance(raw, bytes) else raw
        reply = self.server.handle(json.loads(text), self)
        if reply is not None:
            self._inbox.append(json.dumps(reply))

    def recv(self) -> str:
        if self.closed:
            raise ConnectionError("closed")
        if not self._inbox:
            raise TimeoutError("no websocket frame")
        return self._inbox.pop(0)

    def close(self) -> None:
        self.closed = True
        self.server.closed += 1


class FakeWsServer:
    def __init__(self) -> None:
        self.authed = False
        self.resume_tokens: dict[str, dict[str, Any]] = {}
        self.frames: list[dict[str, Any]] = []
        self.connections = 0
        self.closed = 0
        self.drop_after: int | None = None
        self._dropped = False
        self.commands = 0
        self.cycle = 4
        self.sequence = 10
        self.in_world = False
        self.world_status = "ACTIVE"
        self.accepted_seal = "sha256:9b9c211c156a9b49e700fa39e409733099a38df9d95c7f6fb90ca3e9e740a395"
        self.require_seal = True
        self.next_resume = "resume.fixture.1"

    def connect(self, _url: str) -> FakeSocket:
        self.connections += 1
        self.authed = False
        return FakeSocket(self)

    def _observation(self) -> dict[str, Any]:
        return {
            "world_name": "fixture",
            "cycle": self.cycle,
            "sequence": self.sequence,
            "player_id": "player.fixture",
            "world_status": self.world_status,
            "location": {
                "room_id": "room.anchor",
                "name": "Grid Anchor",
                "exits": [{"direction": "east", "to_room_id": "room.east"}],
                "entities": [],
            },
            "available_actions": ["LOOK", "WAIT", "OBSERVE", "MOVE", "ENTER_WORLD"],
            "affordances": [{"action": "LOOK", "available": True}, {"action": "WAIT", "available": True}],
            "in_world": self.in_world,
        }

    def handle(self, msg: dict[str, Any], sock: FakeSocket) -> dict[str, Any] | None:
        self.frames.append(msg)
        typ = str(msg.get("type") or "").upper()
        rid = msg.get("request_id")
        body = msg.get("body") if isinstance(msg.get("body"), dict) else {}
        if typ == "HELLO":
            resume = str(body.get("resume_token") or "")
            extra: dict[str, Any] = {}
            if resume and resume in self.resume_tokens:
                self.authed = True
                extra["resume_offered"] = True
                extra["resumed"] = True
            return {
                "protocol": "agent-protocol/v1",
                "type": "HELLO_ACK",
                "request_id": rid,
                "body": {
                    "selected_protocol": "agent-protocol/v1",
                    "auth_methods": ["controller-token"],
                    "transports": ["websocket", "http"],
                    **extra,
                },
            }
        if typ == "AUTH":
            token = str(body.get("access_token") or "")
            if not token:
                return {"protocol": "agent-protocol/v1", "type": "ERROR", "request_id": rid, "error": {"code": "NOT_AUTHORIZED", "message": "access_token required"}, "_status": 401}
            if self.require_seal and body.get("prompt_version_hash") != self.accepted_seal:
                return {"protocol": "agent-protocol/v1", "type": "ERROR", "request_id": rid, "error": {"code": "SEAL_REQUIRED", "message": "seal required"}, "_status": 401}
            self.authed = True
            resume = self.next_resume
            self.resume_tokens[resume] = {"player_id": "player.fixture"}
            return {
                "protocol": "agent-protocol/v1",
                "type": "AUTH_ACK",
                "request_id": rid,
                "body": {
                    "session_id": "sess.fixture",
                    "player_id": "player.fixture",
                    "controller_id": "ctrl.fixture",
                    "resume_token": resume,
                },
            }
        if typ == "PING":
            return {"protocol": "agent-protocol/v1", "type": "PONG", "request_id": rid, "body": {}}
        if typ == "DISCONNECT":
            return {"protocol": "agent-protocol/v1", "type": "DISCONNECT_ACK", "request_id": rid, "body": {"ok": True}}
        if not self.authed:
            return {"protocol": "agent-protocol/v1", "type": "ERROR", "request_id": rid, "error": {"code": "NOT_AUTHORIZED", "message": "AUTH required"}, "_status": 401}
        action = body.get("action") if isinstance(body.get("action"), dict) else {}
        verb = str(action.get("verb") or body.get("command") or typ).upper()
        if verb == "ACT":
            verb = "LOOK"
        self.commands += 1
        if self.drop_after is not None and not self._dropped and self.commands > self.drop_after:
            self._dropped = True
            sock.closed = True
            raise ConnectionError("dropped")
        if verb == "ENTER_WORLD":
            self.in_world = True
        if verb == "WAIT":
            self.cycle += 1
            self.sequence += 1
        payload = {
            "ok": True,
            "observation": self._observation(),
            "settled": True,
            "world_status": self.world_status,
        }
        return {
            "protocol": "agent-protocol/v1",
            "type": "OBSERVE" if verb == "OBSERVE" else "ACT_RESULT",
            "request_id": rid,
            "body": payload,
        }
