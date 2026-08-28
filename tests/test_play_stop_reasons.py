"""Defect 2: autonomous play stopped after exactly 3 or 6 turns with no reason.

The live 20-minute playtest saw a healthy authenticated session end after
exactly 3 or 6 turns while `cmd_play` printed only `play finished turns=N`.
These tests pin the mechanism and prove the repaired loop either makes
progress or stops with an explicit, correct reason.
"""

from __future__ import annotations

import pytest

from noema_client.adapters.scripted import FirstValidAffordanceAdapter
from noema_client.errors import FailureClass
from noema_client.policy import ClientPolicy
from noema_client.runner import Runner, proposal_fingerprint
from noema_client.types import ActionProposal, CommandResult, StopReason

BAD_HARVEST = {
    "action": "HARVEST",
    "verb": "COMMIT",
    "operation": "HARVEST",
    "label": "Harvest Salvage Cache",
    "cmd": "harvest salvage-cache 1",
    "target_id": "entity.salvage-cache",
    "target_label": "salvage-cache",
    "available": True,
}
GOOD_MOVE = {
    "action": "MOVE",
    "verb": "MOVE",
    "label": "Move east",
    "cmd": "move east",
    "target_id": "east",
    "direction": "east",
    "available": True,
}


def _observation() -> dict:
    return {
        "world_status": "ACTIVE",
        "available_actions": ["HARVEST", "MOVE", "LOOK", "WAIT"],
        "affordances": [BAD_HARVEST, GOOD_MOVE],
        "location": {
            "entities": [{"entity_id": "entity.salvage-cache", "label": "salvage-cache"}],
            "exits": [{"direction": "east", "to_room_id": "room.spoke"}],
        },
        "entities": [{"entity_id": "entity.salvage-cache", "label": "salvage-cache"}],
        "consequence": "ok",
    }


class HarvestAlwaysRejects:
    """The live shape: an advertised harvest the server always refuses."""

    def __init__(self) -> None:
        self.commands: list[tuple[str, dict]] = []

    def send_command(self, command: str, arguments=None, **kwargs) -> CommandResult:
        args = dict(arguments or {})
        self.commands.append((command.upper(), args))
        operation = str(args.get("operation") or "").upper()
        if operation == "HARVEST":
            return CommandResult(
                ok=False,
                observation=None,
                error={"code": "FORBIDDEN", "message": "Not enough stock available."},
                settled=False,
                http_status=403,
                failure=FailureClass.ACTION_REJECTED,
                idempotency_key="k",
                request_id="r",
                world_status="ACTIVE",
            )
        return CommandResult(
            ok=True,
            observation=_observation(),
            error=None,
            settled=True,
            http_status=200,
            failure=None,
            idempotency_key="k",
            request_id="r",
            world_status="ACTIVE",
        )

    def close(self) -> None:
        return None


def _runner(gateway) -> Runner:
    runner = Runner(gateway, FirstValidAffordanceAdapter(), ClientPolicy())
    runner.ingest(_observation(), world_status="ACTIVE")
    return runner


def test_one_bad_affordance_no_longer_collapses_the_session():
    """Defect 2 root cause: the adapter re-picked the identical failing action.

    HARVEST outranks MOVE, so before the fix every turn proposed the same
    rejected harvest and three consecutive failures tripped the breaker at
    turn 3. The runner must now move on to the next valid candidate.
    """
    gw = HarvestAlwaysRejects()
    runner = _runner(gw)

    first = runner.turn()
    assert first.ok is False
    assert first.proposal.arguments.get("operation") == "HARVEST"
    assert first.stopped is False

    # Every subsequent turn must stop choosing the known-bad harvest.
    for _ in range(6):
        turn = runner.turn()
        assert turn.ok is True, "a healthy alternative affordance was available"
        assert turn.proposal.action == "MOVE"
    assert runner.breaker.tripped is False


def test_avoidance_survives_an_unrelated_success():
    """A later success elsewhere must not resurrect a known-bad affordance.

    Clearing the avoid set on any success made the loop alternate
    harvest-fail / move-ok forever, burning half of every session.
    """
    gw = HarvestAlwaysRejects()
    runner = _runner(gw)
    runner.turn()
    fingerprint = "HARVEST|HARVEST|entity.salvage-cache"
    assert fingerprint in runner.avoid
    runner.turn()  # succeeds via MOVE
    assert fingerprint in runner.avoid


def test_recovered_affordance_becomes_eligible_again():
    """Avoidance is keyed to what the server advertises, not to the session.

    When the Worker stops advertising the harvest the same way — stock
    regenerated past the executable minimum — it must be retried.
    """
    gw = HarvestAlwaysRejects()
    runner = _runner(gw)
    runner.turn()
    fingerprint = "HARVEST|HARVEST|entity.salvage-cache"
    assert fingerprint in runner.avoid

    recovered = _observation()
    recovered["affordances"] = [
        {**BAD_HARVEST, "available": True, "reason": None, "stock_amount": 9},
        GOOD_MOVE,
    ]
    runner.ingest(recovered, world_status="ACTIVE")
    context = {
        "canonical": {
            "affordances": recovered["affordances"],
            "available_actions": recovered["available_actions"],
            "entities": recovered["entities"],
        },
        "system": {"permits": {}, "avoid": dict(runner.avoid)},
    }
    choice = FirstValidAffordanceAdapter().decide(context)
    assert choice is not None
    assert choice.arguments.get("operation") == "HARVEST"


