"""Optional OpenAI-compatible adapter. Isolated/dev only.

Do not pass --goal / --brief / --system on live Perihelion (RFC-0115).
"""

from noema_client import NoemaClient
from noema_client.adapters import OpenAICompatibleAdapter


def main() -> None:
    client = NoemaClient()
    client.discover()
    client.connect()
    adapter = OpenAICompatibleAdapter(base_url="http://127.0.0.1:11434/v1", model="llama3")
    client.play(adapter=adapter, max_actions=4)
    client.close()


if __name__ == "__main__":
    main()
