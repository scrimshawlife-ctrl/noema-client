"""Token secrecy. Credentials never appear in repr, telemetry, or model context."""

from __future__ import annotations

from typing import Any

REDACTED = "<redacted>"


def redact_text(text: str, secrets: list[str]) -> str:
    out = text
    for secret in secrets:
        if secret and secret in out:
            out = out.replace(secret, REDACTED)
    return out


def collect_secrets(*values: str | None) -> list[str]:
    return [v for v in values if v]


def redact_mapping(data: Any, secrets: list[str]) -> Any:
    if isinstance(data, str):
        return redact_text(data, secrets)
    if isinstance(data, dict):
        return {k: redact_mapping(v, secrets) for k, v in data.items()}
    if isinstance(data, list):
        return [redact_mapping(v, secrets) for v in data]
    return data
