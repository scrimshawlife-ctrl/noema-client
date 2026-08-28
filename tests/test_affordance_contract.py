"""Defect 4: advertised friendly commands failed local validation.

The Worker advertised `harvest salvage-cache 1`, but `noema do "harvest
salvage-cache"` was rejected locally as `INVALID_PROPOSAL: target not visible`
because COMMIT/BUILD checked the raw label against visible entity *ids*. Only
INSPECT resolved the label first. The friendly parser also dropped the amount.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from noema_client.actions import resolve_visible_entity, validate_proposal
from noema_client.aliases import proposal_from_line
from noema_client.errors import NoemaActionRejected
from noema_client.policy import ClientPolicy
from noema_client.types import Affordance, Observation

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "worker_affordance_cmds.json").read_text()
)


def _observation() -> Observation:
    entities = [
        {"entity_id": "entity.salvage-cache", "label": "salvage-cache",
         "stock_resource": "materials", "stock_amount": 8},
        {"entity_id": "entity.relay-7", "label": "relay-7", "condition": 60},
    ]
    return Observation(
        entities=entities,
        location={"entities": entities, "exits": [{"direction": "east", "to_room_id": "room.spoke"}]},
        available_actions=[
            "INSPECT", "HARVEST", "REPAIR", "MOVE",
            "DISMANTLE", "UPGRADE", "REPURPOSE", "RESTORE",
        ],
        affordances=[
            Affordance(action="HARVEST", target_id="entity.salvage-cache",
                       cmd="harvest salvage-cache 1",
                       raw={"operation": "HARVEST", "target_label": "salvage-cache",
                            "target_id": "entity.salvage-cache"}),
            Affordance(action="REPAIR", target_id="entity.relay-7", cmd="repair relay-7",
                       raw={"operation": "REPAIR", "target_label": "relay-7",
                            "target_id": "entity.relay-7"}),
        ],
    )


@pytest.mark.parametrize("case", FIXTURE["parsed"], ids=lambda c: c["template"])
def test_worker_command_round_trips_through_the_client(case):
    """Every executable cmd the client parses must reach the same canonical action."""
    proposal = proposal_from_line(case["sample"])
    assert proposal is not None, f"client cannot parse {case['sample']!r}"
    validated = validate_proposal(proposal, _observation(), ClientPolicy())
    assert validated.command == case["command"]
    for key in ("operation", "entity_id", "direction", "amount", "extent"):
        if key in case:
            assert validated.arguments.get(key) == case[key], key


def test_structured_only_commands_are_declared_not_forgotten():
    """The split must stay exhaustive against the Worker's emitted set.

    If the Worker gains a new affordance cmd, regenerate the fixture; an
    entity-label command that silently lands in structured_only is a gap.
    """
    parsed = {c["template"] for c in FIXTURE["parsed"]}
    structured = set(FIXTURE["structured_only"])
    assert not (parsed & structured), "a template cannot be both parsed and structured-only"
    assert len(parsed) + len(structured) == 42


def test_the_exact_live_failure_now_validates():
    """`harvest salvage-cache` — the command that failed in production."""
    proposal = proposal_from_line("harvest salvage-cache")
    validated = validate_proposal(proposal, _observation(), ClientPolicy())
    assert validated.command == "COMMIT"
    assert validated.arguments["operation"] == "HARVEST"
    assert validated.arguments["entity_id"] == "entity.salvage-cache"


def test_advertised_amount_is_preserved():
    proposal = proposal_from_line("harvest salvage-cache 3")
    assert proposal.arguments["amount"] == 3
    validated = validate_proposal(proposal, _observation(), ClientPolicy())
    assert validated.arguments["amount"] == 3


def test_internal_id_still_accepted():
    validated = validate_proposal(
        proposal_from_line("harvest entity.salvage-cache"), _observation(), ClientPolicy()
    )
    assert validated.arguments["entity_id"] == "entity.salvage-cache"


def test_multi_word_label_matches_the_worker_text_adapter():
    obs = Observation(
        entities=[{"entity_id": "entity.storage-cell", "label": "storage cell cache"}],
        available_actions=["HARVEST"],
    )
    validated = validate_proposal(
        proposal_from_line("harvest storage cell cache 2"), obs, ClientPolicy()
    )
    assert validated.arguments["entity_id"] == "entity.storage-cell"
    assert validated.arguments["amount"] == 2


def test_separator_insensitive_label():
    obs = _observation()
    assert resolve_visible_entity(obs, "salvage cache").entity_id == "entity.salvage-cache"
    assert resolve_visible_entity(obs, "SALVAGE-CACHE").entity_id == "entity.salvage-cache"


def test_ambiguous_label_is_an_explicit_error_not_a_guess():
    obs = Observation(
        entities=[
            {"entity_id": "entity.a", "label": "cache"},
            {"entity_id": "entity.b", "label": "cache"},
        ],
        available_actions=["HARVEST"],
    )
    resolved = resolve_visible_entity(obs, "cache")
    assert resolved.ok is False
    assert resolved.code == "AMBIGUOUS_TARGET"
    assert resolved.choices == ("entity.a", "entity.b")
    with pytest.raises(NoemaActionRejected) as exc:
        validate_proposal(proposal_from_line("harvest cache"), obs, ClientPolicy())
    assert exc.value.code == "AMBIGUOUS_TARGET"


def test_invisible_label_stays_rejected():
    """Fail-closed: usability must not invent a target."""
    with pytest.raises(NoemaActionRejected) as exc:
        validate_proposal(
            proposal_from_line("harvest ghost-node"), _observation(), ClientPolicy()
        )
    assert exc.value.code == "INVALID_PROPOSAL"
    assert "not visible" in exc.value.message


def test_hallucinated_internal_id_stays_rejected():
    with pytest.raises(NoemaActionRejected):
        validate_proposal(
            proposal_from_line("harvest entity.does-not-exist"),
            _observation(),
            ClientPolicy(),
        )


def test_non_entity_commit_targets_are_untouched():
    """Office/player targets must not be run through the entity resolver."""
    from noema_client.types import ActionProposal

    obs = Observation(available_actions=["ORG_OFFICE_ASSIGN"])
    validated = validate_proposal(
        ActionProposal(
            action="ORG_OFFICE_ASSIGN",
            arguments={"operation": "ORG_OFFICE_ASSIGN", "office_id": "office.gate",
                       "agent_id": "player.tester"},
        ),
        obs,
        ClientPolicy(),
    )
    assert validated.arguments["office_id"] == "office.gate"


def test_line_argument_is_never_forwarded():
    """Hosted transport strips arguments.line; the client must not rely on it."""
    from noema_client.types import ActionProposal

    validated = validate_proposal(
        ActionProposal(action="INSPECT", arguments={"entity_id": "salvage-cache", "line": "inspect x"}),
        _observation(),
        ClientPolicy(),
    )
    assert "line" not in validated.arguments
