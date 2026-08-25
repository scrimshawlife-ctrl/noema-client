from __future__ import annotations

from pathlib import Path

from noema_client.cli import main

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_connect_docs_cover_one_click_boundaries_and_fallback() -> None:
    docs = "\n".join(
        [
            read("README.md"),
            read("docs/CLI.md"),
            read("skills/noema/SKILL.md"),
            read("skills/noema/references/security.md"),
            read("skills/noema/references/troubleshooting.md"),
            read("skills/noema/references/protocol.md"),
        ]
    )

    required = [
        "noema connect --email owner@example.com",
        "--no-enter",
        "ENTER_WORLD",
        "human approval",
        "plain code fallback",
        "denied",
        "expired",
        "retry",
        "owner_email",
        "passwords",
        "Admin tokens",
    ]
    for phrase in required:
        assert phrase in docs


def test_connect_help_matches_documented_flags(capsys) -> None:
    rc = main(["connect", "--help"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "--email EMAIL" in out
    assert "--no-enter" in out
    assert "plain" in out
    assert "fallback" in out
    assert "automatic ENTER_WORLD/orientation" in out
    assert "owner" in out

    cli_doc = read("docs/CLI.md")
    for phrase in ["--email EMAIL", "--no-enter", "plain code fallback"]:
        assert phrase in cli_doc
