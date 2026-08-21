"""Prabu E2E: WAIT spam, silent policy blocks, NOT_IN_WORLD swallowed by cmd_act."""

from __future__ import annotations

from noema_client.actions import validate_proposal
from noema_client.adapters.scripted import FirstValidAffordanceAdapter
from noema_client.aliases import proposal_from_line
from noema_client.errors import NoemaActionRejected
from noema_client.observations import prepare_context, to_observation
from noema_client.policy import ClientPolicy
from noema_client.types import ActionProposal


def _civic_context(*, first_is_wait: bool = True, policy: ClientPolicy | None = None) -> dict:
    affs = []
    if first_is_wait:
        affs.append({"action": "WAIT", "available": True, "kind": "utility"})
    affs.extend(
        [
            {"action": "INSPECT", "available": True, "target_id": "entity.relay-7", "kind": "utility"},
            {"action": "MOVE", "available": True, "target_id": "east", "cmd": "move east", "kind": "move"},
            {"action": "ORG_CREATE", "available": True, "kind": "org"},
        ]
    )
    obs = to_observation(
        {
            "world_name": "Perihelion Reach",
            "cycle": 93,
            "player_id": "player.devicedda6be5c9f55",
            "location": {"name": "Civic Exchange", "room_id": "room.civic-exchange"},
            "available_actions": ["WAIT", "INSPECT", "MOVE", "ORG_CREATE"],
            "affordances": affs,
            "entities": [{"entity_id": "entity.relay-7", "label": "relay", "condition": 85}],
            "budgets": {"attention": 8, "energy": 10, "compute": 8},
        }
    )
    pol = policy or ClientPolicy()
    return prepare_context(obs, [], pol)


def test_prabu_default_play_does_not_spam_wait_when_inspect_or_move_exist():
    """Baseline bug: first-listed WAIT + quiet/empty-stock Civic Exchange → 15× WAIT."""
    ctx = _civic_context()
    chosen = FirstValidAffordanceAdapter().decide(ctx)
    assert chosen is not None
    assert chosen.action != "WAIT"
    assert chosen.action in {"INSPECT", "MOVE"}


def test_adapter_skips_policy_denied_org_create():
    pol = ClientPolicy(allow_org_create=False)
    ctx = _civic_context(first_is_wait=False, policy=pol)
    # only ORG_CREATE besides MOVE/INSPECT
    chosen = FirstValidAffordanceAdapter().decide(ctx)
    assert chosen is not None
    assert chosen.action != "ORG_CREATE"


def test_policy_blocked_advertised_lists_org_when_gated():
    pol = ClientPolicy(allow_org_create=False, allow_contest=False)
    obs = to_observation(
        {
            "affordances": [
                {"action": "ORG_CREATE", "available": True},
                {"action": "CONTEST_DECLARE", "available": True},
                {"action": "WAIT", "available": True},
            ]
        }
    )
    blocked = pol.blocked_advertised(obs)
    assert "ORG_CREATE" in blocked
    assert "CONTEST_DECLARE" in blocked
    assert "WAIT" not in blocked


def test_default_policy_permits_org_create():
    pol = ClientPolicy()
    assert pol.permits("ORG_CREATE")
    assert pol.permits("CONTEST_DECLARE")
    assert pol.permits("AGREEMENT_FORM")


def test_trade_proposal_from_line_sets_required_keys():
    p = proposal_from_line("trade player.reach-maint3 energy=1 compute=1")
    assert p is not None
    assert p.action == "TRADE"
    assert p.arguments.get("counterparty_id") == "player.reach-maint3"
    assert p.arguments.get("phase") == "propose"
    assert p.arguments.get("offered") == {"energy": 1}
    assert p.arguments.get("requested") == {"compute": 1}


def test_validate_org_create_passes_default_policy():
    obs = to_observation(
        {
            "available_actions": ["ORG_CREATE"],
            "affordances": [{"action": "ORG_CREATE", "available": True}],
        }
    )
    validate_proposal(ActionProposal(action="ORG_CREATE", arguments={"name": "X", "charter": "Y"}), obs, ClientPolicy())
