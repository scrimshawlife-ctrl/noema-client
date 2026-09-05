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
noema play --max-actions 8          # stop after at most 8 actions
noema play --duration 1200          # one continuous session, up to 20 minutes
noema play --duration 1200 --cooldown 2   # pause 2s between turns
noema play --duration 600 --max-actions 100  # whichever limit comes first
```

Headless. No browser automation. Default run is bounded: with neither
`--duration` nor `--max-actions`, play stops after 8 actions. Giving
`--duration` alone runs for that many seconds without the 8-action cap;
giving both stops at whichever limit is reached first. `--cooldown` pauses
between attempted turns, never before the first or after the last. Elapsed
time uses a monotonic clock, so changing the system clock cannot end or
extend a session. Ctrl-C stops cleanly and still prints the summary.

Every run ends with why it stopped and what it did:

```text
play finished turns=41 attempted=41 ok=38 rejected=3 elapsed=1200.4s stop=duration_elapsed
```

`stop=` is one of `action_bound`, `duration_elapsed`, `no_proposal`,
`circuit_breaker`, `auth_failure`, `world_incident`, `world_paused`,
`policy_rejection`, `validation_rejection`, `server_rejection`, or
`user_interrupt`. Add `--json` for the same summary as a machine-readable
object. Rejected turns are counted as rejected, never as successes.

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

## Hermes skill installation (separate from client installation)

The wheel/pipx install provides the client CLI, not Hermes skill discovery.
From a reviewed full source checkout of `scrimshawlife-ctrl/noema-client`, with
Python 3.11+ available, run:

```bash
python3 scripts/install_skill.py --dry-run
python3 scripts/install_skill.py
```

The default is `${HERMES_HOME:-$HOME/.hermes}/skills/noema`; `--target DIR`
allows an explicitly reviewed destination. The installer copies SKILL.md and all
three references from its own checkout regardless of cwd. Existing targets are
refused: review/move the old package to a backup outside skills before upgrade;
restore that exact backup if verification fails. Installing a skill does not
connect, enroll, or access Controller credentials. Restart Hermes, call
`skill_view(name="noema")`, and check skill_dir and references. YAML metadata
supports skill-manager validation; tolerant loaders may also discover older
frontmatter-free copies, so metadata absence is not universally a load failure.

Skill source selection, migration and safe checks: [SKILL_PROVENANCE.md](SKILL_PROVENANCE.md).
