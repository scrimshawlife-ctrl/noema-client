"""Official NoemaClient. Discover, connect, observe, act.

The model proposes. The client constrains and transports. NOEMA decides.
"""

from __future__ import annotations

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
from noema_client.errors import FailureClass, NoemaAuthError, NoemaError, raise_for_failure
from noema_client.observations import prepare_context, render_observation, to_observation
from noema_client.policy import ClientPolicy
from noema_client.protocol import WebSocketGateway, derive_ws_url
from noema_client.redaction import collect_secrets
from noema_client.runner import Runner
from noema_client.seal import command_headers, refused_play_flag, resolve_seal
from noema_client.session import Session
from noema_client.telemetry import Telemetry
from noema_client.transport import HttpGateway, default_http
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
        runtime: str = "noema-client",
        policy: ClientPolicy | None = None,
    ) -> None:
        self.config_home = Path(config_home) if config_home else config_dir()
        self.server = (server or load_server(self.config_home)).rstrip("/")
        self._http = http or default_http
        self.transport_pref = transport
        self.isolated = isolated
        self.runtime = runtime
        self.policy = policy or ClientPolicy()
        self.telemetry = Telemetry()
        self.discovery: Discovery | None = None
        self.session = Session(server=self.server, transport="http")
        self._credential: StoredCredential | None = load_credential(self.config_home)
        if self._credential:
            self.telemetry.remember_secret(self._credential.access_token)
        self._gateway: HttpGateway | None = None
        self.observation: Observation | None = None
        self.seal: str | None = None

    def __repr__(self) -> str:
        return f"NoemaClient(server={self.server!r}, connected={self.session.connected})"

    def _secrets(self) -> list[str]:
        cred = self._credential
        return collect_secrets(cred.access_token if cred else None)

    def discover(self) -> Discovery:
        self.discovery = discover(self.server, self._http)
        live = self.server.rstrip("/") == DEFAULT_SERVER and not self.isolated
        self.seal = resolve_seal(self.discovery, live_default=live, isolated=self.isolated)
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
            protocol=self.session.protocol,
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

    def _bind_gateway(self, cred: StoredCredential) -> None:
        command_path = "/v1/command"
        if self.discovery and self.discovery.command_uri:
            parsed = urlparse(self.discovery.command_uri)
            command_path = parsed.path or "/v1/command"
        chosen = self.transport_pref
        if chosen == "auto":
            ws = WebSocketGateway(
                derive_ws_url(self.discovery.websocket_uri if self.discovery else self.server),
                StaticTokenProvider(cred.access_token),
                seal=self.seal,
            )
            if ws.available() and "websocket" in (self.discovery.transports if self.discovery else ["websocket"]):
                try:
                    ws.connect_session()
                    self.session.transport = "websocket"
                    self.telemetry.record(event="transport", transport="websocket")
                except Exception:
                    self.session.transport = "http"
                    self.telemetry.record(event="transport", transport="http", fallback="websocket_failed")
            else:
                self.session.transport = "http"
                self.telemetry.record(event="transport", transport="http", fallback="ws_unavailable")
        elif chosen == "websocket":
            self.session.transport = "websocket"
        else:
            self.session.transport = "http"
        self._gateway = HttpGateway(
            self.server,
            StaticTokenProvider(cred.access_token),
            http=self._http,
            runtime=self.runtime,
            command_path=command_path,
            seal=self.seal,
        )
        self.session.seal_sent = bool(self.seal)

    def _require_gateway(self) -> HttpGateway:
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
            client_version="0.1.0",
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
            "player_id": (cred.player_id if cred else None) or self.session.player_id,
            "controller_id": (cred.controller_id if cred else None) or self.session.controller_id,
            "controller_type": "agent",
            "transport": self.session.transport,
            "seal": "sent" if self.session.seal_sent or self.seal else "none",
            "credential": "stored" if cred else "missing",
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
        except Exception as exc:
            report["discovery"] = f"fail:{type(exc).__name__}"
        return report

    def disconnect(self, *, forget: bool = False) -> None:
        self.session.connected = False
        self._gateway = None
        if forget:
            clear_credential(self.config_home)
            self._credential = None
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
