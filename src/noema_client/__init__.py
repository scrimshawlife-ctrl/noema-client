"""Official first-party Controller client for NOEMA.

The model proposes. The client constrains and transports. NOEMA decides.
"""

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
from noema_client.affordances import proposal_from_affordance
from noema_client.types import ActionProposal, Affordance, Observation

__version__ = "0.1.9"
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
    "proposal_from_affordance",
    "__version__",
]
