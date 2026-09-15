# Nemotron controller profile for the shared research program

Program: `ABX-NOEMA-REP-001`  
Status: proposed / SHADOW / ADVISORY_ONLY  
Date: 2026-09-14  
Scope: specification review only; no runtime or permission change.

[Shared program draft](https://github.com/scrimshawlife-ctrl/Abraxas/blob/codex/persistent-agent-program-20260914/docs/research/persistent-agent-program/spec.md) owns cross-repository experiment coordination, workflows WF-P01 through WF-P05, acceptance AC-P01 through AC-P10, and the candidate sidecar. This document owns only this repository's participation mapping. The program is not a new specialist or a replacement for existing contracts. Draft branch links are review links; pin the accepted commit when adopted.

## Existing authority

[Agent instructions](../AGENTS.md) and [Noema-Specs official client contract](https://github.com/Zero-State-LLC/Noema-Specs/blob/main/docs/OFFICIAL-AGENT-CLIENT.md) remain authoritative. Product intent lives in Noema-Specs. This is a client-only implementation planning profile, not a second Agent Protocol or new gameplay behavior.

## Candidate profile

Use the existing optional OpenAI-compatible adapter after confirming the installed client's actual configuration surface. Pin model/tokenizer revision, checkpoint/license, serving engine and immutable image digest, precision, context limit, generation budget, prompt template revision, sampling/seed policy, runtime versions and endpoint capability. Check DGX Spark compatibility before selecting an engine; this note selects no checkpoint or engine and invents no CLI flag.

Keep inference endpoint credentials separate from Controller credentials. Noema host does not need model-provider credentials. A compatible chat-completions endpoint does not imply Noesis hidden-state capture support. Model responses propose only existing affordance-constrained actions; the server remains the authority.

## Workflows and acceptance

J-P02 -> WF-P02 -> FROZEN/RUNNING/CAPTURED or BLOCKED -> existing client discovery, seal, proposal, command and resume contracts -> AC-P03/AC-P04 -> T-CLI-P01.

T-CLI-P01: specify scripted and Nemotron profiles for the same isolated reliability scenario, including max actions, consecutive failure limits, stop conditions, request timeout and retry budget. Verify admission/seal, valid action, malformed output, missing target, timeout, server rejection, INCIDENT, credential revocation, and restart/resume. Use existing idempotency semantics; do not invent automatic retry for non-idempotent commands. No silent fallback to another model.

J-P05 -> WF-P05 -> DOSSIER_DRAFT -> inference and end-to-end measurements -> AC-P09 -> T-CLI-P02. Record model-call latency separately from transport/world settlement; p50/p95 with counts and sampling method, input/output tokens where available, valid proposal denominator, accepted/rejected actions and memory/throughput telemetry via an external collector. Missing provider usage fields remain unavailable.

## Authority and evidence

Human /connect approval remains manual where required by the existing enrollment contract. This spec does not execute enrollment, acquire credentials, authorize isolated actions or alter live Perihelion seal rules. Operator-supplied experimental prompts belong only to an admitted isolated profile; they must not become hidden strategic instructions on the sealed live path.

No Nemotron invocation, throughput benchmark, model fit, memory reading or recovery acceptance is asserted. Actual end-to-end compatibility remains NOT_COMPUTABLE until receipt-backed. First implementation should follow accepted Noema intent/spec and identify exact existing adapter symbols/configuration rather than creating duplicate infrastructure.

## Verification

Documentation link/diff checks and existing client tests establish local consistency. A future profile implementation needs mocked protocol/model failure tests and an independently authorized isolated-world receipt; local tests do not imply production acceptance.
