"""Official first-party Controller client for NOEMA.

The model proposes. The client constrains and transports. NOEMA decides.
"""

from noema_client._version import __version__
from noema_client.affordances import proposal_from_affordance
from noema_client.client import NoemaClient
from noema_client.errors import (
    NoemaActionRejected,
    NoemaAuthError,
    NoemaError,
    NoemaProtocolError,
    NoemaSealError,
    NoemaTransportError,
    NoemaWorldIncident,
    NoemaWorldPaused,
)
from noema_client.types import ActionProposal, Affordance, Observation

__all__ = [
    "ActionProposal",
    "Affordance",
    "NoemaActionRejected",
    "NoemaAuthError",
    "NoemaClient",
    "NoemaError",
    "NoemaProtocolError",
    "NoemaSealError",
    "NoemaTransportError",
    "NoemaWorldIncident",
    "NoemaWorldPaused",
    "Observation",
    "__version__",
    "proposal_from_affordance",
]
