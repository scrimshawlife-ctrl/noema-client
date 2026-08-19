# Parity matrix (bootstrap)

Internal source: `Zero-State-LLC/Noema` harness + `clients/noema-llm-agent`.

| Capability | Current Noema client | New noema-client | Parity? |
|---|---|---|---|
| device enroll | harness `DeviceEnrollmentProvider` | `noema connect` | yes |
| controller token | env / enroll | `~/.config/noema/credential.json` 0600 | yes |
| seal | vendored S0 hash + `X-Noema-Seal` | same hash + discovery catalog | yes |
| HTTP `/v1/command` | `GatewayClient` | `HttpGateway` | yes |
| WebSocket HELLO/AUTH | llm-agent `websockets` | optional `[ws]` extra; persistent HELLO/AUTH | yes |
| WebSocket ACT/OBSERVE | llm-agent ACT frames | official client ACT/OBSERVE/PING/DISCONNECT on the same socket | yes |
| resume | llm-agent resume_token | HELLO `resume_token` + stored in `credential.json` 0600 (never printed) | yes |
| observe | harness `to_state` | `Observation` | yes |
| affordance validation | `validate_proposal` | copied | yes |
| scripted run | `ScriptedAdapter` / first-valid | copied | yes |
| LLM adapter | `noema_llm_agent` + OpenAI SDK | OpenAI-compatible urllib, no vendor SDK | partial (no Anthropic SDK) |
| isolated tenant | operator test-world scripts | `--isolated --world-id test.hosted-canonical.*` posts `/v1/operator/test-world/command`; Admin JWT from env only, never stored | yes |
| live tenant | sealed attach on Perihelion | official client ENTER/OBSERVE/WAIT on `/v1/command` with published seal | yes |
| token secrecy | redacted providers | tests for repr/status/telemetry/context | yes |
