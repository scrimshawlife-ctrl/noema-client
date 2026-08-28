from __future__ import annotations

import pytest

from noema_client.acceptance import (
    AcceptanceError,
    run_materials_acceptance,
    validate_materials_gate,
)
from noema_client.cli import main
from noema_client.client import NoemaClient
from noema_client.types import Affordance, CommandResult, Observation

WORLD = "world.perihelion-reach-3"
RUN = "roadmap-579-a"


def result(
    *, sequence: int, cargo: bool = False, constructed: bool = False, storage: int | None = None
) -> CommandResult:
    raw = {"events": [{"event_type": "CONSTRUCT_COMPLETED"}]} if constructed else {}
    observation = {"sequence": sequence, "lot_lines": ["Cargo: 1 lot"] if cargo else []}
    if storage is not None:
        observation["budgets"] = {"storage": storage}
    return CommandResult(
        ok=True,
        observation=observation,
        error=None,
        settled=True,
        http_status=200,
        failure=None,
        idempotency_key="idem",
        request_id="req",
        world_status="ACTIVE",
        raw=raw,
    )


class StubClient:
    server = "https://noema.guru"

    def __init__(self, *, cargo: bool = True, constructed: bool = True) -> None:
        self.cargo = cargo
        self.constructed = constructed
        self.calls: list[tuple] = []

    def observe(self) -> Observation:
        return Observation(
            world=WORLD,
            sequence=10,
            affordances=[Affordance(action="HARVEST", target_id="entity.salvage-cache")],
        )

    def act(self, proposal, *, idempotency_key=None, request_id=None):
        self.calls.append((proposal, idempotency_key, request_id))
        if proposal.action == "HARVEST":
            return result(sequence=11, cargo=self.cargo)
        return result(sequence=12, constructed=self.constructed)


def ready() -> dict:
    return {"world_id": WORLD, "status": "ACTIVE", "settlement_health": "HEALTHY"}


def production_ready() -> dict:
    return {
        "ready": True,
        "status": "ACTIVE",
        "settlement_health": "HEALTHY",
        "world": ready(),
    }


def test_gate_refuses_wrong_ack_before_client_or_network(tmp_path, capsys):
    rc = main(
        [
            "--config-dir",
            str(tmp_path),
            "accept",
            "materials-construct",
            "--world-id",
            WORLD,
            "--ack",
            "yes",
            "--run-id",
            RUN,
        ]
    )
    assert rc == 2
    payload = capsys.readouterr().out
    assert '"code": "ACK_REQUIRED"' in payload


def test_gate_requires_exact_production_host():
    with pytest.raises(AcceptanceError, match="PRODUCTION_HOST_REQUIRED"):
        validate_materials_gate(
            server="https://staging.example",
            world_id=WORLD,
            ack=f"MUTATE {WORLD}",
            run_id=RUN,
        )


def test_acceptance_runs_harvest_then_construct_with_stable_retry_keys():
    client = StubClient()
    output = run_materials_acceptance(
        client,  # type: ignore[arg-type]
        ready=ready(),
        world_id=WORLD,
        ack=f"MUTATE {WORLD}",
        run_id=RUN,
        harvest_target="entity.salvage-cache",
        construct_class="workshop",
    )
    assert output == {
        "ok": True,
        "run_id": RUN,
        "world_id": WORLD,
        "harvest": {"target_id": "entity.salvage-cache", "amount": 5, "settled": True, "sequence": 11},
        "construct": {"class": "workshop", "settled": True, "sequence": 12},
    }
    assert [call[0].action for call in client.calls] == ["HARVEST", "BUILD"]
    assert client.calls[0][1:] == (
        f"accept.materials.{RUN}.harvest",
        f"accept.materials.{RUN}.harvest",
    )
    assert client.calls[1][1:] == (
        f"accept.materials.{RUN}.construct",
        f"accept.materials.{RUN}.construct",
    )


def test_acceptance_accepts_nested_production_ready_world():
    client = StubClient()
    output = run_materials_acceptance(
        client,  # type: ignore[arg-type]
        ready=production_ready(),
        world_id=WORLD,
        ack=f"MUTATE {WORLD}",
        run_id=RUN,
    )
    assert output["ok"] is True


def test_acceptance_refuses_stock_below_construct_cargo_requirement():
    client = StubClient()
    observed = client.observe()
    observed.location = {
        "entities": [
            {
                "entity_id": "entity.salvage-cache",
                "stock_resource": "materials",
                "stock_amount": 4.9,
            }
        ]
    }
    client.observe = lambda: observed  # type: ignore[method-assign]
    with pytest.raises(AcceptanceError, match="HARVEST_STOCK_INSUFFICIENT"):
        run_materials_acceptance(
            client,  # type: ignore[arg-type]
            ready=ready(),
            world_id=WORLD,
            ack=f"MUTATE {WORLD}",
            run_id=RUN,
        )
    assert client.calls == []


