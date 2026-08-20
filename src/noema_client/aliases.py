"""Player-preference aliases and bounded macros. Outside world truth.

Feature E / S4: expansion is local, deterministic, and never a world verb.
Each macro step is an ordinary canonical action. No hidden retries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from noema_client.errors import FailureClass, NoemaActionRejected
from noema_client.types import ActionProposal

MAX_ALIAS_DEPTH = 4
MAX_MACRO_STEPS = 5
MAX_ALIASES = 16

# Reserved command names cannot be alias keys. `x` is left open because
# Feature E's example is `alias x inspect`.
RESERVED = frozenset(
    {
        "help",
        "look",
        "l",
        "wait",
        "observe",
        "enter",
        "move",
        "go",
        "walk",
        "inspect",
        "examine",
        "repair",
        "harvest",
        "trade",
        "message",
        "msg",
        "tell",
        "say",
        "alias",
        "do",
        "talk",
        "form",
        "invite",
        "leave",
        "accept",
        "reject",
        "cancel",
    }
)

_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,23}$")

_VERBS: dict[str, tuple[str, str | None]] = {
    "look": ("LOOK", None),
    "l": ("LOOK", None),
    "observe": ("OBSERVE", None),
    "wait": ("WAIT", None),
    "enter": ("ENTER_WORLD", None),
    "move": ("MOVE", "direction"),
    "go": ("MOVE", "direction"),
    "walk": ("MOVE", "direction"),
    "inspect": ("INSPECT", "entity_id"),
    "examine": ("INSPECT", "entity_id"),
    "x": ("INSPECT", "entity_id"),
    "repair": ("REPAIR", "entity_id"),
    "harvest": ("HARVEST", "entity_id"),
    "trade": ("TRADE", None),
    "message": ("MESSAGE", None),
    "msg": ("MESSAGE", None),
    "tell": ("MESSAGE", None),
    "say": ("MESSAGE", None),
}

STOP_CODES = frozenset(
    {
        "AMBIGUOUS",
        "CLARIFY",
        "WORLD_BLOCKED",
        "NOT_AUTHORIZED",
        "AUTH_REQUIRED",
        "WORLD_INCIDENT",
        "WORLD_PAUSED",
        "SETTLEMENT_FAILURE",
    }
)


def is_reserved_alias_name(name: str) -> bool:
    return str(name or "").strip().lower() in RESERVED


@dataclass(frozen=True)
class ExpandResult:
    line: str
    error: str | None = None


@dataclass(frozen=True)
class AliasCommand:
    ok: bool
    op: str | None = None
    name: str | None = None
    expansion: str | None = None
    error: str | None = None


@dataclass
class AliasApply:
    aliases: dict[str, str]
    text: str


@dataclass(frozen=True)
class MacroSteps:
    steps: list[str] = field(default_factory=list)
    error: str | None = None


def expand_aliases(line: str, aliases: dict[str, str], depth: int = 0) -> ExpandResult:
    trimmed = str(line or "").strip()
    if not trimmed:
        return ExpandResult(line=trimmed)
    if depth > MAX_ALIAS_DEPTH:
        return ExpandResult(line=trimmed, error="Alias expansion is too deep.")
    parts = trimmed.split()
    head = (parts[0] or "").lower()
    rest = " ".join(parts[1:])
    expansion = aliases.get(head)
    if not expansion:
        return ExpandResult(line=trimmed)
    nxt = f"{expansion} {rest}".strip() if rest else expansion.strip()
    return expand_aliases(nxt, aliases, depth + 1)


def parse_alias_command(line: str) -> AliasCommand | None:
    trimmed = str(line or "").strip()
    match = re.match(r"^alias(?:\s+(.*))?$", trimmed, re.IGNORECASE)
    if not match:
        return None
    rest = (match.group(1) or "").strip()
    if not rest or rest.lower() == "list":
        return AliasCommand(ok=True, op="list")
    removed = re.match(r"^(?:rm|remove|unset)\s+(\S+)\s*$", rest, re.IGNORECASE)
    if removed:
        return AliasCommand(ok=True, op="rm", name=removed.group(1).lower())
    setting = re.match(r"^(?:set\s+)?(\S+)\s+(.+)$", rest, re.IGNORECASE)
    if setting:
        name = setting.group(1).lower()
        expansion = setting.group(2).strip()
        if is_reserved_alias_name(name):
            return AliasCommand(ok=False, error=f'"{name}" is a reserved command.')
        if not _NAME_RE.match(name):
            return AliasCommand(ok=False, error="Alias names are short letters.")
        if not expansion:
            return AliasCommand(ok=False, error="Alias needs an expansion.")
        return AliasCommand(ok=True, op="set", name=name, expansion=expansion)
    return AliasCommand(
        ok=False,
        error="Alias syntax: alias list | alias set <name> <command> | alias rm <name>",
    )


def apply_alias_command(aliases: dict[str, str], cmd: AliasCommand | None) -> AliasApply:
    nxt = dict(aliases)
    if cmd is None:
        return AliasApply(aliases=nxt, text="Alias syntax: alias list | alias set <name> <command> | alias rm <name>")
    if not cmd.ok:
        return AliasApply(aliases=nxt, text=cmd.error or "Alias rejected.")
    if cmd.op == "list":
        keys = sorted(nxt)
        if not keys:
            return AliasApply(aliases=nxt, text="No aliases.")
        return AliasApply(aliases=nxt, text="\n".join(f"{k} → {nxt[k]}" for k in keys))
    if cmd.op == "rm":
        name = cmd.name or ""
        nxt.pop(name, None)
        return AliasApply(aliases=nxt, text=f"Alias {name} removed.")
    name = cmd.name or ""
    expansion = cmd.expansion or ""
    if len(nxt) >= MAX_ALIASES and name not in nxt:
        return AliasApply(aliases=nxt, text=f"At most {MAX_ALIASES} aliases.")
    nxt[name] = expansion
    return AliasApply(aliases=nxt, text=f"Alias {name} → {expansion}")


def split_macro_steps(line: str) -> list[str]:
    return [part.strip() for part in str(line or "").split(";") if part.strip()]


def macro_steps_from_line(line: str) -> MacroSteps:
    body = str(line or "").strip()
    do_match = re.match(r"^do\s+(.+)$", body, re.IGNORECASE)
    if do_match:
        body = do_match.group(1).strip()
    steps = split_macro_steps(body)
    if len(steps) > MAX_MACRO_STEPS:
        return MacroSteps(steps=[], error=f"Macros are at most {MAX_MACRO_STEPS} steps.")
    if any(re.match(r"^do\b", step, re.IGNORECASE) for step in steps):
        return MacroSteps(steps=[], error="Macros cannot nest.")
    return MacroSteps(steps=steps)


def proposal_from_line(line: str) -> ActionProposal | None:
    parts = str(line or "").split()
    if not parts:
        return None
    mapped = _VERBS.get(parts[0].lower())
    if not mapped:
        return None
    action, arg_key = mapped
    rest = parts[1:]
    target = rest[0] if rest else None
    arguments: dict[str, Any] = {}
    if action == "MESSAGE" and rest:
        arguments["text"] = " ".join(rest)
        return ActionProposal(action=action, arguments=arguments)
    if arg_key and target:
        arguments[arg_key] = target
    target_id = target if arg_key == "entity_id" else None
    return ActionProposal(action=action, target_id=target_id, arguments=arguments)


def expand_proposal(proposal: ActionProposal, aliases: dict[str, str]) -> ActionProposal:
    if not aliases:
        return proposal
    head = (proposal.action or "").strip().lower()
    if not head or head not in aliases:
        return proposal
    rest: list[str] = []
    if proposal.target_id:
        rest.append(str(proposal.target_id))
    elif isinstance(proposal.arguments, dict):
        for key in ("direction", "entity_id"):
            value = proposal.arguments.get(key)
            if value:
                rest.append(str(value))
                break
    line = f"{head} {' '.join(rest)}".strip() if rest else head
    expanded = expand_aliases(line, aliases)
    if expanded.error:
        raise NoemaActionRejected("ALIAS_TOO_DEEP", expanded.error, failure=FailureClass.INVALID_PROPOSAL)
    parsed = proposal_from_line(expanded.line)
    if parsed is None:
        raise NoemaActionRejected(
            "INVALID_PROPOSAL",
            f"alias expanded to unknown command {expanded.line!r}",
            failure=FailureClass.INVALID_PROPOSAL,
        )
    arguments = dict(proposal.arguments or {})
    arguments.update(parsed.arguments or {})
    return ActionProposal(
        action=parsed.action,
        target_id=parsed.target_id or proposal.target_id,
        arguments=arguments,
        reason_summary=proposal.reason_summary,
    )


def should_stop_macro(result_ok: bool, failure: FailureClass | None, error: dict[str, Any] | None) -> bool:
    if not result_ok:
        return True
    if failure in {
        FailureClass.AUTH_REQUIRED,
        FailureClass.WORLD_INCIDENT,
        FailureClass.WORLD_PAUSED,
        FailureClass.ACTION_REJECTED,
        FailureClass.SETTLEMENT_FAILURE,
    }:
        return True
    code = str((error or {}).get("code") or "").upper()
    return code in STOP_CODES
