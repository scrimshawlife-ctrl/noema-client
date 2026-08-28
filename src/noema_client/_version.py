"""The package version, sourced from package metadata configuration."""

from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as installed_version
from pathlib import Path


def _source_version() -> str | None:
    """Read the canonical version while running directly from a source checkout."""
    for parent in Path(__file__).resolve().parents:
        metadata = parent / "pyproject.toml"
        if metadata.is_file():
            with metadata.open("rb") as stream:
                project = tomllib.load(stream).get("project", {})
            value = project.get("version")
            if isinstance(value, str) and value:
                return value
    return None


__version__ = _source_version()
if __version__ is None:
    try:
        __version__ = installed_version("noema-client")
    except PackageNotFoundError:
        __version__ = "0+unknown"
