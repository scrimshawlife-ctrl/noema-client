"""Official NoemaClient. Discover, connect, observe, act.

The model proposes. The client constrains and transports. NOEMA decides.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from noema_client.actions import validate_proposal
from noema_client.adapters.scripted import FirstValidAffordanceAdapter
from noema_client.auth import DeviceEnrollment, StaticTokenProvider
from noema_client.config import (
    DEFAULT_SERVER,
    StoredCredential,
    clear_credential,
    config_dir,
    load_credential,
    load_server,
    save_credential,
    save_server,
)
from noema_client.discovery import Discovery, discover
from noema_client.errors import FailureClass, NoemaAuthError, NoemaError, NoemaProtocolError, raise_for_failure
from noema_client.isolated import (
    ISOLATED_COMMAND_PATH,
    admit_isolated_world_id,
    is_isolated_world,
    require_isolated_admin_header,
)
from noema_client.observations import prepare_context, render_observation, to_observation
from noema_client.policy import ClientPolicy
from noema_client.protocol import WebSocketGateway, derive_ws_url
from noema_client.redaction import collect_secrets
from noema_client.runner import Runner
from noema_client.seal import command_headers, refused_play_flag, resolve_seal
from noema_client.session import Session
from noema_client.telemetry import Telemetry
from noema_client.transport import CommandTransport, HttpGateway, default_http
from noema_client.types import ActionProposal, CommandResult, Observation


class NoemaClient:
    def __init__(
        self,
        server: str | None = None,
        *,
        config_home: Path | None = None,
        http: Callable[..., dict[str, Any]] | None = None,
        transport: str = "auto",
        isolated: bool = False,
        world_id: str | None = None,
        admin_token: str | None = None,
        runtime: str = "noema-client",
        policy: ClientPolicy | None = None,
        ws_connect: Callable[..., Any] | None = None,
    ) -> None:
        self.config_home = Path(config_home) if config_home else config_dir()
        self.server = (server or load_server(self.config_home)).rstrip("/")
        self._http = http or default_http
        self.transport_pref = transport
        self.world_id = world_id or os.environ.get("NOEMA_WORLD_ID") or None
        cred = load_credential(self.config_home)
        if not self.world_id and cred and cred.world_id:
            self.world_id = cred.world_id
        self.isolated = bool(isolated or is_isolated_world(self.world_id))
        self._admin_token = admin_token or os.environ.get("NOEMA_ADMIN_TOKEN") or None
        self.runtime = runtime
        self.policy = policy or ClientPolicy()
        self._ws_connect = ws_connect
        self.telemetry = Telemetry()
        self.discovery: Discovery | None = None
        self.session = Session(server=self.server, transport="http")
        self._credential: StoredCredential | None = cred
        if self._credential:
            self.telemetry.remember_secret(self._credential.access_token)
            if self._credential.resume_token:
                self.telemetry.remember_secret(self._credential.resume_token)
        if self._admin_token:
            self.telemetry.remember_secret(self._admin_token)
        self._gateway: CommandTransport | None = None
        self.observation: Observation | None = None
        self.seal: str | None = None

    def __repr__(self) -> str:
        return f"NoemaClient(server={self.server!r}, connected={self.session.connected})"

    def _secrets(self) -> list[str]:
        cred = self._credential
        return collect_secrets(
            cred.access_token if cred else None,
            cred.resume_token if cred else None,
            self._admin_token,
        )

    def discover(self) -> Discovery:
        self.discovery = discover(self.server, self._http)
        live = self.server.rstrip("/") == DEFAULT_SERVER and not self.isolated
        self.seal = resolve_seal(
            self.discovery,
            live_default=live,
            isolated=self.isolated,
            world_id=self.world_id,
        )
        self.session.protocol = self.discovery.protocol
        self.telemetry.record(event="discover", protocol=self.discovery.protocol, transport="http")
        return self.discovery

    def connect(self, *, announce: Callable[[str], None] | None = None) -> StoredCredential:
        if refused_play_flag(self):
            raise NoemaError("SEAL", "live play flags are refused")
        if self.discovery is None:
            self.discover()
        cred = self._credential
        if cred and cred.access_token:
            self._bind_gateway(cred)
            self.session.connected = True
            return cred
        enrollment = DeviceEnrollment(self.server, runtime=self.runtime, http=self._http, announce=announce)
        meta = enrollment.start()
        enrollment.poll_until_ready()
        token = enrollment.reveal()
        self.telemetry.remember_secret(token)
        cred = StoredCredential(
            access_token=token,
            player_id=meta.get("player_id"),
            controller_id=meta.get("controller_id"),
            controller_type="agent",
            server=self.server,
            world_id=self.world_id,
            protocol=self.session.protocol,
            resume_token=None,
        )
        save_credential(cred, self.config_home)
        save_server(self.server, self.config_home)
        self._credential = cred
        self._bind_gateway(cred)
        self.session.connected = True
        self.session.player_id = cred.player_id
        self.session.controller_id = cred.controller_id
        self.telemetry.record(event="connect", player_id=cred.player_id, transport=self.session.transport)
        return cred

    def _http_gateway(self, cred: StoredCredential, command_path: str, world_id: str | None, admin_token: str | None) -> HttpGateway:
        return HttpGateway(
            self.server,
            StaticTokenProvider(cred.access_token),
            http=self._http,
            runtime=self.runtime,
            command_path=command_path,
            world_id=world_id if self.isolated else None,
            seal=self.seal,
            admin_token=admin_token,
        )

    def _persist_resume(self, cred: StoredCredential, resume_token: str | None) -> None:
        if not resume_token:
            return
        self.telemetry.remember_secret(resume_token)
        cred.resume_token = resume_token
        self.session.resume = "stored"
        save_credential(cred, self.config_home)

    def _bind_gateway(self, cred: StoredCredential) -> None:
        command_path = "/v1/command"
        world_id = self.world_id
        admin_token = None
        if self.isolated or is_isolated_world(world_id):
            self.isolated = True
            world_id = admit_isolated_world_id(world_id)
            self.world_id = world_id
            command_path = ISOLATED_COMMAND_PATH
            self.seal = None
            admin_token = require_isolated_admin_header(self._admin_token)
        elif self.discovery and self.discovery.command_uri:
            parsed = urlparse(self.discovery.command_uri)
            command_path = parsed.path or "/v1/command"
        chosen = self.transport_pref
        if self.isolated:
            if chosen == "websocket":
                raise NoemaError("WS_ISOLATED", "isolated worlds use HTTP /v1/operator/test-world/command")
            self.session.transport = "http"
            self._gateway = self._http_gateway(cred, command_path, world_id, admin_token)
            self.session.seal_sent = False
            self.session.resume = "none"
            return
        ws_ok = chosen in {"auto", "websocket"}
        advertised = "websocket" in (self.discovery.transports if self.discovery else ["websocket"])
        if ws_ok and (advertised or chosen == "websocket" or self._ws_connect is not None):
            ws = WebSocketGateway(
                derive_ws_url(self.discovery.websocket_uri if self.discovery else self.server),
                StaticTokenProvider(cred.access_token),
                seal=self.seal,
                resume_token=cred.resume_token,
                connect_factory=self._ws_connect,
            )
            if ws.available():
                try:
                    ws.connect_session()
                    self._gateway = ws
                    self.session.transport = "websocket"
                    self.session.resume = "stored" if ws.resume_token else "none"
                    self._persist_resume(cred, ws.resume_token)
                    self.telemetry.record(event="transport", transport="websocket", resumed=ws.resumed)
                    self.session.seal_sent = bool(self.seal)
                    if ws.player_id:
                        self.session.player_id = str(ws.player_id)
                    if ws.controller_id:
                        self.session.controller_id = str(ws.controller_id)
                    return
                except Exception:
                    if chosen == "websocket":
                        raise
                    self.telemetry.record(event="transport", transport="http", fallback="websocket_failed")
            elif chosen == "websocket":
                raise NoemaProtocolError("WS_UNAVAILABLE", "websockets package not installed", failure=FailureClass.PROTOCOL)
        self.session.transport = "http"
        self._gateway = self._http_gateway(cred, command_path, world_id, admin_token)
        self.session.seal_sent = bool(self.seal)
        self.session.resume = "stored" if cred.resume_token else "none"

    def _require_gateway(self) -> CommandTransport:
        if self._gateway is None:
            cred = self._credential or load_credential(self.config_home)
            if not cred:
                raise NoemaAuthError("AUTH_REQUIRED", "not connected")
            self._credential = cred
            if self.discovery is None:
                self.discover()
            self._bind_gateway(cred)
        assert self._gateway is not None
        return self._gateway

    def observe(self) -> Observation:
        result = self._require_gateway().send_command("OBSERVE", {})
        if not result.ok:
            err = result.error or {}
            raise_for_failure(result.failure, str(err.get("code") or "OBSERVE_FAILED"), str(err.get("message") or "observe failed"))
        self.observation = to_observation(result.observation, world_status=result.world_status)
        self.session.cycle = self.observation.cycle
        self.session.world = self.observation.world
        return self.observation

    def act(self, proposal: ActionProposal) -> CommandResult:
        obs = self.observation or to_observation({})
        validated = validate_proposal(proposal, obs, self.policy)
        result = self._require_gateway().send_command(validated.command, validated.arguments)
        if result.ok:
            self.observation = to_observation(
                result.observation,
                last_consequence=(result.observation or {}).get("consequence"),
                world_status=result.world_status,
            )
            self.session.cycle = self.observation.cycle
        self.telemetry.record(
            event="act",
            action=proposal.action,
            target=proposal.target_id,
            ok=result.ok,
            code=(result.error or {}).get("code") if result.error else None,
            latency_ms=None,
            protocol=self.session.protocol,
            transport=self.session.transport,
            client_version="0.1.3",
        )
        return result

    def play(self, *, max_actions: int | None = None, adapter: Any | None = None, enter: bool = True) -> list:
        gw = self._require_gateway()
        runner = Runner(gw, adapter or FirstValidAffordanceAdapter(), self.policy)
        turns = []
        if enter:
            turns.append(self.act(ActionProposal(action="ENTER_WORLD")))
        self.observe()
        runner.observation = self.observation
        bound = max_actions if max_actions is not None else self.policy.max_actions
        for _ in range(bound):
            turn = runner.turn()
            turns.append(turn)
            self.observation = runner.observation
            if turn.stopped or not turn.ok:
                break
        return turns

    def status(self) -> dict[str, Any]:
        cred = self._credential
        return {
            "server": self.server,
            "connected": self.session.connected or bool(cred),
            "protocol": self.session.protocol,
            "world": self.session.world,
            "world_id": self.world_id,
            "isolated": self.isolated,
            "player_id": (cred.player_id if cred else None) or self.session.player_id,
            "controller_id": (cred.controller_id if cred else None) or self.session.controller_id,
            "controller_type": "agent",
            "transport": self.session.transport,
            "seal": "sent" if self.session.seal_sent or self.seal else "none",
            "credential": "stored" if cred else "missing",
            "admin_header": "present" if self._admin_token else "missing",
            "resume": self.session.resume,
            "cycle": self.session.cycle,
        }

    def doctor(self) -> dict[str, Any]:
        report: dict[str, Any] = {
            "config_dir": str(self.config_home),
            "config_dir_mode": _mode(self.config_home),
            "credential": "present" if load_credential(self.config_home) else "missing",
            "server": self.server,
        }
        try:
            health = self._http("GET", f"{self.server}/health", None, None)
            report["reachability"] = "ok" if int(health.get("_http_status") or 200) < 400 else "fail"
        except Exception as exc:
            report["reachability"] = f"fail:{type(exc).__name__}"
        try:
            disc = self.discover()
            report["discovery"] = disc.protocol
            report["seal"] = "required" if self.seal else "not-required"
            report["isolated"] = self.isolated
            report["world_id"] = self.world_id
        except Exception as exc:
            report["discovery"] = f"fail:{type(exc).__name__}"
        return report

    def disconnect(self, *, forget: bool = False) -> None:
        self.session.connected = False
        gw = self._gateway
        self._gateway = None
        if gw is not None:
            try:
                gw.close()
            except Exception:
                pass
        if forget:
            clear_credential(self.config_home)
            self._credential = None
            self.session.resume = "none"
        self.telemetry.record(event="disconnect", forget=forget)

    def close(self) -> None:
        self.disconnect(forget=False)

    def model_context(self) -> dict[str, Any]:
        obs = self.observation or to_observation({})
        ctx = prepare_context(obs, [], self.policy)
        blob = str(ctx)
        for secret in self._secrets():
            assert secret not in blob
        return ctx


def _mode(path: Path) -> str:
    try:
        return oct(path.stat().st_mode & 0o777)
    except OSError:
        return "missing"
