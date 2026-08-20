"""Client-local failures. Not world authority.

Adapted from Zero-State-LLC/Noema src/noema/harness/errors.py.
"""

from __future__ import annotations

from enum import Enum


class FailureClass(str, Enum):
    RETRYABLE_TRANSPORT = "RETRYABLE_TRANSPORT"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    WORLD_NOT_READY = "WORLD_NOT_READY"
    WORLD_PAUSED = "WORLD_PAUSED"
    WORLD_INCIDENT = "WORLD_INCIDENT"
    ACTION_REJECTED = "ACTION_REJECTED"
    INVALID_PROPOSAL = "INVALID_PROPOSAL"
    SETTLEMENT_FAILURE = "SETTLEMENT_FAILURE"
    SETTLEMENT_RESYNC = "SETTLEMENT_RESYNC"
    PROTOCOL = "PROTOCOL"
    SEAL = "SEAL"


class NoemaError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False, failure: FailureClass | None = None) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        self.failure = failure
        super().__init__(message)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.code})"

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class NoemaAuthError(NoemaError):
    pass


class NoemaProtocolError(NoemaError):
    pass


class NoemaWorldPaused(NoemaError):
    pass


class NoemaWorldIncident(NoemaError):
    pass


class NoemaActionRejected(NoemaError):
    pass


class NoemaTransportError(NoemaError):
    pass


class NoemaSealError(NoemaError):
    pass


def raise_for_failure(failure: FailureClass | None, code: str, message: str) -> None:
    if failure is None:
        return
    mapping = {
        FailureClass.AUTH_REQUIRED: NoemaAuthError,
        FailureClass.WORLD_PAUSED: NoemaWorldPaused,
        FailureClass.WORLD_INCIDENT: NoemaWorldIncident,
        FailureClass.ACTION_REJECTED: NoemaActionRejected,
        FailureClass.INVALID_PROPOSAL: NoemaActionRejected,
        FailureClass.RETRYABLE_TRANSPORT: NoemaTransportError,
        FailureClass.PROTOCOL: NoemaProtocolError,
        FailureClass.SEAL: NoemaSealError,
        FailureClass.WORLD_NOT_READY: NoemaError,
        FailureClass.SETTLEMENT_FAILURE: NoemaActionRejected,
        FailureClass.SETTLEMENT_RESYNC: NoemaActionRejected,
    }
    cls = mapping.get(failure, NoemaError)
    raise cls(code, message, retryable=failure == FailureClass.RETRYABLE_TRANSPORT, failure=failure)