def test_stale_affordance_is_refreshed_at_most_once():
    """A rejected affordance may simply be stale; refresh once, never loop."""
    gw = HarvestAlwaysRejects()
    runner = _runner(gw)
    runner.turn()
    looks = [c for c in gw.commands if c[0] == "LOOK"]
    assert len(looks) == 1, "exactly one bounded refresh after the rejection"
    runner.avoid.clear()  # force the same choice again
    runner.turn()
    looks = [c for c in gw.commands if c[0] == "LOOK"]
    assert len(looks) == 1, "the same fingerprint must not buy a second refresh"


class AlwaysRejects(HarvestAlwaysRejects):
    """A world where nothing at all succeeds, including the refresh LOOK."""

    def send_command(self, command: str, arguments=None, **kwargs) -> CommandResult:
        self.commands.append((command.upper(), dict(arguments or {})))
        return CommandResult(
            ok=False,
            observation=None,
            error={"code": "FORBIDDEN", "message": "no"},
            settled=False,
            http_status=403,
            failure=FailureClass.ACTION_REJECTED,
            idempotency_key="k",
            request_id="r",
            world_status="ACTIVE",
        )


def test_breaker_still_bounds_a_fully_hostile_world():
    """Avoidance must not defeat the circuit breaker."""
    gw = AlwaysRejects()
    runner = _runner(gw)
    stopped = False
    for _ in range(12):
        turn = runner.turn()
        if turn.stopped:
            stopped = True
            break
    assert stopped, "the breaker must still bound execution"
    assert runner.breaker.tripped is True


class AuthFails(HarvestAlwaysRejects):
    def send_command(self, command: str, arguments=None, **kwargs) -> CommandResult:
        self.commands.append((command.upper(), dict(arguments or {})))
        return CommandResult(
            ok=False,
            observation=None,
            error={"code": "AUTH_REQUIRED"},
            settled=False,
            http_status=401,
            failure=FailureClass.AUTH_REQUIRED,
            idempotency_key="k",
            request_id="r",
            world_status="ACTIVE",
        )


def test_auth_failure_is_never_treated_as_a_stale_affordance():
    gw = AuthFails()
    runner = _runner(gw)
    turn = runner.turn()
    assert turn.stopped is True
    assert runner.breaker.reason == "auth_failure"
    assert [c for c in gw.commands if c[0] == "LOOK"] == [], "auth failure must not trigger a refresh"


def test_fingerprint_distinguishes_targets_and_operations():
    harvest_a = ActionProposal(
        action="HARVEST", target_id="entity.a", arguments={"operation": "HARVEST"}
    )
    harvest_b = ActionProposal(
        action="HARVEST", target_id="entity.b", arguments={"operation": "HARVEST"}
    )
    assert proposal_fingerprint(harvest_a) != proposal_fingerprint(harvest_b)
    assert proposal_fingerprint(None) == ""


@pytest.mark.parametrize(
    ("failure", "code", "expected"),
    [
        (FailureClass.AUTH_REQUIRED, "AUTH_REQUIRED", StopReason.AUTH_FAILURE),
        (FailureClass.WORLD_PAUSED, "WORLD_PAUSED", StopReason.WORLD_PAUSED),
    ],
)
def test_stop_reasons_are_distinguished(failure, code, expected):
    from noema_client.client import _classify_stop
    from noema_client.types import TurnResult

    runner = _runner(HarvestAlwaysRejects())
    turn = TurnResult(ok=False, stopped=True, reason=code, failure=failure)
    reason, _detail = _classify_stop(turn, runner)
    assert reason == expected


class HarvestDepletes(HarvestAlwaysRejects):
    """Stock lasts three harvests, then the node is permanently refused.

    This is the live 6-turn shape: three successful harvests reset the
    consecutive-failure counter, then three refusals trip the breaker at
    turn six with nothing printed but `play finished turns=6`.
    """

    def __init__(self, allowed: int = 3) -> None:
        super().__init__()
        self.allowed = allowed

    def send_command(self, command: str, arguments=None, **kwargs) -> CommandResult:
        args = dict(arguments or {})
        if str(args.get("operation") or "").upper() == "HARVEST" and self.allowed > 0:
            self.allowed -= 1
            self.commands.append((command.upper(), args))
            return CommandResult(
                ok=True,
                observation=_observation(),
                error=None,
                settled=True,
                http_status=200,
                failure=None,
                idempotency_key="k",
                request_id="r",
                world_status="ACTIVE",
            )
        return super().send_command(command, arguments, **kwargs)


def test_depleting_node_no_longer_ends_the_session_at_turn_six():
    gw = HarvestDepletes()
    runner = _runner(gw)
    turns = [runner.turn() for _ in range(8)]
    assert [t.ok for t in turns[:3]] == [True, True, True], "stock lasts three harvests"
    assert turns[3].ok is False, "the fourth harvest is refused"
    # Before the fix, turns 5 and 6 repeated the same refused harvest and the
    # breaker tripped at turn 6. The loop must now move on instead.
    assert all(t.ok for t in turns[4:]), "the session continues on another affordance"
    assert not any(t.stopped for t in turns)
    assert runner.breaker.tripped is False
