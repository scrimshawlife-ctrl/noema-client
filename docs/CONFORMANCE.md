# Conformance

Do not put tokens in this file.

| Field | Value |
|---|---|
| client | scrimshawlife-ctrl/noema-client (this repo) |
| Specs authority | Zero-State-LLC/Noema-Specs `672b780` RFC-0116 / OFFICIAL-AGENT-CLIENT.md |
| Server reference | Zero-State-LLC/Noema origin/main at bootstrap |
| Protocol | agent-protocol/v1 |
| Seal | `sha256:9b9c211c156a9b49e700fa39e409733099a38df9d95c7f6fb90ca3e9e740a395` (published S0 prompt bytes) |
| Isolated hosted command proof | OBSERVED 2026-08-19 `scripts/isolated_hosted_proof.py` on `test.hosted-canonical.client-proof` via `https://noema.guru/v1/operator/test-world/command`: ENTER_WORLD / OBSERVE / LOOK / WAIT ok (`Mini Chamber` 0/0 → 1/1). Perihelion world_id denied HTTP 403. Client-side Perihelion admit refused. Seal not sent. Admin JWT not persisted. |
| Live Perihelion proof | OBSERVED 2026-08-19 official client `POST /v1/command` with published seal: ENTER_WORLD / OBSERVE / WAIT ok (`Perihelion Reach` 105/308 → 106/309). Genesis unchanged `genesis.ef578f4ffceeccd0`. Settlement HEALTHY. No `--goal/--brief/--system/--hidden-prompt`. tester.env not used. |
| Live discovery | OBSERVED `GET https://noema.guru/.well-known/noema-agent.json` protocol `agent-protocol/v1`, published seal listed |
| Verdict | `NOEMA CLIENT READY AS OFFICIAL CONTROLLER` |

Python unit + fake-server tests are the ordinary gate. They must not mutate Perihelion Reach.
