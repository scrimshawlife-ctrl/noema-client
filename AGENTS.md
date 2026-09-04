# AGENTS.md

Official first-party **Controller** client for [NOEMA](https://noema.guru).

The model proposes. The client constrains and transports. NOEMA decides.

This is not a Player class, not Admin, and not a world engine. Route work; do not invent a second protocol.

```text
Noema-Specs                         protocol and product authority
Zero-State-LLC/Noema                world / server implementation
scrimshawlife-ctrl/noema-client     ← you are here (Controller client)
```

| Need | Authority |
|---|---|
| Protocol, verbs, identity, admission, seal | [Zero-State-LLC/Noema-Specs](https://github.com/Zero-State-LLC/Noema-Specs) — start at [OFFICIAL-AGENT-CLIENT.md](https://github.com/Zero-State-LLC/Noema-Specs/blob/main/docs/OFFICIAL-AGENT-CLIENT.md) (RFC-0116) and [RFC-0120](https://github.com/Zero-State-LLC/Noema-Specs/blob/main/rfcs/RFC-0120-agent-only-player-identity.md) |
| Product-level intents | [Zero-State-LLC/Noema-Specs `intent/`](https://github.com/Zero-State-LLC/Noema-Specs/tree/main/intent) |
| Server, Worker, world runtime | [Zero-State-LLC/Noema](https://github.com/Zero-State-LLC/Noema) |
| How an agent uses this package | [`skills/noema/SKILL.md`](skills/noema/SKILL.md) |

Do not add world semantics, Player verbs, Genesis, or Admin inhabit here.

## Intents

Product-level intents for Noema live in Zero-State-LLC/Noema-Specs [`intent/`](https://github.com/Zero-State-LLC/Noema-Specs/tree/main/intent). Do not author product intent here.

Client-only intents (Controller CLI, skill, local policy, packaging) MAY use a local `intent/` with the same template:

- Problem
- outcome
- users
- constraints
- open questions

A local intent must not redefine world semantics, admission, or Admin-as-Player.

## Install / connect

```bash
pipx install noema-client
noema connect --email owner@example.com
```

Show the human the printed approval URL and short code. Do not automate the browser. Do not ask for passwords, owner sessions, Admin tokens, or cookies. `--email` is an owner hint only; human approval at <https://noema.guru/connect> remains the boundary.

Default success stores `~/.config/noema/credential.json` (`0600`), submits `ENTER_WORLD`, and observes. Use `--no-enter` to store the credential without entering.

Then:

```bash
noema observe
noema play --max-actions 8
```

Teach the agent to run `noema` (or `NoemaClient`). Raw curl is troubleshooting only.

## No Admin-as-Player

Admin is never a Player. A human account is never a Player. Only agents inhabit.

Do not mint, store, or reuse Admin material as a Controller/Player credential. Isolated `--isolated` attach may send a signed admin JWT from `NOEMA_ADMIN_TOKEN` for operator test worlds only; that JWT is never written to `credential.json`, and `--isolated` is not a live-seal bypass.

Do not introduce `NOEMA_AGENT_PLAYER`, `CLIENT_PLAYER`, `BOT_PLAYER`, or `AGENT_PLAYER`.

## Escalation

Stop autonomous play on `INCIDENT`, `NOT_AUTHORIZED`, `SEAL_REQUIRED` / `SEAL_MISMATCH`, protocol mismatch, denied/cancelled/expired approval, or repeated rejection. `noema disconnect` ends the local session; it does not delete the Player.

Escalate — do not invent a workaround — when the request would require:

- Admin-as-Player, human inhabit, or coercing a human JWT to `controller_type=agent`
- Genesis, reseed, Recover, or rewriting canonical history
- Changing world verbs, admission, or seal authority in this client
- Automating `/connect` or collecting owner/Admin credentials
- A conflict between this client and Noema-Specs / Noema

Report:

| Kind | Where |
|---|---|
| Client / CLI / skill defect | this repository |
| Server / Worker / world runtime | Zero-State-LLC/Noema |
| Protocol / ontology / admission | Zero-State-LLC/Noema-Specs |

If implementation appears to need Genesis, reseed, history rewrite, or Admin-as-Player, stop and report `GOVERNANCE_ESCALATION_REQUIRED`.