def test_acceptance_stops_before_construct_without_cargo_receipt():
    client = StubClient(cargo=False)
    with pytest.raises(AcceptanceError, match="CARGO_NOT_OBSERVED"):
        run_materials_acceptance(
            client,  # type: ignore[arg-type]
            ready=ready(),
            world_id=WORLD,
            ack=f"MUTATE {WORLD}",
            run_id=RUN,
        )
    assert [call[0].action for call in client.calls] == ["HARVEST"]


def test_acceptance_accepts_canonical_storage_delta_as_cargo_evidence():
    client = StubClient(cargo=False)
    observed = client.observe()
    observed.resources = {"storage": 16}
    client.observe = lambda: observed  # type: ignore[method-assign]
    original_act = client.act

    def act(proposal, *, idempotency_key=None, request_id=None):
        if proposal.action == "HARVEST":
            client.calls.append((proposal, idempotency_key, request_id))
            return result(sequence=11, storage=11)
        return original_act(proposal, idempotency_key=idempotency_key, request_id=request_id)

    client.act = act  # type: ignore[method-assign]
    output = run_materials_acceptance(
        client,  # type: ignore[arg-type]
        ready=ready(),
        world_id=WORLD,
        ack=f"MUTATE {WORLD}",
        run_id=RUN,
    )
    assert output["ok"] is True
    assert [call[0].action for call in client.calls] == ["HARVEST", "BUILD"]


def test_acceptance_fails_closed_without_construct_receipt():
    client = StubClient(constructed=False)
    with pytest.raises(AcceptanceError, match="ENTITY_RECEIPT_MISSING"):
        run_materials_acceptance(
            client,  # type: ignore[arg-type]
            ready=ready(),
            world_id=WORLD,
            ack=f"MUTATE {WORLD}",
            run_id=RUN,
        )


def test_acceptance_uses_public_client_validation_and_transport(tmp_path):
    class Gateway:
        def __init__(self) -> None:
            self.calls: list[tuple] = []

        def send_command(self, command, arguments=None, **kwargs):
            self.calls.append((command, arguments, kwargs))
            if command == "OBSERVE":
                return CommandResult(
                    ok=True,
                    observation={
                        "world_id": WORLD,
                        "sequence": 10,
                        "available_actions": ["HARVEST"],
                        "affordances": [
                            {"operation": "HARVEST", "target_id": "entity.salvage-cache"}
                        ],
                    },
                    error=None,
                    settled=True,
                    http_status=200,
                    failure=None,
                    idempotency_key=None,
                    request_id=None,
                    world_status="ACTIVE",
                )
            if command == "COMMIT":
                return CommandResult(
                    ok=True,
                    observation={
                        "sequence": 11,
                        "lot_lines": ["Cargo: 1 lot"],
                        "available_actions": ["CONSTRUCT"],
                    },
                    error=None,
                    settled=True,
                    http_status=200,
                    failure=None,
                    idempotency_key=kwargs["idempotency_key"],
                    request_id=kwargs["request_id"],
                    world_status="ACTIVE",
                )
            return CommandResult(
                ok=True,
                observation={"sequence": 12, "consequence": "Constructed workshop"},
                error=None,
                settled=True,
                http_status=200,
                failure=None,
                idempotency_key=kwargs["idempotency_key"],
                request_id=kwargs["request_id"],
                world_status="ACTIVE",
            )

        def close(self):
            return None

    gateway = Gateway()
    client = NoemaClient(server="https://noema.guru", config_home=tmp_path, transport="http")
    client._gateway = gateway

    output = run_materials_acceptance(
        client,
        ready=ready(),
        world_id=WORLD,
        ack=f"MUTATE {WORLD}",
        run_id=RUN,
    )

    assert output["ok"] is True
    assert gateway.calls == [
        ("OBSERVE", {}, {}),
        (
            "COMMIT",
            {"amount": 5, "operation": "HARVEST", "entity_id": "entity.salvage-cache"},
            {
                "idempotency_key": f"accept.materials.{RUN}.harvest",
                "request_id": f"accept.materials.{RUN}.harvest",
            },
        ),
        (
            "BUILD",
            {"operation": "CONSTRUCT", "class": "workshop"},
            {
                "idempotency_key": f"accept.materials.{RUN}.construct",
                "request_id": f"accept.materials.{RUN}.construct",
            },
        ),
    ]
