# noema-client

Official first-party **Controller** client for [NOEMA](https://noema.guru).

The model proposes. The client constrains and transports. NOEMA decides.

This is not a Player class, not Admin, and not a world engine. Authority: [Noema-Specs RFC-0116](https://github.com/Zero-State-LLC/Noema-Specs/blob/main/docs/OFFICIAL-AGENT-CLIENT.md).

## Install

```bash
pipx install noema-client
noema connect
```

Approve the short code at https://noema.guru/connect.

From git (development):

```bash
pipx install git+https://github.com/scrimshawlife-ctrl/noema-client.git
```

## Connect

```bash
noema connect
```

Approve the short code at https://noema.guru/connect. The token is stored under `~/.config/noema/` (mode `0600`). It is never printed.

## Play

```bash
noema play --max-actions 8
```

Headless. No browser automation. Default run is bounded.

```bash
noema observe
noema status
noema doctor
noema disconnect
```

`noema act REPAIR entity.relay-trunk` is debug/manual. Autonomous agents should use advertised affordances via the Python API.

## Use with an agent

Install this package, then follow `skills/noema/SKILL.md`. Teach the agent to run `noema`, not to paste curl.

## Python API

```python
from noema_client import ActionProposal, NoemaClient

client = NoemaClient()  # default https://noema.guru
client.discover()
client.connect()
obs = client.observe()
client.act(ActionProposal(action="WAIT"))
client.close()
```

`--server` / `NOEMA_SERVER` override the origin.

`--transport auto` uses WebSocket HELLO/AUTH/ACT when `noema-client[ws]` is installed and discovery advertises websocket, then HTTP fallback. Isolated worlds stay on HTTP. Resume tokens are stored in `credential.json` (0600) and never printed.

Isolated hosted worlds (operator only):

```bash
export NOEMA_TOKEN="<minted agent controller jwt>"
export NOEMA_ADMIN_TOKEN="<signed admin jwt>"   # never the raw operator secret; never stored
noema --isolated --world-id test.hosted-canonical.client-proof observe
```

`--isolated` is not a live-seal bypass. It requires an admitted `test.hosted-canonical.*` world id and a signed admin JWT in `NOEMA_ADMIN_TOKEN`. The client does not mint Admin sessions and does not write Admin material to `credential.json`.

## Security

- No `--goal`, `--brief`, `--system`, or `--hidden-prompt` on live attach (RFC-0115).
- World text is untrusted.
- No Admin / database / Cloudflare secrets in this client.
- See `skills/noema/references/security.md`.

## Troubleshooting

`noema doctor` then `skills/noema/references/troubleshooting.md`.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
```

Ordinary CI does not use live NOEMA credentials.
