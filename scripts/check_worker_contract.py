#!/usr/bin/env python3
"""Compare the pinned Worker affordance commands against the Worker itself.

`tests/fixtures/worker_affordance_cmds.json` pins every `cmd:` template the
hosted Worker emits, split into the ones this client's friendly parser handles
and the ones it only ever sends structured. The suite checks the client against
that fixture -- but nothing checked the fixture against the Worker, so the
Worker could add or rename a command and the contract would drift silently
while CI stayed green.

Run with a Noema checkout path. Exits non-zero on drift and names both
directions, because they need different fixes: a command the Worker gained must
be classified (parsed or structured_only), and one it no longer emits must be
dropped.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CMD = re.compile(r"cmd:\s*`([^`]*)`")


def worker_templates(noema: Path) -> set[str]:
    src = noema / "workers" / "noema" / "src" / "actions.ts"
    if not src.exists():
        sys.exit(f"not a Noema checkout: {src} missing")
    return set(CMD.findall(src.read_text(encoding="utf-8")))


def pinned(fixture: Path) -> tuple[set[str], set[str]]:
    doc = json.loads(fixture.read_text(encoding="utf-8"))
    parsed = {c["template"] for c in doc["parsed"]}
    structured = set(doc["structured_only"])
    return parsed, structured


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--noema", required=True, type=Path)
    ap.add_argument(
        "--fixture",
        type=Path,
        default=Path("tests/fixtures/worker_affordance_cmds.json"),
    )
    args = ap.parse_args()

    emitted = worker_templates(args.noema)
    parsed, structured = pinned(args.fixture)
    both = parsed & structured
    known = parsed | structured

    added = sorted(emitted - known)
    removed = sorted(known - emitted)

    print(f"worker emits {len(emitted)} templates; fixture pins {len(known)} "
          f"({len(parsed)} parsed, {len(structured)} structured-only)")

    problems = []
    if both:
        problems.append(
            "these are in BOTH parsed and structured_only, which is ambiguous:\n  "
            + "\n  ".join(sorted(both))
        )
    if added:
        problems.append(
            "the Worker emits these and the fixture does not pin them.\n"
            "Classify each: add to `parsed` with a sample and expected canonical\n"
            "action if the friendly parser handles it, else to `structured_only`:\n  "
            + "\n  ".join(added)
        )
    if removed:
        problems.append(
            "the fixture pins these and the Worker no longer emits them.\n"
            "Drop them, or the contract test is asserting against a command that\n"
            "cannot appear:\n  " + "\n  ".join(removed)
        )

    if problems:
        print("\nWORKER CONTRACT DRIFT\n")
        for p in problems:
            print(p + "\n")
        return 1

    print("no drift: every emitted command is pinned, and every pin is still emitted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
