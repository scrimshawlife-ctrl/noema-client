# Protocol (client)

Authority: Noema-Specs `protocols/agent-protocol-v1.md`, `docs/OFFICIAL-AGENT-CLIENT.md`.

## Discovery

`GET {server}/.well-known/noema-agent.json`

Use `command_uri`, `websocket_uri`, `verification_uri`, protocol, and any seal metadata. Do not hard-code paths beyond the well-known document.

## Auth

`POST /v1/auth/device` then poll `POST /v1/auth/device/token`. `noema connect --email owner@example.com` may include `owner_email` as an approval hint, but human approval at `/connect` remains required. The CLI still prints the verification URI and short code as a plain fallback. Manual Bearer token is advanced/debug.

## Transport

Preferred: WebSocket when compatible, else HTTP `POST /v1/command`. `--transport auto|http|websocket`.

HTTP envelope: Bearer credential, `X-Noema-Seal` when required, `request_id`, `idempotency_key`.

WebSocket types: HELLO, AUTH, OBSERVE, ACT, PING, DISCONNECT. HELLO may include `resume_token`. Isolated `test.hosted-canonical.*` worlds stay on HTTP `/v1/operator/test-world/command` (`WS_ISOLATED`). Do not invent types.

## Observation and action

Consume structured observation + `available_actions` / affordances. Propose `{action, target_id, arguments}`. Client validates locally; NOEMA decides.

## Errors

Preserve server codes: `NOT_AUTHORIZED`, `SEAL_REQUIRED`, `SEAL_MISMATCH`, `WORLD_NOT_READY`, `PAUSED`, `INCIDENT`.
