from noema_client.adapters.scripted import FirstValidAffordanceAdapter, ScriptedAdapter
from noema_client.errors import FailureClass
from noema_client.policy import ClientPolicy
from noema_client.runner import CircuitBreaker, Runner
from noema_client.types import ActionProposal, CommandResult, Observation


def test_circuit_breaker_trips():
    br = CircuitBreaker(3)
    br.record_failure("x")
    br.record_failure("x")
    assert not br.tripped
    br.record_failure("x")
    assert br.tripped
    br.record_success()
    assert br.consecutive == 0
    br.trip("WORLD_INCIDENT")
    assert br.tripped
    br.reset()
    assert not br.tripped
    assert br.reason is None
    assert br.consecutive == 0


class _SeqGateway:
    def __init__(self, replies: list[CommandResult]) -> None:
        self.replies = list(replies)
        self.commands: list[str] = []

    def send_command(self, command: str, arguments=None, **kwargs) -> CommandResult:
        self.commands.append(command.upper())
        if not self.replies:
            raise AssertionError(f"unexpected command {command}")
        return self.replies.pop(0)

    def close(self) -> None:
        return None


def _result(*, ok: bool, command_status: str = "ACTIVE", failure: FailureClass | None = None, code: str | None = None) -> CommandResult:
    return CommandResult(
        ok=ok,
        observation={"world_status": command_status, "available_actions": ["LOOK", "WAIT"], "consequence": "ok"} if ok else None,
        error={"code": code} if code else None,
        settled=ok,
        http_status=200 if ok else 409,
        failure=failure,
        idempotency_key="k",
        request_id="r",
        world_status=command_status,
    )


def test_runner_resumes_when_world_is_active_again():
    gw = _SeqGateway(
        [
            _result(ok=False, command_status="INCIDENT", failure=FailureClass.WORLD_INCIDENT, code="WORLD_INCIDENT"),
            _result(ok=True, command_status="ACTIVE"),
            _result(ok=True, command_status="ACTIVE"),
        ]
    )
    runner = Runner(gw, ScriptedAdapter([ActionProposal(action="WAIT"), ActionProposal(action="WAIT")]))
    runner.observation = Observation(world_status="ACTIVE", available_actions=["WAIT"])
    first = runner.turn()
    assert first.ok is False
    assert first.stopped is False
    assert first.failure == FailureClass.WORLD_INCIDENT
    assert not runner.breaker.tripped
    second = runner.turn()
    assert second.ok is True
    assert gw.commands == ["WAIT", "LOOK", "WAIT"]


def test_runner_stays_stopped_while_world_is_incident():
    gw = _SeqGateway(
        [
            _result(ok=False, command_status="INCIDENT", failure=FailureClass.WORLD_INCIDENT, code="WORLD_INCIDENT"),
            _result(ok=True, command_status="INCIDENT"),
        ]
    )
    runner = Runner(gw, ScriptedAdapter([ActionProposal(action="WAIT")]))
    runner.observation = Observation(world_status="ACTIVE", available_actions=["WAIT"])
    first = runner.turn()
    assert first.stopped is True
    assert runner.breaker.tripped
    assert first.failure == FailureClass.WORLD_INCIDENT


def test_scripted_and_first_valid():
    scripted = ScriptedAdapter([ActionProposal(action="LOOK"), ActionProposal(action="WAIT")])
    assert scripted.decide({}).action == "LOOK"
    assert scripted.decide({}).action == "WAIT"
    assert scripted.decide({}) is None
    adapter = FirstValidAffordanceAdapter()
    quiet = adapter.decide({"canonical": {"entities": [], "affordances": [], "available_actions": ["WAIT"]}})
    assert quiet and quiet.action == "WAIT"
    work = adapter.decide(
        {
            "canonical": {
                "entities": [{"entity_id": "entity.relay", "repairable": True}],
                "affordances": [{"action": "REPAIR", "target_id": "entity.relay", "available": True}],
            },
            "system": {"permits": {"repair": True}},
        }
    )
    assert work and work.action == "REPAIR"


def test_first_valid_waits_when_harvest_stock_is_empty():
    adapter = FirstValidAffordanceAdapter()
    decision = adapter.decide(
        {
            "canonical": {
                "entities": [
                    {
                        "entity_id": "entity.storage-cell-cache",
                        "harvestable": False,
                        "stock_amount": 0,
                        "stock_resource": "energy",
                        "condition": 40,
                    }
                ],
                "affordances": [
                    {
                        "action": "HARVEST",
                        "operation": "HARVEST",
                        "available": False,
                        "reason": "Not enough stock available.",
                        "target_id": "entity.storage-cell-cache",
                    },
                    {"action": "MOVE", "available": True, "cmd": "move east"},
                    {"action": "WAIT", "available": True},
                ],
                "available_actions": ["MOVE", "WAIT"],
            }
        }
    )
    assert decision and decision.action == "WAIT"


def test_first_valid_repairs_when_harvest_is_blocked_by_full_hold():
    adapter = FirstValidAffordanceAdapter()
    decision = adapter.decide(
        {
            "canonical": {
                "resources": {"storage": 0},
                "affordances": [
                    {
                        "action": "HARVEST",
                        "available": False,
                        "reason": "You do not have enough free storage.",
                    },
                    {"action": "INSPECT", "available": True, "target_id": "entity.relay-7"},
                    {"action": "REPAIR", "available": True, "target_id": "entity.relay-7"},
                    {"action": "MOVE", "available": True, "cmd": "move east"},
                    {"action": "WAIT", "available": True},
                ],
            },
            "system": {"permits": {"repair": True}},
        }
    )
    assert decision and decision.action == "REPAIR"


def test_first_valid_moves_when_hold_is_full_and_no_repair():
    adapter = FirstValidAffordanceAdapter()
    decision = adapter.decide(
        {
            "canonical": {
                "resources": {"storage": 0},
                "affordances": [
                    {
                        "action": "HARVEST",
                        "available": False,
                        "reason": "You do not have enough free storage.",
                    },
                    {"action": "INSPECT", "available": True},
                    {"action": "MOVE", "available": True, "cmd": "move east"},
                    {"action": "WAIT", "available": True},
                ],
            }
        }
    )
    assert decision and decision.action == "MOVE"
    assert decision.arguments.get("direction") == "east"


def test_first_valid_repairs_before_waiting_on_empty_harvest():
    adapter = FirstValidAffordanceAdapter()
    decision = adapter.decide(
        {
            "canonical": {
                "entities": [{"entity_id": "entity.relay-7", "repairable": True, "condition": 40}],
                "affordances": [
                    {
                        "action": "HARVEST",
                        "operation": "HARVEST",
                        "available": False,
                        "reason": "Not enough stock available.",
                    },
                    {"action": "REPAIR", "available": True, "target_id": "entity.relay-7"},
                    {"action": "WAIT", "available": True},
                ],
            },
            "system": {"permits": {"repair": True}},
        }
    )
    assert decision and decision.action == "REPAIR"


def test_policy_denied_family():
    p = ClientPolicy(allow_contest=False, denied_actions=["TRADE"])
    assert p.permits("CONTEST_DECLARE") is False
    assert p.permits("TRADE") is False
    assert p.permits("LOOK") is True
