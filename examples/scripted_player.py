"""Scripted Controller. No LLM. No secrets."""

from noema_client import ActionProposal, NoemaClient
from noema_client.adapters import ScriptedAdapter


def main() -> None:
    client = NoemaClient()
    client.discover()
    client.connect()
    client.play(
        adapter=ScriptedAdapter(
            [
                ActionProposal(action="ENTER_WORLD"),
                ActionProposal(action="LOOK"),
                ActionProposal(action="WAIT"),
            ]
        ),
        max_actions=3,
        enter=False,
    )
    client.close()


if __name__ == "__main__":
    main()
