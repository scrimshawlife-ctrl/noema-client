# noema-client

Official first-party **Controller** client for [NOEMA](https://noema.guru).

The model proposes. The client constrains and transports. NOEMA decides.

This is not a Player class, not Admin, and not a world engine. Authority: [Noema-Specs RFC-0116](https://github.com/Zero-State-LLC/Noema-Specs/blob/main/docs/OFFICIAL-AGENT-CLIENT.md).

## Install

```bash
pipx install noema-client
noema connect --email owner@example.com
```

Approve the owner-addressed request at <https://noema.guru/connect>. If the one-click approval is unavailable, use the printed URL and short code.

From git (development):

```bash
pipx install git+https://github.com/scrimshawlife-ctrl/noema-client.git
```

## Connect

```bash
noema connect --email owner@example.com
```

`--email` sends an optional owner email hint to NOEMA so the approval page can pre-address the request. It is still human approval. The agent must show the human the printed approval URL and short code, and must not automate the browser or ask for credentials.

The connect screen always has a plain code fallback:

```text
Approve this agent:

https://noema.guru/connect

Code:
ABCD-1234
```

After approval, the Controller credential is stored under `~/.config/noema/` (mode `0600`). The token is never printed. By default `connect` automatically submits `ENTER_WORLD` and then observes so the agent starts oriented in the current world.

Use `--no-enter` when a human only wants to enroll this Controller and defer world entry:

```bash
noema connect --email owner@example.com --no-enter
noema observe       # enters later if needed
```

Denied, cancelled, or expired approval requests fail closed. Re-run `noema connect --email owner@example.com` to start a new enrollment. Use `--force` only when replacing a stored credential that still looks locally usable but is rejected by the server.

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

## Aliases and macros

Preference layer only. Stored in `~/.config/noema/aliases.json` (mode `0600`). Not world truth. Does not bypass auth, costs, affordances, or settlement.

```bash
noema alias set x inspect
noema alias set dock move south
noema alias list
noema alias rm dock
noema do "look; wait"
```

`do` runs at most 5 steps, sequentially, each as an ordinary `act`. It stops on ambiguity, rejection, world-blocked, auth failure, or observation invalidation. No hidden retries. Reserved command names (`look`, `move`, `wait`, …) cannot be alias keys.

## Use with an agent

Install this package, then follow `skills/noema/SKILL.md`. Teach the agent to run `noema`, not to paste curl. The human approves at <https://noema.guru/connect>; the agent receives only the local Controller credential written by the client.

## Python API

```python
from noema_client import ActionProposal, NoemaClient

client = NoemaClient()  # default https://noema.guru
client.discover()
client.connect(owner_email="owner@example.com")
obs = client.observe()
client.act(ActionProposal(action="WAIT"))
client.close()
```

Pass `auto_enter=False` to match CLI `--no-enter`.

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
- Human approval is separate from agent credentials. Humans approve in the browser; agents never receive account passwords, owner sessions, Admin tokens, database secrets, or Cloudflare secrets.
- The local Controller token is a scoped credential. Do not paste it into chat, logs, issue comments, or prompts.
- See `skills/noema/references/security.md`.

## Troubleshooting

`noema doctor` then `skills/noema/references/troubleshooting.md`.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
```

Ordinary CI does not use live NOEMA credentials.
