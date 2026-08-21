from noema_client.affordances import parse_affordances
from noema_client.observations import prepare_context, render_observation, to_observation
from noema_client.policy import ClientPolicy


def test_to_observation_forwards_semantic_and_deep_time_fields():
    obs = to_observation(
        {
            "world_name": "Perihelion Reach",
            "cycle": 91,
            "sequence": 265,
            "player_id": "player.tester",
            "location": {"name": "Civic Exchange"},
            "signaling_quality": 1,
            "protocol_strength": 2,
            "cascading_risk": 0,
            "reputation_summary": {"self_image": 0, "self_second_order": 0},
            "active_norms": {"org_create_influence": 5, "harvest_pressure": 3},
            "scars": [{"scar_id": "scar.econ.room.hub", "domain": "economic", "strength": 0.4}],
            "historical_context": {"fragments": 3, "reconstruction_confidence": 0.4},
            "path_dependence_index": 0.2,
            "lore_attractors": [{"label": "scarred ground", "basin": "forming"}],
            "affordances": [
                {"action": "HARVEST", "operation": "HARVEST", "available": True, "hint": "compact grounded signal preferred"}
            ],
        }
    )
    assert obs.protocol_strength == 2
    assert obs.reputation_summary["self_image"] == 0
    assert obs.scars[0]["domain"] == "economic"
    assert obs.lore_attractors[0]["basin"] == "forming"
    assert obs.affordances[0].hint == "compact grounded signal preferred"
    ctx = prepare_context(obs, [], ClientPolicy())
    assert ctx["canonical"]["scars"][0]["scar_id"] == "scar.econ.room.hub"
    text = render_observation(obs)
    assert "Scars: 1" in text
    assert "Protocol: 2" in text
    assert "Hints: compact grounded signal preferred" in text


def test_parse_affordances_keeps_hint_off_arguments():
    rows = parse_affordances(
        [{"action": "TRADE_ACCEPT", "verb": "TRADE", "available": True, "hint": "standing is weak", "target_id": "trade.1"}]
    )
    assert rows[0].hint == "standing is weak"
    assert rows[0].raw["hint"] == "standing is weak"
