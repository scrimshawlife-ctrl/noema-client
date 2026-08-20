from noema_client.actions import validate_proposal
from noema_client.affordances import arguments_from_affordance, parse_affordances, proposal_from_affordance
from noema_client.adapters.scripted import FirstValidAffordanceAdapter
from noema_client.policy import ClientPolicy
from noema_client.types import ActionProposal, Observation


def _obs(*rows: dict) -> Observation:
    return Observation(
        available_actions=[str(r.get("operation") or r.get("action")) for r in rows],
        affordances=parse_affordances(list(rows)),
        entities=[{"entity_id": "entity.relay-7"}],
        location={"exits": [{"direction": "east", "to_room_id": "room.east"}]},
    )


def test_arguments_from_affordance_drop_line_and_unavailable_reason():
    args = arguments_from_affordance(
        {
            "operation": "CONSTRUCT",
            "class": "workshop",
            "line": "construct workshop",
            "reason": "You do not have enough resources to construct.",
        }
    )
    assert args["operation"] == "CONSTRUCT"
    assert args["class"] == "workshop"
    assert "line" not in args
    assert "reason" not in args


def test_validate_build_construct_from_look_fields():
    obs = _obs({"action": "BUILD", "operation": "CONSTRUCT", "class": "workshop", "available": True})
    validated = validate_proposal(
        proposal_from_affordance(obs.affordances[0].raw),
        obs,
        ClientPolicy(),
    )
    assert validated.command == "BUILD"
    assert validated.arguments["operation"] == "CONSTRUCT"
    assert validated.arguments["class"] == "workshop"
    assert "line" not in validated.arguments


def test_validate_repair_overhaul_extent():
    row = {
        "action": "REPAIR",
        "operation": "REPAIR",
        "target_id": "entity.relay-7",
        "extent": "overhaul",
        "available": True,
    }
    obs = _obs(row)
    validated = validate_proposal(proposal_from_affordance(row), obs, ClientPolicy())
    assert validated.command == "COMMIT"
    assert validated.arguments["operation"] == "REPAIR"
    assert validated.arguments["extent"] == "overhaul"
    assert validated.arguments["entity_id"] == "entity.relay-7"


def test_validate_focus_track_and_vest_org():
    focus = {"action": "FOCUS", "operation": "FOCUS", "track": "engineer", "available": True}
    vest = {
        "action": "BUILD",
        "operation": "VEST",
        "target_id": "entity.workshop-1",
        "org_id": "org.line",
        "available": True,
    }
    focus_v = validate_proposal(proposal_from_affordance(focus), _obs(focus), ClientPolicy())
    assert focus_v.command == "COMMIT"
    assert focus_v.arguments["operation"] == "FOCUS"
    assert focus_v.arguments["track"] == "engineer"
    vest_v = validate_proposal(proposal_from_affordance(vest), _obs(vest), ClientPolicy())
    assert vest_v.command == "BUILD"
    assert vest_v.arguments["operation"] == "VEST"
    assert vest_v.arguments["org_id"] == "org.line"


def test_validate_contest_agreement_access_reconstruct():
    contest = {
        "action": "CONTEST_DECLARE",
        "operation": "CONTEST_DECLARE",
        "contest_form": "INFRASTRUCTURE_DISRUPTION",
        "target": {"kind": "ENTITY", "entity_id": "entity.relay-7"},
        "stake": {"energy": 10, "influence": 6, "compute": 2},
        "available": True,
    }
    access = {
        "action": "ACCESS_POLICY",
        "operation": "ACCESS_POLICY",
        "scope": "EXIT",
        "mode": "DENY",
        "applies_to": "*",
        "direction": "east",
        "acting_for": "org.line",
        "available": True,
    }
    recon = {
        "action": "RECONSTRUCT",
        "operation": "RECONSTRUCT",
        "subject_ref": "entity.relay-7",
        "claim": "Recorded from accessible evidence.",
        "evidence": ["LIVE_INSPECT"],
        "visibility": "PRIVATE",
        "available": True,
    }
    policy = ClientPolicy(allow_contest=True, allow_access=True)
    c = validate_proposal(proposal_from_affordance(contest), _obs(contest), policy)
    assert c.command == "COMMIT"
    assert c.arguments["contest_form"] == "INFRASTRUCTURE_DISRUPTION"
    assert c.arguments["stake"]["energy"] == 10
    a = validate_proposal(proposal_from_affordance(access), _obs(access), policy)
    assert a.command == "COMMIT"
    assert a.arguments["direction"] == "east"
    r = validate_proposal(proposal_from_affordance(recon), _obs(recon), ClientPolicy())
    assert r.command == "COMMIT"
    assert r.arguments["subject_ref"] == "entity.relay-7"
    assert r.arguments["visibility"] == "PRIVATE"


def test_strips_line_even_if_model_sends_it():
    obs = _obs({"action": "BUILD", "operation": "CONSTRUCT", "class": "workshop", "available": True})
    validated = validate_proposal(
        ActionProposal(action="CONSTRUCT", arguments={"class": "workshop", "line": "construct workshop"}),
        obs,
        ClientPolicy(),
    )
    assert "line" not in validated.arguments
    assert validated.command == "BUILD"


def test_first_valid_copies_construct_class():
    adapter = FirstValidAffordanceAdapter()
    decision = adapter.decide(
        {
            "canonical": {
                "entities": [{"entity_id": "entity.relay-7", "repairable": False, "condition": 40}],
                "affordances": [
                    {
                        "action": "BUILD",
                        "operation": "CONSTRUCT",
                        "class": "workshop",
                        "available": True,
                    }
                ],
            }
        }
    )
    assert decision and decision.action == "CONSTRUCT"
    assert decision.arguments.get("class") == "workshop"
    assert decision.arguments.get("operation") == "CONSTRUCT"
