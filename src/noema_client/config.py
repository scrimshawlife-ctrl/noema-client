"""Local Controller config. No Admin secrets.

Unix default: ~/.config/noema/  mode 0600.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_SERVER = "https://noema.guru"


def config_dir() -> Path:
    override = os.environ.get("NOEMA_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "noema"
    return Path.home() / ".config" / "noema"


@dataclass
class StoredCredential:
    access_token: str
    player_id: str | None = None
    controller_id: str | None = None
    controller_type: str | None = "agent"
    server: str = DEFAULT_SERVER
    world_id: str | None = None
    protocol: str = "agent-protocol/v1"
    resume_token: str | None = None

    def __repr__(self) -> str:
        return "StoredCredential(<redacted>)"


def _private_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    os.replace(tmp, path)


def credential_path(directory: Path | None = None) -> Path:
    return (directory or config_dir()) / "credential.json"


def config_path(directory: Path | None = None) -> Path:
    return (directory or config_dir()) / "config.toml"


def aliases_path(directory: Path | None = None) -> Path:
    return (directory or config_dir()) / "aliases.json"


def load_aliases(directory: Path | None = None) -> dict[str, str]:
    path = aliases_path(directory)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in data.items():
        if isinstance(key, str) and isinstance(value, str) and key.strip():
            out[key.strip().lower()] = value.strip()
    return out


def save_aliases(aliases: dict[str, str], directory: Path | None = None) -> Path:
    path = aliases_path(directory)
    payload = {str(key).lower(): str(value) for key, value in aliases.items()}
    _private_write(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def load_credential(directory: Path | None = None) -> StoredCredential | None:
    env_token = os.environ.get("NOEMA_TOKEN")
    server = os.environ.get("NOEMA_SERVER") or DEFAULT_SERVER
    path = credential_path(directory)
    data: dict = {}
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
    token = env_token or data.get("access_token")
    if not token:
        return None
    return StoredCredential(
        access_token=str(token),
        player_id=data.get("player_id"),
        controller_id=data.get("controller_id"),
        controller_type=data.get("controller_type") or "agent",
        server=str(data.get("server") or server),
        world_id=data.get("world_id"),
        protocol=str(data.get("protocol") or "agent-protocol/v1"),
        resume_token=data.get("resume_token"),
    )


def save_credential(cred: StoredCredential, directory: Path | None = None) -> Path:
    path = credential_path(directory)
    payload = asdict(cred)
    _private_write(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def clear_credential(directory: Path | None = None) -> None:
    path = credential_path(directory)
    if path.is_file():
        path.unlink()


def load_server(directory: Path | None = None) -> str:
    env = os.environ.get("NOEMA_SERVER")
    if env:
        return env.rstrip("/")
    path = config_path(directory)
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("server"):
                _, _, value = line.partition("=")
                return value.strip().strip('"').rstrip("/")
    cred = load_credential(directory)
    if cred:
        return cred.server.rstrip("/")
    return DEFAULT_SERVER


def save_server(server: str, directory: Path | None = None) -> Path:
    path = config_path(directory)
    _private_write(path, f'server = "{server.rstrip("/")}"\n')
    return path
