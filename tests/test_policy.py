from noema_client.adapters.scripted import FirstValidAffordanceAdapter, ScriptedAdapter
from noema_client.policy import ClientPolicy
from noema_client.runner import CircuitBreaker
from noema_client.types import ActionProposal


def test_circuit_breaker_trips():
    br = CircuitBreaker(3)
    br.record_failure("x")
    br.record_failure("x")
    assert not br.tripped
    br.record_failure("x")
    assert br.tripped
    br.record_success()
    assert br.consecutive == 0


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
