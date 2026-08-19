# Conformance

Do not put tokens in this file.

| Field | Value |
|---|---|
| client | scrimshawlife-ctrl/noema-client (this repo) |
| Specs authority | Zero-State-LLC/Noema-Specs `672b780` RFC-0116 / OFFICIAL-AGENT-CLIENT.md |
| Server reference | Zero-State-LLC/Noema origin/main at bootstrap |
| Protocol | agent-protocol/v1 |
| Seal | `sha256:9b9c211c156a9b49e700fa39e409733099a38df9d95c7f6fb90ca3e9e740a395` (published S0 prompt bytes) |
| Isolated hosted command proof | not run in this bootstrap (no isolated Player token path; official client does not carry Admin/test-world credentials) |
| Live Perihelion proof | not run (no production mutation) |
| Live discovery | OBSERVED `GET https://noema.guru/.well-known/noema-agent.json` protocol `agent-protocol/v1`, published seal listed |

Python unit + fake-server tests are the ordinary gate. They must not mutate Perihelion Reach.
