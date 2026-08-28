"""Defect 1: `play --duration` and `--cooldown` were parsed and then ignored.

`cmd_play` called `client.play(max_actions=..., enter=...)` only, so the live
20-minute session needed an external shell timer and the default eight-action
bound silently won.
"""

from __future__ import annotations

import pytest

from noema_client import client as client_mod
from noema_client.adapters.scripted import ScriptedAdapter
from noema_client.client import NoemaClient, PlayBoundsError, validate_play_bounds
from noema_client.types import ActionProposal, CommandResult, StopReason


class OkGateway:
    def __init__(self) -> None:
        self.commands: list[str] = []

    def send_command(self, command: str, arguments=None, **kwargs) -> CommandResult:
        self.commands.append(command.upper())
        return CommandResult(
            ok=True,
            observation={
                "world_status": "ACTIVE",
                "available_actions": ["LOOK", "WAIT"],
                "affordances": [],
                "consequence": "ok",
            },
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


class Clock:
    """Monotonic stand-in. Only advances when the loop sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _client(tmp_path) -> NoemaClient:
    c = NoemaClient(server="https://example.invalid", config_home=tmp_path, transport="http")
    c._gateway = OkGateway()
    return c


def _waits(n: int) -> ScriptedAdapter:
    return ScriptedAdapter([ActionProposal(action="WAIT") for _ in range(n)])


def test_default_bound_is_eight_actions(tmp_path):
    report = _client(tmp_path).play(adapter=_waits(50), enter=False)
    assert report.attempted == 8
    assert report.stop_reason == StopReason.ACTION_BOUND


def test_max_actions_only(tmp_path):
    report = _client(tmp_path).play(max_actions=3, adapter=_waits(50), enter=False)
    assert report.attempted == 3
    assert report.stop_reason == StopReason.ACTION_BOUND


def test_duration_alone_is_not_capped_by_the_default_eight(tmp_path, monkeypatch):
    """The regression that forced an external timer in the live playtest."""
    clock = Clock()
    monkeypatch.setattr(client_mod.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(client_mod.time, "sleep", clock.sleep)
    report = _client(tmp_path).play(
        duration=100, cooldown=1, adapter=_waits(500), enter=False
    )
    assert report.attempted > 8, "the default action bound must not end a timed session"
    assert report.stop_reason == StopReason.DURATION_ELAPSED
    assert report.elapsed_seconds >= 100


def test_first_limit_reached_wins_actions(tmp_path, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(client_mod.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(client_mod.time, "sleep", clock.sleep)
    report = _client(tmp_path).play(
        max_actions=4, duration=1000, cooldown=1, adapter=_waits(500), enter=False
    )
    assert report.attempted == 4
    assert report.stop_reason == StopReason.ACTION_BOUND


def test_first_limit_reached_wins_duration(tmp_path, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(client_mod.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(client_mod.time, "sleep", clock.sleep)
    report = _client(tmp_path).play(
        max_actions=500, duration=5, cooldown=1, adapter=_waits(500), enter=False
    )
    assert report.stop_reason == StopReason.DURATION_ELAPSED
    assert report.attempted < 500


def test_cooldown_applies_between_turns_only(tmp_path, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(client_mod.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(client_mod.time, "sleep", clock.sleep)
    report = _client(tmp_path).play(max_actions=4, cooldown=2, adapter=_waits(10), enter=False)
    assert report.attempted == 4
    assert clock.sleeps == [2, 2, 2], "no pause before the first or after the final turn"


def test_zero_cooldown_never_sleeps(tmp_path, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(client_mod.time, "sleep", clock.sleep)
    _client(tmp_path).play(max_actions=3, cooldown=0, adapter=_waits(10), enter=False)
    assert clock.sleeps == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"duration": 0},
        {"duration": -1},
        {"duration": float("nan")},
        {"duration": float("inf")},
        {"cooldown": -0.5},
        {"cooldown": float("nan")},
        {"max_actions": 0},
        {"max_actions": -3},
    ],
)
def test_invalid_bounds_are_rejected(kwargs):
    with pytest.raises(PlayBoundsError):
        validate_play_bounds(**kwargs)


def test_valid_bounds_accepted():
    validate_play_bounds(max_actions=1, duration=0.5, cooldown=0)


class InterruptingGateway(OkGateway):
    def __init__(self, after: int = 2) -> None:
        super().__init__()
        self.after = after
        self.turns = 0

    def send_command(self, command: str, arguments=None, **kwargs) -> CommandResult:
        self.turns += 1
        if self.turns > self.after:
            raise KeyboardInterrupt
        return super().send_command(command, arguments, **kwargs)


def test_ctrl_c_reports_a_partial_summary(tmp_path):
    c = _client(tmp_path)
    # play() issues one observe() before the loop, so allow three calls to get
    # two completed turns before the interrupt.
    c._gateway = InterruptingGateway(after=3)
    report = c.play(max_actions=50, adapter=_waits(50), enter=False)
    assert report.stop_reason == StopReason.USER_INTERRUPT
    assert report.attempted == 2
    assert report.succeeded == 2
    assert "user_interrupt" in report.summary()


def test_summary_reports_counts_and_reason_without_secrets(tmp_path):
    report = _client(tmp_path).play(max_actions=2, adapter=_waits(5), enter=False)
    text = report.summary()
    assert "turns=2" in text
    assert "attempted=2" in text
    assert "ok=2" in text
    assert "rejected=0" in text
    assert "stop=action_bound" in text
    assert "token" not in text.lower()
    assert report.as_dict()["stop_reason"] == "action_bound"


def test_enter_world_is_issued_once(tmp_path):
    c = _client(tmp_path)
    report = c.play(max_actions=5, adapter=_waits(10), enter=True)
    assert c._gateway.commands.count("ENTER_WORLD") == 1
    assert report.stop_reason == StopReason.ACTION_BOUND


def test_no_proposal_is_named(tmp_path):
    report = _client(tmp_path).play(max_actions=5, adapter=_waits(1), enter=False)
    assert report.stop_reason == StopReason.NO_PROPOSAL
    assert report.attempted == 2
